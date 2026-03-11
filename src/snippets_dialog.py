"""
Snippets dialog — browse, edit, and send command snippets to terminals.
"""
from __future__ import annotations

import re
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import (
    QDialog, QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem,
    QLabel, QLineEdit, QTextEdit, QComboBox, QPushButton,
    QDialogButtonBox, QMessageBox, QFileDialog, QToolBar,
    QHeaderView, QAbstractItemView, QSizePolicy,
)
from PySide6.QtGui import QAction

from .snippets import Snippet, SnippetsManager


_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


def _extract_vars(command: str) -> list[str]:
    seen: list[str] = []
    for m in _VAR_RE.finditer(command):
        name = m.group(1)
        if name not in seen:
            seen.append(name)
    return seen


def _substitute_vars(command: str, values: dict[str, str]) -> str:
    def repl(m):
        return values.get(m.group(1), m.group(0))
    return _VAR_RE.sub(repl, command)


class _VarDialog(QDialog):
    """Prompt for {{variable}} values before sending a snippet."""

    def __init__(self, variables: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fill Variables")
        self.setMinimumWidth(360)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Fill in the template variables:"))

        self._fields: dict[str, QLineEdit] = {}
        for var in variables:
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{var}:"))
            edit = QLineEdit()
            edit.setPlaceholderText(var)
            row.addWidget(edit)
            layout.addLayout(row)
            self._fields[var] = edit

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict[str, str]:
        return {k: v.text() for k, v in self._fields.items()}


class SnippetsDialog(QDialog):
    """
    Non-modal dialog for browsing, editing, and sending command snippets.

    Usage:
        dlg = SnippetsDialog(parent, snippets_manager, terminal_panel)
        dlg.show()
    """

    def __init__(self, parent, snippets_manager: SnippetsManager, terminal_panel=None):
        super().__init__(parent)
        self.snippets_manager = snippets_manager
        self.terminal_panel = terminal_panel

        self.setWindowTitle("Command Snippets")
        self.setMinimumSize(820, 560)
        self.setWindowFlag(Qt.WindowType.Window, True)

        self._current_snippet: Optional[Snippet] = None
        self._editing_new = False

        self._build_ui()
        self._refresh_categories()
        self._refresh_list()

        send_sc = QShortcut(QKeySequence("Ctrl+S"), self)
        send_sc.activated.connect(self._on_send)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        toolbar = self._build_toolbar()
        root.addWidget(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([260, 560])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)

    def _build_toolbar(self) -> QToolBar:
        tb = QToolBar()
        tb.setMovable(False)

        self._act_add = QAction("＋ Add", self)
        self._act_add.setToolTip("Add new snippet")
        self._act_add.triggered.connect(self._on_add)
        tb.addAction(self._act_add)

        self._act_delete = QAction("✕ Delete", self)
        self._act_delete.setToolTip("Delete selected snippet")
        self._act_delete.triggered.connect(self._on_delete)
        tb.addAction(self._act_delete)

        tb.addSeparator()

        self._act_send = QAction("▶ Send", self)
        self._act_send.setToolTip("Send snippet to active terminal (Ctrl+S)")
        self._act_send.triggered.connect(self._on_send)
        tb.addAction(self._act_send)

        self._act_broadcast = QAction("📡 Broadcast", self)
        self._act_broadcast.setToolTip("Send snippet to all open terminals")
        self._act_broadcast.triggered.connect(self._on_broadcast)
        tb.addAction(self._act_broadcast)

        self._act_copy = QAction("⎘ Copy", self)
        self._act_copy.setToolTip("Copy command to clipboard")
        self._act_copy.triggered.connect(self._on_copy)
        tb.addAction(self._act_copy)

        tb.addSeparator()

        self._act_export = QAction("↑ Export", self)
        self._act_export.setToolTip("Export snippets to JSON file")
        self._act_export.triggered.connect(self._on_export)
        tb.addAction(self._act_export)

        self._act_import = QAction("↓ Import", self)
        self._act_import.setToolTip("Import snippets from JSON file")
        self._act_import.triggered.connect(self._on_import)
        tb.addAction(self._act_import)

        return tb

    def _build_left_panel(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        layout.addWidget(QLabel("Category"))
        self._category_list = QListWidget()
        self._category_list.setMaximumHeight(140)
        self._category_list.currentItemChanged.connect(self._on_category_changed)
        layout.addWidget(self._category_list)

        layout.addWidget(QLabel("Snippets"))
        self._snippet_tree = QTreeWidget()
        self._snippet_tree.setHeaderLabels(["Name", "Category", "Description"])
        self._snippet_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._snippet_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._snippet_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._snippet_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._snippet_tree.setRootIsDecorated(False)
        self._snippet_tree.currentItemChanged.connect(self._on_snippet_selected)
        self._snippet_tree.itemDoubleClicked.connect(lambda item, col: self._on_send())
        layout.addWidget(self._snippet_tree, 1)

        return w

    def _build_right_panel(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        form_widget = QWidget()
        from PySide6.QtWidgets import QFormLayout
        form = QFormLayout(form_widget)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._edit_name = QLineEdit()
        self._edit_name.setPlaceholderText("Snippet name")
        form.addRow("Name:", self._edit_name)

        self._edit_category = QComboBox()
        self._edit_category.setEditable(True)
        self._edit_category.setPlaceholderText("Category (optional)")
        form.addRow("Category:", self._edit_category)

        self._edit_command = QTextEdit()
        self._edit_command.setPlaceholderText(
            "Command to send, e.g.:\n  tail -f /var/log/syslog\n\n"
            "Use {{variable}} for template variables."
        )
        self._edit_command.setMinimumHeight(100)
        form.addRow("Command:", self._edit_command)

        self._edit_description = QLineEdit()
        self._edit_description.setPlaceholderText("Optional description")
        form.addRow("Description:", self._edit_description)

        layout.addWidget(form_widget)

        btn_row = QHBoxLayout()
        self._btn_save = QPushButton("Save")
        self._btn_save.clicked.connect(self._on_save_snippet)
        self._btn_discard = QPushButton("Discard")
        self._btn_discard.clicked.connect(self._on_discard)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_save)
        btn_row.addWidget(self._btn_discard)
        layout.addLayout(btn_row)

        layout.addStretch()
        return w

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    def _refresh_categories(self):
        self._category_list.blockSignals(True)
        self._category_list.clear()
        all_item = QListWidgetItem("All")
        all_item.setData(Qt.ItemDataRole.UserRole, None)
        self._category_list.addItem(all_item)
        for cat in self.snippets_manager.get_categories():
            item = QListWidgetItem(cat)
            item.setData(Qt.ItemDataRole.UserRole, cat)
            self._category_list.addItem(item)
        self._category_list.blockSignals(False)
        self._category_list.setCurrentRow(0)

        self._edit_category.blockSignals(True)
        self._edit_category.clear()
        self._edit_category.addItem("")
        for cat in self.snippets_manager.get_categories():
            self._edit_category.addItem(cat)
        self._edit_category.blockSignals(False)

    def _current_category_filter(self) -> Optional[str]:
        item = self._category_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _refresh_list(self, preserve_selection: Optional[str] = None):
        cat_filter = self._current_category_filter()
        snippets = self.snippets_manager.get_snippets()
        if cat_filter is not None:
            snippets = [s for s in snippets if s.category == cat_filter]

        self._snippet_tree.blockSignals(True)
        self._snippet_tree.clear()
        for s in sorted(snippets, key=lambda x: x.name.lower()):
            item = QTreeWidgetItem([s.name, s.category, s.description])
            item.setData(0, Qt.ItemDataRole.UserRole, s.id)
            self._snippet_tree.addTopLevelItem(item)
        self._snippet_tree.blockSignals(False)

        if preserve_selection:
            for i in range(self._snippet_tree.topLevelItemCount()):
                item = self._snippet_tree.topLevelItem(i)
                if item.data(0, Qt.ItemDataRole.UserRole) == preserve_selection:
                    self._snippet_tree.setCurrentItem(item)
                    break

    def _populate_editor(self, s: Optional[Snippet]):
        self._current_snippet = s
        if s is None:
            self._edit_name.clear()
            self._edit_category.setCurrentText("")
            self._edit_command.clear()
            self._edit_description.clear()
        else:
            self._edit_name.setText(s.name)
            self._edit_category.setCurrentText(s.category)
            self._edit_command.setPlainText(s.command)
            self._edit_description.setText(s.description)

    def _resolve_command(self, command: str) -> Optional[str]:
        """Substitute {{vars}}. Returns None if user cancelled."""
        variables = _extract_vars(command)
        if not variables:
            return command
        dlg = _VarDialog(variables, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return _substitute_vars(command, dlg.values())

    # ------------------------------------------------------------------
    # Signals / slots
    # ------------------------------------------------------------------

    def _on_category_changed(self):
        self._refresh_list()

    def _on_snippet_selected(self, current: QTreeWidgetItem, _prev):
        if current is None:
            self._populate_editor(None)
            return
        sid = current.data(0, Qt.ItemDataRole.UserRole)
        self._populate_editor(self.snippets_manager.get_snippet(sid))
        self._editing_new = False

    def _on_add(self):
        self._editing_new = True
        self._snippet_tree.clearSelection()
        self._populate_editor(Snippet())
        self._edit_name.setFocus()

    def _on_delete(self):
        item = self._snippet_tree.currentItem()
        if item is None:
            return
        sid = item.data(0, Qt.ItemDataRole.UserRole)
        s = self.snippets_manager.get_snippet(sid)
        name = s.name if s else sid
        reply = QMessageBox.question(
            self, "Delete Snippet", f"Delete snippet '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.snippets_manager.delete_snippet(sid)
            self._current_snippet = None
            self._refresh_categories()
            self._refresh_list()
            self._populate_editor(None)

    def _on_save_snippet(self):
        name = self._edit_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Snippet name is required.")
            return
        command = self._edit_command.toPlainText().strip()

        if self._editing_new or self._current_snippet is None:
            s = Snippet(
                name=name,
                command=command,
                category=self._edit_category.currentText().strip(),
                description=self._edit_description.text().strip(),
            )
            self.snippets_manager.add_snippet(s)
        else:
            s = self._current_snippet
            s.name = name
            s.command = command
            s.category = self._edit_category.currentText().strip()
            s.description = self._edit_description.text().strip()
            self.snippets_manager.update_snippet(s)

        self._editing_new = False
        self._refresh_categories()
        self._refresh_list(preserve_selection=s.id)

    def _on_discard(self):
        self._editing_new = False
        self._populate_editor(self._current_snippet)

    def _on_send(self):
        if self._current_snippet is None:
            return
        command = self._resolve_command(self._current_snippet.command)
        if command is None:
            return
        if not command.endswith("\n"):
            command += "\n"
        if self.terminal_panel is None:
            return
        terminal = self.terminal_panel.active_terminal
        if terminal is None:
            QMessageBox.information(self, "No Terminal", "No active terminal found.")
            return
        terminal.send_text(command)

    def _on_broadcast(self):
        if self._current_snippet is None:
            return
        command = self._resolve_command(self._current_snippet.command)
        if command is None:
            return
        if not command.endswith("\n"):
            command += "\n"
        if self.terminal_panel is None:
            return
        terminals = self.terminal_panel.get_all_terminals()
        if not terminals:
            QMessageBox.information(self, "No Terminals", "No open terminals found.")
            return
        for terminal in terminals:
            terminal.send_text(command)

    def _on_copy(self):
        if self._current_snippet is None:
            return
        command = self._resolve_command(self._current_snippet.command)
        if command is None:
            return
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(command)

    def _on_export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Snippets", "snippets.json", "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "w") as f:
                f.write(self.snippets_manager.export_json())
        except IOError as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def _on_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Snippets", "", "JSON Files (*.json)"
        )
        if not path:
            return
        reply = QMessageBox.question(
            self, "Import Mode",
            "Overwrite existing snippets?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Cancel:
            return
        replace = reply == QMessageBox.StandardButton.Yes
        try:
            with open(path, "r") as f:
                json_str = f.read()
            self.snippets_manager.import_json(json_str, replace=replace)
        except (IOError, ValueError) as e:
            QMessageBox.critical(self, "Import Error", str(e))
            return
        self._refresh_categories()
        self._refresh_list()
        self._populate_editor(None)
