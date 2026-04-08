"""
Preferences dialog (PySide6).

Sections: Terminal, SSH, Global Passphrases, Terminal Logging,
Session Recording, Screenshot, Behaviour.
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QSpinBox, QComboBox, QPushButton,
    QColorDialog, QGroupBox, QScrollArea, QWidget, QCheckBox,
    QFileDialog, QListWidget, QListWidgetItem, QTabWidget,
)
from PySide6.QtGui import QColor

from .config import Config


class _NoScrollSpin(QSpinBox):
    """SpinBox that ignores mouse scroll events (scroll-wheel protection)."""
    def wheelEvent(self, event):
        event.ignore()


class _NoScrollCombo(QComboBox):
    """ComboBox that ignores mouse scroll events."""
    def wheelEvent(self, event):
        event.ignore()


class PreferencesDialog(QDialog):
    """Application preferences window."""

    def __init__(self, parent, config: Config):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Preferences")
        self.setMinimumSize(560, 500)
        self.setModal(True)

        outer = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.setObjectName("prefsTabWidget")
        tabs.tabBar().setUsesScrollButtons(False)
        tabs.tabBar().setExpanding(True)
        tabs.addTab(self._build_terminal_tab(), "Terminal")
        tabs.addTab(self._build_ssh_tab(), "SSH")
        tabs.addTab(self._build_logging_tab(), "Logging")
        tabs.addTab(self._build_recording_tab(), "Recording")
        tabs.addTab(self._build_passphrases_tab(), "Passphrases")
        tabs.addTab(self._build_screenshot_tab(), "Screenshot")
        tabs.addTab(self._build_behaviour_tab(), "Behaviour")
        outer.addWidget(tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    # ------------------------------------------------------------------
    # Tab builders
    # ------------------------------------------------------------------

    def _build_terminal_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._entry_font = QLineEdit(self.config["terminal_font"])
        form.addRow("Font (e.g. Consolas 12):", self._entry_font)

        self._spin_scrollback = _NoScrollSpin()
        self._spin_scrollback.setRange(100, 1_000_000)
        self._spin_scrollback.setSingleStep(500)
        self._spin_scrollback.setValue(self.config["terminal_scrollback_lines"])
        form.addRow("Scrollback Lines:", self._spin_scrollback)

        self._btn_bg = self._color_button(self.config["terminal_bg_color"])
        self._btn_bg.clicked.connect(lambda: self._pick("bg"))
        form.addRow("Background Color:", self._btn_bg)

        self._btn_fg = self._color_button(self.config["terminal_fg_color"])
        self._btn_fg.clicked.connect(lambda: self._pick("fg"))
        form.addRow("Foreground Color:", self._btn_fg)

        self._combo_cursor = _NoScrollCombo()
        for c in ["block", "ibeam", "underline"]:
            self._combo_cursor.addItem(c)
        self._combo_cursor.setCurrentText(self.config["terminal_cursor_shape"])
        form.addRow("Cursor Shape:", self._combo_cursor)

        self._chk_bold = QCheckBox()
        self._chk_bold.setChecked(self.config["terminal_allow_bold"])
        form.addRow("Allow Bold:", self._chk_bold)

        self._chk_bell = QCheckBox()
        self._chk_bell.setChecked(self.config["terminal_audible_bell"])
        form.addRow("Audible Bell:", self._chk_bell)

        return w

    def _build_ssh_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._spin_keepalive = _NoScrollSpin()
        self._spin_keepalive.setRange(0, 3600)
        self._spin_keepalive.setValue(self.config["ssh_keepalive_interval"])
        form.addRow("Keepalive Interval (s):", self._spin_keepalive)

        self._spin_timeout = _NoScrollSpin()
        self._spin_timeout.setRange(5, 300)
        self._spin_timeout.setValue(self.config["ssh_connection_timeout"])
        form.addRow("Connection Timeout (s):", self._spin_timeout)

        self._chk_auto_reconnect = QCheckBox()
        self._chk_auto_reconnect.setChecked(self.config.get("ssh_auto_reconnect", True))
        form.addRow("Auto Reconnect:", self._chk_auto_reconnect)

        self._spin_reconnect_delay = _NoScrollSpin()
        self._spin_reconnect_delay.setRange(1, 300)
        self._spin_reconnect_delay.setValue(self.config.get("ssh_auto_reconnect_delay", 5))
        form.addRow("Reconnect Delay (s):", self._spin_reconnect_delay)

        self._spin_reconnect_retries = _NoScrollSpin()
        self._spin_reconnect_retries.setRange(0, 20)
        self._spin_reconnect_retries.setValue(self.config.get("ssh_auto_reconnect_max_retries", 3))
        form.addRow("Reconnect Retries:", self._spin_reconnect_retries)

        return w

    def _build_logging_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._chk_logging = QCheckBox("Enable auto-logging for all terminals")
        self._chk_logging.setChecked(self.config.get("terminal_logging_enabled", False))
        form.addRow("Auto-Logging:", self._chk_logging)

        log_row = QHBoxLayout()
        self._entry_log_dir = QLineEdit(
            self.config.get("terminal_log_dir", str(Path.home() / "ssh-logs"))
        )
        log_row.addWidget(self._entry_log_dir)
        btn_browse = QPushButton("Browse…")
        btn_browse.setFixedWidth(80)
        btn_browse.clicked.connect(lambda: self._browse_dir(self._entry_log_dir))
        log_row.addWidget(btn_browse)
        log_widget = QWidget()
        log_widget.setLayout(log_row)
        form.addRow("Log Directory:", log_widget)

        note = QLabel("Logs are saved as plain-text .log files (one per connection).")
        note.setWordWrap(True)
        form.addRow("", note)

        return w

    def _build_recording_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        rec_row = QHBoxLayout()
        self._entry_rec_dir = QLineEdit(
            self.config.get("recording_dir",
                            str(Path.home() / "Documents" / "SSHClientManager-Recordings"))
        )
        rec_row.addWidget(self._entry_rec_dir)
        btn_browse = QPushButton("Browse…")
        btn_browse.setFixedWidth(80)
        btn_browse.clicked.connect(lambda: self._browse_dir(self._entry_rec_dir))
        rec_row.addWidget(btn_browse)
        rec_widget = QWidget()
        rec_widget.setLayout(rec_row)
        form.addRow("Recording Directory:", rec_widget)

        note = QLabel(
            "Recordings are saved in asciicast v2 (.cast) format.\n"
            "Access recordings via Tools → Session Recordings."
        )
        note.setWordWrap(True)
        form.addRow("", note)

        return w

    def _build_passphrases_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        layout.addWidget(QLabel(
            "Global passphrases are tried automatically for every SSH connection.\n"
            "Up to 5 passphrases are supported."
        ))

        self._pp_entries = []
        saved = self.config.get("global_passphrases", [])
        for i in range(5):
            entry = QLineEdit()
            entry.setEchoMode(QLineEdit.EchoMode.Password)
            entry.setPlaceholderText(f"Passphrase {i+1} (optional)")
            if i < len(saved):
                entry.setText(saved[i])
            self._pp_entries.append(entry)
            row_w = QHBoxLayout()
            row_w.addWidget(QLabel(f"Passphrase {i+1}:"))
            row_w.addWidget(entry)
            layout.addLayout(row_w)

        layout.addStretch()
        return w

    def _build_screenshot_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._entry_watermark = QLineEdit(self.config.get("screenshot_watermark", ""))
        self._entry_watermark.setPlaceholderText("e.g. Confidential — Do Not Distribute")
        form.addRow("Watermark Text:", self._entry_watermark)

        note = QLabel(
            "Watermark appears semi-transparently in the bottom-right corner of terminal screenshots.\n"
            "Leave empty to disable."
        )
        note.setWordWrap(True)
        form.addRow("", note)

        return w

    def _build_behaviour_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._chk_confirm_close = QCheckBox()
        self._chk_confirm_close.setChecked(self.config["confirm_close_window"])
        form.addRow("Confirm Window Close:", self._chk_confirm_close)

        self._combo_local_shell = _NoScrollCombo()
        self._combo_local_shell.addItem("Auto (PowerShell → cmd)", "auto")
        self._combo_local_shell.addItem("PowerShell", "powershell")
        self._combo_local_shell.addItem("cmd.exe", "cmd")
        cur_shell = self.config.get("local_shell_windows", "auto")
        for i in range(self._combo_local_shell.count()):
            if self._combo_local_shell.itemData(i) == cur_shell:
                self._combo_local_shell.setCurrentIndex(i)
                break
        form.addRow("Local Shell (Windows):", self._combo_local_shell)

        return w

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _color_button(self, hex_color: str) -> QPushButton:
        btn = QPushButton(hex_color)
        btn.setFixedHeight(28)
        self._apply_color_style(btn, hex_color)
        return btn

    def _apply_color_style(self, btn: QPushButton, hex_color: str):
        c = QColor(hex_color)
        text_color = "#fff" if c.lightness() < 128 else "#000"
        btn.setStyleSheet(f"background-color: {hex_color}; color: {text_color};")
        btn.setText(hex_color)

    def _pick(self, which: str):
        current = self.config["terminal_bg_color"] if which == "bg" else self.config["terminal_fg_color"]
        color = QColorDialog.getColor(QColor(current), self)
        if not color.isValid():
            return
        hex_color = color.name()
        if which == "bg":
            self._bg_color = hex_color
            self._apply_color_style(self._btn_bg, hex_color)
        else:
            self._fg_color = hex_color
            self._apply_color_style(self._btn_fg, hex_color)

    def _browse_dir(self, entry: QLineEdit):
        d = QFileDialog.getExistingDirectory(self, "Select Directory", entry.text())
        if d:
            entry.setText(d)

    def _save(self):
        # Terminal
        self.config["terminal_font"] = self._entry_font.text().strip() or self.config["terminal_font"]
        self.config["terminal_scrollback_lines"] = self._spin_scrollback.value()
        self.config["terminal_bg_color"] = self._btn_bg.text()
        self.config["terminal_fg_color"] = self._btn_fg.text()
        self.config["terminal_cursor_shape"] = self._combo_cursor.currentText()
        self.config["terminal_allow_bold"] = self._chk_bold.isChecked()
        self.config["terminal_audible_bell"] = self._chk_bell.isChecked()
        # SSH
        self.config["ssh_keepalive_interval"] = self._spin_keepalive.value()
        self.config["ssh_connection_timeout"] = self._spin_timeout.value()
        self.config["ssh_auto_reconnect"] = self._chk_auto_reconnect.isChecked()
        self.config["ssh_auto_reconnect_delay"] = self._spin_reconnect_delay.value()
        self.config["ssh_auto_reconnect_max_retries"] = self._spin_reconnect_retries.value()
        # Logging
        self.config["terminal_logging_enabled"] = self._chk_logging.isChecked()
        self.config["terminal_log_dir"] = self._entry_log_dir.text().strip()
        # Recording
        self.config["recording_dir"] = self._entry_rec_dir.text().strip()
        # Global passphrases
        self.config["global_passphrases"] = [
            e.text() for e in self._pp_entries if e.text()
        ]
        # Screenshot
        self.config["screenshot_watermark"] = self._entry_watermark.text().strip()
        # Behaviour
        self.config["confirm_close_window"] = self._chk_confirm_close.isChecked()
        self.config["local_shell_windows"] = self._combo_local_shell.currentData()
        self.config.save()
        self.accept()


