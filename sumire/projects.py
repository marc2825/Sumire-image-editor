"""Opt-in, portable editing projects with cleaned original pixels and edit masks."""
from .i18n import tr
import io
import json
import os
from pathlib import Path
import tempfile
import zipfile

from PIL import Image

from .export import check_cancel, file_digest
from .imaging import Document, ImageProblem, MAX_PIXELS, MAX_DIMENSION, clean_pixels
from .locking import image_locks
from .stealth import remove_stealth
from . import legacy

MEMBERS = {"project.json", "original.png", "image.png", "mask.png"}
PROJECT_EXTENSIONS = {".sumire", legacy.PROJECT_EXTENSION}


def read_project(path):
    try:
        before_digest = file_digest(path)
        if path.stat().st_size > 384 * 1024 * 1024:
            raise ValueError()
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            members = {entry.filename for entry in entries}
            if (len(entries) != len(members) or members not in (MEMBERS, MEMBERS | {"initial.png"})
                    or any(entry.file_size > 100 * 1024 * 1024 for entry in entries)):
                raise ValueError()
            if archive.getinfo("project.json").file_size > 4096:
                raise ValueError()
            manifest = json.loads(archive.read("project.json"))
            if (manifest.get("version") not in {1, 2} or (manifest.get("version") == 2) != ("initial.png" in members)
                    or any(type(manifest.get(key)) is not bool for key in ("edited", "original_edited", "original_known"))):
                raise ValueError()
            pixels = {}
            for name in ("original", "image", "mask", *(("initial",) if "initial.png" in members else ())):
                with Image.open(io.BytesIO(archive.read(name + ".png"))) as image:
                    if (image.format != "PNG" or image.width * image.height > MAX_PIXELS
                            or max(image.size) > MAX_DIMENSION or (name == "mask" and image.mode != "L")):
                        raise ValueError()
                    image.load()
                    pixels[name] = image.copy() if name == "mask" else clean_pixels(remove_stealth(image))
            if len({pixels[name].size for name in ("original", "image", "mask")}) != 1:
                raise ValueError()
            if any(pixels["mask"].histogram()[1:255]):
                raise ValueError()
        if file_digest(path) != before_digest:
            raise ValueError()
        # Decoded members already own cleaned, independent pixel buffers.
        document = Document(path, Image.new("RGBA", (1, 1)))
        document.original = pixels["original"]
        document.initial_original = pixels.get("initial", document.original)
        document.geometry_edited = manifest.get("geometry", False) is True
        document.source_format = "PNG"
        document.source_digest = before_digest
        document.image = pixels["image"]
        document.edit_mask = pixels["mask"]
        document.original_edited = manifest["original_edited"]
        document.original_edit_status_known = manifest["original_known"]
        document.edited = manifest["edited"]
        document.restored_edited = manifest["edited"]
        document.project = True
        document.revision = document._sequence = 1
        return document
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, RuntimeError):
        raise ImageProblem(tr("編集プロジェクトを読み込めません。形式・破損・画像の上限を確認してください。")) from None


def write_project(path, original, image, mask, state, *, cancel=None, expected_digest=None, initial=None):
    if path.suffix.lower() not in PROJECT_EXTENSIONS:
        raise ImageProblem(tr("編集プロジェクトは.sumireで保存してください。"))
    with image_locks([path]):
        if path.is_symlink() or (path.exists() and (expected_digest is None or file_digest(path) != expected_digest)):
            raise ImageProblem(tr("同名のプロジェクトが変更されています。別の名前で保存してください。"))
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".sumire-project-", dir=path.parent)
        os.close(descriptor)
        temporary = Path(name)
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("project.json", json.dumps({**state, "version": 2 if initial is not None else 1}))
                images = [("original.png", original), ("image.png", image), ("mask.png", mask)]
                if initial is not None:
                    images.append(("initial.png", initial))
                for filename, pixels in images:
                    check_cancel(cancel)
                    cleaned = pixels if filename == "mask.png" else clean_pixels(remove_stealth(pixels))
                    stream = io.BytesIO()
                    cleaned.save(stream, format="PNG")
                    archive.writestr(filename, stream.getvalue())
            restored = read_project(temporary)
            if (restored.original.tobytes() != clean_pixels(remove_stealth(original)).tobytes()
                    or restored.image.tobytes() != clean_pixels(remove_stealth(image)).tobytes()
                    or restored.edit_mask.tobytes() != mask.tobytes()
                    or (initial is not None and restored.initial_original.tobytes() != clean_pixels(remove_stealth(initial)).tobytes())):
                raise ImageProblem(tr("プロジェクトの保存後検証に失敗しました。"))
            check_cancel(cancel)
            # Windows _commit (os.fsync) needs a descriptor opened for writing.
            with temporary.open("r+b") as stream:
                os.fsync(stream.fileno())
            if path.exists() and file_digest(path) != expected_digest:
                raise ImageProblem(tr("保存中にプロジェクトが変更されました。"))
            if expected_digest is None:
                os.link(temporary, path)
            else:
                os.replace(temporary, path)
            return path
        finally:
            temporary.unlink(missing_ok=True)
