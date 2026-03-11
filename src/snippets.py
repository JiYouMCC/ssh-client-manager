"""
Command Snippets — data model and manager.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from .config import get_config_dir


@dataclass
class Snippet:
    id: str = ""
    name: str = ""
    command: str = ""
    category: str = ""
    description: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())


class SnippetsManager:
    def __init__(self):
        self._file: Path = get_config_dir() / "snippets.json"
        self._snippets: list[Snippet] = []
        self.load()

    def load(self):
        if not self._file.exists():
            self._snippets = []
            return
        try:
            with open(self._file, "r") as f:
                data = json.load(f)
            self._snippets = []
            valid_keys = {f.name for f in Snippet.__dataclass_fields__.values()}
            for item in data.get("snippets", []):
                filtered = {k: v for k, v in item.items() if k in valid_keys}
                self._snippets.append(Snippet(**filtered))
        except (json.JSONDecodeError, IOError, TypeError):
            self._snippets = []

    def save(self):
        try:
            with open(self._file, "w") as f:
                json.dump({"snippets": [asdict(s) for s in self._snippets]}, f, indent=2)
        except IOError as e:
            print(f"Warning: Could not save snippets: {e}")

    def add_snippet(self, s: Snippet):
        self._snippets.append(s)
        self.save()

    def update_snippet(self, s: Snippet):
        for i, existing in enumerate(self._snippets):
            if existing.id == s.id:
                self._snippets[i] = s
                self.save()
                return
        self.add_snippet(s)

    def delete_snippet(self, snippet_id: str):
        self._snippets = [s for s in self._snippets if s.id != snippet_id]
        self.save()

    def get_snippet(self, snippet_id: str) -> Optional[Snippet]:
        for s in self._snippets:
            if s.id == snippet_id:
                return s
        return None

    def get_snippets(self) -> list[Snippet]:
        return list(self._snippets)

    def get_categories(self) -> list[str]:
        return sorted({s.category for s in self._snippets if s.category})

    def export_json(self) -> str:
        return json.dumps({"snippets": [asdict(s) for s in self._snippets]}, indent=2)

    def import_json(self, json_str: str, replace: bool = False):
        try:
            data = json.loads(json_str)
            valid_keys = {f.name for f in Snippet.__dataclass_fields__.values()}
            imported = []
            for item in data.get("snippets", []):
                filtered = {k: v for k, v in item.items() if k in valid_keys}
                s = Snippet(**filtered)
                s.id = str(uuid.uuid4())
                imported.append(s)
            if replace:
                self._snippets = imported
            else:
                self._snippets.extend(imported)
            self.save()
        except (json.JSONDecodeError, TypeError) as e:
            raise ValueError(f"Invalid import data: {e}")
