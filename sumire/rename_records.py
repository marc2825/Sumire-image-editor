"""Durable, idempotent metadata updates coordinated by the rename journal."""
from .i18n import tr
import base64
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path

from .labels import label_key
from .session import source_key
from .storage import TABLES, SCHEMAS, connect_owned, record_path


def plan_records(mapping, folders):
    plans = []
    for folder in sorted(set(folders) | {path.parent for path in mapping}):
        path = record_path(folder)
        if not path.exists():
            continue
        with closing(connect_owned(path)) as connection:
            tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            payload = {}
            for table, columns in TABLES.items():
                if table not in tables:
                    continue
                available = {r[1] for r in connection.execute(f"PRAGMA table_info({table})")}
                select = ",".join(c if c in available else "NULL" for c in columns)
                rows = dict((row[0], list(row)) for row in connection.execute(f"SELECT {select} FROM {table}"))
                updates, deletions = [], []
                for old, new in mapping.items():
                    if table == "receipts":
                        before = source_key(old)
                        stat = old.stat()
                        identity = f"{os.path.normcase(str(new.resolve()))}\0{stat.st_size}\0{stat.st_mtime_ns}"
                        after = hashlib.sha256(identity.encode()).hexdigest()
                    else:
                        if old.parent != folder:
                            continue
                        before, after = label_key(old), label_key(new)
                    deletions.extend((before, after))
                    if before in rows:
                        row = rows[before].copy()
                        row[0] = after
                        if table == "receipts":
                            output = folder / row[1]
                            row[1] = mapping.get(output, output).name
                        if table in {"edit_masks", "metadata_backups"}:
                            row[-1] = base64.b64encode(row[-1]).decode("ascii")
                        updates.append(row)
                if deletions:
                    payload[table] = {"delete": sorted(set(deletions)), "insert": updates}
            if payload:
                plans.append(({"folder": str(folder), "path": str(path)}, payload))
    return plans


def stage_records(plans, token):
    for reference, payload in plans:
        with closing(connect_owned(reference["path"])) as connection:
            with connection:
                connection.execute("CREATE TABLE IF NOT EXISTS rename_tasks (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
                connection.execute("INSERT INTO rename_tasks VALUES (?,?)", (token, json.dumps(payload)))


def validate_references(references):
    if not isinstance(references, list):
        raise ValueError()
    for reference in references:
        folder, path = Path(reference["folder"]), Path(reference["path"])
        if not folder.is_absolute() or path not in {record_path(folder, "folder"), record_path(folder, "app")}:
            raise ValueError()


def apply_records(references, token):
    validate_references(references)
    for reference in references:
        with closing(connect_owned(reference["path"])) as connection:
            row = connection.execute("SELECT payload FROM rename_tasks WHERE id=?", (token,)).fetchone()
            if not row:
                raise OSError(tr("名前変更の管理記録が不足しています。"))
            payload = json.loads(row[0])
            with connection:
                for table, change in payload.items():
                    if table not in TABLES:
                        raise ValueError()
                    columns = TABLES[table]
                    connection.execute(f"CREATE TABLE IF NOT EXISTS {table} ({SCHEMAS[table]})")
                    if table == "receipts" and "edited" not in {r[1] for r in connection.execute("PRAGMA table_info(receipts)")}:
                        connection.execute("ALTER TABLE receipts ADD COLUMN edited INTEGER")
                    rows = change["insert"]
                    if table in {"edit_masks", "metadata_backups"}:
                        rows = [row[:-1] + [base64.b64decode(row[-1], validate=True)] for row in rows]
                    connection.executemany(f"DELETE FROM {table} WHERE source=?", [(key,) for key in change["delete"]])
                    connection.executemany(f"INSERT OR REPLACE INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", rows)


def cleanup_records(references, token):
    validate_references(references)
    for reference in references:
        with closing(connect_owned(reference["path"])) as connection:
            if "rename_tasks" in {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
                with connection:
                    connection.execute("DELETE FROM rename_tasks WHERE id=?", (token,))
