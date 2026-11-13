"""Local SQLite receipts; constant-size updates even for very large folders."""
from __future__ import annotations

import hashlib
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from .export import SaveResult
from .storage import record_path

APPLICATION_ID = 0x53554D49


def source_key(path: Path) -> str:
    stat = path.stat()
    identity = f"{os.path.normcase(str(path.resolve()))}\0{stat.st_size}\0{stat.st_mtime_ns}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def valid_record(name, format, digest) -> bool:
    return (isinstance(name, str) and bool(name) and Path(name).name == name
            and not any(c in name for c in "/\\:")
            and format in {"PNG", "JPEG", "WEBP"}
            and isinstance(digest, str) and len(digest) == 64
            and all(c in "0123456789abcdef" for c in digest))


class Receipts:
    def __init__(self, folder: Path):
        self.folder = folder.resolve()
        self.path = record_path(self.folder)
        self.records: dict[str, dict] = {}
        try:
            if self.path.is_symlink() or not self.path.is_file() or self.path.stat().st_size > 128 * 1024 * 1024:
                return
            with closing(sqlite3.connect(self.path)) as connection:
                if connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
                    return
                columns = {row[1] for row in connection.execute("PRAGMA table_info(receipts)")}
                edited_column = "edited" if "edited" in columns else "NULL"
                for key, name, format, digest, edited in connection.execute(f"SELECT source, name, format, digest, {edited_column} FROM receipts"):
                    if isinstance(key, str) and valid_record(name, format, digest):
                        self.records[key] = {"name": name, "format": format, "digest": digest,
                                             "edited": bool(edited) if type(edited) is int and edited in (0, 1) else None}
        except (OSError, sqlite3.Error):
            pass

    def get(self, path: Path, *, overwrite: bool | None = None) -> dict | None:
        record = self.records.get(source_key(path))
        if record and overwrite is not None and ((self.folder / record["name"]).resolve() == path.resolve()) != overwrite:
            return None
        return record

    @staticmethod
    def _schema(connection):
        connection.execute("CREATE TABLE IF NOT EXISTS receipts (source TEXT PRIMARY KEY, name TEXT, format TEXT, digest TEXT, edited INTEGER)")
        if "edited" not in {row[1] for row in connection.execute("PRAGMA table_info(receipts)")}:
            connection.execute("ALTER TABLE receipts ADD COLUMN edited INTEGER")

    def record(self, path: Path, result: SaveResult, *, previous_key: str | None = None, edited: bool | None = None):
        if result.path.parent != self.folder:
            return
        key = source_key(path)
        value = {"name": result.path.name, "format": result.verification.format, "digest": result.digest.hex(), "edited": edited}
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if self.path.is_symlink():
                raise OSError("Receipt index is a symlink")
            exists = self.path.exists()
            # Connections are short lived; each worker uses its own SQLite handle.
            with closing(sqlite3.connect(self.path, timeout=2)) as connection:
                with connection:
                    app_id = connection.execute("PRAGMA application_id").fetchone()[0]
                    if exists and app_id != APPLICATION_ID:
                        raise OSError("Unrecognized receipt database")
                    connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
                    self._schema(connection)
                    if previous_key and previous_key != key:
                        connection.execute("DELETE FROM receipts WHERE source = ?", (previous_key,))
                    connection.execute("INSERT OR REPLACE INTO receipts (source, name, format, digest, edited) VALUES (?, ?, ?, ?, ?)",
                                       (key, value["name"], value["format"], value["digest"], edited))
            if previous_key and previous_key != key:
                self.records.pop(previous_key, None)
            self.records[key] = value
        except sqlite3.Error:
            raise OSError("Cannot write receipt index") from None

    def remap_sources(self, mapping: dict[Path, Path], previous_keys: dict[Path, str]):
        rows = {old: self.records[key].copy() for old, key in previous_keys.items() if key in self.records}
        if not rows:
            return
        updates = {}
        for old, record in rows.items():
            output = self.folder / record["name"]
            record["name"] = mapping.get(output, output).name
            updates[source_key(mapping[old])] = record
        try:
            if self.path.is_symlink():
                raise OSError("Receipt index is a symlink")
            with closing(sqlite3.connect(self.path, timeout=2)) as connection:
                with connection:
                    if connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
                        raise OSError("Unrecognized receipt database")
                    self._schema(connection)
                    connection.executemany("DELETE FROM receipts WHERE source = ?", [(previous_keys[old],) for old in rows])
                    connection.executemany("INSERT OR REPLACE INTO receipts (source, name, format, digest, edited) VALUES (?, ?, ?, ?, ?)",
                                           [(key, value["name"], value["format"], value["digest"], value["edited"]) for key, value in updates.items()])
        except sqlite3.Error:
            raise OSError("Cannot update receipt index") from None
        for old in rows:
            self.records.pop(previous_keys[old], None)
        self.records.update(updates)

