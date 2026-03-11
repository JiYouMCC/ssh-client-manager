"""
Connection add/edit dialog (PySide6).

Tabs:
  Properties: Group, Name, Description, Command, Credentials, TERM
  Commands:   Post-login commands
  Appearance: Font, colors
"""

from typing import Optional
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QTabWidget, QWidget, QFormLayout,
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QTextEdit,
    QComboBox, QPushButton, QColorDialog, QMessageBox, QSizePolicy,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QCheckBox,
)

from .connection import Connection, ConnectionManager
from .credential_store import CredentialStore


class ConnectionDialog(QDialog):
    """
    Dialog for adding or editing a connection.

    Emits connection_saved(Connection) on successful save.
    """

    connection_saved = Signal(object)

    def __init__(
        self,
        parent,
        connection_manager: ConnectionManager,
        credential_store: CredentialStore,
        connection: Optional[Connection] = None,
    ):
        super().__init__(parent)
        self.connection_manager = connection_manager
        self.credential_store = credential_store
        self.connection = connection
        is_edit = connection is not None

        self.setWindowTitle("Edit Connection" if is_edit else "New Connection")
        self.setMinimumSize(620, 620)
        self.setModal(True)

        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._build_properties_tab(), "Properties")
        tabs.addTab(self._build_tunnels_tab(), "Tunnels")
        tabs.addTab(self._build_commands_tab(), "Commands")
        tabs.addTab(self._build_appearance_tab(), "Appearance")
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if is_edit:
            self._populate(connection)

    # ------------------------------------------------------------------
    # Tab builders
    # ------------------------------------------------------------------

    def _build_properties_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._combo_group = QComboBox()
        self._combo_group.setEditable(True)
        self._combo_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._combo_group.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._combo_group.setMinimumContentsLength(30)
        self._combo_group.addItem("")
        for g in self.connection_manager.get_groups():
            self._combo_group.addItem(g)
        form.addRow("Group:", self._combo_group)

        self._entry_name = QLineEdit()
        self._entry_name.setPlaceholderText("My Server")
        form.addRow("Name:", self._entry_name)

        self._entry_desc = QLineEdit()
        self._entry_desc.setPlaceholderText("Optional description")
        form.addRow("Description:", self._entry_desc)

        self._chk_favorite = QCheckBox("Mark as favorite (⭐)")
        form.addRow("Favorite:", self._chk_favorite)

        self._entry_tags = QLineEdit()
        self._entry_tags.setPlaceholderText("e.g. production, web, linux")
        form.addRow("Tags:", self._entry_tags)

        # Open After: connection that auto-connects before this one
        self._combo_open_after = QComboBox()
        self._combo_open_after.addItem("(none)", "")
        for conn in self.connection_manager.get_connections():
            if conn.id != (self.connection.id if self.connection else ""):
                self._combo_open_after.addItem(conn.name or conn.display_name(), conn.id)
        form.addRow("Open After:", self._combo_open_after)

        self._text_command = QTextEdit()
        self._text_command.setPlaceholderText(
            'ssh -p 22 user@hostname\n'
            '# Multi-line commands are joined with spaces'
        )
        self._text_command.setMinimumHeight(80)
        self._text_command.setMaximumHeight(120)
        form.addRow("SSH Command:", self._text_command)

        # Key file row: path display + browse button
        key_row = QHBoxLayout()
        self._entry_key = QLineEdit()
        self._entry_key.setPlaceholderText("Optional: /path/to/key.pem")
        self._entry_key.setReadOnly(False)
        self._entry_key.textChanged.connect(self._on_key_path_changed)
        key_row.addWidget(self._entry_key)

        btn_browse = QPushButton("Browse…")
        btn_browse.setFixedWidth(80)
        btn_browse.clicked.connect(self._browse_key_file)
        key_row.addWidget(btn_browse)

        btn_clear_key = QPushButton("✕")
        btn_clear_key.setFixedWidth(28)
        btn_clear_key.setToolTip("Clear key file")
        btn_clear_key.clicked.connect(self._clear_key_file)
        key_row.addWidget(btn_clear_key)

        key_widget = QWidget()
        key_widget.setLayout(key_row)
        form.addRow("Key File (-i):", key_widget)

        self._entry_password = QLineEdit()
        self._entry_password.setEchoMode(QLineEdit.EchoMode.Password)
        self._entry_password.setPlaceholderText("Leave empty for key/interactive auth")
        form.addRow("Password:", self._entry_password)

        self._entry_pp1 = QLineEdit()
        self._entry_pp1.setEchoMode(QLineEdit.EchoMode.Password)
        self._entry_pp1.setPlaceholderText("SSH key passphrase")
        form.addRow("Passphrase 1:", self._entry_pp1)

        self._entry_pp2 = QLineEdit()
        self._entry_pp2.setEchoMode(QLineEdit.EchoMode.Password)
        self._entry_pp2.setPlaceholderText("Second key passphrase (optional)")
        form.addRow("Passphrase 2:", self._entry_pp2)

        self._combo_term = QComboBox()
        self._combo_term.setEditable(True)
        for t in ["xterm-256color", "xterm", "vt100", "screen-256color"]:
            self._combo_term.addItem(t)
        form.addRow("TERM:", self._combo_term)

        return w

    def _build_tunnels_tab(self) -> QWidget:
        """
        Port forwarding editor.

        Each row represents one tunnel:
          Type | Local Port | Remote Host | Remote Port | [✕]

        For -D (SOCKS dynamic) Remote Host and Remote Port are disabled.
        """
        w = QWidget()
        layout = QVBoxLayout(w)

        hint = QLabel(
            "Add port-forwarding rules.  They are saved as -L / -R / -D flags in the SSH command.\n"
            "  Local (-L):   traffic on Local Port → Remote Host:Remote Port\n"
            "  Remote (-R):  remote side listens on Local Port → connects back to Remote Host:Remote Port\n"
            "  SOCKS (-D):   local SOCKS5 proxy on Local Port"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._tunnel_table = QTableWidget(0, 5)
        self._tunnel_table.setHorizontalHeaderLabels(
            ["Type", "Local Port", "Remote Host", "Remote Port", ""]
        )
        hh = self._tunnel_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._tunnel_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._tunnel_table.verticalHeader().setVisible(False)
        self._tunnel_table.setAlternatingRowColors(True)
        layout.addWidget(self._tunnel_table)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("＋  Add Tunnel")
        btn_add.clicked.connect(self._add_tunnel_row)
        btn_row.addWidget(btn_add)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        return w

    def _add_tunnel_row(
        self,
        ttype: str = "L",
        local_port: str = "",
        remote_host: str = "",
        remote_port: str = "",
    ):
        """Append a new row to the tunnel table."""
        row = self._tunnel_table.rowCount()
        self._tunnel_table.insertRow(row)

        # Type combo
        combo = QComboBox()
        combo.addItems(["L — Local", "R — Remote", "D — SOCKS"])
        idx = {"L": 0, "R": 1, "D": 2}.get(ttype, 0)
        combo.setCurrentIndex(idx)
        combo.currentIndexChanged.connect(
            lambda _, r=row: self._on_tunnel_type_changed(r)
        )
        self._tunnel_table.setCellWidget(row, 0, combo)

        lp = QTableWidgetItem(local_port)
        lp.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tunnel_table.setItem(row, 1, lp)

        rh = QTableWidgetItem(remote_host)
        self._tunnel_table.setItem(row, 2, rh)

        rp = QTableWidgetItem(remote_port)
        rp.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tunnel_table.setItem(row, 3, rp)

        btn_del = QPushButton("✕")
        btn_del.setFixedWidth(28)
        btn_del.setToolTip("Remove this tunnel")
        btn_del.clicked.connect(lambda _, r=row: self._remove_tunnel_row(r))
        self._tunnel_table.setCellWidget(row, 4, btn_del)

        if ttype == "D":
            self._set_tunnel_row_socks(row, True)

    def _on_tunnel_type_changed(self, row: int):
        combo = self._tunnel_table.cellWidget(row, 0)
        if combo is None:
            return
        is_socks = combo.currentIndex() == 2
        self._set_tunnel_row_socks(row, is_socks)

    def _set_tunnel_row_socks(self, row: int, socks: bool):
        """For SOCKS (-D) rows, grey-out Remote Host / Remote Port cells."""
        for col in (2, 3):
            item = self._tunnel_table.item(row, col)
            if item is None:
                item = QTableWidgetItem("")
                self._tunnel_table.setItem(row, col, item)
            flags = item.flags()
            if socks:
                item.setText("")
                item.setFlags(flags & ~Qt.ItemFlag.ItemIsEnabled)
            else:
                item.setFlags(flags | Qt.ItemFlag.ItemIsEnabled)

    def _remove_tunnel_row(self, row: int):
        self._tunnel_table.removeRow(row)
        # Re-wire delete buttons for remaining rows
        for r in range(self._tunnel_table.rowCount()):
            btn = self._tunnel_table.cellWidget(r, 4)
            if btn:
                try:
                    btn.clicked.disconnect()
                except RuntimeError:
                    pass
                btn.clicked.connect(lambda _, rr=r: self._remove_tunnel_row(rr))

    # ------------------------------------------------------------------
    # Tunnel ↔ command synchronisation
    # ------------------------------------------------------------------

    _TUNNEL_RE = re.compile(
        r'\s*-([LRD])\s+'
        r'(?:'
        r'(\d+):([^:\s]+):(\d+)'   # -L/-R local_port:host:remote_port
        r'|'
        r'(\d+)'                    # -D port
        r')'
    )

    def _tunnels_from_table(self) -> list[tuple[str, str, str, str]]:
        """Return list of (type, local_port, remote_host, remote_port)."""
        rows = []
        for r in range(self._tunnel_table.rowCount()):
            combo = self._tunnel_table.cellWidget(r, 0)
            ttype = ["L", "R", "D"][combo.currentIndex()] if combo else "L"
            lp = (self._tunnel_table.item(r, 1) or QTableWidgetItem("")).text().strip()
            rh = (self._tunnel_table.item(r, 2) or QTableWidgetItem("")).text().strip()
            rpp = (self._tunnel_table.item(r, 3) or QTableWidgetItem("")).text().strip()
            rows.append((ttype, lp, rh, rpp))
        return rows

    def _tunnels_to_flags(self) -> str:
        """Convert table rows to a string of -L/-R/-D flags."""
        parts = []
        for ttype, lp, rh, rpp in self._tunnels_from_table():
            if not lp:
                continue
            if ttype == "D":
                parts.append(f"-D {lp}")
            elif rh and rpp:
                parts.append(f"-{ttype} {lp}:{rh}:{rpp}")
        return " ".join(parts)

    def _strip_tunnel_flags(self, cmd: str) -> str:
        """Remove all -L/-R/-D flags from a command string."""
        return re.sub(
            r'\s*-[LRD]\s+(?:\d+:[^:\s]+:\d+|\d+)',
            '',
            cmd,
        ).strip()

    def _rebuild_command_with_tunnels(self):
        """
        Called on save: strips old tunnel flags, injects new ones after 'ssh'.
        """
        cmd = self._text_command.toPlainText().strip()
        flags = self._tunnels_to_flags()
        cmd_clean = self._strip_tunnel_flags(cmd)

        if not flags:
            self._text_command.setPlainText(cmd_clean)
            return

        tokens = cmd_clean.split(None, 1)
        if tokens and tokens[0].lower() in ("ssh", "ssh.exe"):
            rest = tokens[1] if len(tokens) > 1 else ""
            self._text_command.setPlainText(
                f"{tokens[0]} {flags} {rest}".strip()
            )
        else:
            self._text_command.setPlainText(f"{cmd_clean} {flags}".strip())

    def _populate_tunnels_from_command(self, cmd: str):
        """Parse -L/-R/-D flags out of `cmd` and fill the tunnel table."""
        for m in self._TUNNEL_RE.finditer(cmd):
            ttype = m.group(1)
            if ttype == "D":
                local_port = m.group(5) or ""
                self._add_tunnel_row("D", local_port, "", "")
            else:
                local_port = m.group(2) or ""
                remote_host = m.group(3) or ""
                remote_port = m.group(4) or ""
                self._add_tunnel_row(ttype, local_port, remote_host, remote_port)

    def _build_commands_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel(
            "Commands to run after login (one per line).\n"
            "Use ##D=1000 to insert a 1000 ms delay."
        ))
        self._text_commands = QTextEdit()
        self._text_commands.setPlaceholderText("cd /var/log\ntail -f syslog")
        layout.addWidget(self._text_commands)
        return w

    def _build_appearance_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._entry_font = QLineEdit()
        self._entry_font.setPlaceholderText("Consolas 12  (empty = global default)")
        form.addRow("Font:", self._entry_font)

        self._btn_bg = QPushButton()
        self._btn_bg.setFixedHeight(28)
        self._bg_color = ""
        self._btn_bg.clicked.connect(lambda: self._pick_color("bg"))
        form.addRow("Background:", self._btn_bg)

        self._btn_fg = QPushButton()
        self._btn_fg.setFixedHeight(28)
        self._fg_color = ""
        self._btn_fg.clicked.connect(lambda: self._pick_color("fg"))
        form.addRow("Foreground:", self._btn_fg)

        note = QLabel("Leave colors empty to use the global default theme.")
        note.setWordWrap(True)
        form.addRow("", note)

        return w

    # ------------------------------------------------------------------
    # Key file helpers
    # ------------------------------------------------------------------

    def _browse_key_file(self):
        """Open a file picker for SSH private key files."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select SSH Private Key",
            "",
            "Key files (*.pem *.key *.ppk *.pub id_rsa id_ed25519 id_ecdsa id_dsa);;"
            "All files (*)",
        )
        if path:
            # Normalise to forward slashes so ssh is happy on Windows too
            path = path.replace("\\", "/")
            self._entry_key.setText(path)
            self._inject_key_into_command(path)

    def _clear_key_file(self):
        """Remove the key path from both the field and the command."""
        self._entry_key.clear()
        self._remove_key_from_command()

    def _on_key_path_changed(self, path: str):
        """When the user edits the key path manually, keep the command in sync."""
        if path.strip():
            self._inject_key_into_command(path.strip())
        else:
            self._remove_key_from_command()

    def _inject_key_into_command(self, key_path: str):
        """
        Insert or replace the -i argument in the SSH command text.

        If a -i flag already exists it is replaced in-place so the rest
        of the command (host, port, options) stays untouched.
        """
        cmd = self._text_command.toPlainText().strip()
        if not cmd:
            # Build a minimal placeholder so the user sees the -i
            self._text_command.setPlainText(f'ssh -i "{key_path}" ')
            return

        # Replace existing -i VALUE (handles quoted and unquoted paths)
        new_flag = f'-i "{key_path}"'
        updated, n = re.subn(
            r'-i\s+(?:"[^"]*"|\'[^\']*\'|\S+)',
            new_flag,
            cmd,
        )
        if n:
            self._text_command.setPlainText(updated)
        else:
            # No existing -i — insert after 'ssh' (first token)
            tokens = cmd.split(None, 1)
            if tokens and tokens[0].lower() in ("ssh", "ssh.exe"):
                rest = tokens[1] if len(tokens) > 1 else ""
                self._text_command.setPlainText(
                    f"{tokens[0]} {new_flag} {rest}".rstrip()
                )
            else:
                # Prepend ssh + flag
                self._text_command.setPlainText(f"ssh {new_flag} {cmd}")

    def _remove_key_from_command(self):
        """Strip any -i flag from the command text."""
        cmd = self._text_command.toPlainText()
        updated = re.sub(r'\s*-i\s+(?:"[^"]*"|\'[^\']*\'|\S+)', '', cmd)
        self._text_command.setPlainText(updated.strip())

    def _pick_color(self, which: str):
        color = QColorDialog.getColor(parent=self)
        if not color.isValid():
            return
        hex_color = color.name()
        if which == "bg":
            self._bg_color = hex_color
            self._btn_bg.setStyleSheet(
                f"background-color: {hex_color}; color: {'#fff' if color.lightness() < 128 else '#000'};"
            )
            self._btn_bg.setText(hex_color)
        else:
            self._fg_color = hex_color
            self._btn_fg.setStyleSheet(
                f"background-color: {hex_color}; color: {'#fff' if color.lightness() < 128 else '#000'};"
            )
            self._btn_fg.setText(hex_color)

    def _set_color_button(self, btn: QPushButton, hex_color: str):
        if not hex_color:
            return
        from PySide6.QtGui import QColor
        c = QColor(hex_color)
        btn.setStyleSheet(
            f"background-color: {hex_color}; color: {'#fff' if c.lightness() < 128 else '#000'};"
        )
        btn.setText(hex_color)

    def _populate(self, conn: Connection):
        self._combo_group.setCurrentText(conn.group or "")
        self._entry_name.setText(conn.name)
        self._entry_desc.setText(conn.description)
        self._chk_favorite.setChecked(bool(conn.favorite))
        self._entry_tags.setText(conn.tags or "")
        # Open After combo
        for i in range(self._combo_open_after.count()):
            if self._combo_open_after.itemData(i) == conn.open_after:
                self._combo_open_after.setCurrentIndex(i)
                break
        # Set command first, then extract -i to populate key field
        self._entry_key.blockSignals(True)
        self._text_command.setPlainText(conn.command)
        key_match = re.search(r'-i\s+(?:"([^"]+)"|\'([^\']+)\'|(\S+))', conn.command)
        if key_match:
            key_path = key_match.group(1) or key_match.group(2) or key_match.group(3)
            self._entry_key.setText(key_path)
        self._entry_key.blockSignals(False)

        self._populate_tunnels_from_command(conn.command)

        self._text_commands.setPlainText(conn.commands)
        self._combo_term.setCurrentText(conn.term_type or "xterm-256color")
        self._entry_font.setText(conn.font)

        self._bg_color = conn.bg_color
        self._fg_color = conn.fg_color
        self._set_color_button(self._btn_bg, conn.bg_color)
        self._set_color_button(self._btn_fg, conn.fg_color)

        pw = self.credential_store.get_password(conn.id)
        pp1 = self.credential_store.get_passphrase1(conn.id)
        pp2 = self.credential_store.get_passphrase2(conn.id)
        if pw:
            self._entry_password.setText(pw)
        if pp1:
            self._entry_pp1.setText(pp1)
        if pp2:
            self._entry_pp2.setText(pp2)
        if pp1:
            self._entry_pp1.setText(pp1)
        if pp2:
            self._entry_pp2.setText(pp2)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _on_save(self):
        # Merge tunnel table into the command before reading it
        self._rebuild_command_with_tunnels()
        command = self._text_command.toPlainText().strip()
        if not command:
            QMessageBox.warning(self, "Validation", "SSH Command is required.")
            return

        name = self._entry_name.text().strip()
        if not name:
            # Auto-derive name from command
            parts = command.split()
            name = parts[-1] if parts else command[:40]

        if self.connection:
            conn = self.connection
        else:
            conn = Connection()

        conn.name = name
        conn.group = self._combo_group.currentText().strip()
        conn.description = self._entry_desc.text().strip()
        conn.favorite = self._chk_favorite.isChecked()
        conn.tags = self._entry_tags.text().strip()
        conn.open_after = self._combo_open_after.currentData() or ""
        conn.command = command
        conn.commands = self._text_commands.toPlainText()
        conn.term_type = self._combo_term.currentText().strip()
        conn.font = self._entry_font.text().strip()
        conn.bg_color = self._bg_color
        conn.fg_color = self._fg_color

        if self.connection:
            self.connection_manager.update_connection(conn)
        else:
            self.connection_manager.add_connection(conn)

        # Save credentials
        pw = self._entry_password.text()
        pp1 = self._entry_pp1.text()
        pp2 = self._entry_pp2.text()
        if pw:
            self.credential_store.set_password(conn.id, pw)
        if pp1:
            self.credential_store.set_passphrase1(conn.id, pp1)
        if pp2:
            self.credential_store.set_passphrase2(conn.id, pp2)

        self.connection_saved.emit(conn)
        self.accept()
