# SSH Client Manager

A desktop SSH client manager built with **Python 3 + PySide6 + xterm.js**.

This repository is currently the **Windows / PySide6 edition** (not GTK/libadwaita).

## Implemented Features

- SSH terminal tabs with horizontal/vertical split panes
- Local shell tabs (PowerShell/cmd on Windows)
- Connection groups, favorites, tags, import/export
- Secure credential storage via Fernet encryption (`credentials.dat`)
- SSH auth through Paramiko (password/key/passphrase)
- Port forwarding (`-L`, `-R`, `-D`) and post-login commands
- SFTP browser, session recording (`.cast`), and terminal screenshots
- Optional terminal auto-logging
- Manual reconnect bar and configurable auto-reconnect

## Requirements (Windows)

Install dependencies:

```bash
pip install -r requirements-windows.txt
```

Run:

```bash
python run.py
```

Debug mode:

```bash
python run.py --debug
```

## Configuration

Main files:

- `~/.config/ssh-client-manager/config.json`
- `~/.config/ssh-client-manager/connections.json`
- `~/.config/ssh-client-manager/credentials.dat`
- `~/.config/ssh-client-manager/.store.key`

Anti-disconnect options in `config.json`:

- `ssh_keepalive_interval`: SSH keepalive heartbeat interval in seconds (`0` disables).
- `ssh_connection_timeout`: SSH connection timeout in seconds.
- `ssh_auto_reconnect`: Enable automatic reconnect when an SSH tab disconnects unexpectedly.
- `ssh_auto_reconnect_delay`: Delay between reconnect attempts in seconds.
- `ssh_auto_reconnect_max_retries`: Maximum automatic reconnect attempts per disconnect event.

## Notes

- This project currently supports SSH workflows (and SFTP over SSH).  
- AI assistant, RDP, and VNC are **not implemented** in the current codebase.

## License

GPL-3.0
