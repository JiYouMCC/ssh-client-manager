"""
Sidebar with hierarchical connection tree.

Displays connections organized in groups using QTreeWidget.
Supports right-click context menu, double-click to connect,
and live search filtering.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal, QSortFilterProxyModel
from PySide6.QtGui import QIcon, QAction
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLineEdit, QToolButton, QMenu, QInputDialog, QMessageBox, QSizePolicy,
    QToolBar,
)

from .connection import Connection, ConnectionManager


class Sidebar(QWidget):
    """
    Left panel showing connections grouped hierarchically.

    Signals:
        connect_requested(str): User double-clicked a connection (conn_id)
        edit_requested(str):    User chose Edit from context menu (conn_id)
        delete_requested(str):  User chose Delete from context menu (conn_id)
        add_requested():        User wants to add a new connection
        add_group_requested():  User wants to add a new group
    """

    connect_requested = Signal(str)
    edit_requested = Signal(str)
    delete_requested = Signal(str)
    add_requested = Signal()
    add_group_requested = Signal()

    # Item data roles
    _CONN_ID_ROLE = Qt.ItemDataRole.UserRole
    _IS_GROUP_ROLE = Qt.ItemDataRole.UserRole + 1
    _GROUP_PATH_ROLE = Qt.ItemDataRole.UserRole + 2

    def __init__(self, connection_manager: ConnectionManager, credential_store=None):
        super().__init__()
        self.connection_manager = connection_manager
        self.credential_store = credential_store

        self.setMinimumWidth(180)
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar row
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setIconSize(toolbar.iconSize().__class__(16, 16))

        self._act_add = QAction("＋", self)
        self._act_add.setToolTip("Add Connection")
        self._act_add.triggered.connect(self.add_requested.emit)
        toolbar.addAction(self._act_add)

        self._act_add_group = QAction("📁", self)
        self._act_add_group.setToolTip("Add Group")
        self._act_add_group.triggered.connect(self.add_group_requested.emit)
        toolbar.addAction(self._act_add_group)

        toolbar.addSeparator()

        self._act_expand = QAction("⊞", self)
        self._act_expand.setToolTip("Expand All")
        self._act_expand.triggered.connect(self._expand_all)
        toolbar.addAction(self._act_expand)

        self._act_collapse = QAction("⊟", self)
        self._act_collapse.setToolTip("Collapse All")
        self._act_collapse.triggered.connect(self._collapse_all)
        toolbar.addAction(self._act_collapse)

        layout.addWidget(toolbar)

        # Search bar
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search connections…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search_changed)
        self._search.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._search)

        # Tree widget
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setColumnCount(1)
        self._tree.setIndentation(16)
        self._tree.setAnimated(True)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._tree)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self):
        """Reload all connections from connection_manager and rebuild the tree."""
        self._tree.clear()
        filter_text = self._search.text().strip().lower()

        # Map group_path -> QTreeWidgetItem
        group_items: dict[str, QTreeWidgetItem] = {}

        def get_group_item(group_path: str) -> QTreeWidgetItem:
            if group_path in group_items:
                return group_items[group_path]
            parts = group_path.split("/")
            parent_path = "/".join(parts[:-1])
            label = parts[-1]
            if parent_path:
                parent_item = get_group_item(parent_path)
            else:
                parent_item = self._tree.invisibleRootItem()
            item = QTreeWidgetItem(parent_item, [f"📁 {label}"])
            item.setData(0, self._IS_GROUP_ROLE, True)
            item.setData(0, self._GROUP_PATH_ROLE, group_path)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEnabled)
            item.setExpanded(True)
            group_items[group_path] = item
            return item

        # Build declared groups first (so empty groups appear)
        for group_path in self.connection_manager.get_groups():
            if group_path:
                get_group_item(group_path)

        # Add connections
        connections = self.connection_manager.get_connections()
        for conn in connections:
            # Apply search filter
            if filter_text:
                haystack = f"{conn.name} {conn.display_name()} {conn.group}".lower()
                if filter_text not in haystack:
                    continue

            dest = conn.display_name()
            label = f"🖥 {conn.name}" if conn.name else f"🖥 {dest}"
            tooltip = dest if conn.name else ""

            if conn.group:
                parent = get_group_item(conn.group)
            else:
                parent = self._tree.invisibleRootItem()

            item = QTreeWidgetItem(parent, [label])
            item.setData(0, self._CONN_ID_ROLE, conn.id)
            item.setData(0, self._IS_GROUP_ROLE, False)
            item.setToolTip(0, tooltip)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)

        # Expand all when filtering
        if filter_text:
            self._tree.expandAll()

    def select_connection(self, conn_id: str):
        """Programmatically select the tree item for the given connection ID."""
        def _search_items(parent: QTreeWidgetItem):
            for i in range(parent.childCount()):
                child = parent.child(i)
                if child.data(0, self._CONN_ID_ROLE) == conn_id:
                    self._tree.setCurrentItem(child)
                    self._tree.scrollToItem(child)
                    return True
                if _search_items(child):
                    return True
            return False

        root = self._tree.invisibleRootItem()
        _search_items(root)

    # ------------------------------------------------------------------
    # Slots / internal callbacks
    # ------------------------------------------------------------------

    def _on_search_changed(self, text: str):
        self.refresh()

    def _expand_all(self):
        self._tree.expandAll()

    def _collapse_all(self):
        self._tree.collapseAll()

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        is_group = item.data(0, self._IS_GROUP_ROLE)
        if is_group:
            item.setExpanded(not item.isExpanded())
            return
        conn_id = item.data(0, self._CONN_ID_ROLE)
        if conn_id:
            self.connect_requested.emit(conn_id)

    def _on_context_menu(self, pos):
        item = self._tree.itemAt(pos)
        if item is None:
            return
        is_group = item.data(0, self._IS_GROUP_ROLE)
        global_pos = self._tree.viewport().mapToGlobal(pos)

        if is_group:
            self._show_group_menu(item, global_pos)
        else:
            self._show_connection_menu(item, global_pos)

    def _show_connection_menu(self, item: QTreeWidgetItem, global_pos):
        conn_id = item.data(0, self._CONN_ID_ROLE)
        if not conn_id:
            return
        menu = QMenu(self)

        act_connect = menu.addAction("🔌 Connect")
        act_edit = menu.addAction("✏ Edit")
        act_clone = menu.addAction("📋 Clone")
        menu.addSeparator()
        act_delete = menu.addAction("🗑 Delete")
        menu.addSeparator()
        act_export = menu.addAction("📤 Export")

        chosen = menu.exec(global_pos)
        if chosen == act_connect:
            self.connect_requested.emit(conn_id)
        elif chosen == act_edit:
            self.edit_requested.emit(conn_id)
        elif chosen == act_clone:
            self._clone_connection(conn_id)
        elif chosen == act_delete:
            self.delete_requested.emit(conn_id)
        elif chosen == act_export:
            self._export_connection(conn_id)

    def _show_group_menu(self, item: QTreeWidgetItem, global_pos):
        group_path = item.data(0, self._GROUP_PATH_ROLE) or ""
        menu = QMenu(self)

        act_add = menu.addAction("➕ Add Connection to Group")
        act_rename = menu.addAction("✏ Rename Group")
        menu.addSeparator()
        act_delete = menu.addAction("🗑 Delete Group (with connections)")
        act_delete_empty = menu.addAction("🗑 Delete Group (keep connections)")

        chosen = menu.exec(global_pos)
        if chosen == act_add:
            # Emit add_requested; the caller can pre-populate the group field
            self.add_requested.emit()
        elif chosen == act_rename:
            self._rename_group(group_path)
        elif chosen == act_delete:
            self._delete_group(group_path, delete_connections=True)
        elif chosen == act_delete_empty:
            self._delete_group(group_path, delete_connections=False)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _clone_connection(self, conn_id: str):
        conn = self.connection_manager.get_connection(conn_id)
        if conn is None:
            return
        cloned = conn.clone()
        self.connection_manager.add_connection(cloned)
        self.refresh()

    def _export_connection(self, conn_id: str):
        conn = self.connection_manager.get_connection(conn_id)
        if conn is None:
            return
        QMessageBox.information(
            self,
            "Export",
            f"Connection command:\n\n{conn.command}",
        )

    def _rename_group(self, group_path: str):
        parts = group_path.split("/")
        current_name = parts[-1]
        new_name, ok = QInputDialog.getText(
            self, "Rename Group", "New group name:", text=current_name
        )
        if ok and new_name and new_name != current_name:
            new_path = "/".join(parts[:-1] + [new_name]) if len(parts) > 1 else new_name
            self.connection_manager.rename_group(group_path, new_path)
            self.refresh()

    def _delete_group(self, group_path: str, delete_connections: bool):
        msg = (
            f"Delete group '{group_path}' and all its connections?"
            if delete_connections
            else f"Delete group '{group_path}'? Connections will be moved to root."
        )
        reply = QMessageBox.question(
            self, "Delete Group", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.connection_manager.delete_group(group_path, delete_connections=delete_connections)
            self.refresh()
