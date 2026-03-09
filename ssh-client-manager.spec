# ssh-client-manager.spec — Windows build
# Usage: pyinstaller --clean ssh-client-manager.spec
#
# Produces: dist\SSHClientManager\SSHClientManager.exe
# Zip that folder to share — no Python installation required.

import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

app_name = "SSHClientManager"
entry_py = "run.py"

# ── Data files ───────────────────────────────────────────────────────────────
datas = [
    # xterm.js assets (HTML + bundled JS/CSS)
    ("src/assets", "src/assets"),
]

# ── Hidden imports ───────────────────────────────────────────────────────────
hiddenimports = [
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebChannel",
    "paramiko",
    "paramiko.transport",
    "paramiko.auth_handler",
    "paramiko.packet",
    "paramiko.channel",
    "cryptography",
    "cryptography.fernet",
    "cryptography.hazmat.primitives.ciphers",
    "cryptography.hazmat.backends.openssl",
    "websockets",
    "websockets.server",
    "websockets.legacy.server",
    "psutil",
    "asyncio",
    # src package modules
    "src",
    "src.app",
    "src.window",
    "src.sidebar",
    "src.terminal_panel",
    "src.terminal_widget",
    "src.ssh_session",
    "src.ssh_handler",
    "src.connection",
    "src.connection_dialog",
    "src.preferences_dialog",
    "src.cluster_window",
    "src.config",
    "src.credential_store",
]

# ── Analysis ─────────────────────────────────────────────────────────────────
a = Analysis(
    [entry_py],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "scipy", "PyQt5", "PyQt6"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=app_name,
)

