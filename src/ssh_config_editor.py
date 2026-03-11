"""
SSH Config Editor dialog — edit ~/.ssh/config with syntax highlighting.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRegularExpression, QTimer
from PySide6.QtGui import QFont, QKeySequence, QShortcut, QSyntaxHighlighter, QTextCharFormat, QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLabel,
)

_SSH_KEYWORDS = [
    "Host", "HostName", "User", "Port", "IdentityFile", "ForwardX11",
    "ProxyJump", "ProxyCommand", "ServerAliveInterval", "ServerAliveCountMax",
    "StrictHostKeyChecking", "UserKnownHostsFile", "Compression",
    "ForwardAgent", "AddKeysToAgent", "IdentitiesOnly", "LogLevel",
    "ConnectTimeout", "BatchMode", "PasswordAuthentication",
    "PubkeyAuthentication", "KexAlgorithms", "MACs", "Ciphers",
    "HostKeyAlgorithms", "SendEnv", "RequestTTY", "RemoteForward",
    "LocalForward", "DynamicForward", "ControlMaster", "ControlPath",
    "ControlPersist", "Match", "Include", "PreferredAuthentications",
    "CanonicalDomains", "CanonicalizeFallbackLocal", "CanonicalizeHostname",
]


class SSHConfigHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)

        self._keyword_fmt = QTextCharFormat()
        self._keyword_fmt.setFontWeight(QFont.Weight.Bold)
        self._keyword_fmt.setForeground(QColor("#4c9be8"))

        self._comment_fmt = QTextCharFormat()
        self._comment_fmt.setFontItalic(True)
        self._comment_fmt.setForeground(QColor("#888888"))

        self._keyword_patterns = [
            QRegularExpression(r"(?i)^\s*(" + kw + r")\b")
            for kw in _SSH_KEYWORDS
        ]
        self._comment_re = QRegularExpression(r"^\s*#.*")

    def highlightBlock(self, text: str):
        for pattern in self._keyword_patterns:
            m = pattern.match(text)
            if m.hasMatch():
                self.setFormat(m.capturedStart(1), m.capturedLength(1), self._keyword_fmt)
                break  # only one keyword per line

        m = self._comment_re.match(text)
        if m.hasMatch():
            self.setFormat(m.capturedStart(), m.capturedLength(), self._comment_fmt)


class SSHConfigEditorDialog(QDialog):
    """Edit ~/.ssh/config with basic syntax highlighting."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SSH Config Editor — ~/.ssh/config")
        self.setMinimumSize(700, 540)

        self._config_path = Path.home() / ".ssh" / "config"
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(3000)
        self._save_timer.timeout.connect(lambda: self._status.setText(""))

        layout = QVBoxLayout(self)

        self._editor = QTextEdit()
        font = QFont("Monospace", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._editor.setFont(font)
        self._editor.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self._editor)

        self._highlighter = SSHConfigHighlighter(self._editor.document())

        bottom = QHBoxLayout()
        self._btn_save = QPushButton("Save")
        self._btn_close = QPushButton("Close")
        self._status = QLabel("")
        bottom.addWidget(self._btn_save)
        bottom.addWidget(self._btn_close)
        bottom.addStretch()
        bottom.addWidget(self._status)
        layout.addLayout(bottom)

        self._btn_save.clicked.connect(self._save)
        self._btn_close.clicked.connect(self.accept)
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self._save)

        self._load()

    # ------------------------------------------------------------------

    def _load(self):
        try:
            if self._config_path.exists():
                self._editor.setPlainText(self._config_path.read_text(encoding="utf-8"))
            else:
                self._editor.setPlainText("")
        except OSError as e:
            self._editor.setPlainText("")
            self._status.setText(f"Error loading: {e}")

    def _save(self):
        try:
            self._config_path.parent.mkdir(mode=0o700, exist_ok=True)
            self._config_path.write_text(self._editor.toPlainText(), encoding="utf-8")
            self._status.setText("Saved")
            self._save_timer.start()
        except OSError as e:
            self._status.setText(f"Error: {e}")
