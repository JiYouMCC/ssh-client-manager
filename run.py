#!/usr/bin/env python3
"""
SSH Client Manager - Entry point (Windows / PySide6 edition).

Usage:
    python run.py           # no console window
    python run.py --debug   # keep console visible for logging
"""

import sys
import os
import argparse

# Add project root to path
project_dir = (
    os.path.dirname(sys.executable)
    if getattr(sys, "frozen", False)
    else os.path.dirname(os.path.abspath(__file__))
)
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

# Required for QWebEngineView on some systems
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu-sandbox")


def _hide_console():
    """Hide the Windows console window (no-op on non-Windows / frozen builds)."""
    if sys.platform != "win32" or getattr(sys, "frozen", False):
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass


def _check_deps() -> bool:
    ok = True

    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except ImportError as e:
        print(f"Error: PySide6 or PySide6-WebEngine not found: {e}")
        print("  pip install PySide6 PySide6-WebEngine")
        ok = False

    try:
        import paramiko
    except ImportError:
        print("Warning: paramiko not installed — SSH will not work.")
        print("  pip install paramiko")

    try:
        from cryptography.fernet import Fernet
    except ImportError:
        print("Warning: cryptography not installed — credential storage disabled.")
        print("  pip install cryptography")

    try:
        import websockets
    except ImportError:
        print("Warning: websockets not installed — terminal I/O will not work.")
        print("  pip install websockets")

    return ok


def main():
    parser = argparse.ArgumentParser(description="SSH Client Manager")
    parser.add_argument("--debug", "-d", action="store_true",
                        help="Keep console visible and enable debug logging")
    # keep --verbose as an alias
    parser.add_argument("--verbose", "-v", action="store_true",
                        help=argparse.SUPPRESS)
    args = parser.parse_args()

    debug = args.debug or args.verbose

    if not debug:
        _hide_console()
    else:
        import logging
        logging.basicConfig(level=logging.DEBUG)
        print(f"SSH Client Manager — debug mode  (Python {sys.version.split()[0]})")

    if not _check_deps():
        sys.exit(1)

    from src.app import main as app_main
    sys.exit(app_main())


if __name__ == "__main__":
    main()
