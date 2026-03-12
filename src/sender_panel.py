"""
Sender Panel — prepare multi-line commands and send them to terminals.

Similar to WindTerm's Sender: type / paste commands here, then push them
to the active terminal or broadcast to all open terminals at once.
"""

import re

from PySide6.QtCore import Qt, Signal, QRegularExpression
from PySide6.QtGui import (
    QKeySequence, QTextCursor,
    QSyntaxHighlighter, QTextCharFormat, QColor, QFont,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit,
    QPushButton, QLabel, QCheckBox, QFrame, QSizePolicy,
)


# ---------------------------------------------------------------------------
# Shell syntax highlighter  (Catppuccin Latte palette)
# ---------------------------------------------------------------------------

def _fmt(hex_color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(hex_color))
    if bold:
        f.setFontWeight(QFont.Weight.Bold)
    if italic:
        f.setFontItalic(True)
    return f


class _ShellHighlighter(QSyntaxHighlighter):
    """Minimal shell-command syntax highlighter."""

    _RULES: list[tuple[QRegularExpression, QTextCharFormat]] = []

    def __init__(self, parent):
        super().__init__(parent)
        if not _ShellHighlighter._RULES:
            _ShellHighlighter._RULES = self._build_rules()

    @staticmethod
    def _build_rules():
        rules = []

        def add(pattern: str, fmt: QTextCharFormat):
            rules.append((QRegularExpression(pattern), fmt))

        # Comments
        add(r"#.*$", _fmt("#8c8fa1", italic=True))
        # Double-quoted strings
        add(r'"[^"\\]*(?:\\.[^"\\]*)*"', _fmt("#40a02b"))
        # Single-quoted strings
        add(r"'[^']*'", _fmt("#40a02b"))
        # Variables  $VAR  ${VAR}  $1
        add(r"\$\{?[\w]+\}?", _fmt("#fe640b", bold=True))
        # Flags  -x  --long-opt
        add(r"(?<!\w)--?[\w][\w-]*", _fmt("#179299"))
        # Pipes, redirects, semicolons, &&, ||
        add(r"[|><&;]+", _fmt("#d20f39", bold=True))
        # Common shell keywords / builtins
        builtins = (
            r"\b(?:sudo|su|cd|ls|echo|cat|grep|awk|sed|find|rm|cp|mv|mkdir|"
            r"chmod|chown|kill|ps|top|df|du|tar|curl|wget|ssh|scp|git|python|"
            r"python3|pip|npm|node|docker|kubectl|systemctl|service|export|"
            r"source|alias|unset|set|read|if|then|else|elif|fi|for|while|do|"
            r"done|case|esac|function|return|exit|true|false)\b"
        )
        add(builtins, _fmt("#1e66f5", bold=True))
        # Numbers
        add(r"\b\d+\b", _fmt("#df8e1d"))

        return rules

    def highlightBlock(self, text: str):
        for rx, fmt in _ShellHighlighter._RULES:
            it = rx.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)


class SenderPanel(QWidget):
    """
    Command-preparation panel.

    Signals:
        send_to_active(str)    — send text to the currently focused terminal
        send_to_all(str)       — broadcast text to every open terminal
    """

    send_to_active = Signal(str)
    send_to_all    = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # ── Header ──────────────────────────────────────────────────
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("📤 Sender")
        lbl.setStyleSheet("font-weight: bold; color: #1e66f5;")
        header.addWidget(lbl)
        header.addStretch()

        btn_clear = QPushButton("Clear")
        btn_clear.setFixedHeight(22)
        btn_clear.setFixedWidth(50)
        btn_clear.setToolTip("Clear editor")
        btn_clear.clicked.connect(self._on_clear)
        header.addWidget(btn_clear)
        root.addLayout(header)

        # ── Divider ─────────────────────────────────────────────────
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #ccd0da;")
        root.addWidget(line)

        # ── Editor ──────────────────────────────────────────────────
        self._editor = QPlainTextEdit()
        self._editor.setPlaceholderText(
            "Type or paste commands here…\n\n"
            "Ctrl+Enter  →  Send to active terminal\n"
            "Ctrl+Shift+Enter  →  Broadcast to all"
        )
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._editor.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._editor.setStyleSheet(
            "QPlainTextEdit {"
            "  background-color: #ffffff;"
            "  color: #4c4f69;"
            "  border: 1px solid #bcc0cc;"
            "  border-radius: 6px;"
            "  font-family: 'Cascadia Code', 'Consolas', 'Courier New', monospace;"
            "  font-size: 10pt;"
            "  padding: 4px;"
            "}"
            "QPlainTextEdit:focus {"
            "  border-color: #1e66f5;"
            "}"
        )
        self._highlighter = _ShellHighlighter(self._editor.document())
        # Install key filter for shortcuts
        self._editor.installEventFilter(self)
        root.addWidget(self._editor)

        # ── Options ─────────────────────────────────────────────────
        self._chk_line_by_line = QCheckBox("Send line-by-line (add ↵ after each line)")
        self._chk_line_by_line.setChecked(True)
        self._chk_line_by_line.setToolTip(
            "When checked, appends a newline after every line so each is executed.\n"
            "Uncheck to send the raw text as-is (e.g. for multi-line paste mode)."
        )
        root.addWidget(self._chk_line_by_line)

        # ── Buttons ─────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self._btn_send = QPushButton("▶  Send to Active")
        self._btn_send.setToolTip("Send to the focused terminal  (Ctrl+Enter)")
        self._btn_send.setFixedHeight(28)
        self._btn_send.setStyleSheet(
            "QPushButton { background-color: #1e66f5; color: #ffffff;"
            "  border: none; border-radius: 6px; padding: 4px 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: #3d7ef7; }"
            "QPushButton:pressed { background-color: #1657d4; }"
        )
        self._btn_send.clicked.connect(self._on_send_active)
        btn_row.addWidget(self._btn_send)

        self._btn_broadcast = QPushButton("📡  Broadcast to All")
        self._btn_broadcast.setToolTip("Send to every open terminal  (Ctrl+Shift+Enter)")
        self._btn_broadcast.setFixedHeight(28)
        self._btn_broadcast.setStyleSheet(
            "QPushButton { background-color: #fe640b; color: #ffffff;"
            "  border: none; border-radius: 6px; padding: 4px 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: #ff7c2a; }"
            "QPushButton:pressed { background-color: #e0550a; }"
        )
        self._btn_broadcast.clicked.connect(self._on_send_all)
        btn_row.addWidget(self._btn_broadcast)

        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Key shortcuts inside the editor
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent
        if obj is self._editor and event.type() == QEvent.Type.KeyPress:
            ke: QKeyEvent = event
            ctrl  = ke.modifiers() & Qt.KeyboardModifier.ControlModifier
            shift = ke.modifiers() & Qt.KeyboardModifier.ShiftModifier
            if ctrl and shift and ke.key() == Qt.Key.Key_Return:
                self._on_send_all()
                return True
            if ctrl and not shift and ke.key() == Qt.Key.Key_Return:
                self._on_send_active()
                return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_payload(self) -> str:
        """Return the text to send.

        Line-by-line mode: each line gets a trailing \\r\\n (CR+LF) so the
        shell treats it as Enter. Plain paste mode: send the raw text as-is.
        """
        text = self._editor.toPlainText()
        if not text.strip():
            return ""
        if self._chk_line_by_line.isChecked():
            lines = text.splitlines()
            # Strip trailing whitespace per line, join with CR+LF so every
            # line is submitted as a separate Enter keystroke.
            return "".join(line.rstrip() + "\r\n" for line in lines)
        return text

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_send_active(self):
        payload = self._build_payload()
        if payload:
            self.send_to_active.emit(payload)

    def _on_send_all(self):
        payload = self._build_payload()
        if payload:
            self.send_to_all.emit(payload)

    def _on_clear(self):
        self._editor.clear()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def set_text(self, text: str):
        """Pre-fill the editor (e.g. from a snippet)."""
        self._editor.setPlainText(text)
        self._editor.moveCursor(QTextCursor.MoveOperation.End)

    def focus_editor(self):
        self._editor.setFocus()
