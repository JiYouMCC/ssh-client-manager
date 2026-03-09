"""
SSH Client Manager Application entry point.

Creates the QApplication, applies a light (Catppuccin Latte) chrome stylesheet
with a dark terminal area, and launches the main window.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from .config import Config
from .window import MainWindow


# ---------------------------------------------------------------------------
# Catppuccin Latte light stylesheet (QSS)
# Chrome (menus, toolbar, sidebar, dialogs) is light.
# The terminal itself is a QWebEngineView whose content is controlled by
# xterm.js / terminal.html — it keeps its own dark Mocha palette regardless.
# ---------------------------------------------------------------------------
# Palette:
#   base     #eff1f5   mantle   #e6e9ef   crust    #dce0e8
#   surface0 #ccd0da   surface1 #bcc0cc   overlay1 #8c8fa1
#   text     #4c4f69   subtext1 #5c5f77
#   accent   #1e66f5   green    #40a02b   red      #d20f39
# ---------------------------------------------------------------------------
_LIGHT_QSS = """
/* ── Base ──────────────────────────────────────────────────────────────── */
QMainWindow, QDialog {
    background-color: #eff1f5;
    color: #4c4f69;
}

QWidget {
    background-color: #eff1f5;
    color: #4c4f69;
    font-family: "Segoe UI";
    font-size: 10pt;
    selection-background-color: #bcc0cc;
    selection-color: #4c4f69;
}

/* ── Menu bar ───────────────────────────────────────────────────────────── */
QMenuBar {
    background-color: #e6e9ef;
    color: #4c4f69;
    border-bottom: 1px solid #ccd0da;
    font-family: "Segoe UI";
    font-size: 10pt;
}

QMenuBar::item {
    padding: 5px 10px;
    border-radius: 4px;
}

QMenuBar::item:selected {
    background-color: #ccd0da;
}

QMenu {
    background-color: #eff1f5;
    color: #4c4f69;
    border: 1px solid #bcc0cc;
    border-radius: 6px;
    padding: 4px;
    font-family: "Segoe UI";
    font-size: 10pt;
}

QMenu::item {
    padding: 5px 28px 5px 10px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: #ccd0da;
}

QMenu::separator {
    height: 1px;
    background-color: #ccd0da;
    margin: 4px 8px;
}

/* ── Toolbar ────────────────────────────────────────────────────────────── */
QToolBar {
    background-color: #e6e9ef;
    border-bottom: 1px solid #ccd0da;
    spacing: 2px;
    padding: 2px 4px;
}

QToolBar::separator {
    width: 1px;
    background-color: #bcc0cc;
    margin: 4px 2px;
}

QToolButton {
    background-color: transparent;
    color: #4c4f69;
    border: none;
    border-radius: 4px;
    padding: 4px 8px;
    font-family: "Segoe UI";
    font-size: 10pt;
}

QToolButton:hover {
    background-color: #ccd0da;
}

QToolButton:pressed, QToolButton:checked {
    background-color: #bcc0cc;
}

/* ── Buttons ────────────────────────────────────────────────────────────── */
QPushButton {
    background-color: #e6e9ef;
    color: #4c4f69;
    border: 1px solid #bcc0cc;
    border-radius: 6px;
    padding: 4px 12px;
    min-width: 64px;
}

QPushButton:hover {
    background-color: #ccd0da;
    border-color: #1e66f5;
}

QPushButton:pressed {
    background-color: #bcc0cc;
}

QPushButton:default {
    border-color: #1e66f5;
    color: #1e66f5;
}

/* ── Line edit ──────────────────────────────────────────────────────────── */
QLineEdit {
    background-color: #ffffff;
    color: #4c4f69;
    border: 1px solid #bcc0cc;
    border-radius: 6px;
    padding: 4px 8px;
}

QLineEdit:focus {
    border-color: #1e66f5;
}

QLineEdit:disabled {
    color: #8c8fa1;
    background-color: #e6e9ef;
}

/* ── Text edit ──────────────────────────────────────────────────────────── */
QTextEdit {
    background-color: #ffffff;
    color: #4c4f69;
    border: 1px solid #bcc0cc;
    border-radius: 6px;
    padding: 4px;
}

QTextEdit:focus {
    border-color: #1e66f5;
}

/* ── Sidebar tree ───────────────────────────────────────────────────────── */
QTreeWidget {
    background-color: #e6e9ef;
    color: #4c4f69;
    border: none;
    outline: none;
}

QTreeWidget::item {
    padding: 3px 4px;
    border-radius: 4px;
}

QTreeWidget::item:selected {
    background-color: #bcc0cc;
    color: #4c4f69;
}

QTreeWidget::item:hover {
    background-color: #ccd0da;
}

QTreeWidget::branch {
    background-color: #e6e9ef;
}

/* ── Tab widget ─────────────────────────────────────────────────────────── */
QTabWidget::pane {
    border: none;
    background-color: #eff1f5;
}

QTabBar {
    background-color: #e6e9ef;
}

QTabBar::tab {
    background-color: #e6e9ef;
    color: #5c5f77;
    padding: 4px 12px;
    border: none;
    border-bottom: 2px solid transparent;
    min-width: 80px;
}

QTabBar::tab:selected {
    color: #4c4f69;
    border-bottom-color: #1e66f5;
    background-color: #eff1f5;
}

QTabBar::tab:hover:!selected {
    background-color: #ccd0da;
    color: #4c4f69;
}

/* ── Splitter ───────────────────────────────────────────────────────────── */
QSplitter::handle {
    background-color: #ccd0da;
}

QSplitter::handle:horizontal {
    width: 3px;
}

QSplitter::handle:vertical {
    height: 3px;
}

QSplitter::handle:hover {
    background-color: #1e66f5;
}

/* ── Status bar ─────────────────────────────────────────────────────────── */
QStatusBar {
    background-color: #e6e9ef;
    color: #5c5f77;
    border-top: 1px solid #ccd0da;
    font-size: 11px;
}

QStatusBar::item {
    border: none;
}

/* ── Scroll bars ────────────────────────────────────────────────────────── */
QScrollBar:vertical {
    background-color: #e6e9ef;
    width: 10px;
    margin: 0;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background-color: #bcc0cc;
    min-height: 24px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background-color: #8c8fa1;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background-color: #e6e9ef;
    height: 10px;
    margin: 0;
    border-radius: 5px;
}

QScrollBar::handle:horizontal {
    background-color: #bcc0cc;
    min-width: 24px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #8c8fa1;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ── Combo box ──────────────────────────────────────────────────────────── */
QComboBox {
    background-color: #ffffff;
    color: #4c4f69;
    border: 1px solid #bcc0cc;
    border-radius: 6px;
    padding: 3px 8px;
}

QComboBox:hover {
    border-color: #1e66f5;
}

QComboBox QAbstractItemView {
    background-color: #eff1f5;
    color: #4c4f69;
    selection-background-color: #ccd0da;
    border: 1px solid #bcc0cc;
}

/* ── Table widget ───────────────────────────────────────────────────────── */
QTableWidget {
    background-color: #ffffff;
    color: #4c4f69;
    border: 1px solid #ccd0da;
    border-radius: 4px;
    gridline-color: #e6e9ef;
}

QHeaderView::section {
    background-color: #e6e9ef;
    color: #5c5f77;
    border: none;
    border-bottom: 1px solid #ccd0da;
    padding: 4px 8px;
    font-weight: bold;
}

QTableWidget::item:selected {
    background-color: #ccd0da;
    color: #4c4f69;
}

/* ── Labels ─────────────────────────────────────────────────────────────── */
QLabel {
    color: #4c4f69;
    background-color: transparent;
}

/* ── Group box ──────────────────────────────────────────────────────────── */
QGroupBox {
    color: #1e66f5;
    border: 1px solid #bcc0cc;
    border-radius: 6px;
    margin-top: 8px;
    padding-top: 8px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 4px;
    color: #1e66f5;
}

/* ── Check / radio ──────────────────────────────────────────────────────── */
QCheckBox, QRadioButton {
    color: #4c4f69;
    spacing: 6px;
}

QCheckBox::indicator, QRadioButton::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #bcc0cc;
    border-radius: 3px;
    background-color: #ffffff;
}

QCheckBox::indicator:checked {
    background-color: #1e66f5;
    border-color: #1e66f5;
}

QRadioButton::indicator {
    border-radius: 7px;
}

QRadioButton::indicator:checked {
    background-color: #1e66f5;
    border-color: #1e66f5;
}

/* ── Spin box ───────────────────────────────────────────────────────────── */
QSpinBox, QDoubleSpinBox {
    background-color: #ffffff;
    color: #4c4f69;
    border: 1px solid #bcc0cc;
    border-radius: 6px;
    padding: 3px 6px;
}

/* ── Tool tip ───────────────────────────────────────────────────────────── */
QToolTip {
    background-color: #e6e9ef;
    color: #4c4f69;
    border: 1px solid #bcc0cc;
    border-radius: 4px;
    padding: 3px 6px;
}
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    """
    Application entry point.

    Creates the QApplication, sets up styling, creates Config and MainWindow,
    shows the window, and enters the Qt event loop.

    Returns:
        Exit code from app.exec()
    """
    app = QApplication(sys.argv)
    app.setApplicationName("SSH Client Manager")
    app.setOrganizationName("ssh-client-manager")
    app.setApplicationDisplayName("SSH Client Manager")

    # Windows-comfortable font: Segoe UI 10pt normal weight
    from PySide6.QtGui import QFont
    font = QFont("Segoe UI", 10)
    font.setWeight(QFont.Weight.Normal)
    app.setFont(font)

    app.setStyleSheet(_LIGHT_QSS)

    config = Config()
    window = MainWindow(config)
    window.show()

    return app.exec()
