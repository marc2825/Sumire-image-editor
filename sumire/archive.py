"""Images inside a ZIP file, browsed in place and never changed.

A ZIP is listed once (its central directory only, no image is decoded) into ``ArchiveEntry``
values. An entry is not a ``Path`` and has no ``__fspath__``: code that would open, rename or
delete a file fails loudly instead of touching the archive. Each read opens the ZIP again and
checks that it is the file that was listed (size and modification time) and that the entry is the
one that was listed (size and CRC-32), so a ZIP changed or removed meanwhile is reported, not
misread; the ZIP is never held open, so it can be moved or deleted while it is browsed.

Entries that could be unsafe or ambiguous are left out of the list and counted: names that are
absolute, contain ``..`` or control characters, duplicates, encrypted entries, links and other
special files, unknown compression, and sizes past the limits (a ZIP bomb declares a huge size or
an extreme compression ratio). Pixel limits are the same as for files (``imaging``).
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import zipfile
import zlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .i18n import tr

ARCHIVE_SUFFIXES = {".zip"}
MAX_ENTRIES = 20_000  # items in the central directory
MAX_ENTRY_BYTES = 256 * 1024 * 1024  # one image after decompression, like an image file (imaging.MAX_INPUT_BYTES)
MAX_RATIO = 200  # compression ratio allowed for an entry larger than RATIO_FLOOR
RATIO_FLOOR = 16 * 1024 * 1024
METHODS = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".avif", ".tif", ".tiff", ".gif"}
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


def problem(message):
    from .imaging import ImageProblem
    return ImageProblem(message)


def is_archive(path) -> bool:
    path = Path(path)
    return path.suffix.lower() in ARCHIVE_SUFFIXES and path.is_file()


def safe_member(name: str) -> str | None:
    """The entry's path inside the ZIP with "/" separators, or None when it is not a safe relative path."""
    if not name or "\x00" in name or any(ord(char) < 32 for char in name):
        return None
    name = name.replace("\\", "/")
    if name.startswith("/") or _WINDOWS_DRIVE.match(name):
        return None
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return None
    return "/".join(parts)


@dataclass(frozen=True)
class ArchiveEntry:
    """One image inside a ZIP: where it is, and what was listed (to notice a changed ZIP)."""
    archive: Path
    member: str  # the safe path inside the ZIP, "/" separated
    stored: str  # the name exactly as in the ZIP, to find it again
    size: int
    packed: int
    crc: int
    modified: tuple[int, int, int, int, int, int]
    stamp: tuple[int, int] = field(compare=False)  # the ZIP's size and modification time when listed

    @property
    def name(self) -> str:
        return PurePosixPath(self.member).name

    @property
    def stem(self) -> str:
        return PurePosixPath(self.member).stem

    @property
    def suffix(self) -> str:
        return PurePosixPath(self.member).suffix

    @property
    def folder(self) -> str:
        """The folder inside the ZIP ("" for the top)."""
        parent = PurePosixPath(self.member).parent
        return "" if str(parent) == "." else str(parent)

    @property
    def key(self) -> str:
        """Identifies this image for its label: the ZIP's location, the name inside and the content (CRC, size).

        Another ZIP, another entry of the same name, or a changed entry gets another key, so a label
        never moves to a different image; moving or renaming the ZIP leaves its labels behind.
        """
        text = "\0".join((os.path.normcase(str(self.archive)), self.member, f"{self.crc:08x}", str(self.size)))
        return hashlib.sha256(("zip\0" + text).encode("utf-8")).hexdigest()

    def __str__(self):
        return f"{self.archive} › {self.member}"


@dataclass
class ArchiveCatalog:
    path: Path
    entries: list[ArchiveEntry]
    skipped: Counter = field(default_factory=Counter)

    def __post_init__(self):
        folders = {""}
        for entry in self.entries:
            parts = entry.member.split("/")[:-1]
            folders.update("/".join(parts[:end]) for end in range(1, len(parts) + 1))
        self.folders = folders

    def entries_in(self, folder: str) -> list[ArchiveEntry]:
        return [entry for entry in self.entries if entry.folder == folder]

    def subfolders(self, folder: str) -> list[str]:
        prefix = folder + "/" if folder else ""
        return sorted((name for name in self.folders if name.startswith(prefix) and name != folder
                       and "/" not in name[len(prefix):]), key=str.casefold)

    def skipped_text(self) -> str:
        """「開けない項目」 for the status line, or ""."""
        if not self.skipped:
            return ""
        reasons = {"name": tr("名前が不正"), "duplicate": tr("名前の重複"), "encrypted": tr("暗号化"),
                   "special": tr("リンクなど"), "method": tr("未対応の圧縮"), "size": tr("大きすぎる")}
        detail = tr("、").join(f"{reasons[key]} {count}" for key, count in self.skipped.items())
        return tr("一覧に出していない項目：{detail}").format(detail=detail)


def _stamp(path: Path) -> tuple[int, int]:
    try:
        info = path.stat()
    except FileNotFoundError:
        raise problem(tr("ZIPファイルが見つかりません。移動・削除された可能性があります。")) from None
    except OSError:
        raise problem(tr("ZIPファイルを読めません。アクセス権を確認してください。")) from None
    return info.st_size, info.st_mtime_ns


def read_catalog(path, cancel=None) -> ArchiveCatalog:
    """List the images of the ZIP at ``path`` (its directory only; nothing is decompressed)."""
    from .export import check_cancel
    path = Path(path).resolve()
    stamp = _stamp(path)
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, ValueError, EOFError, NotImplementedError):
        raise problem(tr("ZIPファイルを開けません。壊れているか、ZIP形式ではありません。")) from None
    if len(infos) > MAX_ENTRIES:
        raise problem(tr("ZIPの項目が多すぎます（{count:,}件まで）。").format(count=MAX_ENTRIES))
    files = [info for info in infos if not info.is_dir()]
    members = {id(info): safe_member(info.filename) for info in files}
    counts = Counter(member for member in members.values() if member is not None)
    entries: list[ArchiveEntry] = []
    skipped: Counter = Counter()
    for info in files:
        check_cancel(cancel)
        member = members[id(info)]
        if member is not None and PurePosixPath(member).suffix.lower() not in IMAGE_SUFFIXES:
            continue  # other files are simply not shown
        if member is None:
            if PurePosixPath(info.filename.replace("\\", "/")).suffix.lower() in IMAGE_SUFFIXES:
                skipped["name"] += 1
            continue
        mode = info.external_attr >> 16
        if counts[member] > 1:
            skipped["duplicate"] += 1
        elif info.flag_bits & 0x1:
            skipped["encrypted"] += 1
        elif info.create_system == 3 and stat.S_IFMT(mode) not in (0, stat.S_IFREG):
            skipped["special"] += 1  # a symbolic link, device or the like (Unix file type bits)
        elif info.compress_type not in METHODS:
            skipped["method"] += 1
        elif (info.file_size > MAX_ENTRY_BYTES or info.file_size < 0 or info.compress_size < 0
              or (info.file_size > RATIO_FLOOR and info.file_size > MAX_RATIO * max(1, info.compress_size))):
            skipped["size"] += 1
        else:
            entries.append(ArchiveEntry(path, member, info.filename, info.file_size, info.compress_size, info.CRC,
                                        tuple(info.date_time), stamp))  # type: ignore[arg-type]
    return ArchiveCatalog(path, entries, skipped)


def read_entry(entry: ArchiveEntry, cancel=None) -> bytes:
    """The entry's bytes exactly as stored, after checking that the ZIP and the entry are the ones listed."""
    if _stamp(entry.archive) != entry.stamp:
        raise problem(tr("開いた後にZIPファイルが変更されました。再読み込み（Ctrl+R）で開き直してください。"))
    try:
        with zipfile.ZipFile(entry.archive) as archive:
            try:
                info = archive.getinfo(entry.stored)
            except KeyError:
                raise problem(tr("開いた後にZIPファイルが変更されました。再読み込み（Ctrl+R）で開き直してください。")) from None
            if (info.file_size, info.compress_size, info.CRC) != (entry.size, entry.packed, entry.crc):
                raise problem(tr("開いた後にZIPファイルが変更されました。再読み込み（Ctrl+R）で開き直してください。"))
            with archive.open(info) as stream:
                data = stream.read(MAX_ENTRY_BYTES + 1)  # the decompressor stops at the listed size and checks the CRC
    except (zipfile.BadZipFile, zlib.error, EOFError, OSError, RuntimeError, NotImplementedError, ValueError, LookupError):
        raise problem(tr("ZIPの中の画像を読めません。ZIPが壊れている可能性があります。")) from None
    if len(data) != entry.size:
        raise problem(tr("ZIPの中の画像を読めません。ZIPが壊れている可能性があります。"))
    return data


def export_name(entry: ArchiveEntry, keep_folders: bool) -> PurePosixPath:
    """Where an exported entry goes, relative to the chosen folder; every part made safe for Windows too."""
    parts = entry.member.split("/") if keep_folders else [entry.name]
    return PurePosixPath(*(_safe_part(part) for part in parts))


_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))}


def _safe_part(part: str) -> str:
    cleaned = re.sub(r'[<>:"|?*\x00-\x1f]', "_", part).rstrip(" .") or "_"
    if cleaned.split(".")[0].upper() in _RESERVED:
        cleaned = "_" + cleaned
    return cleaned


def _write_new(target: Path, data: bytes, another) -> Path:
    """Create ``target`` with ``data``; if a file appeared there meanwhile, use ``another()``. No partial file is left."""
    for _ in range(3):
        try:
            stream = open(target, "xb")  # "x": never replace an existing file
        except FileExistsError:
            target = another()
            continue
        try:
            with stream:
                stream.write(data)
        except OSError:
            target.unlink(missing_ok=True)
            raise
        return target
    raise FileExistsError(target)


def export_entries(entries, folder: Path, *, keep_folders=False, cancel=None, progress=None):
    """Write the entries' bytes, unchanged, as new files under ``folder``; existing files are never overwritten.

    A name that is taken gets "_2" and so on. Returns {entry: written path}.
    """
    from .export import check_cancel
    from .folders import free_target
    folder = Path(folder).resolve()
    written = {}
    reserved: set[Path] = set()
    for number, entry in enumerate(entries, 1):
        check_cancel(cancel)
        relative = export_name(entry, keep_folders)
        target_folder = (folder / relative.parent) if relative.parent != PurePosixPath(".") else folder
        target = free_target(target_folder, relative.name, frozenset(reserved))
        if not target.resolve().is_relative_to(folder):
            raise problem(tr("書き出し先がフォルダーの外になるため、中止しました。"))
        data = read_entry(entry, cancel)
        check_cancel(cancel)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target = _write_new(target, data, lambda: free_target(target_folder, relative.name, frozenset(reserved)))
        except OSError:
            raise problem(tr("書き出せませんでした。書き出し先の空き容量とアクセス権を確認してください。")) from None
        reserved.add(target)
        written[entry] = target
        if progress is not None:
            progress(number, len(entries))
    return written
