"""
Cluster mode window (PySide6).

Sends the same command to multiple selected terminals simultaneously.
Features:
  - Checkbox list of all open terminals
  - All / None / Invert quick-select
  - Command history (Ctrl+Up / Ctrl+Down)
  - Non-modal so the user can interact with terminals while broadcasting
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QLabel, QScrollArea, QWidget, QCheckBox, QFrame,
)
from PySide6.QtGui import QKeyEvent, QKeySequence, QShortcut


class ClusterWindow(QDialog):
    """Non-modal window for broadcasting commands to multiple terminals."""

    def __init__(self, parent, terminal_panel):
        super().__init__(parent)
        self.setWindowTitle("Cluster – Send to Terminals")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(460, 400)

        self._panel = terminal_panel
        self._checks: list[tuple[QCheckBox, object]] = []
        self._history: list[str] = []
        self._history_idx = -1

        layout = QVBoxLayout(self)

        # Quick-select row
        qs = QHBoxLayout()
        for label, fn in [("All", self._select_all), ("None", self._select_none), ("Invert", self._select_invert)]:
            btn = QPushButton(label)
            btn.setFixedWidth(70)
            btn.clicked.connect(fn)
            qs.addWidget(btn)
        qs.addStretch()
        layout.addLayout(qs)

        # Terminal list
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll_area.setWidget(self._list_widget)
        layout.addWidget(self._scroll_area, stretch=1)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep2)

        # Command entry + send
        entry_row = QHBoxLayout()
        self._entry = QLineEdit()
        self._entry.setPlaceholderText("Command to broadcast…")
        self._entry.returnPressed.connect(self._send)
        entry_row.addWidget(self._entry)

        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self._send)
        entry_row.addWidget(send_btn)
        layout.addLayout(entry_row)

        # History shortcuts
        up = QShortcut(QKeySequence("Ctrl+Up"), self._entry)
        up.activated.connect(self._history_prev)
        down = QShortcut(QKeySequence("Ctrl+Down"), self._entry)
        down.activated.connect(self._history_next)

        self._refresh_list()

    # ------------------------------------------------------------------

    def _refresh_list(self):
        # Clear
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._checks.clear()

        terminals = self._panel.get_all_terminals()
        if not terminals:
            self._list_layout.addWidget(QLabel("No terminals open."))
            return

        for term in terminals:
            conn = getattr(term, "connection", None)
            label = conn.name if conn and conn.name else "Terminal"
            if conn and conn.command:
                parts = conn.command.split()
                dest = parts[-1] if parts else ""
                if dest:
                    label = f"{label}  ({dest})"
            cb = QCheckBox(label)
            cb.setChecked(True)
            self._checks.append((cb, term))
            self._list_layout.addWidget(cb)

    def _select_all(self):
        for cb, _ in self._checks:
            cb.setChecked(True)

    def _select_none(self):
        for cb, _ in self._checks:
            cb.setChecked(False)

    def _select_invert(self):
        for cb, _ in self._checks:
            cb.setChecked(not cb.isChecked())

    def _send(self):
        cmd = self._entry.text()
        if not cmd:
            return
        for cb, term in self._checks:
            if cb.isChecked():
                term.send_text(cmd + "\n")
        # History
        if not self._history or self._history[-1] != cmd:
            self._history.append(cmd)
        self._history_idx = len(self._history)
        self._entry.clear()

    def _history_prev(self):
        if not self._history:
            return
        self._history_idx = max(0, self._history_idx - 1)
        self._entry.setText(self._history[self._history_idx])

    def _history_next(self):
        if not self._history:
            return
        self._history_idx = min(len(self._history), self._history_idx + 1)
        if self._history_idx < len(self._history):
            self._entry.setText(self._history[self._history_idx])
        else:
            self._entry.clear()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_list()
