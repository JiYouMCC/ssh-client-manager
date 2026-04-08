"""
Sender Panel — prepare multi-line commands and send them to terminals.

Similar to WindTerm's Sender: type / paste commands here, then push them
to the active terminal or broadcast to all open terminals at once.
"""

import re
import shlex

from PySide6.QtCore import Qt, Signal, QRegularExpression
from PySide6.QtGui import (
    QKeySequence, QTextCursor,
    QSyntaxHighlighter, QTextCharFormat, QColor, QFont,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit,
    QPushButton, QLabel, QCheckBox, QFrame, QSizePolicy, QDialog,
    QDialogButtonBox,
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

    _VAR_PATTERN = re.compile(r"\{([a-zA-Z_]\w*)\}")

    def __init__(self, terminal_panel, parent=None):
        super().__init__(parent)
        self._terminal_panel = terminal_panel
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

        self._lbl_templates = QLabel(
            "Template vars: {name} {host} {user} {port} {group} {index} {target}"
        )
        self._lbl_templates.setStyleSheet("color: #8c8fa1; font-size: 11px;")
        root.addWidget(self._lbl_templates)

        # ── Options ─────────────────────────────────────────────────
        self._chk_wrap = QCheckBox("Wrap long lines in editor")
        self._chk_wrap.setChecked(False)
        self._chk_wrap.setToolTip(
            "When checked, long lines are visually wrapped in the editor.\n"
            "Uncheck to keep one command per physical line with horizontal scrolling."
        )
        self._chk_wrap.toggled.connect(self._on_toggle_wrap)
        root.addWidget(self._chk_wrap)

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

        self._btn_preview_active = QPushButton("🧪 Preview Active")
        self._btn_preview_active.setToolTip("Render template for active target only")
        self._btn_preview_active.setFixedHeight(28)
        self._btn_preview_active.clicked.connect(self._on_preview_active)
        btn_row.addWidget(self._btn_preview_active)

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

        self._btn_preview_all = QPushButton("🧪 Preview All")
        self._btn_preview_all.setToolTip("Render template for all open terminals")
        self._btn_preview_all.setFixedHeight(28)
        self._btn_preview_all.clicked.connect(self._on_preview_all)
        btn_row.addWidget(self._btn_preview_all)

        root.addLayout(btn_row)

        self._lbl_result = QLabel("")
        self._lbl_result.setStyleSheet("color: #5c5f77; font-size: 11px;")
        root.addWidget(self._lbl_result)

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
        """Return raw editor text."""
        text = self._editor.toPlainText()
        return text if text.strip() else ""

    @staticmethod
    def _parse_target(command: str) -> tuple[str, str, str]:
        """Parse SSH command into (user, host, port)."""
        if not command:
            return "", "", "22"
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = command.split()
        user = ""
        host = ""
        port = "22"
        i = 1 if parts and parts[0] == "ssh" else 0
        positional = []
        while i < len(parts):
            arg = parts[i]
            if arg == "-p" and i + 1 < len(parts):
                port = parts[i + 1]
                i += 2
                continue
            if arg in ("-l", "--login-name") and i + 1 < len(parts):
                user = parts[i + 1]
                i += 2
                continue
            if arg.startswith("-"):
                i += 2 if len(arg) == 2 and i + 1 < len(parts) else 1
                continue
            positional.append(arg)
            i += 1
        if positional:
            dest = positional[-1]
            if "@" in dest:
                user, host = dest.rsplit("@", 1)
            else:
                host = dest
        return user, host, port

    def _build_context(self, term, index: int) -> dict[str, str]:
        conn = getattr(term, "connection", None)
        name = (conn.name if conn and conn.name else "").strip() if conn else ""
        group = (conn.group if conn and conn.group else "").strip() if conn else ""
        command = (conn.command if conn and conn.command else "").strip() if conn else ""
        user, host, port = self._parse_target(command)
        if not name:
            name = host or f"terminal-{index}"
        target = f"{user}@{host}" if user and host else (host or name)
        return {
            "name": name,
            "host": host,
            "user": user,
            "port": port,
            "group": group,
            "index": str(index),
            "target": target,
        }

    def _render_template(self, text: str, context: dict[str, str]) -> str:
        def repl(match):
            key = match.group(1)
            return context.get(key, match.group(0))
        return self._VAR_PATTERN.sub(repl, text)

    def _to_wire_payload(self, text: str) -> str:
        if self._chk_line_by_line.isChecked():
            return "".join(line.rstrip() + "\r\n" for line in text.splitlines())
        return text

    def _collect_targets(self, all_targets: bool):
        if all_targets:
            return list(self._terminal_panel.get_all_terminals())
        active = self._terminal_panel.active_terminal
        return [active] if active is not None else []

    def _show_preview_dialog(self, title: str, content: str):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(860, 560)
        v = QVBoxLayout(dlg)
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(content)
        v.addWidget(editor)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dlg.reject)
        buttons.accepted.connect(dlg.accept)
        v.addWidget(buttons)
        dlg.exec()

    def _preview(self, all_targets: bool):
        text = self._build_payload()
        if not text:
            self._lbl_result.setText("Nothing to preview.")
            return
        targets = self._collect_targets(all_targets)
        if not targets:
            self._lbl_result.setText("No target terminals available.")
            return
        blocks = []
        for idx, term in enumerate(targets, start=1):
            ctx = self._build_context(term, idx)
            rendered = self._render_template(text, ctx)
            conn_state = "connected" if term.is_connected() else "disconnected"
            blocks.append(
                f"[{idx}] {ctx['target']} ({conn_state})\n"
                f"{rendered}"
            )
        title = "Sender Preview — All Targets" if all_targets else "Sender Preview — Active Target"
        self._show_preview_dialog(title, "\n\n" + ("\n\n" + ("-" * 72) + "\n\n").join(blocks))
        self._lbl_result.setText(f"Previewed {len(blocks)} target(s).")

    def _dispatch(self, all_targets: bool):
        text = self._build_payload()
        if not text:
            self._lbl_result.setText("Nothing to send.")
            return
        targets = self._collect_targets(all_targets)
        if not targets:
            self._lbl_result.setText("No target terminals available.")
            return
        sent = 0
        skipped = []
        for idx, term in enumerate(targets, start=1):
            ctx = self._build_context(term, idx)
            if not term.is_connected():
                skipped.append(f"{ctx['target']} (disconnected)")
                continue
            rendered = self._render_template(text, ctx)
            wire = self._to_wire_payload(rendered)
            if wire:
                term.send_text(wire)
                sent += 1
        total = len(targets)
        if skipped:
            preview = ", ".join(skipped[:3])
            suffix = "…" if len(skipped) > 3 else ""
            self._lbl_result.setText(
                f"Sent: {sent}/{total}, skipped: {len(skipped)} ({preview}{suffix})"
            )
        else:
            self._lbl_result.setText(f"Sent: {sent}/{total}, skipped: 0.")

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_send_active(self):
        self._dispatch(all_targets=False)

    def _on_send_all(self):
        self._dispatch(all_targets=True)

    def _on_preview_active(self):
        self._preview(all_targets=False)

    def _on_preview_all(self):
        self._preview(all_targets=True)

    def _on_clear(self):
        self._editor.clear()

    def _on_toggle_wrap(self, checked: bool):
        mode = (
            QPlainTextEdit.LineWrapMode.WidgetWidth
            if checked else QPlainTextEdit.LineWrapMode.NoWrap
        )
        self._editor.setLineWrapMode(mode)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def set_text(self, text: str):
        """Pre-fill the editor (e.g. from a snippet)."""
        self._editor.setPlainText(text)
        self._editor.moveCursor(QTextCursor.MoveOperation.End)

    def focus_editor(self):
        self._editor.setFocus()
