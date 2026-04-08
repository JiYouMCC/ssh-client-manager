"""
PySide6 terminal panel — QTabWidget per pane, QSplitter for splits.

Supports:
  - Multiple tab groups (one QTabWidget per pane)
  - Horizontal / vertical splitting with unlimited nesting
  - Split Left / Right / Up / Down directions
  - Tab drag between panes (via Qt's built-in tab moving + manual drag)
  - Clone (duplicate) current tab
  - Close button on each tab
  - Visual strikethrough on disconnected tabs
  - Recording indicator [REC] in tab title
"""

from typing import Optional

from PySide6.QtCore import Qt, Signal, QMimeData, QPoint
from PySide6.QtGui import QDrag, QFont, QFontMetrics
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

    def set_recording(self, recording: bool):
        prefix = "[REC] " if recording else ""
        self._label.setText(prefix + self._label.text().replace("[REC] ", ""))
        if recording:
            self._label.setStyleSheet("color: #f38ba8;")  # red
        else:
            self._label.setStyleSheet("")

    def set_disconnected(self, disconnected: bool):
        font = self._label.font()
        font.setStrikeOut(disconnected)
        self._label.setFont(font)
        color = "#888" if disconnected else ""
        self._label.setStyleSheet(f"color: {color};")


class DraggableTabBar(QTabBar):
    """
    QTabBar subclass that supports dragging tabs to a different pane.

    Within the same bar, normal Qt movable-tab reordering applies.
    When the cursor leaves the bar rect while dragging, a QDrag is
    initiated so the tab can be dropped onto another DraggableTabBar.
    """

    # Shared drag state across all instances
    _active_drag_bar: Optional["DraggableTabBar"] = None
    _active_drag_idx: int = -1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pressed_idx: int = -1
        self._press_pos: QPoint = QPoint()
        self.setAcceptDrops(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed_idx = self.tabAt(event.pos())
            self._press_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            self._pressed_idx >= 0
            and not self.rect().contains(event.pos())
            and (event.pos() - self._press_pos).manhattanLength()
                >= QApplication.startDragDistance()
        ):
            idx = self._pressed_idx
            self._pressed_idx = -1  # prevent double-drag

            DraggableTabBar._active_drag_bar = self
            DraggableTabBar._active_drag_idx = idx

            mime = QMimeData()
            mime.setData("application/x-pane-tab", b"1")

            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.setPixmap(self.grab(self.tabRect(idx)))
            drag.exec(Qt.DropAction.MoveAction)
            return
        super().mouseMoveEvent(event)

    def dragEnterEvent(self, event):
        if (
            event.mimeData().hasFormat("application/x-pane-tab")
            and isinstance(event.source(), DraggableTabBar)
            and event.source() is not self
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if (
            event.mimeData().hasFormat("application/x-pane-tab")
            and isinstance(event.source(), DraggableTabBar)
            and event.source() is not self
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if (
            event.mimeData().hasFormat("application/x-pane-tab")
            and isinstance(event.source(), DraggableTabBar)
            and event.source() is not self
        ):
            src_bar = DraggableTabBar._active_drag_bar
            src_idx = DraggableTabBar._active_drag_idx
            if src_bar is not None and src_idx >= 0:
                src_pane = src_bar.parent()
                dst_pane = self.parent()
                if isinstance(src_pane, PaneTabWidget) and isinstance(dst_pane, PaneTabWidget):
                    dst_pane.panel._move_tab_between_panes(
                        src_pane, src_idx, dst_pane, event.pos()
                    )
            DraggableTabBar._active_drag_bar = None
            DraggableTabBar._active_drag_idx = -1
            event.acceptProposedAction()
        else:
            event.ignore()


class PaneTabWidget(QTabWidget):
    """
    A QTabWidget that belongs to a TerminalPanel.

    Emits split_requested when the user picks split from context menu.
    """

    split_h_requested       = Signal(int)   # split left (insert before)
    split_h_right_requested = Signal(int)   # split right (insert after)
    split_v_requested       = Signal(int)   # split up (insert before)
    split_v_down_requested  = Signal(int)   # split down (insert after)
    clone_requested         = Signal(int)   # clone tab

    def __init__(self, panel: "TerminalPanel", parent=None):
        super().__init__(parent)
        self.setTabBar(DraggableTabBar(self))
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
        menu.addAction("Split Left",  lambda: self.split_h_requested.emit(idx))
        menu.addAction("Split Right", lambda: self.split_h_right_requested.emit(idx))
        menu.addAction("Split Up",    lambda: self.split_v_requested.emit(idx))
        menu.addAction("Split Down",  lambda: self.split_v_down_requested.emit(idx))
        menu.addSeparator()
        menu.addAction("Clone Tab",   lambda: self.clone_requested.emit(idx))
        menu.addSeparator()
        menu.addAction("Close Tab",   lambda: self.panel.close_tab(self, idx))
        menu.exec(self.tabBar().mapToGlobal(pos))


class TerminalPanel(QWidget):
    """
    Top-level terminal panel hosting one or more PaneTabWidgets in a QSplitter tree.
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
        tab_label.close_clicked.connect(lambda: self._close_terminal(term))

        idx = pane.addTab(term, "")
        pane.tabBar().setTabButton(idx, QTabBar.ButtonPosition.LeftSide, tab_label)
        pane.setCurrentIndex(idx)

        term.title_changed.connect(lambda t: self._update_tab_title(term, t))
        term.child_exited.connect(lambda: self._on_terminal_exited(term))
        term.recording_changed.connect(lambda rec: self._on_recording_changed(term, rec))
        term.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        term.installEventFilter(self)

        term.start_session(session)
        self._set_active(term)
        return term

    def split_horizontal(self, tab_widget: PaneTabWidget, index: int):
        self._split(tab_widget, index, Qt.Orientation.Horizontal, insert_before=True)

    def split_horizontal_right(self, tab_widget: PaneTabWidget, index: int):
        self._split(tab_widget, index, Qt.Orientation.Horizontal, insert_before=False)

    def split_vertical(self, tab_widget: PaneTabWidget, index: int):
        self._split(tab_widget, index, Qt.Orientation.Vertical, insert_before=True)

    def split_vertical_down(self, tab_widget: PaneTabWidget, index: int):
        self._split(tab_widget, index, Qt.Orientation.Vertical, insert_before=False)

    def close_tab(self, tab_widget: PaneTabWidget, index: int):
        if index < 0 or index >= tab_widget.count():
            return
        term: TerminalWidget = tab_widget.widget(index)
        term.stop_session()
        tab_widget.removeTab(index)
        if tab_widget.count() == 0 and tab_widget is not self._initial_pane:
            self._remove_empty_pane(tab_widget)
        if self._active_terminal is term:
            self._active_terminal = None
            for p in self._all_panes():
                if p.count() > 0:
                    self._set_active(p.currentWidget())
                    break

    def clone_active_tab(self):
        term = self._active_terminal
        if term is None:
            return
        conn = term.connection
        if conn is None:
            return
        try:
            from .ssh_handler import SSHHandler
            from .credential_store import CredentialStore
            store = CredentialStore()
            handler = SSHHandler(store, self.config)
            session = handler.create_session(conn)
            title = conn.name or conn.display_name()
            self.new_tab(session, conn, title)
        except Exception:
            pass

    def switch_to_tab(self, index: int):
        all_terms = self.get_all_terminals()
        if 0 <= index < len(all_terms):
            target = all_terms[index]
            for pane in self._all_panes():
                idx = pane.indexOf(target)
                if idx >= 0:
                    pane.setCurrentIndex(idx)
                    self._set_active(target)
                    return

    def next_tab(self):
        pane = self.active_pane
        if pane and pane.count() > 1:
            pane.setCurrentIndex((pane.currentIndex() + 1) % pane.count())

    def prev_tab(self):
        pane = self.active_pane
        if pane and pane.count() > 1:
            pane.setCurrentIndex((pane.currentIndex() - 1) % pane.count())

    def close_active_tab(self):
        pane = self.active_pane
        if pane:
            self.close_tab(pane, pane.currentIndex())

    def get_all_terminals(self) -> list[TerminalWidget]:
        result = []
        for pane in self._all_panes():
            for i in range(pane.count()):
                w = pane.widget(i)
                if isinstance(w, TerminalWidget):
                    result.append(w)
        return result

    def unsplit(self):
        all_panes = self._all_panes()
        if len(all_panes) <= 1:
            return
        first = all_panes[0]
        for pane in all_panes[1:]:
            while pane.count():
                w = pane.widget(0)
                label_w = pane.tabBar().tabButton(0, QTabBar.ButtonPosition.LeftSide)
                title = label_w._base_title if isinstance(label_w, TabLabel) else "Terminal"
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
        pane.split_h_right_requested.connect(lambda idx: self.split_horizontal_right(pane, idx))
        pane.split_v_requested.connect(lambda idx: self.split_vertical(pane, idx))
        pane.split_v_down_requested.connect(lambda idx: self.split_vertical_down(pane, idx))
        pane.clone_requested.connect(lambda idx: self.clone_active_tab())
        pane.currentChanged.connect(
            lambda idx: self._set_active(pane.widget(idx)) if idx >= 0 else None
        )
        return pane

    def _split(self, tab_widget: PaneTabWidget, index: int, orientation: Qt.Orientation,
               insert_before: bool = False):
        parent = tab_widget.parent()
        new_pane = self._create_pane()

        if isinstance(parent, QSplitter) and parent.orientation() == orientation:
            splitter = parent
            pane_idx = splitter.indexOf(tab_widget)
            insert_at = pane_idx if insert_before else pane_idx + 1
            splitter.insertWidget(insert_at, new_pane)
        else:
            new_splitter = QSplitter(orientation)
            if isinstance(parent, QSplitter):
                idx_in_parent = parent.indexOf(tab_widget)
                tab_widget.setParent(new_splitter)
                if insert_before:
                    new_splitter.addWidget(new_pane)
                    new_splitter.addWidget(tab_widget)
                else:
                    new_splitter.addWidget(tab_widget)
                    new_splitter.addWidget(new_pane)
                parent.insertWidget(idx_in_parent, new_splitter)
            else:
                tab_widget.setParent(new_splitter)
                if insert_before:
                    new_splitter.addWidget(new_pane)
                    new_splitter.addWidget(tab_widget)
                else:
                    new_splitter.addWidget(tab_widget)
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

    def _close_terminal(self, term: TerminalWidget):
        """Find which pane contains term and close it."""
        for pane in self._all_panes():
            idx = pane.indexOf(term)
            if idx >= 0:
                self.close_tab(pane, idx)
                return

    def _add_existing_tab(self, pane: PaneTabWidget, widget: QWidget, title: str):
        tab_label = TabLabel(title)
        idx = pane.addTab(widget, "")
        pane.tabBar().setTabButton(idx, QTabBar.ButtonPosition.LeftSide, tab_label)
        if isinstance(widget, TerminalWidget):
            tab_label.close_clicked.connect(lambda: self._close_terminal(widget))

    def _move_tab_between_panes(self, src_pane: PaneTabWidget, src_idx: int,
                                 dst_pane: PaneTabWidget, drop_pos: QPoint):
        """Move a tab from src_pane to dst_pane, inserting at drop_pos."""
        if src_pane is dst_pane or src_idx < 0 or src_idx >= src_pane.count():
            return

        widget = src_pane.widget(src_idx)
        if not isinstance(widget, TerminalWidget):
            return

        src_label = src_pane.tabBar().tabButton(src_idx, QTabBar.ButtonPosition.LeftSide)
        title = src_label._base_title if isinstance(src_label, TabLabel) else "Terminal"

        # Remove from source without destroying the widget
        src_pane.removeTab(src_idx)

        # Determine insert position in destination
        target_idx = dst_pane.tabBar().tabAt(drop_pos)

        tab_label = TabLabel(title)
        tab_label.close_clicked.connect(lambda: self._close_terminal(widget))

        if target_idx < 0:
            new_idx = dst_pane.addTab(widget, "")
        else:
            new_idx = dst_pane.insertTab(target_idx, widget, "")

        dst_pane.tabBar().setTabButton(new_idx, QTabBar.ButtonPosition.LeftSide, tab_label)
        dst_pane.setCurrentIndex(new_idx)
        self._set_active(widget)

        if src_pane.count() == 0 and src_pane is not self._initial_pane:
            self._remove_empty_pane(src_pane)

    def _set_active(self, widget):
        if isinstance(widget, TerminalWidget):
            self._active_terminal = widget
            widget.grab_focus()

    def _update_tab_title(self, term: TerminalWidget, title: str):
        if term.connection and term.connection.name:
            return
        for pane in self._all_panes():
            idx = pane.indexOf(term)
            if idx >= 0:
                label_w = pane.tabBar().tabButton(idx, QTabBar.ButtonPosition.LeftSide)
                if isinstance(label_w, TabLabel):
                    label_w.set_title(title)
                return

    def _on_terminal_exited(self, term: TerminalWidget):
        for pane in self._all_panes():
            idx = pane.indexOf(term)
            if idx >= 0:
                label_w = pane.tabBar().tabButton(idx, QTabBar.ButtonPosition.LeftSide)
                if isinstance(label_w, TabLabel):
                    label_w.set_disconnected(True)
                    label_w.set_recording(False)
                return

    def _on_recording_changed(self, term: TerminalWidget, recording: bool):
        for pane in self._all_panes():
            idx = pane.indexOf(term)
            if idx >= 0:
                label_w = pane.tabBar().tabButton(idx, QTabBar.ButtonPosition.LeftSide)
                if isinstance(label_w, TabLabel):
                    label_w.set_recording(recording)
                return

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.MouseButtonPress:
            if isinstance(obj, TerminalWidget):
                self._set_active(obj)
        return super().eventFilter(obj, event)
