# Windows Packaging — SSH Client Manager

This document explains how to build a self-contained **SSHClientManager.exe** using
PyInstaller and distribute it as a **ZIP archive** for Windows 10 / 11.

No Python installation is required on the end-user's machine — everything is bundled.

---

## Files

| File | Purpose |
|------|---------|
| `pyinstaller.ps1` | Top-level build script — run this to produce the `.exe` and `.zip` |
| `ssh-client-manager.spec` | PyInstaller spec: declares all modules and assets to bundle |
| `requirements-windows.txt` | Python dependencies for the Windows build |

---

## Prerequisites

Only needed on the **developer / build machine**. End-users receive the ZIP and run
the `.exe` directly.

### 1 — Install Python 3.11+

Download from <https://python.org/downloads/windows/> and install.  
Make sure **"Add Python to PATH"** is checked during setup.

Verify:

```powershell
python --version
```

### 2 — (Optional) Allow PowerShell scripts

If you have never run a `.ps1` script on this machine, allow it for the current user:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

---

## Building

Run from the **project root** directory in PowerShell:

```powershell
.\pyinstaller.ps1
```

The script will:

1. Check that `ssh-client-manager.spec` is present in the current directory
2. Create an isolated virtual environment at `.venv-build\` (first run only)
3. Install `PyInstaller` and all project Python dependencies from `requirements-windows.txt`
4. Run `pyinstaller --clean --noconfirm ssh-client-manager.spec`
5. Produce `dist\SSHClientManager\SSHClientManager.exe`
6. Create `dist\SSHClientManager-Windows-{VERSION}.zip` ready for distribution

### Manual PyInstaller invocation

```powershell
.venv-build\Scripts\activate
python -m PyInstaller --clean --noconfirm ssh-client-manager.spec
```

---

## Output

| Path | Description |
|------|-------------|
| `dist\SSHClientManager\` | Self-contained application folder |
| `dist\SSHClientManager\SSHClientManager.exe` | Main executable |
| `dist\SSHClientManager-Windows-*.zip` | Distributable ZIP archive |

To distribute: share the **ZIP file**. Users extract it and double-click
`SSHClientManager.exe` — no installer needed.

### Test the build

```powershell
dist\SSHClientManager\SSHClientManager.exe
```

---

## Adding an App Icon

Place a `.ico` file at `packaging\windows\sshclientmanager.ico`, then reference it
in `ssh-client-manager.spec`:

```python
exe = EXE(
    ...
    icon="packaging\\windows\\sshclientmanager.ico",
)
```

### Create a `.ico` from a PNG

Using ImageMagick (install via `winget install ImageMagick.ImageMagick`):

```powershell
magick icon.png -define icon:auto-resize="256,128,64,48,32,16" packaging\windows\sshclientmanager.ico
```

---

## Troubleshooting

### App fails to start (no window, no error)

Run from a terminal to see console output:

```powershell
dist\SSHClientManager\SSHClientManager.exe
```

Or temporarily enable a console window by setting `console=True` in the `EXE` block
of `ssh-client-manager.spec`, rebuild, and inspect the output.

### `ModuleNotFoundError` at runtime

Add the missing module to `hiddenimports` in `ssh-client-manager.spec` and rebuild.

### Antivirus false positive

PyInstaller-built executables are occasionally flagged by antivirus software.
This is a known false-positive. You can:

- Submit the file to your AV vendor for whitelisting
- Sign the executable with a code-signing certificate (see below)

### Code-signing the executable (optional)

```powershell
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 `
    /f your-cert.pfx /p your-password `
    dist\SSHClientManager\SSHClientManager.exe
```

---

## Architecture Notes

| Concern | Detail |
|---------|--------|
| x86_64 | Fully supported — the only architecture targeted |
| ARM64 / Windows on Arm | Not tested; may work with a native Python ARM64 install |
| Windows 10 / 11 | Tested; Windows 7/8 not supported (PySide6 requirement) |
| Keychain / Credential Manager | Not used — credentials are AES-encrypted locally by `src/credential_store.py` |
| OpenSSH client | Uses the Windows built-in `ssh.exe` (`C:\Windows\System32\OpenSSH\ssh.exe`, available on Windows 10 1809+) |
