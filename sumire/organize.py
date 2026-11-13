"""Rename image files without re-encoding or overwriting unrelated files."""
from __future__ import annotations
from .i18n import tr

import os
import json
import uuid
from pathlib import Path

from .export import check_cancel, file_digest
from .imaging import ImageProblem
from .locking import image_locks
from .rename_records import plan_records, stage_records, apply_records, cleanup_records, validate_references
from . import legacy


def pending_renames(folder):
    return sorted({path for slug in ("sumire", legacy.SLUG) for path in folder.glob(f".{slug}-rename-*.json")})


def _journal(path, data):
    temporary = path.with_suffix(".writing")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def recover_rename(journal):
    """Recover only journal-owned hard links; refuse unrelated replacements."""
    try:
        if journal.is_symlink() or journal.stat().st_size > 8 * 1024 * 1024:
            raise ValueError()
        data = json.loads(journal.read_text(encoding="utf-8"))
        token = data["id"]
        if len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
            raise ValueError()
        entries = [(Path(row["old"]), Path(row["new"]), Path(row["temp"]), row["digest"]) for row in data["entries"]]
        if not entries or data["phase"] not in {"staging", "renaming", "metadata", "committed"}:
            raise ValueError()
        references = data.get("databases", [])
        validate_references(references)
        slug = legacy.SLUG if journal.name.startswith(f".{legacy.SLUG}-rename-") else "sumire"
        for number, (old, new, temporary, digest) in enumerate(entries):
            if (not old.is_absolute() or old.parent != new.parent or old.parent != temporary.parent
                    or temporary.name != f".{slug}-rename-{token}-{number}.tmp"
                    or len(digest) != 64 or old.is_symlink() or new.is_symlink() or temporary.is_symlink()):
                raise ValueError()
        if journal.parent not in {old.parent for old, *_ in entries} or journal.name != f".{slug}-rename-{token}.json":
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError):
        raise ImageProblem(tr("名前変更の復旧記録を確認できません。記録と画像を手動で確認してください。")) from None
    with image_locks([p for entry in entries for p in entry[:2]]):
        for old, new, temporary, digest in entries:
            if temporary.exists() and file_digest(temporary).hex() != digest:
                raise ImageProblem(tr("復旧用画像が変更されています。自動復旧を中止しました。"))
        if data["phase"] == "renaming":
            if any(not temporary.is_file() for _, _, temporary, _ in entries):
                raise ImageProblem(tr("復旧用画像が不足しています。自動復旧を中止しました。"))
            occupied = {p for old, new, _, _ in entries for p in (old, new) if p.exists()}
            if any(not any(os.path.samefile(p, temporary) for _, _, temporary, _ in entries) for p in occupied):
                raise ImageProblem(tr("復旧先に別のファイルがあります。自動復旧を中止しました。"))
            for path in occupied:
                path.unlink()
            for old, _, temporary, _ in entries:
                os.link(temporary, old)
        elif data["phase"] == "staging":
            if any(not old.is_file() or file_digest(old).hex() != digest for old, _, _, digest in entries):
                raise ImageProblem(tr("元画像が変更されています。自動復旧を中止しました。"))
        elif any(not new.is_file() or file_digest(new).hex() != digest for _, new, _, digest in entries):
            raise ImageProblem(tr("変更後の画像を確認できません。復旧用画像を残して中止しました。"))
        if data["phase"] == "metadata":
            try:
                apply_records(references, token)
            except (OSError, ValueError) as error:
                raise ImageProblem(tr("管理記録を復旧できませんでした。画像と復旧記録は残っています。")) from error
            data["phase"] = "committed"
            for folder in {old.parent for old, *_ in entries}:
                _journal(folder / journal.name, data)
        cleanup_records(references, token)
        for _, _, temporary, _ in entries:
            temporary.unlink(missing_ok=True)
        for folder in {old.parent for old, *_ in entries}:
            (folder / journal.name).unlink(missing_ok=True)
    return data["phase"]


def sequence_width(count: int, start: int = 0) -> int:
    """Digits of the largest number plus one spare digit (0–8 → 2 digits, 0–10 → 3 digits)."""
    return len(str(max(start, start + count - 1))) + 1


def sequence_stems(count: int, start: int = 0) -> list[str]:
    """Zero-padded numbers of one width, so every name sorts in order in Explorer."""
    width = sequence_width(count, start)
    return [str(number).zfill(width) for number in range(start, start + count)]


def renamed_path(source: Path, stem: str) -> Path:
    if (not stem or stem in {".", ".."} or stem.endswith((".", " "))
            or any(c in stem for c in '<>:"/\\|?*') or any(ord(c) < 32 for c in stem)
            or stem.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}):
        raise ImageProblem(tr("保存名に使用できない文字が含まれています。拡張子を除く名前を入力してください。"))
    return source.with_name(stem + source.suffix)


def rename_images(mapping: dict[Path, Path], *, cancel=None, progress=None, expected_digests=None, record_folders=None):
    with image_locks([*mapping, *mapping.values()]):
        if expected_digests and any(file_digest(path) != digest for path, digest in expected_digests.items()):
            raise ImageProblem(tr("名前変更後に画像が変更されています。元の名前へ戻せません。"))
        return _rename_images(mapping, cancel=cancel, progress=progress, record_folders=record_folders)


def _rename_images(mapping: dict[Path, Path], *, cancel=None, progress=None, record_folders=None):
    """Stage every source first so cycles such as 0.png <-> 1.png are safe.

    Hard links provide exclusive creation on Windows and Unix. Temporary links
    retain all original bytes until commit, and allow rollback on error/cancel.
    """
    changed = {old: new for old, new in mapping.items() if str(old) != str(new)}
    if not changed:
        return mapping
    targets = [os.path.normcase(str(path)).casefold() for path in mapping.values()]
    if len(targets) != len(set(targets)):
        raise ImageProblem(tr("変更後のファイル名が重複しています。"))
    for old, new in changed.items():
        check_cancel(cancel)
        if old.parent != new.parent or old.is_symlink() or not old.is_file():
            raise ImageProblem(tr("変更する元画像を確認できません。画像一覧を開き直してください。"))
        if new.exists() and new not in changed:
            raise ImageProblem(tr("同名ファイルが存在するため変更できません: {name}").format(name=new.name))
    staged = {}
    removed = set()
    created = set()
    token = uuid.uuid4().hex
    plans = plan_records(mapping, record_folders) if record_folders is not None else []
    planned = {old: old.parent / f".sumire-rename-{token}-{number}.tmp" for number, old in enumerate(changed)}
    journals = [folder / f".sumire-rename-{token}.json" for folder in sorted({p.parent for p in changed})]
    data = {"id": token, "phase": "staging", "databases": [reference for reference, _ in plans], "entries": [
        {"old": str(old), "new": str(changed[old]), "temp": str(temporary), "digest": file_digest(old).hex()}
        for old, temporary in planned.items()]}
    try:
        for journal in journals:
            _journal(journal, data)
        stage_records(plans, token)
        for old in changed:
            check_cancel(cancel)
            temporary = planned[old]
            os.link(old, temporary)
            staged[old] = temporary
        data["phase"] = "renaming"
        for journal in journals:
            _journal(journal, data)
        for old, temporary in staged.items():
            check_cancel(cancel)
            if not old.exists() or not os.path.samefile(old, temporary):
                raise ImageProblem(tr("名前の変更中に元画像が変更されました。"))
            old.unlink()
            removed.add(old)
        for number, (old, new) in enumerate(mapping.items(), 1):
            check_cancel(cancel)
            if old in changed:
                os.link(staged[old], new)
                created.add(old)
            if progress:
                progress(number, len(mapping))
        check_cancel(cancel)
        if plans:
            data["phase"] = "metadata"
            for journal in journals:
                _journal(journal, data)
            apply_records(data["databases"], token)
        data["phase"] = "committed"
        for journal in journals:
            _journal(journal, data)
    except BaseException:
        if data["phase"] in {"metadata", "committed"}:
            raise ImageProblem(tr("名前変更の確定が中断しました。画像と管理記録は残っています。フォルダーを開き直して復旧してください。")) from None
        restored = True
        for old in created:
            new = changed[old]
            try:
                if new.exists() and os.path.samefile(new, staged[old]):
                    new.unlink()
            except OSError:
                restored = False
        for old in removed:
            try:
                os.link(staged[old], old)
            except OSError:
                restored = False
        if not restored:
            raise ImageProblem(tr("一部のファイルを元の名前に戻せませんでした。元画像は .sumire-rename- で始まる一時ファイルに残っています。")) from None
        for temporary in staged.values():
            temporary.unlink()
        cleanup_records(data["databases"], token)
        for journal in journals:
            journal.unlink(missing_ok=True)
        raise
    cleanup_records(data["databases"], token)
    cleanup_ok = True
    for temporary in staged.values():
        try:
            temporary.unlink()
        except OSError:
            # Renames are already committed; keep the extra link rather than
            # report a failed rename after paths have actually changed.
            cleanup_ok = False
    if cleanup_ok:
        for journal in journals:
            try:
                journal.unlink(missing_ok=True)
            except OSError:
                pass
    return mapping
