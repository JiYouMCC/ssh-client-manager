"""
PySide6 terminal widget — QWebEngineView hosting xterm.js.

Each TerminalWidget owns a BaseSession (SSHSession or LocalShellSession).
The WebSocket server lives inside the session; the view loads terminal.html
with ?port=<ws_port> so xterm.js can connect.
"""

import json
import os
import sys
import urllib.parse
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QUrl, Signal, QTimer, QObject
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage
from PySide6.QtWidgets import QWidget, QVBoxLayout, QMenu, QApplication

from .config import Config
from .connection import Connection
from .ssh_session import BaseSession, SSHSession, LocalShellSession

_ASSETS_DIR = (
    Path(sys._MEIPASS) / "src" / "assets"
    if getattr(sys, "frozen", False)
    else Path(__file__).parent / "assets"
)


class _SilentPage(QWebEnginePage):
    """Suppress JS console messages from the terminal page."""

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceId):
        pass


class TerminalWidget(QWidget):
    """
    A terminal widget backed by xterm.js in a QWebEngineView.

    Signals:
        title_changed(str)   — terminal title updated
        child_exited()       — SSH/process disconnected
    """

    title_changed = Signal(str)
    child_exited = Signal()

    def __init__(
        self,
        config: Config,
        connection: Optional[Connection] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.config = config
        self.connection = connection
        self._session: Optional[BaseSession] = None
        self._connected = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._view = QWebEngineView(self)
        page = _SilentPage(self._view)
        self._view.setPage(page)

        # Allow local file access (needed for xterm.js loaded from disk)
        settings = self._view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)

        layout.addWidget(self._view)

        self._view.titleChanged.connect(self._on_js_title)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_session(self, session: BaseSession):
        """Attach a session and load the terminal page."""
        self._session = session
        session.on_disconnected = self._on_disconnected

        session.start()

        # Give the WS server a moment to bind
        QTimer.singleShot(200, self._load_terminal)

    def send_text(self, text: str):
        """Send text directly to the session (for post-login commands)."""
        if self._session:
            self._session.send_input(text)

    def grab_focus(self):
        self._view.setFocus()

    def is_connected(self) -> bool:
        return self._connected

    def stop_session(self):
        if self._session:
            self._session.stop()
            self._session = None
        self._connected = False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_terminal(self):
        if not self._session:
            return

        cfg = self.config
        conn = self.connection

        # Build font string (e.g. "Consolas, monospace" from "Consolas 12")
        font_str = (conn.font if conn and conn.font else cfg["terminal_font"])
        parts = font_str.rsplit(" ", 1)
        font_family = parts[0] if len(parts) == 2 else font_str
        try:
            font_size = int(parts[1]) if len(parts) == 2 else 12
        except ValueError:
            font_size = 12

        bg = (conn.bg_color if conn and conn.bg_color else cfg["terminal_bg_color"])
        fg = (conn.fg_color if conn and conn.fg_color else cfg["terminal_fg_color"])
        palette = cfg["terminal_palette"]
        cursor = cfg["terminal_cursor_shape"]
        scrollback = cfg["terminal_scrollback_lines"]

        params = {
            "port": str(self._session.port),
            "bg": bg,
            "fg": fg,
            "font_family": font_family,
            "font_size": str(font_size),
            "scrollback": str(scrollback),
            "cursor": cursor,
            "palette": urllib.parse.quote(json.dumps(palette)),
        }

        query = "&".join(f"{k}={urllib.parse.quote(str(v), safe='')}"
                         for k, v in params.items()
                         if k != "palette")
        query += f"&palette={params['palette']}"

        html_path = _ASSETS_DIR / "terminal.html"
        base_url = QUrl.fromLocalFile(str(_ASSETS_DIR) + "/")
        url = QUrl(f"file:///{html_path.as_posix()}?{query}")

        self._view.load(url)
        self._connected = True

    def _on_js_title(self, title: str):
        if title and title != "terminal.html":
            self.title_changed.emit(title)

    def _on_disconnected(self):
        self._connected = False
        self.child_exited.emit()

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction("Copy", self._copy)
        menu.addAction("Paste", self._paste)
        menu.addSeparator()
        menu.addAction("Select All", self._select_all)
        menu.exec(event.globalPos())

    def _copy(self):
        self._view.page().runJavaScript(
            "term.getSelection()",
            lambda sel: QApplication.clipboard().setText(sel) if sel else None
        )

    def _paste(self):
        text = QApplication.clipboard().text()
        if text and self._session:
            self._session.send_input(text)

    def _select_all(self):
        self._view.page().runJavaScript("term.selectAll()")

