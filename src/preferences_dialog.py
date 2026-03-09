"""
Preferences dialog (PySide6).

Terminal appearance and behavior settings.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QSpinBox, QComboBox, QPushButton,
    QColorDialog, QGroupBox, QScrollArea, QWidget, QCheckBox,
)
from PySide6.QtGui import QColor

from .config import Config


class PreferencesDialog(QDialog):
    """Application preferences window."""

    def __init__(self, parent, config: Config):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Preferences")
        self.setMinimumSize(480, 560)
        self.setModal(True)

        outer = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setSpacing(16)

        # --- Terminal section ---
        term_group = QGroupBox("Terminal")
        term_form = QFormLayout(term_group)

        self._entry_font = QLineEdit(config["terminal_font"])
        term_form.addRow("Font (e.g. Consolas 12):", self._entry_font)

        self._spin_scrollback = QSpinBox()
        self._spin_scrollback.setRange(100, 1_000_000)
        self._spin_scrollback.setSingleStep(500)
        self._spin_scrollback.setValue(config["terminal_scrollback_lines"])
        term_form.addRow("Scrollback Lines:", self._spin_scrollback)

        self._btn_bg = self._color_button(config["terminal_bg_color"])
        self._btn_bg.clicked.connect(lambda: self._pick("bg"))
        term_form.addRow("Background Color:", self._btn_bg)

        self._btn_fg = self._color_button(config["terminal_fg_color"])
        self._btn_fg.clicked.connect(lambda: self._pick("fg"))
        term_form.addRow("Foreground Color:", self._btn_fg)

        self._combo_cursor = QComboBox()
        for c in ["block", "ibeam", "underline"]:
            self._combo_cursor.addItem(c)
        self._combo_cursor.setCurrentText(config["terminal_cursor_shape"])
        term_form.addRow("Cursor Shape:", self._combo_cursor)

        self._chk_bold = QCheckBox()
        self._chk_bold.setChecked(config["terminal_allow_bold"])
        term_form.addRow("Allow Bold:", self._chk_bold)

        self._chk_bell = QCheckBox()
        self._chk_bell.setChecked(config["terminal_audible_bell"])
        term_form.addRow("Audible Bell:", self._chk_bell)

        layout.addWidget(term_group)

        # --- SSH section ---
        ssh_group = QGroupBox("SSH")
        ssh_form = QFormLayout(ssh_group)

        self._spin_keepalive = QSpinBox()
        self._spin_keepalive.setRange(0, 3600)
        self._spin_keepalive.setValue(config["ssh_keepalive_interval"])
        ssh_form.addRow("Keepalive Interval (s):", self._spin_keepalive)

        self._spin_timeout = QSpinBox()
        self._spin_timeout.setRange(5, 300)
        self._spin_timeout.setValue(config["ssh_connection_timeout"])
        ssh_form.addRow("Connection Timeout (s):", self._spin_timeout)

        layout.addWidget(ssh_group)

        # --- Behaviour section ---
        beh_group = QGroupBox("Behaviour")
        beh_form = QFormLayout(beh_group)

        self._chk_confirm_close = QCheckBox()
        self._chk_confirm_close.setChecked(config["confirm_close_window"])
        beh_form.addRow("Confirm Window Close:", self._chk_confirm_close)

        layout.addWidget(beh_group)
        layout.addStretch()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

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

    def _save(self):
        self.config["terminal_font"] = self._entry_font.text().strip() or self.config["terminal_font"]
        self.config["terminal_scrollback_lines"] = self._spin_scrollback.value()
        self.config["terminal_bg_color"] = self._btn_bg.text()
        self.config["terminal_fg_color"] = self._btn_fg.text()
        self.config["terminal_cursor_shape"] = self._combo_cursor.currentText()
        self.config["terminal_allow_bold"] = self._chk_bold.isChecked()
        self.config["terminal_audible_bell"] = self._chk_bell.isChecked()
        self.config["ssh_keepalive_interval"] = self._spin_keepalive.value()
        self.config["ssh_connection_timeout"] = self._spin_timeout.value()
        self.config["confirm_close_window"] = self._chk_confirm_close.isChecked()
        self.accept()
