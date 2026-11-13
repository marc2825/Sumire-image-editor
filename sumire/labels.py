"""Review labels stored locally, independently of pixel edits and save receipts."""
from __future__ import annotations
from .i18n import tr

import hashlib
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from .session import APPLICATION_ID
from .storage import record_path

# In key order: 採用 1, 保留 2, 不採用 3.
REVIEW_LABELS = {"accepted": tr("採用"), "pending": tr("保留"), "rejected": tr("不採用")}


def label_key(path: Path) -> str:
    # Unlike save receipts, a label survives changes to the image at this path.
    return hashlib.sha256(os.path.normcase(str(path.resolve())).encode("utf-8")).hexdigest()


class ReviewLabels:
    def __init__(self, folder: Path):
        self.folder = folder.resolve()
        self.path = record_path(self.folder)
        self.labels: dict[str, str] = {}
        self.notes: dict[str, str] = {}
        try:
            if self.path.is_symlink() or not self.path.is_file() or self.path.stat().st_size > 128 * 1024 * 1024:
                return
            with closing(sqlite3.connect(self.path)) as connection:
                if connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
                    return
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "review_labels" in tables:
                    for key, label in connection.execute("SELECT source, label FROM review_labels"):
                        if isinstance(key, str) and label in REVIEW_LABELS:
                            self.labels[key] = label
                if "review_notes" in tables:
                    for key, note in connection.execute("SELECT source, note FROM review_notes"):
                        if isinstance(key, str) and isinstance(note, str) and len(note) <= 4000:
                            self.notes[key] = note
        except (OSError, sqlite3.Error):
            pass

    def get(self, path: Path) -> str | None:
        return self.labels.get(label_key(path))

    def set(self, path: Path, label: str | None):
        if label is not None and label not in REVIEW_LABELS:
            raise ValueError("Unknown review label")
        if path.resolve().parent != self.folder:
            raise ValueError("Review labels belong to the source folder")
        key = label_key(path)
        self._write({key: label})

    def set_many(self, values):
        if any(path.parent != self.folder or (label is not None and label not in REVIEW_LABELS) for path, label in values.items()):
            raise ValueError("Invalid review label update")
        self._write({label_key(path): label for path, label in values.items()})

    def note(self, path):
        return self.notes.get(label_key(path), "")

    def set_note(self, path, text):
        if path.parent != self.folder or len(text) > 4000:
            raise ValueError("Invalid review note")
        self._write({}, {label_key(path): text})

    def remap_paths(self, mapping: dict[Path, Path]):
        local = {old: new for old, new in mapping.items() if old.parent == self.folder}
        if any(new.parent != self.folder for new in local.values()):
            raise ValueError("Review label remapping requires the same folder")
        if not local or not (self.labels or self.notes):
            return
        # Snapshot first so cycles and an unlabelled image replacing a labelled
        # path do not duplicate or inherit another image's label.
        updates = {label_key(old): None for old in local}
        updates.update({label_key(new): self.get(old) for old, new in local.items()})
        notes = {label_key(old): "" for old in local}
        notes.update({label_key(new): self.note(old) for old, new in local.items()})
        self._write(updates, notes)

    def _write(self, updates: dict[str, str | None], notes=None):
        notes = notes or {}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.is_symlink():
                raise OSError("Label index is a symlink")
            exists = self.path.exists()
            with closing(sqlite3.connect(self.path, timeout=2)) as connection:
                with connection:
                    app_id = connection.execute("PRAGMA application_id").fetchone()[0]
                    if exists and app_id != APPLICATION_ID:
                        raise OSError("Unrecognized label database")
                    connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
                    connection.execute("CREATE TABLE IF NOT EXISTS review_labels (source TEXT PRIMARY KEY, label TEXT NOT NULL)")
                    connection.executemany("DELETE FROM review_labels WHERE source = ?", [(key,) for key in updates])
                    connection.executemany("INSERT INTO review_labels VALUES (?, ?)",
                                           [(key, label) for key, label in updates.items() if label is not None])
                    if notes:
                        connection.execute("CREATE TABLE IF NOT EXISTS review_notes (source TEXT PRIMARY KEY, note TEXT NOT NULL)")
                        connection.executemany("DELETE FROM review_notes WHERE source = ?", [(key,) for key in notes])
                        connection.executemany("INSERT INTO review_notes VALUES (?, ?)", [(key, note) for key, note in notes.items() if note])
        except sqlite3.Error:
            raise OSError("Cannot write review labels") from None
        for key, label in updates.items():
            if label is None:
                self.labels.pop(key, None)
            else:
                self.labels[key] = label
        for key, note in notes.items():
            if note:
                self.notes[key] = note
            else:
                self.notes.pop(key, None)
