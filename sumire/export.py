"""Verified atomic export. No image data, filenames or metadata are logged."""
from __future__ import annotations
from .i18n import tr

import hashlib
import os
import struct
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .imaging import FLAT_BACKGROUND, ImageProblem, MAX_INPUT_BYTES, clean_pixels, flatten, validate_opened
from .stealth import remove_stealth, stealth_channels
from .locking import image_locks


EXTENSIONS = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "AVIF": ".avif", "BMP": ".bmp",
              "TIFF": ".tif", "GIF": ".gif", "HEIF": ".heic"}


def detect_format(path: Path) -> str | None:
    """Encoded format from the file header (no pixel decoding)."""
    try:
        with Image.open(path) as image:
            return image.format
    except (OSError, ValueError, SyntaxError):
        return None


def kept_format(format: str | None) -> str:
    """Export format that keeps the source's encoding when the verified writer supports it."""
    return format if format in {"PNG", "JPEG", "WEBP"} else "PNG"


class Cancelled(Exception):
    pass


class HiddenMetadata(ImageProblem):
    """A previously saved image may need cleaning under the stricter verifier."""


def _metadata_part(kind: bytes, format: str) -> HiddenMetadata | None:
    """A part outside the clean-file allowlist that is metadata (C2PA, tIME, APPn…): the file kept its
    metadata, which Pillow alone may not show. Anything else stays a malformed file."""
    from .metadata import _is_metadata
    payload = b"" if format != "JPEG" else b"\0"  # only the kind matters here
    return HiddenMetadata(tr("保存画像に付加メタデータが見つかりました。")) if _is_metadata(kind, payload, format) else None


def check_cancel(cancel: threading.Event | None) -> None:
    if cancel and cancel.is_set():
        raise Cancelled()


@dataclass(frozen=True)
class Verification:
    format: str
    size: tuple[int, int]
    containers: tuple[str, ...]


def _png_chunks(path: Path) -> tuple[str, ...]:
    chunks = []
    with path.open("rb") as stream:
        if stream.read(8) != b"\x89PNG\r\n\x1a\n":
            raise ImageProblem(tr("PNGの検証に失敗しました。"))
        while True:
            header = stream.read(8)
            if len(header) != 8:
                raise ImageProblem(tr("PNGが途中で切れています。"))
            length, kind = struct.unpack(">I4s", header)
            # Our RGBA writer emits only these structural/pixel chunks.
            if kind not in {b"IHDR", b"IDAT", b"IEND"}:
                raise _metadata_part(kind, "PNG") or ImageProblem(tr("出力PNGに不要なチャンクが見つかりました。"))
            chunks.append(kind.decode("ascii"))
            stream.seek(length + 4, 1)
            if kind == b"IEND":
                if stream.read(1):
                    raise ImageProblem(tr("出力PNGに余分なデータがあります。"))
                return tuple(chunks)


def _jpeg_markers(path: Path) -> tuple[str, ...]:
    markers: list[str] = []
    with path.open("rb") as stream:
        if stream.read(2) != b"\xff\xd8":
            raise ImageProblem(tr("JPEGの検証に失敗しました。"))
        scan = False
        while True:
            if scan:
                # Find the next real marker, skipping entropy-byte stuffing and
                # restart markers. Chunked scanning avoids a second whole-file copy.
                while True:
                    start = stream.tell()
                    data = stream.read(64 * 1024)
                    if not data:
                        raise ImageProblem(tr("JPEGの終端がありません。"))
                    offset = 0
                    found = False
                    while True:
                        offset = data.find(b"\xff", offset)
                        if offset < 0:
                            break
                        if offset == len(data) - 1:
                            following = stream.read(1)
                            if not following:
                                raise ImageProblem(tr("JPEGのマーカーが途中で切れています。"))
                            if following[0] != 0 and not 0xD0 <= following[0] <= 0xD7:
                                stream.seek(start + offset)
                                found = True
                            break
                        code = data[offset + 1]
                        if code == 0 or 0xD0 <= code <= 0xD7:
                            offset += 2
                            continue
                        stream.seek(start + offset)
                        found = True
                        break
                    if found:
                        break
                scan = False
            if stream.read(1) != b"\xff":
                raise ImageProblem(tr("JPEGマーカーが不正です。"))
            marker = stream.read(1)
            while marker == b"\xff":
                marker = stream.read(1)
            if len(marker) != 1:
                raise ImageProblem(tr("JPEGが途中で切れています。"))
            code = marker[0]
            if code == 0xD9:
                if stream.read(1):
                    raise ImageProblem(tr("出力JPEGに余分なデータがあります。"))
                return tuple(markers)
            if code not in {0xC0, 0xC1, 0xC2, 0xC4, 0xDB, 0xDD, 0xDA, 0xE0}:
                raise _metadata_part(bytes([code]), "JPEG") or ImageProblem(tr("出力JPEGに付加メタデータまたは不明なマーカーが見つかりました。"))
            header = stream.read(2)
            if len(header) != 2:
                raise ImageProblem(tr("JPEGが途中で切れています。"))
            length = struct.unpack(">H", header)[0]
            if length < 2:
                raise ImageProblem(tr("JPEGが不正です。"))
            payload = stream.read(length - 2)
            if len(payload) != length - 2:
                raise ImageProblem(tr("JPEGが途中で切れています。"))
            if code == 0xE0 and (len(payload) != 14 or not payload.startswith(b"JFIF\x00") or payload[12:] != b"\x00\x00"):
                raise HiddenMetadata(tr("出力JPEGに不明なAPP0があります。"))
            markers.append(f"{code:02X}")
            scan = code == 0xDA


def _webp_chunks(path: Path) -> tuple[str, ...]:
    chunks = []
    with path.open("rb") as stream:
        header = stream.read(12)
        if header[:4] != b"RIFF" or header[8:12] != b"WEBP":
            raise ImageProblem(tr("WebPの検証に失敗しました。"))
        expected = struct.unpack("<I", header[4:8])[0] + 8
        if expected != path.stat().st_size:
            raise ImageProblem(tr("WebPのサイズが不正です。"))
        while stream.tell() < expected:
            raw = stream.read(8)
            if len(raw) != 8:
                raise ImageProblem(tr("WebPが途中で切れています。"))
            kind, length = struct.unpack("<4sI", raw)
            if kind not in {b"VP8 ", b"VP8L", b"VP8X", b"ALPH"}:
                raise _metadata_part(kind, "WEBP") or ImageProblem(tr("出力WebPに不要なチャンクが見つかりました。"))
            chunks.append(kind.decode("ascii"))
            stream.seek(length + (length % 2), 1)
        if stream.tell() != expected:
            raise ImageProblem(tr("WebPが不正です。"))
    return tuple(chunks)


def verify_export(path: Path, expected_size: tuple[int, int], expected_format: str, *, allow_metadata=False) -> Verification:
    return _verify_export(path, expected_size, expected_format, allow_metadata=allow_metadata)[0]


def load_verified_export(path: Path, expected_size: tuple[int, int] | None, expected_format: str, *, allow_metadata=False):
    """Return the same decoded pixels that passed every export check."""
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ImageProblem(tr("ファイルが大きすぎます。入力の上限は256MiBです。"))
    verification, pixels = _verify_export(path, expected_size, expected_format, keep_pixels=True, allow_metadata=allow_metadata)
    return pixels, verification


def _verify_export(path, expected_size, expected_format, *, keep_pixels=False, allow_metadata=False):
    with Image.open(path) as checksum:
        checksum.verify()
    with Image.open(path) as result:
        if keep_pixels:
            validate_opened(result)
        result.load()
        if (expected_size is not None and result.size != expected_size) or result.format != expected_format or getattr(result, "n_frames", 1) != 1:
            raise ImageProblem(tr("保存画像の寸法・形式の検証に失敗しました。"))
        # JFIF version/density is structural encoder information, not inherited metadata.
        structural = {"jfif", "jfif_version", "jfif_unit", "jfif_density"}
        if expected_format == "WEBP":
            # Pillow supplies these defaults even for a static VP8L-only file.
            # The RIFF allowlist below independently rejects ANIM/ANMF chunks.
            structural |= {"loop", "background", "timestamp", "duration"}
        if not allow_metadata:
            if set(result.info) - structural or result.getexif():
                raise HiddenMetadata(tr("保存画像に付加メタデータが見つかりました。"))
            if stealth_channels(result):
                raise HiddenMetadata(tr("保存画像にNovelAI等の隠しメタデータが見つかりました。"))
            pixels = clean_pixels(result) if keep_pixels else None
        else:
            # A file saved with its metadata kept: show the same pixels a fresh load would.
            pixels = clean_pixels(remove_stealth(result)) if keep_pixels else None
        if pixels is not None:
            pixels.format = result.format
    if allow_metadata:
        return Verification(expected_format, pixels.size if pixels is not None else expected_size, ()), pixels
    readers = {"PNG": _png_chunks, "JPEG": _jpeg_markers, "WEBP": _webp_chunks}
    return Verification(expected_format, pixels.size if pixels is not None else expected_size, readers[expected_format](path)), pixels


def file_digest(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.digest()


@dataclass(frozen=True)
class SaveResult:
    path: Path
    verification: Verification
    digest: bytes
    # True when the source's metadata was written into the file (``keep_metadata``).
    metadata_kept: bool = False


def save_image(image: Image.Image, target: Path, *, source: Path, **options) -> SaveResult:
    with image_locks([source, target]):
        return _save_image(image, target, source=source, **options)


def _save_image(image: Image.Image, target: Path, *, source: Path, format: str = "PNG",
               owned_digest: bytes | None = None, cancel: threading.Event | None = None,
               background: str = FLAT_BACKGROUND, overwrite_source: bool = False,
               source_digest: bytes | None = None, backup_metadata: bool = False, jpeg_quality: int = 95,
               keep_metadata: bool = False, backup=None) -> SaveResult:
    """Overwrite an input only by explicit opt-in and a matching loaded-file digest.

    ``keep_metadata`` writes the source's metadata into the new file when the
    format allows it; otherwise the file is clean like any other save.
    ``backup`` is called with the source path just before an overwrite replaces it.
    """
    check_cancel(cancel)
    if type(jpeg_quality) is not int or not 1 <= jpeg_quality <= 100:
        raise ImageProblem(tr("JPEGの品質は1〜100で指定してください。"))
    target, source = target.resolve(), source.resolve()
    same_source = target == source or (target.exists() and source.exists() and os.path.samefile(target, source))
    if same_source and not (overwrite_source and target == source):
        raise ImageProblem(tr("元画像への上書きは、上書き保存を選んだ場合だけ行えます。"))
    if overwrite_source:
        if target != source or source_digest is None or not source.is_file():
            raise ImageProblem(tr("上書きする元画像を確認できません。画像を開き直してください。"))
        owned_digest = source_digest
    if format not in {"PNG", "JPEG", "WEBP"}:
        raise ImageProblem(tr("出力形式に対応していません。"))
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and (owned_digest is None or file_digest(target) != owned_digest):
        if overwrite_source:
            raise ImageProblem(tr("元画像が変更されています。画像を開き直してから保存してください。"))
        raise ImageProblem(tr("同名のファイルがあるか、別のアプリで変更されています。保存名を変えてください。"))
    if overwrite_source:
        with Image.open(source) as encoded:
            if encoded.format != format:
                raise ImageProblem(tr("上書き保存では元画像のPNG / JPEG / WebP形式を維持してください。"))
    payload = _keepable_metadata(source, source_digest, format, cancel) if keep_metadata else None
    descriptor, name = tempfile.mkstemp(prefix=".sumire-", suffix=".tmp", dir=target.parent)
    temporary = Path(name)
    try:
        pixels = clean_pixels(remove_stealth(image))
        if payload is not None:
            from .metadata import restored_bytes
            data = restored_bytes(pixels, payload, cancel, jpeg_quality=jpeg_quality)
            pixels = None  # type: ignore[assignment]  # freed early; only the payload is None branches use it again
        options: dict = {}
        if payload is None and format == "JPEG":
            pixels = flatten(pixels, background)
            options = {"quality": jpeg_quality, "subsampling": 0}
        elif payload is None and format == "WEBP":
            options = {"lossless": True, "exact": True}
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            if payload is not None:
                stream.write(data)
            else:
                pixels.save(stream, format=format, **options)
            stream.flush()
            os.fsync(stream.fileno())
        check_cancel(cancel)
        kept = payload is not None
        verification = verify_export(temporary, image.size, format, allow_metadata=kept)
        digest = file_digest(temporary)
        check_cancel(cancel)
        if backup_metadata and not kept:
            from .metadata import backup_before_replace
            backup_before_replace(source, target, digest, source_digest, cancel=cancel)
            check_cancel(cancel)
        if target.exists():
            if owned_digest is None or file_digest(target) != owned_digest:
                raise ImageProblem(tr("保存先が変更されたため保存を中止しました。"))
            if backup is not None and overwrite_source:
                backup(target)
            os.replace(temporary, target)
        else:
            if overwrite_source:
                raise ImageProblem(tr("元画像が移動または削除されたため、上書きを中止しました。"))
            # Atomic create-without-replace on Windows and Unix. No empty final file.
            os.link(temporary, target)
            temporary.unlink()
        return SaveResult(target, verification, digest, kept)
    except FileExistsError:
        raise ImageProblem(tr("同名ファイルが先に作成されたため保存を中止しました。")) from None
    finally:
        if descriptor != -1:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _keepable_metadata(source, source_digest, format, cancel):
    """The source's metadata when it can be written into ``format``; None when there is none or it can't be."""
    from .metadata import capture_metadata, unpack_backup
    if not source.is_file() or source.stat().st_size > MAX_INPUT_BYTES:
        return None
    raw = source.read_bytes()
    if source_digest is not None and hashlib.sha256(raw).digest() != source_digest:
        raise ImageProblem(tr("元画像が変更されています。画像を開き直してから保存してください。"))
    payload = capture_metadata(raw, cancel)
    check_cancel(cancel)
    if payload is None:
        return None
    saved_format, _parts, stealth = unpack_backup(payload)
    if saved_format != format or (stealth and format == "JPEG"):
        return None
    return payload


def available_target(folder: Path, stem: str, format: str, reserved: set[Path] | None = None) -> Path:
    if not stem or stem in {".", ".."} or any(c in stem for c in '<>:"/\\|?*') or stem.endswith((".", " ")) or any(ord(c) < 32 for c in stem):
        raise ImageProblem(tr("保存名に使用できない文字が含まれています。"))
    if stem.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        raise ImageProblem(tr("Windowsで予約された保存名です。"))
    extension = EXTENSIONS[format]
    reserved = reserved or set()
    index = 1
    while True:
        suffix = "" if index == 1 else f"_{index}"
        candidate = (folder / f"{stem}{suffix}{extension}").resolve()
        if not candidate.exists() and candidate not in reserved:
            return candidate
        index += 1
