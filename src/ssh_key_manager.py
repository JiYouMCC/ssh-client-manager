"""
SSH Key Manager dialog — lists ~/.ssh/ keys and generates new ones.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QMessageBox, QHeaderView, QComboBox, QLineEdit,
    QFormLayout, QDialogButtonBox, QLabel,
)


class _GenerateKeyDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generate SSH Key")
        self.setModal(True)
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._combo_type = QComboBox()
        for label in ["RSA 2048", "RSA 4096", "Ed25519", "ECDSA 256", "ECDSA 384", "ECDSA 521"]:
            self._combo_type.addItem(label)
        form.addRow("Key Type:", self._combo_type)

        self._edit_filename = QLineEdit()
        self._edit_filename.setPlaceholderText("e.g. id_rsa_myserver")
        form.addRow("Filename:", self._edit_filename)

        self._edit_comment = QLineEdit()
        self._edit_comment.setPlaceholderText("e.g. user@host")
        form.addRow("Comment:", self._edit_comment)

        self._edit_passphrase = QLineEdit()
        self._edit_passphrase.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit_passphrase.setPlaceholderText("Leave empty for no passphrase")
        form.addRow("Passphrase:", self._edit_passphrase)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Generate")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate(self):
        if not self._edit_filename.text().strip():
            QMessageBox.warning(self, "Input Required", "Please enter a filename.")
            return
        self.accept()

    def get_params(self) -> dict:
        label = self._combo_type.currentText()
        type_map = {
            "RSA 2048":  ("rsa",   "2048"),
            "RSA 4096":  ("rsa",   "4096"),
            "Ed25519":   ("ed25519", None),
            "ECDSA 256": ("ecdsa", "256"),
            "ECDSA 384": ("ecdsa", "384"),
            "ECDSA 521": ("ecdsa", "521"),
        }
        key_type, bits = type_map[label]
        return {
            "type":       key_type,
            "bits":       bits,
            "filename":   self._edit_filename.text().strip(),
            "comment":    self._edit_comment.text().strip(),
            "passphrase": self._edit_passphrase.text(),
        }


class SSHKeyManagerDialog(QDialog):
    """Lists SSH keys in ~/.ssh/ and allows generating new ones."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SSH Key Manager")
        self.setMinimumSize(780, 420)

        layout = QVBoxLayout(self)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Filename", "Type", "Bits", "Fingerprint", "Comment"])
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

        toolbar = QHBoxLayout()
        self._btn_generate = QPushButton("Generate New Key")
        self._btn_refresh = QPushButton("Refresh")
        self._btn_close = QPushButton("Close")
        toolbar.addWidget(self._btn_generate)
        toolbar.addWidget(self._btn_refresh)
        toolbar.addStretch()
        toolbar.addWidget(self._btn_close)
        layout.addLayout(toolbar)

        self._btn_generate.clicked.connect(self._on_generate)
        self._btn_refresh.clicked.connect(self._load_keys)
        self._btn_close.clicked.connect(self.accept)

        self._load_keys()

    # ------------------------------------------------------------------

    def _load_keys(self):
        self._table.setRowCount(0)
        ssh_dir = Path.home() / ".ssh"
        if not ssh_dir.exists():
            return
        for pub_file in sorted(ssh_dir.glob("*.pub")):
            self._add_key_row(pub_file)

    def _add_key_row(self, pub_file: Path):
        try:
            result = subprocess.run(
                ["ssh-keygen", "-l", "-f", str(pub_file)],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return
            line = result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return

        # Format: 2048 SHA256:xxxx comment (RSA)
        m = re.match(r"(\d+)\s+(\S+)\s+(.*?)\s+\((\w+)\)\s*$", line)
        if not m:
            return
        bits, fingerprint, comment, key_type = m.groups()

        row = self._table.rowCount()
        self._table.insertRow(row)
        for col, text in enumerate([pub_file.stem, key_type, bits, fingerprint, comment]):
            item = QTableWidgetItem(text)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, col, item)

    def _on_generate(self):
        dlg = _GenerateKeyDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        params = dlg.get_params()
        ssh_dir = Path.home() / ".ssh"
        ssh_dir.mkdir(mode=0o700, exist_ok=True)
        key_path = ssh_dir / params["filename"]

        if key_path.exists():
            answer = QMessageBox.question(
                self, "File Exists",
                f"{key_path} already exists. Overwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        cmd = ["ssh-keygen", "-t", params["type"], "-f", str(key_path), "-N", params["passphrase"]]
        if params["bits"]:
            cmd += ["-b", params["bits"]]
        if params["comment"]:
            cmd += ["-C", params["comment"]]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                QMessageBox.information(self, "Success", f"Key generated:\n{key_path}")
                self._load_keys()
            else:
                QMessageBox.critical(self, "Error", result.stderr.strip() or "Key generation failed.")
        except FileNotFoundError:
            QMessageBox.critical(self, "Error", "ssh-keygen not found. Is OpenSSH installed?")
        except (subprocess.TimeoutExpired, OSError) as e:
            QMessageBox.critical(self, "Error", str(e))
