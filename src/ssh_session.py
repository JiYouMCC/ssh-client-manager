"""
SSH session management with asyncio WebSocket bridge.

Each SSHSession:
  1. Opens a paramiko SSH connection (password / key / passphrase auth)
  2. Requests an interactive PTY channel
  3. Starts a local asyncio WebSocket server on a random port
  4. Bridges data between xterm.js (WebSocket) and the SSH channel

Local shell sessions use a subprocess with winpty (Windows) or pty (Unix).
"""

import asyncio
import json
import os
import platform
import queue
import shutil
import socket
import subprocess
import sys
import threading
from typing import Optional

import paramiko
import websockets
import websockets.server


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class BaseSession:
    """
    Abstract base for SSH and local shell sessions.

    Subclasses implement _start_io() which sets up the I/O loop between
    the WebSocket client and the underlying process/channel.
    """

    def __init__(self):
        self.port: int = _find_free_port()
        self._ws_server = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ws_client: Optional[websockets.server.WebSocketServerProtocol] = None
        self._running = False
        # Signals (set by owner)
        self.on_title_changed = None   # callback(title: str)
        self.on_disconnected = None    # callback()
        # Logging / recording (set by owner after construction)
        self.log_file_path: Optional[str] = None
        self.recording_file_path: Optional[str] = None
        self._log_fh = None
        self._rec_fh = None
        self._rec_start: Optional[float] = None

    def _open_output_files(self, cols: int = 220, rows: int = 50):
        """Open log and/or recording files for writing."""
        import time as _time
        if self.log_file_path:
            try:
                import pathlib
                pathlib.Path(self.log_file_path).parent.mkdir(parents=True, exist_ok=True)
                self._log_fh = open(self.log_file_path, "a", encoding="utf-8", errors="replace")
            except Exception as e:
                print(f"[session] Cannot open log file: {e}")

        if self.recording_file_path:
            try:
                import pathlib, json as _json
                pathlib.Path(self.recording_file_path).parent.mkdir(parents=True, exist_ok=True)
                self._rec_fh = open(self.recording_file_path, "w", encoding="utf-8")
                self._rec_start = _time.time()
                header = _json.dumps({
                    "version": 2, "width": cols, "height": rows,
                    "timestamp": int(self._rec_start), "title": ""
                })
                self._rec_fh.write(header + "\n")
                self._rec_fh.flush()
            except Exception as e:
                print(f"[session] Cannot open recording file: {e}")

    def _write_output(self, data: bytes):
        """Write output data to log and recording files."""
        import time as _time, json as _json
        text = data.decode("utf-8", errors="replace")
        if self._log_fh:
            try:
                self._log_fh.write(text)
                self._log_fh.flush()
            except Exception:
                pass
        if self._rec_fh and self._rec_start is not None:
            try:
                ts = round(_time.time() - self._rec_start, 6)
                event = _json.dumps([ts, "o", text])
                self._rec_fh.write(event + "\n")
                self._rec_fh.flush()
            except Exception:
                pass

    def _close_output_files(self):
        if self._log_fh:
            try:
                self._log_fh.close()
            except Exception:
                pass
            self._log_fh = None
        if self._rec_fh:
            try:
                self._rec_fh.close()
            except Exception:
                pass
            self._rec_fh = None

    def start_recording(self, file_path: str, cols: int = 220, rows: int = 50):
        """Open a new recording file mid-session (asciicast v2)."""
        import time as _time, json as _json, pathlib
        # Close any existing recording first
        self.stop_recording()
        self.recording_file_path = file_path
        try:
            pathlib.Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            self._rec_fh = open(file_path, "w", encoding="utf-8")
            self._rec_start = _time.time()
            header = _json.dumps({
                "version": 2, "width": cols, "height": rows,
                "timestamp": int(self._rec_start), "title": "",
            })
            self._rec_fh.write(header + "\n")
            self._rec_fh.flush()
        except Exception as e:
            print(f"[session] Cannot open recording file: {e}")
            self._rec_fh = None
            self._rec_start = None
            self.recording_file_path = None

    def stop_recording(self):
        """Close the current recording file."""
        if self._rec_fh:
            try:
                self._rec_fh.close()
            except Exception:
                pass
            self._rec_fh = None
        self._rec_start = None
        self.recording_file_path = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        """Start the WebSocket server in a background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Shut down the session."""
        self._running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

    def send_input(self, data: str):
        """Send input text to the session (called from main thread)."""
        if self._loop and self._loop.is_running() and self._ws_client:
            asyncio.run_coroutine_threadsafe(
                self._ws_client.send(data), self._loop
            )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_event_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception:
            pass
        finally:
            self._loop.close()

    async def _serve(self):
        async with websockets.serve(self._handle_ws, "127.0.0.1", self.port):
            await asyncio.sleep(3600 * 24)  # keep server alive

    async def _handle_ws(self, websocket):
        self._ws_client = websocket
        self._open_output_files()
        try:
            await self._start_io(websocket)
        finally:
            self._ws_client = None
            self._close_output_files()
            if self.on_disconnected:
                self.on_disconnected()

    async def _start_io(self, websocket):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# SSH Session (paramiko)
# ---------------------------------------------------------------------------

class SSHSession(BaseSession):
    """
    SSH session using paramiko.

    Auth order: key file (with optional passphrase) → password → interactive
    """

    def __init__(
        self,
        hostname: str,
        port: int = 22,
        username: str = "",
        password: str = "",
        key_file: str = "",
        passphrase1: str = "",
        passphrase2: str = "",
        timeout: int = 30,
        keepalive: int = 60,
        term_type: str = "xterm-256color",
        tunnels: Optional[list] = None,
    ):
        super().__init__()
        self.hostname = hostname
        self.ssh_port = port
        self.username = username
        self.password = password
        self.key_file = key_file
        self.passphrase1 = passphrase1
        self.passphrase2 = passphrase2
        self.timeout = timeout
        self.keepalive = keepalive
        self.term_type = term_type or "xterm-256color"
        self._tunnels = tunnels or []

        self._transport: Optional[paramiko.Transport] = None
        self._channel: Optional[paramiko.Channel] = None
        self._tunnel_servers: list = []   # asyncio.Server handles (local/SOCKS)
        self._tunnel_tasks: list = []     # asyncio.Task handles (remote forward)

    def _connect(self):
        """Establish the paramiko transport + auth (blocking)."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = dict(
            hostname=self.hostname,
            port=self.ssh_port,
            username=self.username,
            timeout=self.timeout,
            look_for_keys=False,
            allow_agent=False,
        )

        # Try key auth first
        if self.key_file and os.path.exists(self.key_file):
            for passphrase in [self.passphrase1 or None, self.passphrase2 or None]:
                try:
                    connect_kwargs["key_filename"] = self.key_file
                    connect_kwargs["passphrase"] = passphrase
                    client.connect(**connect_kwargs)
                    break
                except (paramiko.ssh_exception.AuthenticationException,
                        paramiko.ssh_exception.SSHException):
                    continue
            else:
                # Fall through to password auth
                connect_kwargs.pop("key_filename", None)
                connect_kwargs.pop("passphrase", None)

        if not client.get_transport() or not client.get_transport().is_authenticated():
            # Password auth
            connect_kwargs["password"] = self.password or None
            connect_kwargs.pop("key_filename", None)
            connect_kwargs.pop("passphrase", None)
            client.connect(**connect_kwargs)

        transport = client.get_transport()
        transport.set_keepalive(self.keepalive)

        self._transport = transport
        return client

    async def _start_io(self, websocket):
        # Connect in a thread pool (blocking I/O)
        loop = asyncio.get_event_loop()
        try:
            client = await loop.run_in_executor(None, self._connect)
        except Exception as e:
            await websocket.send(
                f"\r\n\x1b[31mConnection failed: {e}\x1b[0m\r\n"
            )
            return

        # Set up port-forwarding tunnels before opening the shell
        await self._setup_tunnels()

        # Open interactive shell channel
        channel = client.invoke_shell(
            term=self.term_type,
            width=220,
            height=50,
        )
        channel.setblocking(False)
        self._channel = channel

        await self._bridge(websocket, channel)
        channel.close()
        client.close()

        # Clean up tunnel servers/tasks
        for srv in self._tunnel_servers:
            srv.close()
        for task in self._tunnel_tasks:
            task.cancel()

    # ------------------------------------------------------------------
    # Tunnel setup
    # ------------------------------------------------------------------

    async def _setup_tunnels(self):
        """Set up all configured port-forwarding rules after SSH is connected."""
        for t in self._tunnels:
            ttype = t.get("type")
            try:
                if ttype == "L":
                    srv = await self._start_local_forward(
                        t["local_port"], t["remote_host"], t["remote_port"]
                    )
                    self._tunnel_servers.append(srv)
                elif ttype == "R":
                    task = asyncio.create_task(
                        self._start_remote_forward(
                            t["local_port"], t["remote_host"], t["remote_port"]
                        )
                    )
                    self._tunnel_tasks.append(task)
                elif ttype == "D":
                    srv = await self._start_socks_proxy(t["local_port"])
                    self._tunnel_servers.append(srv)
            except Exception as e:
                # Non-fatal: log to stderr but don't abort the shell
                print(f"[tunnel] Failed to set up -{ttype} {t}: {e}", flush=True)

    # --- Local forwarding (-L local_port:remote_host:remote_port) ----------

    async def _start_local_forward(self, local_port: int, remote_host: str,
                                    remote_port: int) -> asyncio.Server:
        transport = self._transport

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            peer = writer.get_extra_info("peername") or ("127.0.0.1", 0)
            loop = asyncio.get_event_loop()
            try:
                channel = await loop.run_in_executor(
                    None,
                    lambda: transport.open_channel(
                        "direct-tcpip", (remote_host, remote_port), peer
                    ),
                )
            except Exception as e:
                writer.close()
                return

            channel.setblocking(False)
            await self._bridge_stream(reader, writer, channel)
            channel.close()
            writer.close()

        return await asyncio.start_server(handle, "127.0.0.1", local_port)

    # --- Remote forwarding (-R remote_port:local_host:local_port) ----------

    async def _start_remote_forward(self, remote_port: int, local_host: str,
                                     local_port: int):
        transport = self._transport
        loop = asyncio.get_event_loop()

        # Ask the server to forward remote_port back to us
        await loop.run_in_executor(
            None,
            lambda: transport.request_port_forward("", remote_port),
        )

        while self._running:
            channel = await loop.run_in_executor(
                None, lambda: transport.accept(timeout=1)
            )
            if channel is None:
                continue
            asyncio.create_task(
                self._forward_channel_to_local(channel, local_host, local_port)
            )

    async def _forward_channel_to_local(self, channel, local_host: str,
                                         local_port: int):
        try:
            reader, writer = await asyncio.open_connection(local_host, local_port)
        except Exception:
            channel.close()
            return
        channel.setblocking(False)
        await self._bridge_stream(reader, writer, channel)
        channel.close()
        writer.close()

    # --- SOCKS5 dynamic proxy (-D local_port) ------------------------------

    async def _start_socks_proxy(self, local_port: int) -> asyncio.Server:
        transport = self._transport

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            try:
                await self._handle_socks5(reader, writer, transport)
            except Exception:
                pass
            finally:
                writer.close()

        return await asyncio.start_server(handle, "127.0.0.1", local_port)

    async def _handle_socks5(self, reader: asyncio.StreamReader,
                              writer: asyncio.StreamWriter,
                              transport: paramiko.Transport):
        # Auth negotiation: VER NMETHODS METHODS
        header = await reader.readexactly(2)
        n_methods = header[1]
        await reader.readexactly(n_methods)
        writer.write(b"\x05\x00")   # no auth required
        await writer.drain()

        # Connection request: VER CMD RSV ATYP ...
        req = await reader.readexactly(4)
        if req[1] != 0x01:          # only CONNECT supported
            writer.write(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
            return

        atyp = req[3]
        if atyp == 0x01:            # IPv4
            addr = ".".join(str(b) for b in await reader.readexactly(4))
        elif atyp == 0x03:          # domain name
            n = (await reader.readexactly(1))[0]
            addr = (await reader.readexactly(n)).decode()
        else:
            writer.write(b"\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00")
            return

        port_bytes = await reader.readexactly(2)
        port = int.from_bytes(port_bytes, "big")

        # Open SSH channel to destination
        peer = writer.get_extra_info("peername") or ("127.0.0.1", 0)
        loop = asyncio.get_event_loop()
        try:
            channel = await loop.run_in_executor(
                None,
                lambda: transport.open_channel("direct-tcpip", (addr, port), peer),
            )
        except Exception:
            writer.write(b"\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00")
            return

        # Success response
        writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        await writer.drain()

        channel.setblocking(False)
        await self._bridge_stream(reader, writer, channel)
        channel.close()

    # --- Generic stream ↔ paramiko-channel bridge -------------------------

    async def _bridge_stream(self, reader: asyncio.StreamReader,
                              writer: asyncio.StreamWriter,
                              channel: paramiko.Channel):
        """Bridge asyncio stream ↔ paramiko channel until either side closes."""
        loop = asyncio.get_event_loop()

        async def ch_to_stream():
            while self._running and not channel.closed:
                data = await loop.run_in_executor(None, self._recv_channel, channel)
                if not data:
                    break
                writer.write(data)
                await writer.drain()

        async def stream_to_ch():
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                channel.sendall(data)

        await asyncio.gather(ch_to_stream(), stream_to_ch(), return_exceptions=True)

    def _recv_channel(self, channel: paramiko.Channel) -> Optional[bytes]:
        """Blocking recv from paramiko channel (for use in executor)."""
        import time
        while self._running and not channel.closed:
            if channel.recv_ready():
                return channel.recv(4096)
            if channel.exit_status_ready():
                return None
            time.sleep(0.005)
        return None

    async def _bridge(self, websocket, channel):
        """Bidirectional bridge between WebSocket and paramiko channel."""
        loop = asyncio.get_event_loop()

        async def ssh_to_ws():
            while self._running:
                try:
                    data = await loop.run_in_executor(None, self._read_channel, channel)
                    if data is None:
                        break
                    if data:
                        self._write_output(data)
                        await websocket.send(bytes(data))
                except Exception:
                    break

        async def ws_to_ssh():
            async for message in websocket:
                if isinstance(message, str):
                    try:
                        msg = json.loads(message)
                        if msg.get("type") == "resize":
                            cols = msg.get("cols", 80)
                            rows = msg.get("rows", 24)
                            channel.resize_pty(width=cols, height=rows)
                    except (json.JSONDecodeError, Exception):
                        channel.send(message.encode("utf-8", errors="replace"))
                else:
                    channel.send(message)

        await asyncio.gather(ssh_to_ws(), ws_to_ssh(), return_exceptions=True)

    def _read_channel(self, channel) -> Optional[bytes]:
        """Blocking read from paramiko channel; returns None on EOF."""
        import time
        while self._running:
            if channel.closed or channel.exit_status_ready():
                return None
            if channel.recv_ready():
                return channel.recv(4096)
            if channel.recv_stderr_ready():
                return channel.recv_stderr(4096)
            time.sleep(0.01)
        return None


# ---------------------------------------------------------------------------
# Local Shell Session (subprocess)
# ---------------------------------------------------------------------------

class LocalShellSession(BaseSession):
    """
    Local interactive shell session.

    Windows: PowerShell → cmd.exe fallback (or explicit preference)
    Unix: $SHELL → /bin/bash fallback
    """

    def __init__(self, term_type: str = "xterm-256color", shell_preference: str = "auto"):
        super().__init__()
        self.term_type = term_type
        self._shell_preference = shell_preference

    def _get_shell_cmd(self) -> list[str]:
        if platform.system() == "Windows":
            pref = self._shell_preference
            if pref == "cmd":
                return ["cmd.exe"]
            if pref == "powershell":
                ps = shutil.which("pwsh") or shutil.which("powershell")
                return [ps, "-NoLogo"] if ps else ["cmd.exe"]
            # auto: prefer pwsh/powershell, fall back to cmd
            ps = shutil.which("pwsh") or shutil.which("powershell")
            if ps:
                return [ps, "-NoLogo"]
            return ["cmd.exe"]
        shell = os.environ.get("SHELL", "/bin/bash")
        return [shell]

    async def _start_io(self, websocket):
        cmd = self._get_shell_cmd()
        env = os.environ.copy()
        env["TERM"] = self.term_type

        if platform.system() == "Windows":
            await self._start_io_windows(websocket, cmd, env)
        else:
            await self._start_io_unix(websocket, cmd, env)

    async def _start_io_windows(self, websocket, cmd, env):
        """Windows local shell via ConPTY (pywinpty). Falls back to pipe on import error."""
        try:
            import winpty as _winpty
        except ImportError:
            await websocket.send(
                "\r\n\x1b[31mpywinpty is not installed. "
                "Run: pip install pywinpty\x1b[0m\r\n"
            )
            return

        try:
            pty_proc = _winpty.PtyProcess.spawn(cmd, dimensions=(24, 80), env=env)
        except Exception as e:
            await websocket.send(
                f"\r\n\x1b[31mFailed to start shell: {e}\x1b[0m\r\n"
            )
            return

        loop = asyncio.get_event_loop()

        async def pty_to_ws():
            while self._running:
                try:
                    data = await loop.run_in_executor(None, lambda: pty_proc.read(4096))
                    if data:
                        encoded = data.encode("utf-8", errors="replace")
                        self._write_output(encoded)
                        await websocket.send(bytes(encoded))
                except EOFError:
                    break
                except Exception:
                    break

        async def ws_to_pty():
            async for message in websocket:
                if isinstance(message, str):
                    try:
                        msg = json.loads(message)
                        if msg.get("type") == "resize":
                            cols = msg.get("cols", 80)
                            rows = msg.get("rows", 24)
                            pty_proc.setwinsize(rows, cols)
                    except Exception:
                        pty_proc.write(message)
                else:
                    pty_proc.write(message.decode("utf-8", errors="replace"))

        await asyncio.gather(pty_to_ws(), ws_to_pty(), return_exceptions=True)
        try:
            pty_proc.terminate(force=True)
        except Exception:
            pass

    async def _start_io_unix(self, websocket, cmd, env):
        """Unix local shell via PTY."""
        try:
            import pty
            master, slave = pty.openpty()
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                env=env,
                close_fds=True,
            )
            os.close(slave)
        except Exception as e:
            await websocket.send(
                f"\r\n\x1b[31mFailed to start shell: {e}\x1b[0m\r\n"
            )
            return

        async def pty_to_ws():
            loop = asyncio.get_event_loop()
            while self._running:
                try:
                    data = await loop.run_in_executor(
                        None, lambda: os.read(master, 4096)
                    )
                    if data:
                        self._write_output(data)
                        await websocket.send(bytes(data))
                except OSError:
                    break

        async def ws_to_pty():
            async for message in websocket:
                if isinstance(message, str):
                    try:
                        msg = json.loads(message)
                        if msg.get("type") == "resize":
                            import fcntl, termios, struct
                            cols = msg.get("cols", 80)
                            rows = msg.get("rows", 24)
                            fcntl.ioctl(
                                master, termios.TIOCSWINSZ,
                                struct.pack("HHHH", rows, cols, 0, 0)
                            )
                    except Exception:
                        os.write(master, message.encode("utf-8", errors="replace"))
                else:
                    os.write(master, message)

        await asyncio.gather(pty_to_ws(), ws_to_pty(), return_exceptions=True)
        os.close(master)

