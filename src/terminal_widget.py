"""
PySide6 terminal widget — QWebEngineView hosting xterm.js.

Each TerminalWidget owns a BaseSession (SSHSession or LocalShellSession).
The WebSocket server lives inside the session; the view loads terminal.html
with ?port=<ws_port> so xterm.js can connect.
"""

import json
import os
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QUrl, Signal, QTimer, QObject, QPoint
from PySide6.QtGui import QPainter, QColor, QFont as QGuiFont
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QMenu, QApplication,
    QPushButton, QLabel, QFrame,
)

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
        recording_changed(bool) — recording state changed
    """

    title_changed = Signal(str)
    child_exited = Signal()
    recording_changed = Signal(bool)

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
        self._is_recording = False
        self._manual_stop_requested = False
        self._reconnect_attempts = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Reconnect overlay (shown on disconnect)
        self._reconnect_bar = self._build_reconnect_bar()
        layout.addWidget(self._reconnect_bar)
        self._reconnect_bar.hide()

        self._view = QWebEngineView(self)
        page = _SilentPage(self._view)
        self._view.setPage(page)
        # Suppress the browser's native context menu so our contextMenuEvent fires
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

        settings = self._view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)

        layout.addWidget(self._view)

        self._view.titleChanged.connect(self._on_js_title)

    # ------------------------------------------------------------------
    # Reconnect bar
    # ------------------------------------------------------------------

    def _build_reconnect_bar(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background: #313244; border-bottom: 1px solid #585b70; }"
        )
        h = QHBoxLayout(frame)
        h.setContentsMargins(8, 4, 8, 4)
        lbl = QLabel("⚡ Connection closed.")
        lbl.setStyleSheet("color: #f38ba8;")
        h.addWidget(lbl)
        h.addStretch()
        btn = QPushButton("🔄 Reconnect")
        btn.setFixedHeight(26)
        btn.clicked.connect(self._on_reconnect)
        h.addWidget(btn)
        frame.setMaximumHeight(40)
        return frame

    def _on_reconnect(self):
        """Re-create session for this connection and reconnect."""
        if self.connection is None:
            return
        self._manual_stop_requested = False
        self._reconnect_bar.hide()
        # Import lazily to avoid circular imports
        try:
            from .ssh_handler import SSHHandler
            from .credential_store import CredentialStore
            store = CredentialStore()
            handler = SSHHandler(store, self.config)
            session = handler.create_session(self.connection)
            self.start_session(session)
        except Exception:
            self._reconnect_bar.show()
            self._schedule_auto_reconnect()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_session(self, session: BaseSession):
        """Attach a session and load the terminal page."""
        self._session = session
        self._manual_stop_requested = False
        session.on_disconnected = self._on_disconnected

        # Attach logging if enabled
        if self.config.get("terminal_logging_enabled", False):
            log_dir = Path(self.config.get("terminal_log_dir", str(Path.home() / "ssh-logs")))
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d-%H%M%S")
            name = (self.connection.name or "session").replace(" ", "_") if self.connection else "session"
            session.log_file_path = str(log_dir / f"{name}-{ts}.log")

        session.start()
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
            self._manual_stop_requested = True
            self._session.stop()
            self._session = None
        self._connected = False

    # --- Font zoom ---

    def zoom_in(self):
        self._view.page().runJavaScript("if(window.termZoomIn) termZoomIn();")

    def zoom_out(self):
        self._view.page().runJavaScript("if(window.termZoomOut) termZoomOut();")

    def zoom_reset(self):
        self._view.page().runJavaScript("if(window.termZoomReset) termZoomReset();")

    # --- Recording ---

    def start_recording(self, file_path: str):
        if self._session:
            # Ask xterm.js for actual cols/rows, then open the file with those dims
            self._view.page().runJavaScript(
                "[term.cols, term.rows]",
                lambda dims: self._do_start_recording(file_path, dims)
            )

    def _do_start_recording(self, file_path: str, dims):
        if not self._session:
            return
        cols, rows = (dims[0], dims[1]) if isinstance(dims, list) and len(dims) == 2 else (220, 50)
        self._session.start_recording(file_path, cols=int(cols), rows=int(rows))
        self._is_recording = True
        self.recording_changed.emit(True)

    def stop_recording(self):
        if self._session:
            self._session.stop_recording()
        self._is_recording = False
        self.recording_changed.emit(False)

    def is_recording(self) -> bool:
        return self._is_recording

    # --- Screenshot ---

    def copy_screenshot(self):
        """Capture full terminal, optionally stamp watermark, copy to clipboard."""
        pixmap = self._view.grab()
        self._apply_watermark_and_copy(pixmap)

    def copy_screenshot_selection(self):
        """Capture only the selected rows using the rect saved at right-click time."""
        self._view.page().runJavaScript(
            "window._savedSelectionRect || null",
            self._on_selection_rect
        )

    def _on_selection_rect(self, rect):
        pixmap = self._view.grab()
        if rect and rect.get("w", 0) > 0 and rect.get("h", 0) > 0:
            from PySide6.QtCore import QRect
            # JS returns CSS (logical) pixel coords; scale by the pixmap's device pixel ratio
            dpr = pixmap.devicePixelRatio()
            if dpr <= 0:
                dpr = 1.0
            x = max(0, int(rect["x"] * dpr))
            y = max(0, int(rect["y"] * dpr))
            w = min(int(rect["w"] * dpr), pixmap.width() - x)
            h = min(int(rect["h"] * dpr), pixmap.height() - y)
            if w > 0 and h > 0:
                cropped = pixmap.copy(QRect(x, y, w, h))
                if not cropped.isNull():
                    cropped.setDevicePixelRatio(dpr)
                    pixmap = cropped
        self._apply_watermark_and_copy(pixmap)

    def _apply_watermark_and_copy(self, pixmap):
        watermark = self.config.get("screenshot_watermark", "").strip()
        if watermark:
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            font = QGuiFont("Arial", 13)
            font.setBold(True)
            painter.setFont(font)
            margin = 10
            fm = painter.fontMetrics()
            text_w = fm.horizontalAdvance(watermark)
            x = pixmap.width() - text_w - margin
            y = pixmap.height() - margin
            painter.setPen(QColor(0, 0, 0, 120))
            painter.drawText(x + 1, y + 1, watermark)
            painter.setPen(QColor(255, 255, 255, 160))
            painter.drawText(x, y, watermark)
            painter.end()
        QApplication.clipboard().setPixmap(pixmap)
        self._show_toast("📷 Screenshot copied to clipboard")

    def _show_toast(self, message: str, duration_ms: int = 2000):
        """Show a brief floating notification inside the widget."""
        toast = QLabel(message, self)
        toast.setStyleSheet(
            "QLabel { background: rgba(30,30,46,210); color: #cdd6f4;"
            " border: 1px solid #585b70; border-radius: 6px;"
            " padding: 6px 14px; font-size: 13px; }"
        )
        toast.adjustSize()
        # Centre horizontally near the bottom
        x = (self.width() - toast.width()) // 2
        y = self.height() - toast.height() - 20
        toast.move(max(0, x), max(0, y))
        toast.show()
        toast.raise_()
        QTimer.singleShot(duration_ms, toast.deleteLater)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_terminal(self):
        if not self._session:
            return

        cfg = self.config
        conn = self.connection

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

        # convertEol is not needed: ConPTY (Windows) and PTY (Unix) both handle line endings

        # Measure the actual tab bar height so terminal.html can compensate for
        # the documentMode overlap (tab bar floats over the content area).
        tab_overlap = 0
        tab_widget = self.parent()
        while tab_widget is not None:
            from PySide6.QtWidgets import QTabWidget
            if isinstance(tab_widget, QTabWidget):
                tab_overlap = tab_widget.tabBar().height()
                break
            tab_widget = tab_widget.parent()

        params = {
            "port": str(self._session.port),
            "bg": bg,
            "fg": fg,
            "font_family": font_family,
            "font_size": str(font_size),
            "scrollback": str(scrollback),
            "cursor": cursor,
            "tab_overlap": str(tab_overlap),
            "palette": urllib.parse.quote(json.dumps(palette)),
        }

        query = "&".join(f"{k}={urllib.parse.quote(str(v), safe='')}"
                         for k, v in params.items()
                         if k != "palette")
        query += f"&palette={params['palette']}"

        html_path = _ASSETS_DIR / "terminal.html"
        url = QUrl(f"file:///{html_path.as_posix()}?{query}")
        self._view.load(url)
        self._connected = True
        self._reconnect_attempts = 0

    def _on_js_title(self, title: str):
        if title and title != "terminal.html":
            self.title_changed.emit(title)

    def _on_disconnected(self):
        if self._manual_stop_requested:
            self._manual_stop_requested = False
            return
        self._connected = False
        if self._is_recording:
            self.stop_recording()
        self.child_exited.emit()
        if self.connection is not None:
            self._reconnect_bar.show()
            self._schedule_auto_reconnect()

    def _schedule_auto_reconnect(self):
        if self.connection is None:
            return
        if not self.config.get("ssh_auto_reconnect", True):
            return
        max_retries = max(0, int(self.config.get("ssh_auto_reconnect_max_retries", 3)))
        if self._reconnect_attempts >= max_retries:
            return
        delay_seconds = max(1, int(self.config.get("ssh_auto_reconnect_delay", 5)))
        self._reconnect_attempts += 1
        QTimer.singleShot(delay_seconds * 1000, self._on_reconnect)

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction("Copy", self._copy)
        menu.addAction("Paste", self._paste)
        menu.addSeparator()
        menu.addAction("Select All", self._select_all)
        menu.addSeparator()
        if self._is_recording:
            menu.addAction("⏹ Stop Recording", self.stop_recording)
        else:
            menu.addAction("⏺ Start Recording", self._start_recording_prompt)
        menu.addSeparator()
        menu.addAction("📷 Copy Screenshot of Selection", self.copy_screenshot_selection)
        menu.addAction("📷 Copy Full Screenshot", self.copy_screenshot)
        menu.exec(event.globalPos())

    def _start_recording_prompt(self):
        rec_dir = Path(self.config.get(
            "recording_dir",
            str(Path.home() / "Documents" / "SSHClientManager-Recordings")
        ))
        rec_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        name = (self.connection.name or "session").replace(" ", "_") if self.connection else "session"
        file_path = str(rec_dir / f"{name}-{ts}.cast")
        self.start_recording(file_path)

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

