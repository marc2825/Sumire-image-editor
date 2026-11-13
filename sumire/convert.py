"""Format conversion and size reduction into new, metadata-free files.

Every output is encoded in memory, decoded again and checked before it is
written: the format, size, single frame, absence of inherited metadata and,
for the encodings presented as lossless, identical pixels. Originals are never
modified. When enabled, the source's metadata is stored in the record database
under the new file, so "メタデータを復元して別名保存" works on the converted copy.
"""
from __future__ import annotations
from .i18n import tr

from dataclasses import dataclass
import hashlib
import io
import os
from pathlib import Path
import tempfile

from PIL import Image

from .editing import lanczos3_resize
from .export import check_cancel
from .imaging import HEIF_WRITABLE, ImageProblem, clean_pixels
from .stealth import remove_stealth, stealth_channels

# Pillow format name → (label, extension). HEIF needs the optional pillow-heif plugin.
TARGETS = {
    "PNG": ("PNG", ".png"),
    "JPEG": ("JPEG", ".jpg"),
    "WEBP": ("WebP", ".webp"),
    "AVIF": ("AVIF", ".avif"),
    "BMP": ("BMP", ".bmp"),
    "TIFF": ("TIFF", ".tif"),
    "GIF": ("GIF", ".gif"),
    "HEIF": ("HEIC", ".heic"),
}
# Encoder bookkeeping that Pillow reports for files carrying no metadata.
STRUCTURAL_INFO = {"jfif", "jfif_version", "jfif_unit", "jfif_density", "loop", "background", "timestamp",
                   "duration", "compression", "dpi", "resolution", "version", "transparency"}
# Image structure tags of a TIFF written by Pillow (no description, software, EXIF, GPS…).
STRUCTURAL_TIFF = {256, 257, 258, 259, 262, 273, 277, 278, 279, 282, 283, 284, 296, 317, 338, 339}


def writable(format: str) -> bool:
    return format in TARGETS and (format != "HEIF" or HEIF_WRITABLE)


@dataclass(frozen=True)
class Encoding:
    format: str = "PNG"
    quality: int | None = None      # lossy encoders only
    lossless: bool = False          # WebP: lossless mode
    colors: int | None = None       # reduce to a palette of this many colours (PNG / GIF)
    max_side: int | None = None     # shrink so the longer side fits (Lanczos3)

    @property
    def lossy(self) -> bool:
        """True when the decoded pixels may differ from the edited image."""
        if self.max_side or self.colors or self.format in {"JPEG", "AVIF", "HEIF", "GIF"}:
            return True
        return self.format == "WEBP" and not self.lossless

    def extension(self) -> str:
        return TARGETS[self.format][1]


def _flatten(pixels, background="white"):
    flat = Image.new("RGB", pixels.size, background)
    flat.paste(pixels, mask=pixels.getchannel("A"))
    return flat


def _opaque(pixels) -> bool:
    return pixels.getchannel("A").getextrema() == (255, 255)


def _exact_palette(rgb):
    """A lossless palette image when the picture has at most 256 colours, else None."""
    colors = rgb.getcolors(256)
    if not colors:
        return None
    palette = Image.new("P", (1, 1))
    flat = [channel for _, color in colors for channel in color]
    palette.putpalette(flat + [0] * (768 - len(flat)))
    mapped = rgb.quantize(palette=palette, dither=Image.Dither.NONE)
    return mapped if mapped.convert("RGB").tobytes() == rgb.tobytes() else None


def _palette(pixels, colors):
    """Reduce to ``colors`` colours, keeping fully transparent areas transparent."""
    transparent = not _opaque(pixels)
    rgb = _flatten(pixels)
    reduced = rgb.quantize(colors=min(colors, 255 if transparent else 256), method=Image.Quantize.MEDIANCUT,
                           dither=Image.Dither.FLOYDSTEINBERG)
    flat = reduced.getpalette()[:765]
    reduced.putpalette(flat + [0] * (768 - len(flat)))
    if transparent:
        reduced.paste(255, mask=pixels.getchannel("A").point(lambda value: 255 if value < 128 else 0))
        reduced.info["transparency"] = 255
    return reduced


def prepared_pixels(image, encoding: Encoding):
    pixels = clean_pixels(remove_stealth(image))
    if encoding.max_side and max(pixels.size) > encoding.max_side:
        scale = encoding.max_side / max(pixels.size)
        pixels = lanczos3_resize(pixels, (max(1, round(pixels.width * scale)), max(1, round(pixels.height * scale))))
    return pixels


def encode(image, encoding: Encoding):
    """Return (encoded bytes, pixels the file must decode to when lossless)."""
    if not writable(encoding.format):
        raise ImageProblem(tr("{get}の書き出しには対応していません。").format(get=TARGETS.get(encoding.format, (encoding.format,))[0]))
    quality = encoding.quality
    if quality is not None and (type(quality) is not int or not 1 <= quality <= 100):
        raise ImageProblem(tr("品質は1〜100で指定してください。"))
    pixels = prepared_pixels(image, encoding)
    expected = pixels
    format, options = encoding.format, {}
    if format == "PNG":
        options = {"optimize": True, "compress_level": 9}
        if encoding.colors:
            output = _palette(pixels, encoding.colors)
            if "transparency" in output.info:
                options["transparency"] = output.info["transparency"]
            expected = None
        elif _opaque(pixels):
            rgb = pixels.convert("RGB")
            output = _exact_palette(rgb) or rgb
        else:
            output = pixels
    elif format == "JPEG":
        output = _flatten(pixels)
        quality = quality or 90
        options = {"quality": quality, "subsampling": 0 if quality >= 90 else 2, "optimize": True}
        expected = None
    elif format == "WEBP":
        output = pixels
        options = {"lossless": True, "exact": True, "method": 6} if encoding.lossless else {"quality": quality or 80, "method": 6}
        expected = pixels if encoding.lossless else None
    elif format == "AVIF":
        output = pixels
        quality = quality or 60
        options = {"quality": quality, "subsampling": "4:4:4" if quality >= 90 else "4:2:0", "speed": 6}
        expected = None
    elif format == "BMP":
        # Readers ignore BMP alpha inconsistently; write a predictable opaque image.
        output = _flatten(pixels)
        expected = None if not _opaque(pixels) else pixels
    elif format == "TIFF":
        output = pixels if not _opaque(pixels) else pixels.convert("RGB")
        options = {"compression": "tiff_adobe_deflate"}
    elif format == "GIF":
        rgb = _flatten(pixels)
        exact = _exact_palette(rgb) if _opaque(pixels) and not encoding.colors else None
        output = exact or _palette(pixels, encoding.colors or 256)
        if "transparency" in output.info:
            options["transparency"] = output.info["transparency"]
        expected = pixels if exact else None
    else:  # HEIF
        output = pixels
        options = {"quality": quality or 60}
        expected = None
    stream = io.BytesIO()
    output.save(stream, format=format, **options)
    raw = stream.getvalue()
    verify_encoded(raw, format, pixels.size, expected)
    return raw


def verify_encoded(raw, format, size, expected=None):
    """Decode the new file and reject anything but plain pixels of the expected shape."""
    try:
        with Image.open(io.BytesIO(raw)) as result:
            result.load()
            if result.format != format or result.size != size or getattr(result, "n_frames", 1) != 1:
                raise ImageProblem(tr("変換後の画像の寸法・形式を検証できません。"))
            if set(result.info) - STRUCTURAL_INFO:
                raise ImageProblem(tr("変換後の画像に付加情報が見つかりました。"))
            if format == "TIFF":
                if set(result.tag_v2) - STRUCTURAL_TIFF:
                    raise ImageProblem(tr("変換後のTIFFに付加情報が見つかりました。"))
            elif result.getexif():
                raise ImageProblem(tr("変換後の画像にEXIFが見つかりました。"))
            if stealth_channels(result):
                raise ImageProblem(tr("変換後の画像に隠しメタデータが見つかりました。"))
            if expected is not None:
                decoded = result.convert("RGBA")
                if decoded.tobytes() != expected.tobytes():
                    raise ImageProblem(tr("可逆の変換で画素が変化したため中止しました。"))
    except ImageProblem:
        raise
    except (OSError, ValueError, SyntaxError):
        raise ImageProblem(tr("変換後の画像を読み込めません。")) from None


def stage(raw, folder: Path) -> Path:
    """Write encoded bytes to a hidden temporary file in ``folder`` (same volume as the target)."""
    descriptor, name = tempfile.mkstemp(prefix=".sumire-convert-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise
    return Path(name)


def commit(staged: Path, target: Path, *, source: Path | None = None, source_digest: bytes | None = None,
           backup: bool = False, cancel=None) -> bytes:
    """Create ``target`` from a staged file without replacing anything; back up metadata first."""
    from .locking import image_locks
    with image_locks([target, *([source] if source else [])]):
        check_cancel(cancel)
        digest = hashlib.sha256(staged.read_bytes()).digest()
        if backup and source is not None:
            store_source_metadata(source, target, digest, source_digest, cancel=cancel)
        try:
            os.link(staged, target)
        except FileExistsError:
            raise ImageProblem(tr("同名のファイルが先に作成されたため、この画像を中止しました。")) from None
        staged.unlink(missing_ok=True)
        return digest


def store_source_metadata(source, target, target_digest, expected_digest=None, *, cancel=None):
    """Keep the original's metadata in the target folder's records, keyed to the new file."""
    from .imaging import MAX_INPUT_BYTES
    from .metadata import MetadataStore, capture_metadata
    if source.stat().st_size > MAX_INPUT_BYTES:
        raise ImageProblem(tr("元画像が大きすぎるためメタデータを退避できません。"))
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).digest()
    if expected_digest is not None and digest != expected_digest:
        raise ImageProblem(tr("処理中に元画像が変更されました。"))
    payload = MetadataStore(source.parent).get(source, digest) or capture_metadata(raw, cancel)
    check_cancel(cancel)
    if payload is not None:
        MetadataStore(target.parent).store(target, target_digest, payload)
    return payload


def format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB" if size >= 100 * 1024 else f"{size / 1024:.1f} KB"
    if size < 1024 ** 3:
        return f"{size / 1024 / 1024:.1f} MB"
    return f"{size / 1024 ** 3:.2f} GB"


def size_summary(before: int, after: int, label: str = tr("圧縮後"), source: str = tr("元画像")) -> str:
    """「元画像3.2 MB → 圧縮後740 KB（77%削減）」"""
    return tr("{source}{before} → {label}{after}").format(source=source, before=format_bytes(before), label=label,
                                                       after=format_bytes(after)) + size_change(before, after)


def size_change(before: int, after: int) -> str:
    """「（77%削減）」"""
    text = ""
    if before <= 0:
        return text
    change = round((before - after) * 100 / before)
    if change > 0:
        return text + tr("（{change}%削減）").format(change=change)
    if change < 0:
        return text + tr("（{value}%増加）").format(value=-change)
    return text + tr("（ほぼ同じ）")
