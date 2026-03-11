"""
Sort Groups dialog — reorder top-level groups and subgroups.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QDialogButtonBox, QLabel,
)

from .connection import ConnectionManager


class SortGroupsDialog(QDialog):
    """
    Dialog for reordering connection groups.

    Constructor:
        SortGroupsDialog(parent, connection_manager)

    On accept, saves the new order to connection_manager._group_order
    and calls connection_manager.save().
    """

    def __init__(self, parent, connection_manager: ConnectionManager):
        super().__init__(parent)
        self.connection_manager = connection_manager

        self.setWindowTitle("Sort Groups")
        self.setMinimumSize(360, 460)
        self.setModal(True)

        self._build_ui()
        self._populate()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Drag or use the buttons to reorder groups:"))

        list_row = QHBoxLayout()

        self._list = QListWidget()
        self._list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        list_row.addWidget(self._list, 1)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(4)

        self._btn_up = QPushButton("▲ Up")
        self._btn_up.clicked.connect(self._move_up)
        btn_col.addWidget(self._btn_up)

        self._btn_down = QPushButton("▼ Down")
        self._btn_down.clicked.connect(self._move_down)
        btn_col.addWidget(self._btn_down)

        btn_col.addStretch()

        self._btn_az = QPushButton("A → Z")
        self._btn_az.setToolTip("Reset to alphabetical order")
        self._btn_az.clicked.connect(self._reset_az)
        btn_col.addWidget(self._btn_az)

        list_row.addLayout(btn_col)
        layout.addLayout(list_row, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _populate(self):
        """Fill list with groups, respecting any saved order."""
        all_groups = self.connection_manager.get_groups()
        saved_order: list[str] = list(self.connection_manager._group_order)

        # Ordered groups first, then any newly added groups not in saved order
        ordered = [g for g in saved_order if g in all_groups]
        remaining = [g for g in all_groups if g not in ordered]
        display_groups = ordered + remaining

        self._list.clear()
        for group in display_groups:
            depth = group.count("/")
            indent = "    " * depth
            item = QListWidgetItem(indent + group)
            item.setData(Qt.ItemDataRole.UserRole, group)
            self._list.addItem(item)

    def _current_order(self) -> list[str]:
        return [
            self._list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._list.count())
        ]

    # ------------------------------------------------------------------
    # Button slots
    # ------------------------------------------------------------------

    def _move_up(self):
        row = self._list.currentRow()
        if row <= 0:
            return
        item = self._list.takeItem(row)
        self._list.insertItem(row - 1, item)
        self._list.setCurrentRow(row - 1)

    def _move_down(self):
        row = self._list.currentRow()
        if row < 0 or row >= self._list.count() - 1:
            return
        item = self._list.takeItem(row)
        self._list.insertItem(row + 1, item)
        self._list.setCurrentRow(row + 1)

    def _reset_az(self):
        current_row = self._list.currentRow()
        items = [
            (self._list.item(i).text(), self._list.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(self._list.count())
        ]
        items.sort(key=lambda x: x[1].lower())
        self._list.clear()
        for text, group in items:
            depth = group.count("/")
            indent = "    " * depth
            item = QListWidgetItem(indent + group)
            item.setData(Qt.ItemDataRole.UserRole, group)
            self._list.addItem(item)
        if 0 <= current_row < self._list.count():
            self._list.setCurrentRow(current_row)

    def _on_accept(self):
        new_order = self._current_order()
        self.connection_manager._group_order = new_order
        self.connection_manager.save()
        self.accept()
