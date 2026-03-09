"""
Main application window.

Combines the sidebar (connection tree), terminal panel (split tabs),
toolbar, and menu into the main PySide6 QMainWindow.
"""

from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QToolBar, QStatusBar,
    QMenuBar, QMenu, QMessageBox, QApplication, QLabel,
)

from .config import Config
from .connection import Connection, ConnectionManager
from .credential_store import CredentialStore
from .ssh_handler import SSHHandler
from .terminal_panel import TerminalPanel
from .sidebar import Sidebar

try:
    from .connection_dialog import ConnectionDialog
    _HAS_CONN_DIALOG = True
except ImportError:
    _HAS_CONN_DIALOG = False

try:
    from .preferences_dialog import PreferencesDialog
    _HAS_PREFS_DIALOG = True
except ImportError:
    _HAS_PREFS_DIALOG = False

try:
    from .cluster_window import ClusterWindow
    _HAS_CLUSTER = True
except ImportError:
    _HAS_CLUSTER = False


class MainWindow(QMainWindow):
    """
    The main application window.

    Layout:
    ┌──────────────────────────────────────────────┐
    │ MenuBar                                       │
    ├──────────────────────────────────────────────┤
    │ ToolBar  [New Tab][Local][SplitH][SplitV]... │
    ├──────────┬───────────────────────────────────┤
    │ Sidebar  │ TerminalPanel                     │
    │  Search  │  PaneTabWidget (splits/tabs)       │
    │  Tree    │                                   │
    ├──────────┴───────────────────────────────────┤
    │ StatusBar                                    │
    └──────────────────────────────────────────────┘
    """

    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.connection_manager = ConnectionManager()
        self.credential_store = CredentialStore()
        self.ssh_handler = SSHHandler(self.credential_store)

        self.setWindowTitle("SSH Client Manager")
        self.resize(
            int(config.get("window_width", 1200)),
            int(config.get("window_height", 750)),
        )

        self._build_ui()
        self._build_menu()
        self._build_toolbar()
        self._build_statusbar()
        self._connect_signals()
        self._restore_sidebar_width()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        """Build central splitter with sidebar and terminal panel."""
        self.terminal_panel = TerminalPanel(self.config)
        self.sidebar = Sidebar(self.connection_manager, self.credential_store)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.addWidget(self.sidebar)
        self._splitter.addWidget(self.terminal_panel)

        sidebar_width = int(self.config.get("sidebar_width", 220))
        total = self.width()
        self._splitter.setSizes([sidebar_width, max(total - sidebar_width, 200)])
        self._splitter.setCollapsible(0, True)
        self._splitter.setCollapsible(1, False)
        self.setCentralWidget(self._splitter)

    def _build_menu(self):
        """Build QMenuBar."""
        menubar = self.menuBar()

        # File
        file_menu = menubar.addMenu("&File")

        act_new_tab = QAction("New &Tab", self)
        act_new_tab.setShortcut(QKeySequence("Ctrl+T"))
        act_new_tab.triggered.connect(self._on_new_tab)
        file_menu.addAction(act_new_tab)

        act_local = QAction("New &Local Shell", self)
        act_local.setShortcut(QKeySequence("Ctrl+Shift+T"))
        act_local.triggered.connect(self._on_local_shell)
        file_menu.addAction(act_local)

        file_menu.addSeparator()

        act_import = QAction("&Import Connections…", self)
        act_import.triggered.connect(self._on_import)
        file_menu.addAction(act_import)

        act_export = QAction("&Export Connections…", self)
        act_export.triggered.connect(self._on_export)
        file_menu.addAction(act_export)

        file_menu.addSeparator()

        act_quit = QAction("&Quit", self)
        act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        act_quit.triggered.connect(QApplication.instance().quit)
        file_menu.addAction(act_quit)

        # View
        view_menu = menubar.addMenu("&View")

        self._act_sidebar = QAction("Toggle &Sidebar", self)
        self._act_sidebar.setShortcut(QKeySequence("Ctrl+\\"))
        self._act_sidebar.triggered.connect(self._on_toggle_sidebar)
        view_menu.addAction(self._act_sidebar)

        act_unsplit = QAction("&Unsplit", self)
        act_unsplit.triggered.connect(self._on_unsplit)
        view_menu.addAction(act_unsplit)

        view_menu.addSeparator()

        act_prefs = QAction("&Preferences…", self)
        act_prefs.setShortcut(QKeySequence("Ctrl+,"))
        act_prefs.triggered.connect(self._on_preferences)
        view_menu.addAction(act_prefs)

        # Help
        help_menu = menubar.addMenu("&Help")
        act_about = QAction("&About", self)
        act_about.triggered.connect(self._on_about)
        help_menu.addAction(act_about)

    def _build_toolbar(self):
        """Build main toolbar."""
        tb = QToolBar("Main Toolbar")
        tb.setMovable(False)
        tb.setIconSize(QSize(20, 20))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        act_new = QAction("⊞ New Tab", self)
        act_new.setToolTip("Open connection in new tab (Ctrl+T)")
        act_new.triggered.connect(self._on_new_tab)
        tb.addAction(act_new)

        act_local = QAction("💻 Local Shell", self)
        act_local.setToolTip("Open local shell tab (Ctrl+Shift+T)")
        act_local.triggered.connect(self._on_local_shell)
        tb.addAction(act_local)

        tb.addSeparator()

        act_splith = QAction("⊟ Split H", self)
        act_splith.setToolTip("Split terminal horizontally")
        act_splith.triggered.connect(self._on_split_horizontal)
        tb.addAction(act_splith)

        act_splitv = QAction("⊞ Split V", self)
        act_splitv.setToolTip("Split terminal vertically")
        act_splitv.triggered.connect(self._on_split_vertical)
        tb.addAction(act_splitv)

        act_unsplit = QAction("▣ Unsplit", self)
        act_unsplit.setToolTip("Remove splits")
        act_unsplit.triggered.connect(self._on_unsplit)
        tb.addAction(act_unsplit)

        tb.addSeparator()

        self._act_cluster = QAction("📡 Cluster", self)
        self._act_cluster.setToolTip("Cluster mode — send to all terminals")
        self._act_cluster.setCheckable(True)
        self._act_cluster.triggered.connect(self._on_cluster)
        tb.addAction(self._act_cluster)

        tb.addSeparator()

        act_prefs = QAction("⚙ Prefs", self)
        act_prefs.setToolTip("Open preferences")
        act_prefs.triggered.connect(self._on_preferences)
        tb.addAction(act_prefs)

    def _build_statusbar(self):
        """Build status bar with connection count and active terminal title."""
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

        self._status_conn_count = QLabel("Connections: 0")
        self._status_title = QLabel("")

        self._statusbar.addWidget(self._status_conn_count)
        self._statusbar.addPermanentWidget(self._status_title)
        self._update_status()

    def _connect_signals(self):
        """Wire up sidebar and terminal panel signals."""
        self.sidebar.connect_requested.connect(self._on_connect_requested)
        self.sidebar.edit_requested.connect(self._on_edit_requested)
        self.sidebar.delete_requested.connect(self._on_delete_requested)
        self.sidebar.add_requested.connect(self._on_add_connection)
        self.sidebar.add_group_requested.connect(self._on_add_group)

        # Update status bar when active terminal title changes
        try:
            active = self.terminal_panel.active_terminal
            if active:
                active.title_changed.connect(self._on_terminal_title_changed)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Sidebar signal handlers
    # ------------------------------------------------------------------

    def _on_connect_requested(self, conn_id: str):
        """Connect to the selected connection."""
        conn = self.connection_manager.get_connection(conn_id)
        if conn is None:
            QMessageBox.warning(self, "Not Found", f"Connection {conn_id!r} not found.")
            return
        self._do_connect(conn)

    def _on_edit_requested(self, conn_id: str):
        """Open the edit dialog for a connection."""
        conn = self.connection_manager.get_connection(conn_id)
        if conn is None:
            return
        if not _HAS_CONN_DIALOG:
            QMessageBox.information(
                self, "Not Available",
                "Connection editor dialog is not yet implemented."
            )
            return
        dlg = ConnectionDialog(self, self.connection_manager, self.credential_store, conn)
        if dlg.exec():
            self.sidebar.refresh()
            self._update_status()

    def _on_delete_requested(self, conn_id: str):
        """Confirm and delete a connection."""
        conn = self.connection_manager.get_connection(conn_id)
        name = conn.name if conn else conn_id
        reply = QMessageBox.question(
            self, "Delete Connection",
            f"Delete connection '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.connection_manager.delete_connection(conn_id)
            self.sidebar.refresh()
            self._update_status()

    def _on_add_connection(self):
        """Open dialog to add a new connection."""
        if not _HAS_CONN_DIALOG:
            QMessageBox.information(
                self, "Not Available",
                "Connection editor dialog is not yet implemented."
            )
            return
        dlg = ConnectionDialog(self, self.connection_manager, self.credential_store)
        if dlg.exec():
            self.sidebar.refresh()
            self._update_status()

    def _on_add_group(self):
        """Prompt user for a new group name."""
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Add Group", "Group name:")
        if ok and name.strip():
            self.connection_manager.add_group(name.strip())
            self.sidebar.refresh()

    # ------------------------------------------------------------------
    # Connection / terminal actions
    # ------------------------------------------------------------------

    def _do_connect(self, conn: Connection):
        """Create an SSH session and open it in a new terminal tab."""
        try:
            session = self.ssh_handler.create_session(conn)
        except Exception as exc:
            QMessageBox.critical(self, "Connection Error", str(exc))
            return

        title = conn.name or conn.display_name()
        self.terminal_panel.new_tab(session, conn, title)

        # Send post-login commands after a short delay
        post_cmds = self.ssh_handler.get_post_login_commands(conn)
        if post_cmds:
            QTimer.singleShot(500, lambda: self._send_post_commands(post_cmds))

        self._update_status()

    def _send_post_commands(self, commands: list[str]):
        """Send post-login commands to the currently active terminal."""
        try:
            terminal = self.terminal_panel.active_terminal
            if terminal:
                for cmd in commands:
                    terminal.send_text(cmd + "\n")
        except Exception:
            pass

    def _on_new_tab(self):
        """Open connection picker, then connect."""
        if not _HAS_CONN_DIALOG:
            QMessageBox.information(
                self, "Tip",
                "Double-click a connection in the sidebar to connect.\n"
                "Use the + button in the sidebar to add new connections."
            )
            return
        dlg = ConnectionDialog(self, self.connection_manager, self.credential_store)
        if dlg.exec():
            self.sidebar.refresh()

    def _on_local_shell(self):
        """Open a local shell tab."""
        try:
            session = self.ssh_handler.create_local_session()
            self.terminal_panel.new_tab(session, None, "Local Shell")
            self._update_status()
        except Exception as exc:
            QMessageBox.critical(self, "Local Shell Error", str(exc))

    def _on_split_horizontal(self):
        """Split the active pane horizontally."""
        try:
            pane = self.terminal_panel.active_pane
            idx = self.terminal_panel.active_pane_index
            if pane is not None:
                self.terminal_panel.split_horizontal(pane, idx)
        except Exception:
            pass

    def _on_split_vertical(self):
        """Split the active pane vertically."""
        try:
            pane = self.terminal_panel.active_pane
            idx = self.terminal_panel.active_pane_index
            if pane is not None:
                self.terminal_panel.split_vertical(pane, idx)
        except Exception:
            pass

    def _on_unsplit(self):
        """Remove all splits."""
        try:
            self.terminal_panel.unsplit()
        except Exception:
            pass

    def _on_cluster(self, checked: bool):
        """Toggle cluster mode or open cluster window."""
        if not _HAS_CLUSTER:
            self._act_cluster.setChecked(False)
            QMessageBox.information(
                self, "Not Available",
                "Cluster mode window is not yet implemented."
            )
            return
        if checked:
            dlg = ClusterWindow(self, self.terminal_panel)
            dlg.exec()
            self._act_cluster.setChecked(False)

    # ------------------------------------------------------------------
    # Menu / toolbar handlers (misc)
    # ------------------------------------------------------------------

    def _on_toggle_sidebar(self):
        visible = self.sidebar.isVisible()
        self.sidebar.setVisible(not visible)
        self.config["sidebar_visible"] = not visible

    def _on_preferences(self):
        if not _HAS_PREFS_DIALOG:
            QMessageBox.information(
                self, "Not Available",
                "Preferences dialog is not yet implemented."
            )
            return
        dlg = PreferencesDialog(self, self.config)
        dlg.exec()

    def _on_import(self):
        QMessageBox.information(self, "Import", "Import functionality coming soon.")

    def _on_export(self):
        QMessageBox.information(self, "Export", "Export functionality coming soon.")

    def _on_about(self):
        QMessageBox.about(
            self,
            "About SSH Client Manager",
            "<h3>SSH Client Manager</h3>"
            "<p>A PySide6 SSH connection manager with split terminals, "
            "cluster mode, and encrypted credential storage.</p>",
        )

    def _on_terminal_title_changed(self, title: str):
        self._status_title.setText(title)

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------

    def _update_status(self):
        count = len(self.connection_manager.get_connections())
        self._status_conn_count.setText(f"Connections: {count}")
        try:
            terminals = self.terminal_panel.get_all_terminals()
            n = len(terminals) if terminals else 0
            self._status_conn_count.setText(f"Connections: {count}  |  Open terminals: {n}")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Persistence / close
    # ------------------------------------------------------------------

    def _restore_sidebar_width(self):
        sidebar_visible = self.config.get("sidebar_visible", True)
        self.sidebar.setVisible(bool(sidebar_visible))

    def closeEvent(self, event: QCloseEvent):
        """Save window state and optionally confirm close."""
        if self.config.get("confirm_close_window", False):
            try:
                terminals = self.terminal_panel.get_all_terminals()
            except Exception:
                terminals = []
            if terminals:
                reply = QMessageBox.question(
                    self,
                    "Close SSH Client Manager",
                    f"There are {len(terminals)} open terminal(s). Really close?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return

        # Save window geometry
        self.config["window_width"] = self.width()
        self.config["window_height"] = self.height()
        sizes = self._splitter.sizes()
        if sizes:
            self.config["sidebar_width"] = sizes[0]
        self.config["sidebar_visible"] = self.sidebar.isVisible()
        try:
            self.config.save()
        except Exception:
            pass
        event.accept()
