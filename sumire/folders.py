"""Folders inside a tab: listing, creating, and moving images between them.

A move never overwrites a file. The image keeps its bytes (hard link, or a
verified copy across drives), and its records — label, note, edit mask,
geometry steps and metadata backup — move to the destination folder's records.
"""
from __future__ import annotations
from .i18n import tr

from contextlib import closing
import os
from pathlib import Path
import sqlite3

from .export import Cancelled, check_cancel, file_digest
from .imaging import ImageProblem
from .labels import REVIEW_LABELS, label_folder_names, label_key
from .locking import image_locks
from .storage import SCHEMAS, TABLES, connect_owned, record_path

INVALID = '<>:"/\\|?*'
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
# Records that belong to the image itself (receipts belong to the output folder).
MOVED_TABLES = ("review_labels", "review_notes", "review_tags", "edit_masks", "geometry_edits", "metadata_backups")


def folder_name_problem(name: str) -> str:
    if (not name or name in {".", ".."} or name.endswith((".", " ")) or any(c in name for c in INVALID)
            or any(ord(c) < 32 for c in name) or name.split(".")[0].upper() in RESERVED):
        return tr("フォルダー名に使えない文字が含まれています。")
    return ""


def subfolders(folder: Path) -> list[Path]:
    """Visible folders directly inside ``folder``, in natural name order."""
    from .library import filename_key
    try:
        found = [path for path in Path(folder).iterdir()
                 if path.is_dir() and not path.is_symlink() and not path.name.startswith(".")]
    except OSError:
        return []
    return sorted(found, key=lambda path: (filename_key(path), path.name))


def _folder_label(folder: Path):
    """(label, language index) when ``folder`` is named like a label folder (採用 / Accept / 采用…)."""
    name = folder.name.casefold()
    for label, names in label_folder_names().items():
        for number, text in enumerate(names):
            if name == text.casefold():
                return label, number
    return None


def label_folder_target(path: Path, label: str) -> Path | None:
    """The folder 「ラベルのフォルダーへ自動で振り分ける」 moves ``path`` into for ``label``, or None.

    It sorts only where label folders already exist: inside the image's folder, or
    beside it when the image is in one of them (from 保留 to the 採用 next to it).
    A label folder still missing there is named like the others (their language).
    """
    here = Path(path).parent
    found = [(folder, _folder_label(folder)) for folder in subfolders(here)]
    root = here
    if not any(match for _folder, match in found) and _folder_label(here):
        root = here.parent
        found = [(folder, _folder_label(folder)) for folder in subfolders(root)]
    found = [(folder, match) for folder, match in found if match]
    if not found:
        return None
    target = next((folder for folder, (value, _number) in found if value == label), None)
    if target is None:
        names = label_folder_names()[label]
        number = found[0][1][1]
        target = root / (names[number] if number < len(names) else REVIEW_LABELS[label])
    return None if target == here else target


def label_folders(folder: Path) -> tuple[Path, list[Path]]:
    """(the folder holding the label folders, those folders) for a tab's folder.

    Inside a label folder (and none below it), its neighbours are the ones.
    """
    here = Path(folder)
    found = [path for path in subfolders(here) if _folder_label(path)]
    if not found and _folder_label(here):
        root = here.parent
        return root, [path for path in subfolders(root) if _folder_label(path)]
    return here, found


def folder_images(folder: Path) -> list[Path]:
    """The image files directly in ``folder`` (no links, no hidden files), in name order."""
    from .imaging import SUPPORTED
    from .library import filename_key
    try:
        found = [path for path in Path(folder).iterdir() if path.suffix.lower() in SUPPORTED and path.is_file()
                 and not path.is_symlink() and not path.name.startswith(".")]
    except OSError:
        return []
    return sorted(found, key=lambda path: (filename_key(path), path.name))


def create_folder(parent: Path, name: str) -> Path:
    name = name.strip()
    problem = folder_name_problem(name)
    if problem:
        raise ImageProblem(problem)
    target = Path(parent) / name
    try:
        target.mkdir()
    except FileExistsError:
        raise ImageProblem(tr("同じ名前のフォルダーかファイルがあります。別の名前にしてください。")) from None
    except OSError:
        raise ImageProblem(tr("フォルダーを作成できません。場所とアクセス権を確認してください。")) from None
    return target.resolve()


def free_target(folder: Path, name: str, reserved=frozenset()) -> Path:
    """``name`` in ``folder``, or ``name_2`` etc. when it is taken."""
    stem, suffix = Path(name).stem, Path(name).suffix
    candidate, number = folder / name, 2
    while candidate.exists() or candidate in reserved:
        candidate = folder / f"{stem}_{number}{suffix}"
        number += 1
    return candidate


def _rows(path: Path):
    database = record_path(path.parent)
    if not database.is_file():
        return {}
    rows = {}
    try:
        with closing(connect_owned(database)) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in MOVED_TABLES:
                if table not in tables:
                    continue
                available = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
                columns = TABLES[table]
                select = ",".join(column if column in available else "NULL" for column in columns)
                row = connection.execute(f"SELECT {select} FROM {table} WHERE source=?", (label_key(path),)).fetchone()
                if row:
                    rows[table] = list(row)
    except (OSError, sqlite3.Error):
        raise ImageProblem(tr("移動元の管理記録を読み込めません。")) from None
    return rows


def _write_rows(path: Path, rows):
    if not rows:
        return
    try:
        with closing(connect_owned(record_path(path.parent))) as connection:
            with connection:
                for table, row in rows.items():
                    columns = TABLES[table]
                    connection.execute(f"CREATE TABLE IF NOT EXISTS {table} ({SCHEMAS[table]})")
                    connection.execute(f"INSERT OR REPLACE INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                                       [label_key(path), *row[1:]])
    except (OSError, sqlite3.Error):
        raise ImageProblem(tr("移動先の管理記録を保存できないため、移動を中止しました。")) from None


def _delete_rows(path: Path, tables):
    database = record_path(path.parent)
    if not tables or not database.is_file():
        return
    try:
        with closing(connect_owned(database)) as connection:
            with connection:
                for table in tables:
                    connection.execute(f"DELETE FROM {table} WHERE source=?", (label_key(path),))
    except (OSError, sqlite3.Error):
        pass  # A stale record keyed to a path that no longer exists is harmless.


def _copy_verified(source: Path, target: Path, digest: bytes):
    """Exclusive create on another drive; the copy must match byte for byte."""
    try:
        writer = target.open("xb")
    except FileExistsError:
        raise ImageProblem(tr("移動先に同名のファイルが作られたため中止しました。")) from None
    try:
        with source.open("rb") as reader, writer:
            for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        if file_digest(target) != digest:
            raise ImageProblem(tr("移動先へのコピーを確認できませんでした。"))
    except BaseException:
        target.unlink(missing_ok=True)  # created exclusively above, so it is ours
        raise


def move_image(source: Path, folder: Path, *, name: str | None = None, reserved=frozenset(),
               expected_digest: bytes | None = None, cancel=None) -> Path:
    """Move ``source`` into ``folder`` (as ``name`` when free) without overwriting; its records move with it."""
    source, folder = Path(source).resolve(), Path(folder).resolve()
    if source.parent == folder:
        return source
    if not folder.is_dir():
        raise ImageProblem(tr("移動先のフォルダーが見つかりません。"))
    target = free_target(folder, name or source.name, reserved)
    with image_locks([source, target]):
        check_cancel(cancel)
        if source.is_symlink() or not source.is_file():
            raise ImageProblem(tr("移動する画像が見つかりません。"))
        digest = file_digest(source)
        if expected_digest is not None and digest != expected_digest:
            raise ImageProblem(tr("移動の前後で画像が変更されています。"))
        rows = _rows(source)
        _write_rows(target, rows)
        created = False
        try:
            try:
                os.link(source, target)
                created = True
            except FileExistsError:
                raise ImageProblem(tr("移動先に同名のファイルが作られたため中止しました。")) from None
            except OSError:
                # Another drive, or no hard links on this file system.
                _copy_verified(source, target, digest)
                created = True
            source.unlink()
        except BaseException:
            if created and source.exists():
                try:
                    if target.exists() and file_digest(target) == digest:
                        target.unlink()
                except OSError:
                    pass
            _delete_rows(target, rows)
            raise
        _delete_rows(source, rows)
    return target.resolve()


def move_images(paths, folder: Path, *, cancel=None, progress=None, expected=None):
    """Move several images; returns ({old: new}, {old: reason})."""
    moved: dict[Path, Path] = {}
    failed: dict[Path, str] = {}
    reserved: set[Path] = set()
    for number, path in enumerate(paths, 1):
        try:
            check_cancel(cancel)
        except Cancelled:
            break
        try:
            target = move_image(path, folder, reserved=frozenset(reserved), cancel=cancel,
                                expected_digest=(expected or {}).get(path))
            reserved.add(target)
            moved[path] = target
        except Cancelled:
            break
        except ImageProblem as error:
            failed[path] = str(error)
        except OSError:
            failed[path] = tr("画像を移動できません。アクセス権と、ほかのアプリで開いていないかを確認してください。")
        if progress:
            progress(number, len(paths))
    return moved, failed
