"""
PySide6 terminal panel — QTabWidget per pane, QSplitter for splits.

Supports:
  - Multiple tab groups (one QTabWidget per pane)
  - Horizontal / vertical splitting with unlimited nesting
  - Tab drag between panes (via Qt's built-in tab moving + manual drag)
  - Close button on each tab
  - Visual strikethrough on disconnected tabs
"""

from typing import Optional

from PySide6.QtCore import Qt, Signal, QMimeData, QPoint
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QWidget, QSplitter, QTabWidget, QTabBar, QHBoxLayout,
    QVBoxLayout, QPushButton, QLabel, QMenu, QApplication,
)

from .terminal_widget import TerminalWidget
from .config import Config
from .connection import Connection
from .ssh_session import BaseSession


class TabLabel(QWidget):
    """Custom tab label with title and close button."""

    close_clicked = Signal()

    def __init__(self, title: str = "Terminal", parent=None):
        super().__init__(parent)
        self._base_title = title

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 2, 0)
        layout.setSpacing(5)

        display = title if len(title) <= 30 else title[:26] + "..."
        self._label = QLabel(display)
        layout.addWidget(self._label)

        btn = QPushButton("✕")
        btn.setFixedSize(14, 14)
        btn.setFlat(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton {"
            "  font-size: 9px; padding: 0; border: none;"
            "  border-radius: 3px; color: #888;"
            "  background: transparent;"
            "}"
            "QPushButton:hover {"
            "  background: rgba(255,255,255,0.15); color: #ddd;"
            "}"
        )
        btn.clicked.connect(self.close_clicked)
        layout.addWidget(btn)

        self.setMaximumHeight(32)
        self._apply_width(display)

    def _apply_width(self, text: str):
        fm = QFontMetrics(self._label.font())
        self.setFixedWidth(fm.horizontalAdvance(text) + 75)

    def set_title(self, title: str):
        display = title.strip() if title else ""
        if not display:
            display = self._base_title
        if len(display) > 30:
            display = display[:26] + "..."
        self._label.setText(display)
        self._apply_width(display)

    def set_disconnected(self, disconnected: bool):
        font = self._label.font()
        font.setStrikeOut(disconnected)
        self._label.setFont(font)
        color = "#888" if disconnected else ""
        self._label.setStyleSheet(f"color: {color};")


class PaneTabWidget(QTabWidget):
    """
    A QTabWidget that belongs to a TerminalPanel.

    Emits split_requested when the user picks split from context menu.
    """

    split_h_requested = Signal(int)   # tab index
    split_v_requested = Signal(int)   # tab index

    def __init__(self, panel: "TerminalPanel", parent=None):
        super().__init__(parent)
        self.panel = panel
        self.setTabsClosable(False)   # We use custom close buttons
        self.setMovable(True)
        self.setDocumentMode(True)
        self.tabBar().setMinimumHeight(36)
        self.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabBar().customContextMenuRequested.connect(self._tab_context_menu)

    def _tab_context_menu(self, pos: QPoint):
        idx = self.tabBar().tabAt(pos)
        if idx < 0:
            return
        menu = QMenu(self)
        menu.addAction("Split Horizontally", lambda: self.split_h_requested.emit(idx))
        menu.addAction("Split Vertically",   lambda: self.split_v_requested.emit(idx))
        menu.addSeparator()
        menu.addAction("Close Tab", lambda: self.panel.close_tab(self, idx))
        menu.exec(self.tabBar().mapToGlobal(pos))


class TerminalPanel(QWidget):
    """
    Top-level terminal panel hosting one or more PaneTabWidgets in a QSplitter tree.

    Public API:
        new_tab(session, connection, title)  → adds tab to the active pane
        split_horizontal(tab_widget, index)  → split active pane horizontally
        split_vertical(tab_widget, index)    → split active pane vertically
        close_tab(tab_widget, index)
        get_all_terminals()                  → list[TerminalWidget]
        active_terminal                      → currently focused TerminalWidget
    """

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self._active_terminal: Optional[TerminalWidget] = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        # Root splitter
        self._root = QSplitter(Qt.Orientation.Horizontal, self)
        self._layout.addWidget(self._root)

        # Initial pane
        self._initial_pane = self._create_pane()
        self._root.addWidget(self._initial_pane)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    @property
    def active_terminal(self) -> Optional[TerminalWidget]:
        return self._active_terminal

    @property
    def active_pane(self) -> Optional[PaneTabWidget]:
        return self._find_active_pane() or self._initial_pane

    @property
    def active_pane_index(self) -> int:
        pane = self.active_pane
        if pane and self._active_terminal:
            return pane.indexOf(self._active_terminal)
        if pane:
            return pane.currentIndex()
        return 0

    def new_tab(
        self,
        session: BaseSession,
        connection: Optional[Connection] = None,
        title: str = "Terminal",
        target_pane: Optional[PaneTabWidget] = None,
    ) -> TerminalWidget:
        """Create a new terminal tab in the given pane (or active/first pane)."""
        pane = target_pane or self._find_active_pane() or self._initial_pane

        term = TerminalWidget(self.config, connection, parent=self)
        tab_label = TabLabel(title)
        tab_label.close_clicked.connect(lambda: self.close_tab(pane, pane.indexOf(term)))

        idx = pane.addTab(term, "")
        pane.tabBar().setTabButton(idx, QTabBar.ButtonPosition.LeftSide, tab_label)
        pane.setCurrentIndex(idx)

        term.title_changed.connect(lambda t: self._update_tab_title(pane, term, t))
        term.child_exited.connect(lambda: self._on_terminal_exited(pane, term))
        term.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        term.installEventFilter(self)

        term.start_session(session)
        self._set_active(term)
        return term

    def split_horizontal(self, tab_widget: PaneTabWidget, index: int):
        self._split(tab_widget, index, Qt.Orientation.Horizontal)

    def split_vertical(self, tab_widget: PaneTabWidget, index: int):
        self._split(tab_widget, index, Qt.Orientation.Vertical)

    def close_tab(self, tab_widget: PaneTabWidget, index: int):
        if index < 0 or index >= tab_widget.count():
            return
        term: TerminalWidget = tab_widget.widget(index)
        term.stop_session()
        tab_widget.removeTab(index)
        # Remove empty pane
        if tab_widget.count() == 0 and tab_widget is not self._initial_pane:
            self._remove_empty_pane(tab_widget)
        # Update active terminal
        if self._active_terminal is term:
            self._active_terminal = None
            panes = self._all_panes()
            for p in panes:
                if p.count() > 0:
                    self._set_active(p.currentWidget())
                    break

    def get_all_terminals(self) -> list[TerminalWidget]:
        result = []
        for pane in self._all_panes():
            for i in range(pane.count()):
                w = pane.widget(i)
                if isinstance(w, TerminalWidget):
                    result.append(w)
        return result

    def unsplit(self):
        """Collapse all splits — keep only the first pane."""
        all_panes = self._all_panes()
        if len(all_panes) <= 1:
            return
        # Move all tabs from other panes to the first
        first = all_panes[0]
        for pane in all_panes[1:]:
            while pane.count():
                w = pane.widget(0)
                label_w = pane.tabBar().tabButton(0, QTabBar.ButtonPosition.LeftSide)
                title = label_w.findChild(QLabel).text() if label_w else "Terminal"
                pane.removeTab(0)
                self._add_existing_tab(first, w, title)
            pane.setParent(None)
            pane.deleteLater()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_pane(self) -> PaneTabWidget:
        pane = PaneTabWidget(self)
        pane.split_h_requested.connect(lambda idx: self.split_horizontal(pane, idx))
        pane.split_v_requested.connect(lambda idx: self.split_vertical(pane, idx))
        pane.currentChanged.connect(
            lambda idx: self._set_active(pane.widget(idx)) if idx >= 0 else None
        )
        return pane

    def _split(self, tab_widget: PaneTabWidget, index: int, orientation: Qt.Orientation):
        """Split the pane containing tab_widget, inserting a new pane next to it."""
        parent = tab_widget.parent()

        # Find or create a splitter at the right orientation
        if isinstance(parent, QSplitter) and parent.orientation() == orientation:
            splitter = parent
            pane_idx = splitter.indexOf(tab_widget)
            new_pane = self._create_pane()
            splitter.insertWidget(pane_idx + 1, new_pane)
        else:
            new_splitter = QSplitter(orientation)
            if isinstance(parent, QSplitter):
                idx_in_parent = parent.indexOf(tab_widget)
                tab_widget.setParent(new_splitter)
                new_splitter.addWidget(tab_widget)
                new_pane = self._create_pane()
                new_splitter.addWidget(new_pane)
                parent.insertWidget(idx_in_parent, new_splitter)
            else:
                # Root level
                tab_widget.setParent(new_splitter)
                new_splitter.addWidget(tab_widget)
                new_pane = self._create_pane()
                new_splitter.addWidget(new_pane)
                self._layout.addWidget(new_splitter)
                if self._root is not tab_widget:
                    self._root.setParent(None)
                self._root = new_splitter

        return new_pane

    def _remove_empty_pane(self, pane: PaneTabWidget):
        parent = pane.parent()
        pane.setParent(None)
        pane.deleteLater()
        if isinstance(parent, QSplitter) and parent.count() == 1:
            # Collapse single-child splitter
            remaining = parent.widget(0)
            grandparent = parent.parent()
            if isinstance(grandparent, QSplitter):
                idx = grandparent.indexOf(parent)
                remaining.setParent(grandparent)
                grandparent.insertWidget(idx, remaining)
                parent.setParent(None)
                parent.deleteLater()

    def _find_active_pane(self) -> Optional[PaneTabWidget]:
        if self._active_terminal:
            for pane in self._all_panes():
                if pane.indexOf(self._active_terminal) >= 0:
                    return pane
        return None

    def _all_panes(self) -> list[PaneTabWidget]:
        result = []
        self._collect_panes(self._root, result)
        return result

    def _collect_panes(self, widget: QWidget, result: list):
        if isinstance(widget, PaneTabWidget):
            result.append(widget)
        elif isinstance(widget, QSplitter):
            for i in range(widget.count()):
                self._collect_panes(widget.widget(i), result)

    def _add_existing_tab(self, pane: PaneTabWidget, widget: QWidget, title: str):
        tab_label = TabLabel(title)
        idx = pane.addTab(widget, "")
        pane.tabBar().setTabButton(idx, QTabBar.ButtonPosition.LeftSide, tab_label)
        if isinstance(widget, TerminalWidget):
            tab_label.close_clicked.connect(
                lambda: self.close_tab(pane, pane.indexOf(widget))
            )

    def _set_active(self, widget):
        if isinstance(widget, TerminalWidget):
            self._active_terminal = widget
            widget.grab_focus()

    def _update_tab_title(self, pane: PaneTabWidget, term: TerminalWidget, title: str):
        idx = pane.indexOf(term)
        if idx < 0:
            return
        label_w = pane.tabBar().tabButton(idx, QTabBar.ButtonPosition.LeftSide)
        if isinstance(label_w, TabLabel):
            label_w.set_title(title)

    def _on_terminal_exited(self, pane: PaneTabWidget, term: TerminalWidget):
        idx = pane.indexOf(term)
        if idx < 0:
            return
        label_w = pane.tabBar().tabButton(idx, QTabBar.ButtonPosition.LeftSide)
        if isinstance(label_w, TabLabel):
            label_w.set_disconnected(True)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.MouseButtonPress:
            if isinstance(obj, TerminalWidget):
                self._set_active(obj)
        return super().eventFilter(obj, event)


