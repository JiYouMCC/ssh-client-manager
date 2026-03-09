"""
SSH connection parameter parsing and session factory.

Credentials are handled by paramiko directly (no bash scripts, no SSH_ASKPASS).
Session objects (SSHSession / LocalShellSession) manage the actual I/O.
"""

import os
import platform
import shlex
import shutil
from typing import Optional

from .connection import Connection
from .credential_store import CredentialStore
from .ssh_session import SSHSession, LocalShellSession


class SSHHandler:
    """
    Parses SSH connection parameters and creates session objects.
    """

    def __init__(self, credential_store: CredentialStore):
        self._cred_store = credential_store

    # ------------------------------------------------------------------
    # Session factory
    # ------------------------------------------------------------------

    def create_session(self, connection: Connection) -> SSHSession:
        """
        Build an SSHSession from a Connection, injecting stored credentials.
        """
        params = self._parse_ssh_params(connection)

        return SSHSession(
            hostname=params["hostname"],
            port=params["port"],
            username=params["username"],
            password=self._cred_store.get_password(connection.id) or "",
            key_file=params["key_file"],
            passphrase1=self._cred_store.get_passphrase1(connection.id) or "",
            passphrase2=self._cred_store.get_passphrase2(connection.id) or "",
            term_type=connection.term_type or "xterm-256color",
            tunnels=params["tunnels"],
        )

    def create_local_session(self) -> LocalShellSession:
        """Create a local shell session."""
        return LocalShellSession()

    # ------------------------------------------------------------------
    # Command parsing
    # ------------------------------------------------------------------

    def build_ssh_command(self, connection: Connection) -> list[str]:
        """
        Parse the raw command string into argv (kept for display / advanced use).
        """
        if not connection.command:
            return ["ssh"]
        cmd_str = " ".join(connection.command.strip().splitlines())
        try:
            return shlex.split(cmd_str)
        except ValueError:
            return cmd_str.split()

    def _parse_ssh_params(self, connection: Connection) -> dict:
        """
        Extract hostname, port, username, key file and port-forwarding rules
        from the command string.

        Supports common ssh flags:
          -p PORT   -i IDENTITY_FILE   -L [local_port:remote_host:remote_port]
          -R [remote_port:local_host:local_port]   -D [local_port]
          user@host   host
        """
        argv = self.build_ssh_command(connection)

        params = {
            "hostname": "",
            "port": 22,
            "username": "",
            "key_file": "",
            "tunnels": [],   # list of dicts: {type, local_port, remote_host, remote_port}
        }

        i = 1  # skip "ssh"
        positional = []
        while i < len(argv):
            arg = argv[i]
            if arg in ("-p",) and i + 1 < len(argv):
                try:
                    params["port"] = int(argv[i + 1])
                except ValueError:
                    pass
                i += 2
            elif arg in ("-i",) and i + 1 < len(argv):
                params["key_file"] = argv[i + 1]
                i += 2
            elif arg in ("-l",) and i + 1 < len(argv):
                params["username"] = argv[i + 1]
                i += 2
            elif arg == "-L" and i + 1 < len(argv):
                t = self._parse_forward_spec("L", argv[i + 1])
                if t:
                    params["tunnels"].append(t)
                i += 2
            elif arg == "-R" and i + 1 < len(argv):
                t = self._parse_forward_spec("R", argv[i + 1])
                if t:
                    params["tunnels"].append(t)
                i += 2
            elif arg == "-D" and i + 1 < len(argv):
                try:
                    params["tunnels"].append({
                        "type": "D",
                        "local_port": int(argv[i + 1]),
                        "remote_host": "",
                        "remote_port": 0,
                    })
                except ValueError:
                    pass
                i += 2
            elif arg.startswith("-"):
                # Skip other flags with values (single char flags that take a value)
                if len(arg) == 2 and arg[1] in "bceFIJmOoQSw" and i + 1 < len(argv):
                    i += 2
                else:
                    i += 1
            else:
                positional.append(arg)
                i += 1

        # Last positional is [user@]host
        if positional:
            dest = positional[-1]
            if "@" in dest:
                params["username"], params["hostname"] = dest.rsplit("@", 1)
            else:
                params["hostname"] = dest

        return params

    @staticmethod
    def _parse_forward_spec(ttype: str, spec: str) -> Optional[dict]:
        """
        Parse a port-forward spec string: [bind_addr:]port:host:hostport
        Returns None if the spec is malformed.
        """
        parts = spec.split(":")
        try:
            if ttype == "L":
                # local_port:remote_host:remote_port
                # or bind_addr:local_port:remote_host:remote_port
                if len(parts) == 3:
                    return {"type": "L", "local_port": int(parts[0]),
                            "remote_host": parts[1], "remote_port": int(parts[2])}
                if len(parts) == 4:
                    return {"type": "L", "local_port": int(parts[1]),
                            "remote_host": parts[2], "remote_port": int(parts[3])}
            elif ttype == "R":
                if len(parts) == 3:
                    return {"type": "R", "local_port": int(parts[0]),
                            "remote_host": parts[1], "remote_port": int(parts[2])}
                if len(parts) == 4:
                    return {"type": "R", "local_port": int(parts[1]),
                            "remote_host": parts[2], "remote_port": int(parts[3])}
        except (ValueError, IndexError):
            pass
        return None

    # ------------------------------------------------------------------
    # Post-login commands
    # ------------------------------------------------------------------

    def get_post_login_commands(self, connection: Connection) -> list[str]:
        """
        Parse post-login commands. Supports ##D=<ms> delay markers.
        Returns list of command strings (delay markers preserved as-is).
        """
        if not connection.commands:
            return []
        return [
            line.strip()
            for line in connection.commands.strip().split("\n")
            if line.strip()
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def get_local_shell_command() -> list[str]:
        """Get the local shell command for the current OS."""
        if platform.system() == "Windows":
            ps = shutil.which("pwsh") or shutil.which("powershell")
            return [ps, "-NoLogo"] if ps else ["cmd.exe"]
        return [os.environ.get("SHELL", "/bin/bash")]
