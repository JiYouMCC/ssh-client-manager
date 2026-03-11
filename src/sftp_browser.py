"""
SFTP Browser dialog — browse, upload, and download remote files over SSH.

Uses paramiko directly (no SSHSession WebSocket bridge) so we can access
the SFTP subsystem without a PTY.
"""

from __future__ import annotations

import os
import shlex
import stat
import threading
from pathlib import Path
from typing import Optional

import paramiko
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .connection import Connection
from .credential_store import CredentialStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _human_size(n: int) -> str:
    """Return a human-readable file size string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _permissions_str(mode: int) -> str:
    """Convert a stat mode integer to a rwx string (e.g. drwxr-xr-x)."""
    flags = [
        (stat.S_IRUSR, "r"), (stat.S_IWUSR, "w"), (stat.S_IXUSR, "x"),
        (stat.S_IRGRP, "r"), (stat.S_IWGRP, "w"), (stat.S_IXGRP, "x"),
        (stat.S_IROTH, "r"), (stat.S_IWOTH, "w"), (stat.S_IXOTH, "x"),
    ]
    bits = "".join(c if mode & f else "-" for f, c in flags)
    if stat.S_ISDIR(mode):
        return "d" + bits
    if stat.S_ISLNK(mode):
        return "l" + bits
    return "-" + bits


def _parse_ssh_params(command: str) -> dict:
    """
    Extract hostname, port, username and key_file from a raw SSH command string.
    Mirrors the logic in SSHHandler._parse_ssh_params without requiring the class.
    """
    params = {"hostname": "", "port": 22, "username": "", "key_file": ""}
    if not command:
        return params

    cmd = " ".join(command.strip().splitlines())
    try:
        argv = shlex.split(cmd)
    except ValueError:
        argv = cmd.split()

    i = 1  # skip "ssh"
    positional: list[str] = []
    while i < len(argv):
        arg = argv[i]
        if arg == "-p" and i + 1 < len(argv):
            try:
                params["port"] = int(argv[i + 1])
            except ValueError:
                pass
            i += 2
        elif arg == "-i" and i + 1 < len(argv):
            params["key_file"] = argv[i + 1]
            i += 2
        elif arg == "-l" and i + 1 < len(argv):
            params["username"] = argv[i + 1]
            i += 2
        elif arg.startswith("-"):
            # skip flags that consume the next token
            if len(arg) == 2 and arg[1] in "bceFIJLmOoQRDSw" and i + 1 < len(argv):
                i += 2
            else:
                i += 1
        else:
            positional.append(arg)
            i += 1

    if positional:
        dest = positional[-1]
        if "@" in dest:
            params["username"], params["hostname"] = dest.rsplit("@", 1)
        else:
            params["hostname"] = dest

    return params


# ---------------------------------------------------------------------------
# Background worker signals
# ---------------------------------------------------------------------------

class _WorkerSignals(QObject):
    progress = Signal(int, int)   # bytes_done, bytes_total
    finished = Signal()
    error = Signal(str)


# ---------------------------------------------------------------------------
# Transfer worker (download / upload in a thread)
# ---------------------------------------------------------------------------

class _TransferWorker(threading.Thread):
    """Runs a paramiko SFTP transfer in a daemon thread, emitting Qt signals."""

    _CHUNK = 32_768  # 32 KB read/write chunks

    def __init__(
        self,
        sftp: paramiko.SFTPClient,
        remote_path: str,
        local_path: Path,
        direction: str,   # "download" or "upload"
    ):
        super().__init__(daemon=True)
        self._sftp = sftp
        self._remote = remote_path
        self._local = local_path
        self._direction = direction
        self.signals = _WorkerSignals()

    def run(self) -> None:
        try:
            if self._direction == "download":
                self._download()
            else:
                self._upload()
            self.signals.finished.emit()
        except Exception as exc:
            self.signals.error.emit(str(exc))

    def _download(self) -> None:
        file_stat = self._sftp.stat(self._remote)
        total = file_stat.st_size or 0
        done = 0
        self._local.parent.mkdir(parents=True, exist_ok=True)
        with self._sftp.open(self._remote, "rb") as remote_fh:
            with open(self._local, "wb") as local_fh:
                while True:
                    chunk = remote_fh.read(self._CHUNK)
                    if not chunk:
                        break
                    local_fh.write(chunk)
                    done += len(chunk)
                    self.signals.progress.emit(done, total)

    def _upload(self) -> None:
        total = self._local.stat().st_size
        done = 0
        with open(self._local, "rb") as local_fh:
            with self._sftp.open(self._remote, "wb") as remote_fh:
                while True:
                    chunk = local_fh.read(self._CHUNK)
                    if not chunk:
                        break
                    remote_fh.write(chunk)
                    done += len(chunk)
                    self.signals.progress.emit(done, total)


# ---------------------------------------------------------------------------
# SFTPBrowser dialog
# ---------------------------------------------------------------------------

class SFTPBrowser(QDialog):
    """Non-modal dialog for browsing a remote filesystem via paramiko SFTP."""

    # Columns
    _COL_NAME = 0
    _COL_SIZE = 1
    _COL_MODIFIED = 2
    _COL_PERMS = 3

    def __init__(
        self,
        parent: QWidget,
        connection: Connection,
        credential_store: CredentialStore,
    ):
        super().__init__(parent)
        self._conn = connection
        self._creds = credential_store
        self._ssh: Optional[paramiko.SSHClient] = None
        self._sftp: Optional[paramiko.SFTPClient] = None
        self._home_dir: str = "/"
        self._current_path: str = "/"
        self._history: list[str] = []
        self._sort_col: int = self._COL_NAME
        self._sort_asc: bool = True
        self._active_transfer: Optional[_TransferWorker] = None

        self.setWindowTitle(f"SFTP — {connection.name}")
        self.resize(900, 600)
        self.setMinimumSize(600, 400)

        self._build_ui()
        self._connect_sftp()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Toolbar
        toolbar = QToolBar()
        toolbar.setMovable(False)

        self._act_back = QAction("← Back", self)
        self._act_back.setToolTip("Navigate back")
        self._act_back.triggered.connect(self._go_back)
        toolbar.addAction(self._act_back)

        self._act_up = QAction("↑ Up", self)
        self._act_up.setToolTip("Go to parent directory")
        self._act_up.triggered.connect(self._go_up)
        toolbar.addAction(self._act_up)

        self._act_home = QAction("🏠 Home", self)
        self._act_home.setToolTip("Go to home directory")
        self._act_home.triggered.connect(self._go_home)
        toolbar.addAction(self._act_home)

        self._act_refresh = QAction("🔄 Refresh", self)
        self._act_refresh.setToolTip("Refresh current directory")
        self._act_refresh.triggered.connect(self._refresh)
        toolbar.addAction(self._act_refresh)

        toolbar.addSeparator()

        self._act_upload = QAction("📤 Upload", self)
        self._act_upload.setToolTip("Upload a file to the current directory")
        self._act_upload.triggered.connect(self._upload_file)
        toolbar.addAction(self._act_upload)

        root.addWidget(toolbar)

        # Path bar
        path_bar = QWidget()
        path_layout = QHBoxLayout(path_bar)
        path_layout.setContentsMargins(6, 4, 6, 4)
        path_layout.setSpacing(4)
        path_layout.addWidget(QLabel("Path:"))
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("/")
        self._path_edit.returnPressed.connect(self._navigate_to_path_bar)
        path_layout.addWidget(self._path_edit)
        root.addWidget(path_bar)

        # File list
        self._tree = QTreeWidget()
        self._tree.setColumnCount(4)
        self._tree.setHeaderLabels(["Name", "Size", "Modified", "Permissions"])
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.setSortingEnabled(False)  # we sort manually
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        self._tree.header().sectionClicked.connect(self._on_header_click)
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._tree)

        # Status bar
        status_widget = QWidget()
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(6, 2, 6, 2)
        self._status_label = QLabel("Connecting…")
        self._status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedWidth(180)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.hide()
        status_layout.addWidget(self._status_label)
        status_layout.addWidget(self._progress_bar)
        root.addWidget(status_widget)

    # ------------------------------------------------------------------
    # SFTP connection
    # ------------------------------------------------------------------

    def _connect_sftp(self) -> None:
        """Open SSH + SFTP connection in a background thread."""
        t = threading.Thread(target=self._connect_thread, daemon=True)
        t.start()

    def _connect_thread(self) -> None:
        params = _parse_ssh_params(self._conn.command)
        hostname = params["hostname"]
        port = params["port"]
        username = params["username"] or None
        key_file = params["key_file"] or None
        password = self._creds.get_password(self._conn.id)
        passphrase1 = self._creds.get_passphrase1(self._conn.id) or None
        passphrase2 = self._creds.get_passphrase2(self._conn.id) or None

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            connect_kwargs: dict = {
                "hostname": hostname,
                "port": port,
                "look_for_keys": False,
                "allow_agent": True,
            }
            if username:
                connect_kwargs["username"] = username

            connected = False

            # 1) Try key file auth
            if key_file:
                for pp in (passphrase1, passphrase2, None):
                    try:
                        client.connect(
                            **connect_kwargs,
                            key_filename=key_file,
                            passphrase=pp,
                        )
                        connected = True
                        break
                    except (paramiko.AuthenticationException, paramiko.SSHException):
                        continue

            # 2) Try password auth
            if not connected and password:
                client.connect(**connect_kwargs, password=password)
                connected = True

            # 3) Try agent / default keys as last resort
            if not connected:
                client.connect(**connect_kwargs, look_for_keys=True, allow_agent=True)
                connected = True

            sftp = client.open_sftp()
            home = sftp.normalize(".")

            self._ssh = client
            self._sftp = sftp
            self._home_dir = home

            # Switch to UI thread via queued slot
            from PySide6.QtCore import QMetaObject, Q_ARG
            QMetaObject.invokeMethod(
                self, "_on_connected",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, home),
            )

        except Exception as exc:
            client.close()
            from PySide6.QtCore import QMetaObject, Q_ARG
            QMetaObject.invokeMethod(
                self, "_on_connect_error",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, str(exc)),
            )

    # Slots called from the background thread via QMetaObject.invokeMethod
    def _on_connected(self, home: str) -> None:
        self._set_status(f"Connected to {self._conn.name}")
        self._load_directory(home)

    def _on_connect_error(self, message: str) -> None:
        self._set_status(f"Connection failed: {message}", error=True)
        QMessageBox.critical(
            self,
            "Connection Error",
            f"Could not connect to {self._conn.name}:\n\n{message}",
        )

    # ------------------------------------------------------------------
    # Directory listing
    # ------------------------------------------------------------------

    def _load_directory(self, path: str) -> None:
        if not self._sftp:
            return
        try:
            entries = self._sftp.listdir_attr(path)
        except Exception as exc:
            self._set_status(f"Error listing {path}: {exc}", error=True)
            return

        self._current_path = path
        self._path_edit.setText(path)
        self._tree.clear()

        dirs: list[QTreeWidgetItem] = []
        files: list[QTreeWidgetItem] = []

        for attr in entries:
            name = attr.filename
            is_dir = stat.S_ISDIR(attr.st_mode) if attr.st_mode else False
            size_str = "—" if is_dir else _human_size(attr.st_size or 0)
            import datetime
            mtime = attr.st_mtime or 0
            mod_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M") if mtime else ""
            perm_str = _permissions_str(attr.st_mode) if attr.st_mode else ""

            item = QTreeWidgetItem([name, size_str, mod_str, perm_str])
            item.setData(0, Qt.ItemDataRole.UserRole, is_dir)
            # Store raw size for numeric sorting
            item.setData(1, Qt.ItemDataRole.UserRole, attr.st_size or 0)
            # Store raw mtime for sorting
            item.setData(2, Qt.ItemDataRole.UserRole, mtime)

            if is_dir:
                dirs.append(item)
            else:
                files.append(item)

        # Sort each group
        key_fn = self._sort_key
        dirs.sort(key=key_fn, reverse=not self._sort_asc)
        files.sort(key=key_fn, reverse=not self._sort_asc)

        for item in dirs + files:
            self._tree.addTopLevelItem(item)

        count = len(dirs) + len(files)
        self._set_status(f"{count} item{'s' if count != 1 else ''} in {path}")

        self._act_back.setEnabled(bool(self._history))
        self._act_up.setEnabled(path != "/")

    def _sort_key(self, item: QTreeWidgetItem):
        if self._sort_col == self._COL_NAME:
            return item.text(0).lower()
        if self._sort_col == self._COL_SIZE:
            return item.data(1, Qt.ItemDataRole.UserRole) or 0
        if self._sort_col == self._COL_MODIFIED:
            return item.data(2, Qt.ItemDataRole.UserRole) or 0
        if self._sort_col == self._COL_PERMS:
            return item.text(3)
        return item.text(0).lower()

    def _navigate(self, path: str) -> None:
        if path == self._current_path:
            return
        self._history.append(self._current_path)
        self._load_directory(path)

    def _navigate_to_path_bar(self) -> None:
        self._navigate(self._path_edit.text().strip() or "/")

    # ------------------------------------------------------------------
    # Toolbar actions
    # ------------------------------------------------------------------

    def _go_back(self) -> None:
        if self._history:
            self._load_directory(self._history.pop())

    def _go_up(self) -> None:
        parent = str(Path(self._current_path).parent).replace("\\", "/")
        if parent and parent != self._current_path:
            self._navigate(parent)

    def _go_home(self) -> None:
        self._navigate(self._home_dir)

    def _refresh(self) -> None:
        self._load_directory(self._current_path)

    def _on_header_click(self, col: int) -> None:
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True
        self._load_directory(self._current_path)

    # ------------------------------------------------------------------
    # Item interaction
    # ------------------------------------------------------------------

    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        is_dir = item.data(0, Qt.ItemDataRole.UserRole)
        name = item.text(0)
        remote_path = self._join(self._current_path, name)
        if is_dir:
            self._navigate(remote_path)
        else:
            dest = Path.home() / "Downloads" / name
            self._start_download(remote_path, dest)

    def _show_context_menu(self, pos) -> None:
        selected = self._tree.selectedItems()
        menu = QMenu(self)

        if selected:
            single = selected[0] if len(selected) == 1 else None
            is_dir = single.data(0, Qt.ItemDataRole.UserRole) if single else False

            if single and not is_dir:
                dl_action = menu.addAction("⬇ Download")
                dl_action.triggered.connect(lambda: self._download_selected(single))

            upload_action = menu.addAction("⬆ Upload here")
            upload_action.triggered.connect(self._upload_file)

            if single:
                rename_action = menu.addAction("✏ Rename")
                rename_action.triggered.connect(lambda: self._rename_item(single))

                delete_action = menu.addAction("🗑 Delete")
                delete_action.triggered.connect(lambda: self._delete_selected(selected))

            menu.addSeparator()

        new_folder_action = menu.addAction("📁 New Folder")
        new_folder_action.triggered.connect(self._new_folder)

        menu.exec(self._tree.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def _download_selected(self, item: QTreeWidgetItem) -> None:
        name = item.text(0)
        remote_path = self._join(self._current_path, name)
        dest = Path.home() / "Downloads" / name
        self._start_download(remote_path, dest)

    def _start_download(self, remote_path: str, local_path: Path) -> None:
        if not self._sftp:
            return
        worker = _TransferWorker(self._sftp, remote_path, local_path, "download")
        worker.signals.progress.connect(self._on_transfer_progress)
        worker.signals.finished.connect(
            lambda: self._on_transfer_done(f"Downloaded → {local_path}")
        )
        worker.signals.error.connect(self._on_transfer_error)
        self._active_transfer = worker
        self._progress_bar.setValue(0)
        self._progress_bar.show()
        self._set_status(f"Downloading {Path(remote_path).name}…")
        worker.start()

    def _upload_file(self) -> None:
        if not self._sftp:
            return
        local_path, _ = QFileDialog.getOpenFileName(self, "Select file to upload")
        if not local_path:
            return
        local = Path(local_path)
        remote_path = self._join(self._current_path, local.name)
        worker = _TransferWorker(self._sftp, remote_path, local, "upload")
        worker.signals.progress.connect(self._on_transfer_progress)
        worker.signals.finished.connect(
            lambda: self._on_transfer_done(f"Uploaded {local.name}")
        )
        worker.signals.error.connect(self._on_transfer_error)
        self._active_transfer = worker
        self._progress_bar.setValue(0)
        self._progress_bar.show()
        self._set_status(f"Uploading {local.name}…")
        worker.start()

    def _rename_item(self, item: QTreeWidgetItem) -> None:
        if not self._sftp:
            return
        from PySide6.QtWidgets import QInputDialog
        old_name = item.text(0)
        new_name, ok = QInputDialog.getText(
            self, "Rename", "New name:", text=old_name
        )
        if not ok or not new_name or new_name == old_name:
            return
        old_path = self._join(self._current_path, old_name)
        new_path = self._join(self._current_path, new_name)
        try:
            self._sftp.rename(old_path, new_path)
            self._refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Rename Failed", str(exc))

    def _delete_selected(self, items: list[QTreeWidgetItem]) -> None:
        if not self._sftp:
            return
        names = [i.text(0) for i in items]
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete {len(names)} item(s)?\n" + "\n".join(names),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        errors: list[str] = []
        for item in items:
            name = item.text(0)
            is_dir = item.data(0, Qt.ItemDataRole.UserRole)
            remote_path = self._join(self._current_path, name)
            try:
                if is_dir:
                    self._sftp.rmdir(remote_path)
                else:
                    self._sftp.remove(remote_path)
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        if errors:
            QMessageBox.warning(self, "Delete Errors", "\n".join(errors))
        self._refresh()

    def _new_folder(self) -> None:
        if not self._sftp:
            return
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if not ok or not name:
            return
        remote_path = self._join(self._current_path, name)
        try:
            self._sftp.mkdir(remote_path)
            self._refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Create Folder Failed", str(exc))

    # ------------------------------------------------------------------
    # Transfer callbacks
    # ------------------------------------------------------------------

    def _on_transfer_progress(self, done: int, total: int) -> None:
        if total > 0:
            pct = int(done * 100 / total)
            self._progress_bar.setValue(pct)
            self._progress_bar.setFormat(
                f"{_human_size(done)} / {_human_size(total)} ({pct}%)"
            )
        else:
            self._progress_bar.setFormat(_human_size(done))

    def _on_transfer_done(self, message: str) -> None:
        self._progress_bar.setValue(100)
        self._progress_bar.hide()
        self._set_status(message)
        self._refresh()

    def _on_transfer_error(self, message: str) -> None:
        self._progress_bar.hide()
        self._set_status(f"Transfer failed: {message}", error=True)
        QMessageBox.warning(self, "Transfer Error", message)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_status(self, text: str, *, error: bool = False) -> None:
        self._status_label.setText(text)
        color = "red" if error else ""
        self._status_label.setStyleSheet(f"color: {color};" if color else "")

    @staticmethod
    def _join(base: str, name: str) -> str:
        """POSIX-safe path join for remote paths."""
        return base.rstrip("/") + "/" + name

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        if self._sftp:
            try:
                self._sftp.close()
            except Exception:
                pass
        if self._ssh:
            try:
                self._ssh.close()
            except Exception:
                pass
        super().closeEvent(event)
