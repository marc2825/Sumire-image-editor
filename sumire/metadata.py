"""Compressed metadata backups and explicit restoration into a separate image."""
from __future__ import annotations
from .i18n import tr

import base64
from contextlib import closing
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import struct
import tempfile
import zlib

from PIL import Image, ImageCms

from .imaging import ImageProblem, MAX_INPUT_BYTES, clean_pixels, flatten, validate_opened
from .labels import label_key
from . import provenance
from .storage import connect_owned, record_path, SCHEMAS
from .stealth import SIGNATURES, stealth_channels

MAX_BACKUP = 16 * 1024 * 1024
PNG_PIXELS = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"bKGD", b"hIST", b"acTL", b"fcTL", b"fdAT"}
WEBP_PIXELS = {b"VP8 ", b"VP8L", b"VP8X", b"ALPH", b"ANIM", b"ANMF"}


C2PA = tr("C2PA（コンテンツ認証情報）")


def categories(image, path=None, raw=None):
    """Fixed category names for an opened, loaded image; never keys or values.

    ``path`` (the image's file) or ``raw`` (its bytes) is read for the parts Pillow does not keep, such as C2PA.
    """
    found = set()
    exif = image.getexif()
    if exif:
        found.add("EXIF")
    if 34853 in exif:
        found.add(tr("GPS・位置情報"))
    if any(tag in exif for tag in (271, 272, 305, 306, 33434, 33437, 34665, 42036)):
        found.add(tr("カメラ・撮影情報"))
    keys = {str(key).lower() for key in image.info}
    if keys & {"prompt", "parameters", "negative_prompt", "workflow"}:
        found.add(tr("生成プロンプト"))
    comment = image.info.get("Comment", image.info.get("comment"))
    if isinstance(comment, str):
        try:
            parsed = json.loads(comment)
            if isinstance(parsed, dict) and {"prompt", "uc"} & parsed.keys():
                found.add(tr("生成プロンプト"))
        except (ValueError, TypeError):
            pass
    if stealth_channels(image):
        found.add(tr("Stealth PNGInfo（隠し情報）"))
    if "icc_profile" in keys:
        found.add(tr("ICCカラープロファイル"))
    if keys & {"xmp", "xml:com.adobe.xmp"}:
        found.add("XMP")
    if keys - STRUCTURAL - {"exif", "icc_profile", "xmp", "xml:com.adobe.xmp"}:
        found.add(tr("テキスト・その他の付加情報"))
    store = (provenance.raw_store(raw, image.format) if raw is not None
             else provenance.file_store(path, image.format) if path is not None else None)
    if store:
        found.add(C2PA)
    xmp = image.info.get("xmp") or image.info.get("XML:com.adobe.xmp")
    if (store and provenance.store_is_ai(store)) or provenance.AI_SOURCES & set(provenance.xmp_sources(xmp)):
        found.add(tr("AI生成の表示"))
    if xmp_has_location(xmp) or (store and b"exif:GPSLatitude" in store):
        found.add(tr("GPS・位置情報"))
    return sorted(found)


STRUCTURAL = {"jfif", "jfif_version", "jfif_unit", "jfif_density", "loop", "background", "timestamp", "duration",
              "transparency", "dpi", "compression", "resolution", "version", "gamma", "srgb", "chromaticity", "aspect",
              "progressive", "progression", "adobe", "adobe_transform", "interlace"}


def inspect_metadata(path):
    """Return fixed category names only, never arbitrary keys or their values."""
    from .export import file_digest
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ImageProblem(tr("ファイルが大きすぎます。"))
    digest = file_digest(path)
    try:
        with Image.open(path) as image:
            validate_opened(image)
            image.load()
            found = categories(image, path)
        if file_digest(path) != digest:
            raise ImageProblem(tr("確認中にファイルが変更されました。もう一度確認してください。"))
        return found
    except (OSError, ValueError, SyntaxError):
        raise ImageProblem(tr("メタデータを確認できません。形式・破損・アクセス権を確認してください。")) from None


def _parts(raw, format):
    """Yield encoded chunks/segments; JPEG scans are never treated as metadata."""
    if format in {"PNG", "WEBP"}:
        offset = 8 if format == "PNG" else 12
        while offset < len(raw):
            if offset + 8 > len(raw):
                raise ValueError()
            if format == "PNG":
                size, kind = struct.unpack_from(">I4s", raw, offset)
                end = offset + 12 + size
            else:
                kind, size = struct.unpack_from("<4sI", raw, offset)
                end = offset + 8 + size + size % 2
            if end > len(raw):
                raise ValueError()
            yield kind, raw[offset + 8:offset + 8 + size]
            offset = end
            if kind == b"IEND":
                break
    elif format == "JPEG":
        offset = 2
        while offset < len(raw):
            if raw[offset] != 255:
                # Entropy-coded scan data, with 0xFF00 stuffing and restart markers.
                offset = raw.find(b"\xff", offset)
                if offset < 0:
                    raise ValueError()
            while offset < len(raw) and raw[offset] == 255:
                offset += 1
            if offset >= len(raw):
                raise ValueError()
            code = raw[offset]
            offset += 1
            if code == 0 or 0xD0 <= code <= 0xD7:
                continue
            if code == 0xD9:
                break
            if offset + 2 > len(raw):
                raise ValueError()
            size = int.from_bytes(raw[offset:offset + 2], "big")
            if size < 2 or offset + size > len(raw):
                raise ValueError()
            yield bytes([code]), raw[offset + 2:offset + size]
            offset += size


def _is_metadata(kind, payload, format):
    if format == "PNG":
        return len(kind) == 4 and kind.isalpha() and 97 <= kind[0] <= 122 and kind not in PNG_PIXELS
    if format == "WEBP":
        return kind not in WEBP_PIXELS and len(kind) == 4
    return (len(kind) == 1 and (0xE1 <= kind[0] <= 0xEF or kind == b"\xfe")
            and not (kind == b"\xee" and payload.startswith(b"Adobe"))) or (
                kind == b"\xe0" and not (payload.startswith(b"JFIF\0") and len(payload) == 14
                                         and payload[7:] == b"\0\0\x01\0\x01\0\0"))


def _check_cancel(cancel):
    if cancel is not None:
        from .export import check_cancel
        check_cancel(cancel)


def _carrier_bytes(image, channel, byte_count, cancel=None):
    pixels = image.convert("RGBA").load()
    channels = (3,) if channel == "alpha" else (0, 1, 2)
    if byte_count * 8 > image.width * image.height * len(channels):
        raise ValueError()
    result = bytearray(byte_count)
    for index in range(byte_count * 8):
        if index % 65536 == 0:
            _check_cancel(cancel)
        pixel, part = divmod(index, len(channels))
        x, y = divmod(pixel, image.height)
        result[index // 8] |= (pixels[x, y][channels[part]] & 1) << (7 - index % 8)
    return bytes(result)


def _stealth_payloads(image, cancel=None):
    result = []
    for channel in stealth_channels(image):
        header = _carrier_bytes(image, channel, 19)
        bits = int.from_bytes(header[15:19], "big")
        if bits % 8 or bits // 8 > MAX_BACKUP:
            raise ValueError()
        result.append((channel, _carrier_bytes(image, channel, 19 + bits // 8, cancel)))
    return result


def _compress(format, parts, stealth):
    if not parts and not stealth:
        return None
    value = {"version": 1, "format": format,
             "parts": [[base64.b64encode(k).decode(), base64.b64encode(v).decode()] for k, v in parts],
             "stealth": [[k, base64.b64encode(v).decode()] for k, v in stealth]}
    raw = json.dumps(value, separators=(",", ":")).encode()
    if len(raw) > MAX_BACKUP:
        raise ImageProblem(tr("復元用メタデータが上限16MiBを超えるため、画像を保存しませんでした。"))
    return zlib.compress(raw, level=9)


def unpack_backup(blob):
    try:
        if not isinstance(blob, bytes) or len(blob) > MAX_BACKUP:
            raise ValueError()
        decoder = zlib.decompressobj()
        raw = decoder.decompress(blob, MAX_BACKUP + 1)
        if len(raw) > MAX_BACKUP or not decoder.eof or decoder.unused_data:
            raise ValueError()
        value = json.loads(raw)
        format = value["format"]
        if value["version"] != 1 or format not in {"PNG", "JPEG", "WEBP"}:
            raise ValueError()
        parts = [(base64.b64decode(k, validate=True), base64.b64decode(v, validate=True)) for k, v in value["parts"]]
        stealth = [(k, base64.b64decode(v, validate=True)) for k, v in value["stealth"]]
        if not all(_is_metadata(k, v, format) for k, v in parts):
            raise ValueError()
        if len({k for k, _ in stealth}) != len(stealth):
            raise ValueError()
        for channel, payload in stealth:
            if channel not in SIGNATURES or payload[:15] not in SIGNATURES[channel] or len(payload) < 19:
                raise ValueError()
            if int.from_bytes(payload[15:19], "big") != (len(payload) - 19) * 8:
                raise ValueError()
        return format, parts, stealth
    except (ValueError, KeyError, TypeError, zlib.error, UnicodeError):
        raise ImageProblem(tr("復元用メタデータが破損しているか、対応していません。")) from None


# Image structure tags of TIFF; everything else in IFD0 is descriptive metadata.
TIFF_STRUCTURE = {254, 255, 256, 257, 258, 259, 262, 263, 266, 273, 277, 278, 279, 280, 281, 284, 290, 291,
                  292, 293, 296, 317, 320, 322, 323, 324, 325, 338, 339, 340, 341, 347, 513, 514, 530, 531, 532}


def _itxt(keyword, text):
    return keyword.encode("latin-1") + b"\0\0\0\0\0" + text


def _portable_parts(image):
    """EXIF, ICC, XMP and comments of formats without PNG/JPEG/WebP containers, as PNG chunks."""
    parts = []
    exif = image.getexif()
    if image.format == "TIFF":
        for tag in list(exif):
            if tag in TIFF_STRUCTURE:
                del exif[tag]
    if exif:
        parts.append((b"eXIf", exif.tobytes()))
    profile = image.info.get("icc_profile")
    if profile:
        parts.append((b"iCCP", b"ICC\0\0" + zlib.compress(profile)))
    xmp = image.info.get("xmp") or image.info.get("XML:com.adobe.xmp")
    if isinstance(xmp, str):
        xmp = xmp.encode("utf-8")
    if xmp:
        parts.append((b"iTXt", _itxt("XML:com.adobe.xmp", xmp)))
    comment = image.info.get("comment")
    if isinstance(comment, str):
        comment = comment.encode("utf-8")
    if comment:
        parts.append((b"iTXt", _itxt("Comment", comment)))
    return parts


def capture_metadata(raw, cancel=None):
    try:
        with Image.open(io.BytesIO(raw)) as image:
            format = image.format
            if format not in {"PNG", "JPEG", "WEBP", "BMP"}:
                # AVIF / TIFF / GIF / HEIF: restorable as a PNG copy with the same information.
                image.load()
                return _compress("PNG", _portable_parts(image), _stealth_payloads(image, cancel))
            parts = [(k, v) for k, v in _parts(raw, format) if _is_metadata(k, v, format)]
            stealth = _stealth_payloads(image, cancel)
            if format == "BMP":
                # BMP exports as PNG; preserve the portable profile/density fields.
                format = "PNG"
                profile = image.info.get("icc_profile")
                if profile:
                    parts.append((b"iCCP", b"ICC\0\0" + zlib.compress(profile)))
                dpi = image.info.get("dpi")
                if dpi:
                    parts.append((b"pHYs", struct.pack(">IIB", round(dpi[0] / .0254), round(dpi[1] / .0254), 1)))
            return _compress(format, parts, stealth)
    except (OSError, ValueError, struct.error):
        raise ImageProblem(tr("元画像のメタデータを退避できないため、保存を中止しました。")) from None


class MetadataStore:
    def __init__(self, folder):
        self.path = record_path(folder)

    def get(self, source, digest):
        if not self.path.exists():
            return None
        try:
            with closing(connect_owned(self.path)) as connection:
                if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata_backups'").fetchone():
                    return None
                row = connection.execute("SELECT digest,previous_digest,payload FROM metadata_backups WHERE source=?", (label_key(source),)).fetchone()
            if row and digest.hex() in row[:2]:
                unpack_backup(row[2])
                return row[2]
            return None
        except (OSError, sqlite3.Error):
            raise ImageProblem(tr("復元用メタデータの管理記録を読み込めません。")) from None

    def store(self, source, digest, payload, previous_digest=None):
        unpack_backup(payload)
        try:
            with closing(connect_owned(self.path)) as connection:
                page_size = connection.execute("PRAGMA page_size").fetchone()[0]
                connection.execute(f"PRAGMA max_page_count={128 * 1024 * 1024 // page_size}")
                with connection:
                    connection.execute(f"CREATE TABLE IF NOT EXISTS metadata_backups ({SCHEMAS['metadata_backups']})")
                    connection.execute("INSERT OR REPLACE INTO metadata_backups VALUES (?,?,?,?)",
                                       (label_key(source), digest.hex(), previous_digest.hex() if previous_digest else None, payload))
        except (OSError, sqlite3.Error):
            raise ImageProblem(tr("復元用メタデータをDBへ保存できないため、画像の保存を中止しました。")) from None


def backup_before_replace(source, target, target_digest, expected_source_digest=None, *, cancel=None):
    """Commit recoverable metadata before the destructive image replacement."""
    if source.stat().st_size > MAX_INPUT_BYTES:
        raise ImageProblem(tr("元画像が大きすぎるためメタデータを退避できません。"))
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).digest()
    if expected_source_digest is not None and expected_source_digest != digest:
        raise ImageProblem(tr("元画像が変更されています。画像を開き直してから保存してください。"))
    store = MetadataStore(source.parent)
    # Prefer the original backup when re-saving an already cleaned image.
    payload = store.get(source, digest)
    if payload is None:
        payload = capture_metadata(raw, cancel)
    _check_cancel(cancel)
    if payload is not None:
        if source != target:
            store.store(source, digest, payload)
        MetadataStore(target.parent).store(target, target_digest, payload, digest if source == target else None)
    return payload


# --- pictures inside metadata ---------------------------------------------------
# Metadata written into edited pixels (kept on save, or restored) must never
# carry a picture of the image as it was: EXIF thumbnails, maker-note previews,
# Photoshop thumbnails, images in XMP (Google's GImage:Data, xmpGImg:image) or
# in text. Only parts of known kinds are written, and none containing a picture.
EMBEDDED_IMAGE = re.compile(
    rb"\xff\xd8\xff|\x89PNG\r\n\x1a\n|GIF8[79]a|RIFF.{4}WEBP|ftyp(?:avif|avis|heic|heix|mif1)"
    rb"|(?<![A-Za-z0-9+/])(?:/9j/|iVBORw0KGgo|R0lGOD[dl]h|UklGR)[A-Za-z0-9+/]{16}", re.DOTALL)
COLOUR_CHUNKS = {b"iCCP", b"sRGB", b"gAMA", b"cHRM"}
PNG_TEXT = {b"tEXt", b"zTXt", b"iTXt"}
XMP_HEADER = b"http://ns.adobe.com/xap/1.0/\0"
# IFD0 tags that point at pixel data or carry a container of their own
# (strips, JPEG thumbnail, SubIFDs, XMP, Photoshop resources).
EXIF_PICTURE_TAGS = (0x0111, 0x0117, 0x0201, 0x0202, 0x014A, 0x02BC, 0x8649)
MAKER_NOTE = 0x927C


def _inflate(data):
    """Decompressed chunk text, or None when it is broken or too large to check."""
    inflater = zlib.decompressobj()
    try:
        text = inflater.decompress(data, MAX_BACKUP)
    except zlib.error:
        return None
    return None if inflater.unconsumed_tail else text


def _png_text(kind, value):
    """The text of a PNG text chunk; None when it is malformed or can't be checked."""
    _, found, rest = value.partition(b"\0")
    if not found:
        return None
    if kind == b"tEXt":
        return rest
    if kind == b"zTXt":
        return _inflate(rest[1:]) if rest[:1] == b"\0" else None
    if len(rest) < 2 or rest[0] not in (0, 1) or rest[1] != 0:
        return None
    compressed, rest = rest[0], rest[2:]
    _, found, rest = rest.partition(b"\0")  # language
    _, found_again, text = rest.partition(b"\0")  # translated keyword
    if not (found and found_again):
        return None
    return _inflate(text) if compressed else text


def _next_ifd(tiff):
    """Offset of the IFD after IFD0 (the thumbnail's), 0 when there is none."""
    if len(tiff) < 8 or tiff[:2] not in (b"II", b"MM"):
        return 0
    order = "<" if tiff[:2] == b"II" else ">"
    offset = struct.unpack_from(order + "I", tiff, 4)[0]
    if offset + 2 > len(tiff):
        return 0
    end = offset + 2 + struct.unpack_from(order + "H", tiff, offset)[0] * 12
    return struct.unpack_from(order + "I", tiff, end)[0] if end + 4 <= len(tiff) else 0


def _exif_without_pictures(data):
    """EXIF without its thumbnail, maker note or other pictures; None to leave it out.

    Unchanged bytes when there is nothing to remove. Otherwise the EXIF is
    rewritten (dates, camera, GPS and the other fields stay); a maker note is
    dropped as a whole, since its previews can't be told apart from its data.
    """
    prefix = data.startswith(b"Exif\0\0")
    tiff = data[6:] if prefix else data
    try:
        exif = Image.Exif()
        exif.load(tiff)
        details = exif.get_ifd(0x8769) if 0x8769 in exif else {}
        if not (_next_ifd(tiff) or MAKER_NOTE in details or EMBEDDED_IMAGE.search(tiff)
                or any(tag in exif for tag in EXIF_PICTURE_TAGS)):
            return data
        for tag in EXIF_PICTURE_TAGS:
            exif.pop(tag, None)
        details.pop(MAKER_NOTE, None)
        result = exif.tobytes()[6:]
    except Exception:  # EXIF Pillow can't rewrite can't be checked either: leave it out.
        return None
    if _next_ifd(result) or EMBEDDED_IMAGE.search(result):
        return None
    return b"Exif\0\0" + result if prefix else result


def _part_without_pictures(kind, value, format):
    """The part as it may be written into edited pixels, or None to leave it out."""
    if format == "PNG":
        if kind in COLOUR_CHUNKS or kind in {b"pHYs", b"tIME"}:
            return value
        if kind == b"eXIf":
            return _exif_without_pictures(value)
        if kind in PNG_TEXT:
            text = _png_text(kind, value)
            return value if text is not None and not EMBEDDED_IMAGE.search(text) else None
        return None
    if format == "WEBP":
        if kind == b"ICCP":
            return value
        if kind == b"EXIF":
            return _exif_without_pictures(value)
        return value if kind == b"XMP " and not EMBEDDED_IMAGE.search(value) else None
    if kind == b"\xe0":  # JFIF; its optional thumbnail is uncompressed, so drop it by position
        return value[:12] + b"\0\0" if value.startswith(b"JFIF\0") and len(value) >= 14 else None
    if kind == b"\xe1":
        if value.startswith(b"Exif\0\0"):
            return _exif_without_pictures(value)
        return value if value.startswith(XMP_HEADER) and not EMBEDDED_IMAGE.search(value) else None
    if kind == b"\xe2" and value.startswith(b"ICC_PROFILE\0"):
        return value
    if kind in {b"\xed", b"\xfe"}:  # Photoshop resources (IPTC), comment
        return None if EMBEDDED_IMAGE.search(value) else value
    return None  # MPF, FlashPix, extended XMP, C2PA and other segments


def _is_c2pa(kind, value, format):
    return (format == "PNG" and kind == b"caBX") or (format == "WEBP" and kind == b"C2PA") or (
        format == "JPEG" and kind == b"\xeb" and value[:2] == b"JP")


def _keepable_c2pa(parts, format):
    """A C2PA manifest is kept whole or not at all, and never when it holds a thumbnail.

    Editing breaks its signature (verifiers then report a change), but what it records stays readable.
    """
    found = [value for kind, value in parts if _is_c2pa(kind, value, format)]
    if not found:
        return False
    store = provenance.jpeg_segments_store(found) if format == "JPEG" else provenance._extract(found[0])
    return store is not None and not provenance.has_thumbnail(store)


def without_pictures(parts, format):
    result = []
    c2pa = _keepable_c2pa(parts, format)
    for kind, value in parts:
        if _is_c2pa(kind, value, format):
            if c2pa:
                result.append((kind, value))
            continue
        value = _part_without_pictures(kind, value, format)
        if value is not None and _is_metadata(kind, value, format):
            result.append((kind, value))
    return result


def _normal_exif(data):
    # Change only Orientation in place, preserving GPS and the other fields.
    prefix = 6 if data.startswith(b"Exif\0\0") else 0
    raw = bytearray(data)
    tiff = memoryview(raw)[prefix:]
    if len(tiff) < 8 or bytes(tiff[:2]) not in {b"II", b"MM"}:
        return data
    order = "<" if bytes(tiff[:2]) == b"II" else ">"
    offset = struct.unpack_from(order + "I", tiff, 4)[0]
    if offset + 2 > len(tiff):
        return data
    count = struct.unpack_from(order + "H", tiff, offset)[0]
    for index in range(count):
        start = offset + 2 + index * 12
        if start + 12 > len(tiff):
            break
        tag, kind, number = struct.unpack_from(order + "HHI", tiff, start)
        if tag == 274 and kind == 3 and number == 1:
            struct.pack_into(order + "H", tiff, start + 8, 1)
    return bytes(raw)


def _normal_parts(parts, format):
    result, profile = [], False
    for kind, value in without_pictures(parts, format):
        if ((format == "PNG" and kind in {b"iCCP", b"gAMA", b"cHRM", b"sRGB"})
                or (format == "JPEG" and kind == b"\xe2" and value.startswith(b"ICC_PROFILE\0"))
                or (format == "WEBP" and kind == b"ICCP")):
            profile = True
            continue
        if kind in {b"eXIf", b"EXIF"} or (format == "JPEG" and kind == b"\xe1" and value.startswith(b"Exif\0\0")):
            value = _normal_exif(value)
        result.append((kind, value))
    if profile:
        srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        if format == "PNG":
            result.insert(0, (b"iCCP", b"sRGB\0\0" + zlib.compress(srgb)))
        elif format == "JPEG":
            result.insert(0, (b"\xe2", b"ICC_PROFILE\0\x01\x01" + srgb))
        else:
            result.insert(0, (b"ICCP", srgb))
    return result


def _png_chunk(kind, value):
    return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value))


def _webp_chunk(kind, value):
    return kind + struct.pack("<I", len(value)) + value + (b"\0" if len(value) % 2 else b"")


def restored_bytes(image, payload, cancel=None, *, jpeg_quality=95):
    format, parts, stealth = unpack_backup(payload)
    # Stealth needs a lossless output. Its own container is kept where possible.
    if stealth and format == "JPEG":
        raise ImageProblem(tr("JPEGには隠しメタデータを正確に復元できません。"))
    pixels = clean_pixels(image)
    for channel, data in stealth:
        channels = (3,) if channel == "alpha" else (0, 1, 2)
        if len(data) * 8 > pixels.width * pixels.height * len(channels):
            raise ImageProblem(tr("この画像サイズには隠しメタデータを復元できません。"))
        access = pixels.load()
        for index in range(len(data) * 8):
            if index % 65536 == 0:
                _check_cancel(cancel)
            pixel, part = divmod(index, len(channels))
            x, y = divmod(pixel, pixels.height)
            values = list(access[x, y])
            values[channels[part]] = (values[channels[part]] & 254) | ((data[index // 8] >> (7 - index % 8)) & 1)
            access[x, y] = tuple(values)
    output = io.BytesIO()
    if format == "JPEG":
        flat = flatten(pixels)
        flat.save(output, format="JPEG", quality=jpeg_quality, subsampling=0)
    else:
        pixels.save(output, format=format, **({"lossless": True, "exact": True} if format == "WEBP" else {}))
    raw = output.getvalue()
    parts = _normal_parts(parts, format)
    if format == "PNG":
        raw = raw[:33] + b"".join(_png_chunk(k, v) for k, v in parts) + raw[33:]
    elif format == "JPEG":
        if any(len(v) > 65533 for _, v in parts):
            raise ImageProblem(tr("JPEGのメタデータが大きすぎます。"))
        # Remove the encoder's APP0 if restoring the original APP0 instead.
        if any(k == b"\xe0" for k, _ in parts) and raw[2:4] == b"\xff\xe0":
            raw = raw[:2] + raw[4 + int.from_bytes(raw[4:6], "big"):]
        raw = raw[:2] + b"".join(b"\xff" + k + struct.pack(">H", len(v) + 2) + v for k, v in parts) + raw[2:]
    else:
        image_parts = [(k, v) for k, v in _parts(raw, format) if k != b"VP8X"]
        flags = (0x10 if pixels.getchannel("A").getextrema() != (255, 255) else 0)
        flags |= sum(flag for kind, flag in ((b"ICCP", 0x20), (b"EXIF", 0x08), (b"XMP ", 0x04)) if any(k == kind for k, _ in parts))
        vp8x = bytes([flags, 0, 0, 0]) + (pixels.width - 1).to_bytes(3, "little") + (pixels.height - 1).to_bytes(3, "little")
        chunks = [(b"VP8X", vp8x)] + [p for p in parts if p[0] == b"ICCP"] + image_parts + [p for p in parts if p[0] != b"ICCP"]
        body = b"WEBP" + b"".join(_webp_chunk(k, v) for k, v in chunks)
        raw = b"RIFF" + struct.pack("<I", len(body)) + body
    with Image.open(io.BytesIO(raw)) as restored:
        restored.load()
        if restored.size != pixels.size or restored.format != format:
            raise ImageProblem(tr("メタデータ復元後の画像を検証できません。"))
        if format != "JPEG" and restored.convert("RGBA").tobytes() != pixels.tobytes():
            raise ImageProblem(tr("メタデータ復元で画像の画素が変化しました。"))
        if _stealth_payloads(restored, cancel) != stealth:
            raise ImageProblem(tr("隠しメタデータの復元検証に失敗しました。"))
    actual = [(k, v) for k, v in _parts(raw, format) if _is_metadata(k, v, format)]
    if actual != parts:
        raise ImageProblem(tr("メタデータ復元後の照合に失敗しました。"))
    return raw


def restore_copy(image, target, payload, *, protected=(), cancel=None):
    from .export import check_cancel
    from .locking import image_locks
    target = Path(target).resolve()
    if target in {Path(path).resolve() for path in protected} or target.exists():
        raise ImageProblem(tr("復元先には新しいファイル名を指定してください。元画像や既存ファイルは上書きしません。"))
    format = unpack_backup(payload)[0]
    if target.suffix.lower() not in {"PNG": {".png"}, "JPEG": {".jpg", ".jpeg"}, "WEBP": {".webp"}}[format]:
        raise ImageProblem(tr("復元元のメタデータと同じ画像形式で保存してください。"))
    with image_locks([target, *protected]):
        check_cancel(cancel)
        raw = restored_bytes(image, payload, cancel)
        check_cancel(cancel)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".sumire-restore-", suffix=".tmp", dir=target.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            check_cancel(cancel)
            os.link(temporary, target)
        except FileExistsError:
            raise ImageProblem(tr("復元先に同名のファイルが作成されたため中止しました。")) from None
        finally:
            temporary.unlink(missing_ok=True)
    return target


# --- Reading metadata for display -------------------------------------------------

TEXT_LABELS = {
    "parameters": tr("生成パラメーター（Stable Diffusion WebUIなど）"), "prompt": tr("プロンプト（ComfyUIのワークフロー）"),
    "workflow": tr("ワークフロー（ComfyUI）"), "comment": tr("コメント"), "description": tr("説明（NovelAIではプロンプト）"),
    "software": tr("ソフトウェア"), "source": tr("生成元"), "title": tr("タイトル"), "author": tr("作者"),
    "copyright": tr("著作権"), "generation time": tr("生成時間"), "creation time": tr("作成日時"),
}
STEALTH_LIMIT = 4 * 1024 * 1024
EXIF_LABELS = {
    "Make": tr("メーカー"), "Model": tr("機種"), "Software": tr("ソフトウェア"), "DateTime": tr("更新日時"), "DateTimeOriginal": tr("撮影日時"),
    "DateTimeDigitized": tr("デジタル化の日時"), "Artist": tr("作者"), "Copyright": tr("著作権"), "ImageDescription": tr("説明"),
    "Orientation": tr("向き"), "XResolution": tr("横の解像度"), "YResolution": tr("縦の解像度"), "ResolutionUnit": tr("解像度の単位"),
    "UserComment": tr("ユーザーコメント"), "LensModel": tr("レンズ"), "ExposureTime": tr("露出時間"), "FNumber": tr("F値"),
    "ISOSpeedRatings": tr("ISO感度"), "FocalLength": tr("焦点距離"), "BodySerialNumber": tr("本体のシリアル番号"),
    "XPComment": tr("コメント（Windows）"), "XPAuthor": tr("作者（Windows）"), "XPTitle": tr("タイトル（Windows）"),
    "XPKeywords": tr("キーワード（Windows）"), "XPSubject": tr("件名（Windows）"), "HostComputer": tr("コンピューター名"),
    "GPSLatitudeRef": tr("緯度の基準（N/S）"), "GPSLatitude": tr("緯度（度, 分, 秒）"), "GPSLongitudeRef": tr("経度の基準（E/W）"),
    "GPSLongitude": tr("経度（度, 分, 秒）"), "GPSAltitude": tr("高度"), "GPSAltitudeRef": tr("高度の基準"),
    "GPSTimeStamp": tr("GPSの時刻"), "GPSDateStamp": tr("GPSの日付"),
}


def _exif_label(names, tag):
    name = names.get(tag)
    if name is None:
        return tr("不明なタグ（0x{tag:04X}）").format(tag=tag)
    return tr("{EXIF_LABELS}（{name}）").format(EXIF_LABELS=EXIF_LABELS[name], name=name) if name in EXIF_LABELS else name


def _text(value, limit=20000):
    """Readable text for a metadata value; binary data is described, not dumped."""
    if isinstance(value, bytes):
        stripped = value.rstrip(b"\0")
        try:
            value = stripped.decode("utf-8")
        except UnicodeDecodeError:
            return tr("（バイナリー・{count:,}バイト）").format(count=len(value))
        if any(ord(c) < 32 and c not in "\t\r\n" for c in value):
            return tr("（バイナリー・{count:,}バイト）").format(count=len(value))
    elif isinstance(value, tuple) and value and all(isinstance(item, (int, float)) or hasattr(item, "numerator") for item in value):
        value = ", ".join(f"{float(item):g}" for item in value)
    elif hasattr(value, "numerator") and not isinstance(value, int):
        value = f"{float(value):g}"
    value = str(value)
    try:
        parsed = json.loads(value)
        if isinstance(parsed, (dict, list)):
            value = json.dumps(parsed, ensure_ascii=False, indent=2)
    except (ValueError, TypeError):
        pass
    return value if len(value) <= limit else value[:limit] + tr("\n…（以下省略・全{count:,}文字）").format(count=len(value))


def _gps_degrees(values, ref):
    try:
        degrees, minutes, seconds = (float(value) for value in values)
        number = degrees + minutes / 60 + seconds / 3600
        return -number if ref in {"S", "W"} else number
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _stealth_text(image):
    """Decode NovelAI / stealth PNGInfo for display only."""
    import gzip
    result = []
    for channel, payload in _stealth_payloads(image):
        signature, data = payload[:15], payload[19:]
        name = signature.decode("ascii")
        try:
            if signature.endswith(b"comp"):
                with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
                    data = stream.read(STEALTH_LIMIT + 1)
                if len(data) > STEALTH_LIMIT:
                    raise ValueError()
            result.append((name, _text(data)))
        except (OSError, EOFError, ValueError):
            result.append((name, tr("不明（内容を読み取れません）")))
    return result


WHEN_WHERE = tr("日時・場所")


def _xmp_value(text, name):
    """An XMP property written as an attribute or as an element."""
    pattern = re.escape(name)
    match = re.search(rf'{pattern}="([^"]*)"|<{pattern}>([^<]*)</{pattern}>', text)
    return (match.group(1) if match.group(1) is not None else match.group(2)).strip() if match else None


def _xmp_degrees(value):
    """XMP GPS coordinates: 「35,42.2058N」 or 「35,42,12.35N」 (or a plain number)."""
    match = re.fullmatch(r"(\d+(?:\.\d+)?),(\d+(?:\.\d+)?)(?:,(\d+(?:\.\d+)?))?([NSEW])", (value or "").strip())
    if match:
        number = float(match.group(1)) + float(match.group(2)) / 60 + float(match.group(3) or 0) / 3600
        return -number if match.group(4) in {"S", "W"} else number
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _exif_time(value, offset=None):
    """「2025:10:18 10:12:36」 as 「2025-10-18 10:12:36」, with its UTC offset when recorded."""
    text = (value.decode("ascii", "replace") if isinstance(value, bytes) else str(value)).strip("\0 ")
    match = re.fullmatch(r"(\d{4}):(\d{2}):(\d{2})[ T](\d{2}:\d{2}:\d{2})", text)
    text = f"{match.group(1)}-{match.group(2)}-{match.group(3)} {match.group(4)}" if match else text
    offset = (offset.decode("ascii", "replace") if isinstance(offset, bytes) else str(offset or "")).strip("\0 ")
    return f"{text} {offset}" if offset else text


def _iso_text(value):
    moment = provenance.parse_time(value)
    return provenance.local_text(moment) if moment else value.replace("T", " ")


def when_and_where(exif, xmp, store, raw, format):
    """(item, text) rows saying when and where the image was taken or made, from every source found.

    Each value names its source (EXIF, XMP, PNG, C2PA); the first source found for an item is shown.
    """
    rows = {}

    def add(item, value, source):
        if value and item not in rows:
            rows[item] = tr("{value}（{source}）").format(value=value, source=source)

    ifd = exif.get_ifd(0x8769) if exif else {}
    gps = exif.get_ifd(0x8825) if exif else {}
    if ifd.get(0x9003):
        add(tr("撮影日時"), _exif_time(ifd[0x9003], ifd.get(0x9011)), "EXIF")
    elif ifd.get(0x9004):
        add(tr("撮影日時"), _exif_time(ifd[0x9004], ifd.get(0x9012)), "EXIF")
    if exif and exif.get(0x0132):
        add(tr("更新日時"), _exif_time(exif[0x0132], ifd.get(0x9010)), "EXIF")
    if gps:
        latitude, longitude = _gps_degrees(gps.get(2, ()), gps.get(1)), _gps_degrees(gps.get(4, ()), gps.get(3))
        if latitude is not None and longitude is not None:
            add(tr("緯度・経度"), f"{latitude:.6f}, {longitude:.6f}", "EXIF GPS")
        try:
            altitude = float(gps[6]) * (-1 if gps.get(5) in (1, b"\x01") else 1)
            add(tr("高度"), f"{altitude:.1f} m", "EXIF GPS")
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            pass
        if gps.get(29) and gps.get(7):
            try:
                clock = ":".join(f"{int(float(part)):02d}" for part in gps[7])
                add(tr("GPSの日時（UTC）"), f"{_exif_time(gps[29]).replace(':', '-')} {clock}", "EXIF GPS")
            except (TypeError, ValueError, ZeroDivisionError):
                pass
    if exif:
        camera = " ".join(str(exif[tag]).strip("\0 ") for tag in (0x010F, 0x0110) if exif.get(tag))
        add(tr("カメラ"), camera, "EXIF")
    text = xmp.decode("utf-8", "replace") if isinstance(xmp, bytes) else str(xmp or "")
    if text:
        for item, names in ((tr("撮影日時"), ("exif:DateTimeOriginal", "photoshop:DateCreated")), (tr("作成日時"), ("xmp:CreateDate",)),
                            (tr("更新日時"), ("xmp:ModifyDate",))):
            value = next(filter(None, (_xmp_value(text, name) for name in names)), None)
            add(item, value and _iso_text(value), "XMP")
        latitude, longitude = _xmp_degrees(_xmp_value(text, "exif:GPSLatitude")), _xmp_degrees(_xmp_value(text, "exif:GPSLongitude"))
        if latitude is not None and longitude is not None:
            add(tr("緯度・経度"), f"{latitude:.6f}, {longitude:.6f}", "XMP")
    info = provenance.read_manifest(store) if store else None
    if info:
        add(tr("撮影日時"), info["exif"].get("exif:DateTimeOriginal") and _iso_text(info["exif"]["exif:DateTimeOriginal"]), "C2PA")
        latitude = _xmp_degrees(info["exif"].get("exif:GPSLatitude"))
        longitude = _xmp_degrees(info["exif"].get("exif:GPSLongitude"))
        if latitude is not None and longitude is not None:
            add(tr("緯度・経度"), f"{latitude:.6f}, {longitude:.6f}", "C2PA")
        add(tr("作成日時"), info["created"] and provenance.local_text(info["created"]), "C2PA")
        add(tr("署名の日時"), info["signed"] and provenance.local_text(info["signed"]), tr("C2PA・タイムスタンプ"))
    if format == "PNG":
        for kind, payload in _parts(raw, format):
            if kind == b"tIME" and len(payload) == 7:
                year, month, day, hour, minute, second = struct.unpack(">HBBBBB", payload)
                add(tr("更新日時"), f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d} UTC", "PNG")
    order = [tr("撮影日時"), tr("作成日時"), tr("更新日時"), tr("署名の日時"), tr("緯度・経度"), tr("高度"), tr("GPSの日時（UTC）"), tr("カメラ")]
    return [(item, rows[item]) for item in order if item in rows]


def xmp_has_location(xmp):
    text = xmp.decode("utf-8", "replace") if isinstance(xmp, bytes) else str(xmp or "")
    return "exif:GPSLatitude" in text


def describe_metadata(path):
    """Every metadata entry of ``path`` as (category, item, content) for display.

    Items whose meaning is unknown are listed under 不明 with their size, never omitted.
    """
    from PIL import ExifTags
    from .archive import ArchiveEntry, read_entry
    from .export import file_digest
    if isinstance(path, ArchiveEntry):
        raw = read_entry(path)  # checked against the ZIP as listed; the ZIP is never written
        digest = None
    else:
        path = Path(path)
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise ImageProblem(tr("ファイルが大きすぎます。"))
        digest = file_digest(path)
        raw = path.read_bytes()
    entries = []
    try:
        with Image.open(io.BytesIO(raw)) as image:
            validate_opened(image)
            image.load()
            format = image.format
            exif = image.getexif()
            for tag, value in exif.items():
                if tag in {0x8769, 0x8825, 0xA005}:
                    continue
                if format == "TIFF" and tag in TIFF_STRUCTURE:
                    continue
                entries.append(("EXIF", _exif_label(ExifTags.TAGS, tag), _text(value)))
            for tag, value in exif.get_ifd(0x8769).items():
                if tag == 0x927C:
                    entries.append(("EXIF", "MakerNote", tr("（メーカー独自のデータ・{count:,}バイト）").format(count=len(value))))
                    continue
                entries.append(("EXIF", _exif_label(ExifTags.TAGS, tag), _text(value)))
            gps = exif.get_ifd(0x8825)
            for tag, value in gps.items():
                entries.append((tr("GPS・位置情報"), _exif_label(ExifTags.GPSTAGS, tag), _text(value)))
            if gps:
                latitude = _gps_degrees(gps.get(2, ()), gps.get(1))
                longitude = _gps_degrees(gps.get(4, ()), gps.get(3))
                if latitude is not None and longitude is not None:
                    entries.append((tr("GPS・位置情報"), tr("緯度・経度"), f"{latitude:.6f}, {longitude:.6f}"))
            known = {"exif", "icc_profile", "xmp", "xml:com.adobe.xmp", "comment"}
            for key, value in image.info.items():
                lowered = str(key).lower()
                if lowered in STRUCTURAL or lowered in known:
                    continue
                label = TEXT_LABELS.get(lowered, str(key))
                category = tr("生成情報") if lowered in {"parameters", "prompt", "workflow", "description", "source", "generation time"} else tr("テキスト")
                if lowered == "comment":
                    category = tr("生成情報")
                entries.append((category, label, _text(value)))
            comment = image.info.get("comment", image.info.get("Comment"))
            if comment:
                entries.append((tr("生成情報") if isinstance(comment, str) and '"prompt"' in comment else tr("コメント"), tr("コメント"), _text(comment)))
            xmp = image.info.get("xmp") or image.info.get("XML:com.adobe.xmp")
            if xmp:
                entries.extend(("XMP", tr("作成の方法（IPTC）"), provenance.source_text(code)) for code in provenance.xmp_sources(xmp))
                entries.append(("XMP", tr("XMPデータ"), _text(xmp)))
            profile = image.info.get("icc_profile")
            if profile:
                try:
                    name = ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(profile))).strip()
                except (ImageCms.PyCMSError, OSError, ValueError):
                    name = tr("不明")
                entries.append((tr("ICCカラープロファイル"), tr("プロファイル名"), tr("{value}（{count:,}バイト）").format(value=name or tr('不明'), count=len(profile))))
            for name, text in _stealth_text(image):
                entries.append((tr("Stealth PNGInfo（画素に埋め込まれた情報）"), name, text))
            store = provenance.raw_store(raw, format)
            if store:
                entries.extend((C2PA, item, text) for item, text in provenance.describe_store(store))
            # When and where first: the facts most often worth checking before sharing.
            entries[:0] = [(WHEN_WHERE, item, text) for item, text in when_and_where(exif, xmp, store, raw, format)]
            if format in {"PNG", "JPEG", "WEBP"}:
                understood = {"PNG": {b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"iCCP", b"gAMA", b"cHRM", b"sRGB", b"pHYs", b"tIME"},
                              "WEBP": {b"EXIF", b"XMP ", b"ICCP"},
                              "JPEG": {b"\xe1", b"\xe2", b"\xfe"}}[format]
                for kind, payload in _parts(raw, format):
                    if not _is_metadata(kind, payload, format) or kind in understood:
                        continue
                    if store and (kind in {b"caBX", b"C2PA"} or (kind == b"\xeb" and payload[:2] == b"JP")):
                        continue  # read above
                    if format == "PNG" and kind == b"tIME":
                        continue
                    label = tr("APP{value}セグメント").format(value=kind[0] - 0xE0) if format == "JPEG" and 0xE0 <= kind[0] <= 0xEF else (
                        tr("{decode}チャンク").format(decode=kind.decode('latin-1')))
                    entries.append((tr("不明"), label, tr("不明（{count:,}バイト）").format(count=len(payload))))
    except (OSError, ValueError, SyntaxError, struct.error):
        raise ImageProblem(tr("メタデータを読み取れません。形式・破損・アクセス権を確認してください。")) from None
    if digest is not None and file_digest(path) != digest:
        raise ImageProblem(tr("確認中にファイルが変更されました。もう一度確認してください。"))
    return entries
