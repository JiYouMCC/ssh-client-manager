"""
Main application window.

Combines the sidebar (connection tree), terminal panel (split tabs),
toolbar, and menu into the main PySide6 QMainWindow.
"""

from __future__ import annotations

import os
import sys
import time
import zipfile
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QToolBar, QStatusBar,
    QMenuBar, QMenu, QMessageBox, QApplication, QLabel,
    QLineEdit, QHBoxLayout, QFileDialog,
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

try:
    from .snippets import SnippetsManager
    from .snippets_dialog import SnippetsDialog
    _HAS_SNIPPETS = True
except ImportError:
    _HAS_SNIPPETS = False

try:
    from .sftp_browser import SFTPBrowser
    _HAS_SFTP = True
except ImportError:
    _HAS_SFTP = False

try:
    from .recording_dialog import RecordingDialog
    _HAS_RECORDING = True
except ImportError:
    _HAS_RECORDING = False

try:
    from .ssh_key_manager import SSHKeyManagerDialog
    _HAS_KEY_MANAGER = True
except ImportError:
    _HAS_KEY_MANAGER = False

try:
    from .ssh_config_editor import SSHConfigEditorDialog
    _HAS_CONFIG_EDITOR = True
except ImportError:
    _HAS_CONFIG_EDITOR = False


class MainWindow(QMainWindow):
    """
    The main application window.

    Layout:
    ┌──────────────────────────────────────────────────────┐
    │ MenuBar                                               │
    ├──────────────────────────────────────────────────────┤
    │ ToolBar  [New Tab][Local][Split...][Cluster][AI]...  │
    ├──────────┬──────────────────────────┬────────────────┤
    │ Sidebar  │ TerminalPanel            │ AI Panel       │
    │  Search  │  PaneTabWidget           │  (optional)    │
    │  Tree    │                          │                │
    ├──────────┴──────────────────────────┴────────────────┤
    │ StatusBar                                            │
    └──────────────────────────────────────────────────────┘
    """

    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.connection_manager = ConnectionManager()
        self.credential_store = CredentialStore()
        self.ssh_handler = SSHHandler(self.credential_store)
        self.snippets_manager = SnippetsManager() if _HAS_SNIPPETS else None
        self._snippets_dialog: Optional[object] = None

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
        self._setup_shortcuts()

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

        act_new_conn = QAction("&New Connection…", self)
        act_new_conn.setShortcut(QKeySequence("Ctrl+Shift+N"))
        act_new_conn.triggered.connect(self._on_add_connection)
        file_menu.addAction(act_new_conn)

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

        act_backup = QAction("📦 Backup All…", self)
        act_backup.triggered.connect(self._on_backup)
        file_menu.addAction(act_backup)

        act_restore = QAction("📂 Restore All…", self)
        act_restore.triggered.connect(self._on_restore)
        file_menu.addAction(act_restore)

        file_menu.addSeparator()

        act_quit = QAction("&Quit", self)
        act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        act_quit.triggered.connect(QApplication.instance().quit)
        file_menu.addAction(act_quit)

        # View
        view_menu = menubar.addMenu("&View")

        self._act_sidebar = QAction("Toggle &Sidebar", self)
        self._act_sidebar.setShortcut(QKeySequence("F9"))
        self._act_sidebar.triggered.connect(self._on_toggle_sidebar)
        view_menu.addAction(self._act_sidebar)

        view_menu.addSeparator()

        # Split submenu
        split_menu = view_menu.addMenu("&Split")
        for label, key, fn in [
            ("Split Left",  "Ctrl+Shift+Left",  self._on_split_left),
            ("Split Right", "Ctrl+Shift+Right", self._on_split_right),
            ("Split Up",    "Ctrl+Shift+Up",    self._on_split_up),
            ("Split Down",  "Ctrl+Shift+Down",  self._on_split_down),
        ]:
            a = QAction(label, self)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(fn)
            split_menu.addAction(a)

        act_unsplit = QAction("&Unsplit All", self)
        act_unsplit.triggered.connect(self._on_unsplit)
        view_menu.addAction(act_unsplit)

        view_menu.addSeparator()

        act_prefs = QAction("&Preferences…", self)
        act_prefs.setShortcut(QKeySequence("Ctrl+,"))
        act_prefs.triggered.connect(self._on_preferences)
        view_menu.addAction(act_prefs)

        # Tools
        tools_menu = menubar.addMenu("&Tools")

        act_snippets = QAction("✂ Command &Snippets…", self)
        act_snippets.setShortcut(QKeySequence("Ctrl+Shift+S"))
        act_snippets.triggered.connect(self._on_snippets)
        tools_menu.addAction(act_snippets)

        act_recordings = QAction("⏺ Session &Recordings…", self)
        act_recordings.triggered.connect(self._on_recordings)
        tools_menu.addAction(act_recordings)

        tools_menu.addSeparator()

        act_key_mgr = QAction("🔑 SSH &Key Manager…", self)
        act_key_mgr.triggered.connect(self._on_ssh_key_manager)
        tools_menu.addAction(act_key_mgr)

        act_ssh_cfg = QAction("📝 SSH &Config Editor…", self)
        act_ssh_cfg.triggered.connect(self._on_ssh_config_editor)
        tools_menu.addAction(act_ssh_cfg)

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

        # Quick Connect
        self._quick_connect = QLineEdit()
        self._quick_connect.setPlaceholderText("Quick Connect: ssh user@host")
        self._quick_connect.setFixedWidth(220)
        self._quick_connect.returnPressed.connect(self._on_quick_connect)
        tb.addWidget(self._quick_connect)

        tb.addSeparator()

        act_new_conn = QAction("＋ New", self)
        act_new_conn.setToolTip("New Connection (Ctrl+Shift+N)")
        act_new_conn.triggered.connect(self._on_add_connection)
        tb.addAction(act_new_conn)

        act_local = QAction("💻 Local Shell", self)
        act_local.setToolTip("Open local shell tab (Ctrl+Shift+T)")
        act_local.triggered.connect(self._on_local_shell)
        tb.addAction(act_local)

        tb.addSeparator()

        act_splith = QAction("⊢ Split ←", self)
        act_splith.setToolTip("Split Left (Ctrl+Shift+Left)")
        act_splith.triggered.connect(self._on_split_left)
        tb.addAction(act_splith)

        act_splithr = QAction("⊣ Split →", self)
        act_splithr.setToolTip("Split Right (Ctrl+Shift+Right)")
        act_splithr.triggered.connect(self._on_split_right)
        tb.addAction(act_splithr)

        act_splitu = QAction("⊤ Split ↑", self)
        act_splitu.setToolTip("Split Up (Ctrl+Shift+Up)")
        act_splitu.triggered.connect(self._on_split_up)
        tb.addAction(act_splitu)

        act_splitd = QAction("⊥ Split ↓", self)
        act_splitd.setToolTip("Split Down (Ctrl+Shift+Down)")
        act_splitd.triggered.connect(self._on_split_down)
        tb.addAction(act_splitd)

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

        self._act_record = QAction("⏺ Record", self)
        self._act_record.setToolTip("Start/stop session recording")
        self._act_record.setCheckable(True)
        self._act_record.triggered.connect(self._on_toggle_recording)
        tb.addAction(self._act_record)

        tb.addSeparator()

        act_prefs = QAction("⚙ Prefs", self)
        act_prefs.setToolTip("Open preferences")
        act_prefs.triggered.connect(self._on_preferences)
        tb.addAction(act_prefs)

    def _build_statusbar(self):
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

        self._status_conn_count = QLabel("Connections: 0")
        self._status_title = QLabel("")

        self._statusbar.addWidget(self._status_conn_count)
        self._statusbar.addPermanentWidget(self._status_title)
        self._update_status()

    def _setup_shortcuts(self):
        """Register global keyboard shortcuts not already on menu actions."""
        from PySide6.QtGui import QShortcut

        def _sc(key, fn):
            s = QShortcut(QKeySequence(key), self)
            s.activated.connect(fn)

        _sc("Ctrl+W",          self.terminal_panel.close_active_tab)
        _sc("Ctrl+Tab",        self.terminal_panel.next_tab)
        _sc("Ctrl+Shift+Tab",  self.terminal_panel.prev_tab)
        _sc("Ctrl+Shift+D",    self.terminal_panel.clone_active_tab)
        _sc("F9",              self._on_toggle_sidebar)

        # Zoom shortcuts (also handled in JS, but Python-side for consistency)
        _sc("Ctrl+=", lambda: self._zoom("in"))
        _sc("Ctrl++", lambda: self._zoom("in"))
        _sc("Ctrl+-", lambda: self._zoom("out"))
        _sc("Ctrl+0", lambda: self._zoom("reset"))

        # Alt+1..Alt+9  switch to tab by number
        for i in range(1, 10):
            _sc(f"Alt+{i}", lambda idx=i-1: self.terminal_panel.switch_to_tab(idx))

    def _connect_signals(self):
        """Wire up sidebar and terminal panel signals."""
        self.sidebar.connect_requested.connect(self._on_connect_requested)
        self.sidebar.edit_requested.connect(self._on_edit_requested)
        self.sidebar.delete_requested.connect(self._on_delete_requested)
        self.sidebar.add_requested.connect(self._on_add_connection)
        self.sidebar.add_group_requested.connect(self._on_add_group)
        self.sidebar.open_sftp_requested.connect(self._on_open_sftp)

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
        conn = self.connection_manager.get_connection(conn_id)
        if conn is None:
            QMessageBox.warning(self, "Not Found", f"Connection {conn_id!r} not found.")
            return
        # Handle "Open After" prerequisite
        if conn.open_after:
            prereq = self.connection_manager.get_connection(conn.open_after)
            if prereq:
                self._do_connect(prereq)
                QTimer.singleShot(2000, lambda: self._do_connect(conn))
                return
        self._do_connect(conn)

    def _on_edit_requested(self, conn_id: str):
        conn = self.connection_manager.get_connection(conn_id)
        if conn is None:
            return
        if not _HAS_CONN_DIALOG:
            return
        dlg = ConnectionDialog(self, self.connection_manager, self.credential_store, conn)
        if dlg.exec():
            self.sidebar.refresh()
            self._update_status()

    def _on_delete_requested(self, conn_id: str):
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
        if not _HAS_CONN_DIALOG:
            return
        dlg = ConnectionDialog(self, self.connection_manager, self.credential_store)
        if dlg.exec():
            self.sidebar.refresh()
            self._update_status()

    def _on_add_group(self):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Add Group", "Group name:")
        if ok and name.strip():
            self.connection_manager.add_group(name.strip())
            self.sidebar.refresh()

    def _on_open_sftp(self, conn_id: str):
        if not _HAS_SFTP:
            QMessageBox.information(self, "SFTP", "SFTP browser not available.")
            return
        conn = self.connection_manager.get_connection(conn_id)
        if conn is None:
            return
        dlg = SFTPBrowser(self, conn, self.credential_store)
        dlg.show()

    # ------------------------------------------------------------------
    # Connection / terminal actions
    # ------------------------------------------------------------------

    def _do_connect(self, conn: Connection):
        try:
            session = self.ssh_handler.create_session(conn)
        except Exception as exc:
            QMessageBox.critical(self, "Connection Error", str(exc))
            return

        title = conn.name or conn.display_name()
        self.terminal_panel.new_tab(session, conn, title)

        post_cmds = self.ssh_handler.get_post_login_commands(conn)
        if post_cmds:
            QTimer.singleShot(500, lambda: self._send_post_commands(post_cmds))

        self._update_status()

    def _send_post_commands(self, commands: list[str]):
        try:
            terminal = self.terminal_panel.active_terminal
            if terminal:
                for cmd in commands:
                    terminal.send_text(cmd + "\n")
        except Exception:
            pass

    def _on_new_tab(self):
        if not _HAS_CONN_DIALOG:
            return
        dlg = ConnectionDialog(self, self.connection_manager, self.credential_store)
        if dlg.exec():
            self.sidebar.refresh()

    def _on_local_shell(self):
        try:
            shell_pref = self.config.get("local_shell_windows", "auto")
            session = self.ssh_handler.create_local_session(shell_preference=shell_pref)
            self.terminal_panel.new_tab(session, None, "Local Shell")
            self._update_status()
        except Exception as exc:
            QMessageBox.critical(self, "Local Shell Error", str(exc))

    def _on_quick_connect(self):
        text = self._quick_connect.text().strip()
        if not text:
            return
        # If no "ssh" prefix, add it
        if not text.startswith("ssh "):
            text = f"ssh {text}"
        temp_conn = Connection(name=text, command=text)
        self._quick_connect.clear()
        try:
            session = self.ssh_handler.create_session(temp_conn)
            self.terminal_panel.new_tab(session, temp_conn, text)
            self._update_status()
        except Exception as exc:
            QMessageBox.critical(self, "Quick Connect Error", str(exc))

    # ------------------------------------------------------------------
    # Split actions
    # ------------------------------------------------------------------

    def _on_split_left(self):
        pane = self.terminal_panel.active_pane
        idx = self.terminal_panel.active_pane_index
        if pane is not None:
            self.terminal_panel.split_horizontal(pane, idx)

    def _on_split_right(self):
        pane = self.terminal_panel.active_pane
        idx = self.terminal_panel.active_pane_index
        if pane is not None:
            self.terminal_panel.split_horizontal_right(pane, idx)

    def _on_split_up(self):
        pane = self.terminal_panel.active_pane
        idx = self.terminal_panel.active_pane_index
        if pane is not None:
            self.terminal_panel.split_vertical(pane, idx)

    def _on_split_down(self):
        pane = self.terminal_panel.active_pane
        idx = self.terminal_panel.active_pane_index
        if pane is not None:
            self.terminal_panel.split_vertical_down(pane, idx)

    def _on_unsplit(self):
        try:
            self.terminal_panel.unsplit()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Zoom
    # ------------------------------------------------------------------

    def _zoom(self, direction: str):
        term = self.terminal_panel.active_terminal
        if term is None:
            return
        if direction == "in":
            term.zoom_in()
        elif direction == "out":
            term.zoom_out()
        else:
            term.zoom_reset()

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def _on_toggle_recording(self, checked: bool):
        term = self.terminal_panel.active_terminal
        if term is None:
            self._act_record.setChecked(False)
            return
        if checked:
            term._start_recording_prompt()
        else:
            term.stop_recording()

    # ------------------------------------------------------------------
    # Tools menu handlers
    # ------------------------------------------------------------------

    def _on_cluster(self, checked: bool):
        if not _HAS_CLUSTER:
            self._act_cluster.setChecked(False)
            return
        if checked:
            dlg = ClusterWindow(self, self.terminal_panel)
            dlg.exec()
            self._act_cluster.setChecked(False)

    def _on_snippets(self):
        if not _HAS_SNIPPETS:
            QMessageBox.information(self, "Snippets", "Command Snippets not available.")
            return
        if self._snippets_dialog is None or not self._snippets_dialog.isVisible():
            self._snippets_dialog = SnippetsDialog(
                self, self.snippets_manager, self.terminal_panel
            )
        self._snippets_dialog.show()
        self._snippets_dialog.raise_()

    def _on_recordings(self):
        if not _HAS_RECORDING:
            QMessageBox.information(self, "Recordings", "Recording player not available.")
            return
        dlg = RecordingDialog(self, self.config)
        dlg.exec()

    def _on_ssh_key_manager(self):
        if not _HAS_KEY_MANAGER:
            QMessageBox.information(self, "SSH Keys", "SSH Key Manager not available.")
            return
        dlg = SSHKeyManagerDialog(self)
        dlg.exec()

    def _on_ssh_config_editor(self):
        if not _HAS_CONFIG_EDITOR:
            QMessageBox.information(self, "SSH Config", "SSH Config Editor not available.")
            return
        dlg = SSHConfigEditorDialog(self)
        dlg.exec()

    # ------------------------------------------------------------------
    # Menu / toolbar handlers (misc)
    # ------------------------------------------------------------------

    def _on_toggle_sidebar(self):
        visible = self.sidebar.isVisible()
        self.sidebar.setVisible(not visible)
        self.config["sidebar_visible"] = not visible

    def _on_preferences(self):
        if not _HAS_PREFS_DIALOG:
            return
        dlg = PreferencesDialog(self, self.config)
        dlg.exec()

    def _on_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Connections", "", "JSON files (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            with open(path, "r") as f:
                json_str = f.read()
            reply = QMessageBox.question(
                self, "Import Mode",
                "Overwrite existing connections, or append?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            replace = (reply == QMessageBox.StandardButton.Yes)
            self.connection_manager.import_connections(json_str, replace=replace)
            self.sidebar.refresh()
            self._update_status()
            QMessageBox.information(self, "Import", "Connections imported successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Import Error", str(e))

    def _on_export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Connections", "connections.json", "JSON files (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            json_str = self.connection_manager.export_connections()
            with open(path, "w") as f:
                f.write(json_str)
            QMessageBox.information(self, "Export", f"Connections exported to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def _on_backup(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Backup All", f"ssh-client-manager-backup-{time.strftime('%Y%m%d')}.zip",
            "ZIP files (*.zip);;All files (*)"
        )
        if not path:
            return
        try:
            from .config import get_config_dir
            cfg_dir = get_config_dir()
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                for fname in ["config.json", "connections.json", "snippets.json",
                               ".store.key", ".credentials.enc"]:
                    src = cfg_dir / fname
                    if src.exists():
                        zf.write(src, fname)
            QMessageBox.information(self, "Backup", f"Backup saved to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Backup Error", str(e))

    def _on_restore(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Restore All", "", "ZIP files (*.zip);;All files (*)"
        )
        if not path:
            return
        reply = QMessageBox.question(
            self, "Restore",
            "This will replace ALL current configuration. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            from .config import get_config_dir
            cfg_dir = get_config_dir()
            with zipfile.ZipFile(path, "r") as zf:
                zf.extractall(cfg_dir)
            # Reload connection manager
            self.connection_manager.load()
            self.sidebar.refresh()
            self._update_status()
            QMessageBox.information(self, "Restore", "Restore complete. Please restart for all settings to take effect.")
        except Exception as e:
            QMessageBox.critical(self, "Restore Error", str(e))

    def _on_about(self):
        QMessageBox.about(
            self,
            "About SSH Client Manager",
            "<h3>SSH Client Manager</h3>"
            "<p>A PySide6 SSH connection manager with split terminals, "
            "cluster mode, command snippets, SFTP browser, session recording, "
            "AI assistant, and encrypted credential storage.</p>",
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

