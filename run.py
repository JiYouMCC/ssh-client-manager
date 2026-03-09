#!/usr/bin/env python3
"""
SSH Client Manager - Entry point (Windows / PySide6 edition).

Features:
- Split terminals (horizontal/vertical, unlimited nesting)
- Tabbed interface per pane
- Encrypted credential storage (AES/Fernet)
- paramiko-based SSH authentication (password, key, passphrase)
- xterm.js terminal via QWebEngineView
- Cluster mode for broadcasting commands to multiple terminals
- Hierarchical connection grouping

Usage:
    python run.py [--verbose]
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
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable verbose debug output")
    args = parser.parse_args()

    if args.verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)
        print("Verbose mode enabled")

    print(f"SSH Client Manager v1.0.0  (Python {sys.version.split()[0]})")

    if not _check_deps():
        sys.exit(1)

    from src.app import main as app_main
    sys.exit(app_main())


if __name__ == "__main__":
    main()
