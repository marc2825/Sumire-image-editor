"""C2PA (Content Credentials) and IPTC AI marks: found, shown, and removed with the metadata.

The manifests are built here from the public formats (JUMBF boxes, CBOR, a DER
certificate), independently of the reader in sumire.provenance.
"""
from datetime import datetime, timezone
import io
import struct
import zlib

from PIL import Image, PngImagePlugin

import pytest

from sumire.export import HiddenMetadata, file_digest, load_verified_export, save_image, verify_export
from sumire.imaging import ImageProblem
from sumire.imaging import load_image
from sumire.metadata import C2PA, WHEN_WHERE, describe_metadata, inspect_metadata
from sumire.provenance import describe_store, raw_store

from test_gui import window  # noqa: F401  (fixture)

AI = "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"


class Tag:
    def __init__(self, number, value):
        self.number, self.value = number, value


def head(major, number):
    if number < 24:
        return bytes([major << 5 | number])
    for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
        if number < 1 << (8 * size):
            return bytes([major << 5 | info]) + number.to_bytes(size, "big")


def cbor(value):
    if value is None:
        return b"\xf6"
    if isinstance(value, bool):
        return b"\xf5" if value else b"\xf4"
    if isinstance(value, int):
        return head(0, value) if value >= 0 else head(1, -1 - value)
    if isinstance(value, bytes):
        return head(2, len(value)) + value
    if isinstance(value, str):
        return head(3, len(value.encode())) + value.encode()
    if isinstance(value, list):
        return head(4, len(value)) + b"".join(cbor(item) for item in value)
    if isinstance(value, dict):
        return head(5, len(value)) + b"".join(cbor(key) + cbor(item) for key, item in value.items())
    return head(6, value.number) + cbor(value.value)


def box(kind, data):
    return struct.pack(">I4s", 8 + len(data), kind) + data


def superbox(kind, label, *children):
    description = kind + bytes.fromhex("00110010800000aa00389b71") + b"\x03" + label.encode() + b"\0"
    return box(b"jumb", box(b"jumd", description) + b"".join(children))


def der(tag, data):
    size = len(data)
    length = bytes([size]) if size < 128 else bytes([0x80 | 2]) + size.to_bytes(2, "big")
    return bytes([tag]) + length + data


def name(**fields):
    oids = {"O": b"\x55\x04\x0a", "CN": b"\x55\x04\x03"}
    return der(0x30, b"".join(der(0x31, der(0x30, der(6, oids[key]) + der(0x0C, value.encode()))) for key, value in fields.items()))


def certificate(organization):
    tbs = der(0x30, der(0xA0, der(2, b"\x02")) + der(2, b"\x01") + der(0x30, der(6, b"\x2a\x86\x48"))
              + name(O="Synthetic Test CA") + der(0x30, b"") + name(O=organization, CN="Signing key"))
    return der(0x30, tbs + der(0x30, b"") + der(3, b"\x00"))


def manifest_store(organization="OpenAI", generator="ChatGPT", agent="GPT-4o", when=None, timestamp=None, thumbnail=False,
                   icon=False, embedded=False):
    created = {"action": "c2pa.created", "digitalSourceType": AI, "softwareAgent": {"name": agent}}
    if when:
        created["when"] = when
    actions = {"actions": [created, {"action": "c2pa.converted"}]}
    claim = {"claim_generator_info": [{"name": generator, "version": "1.0"}], "signature": "self#jumbf=c2pa.signature"}
    # An RFC 3161 token: its TSTInfo genTime (GeneralizedTime) comes before any certificate's dates.
    unprotected = {"sigTst2": {"tstTokens": [{"val": b"\x30\x82synthetic-token\x18\x0f" + timestamp.encode() + b"\x17\x0d260408174626Z"}]}} if timestamp else {}
    signature = Tag(18, [cbor({1: -7, 33: [certificate(organization)]}), unprotected, None, b"synthetic signature"])
    return superbox(b"c2pa", "c2pa", superbox(
        b"c2ma", "urn:uuid:synthetic",
        superbox(b"c2as", "c2pa.assertions", superbox(b"cbor", "c2pa.actions", box(b"cbor", cbor(actions))),
                 *([superbox(b"bfdb", "c2pa.thumbnail.claim.jpeg", box(b"bidb", picture("JPEG")))] if thumbnail else []),
                 *([superbox(b"bfdb", "c2pa.icon", box(b"bidb", picture("PNG")))] if icon else []),
                 *([superbox(b"bfdb", "c2pa.embedded-data", box(b"bidb", picture("PNG")))] if embedded else [])),
        superbox(b"c2cl", "c2pa.claim", box(b"cbor", cbor(claim))),
        superbox(b"c2cs", "c2pa.signature", box(b"cbor", cbor(signature)))))


def picture(format, **options):
    stream = io.BytesIO()
    Image.new("RGB", (48, 32), "#8877aa").save(stream, format, **options)
    return stream.getvalue()


def png_with(store):
    data = picture("PNG")
    chunk = struct.pack(">I", len(store)) + b"caBX" + store + struct.pack(">I", zlib.crc32(b"caBX" + store))
    return data[:33] + chunk + data[33:]  # right after IHDR


def jpeg_with(store):
    """The manifest split over two APP11 segments; the second repeats the box header."""
    data, half = picture("JPEG"), len(store) // 2
    segments = b""
    for number, part in ((1, store[:half]), (2, store[:8] + store[half:])):
        payload = b"JP" + struct.pack(">HI", 1, number) + part
        segments += b"\xff\xeb" + (len(payload) + 2).to_bytes(2, "big") + payload
    return data[:2] + segments + data[2:]


def webp_with(store):
    exif = Image.Exif()
    exif[305] = "synthetic"
    data = picture("WEBP", lossless=True, exif=exif.tobytes())  # extended (VP8X) format
    chunk = b"C2PA" + struct.pack("<I", len(store)) + store + b"\0" * (len(store) % 2)
    body = data[12:] + chunk
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + body


def rows(path):
    return {(category, item): text for category, item, text in describe_metadata(path)}


def test_c2pa_in_png_jpeg_and_webp_is_found_and_described(tmp_path):
    store = manifest_store()
    for name_, data, format in (("chatgpt.png", png_with(store), "PNG"), ("chatgpt.jpg", jpeg_with(store), "JPEG"),
                                ("chatgpt.webp", webp_with(store), "WEBP")):
        path = tmp_path / name_
        path.write_bytes(data)
        assert raw_store(data, format) == store
        found = inspect_metadata(path)
        assert C2PA in found and "AI生成の表示" in found, name_
        shown = rows(path)
        assert shown[(C2PA, "作成の方法")] == "AIで生成（trainedAlgorithmicMedia）"
        assert shown[(C2PA, "署名者（検証はしていません）")] == "OpenAI"
        assert shown[(C2PA, "作成したツール")] == "ChatGPT 1.0"
        assert shown[(C2PA, "使われたAI・ソフトウェア")] == "GPT-4o"
        assert shown[(C2PA, "記録された操作")] == "c2pa.created, c2pa.converted"
        # Read, so not listed again as an unknown chunk or segment.
        assert not [key for key in shown if key[0] == "不明"], name_


def test_c2pa_alone_makes_the_metadata_status_not_empty(tmp_path):
    """Pillow keeps no trace of a caBX chunk; the file itself is read for it."""
    path = tmp_path / "claude.png"
    path.write_bytes(png_with(manifest_store("Anthropic, PBC", "Claude")))
    found = []
    load_image(path, found)
    assert C2PA in found
    assert rows(path)[(C2PA, "署名者（検証はしていません）")] == "Anthropic, PBC"


def test_saving_without_metadata_removes_c2pa(tmp_path):
    source = tmp_path / "generated.png"
    source.write_bytes(png_with(manifest_store()))
    image = load_image(source)
    result = save_image(image, source, source=source, format="PNG", overwrite_source=True, source_digest=file_digest(source))
    verify_export(result.path, image.size, "PNG")
    assert raw_store(result.path.read_bytes(), "PNG") is None
    assert inspect_metadata(result.path) == []


def test_iptc_ai_mark_in_xmp(tmp_path):
    info = PngImagePlugin.PngInfo()
    info.add_itxt("XML:com.adobe.xmp", f'<x:xmpmeta><rdf:Description Iptc4xmpExt:DigitalSourceType="{AI}"/></x:xmpmeta>')
    path = tmp_path / "marked.png"
    Image.new("RGB", (8, 8)).save(path, pnginfo=info)
    assert "AI生成の表示" in inspect_metadata(path)
    assert rows(path)[("XMP", "作成の方法（IPTC）")] == "AIで生成（trainedAlgorithmicMedia）"


def test_damaged_manifest_is_reported_not_raised():
    store = manifest_store()
    broken = store[:40] + b"\xff" * (len(store) - 40)
    assert describe_store(broken)[-1][0] == "C2PAの記録"
    assert "内容を読み取れません" in describe_store(broken)[-1][1]


def local(*parts):
    moment = datetime(*parts, tzinfo=timezone.utc).astimezone()
    offset = moment.strftime("%z")
    return f"{moment:%Y-%m-%d %H:%M:%S} {offset[:3]}:{offset[3:]}"


def when_where(path):
    return {item: text for category, item, text in describe_metadata(path) if category == WHEN_WHERE}


def test_when_and_where_from_c2pa_times(tmp_path):
    """ChatGPT's manifest records when it made the image, and a timestamp authority vouches for the signing time."""
    path = tmp_path / "IMG_20251018_101236.png"  # a camera-like name says nothing about when it was made
    path.write_bytes(png_with(manifest_store(when="2026-11-14T03:23:43.439930276Z", timestamp="20261114032343Z")))
    found = when_where(path)
    assert found["作成日時"] == f"{local(2026, 11, 14, 3, 23, 43)}（C2PA）"
    assert found["署名の日時"] == f"{local(2026, 11, 14, 3, 23, 43)}（C2PA・タイムスタンプ）"
    assert list(when_where(path)) == ["作成日時", "署名の日時"]  # listed first, in a fixed order
    assert describe_metadata(path)[0][0] == WHEN_WHERE


def test_when_and_where_from_exif_photo(tmp_path):
    exif = Image.Exif()
    exif[0x010F], exif[0x0110], exif[0x0132] = "Synthetic", "Camera 1", "2025:10:18 11:00:00"
    exif.get_ifd(0x8769).update({0x9003: "2025:10:18 10:12:36", 0x9011: "+09:00"})
    exif.get_ifd(0x8825).update({1: "N", 2: (35.0, 42.0, 39.6), 3: "E", 4: (139.0, 47.0, 48.0), 5: b"\x00", 6: 12.5,
                                 7: (1.0, 12.0, 36.0), 29: "2025:10:18"})
    path = tmp_path / "photo.jpg"
    Image.new("RGB", (40, 30)).save(path, exif=exif)
    assert when_where(path) == {
        "撮影日時": "2025-10-18 10:12:36 +09:00（EXIF）", "更新日時": "2025-10-18 11:00:00（EXIF）",
        "緯度・経度": "35.711000, 139.796667（EXIF GPS）", "高度": "12.5 m（EXIF GPS）",
        "GPSの日時（UTC）": "2025-10-18 01:12:36（EXIF GPS）", "カメラ": "Synthetic Camera 1（EXIF）"}


def test_when_and_where_from_xmp_counts_as_location(tmp_path):
    info = PngImagePlugin.PngInfo()
    info.add_itxt("XML:com.adobe.xmp", '<x:xmpmeta><rdf:Description exif:DateTimeOriginal="2025-10-18T10:12:36"'
                                      ' exif:GPSLatitude="35,42.66N" exif:GPSLongitude="139,47.8E"/></x:xmpmeta>')
    path = tmp_path / "xmp.png"
    Image.new("RGB", (8, 8)).save(path, pnginfo=info)
    assert when_where(path) == {"撮影日時": "2025-10-18 10:12:36（XMP）", "緯度・経度": "35.711000, 139.796667（XMP）"}
    assert "GPS・位置情報" in inspect_metadata(path)


def test_nothing_about_when_or_where_adds_no_rows(tmp_path):
    path = tmp_path / "plain.png"
    Image.new("RGB", (8, 8)).save(path)
    assert when_where(path) == {}


def save_keeping_metadata(source, format):
    image = load_image(source)
    image.paste("black", (2, 2, 12, 12))
    return save_image(image, source, source=source, format=format, overwrite_source=True,
                      source_digest=file_digest(source), keep_metadata=True)


def test_keeping_metadata_keeps_c2pa(tmp_path):
    """ChatGPT images carry only C2PA: with 「保存してもメタデータを残す」 it must survive an edit."""
    store = manifest_store(when="2026-11-14T03:23:43Z")
    for name_, data, format in (("kept.png", png_with(store), "PNG"), ("kept.jpg", jpeg_with(store), "JPEG"),
                                ("kept.webp", webp_with(store), "WEBP")):
        path = tmp_path / name_
        path.write_bytes(data)
        assert save_keeping_metadata(path, format).metadata_kept
        assert raw_store(path.read_bytes(), format) == store, name_
        assert C2PA in inspect_metadata(path)
        assert when_where(path)["作成日時"] == f"{local(2026, 11, 14, 3, 23, 43)}（C2PA）"


def test_c2pa_holding_a_thumbnail_is_not_kept(tmp_path):
    """A thumbnail is a small copy of the unedited image: a mosaicked area must not survive in it."""
    path = tmp_path / "thumbnail.png"
    path.write_bytes(png_with(manifest_store(thumbnail=True)))
    save_keeping_metadata(path, "PNG")
    assert raw_store(path.read_bytes(), "PNG") is None


def test_a_saved_file_that_kept_c2pa_counts_as_keeping_metadata(tmp_path):
    """Reopening such a file must not fail as 「出力PNGに不要なチャンク」: Pillow shows nothing of C2PA."""
    store = manifest_store()
    for name_, data, format in (("again.png", png_with(store), "PNG"), ("again.jpg", jpeg_with(store), "JPEG"),
                                ("again.webp", webp_with(store), "WEBP")):
        path = tmp_path / name_
        path.write_bytes(data)
        save_keeping_metadata(path, format)
        with pytest.raises(HiddenMetadata):
            load_verified_export(path, None, format)
    # A part that is not metadata is still a broken file.
    broken = tmp_path / "broken.png"
    data = picture("PNG")
    broken.write_bytes(data[:33] + struct.pack(">I", 0) + b"XXXX" + struct.pack(">I", zlib.crc32(b"XXXX")) + data[33:])
    with pytest.raises(ImageProblem) as error:
        load_verified_export(broken, None, "PNG")
    assert not isinstance(error.value, HiddenMetadata)


def test_an_edited_c2pa_image_opens_again_in_the_window(qtbot, window, tmp_path):
    from test_gui import draw
    folder = tmp_path / "chatgpt"
    folder.mkdir()
    for name_ in ("a.png", "b.png"):
        (folder / name_).write_bytes(png_with(manifest_store()))
    window.strip_metadata.setChecked(False)  # 保存してもメタデータを残す
    window.auto.setChecked(False)
    window.open_inputs([str(folder)])
    qtbot.waitUntil(lambda: window.document is not None and window.document.path.parent == folder.resolve()
                    and window.canvas.ready, timeout=10000)
    path = window.document.path
    draw(window, start=(5, 10), end=(40, 10))  # in the 48 × 32 picture
    qtbot.waitUntil(lambda: window.document.dirty and not window.finalizing and window.canvas.ready, timeout=10000)
    window.save()
    qtbot.waitUntil(lambda: not window.saving and not window.document.dirty, timeout=10000)
    assert raw_store(path.read_bytes(), "PNG") == manifest_store()
    window.navigate(1)
    qtbot.waitUntil(lambda: window.document is not None and window.document.path != path and window.canvas.ready, timeout=10000)
    window.documents.pop(path, None)  # read it from the file again
    window.navigate(-1)
    qtbot.waitUntil(lambda: (window.document is not None and window.document.path == path and window.canvas.ready)
                    or "読み込みエラー" in window.model.states.get(path, ""), timeout=10000)
    assert "読み込みエラー" not in window.model.states.get(path, "")
    assert C2PA in window.document.metadata and "保存済み" in window.model.states[path]


def test_c2pa_with_an_icon_is_kept_but_embedded_image_data_is_not(tmp_path):
    """ChatGPT's manifest carries the issuer's icon (kept); any other embedded picture may copy the image."""
    kept = tmp_path / "icon.png"
    kept.write_bytes(png_with(manifest_store(icon=True)))
    save_keeping_metadata(kept, "PNG")
    assert raw_store(kept.read_bytes(), "PNG") == manifest_store(icon=True)
    dropped = tmp_path / "embedded.png"
    dropped.write_bytes(png_with(manifest_store(embedded=True)))
    save_keeping_metadata(dropped, "PNG")
    assert raw_store(dropped.read_bytes(), "PNG") is None
