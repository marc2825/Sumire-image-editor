"""Image files on the clipboard: copy or cut in the list, paste into the folder of the tab.

The clipboard holds file links, as Explorer does, so files copied in Sumīre paste in
Explorer and the other way round. "Preferred DropEffect" tells cut (move) from copy.
"""
from __future__ import annotations

import shutil
import struct
from pathlib import Path

from PySide6.QtCore import QMimeData, QUrl

from .export import check_cancel
from .folders import free_target
from .imaging import SUPPORTED

DROP_EFFECT = 'application/x-qt-windows-mime;value="Preferred DropEffect"'
CUT_MIME = "application/x-sumire-cut"
MOVE, COPY = 2, 5  # DROPEFFECT_MOVE; DROPEFFECT_COPY | DROPEFFECT_LINK, as Explorer writes for a copy


def file_mime(paths, cut: bool) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    mime.setText("\n".join(str(path) for path in paths))
    mime.setData(DROP_EFFECT, struct.pack("<I", MOVE if cut else COPY))
    mime.setData(CUT_MIME, b"1" if cut else b"0")
    return mime


def clipboard_files(mime) -> tuple[list[Path], bool]:
    """(image files on the clipboard, whether they were cut); folders and other files are left out."""
    if mime is None or not mime.hasUrls():
        return [], False
    paths = []
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = Path(url.toLocalFile())
        if path.suffix.lower() in SUPPORTED and path.is_file() and not path.is_symlink():
            paths.append(path)
    if mime.hasFormat(CUT_MIME):
        cut = bytes(mime.data(CUT_MIME)) == b"1"
    else:
        effect = bytes(mime.data(DROP_EFFECT))
        cut = len(effect) >= 4 and struct.unpack("<I", effect[:4])[0] & 3 == MOVE
    return paths, cut


def copy_files(paths, folder: Path, cancel=None):
    """Copy each image into ``folder`` under a free name (never over an existing file).

    Returns ({source: copy}, {source: reason}). Records (labels, notes) stay with the original.
    """
    copied: dict[Path, Path] = {}
    failed: dict[Path, str] = {}
    reserved: set[Path] = set()
    for path in paths:
        check_cancel(cancel)
        target = free_target(folder, path.name, frozenset(reserved))
        created = False
        try:
            with path.open("rb") as source, target.open("xb") as stream:  # "x": fails rather than replace
                created = True
                shutil.copyfileobj(source, stream, 1024 * 1024)
            shutil.copystat(path, target)
            reserved.add(target)
            copied[path] = target
        except OSError as error:
            if created:
                target.unlink(missing_ok=True)  # a partial copy (disk full, file in use) is not left behind
            failed[path] = "exists" if isinstance(error, FileExistsError) else "error"
    return copied, failed
