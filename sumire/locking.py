"""Cross-process, crash-released locks shared by Sumīre saves and renames."""
from .i18n import tr
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import tempfile

from .imaging import ImageProblem
from . import legacy


@contextmanager
def image_locks(paths):
    user = getattr(os, 'getuid', lambda: 'user')()
    folders = [Path(tempfile.gettempdir()) / f"{slug}-locks-{user}" for slug in ("sumire", legacy.SLUG)]
    for folder in folders:
        folder.mkdir(exist_ok=True)
    handles = []
    identities = sorted({os.path.normcase(str(Path(path).resolve())) for path in paths})
    try:
        # Also acquire the legacy lock so an older running version cannot save
        # or rename the same image while the new version owns it.
        for identity, folder in ((identity, folder) for identity in identities for folder in folders):
            path = folder / (hashlib.sha256(identity.encode()).hexdigest() + ".lock")
            stream = path.open("a+b")
            try:
                if os.name == "nt":
                    import msvcrt
                    if path.stat().st_size == 0:
                        stream.write(b"0")
                        stream.flush()
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                stream.close()
                raise ImageProblem(tr("別のSumīreがこの画像を処理中です。完了後に再試行してください。")) from None
            handles.append(stream)
        yield
    finally:
        for stream in reversed(handles):
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            stream.close()
