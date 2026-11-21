"""Originals kept for this run before an overwrite replaces them.

The first time a file is overwritten in a run, its bytes are copied to a private
temporary folder (a copy, not a hard link, so an app that rewrites the file in
place can't change the kept original), so
the exact original, with its metadata and without recompression, can be put
back. The folder is removed when Sumīre exits; folders left by a crash are
removed on a later start once they are a week old.
"""
from __future__ import annotations
from .i18n import tr

import atexit
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

from .export import file_digest
from .imaging import ImageProblem

PREFIX = "sumire-backup-"
STALE_SECONDS = 7 * 24 * 60 * 60


class OriginalBackups:
    def __init__(self, parent: Path | None = None):
        self.parent = Path(parent or tempfile.gettempdir())
        self.root: Path | None = None
        self.files: dict[Path, tuple[Path, bytes]] = {}
        self.lock = threading.Lock()

    def _folder(self) -> Path:
        if self.root is None:
            self.root = Path(tempfile.mkdtemp(prefix=PREFIX, dir=self.parent))
        return self.root

    def keep(self, path: Path) -> None:
        """Keep ``path`` as it is now, unless an earlier original of this run is already kept."""
        path = Path(path).resolve()
        with self.lock:
            if path in self.files and self.files[path][0].exists():
                return
            folder = self._folder()
            target = folder / f"{len(self.files):05d}{path.suffix.lower()}"
            shutil.copy2(path, target)
            self.files[path] = (target, file_digest(target))

    def has(self, path) -> bool:
        if not isinstance(path, (str, os.PathLike)):
            return False  # an image in a ZIP is never overwritten, so nothing is kept for it
        entry = self.files.get(Path(path).resolve())
        return entry is not None and entry[0].is_file()

    def restore(self, path: Path, expected_digest: bytes | None) -> bytes:
        """Put the kept original back in place of ``path``; returns its digest.

        ``expected_digest`` is the digest of the file Sumīre last wrote or loaded:
        a file changed by another app in the meantime is never replaced.
        """
        path = Path(path).resolve()
        with self.lock:
            entry = self.files.get(path)
            if entry is None or not entry[0].is_file():
                raise ImageProblem(tr("この画像の元の状態は残っていません。"))
            backup, digest = entry
            if not path.is_file() or (expected_digest is not None and file_digest(path) != expected_digest):
                raise ImageProblem(tr("画像がほかのアプリで変更されたため、元に戻すのを中止しました。"))
            descriptor, name = tempfile.mkstemp(prefix=".sumire-", suffix=".tmp", dir=path.parent)
            temporary = Path(name)
            try:
                with os.fdopen(descriptor, "wb") as stream, backup.open("rb") as source:
                    shutil.copyfileobj(source, stream, 1024 * 1024)
                    stream.flush()
                    os.fsync(stream.fileno())
                if file_digest(temporary) != digest:
                    raise ImageProblem(tr("残しておいた元画像を確認できませんでした。"))
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            return digest

    def cleanup(self) -> None:
        with self.lock:
            if self.root is not None:
                shutil.rmtree(self.root, ignore_errors=True)
            self.root = None
            self.files.clear()


def remove_stale(parent: Path | None = None, now: float | None = None) -> None:
    """Delete folders left by runs that ended without cleaning up, once they are old."""
    parent = Path(parent or tempfile.gettempdir())
    now = time.time() if now is None else now
    try:
        candidates = list(parent.glob(PREFIX + "*"))
    except OSError:
        return
    for folder in candidates:
        try:
            if folder.is_dir() and now - folder.stat().st_mtime > STALE_SECONDS:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass


_store: OriginalBackups | None = None


def store() -> OriginalBackups:
    """The one backup store of this process, cleaned up when it exits."""
    global _store
    if _store is None:
        _store = OriginalBackups()
        atexit.register(_store.cleanup)
        remove_stale()
    return _store
