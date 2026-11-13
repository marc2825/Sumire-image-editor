"""Namespaced record locations and reversible migration of Sumīre databases."""
from .i18n import tr
from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile

from .preferences import Preferences, settings_path
from . import legacy

APPLICATION_ID = 0x53554D49  # Stable on-disk identifier; keep existing DBs readable.
TABLES = {
    "receipts": ("source", "name", "format", "digest", "edited"),
    "review_labels": ("source", "label"),
    "review_notes": ("source", "note"),
    "edit_masks": ("source", "digest", "width", "height", "png"),
    "geometry_edits": ("source", "digest", "recipe"),
    "metadata_backups": ("source", "digest", "previous_digest", "payload"),
}
SCHEMAS = {
    "receipts": "source TEXT PRIMARY KEY, name TEXT, format TEXT, digest TEXT, edited INTEGER",
    "review_labels": "source TEXT PRIMARY KEY, label TEXT NOT NULL",
    "review_notes": "source TEXT PRIMARY KEY, note TEXT NOT NULL",
    "edit_masks": "source TEXT PRIMARY KEY, digest TEXT, width INTEGER, height INTEGER, png BLOB",
    "geometry_edits": "source TEXT PRIMARY KEY, digest TEXT, recipe TEXT",
    "metadata_backups": "source TEXT PRIMARY KEY, digest TEXT, previous_digest TEXT, payload BLOB NOT NULL",
}


def record_path(folder, mode=None):
    folder = Path(folder).resolve()
    mode = mode or Preferences().data.get("storage", "folder")
    if mode == "app":
        key = hashlib.sha256(os.path.normcase(str(folder)).encode()).hexdigest()
        folder = settings_path().parent / "records" / key
    current = folder / ".sumire-index.sqlite3"
    previous = folder / legacy.DATABASE_FILENAME
    return previous if not current.exists() and previous.exists() else current


def connect_owned(path):
    path = Path(path)
    if path.is_symlink() or (path.exists() and (not path.is_file() or path.stat().st_size > 128 * 1024 * 1024)):
        raise OSError(tr("管理記録を確認できません。"))
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    connection = sqlite3.connect(path, timeout=2)
    if exists and connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
        connection.close()
        raise OSError(tr("Sumīre以外の管理ファイルは変更できません。"))
    if not exists:
        connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
    return connection


def migrate_records(folders, mode, preferences):
    """Stage every destination, switch settings last, then remove unchanged sources."""
    if mode not in {"folder", "app"}:
        raise ValueError("Unknown storage location")
    old_mode = preferences.data.get("storage", "folder")
    if mode == old_mode:
        return 0
    staged, installed = [], []
    try:
        for folder in sorted(set(Path(folder).resolve() for folder in folders)):
            source, target = record_path(folder, old_mode), record_path(folder, mode)
            if not source.exists():
                continue
            with closing(connect_owned(source)) as source_db:
                tables = {row[0] for row in source_db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "rename_tasks" in tables and source_db.execute("SELECT 1 FROM rename_tasks LIMIT 1").fetchone():
                    raise OSError(tr("中断した名前変更を復旧してから保存場所を変更してください。"))
                target.parent.mkdir(parents=True, exist_ok=True)
                fd, name = tempfile.mkstemp(prefix=".sumire-migrate-", dir=target.parent)
                os.close(fd)
                temporary = Path(name)
                staged.append((source, target, temporary, hashlib.sha256(source.read_bytes()).digest()))
                with closing(sqlite3.connect(temporary)) as destination:
                    if target.exists():
                        with closing(connect_owned(target)) as existing:
                            existing.backup(destination)
                    with destination:
                        destination.execute(f"PRAGMA application_id={APPLICATION_ID}")
                        for table in TABLES:
                            if table not in tables:
                                continue
                            columns = TABLES[table]
                            destination.execute(f"CREATE TABLE IF NOT EXISTS {table} ({SCHEMAS[table]})")
                            if table == "receipts" and "edited" not in {r[1] for r in destination.execute("PRAGMA table_info(receipts)")}:
                                destination.execute("ALTER TABLE receipts ADD COLUMN edited INTEGER")
                            available = {r[1] for r in source_db.execute(f"PRAGMA table_info({table})")}
                            select = ",".join(column if column in available else "NULL" for column in columns)
                            rows = source_db.execute(f"SELECT {select} FROM {table}").fetchall()
                            destination.executemany(f"INSERT OR REPLACE INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", rows)
        for source, target, temporary, digest in staged:
            backup = None
            if target.exists():
                fd, name = tempfile.mkstemp(prefix=".sumire-previous-", dir=target.parent)
                os.close(fd)
                backup = Path(name)
                os.replace(target, backup)
            installed.append((target, backup))
            os.replace(temporary, target)
        preferences.save({**preferences.data, "storage": mode})
    except BaseException:
        for target, backup in reversed(installed):
            target.unlink(missing_ok=True)
            if backup:
                os.replace(backup, target)
        raise
    finally:
        for _, _, temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    for target, backup in installed:
        if backup:
            try:
                backup.unlink(missing_ok=True)
            except OSError:
                pass
    for source, _, _, digest in staged:
        try:
            if source.exists() and hashlib.sha256(source.read_bytes()).digest() == digest:
                source.unlink()
        except OSError:
            # The settings already point at complete destination databases.
            # Retaining an old copy is preferable to reporting migration failure.
            pass
    return len(staged)


def delete_records(folders):
    paths = []
    for folder in set(folders):
        path = record_path(folder)
        if path.exists():
            with closing(connect_owned(path)) as connection:
                tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "rename_tasks" in tables and connection.execute("SELECT 1 FROM rename_tasks LIMIT 1").fetchone():
                    raise OSError(tr("名前変更の復旧前には管理記録を削除できません。"))
            paths.append(path)
    for path in paths:
        path.unlink()
    return len(paths)
