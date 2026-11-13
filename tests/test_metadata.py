from contextlib import closing
import io
import threading
import zlib

import pytest
from PIL import Image, ImageCms, PngImagePlugin

from sumire.export import Cancelled, file_digest, save_image, verify_export
from sumire.imaging import ImageProblem, load_image
from sumire.metadata import MetadataStore, capture_metadata, restore_copy, restored_bytes, unpack_backup
from sumire.organize import rename_images
from sumire.preferences import Preferences
from sumire.storage import delete_records, migrate_records, record_path


def source_with_metadata(path, format):
    image = Image.new("RGB", (80, 60), "#d0a080")
    exif = Image.Exif()
    exif[315] = "synthetic artist"
    exif[34853] = {1: "N", 2: (35., 0., 0.)}
    options = {"exif": exif, "xmp": b"<x:xmpmeta>synthetic XMP</x:xmpmeta>"}
    if format == "PNG":
        info = PngImagePlugin.PngInfo()
        info.add_itxt("parameters", "日本語のプロンプト " * 100, zip=True)
        info.add_text("Comment", "synthetic comment")
        options["pnginfo"] = info
    image.save(path, format=format, **options)
    if format == "JPEG":
        data = path.read_bytes()
        comment = b"synthetic comment"
        iptc = b"Photoshop 3.0\0synthetic IPTC"
        path.write_bytes(data[:2] + b"\xff\xfe" + (len(comment) + 2).to_bytes(2, "big") + comment
                         + b"\xff\xed" + (len(iptc) + 2).to_bytes(2, "big") + iptc + data[2:])
    return path


@pytest.mark.parametrize("format,extension", [("PNG", ".png"), ("JPEG", ".jpg"), ("WEBP", ".webp")])
def test_metadata_roundtrip_keeps_edits_and_original_fields(tmp_path, format, extension):
    source = source_with_metadata(tmp_path / ("日本語" + extension), format)
    original_payload = unpack_backup(capture_metadata(source.read_bytes()))
    image = load_image(source)
    image.paste("black", (20, 15, 60, 45))
    result = save_image(image, source, source=source, format=format, overwrite_source=True,
                        source_digest=file_digest(source), backup_metadata=True)
    verify_export(source, image.size, format)
    blob = MetadataStore(tmp_path).get(source, result.digest)
    assert unpack_backup(blob) == original_payload
    assert b"synthetic artist" not in record_path(tmp_path).read_bytes()
    restored = tmp_path / ("restored" + extension)
    restore_copy(image, restored, blob, protected=[source])
    with Image.open(restored) as output:
        assert output.getexif()[315] == "synthetic artist"
        assert output.getexif().get_ifd(34853)[1] == "N"
        assert output.convert("RGB").getpixel((40, 30)) == (0, 0, 0)
        if format == "PNG":
            assert output.info["parameters"] == "日本語のプロンプト " * 100
            assert output.convert("RGBA").tobytes() == image.tobytes()
        if format == "WEBP":
            assert output.info["xmp"] == b"<x:xmpmeta>synthetic XMP</x:xmpmeta>"
            assert output.convert("RGBA").tobytes() == image.tobytes()
    assert unpack_backup(capture_metadata(restored.read_bytes())) == original_payload
    assert file_digest(source) == result.digest


@pytest.mark.parametrize("channel", ["alpha", "rgb"])
@pytest.mark.parametrize("compressed", [False, True])
def test_hidden_prompt_roundtrip(tmp_path, patterned, encode_stealth, decode_stealth, channel, compressed):
    source = tmp_path / "hidden.png"
    original = encode_stealth(patterned, channel=channel, compressed=compressed)
    expected = decode_stealth(original, channel=channel)
    original.save(source)
    image = load_image(source)
    image.paste("black", (50, 50, 100, 90))
    result = save_image(image, source, source=source, overwrite_source=True, source_digest=file_digest(source), backup_metadata=True)
    with Image.open(source) as clean:
        assert decode_stealth(clean, channel=channel) is None
    blob = MetadataStore(tmp_path).get(source, result.digest)
    restored = tmp_path / "restored.png"
    restore_copy(image, restored, blob)
    with Image.open(restored) as output:
        assert decode_stealth(output, channel=channel) == expected
        pixel = output.getpixel((75, 70))
        assert max(pixel[:3]) <= 1


def test_repeated_save_and_undo_keep_backup_and_failures_keep_source(tmp_path, monkeypatch):
    source = source_with_metadata(tmp_path / "image.png", "PNG")
    before = source.read_bytes()
    original = load_image(source)
    digest = file_digest(source)
    first = save_image(original, source, source=source, overwrite_source=True, source_digest=digest, backup_metadata=True)
    payload = MetadataStore(tmp_path).get(source, first.digest)
    edited = original.copy()
    edited.paste("black", (10, 10, 50, 50))
    second = save_image(edited, source, source=source, overwrite_source=True, source_digest=first.digest, backup_metadata=True)
    assert MetadataStore(tmp_path).get(source, second.digest) == payload
    clean_before = source.read_bytes()
    import sumire.export as module
    monkeypatch.setattr(module.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("synthetic failure")))
    with pytest.raises(OSError):
        save_image(original, source, source=source, overwrite_source=True, source_digest=second.digest, backup_metadata=True)
    assert source.read_bytes() == clean_before
    assert MetadataStore(tmp_path).get(source, second.digest) == payload
    assert before != clean_before


def test_backup_failure_refuses_destructive_save(tmp_path, monkeypatch):
    source = source_with_metadata(tmp_path / "image.png", "PNG")
    original = source.read_bytes()
    monkeypatch.setattr(MetadataStore, "store", lambda *a, **k: (_ for _ in ()).throw(OSError("full")))
    with pytest.raises(OSError):
        save_image(load_image(source), source, source=source, overwrite_source=True, source_digest=file_digest(source), backup_metadata=True)
    assert source.read_bytes() == original
    assert not list(tmp_path.glob(".sumire-*.tmp"))


def test_separate_export_remap_migration_and_restart(tmp_path):
    source = source_with_metadata(tmp_path / "image.png", "PNG")
    output = tmp_path / "output" / "export.webp"
    before = source.read_bytes()
    result = save_image(load_image(source), output, source=source, format="WEBP", backup_metadata=True)
    assert source.read_bytes() == before
    payload = MetadataStore(output.parent).get(output, result.digest)
    assert payload == MetadataStore(source.parent).get(source, file_digest(source))
    assert unpack_backup(payload)[0] == "PNG"  # Restore in the original metadata container.
    new = output.with_name("renamed.webp")
    rename_images({output: new}, record_folders={output.parent})
    assert MetadataStore(new.parent).get(new, result.digest) == payload
    preferences = Preferences()
    assert migrate_records([source.parent, new.parent], "app", preferences) == 2
    assert MetadataStore(new.parent).get(new, result.digest) == payload
    restore_copy(load_image(new), new.with_name("restored.png"), payload, protected=[new])
    delete_records([new.parent])
    assert MetadataStore(new.parent).get(new, result.digest) is None


def test_stale_backup_not_used_for_replaced_image(tmp_path):
    source = source_with_metadata(tmp_path / "image.png", "PNG")
    result = save_image(load_image(source), source, source=source, overwrite_source=True, source_digest=file_digest(source), backup_metadata=True)
    assert MetadataStore(tmp_path).get(source, result.digest)
    Image.new("RGB", (80, 60), "blue").save(source)
    assert MetadataStore(tmp_path).get(source, file_digest(source)) is None


def test_restore_refuses_existing_or_source_and_handles_cancel(tmp_path):
    source = source_with_metadata(tmp_path / "image.png", "PNG")
    before = source.read_bytes()
    payload = capture_metadata(before)
    with pytest.raises(ImageProblem):
        restore_copy(load_image(source), source, payload, protected=[source])
    assert source.read_bytes() == before
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        restore_copy(load_image(source), tmp_path / "copy.png", payload, cancel=cancel)
    assert not (tmp_path / "copy.png").exists()


def test_corrupt_and_oversized_backup_rejected():
    for blob in (b"broken", zlib.compress(b"x" * (17 * 1024 * 1024)), zlib.compress(b"{}")):
        with pytest.raises(ImageProblem):
            unpack_backup(blob)


def test_orientation_and_colour_profile_are_normalized_for_edited_pixels(tmp_path):
    source = tmp_path / "oriented.png"
    image = Image.new("RGB", (60, 40), "green")
    exif = Image.Exif(); exif[274] = 6; exif[315] = "synthetic artist"
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    image.save(source, exif=exif, icc_profile=profile)
    pixels = load_image(source)
    payload = capture_metadata(source.read_bytes())
    assert pixels.size == (40, 60)
    with Image.open(io.BytesIO(restored_bytes(pixels, payload))) as restored:
        assert restored.getexif()[274] == 1
        assert restored.getexif()[315] == "synthetic artist"
        assert restored.info["icc_profile"]
        assert restored.convert("RGBA").tobytes() == pixels.tobytes()
    # The original orientation is still retained in the compressed backup.
    exif_bytes = next(value for kind, value in unpack_backup(payload)[1] if kind == b"eXIf")
    saved_exif = Image.Exif()
    saved_exif.load(exif_bytes)
    assert saved_exif[274] == 6


def test_foreign_database_and_changed_source_refuse_backup(tmp_path):
    import sqlite3
    source = source_with_metadata(tmp_path / "image.png", "PNG")
    before = source.read_bytes()
    with closing(sqlite3.connect(record_path(tmp_path))) as connection:
        connection.execute("CREATE TABLE other_app (value TEXT)")
    with pytest.raises(ImageProblem):
        save_image(load_image(source), source, source=source, overwrite_source=True,
                   source_digest=file_digest(source), backup_metadata=True)
    assert source.read_bytes() == before
    record_path(tmp_path).unlink()
    with pytest.raises(ImageProblem):
        save_image(load_image(source), tmp_path / "copy.png", source=source,
                   source_digest=b"x" * 32, backup_metadata=True)
    assert source.read_bytes() == before and not (tmp_path / "copy.png").exists()


def test_clean_input_creates_no_backup_and_jpeg_density_roundtrips(tmp_path):
    source = tmp_path / "clean.png"
    Image.new("RGB", (30, 40)).save(source)
    result = save_image(load_image(source), source, source=source, overwrite_source=True,
                        source_digest=file_digest(source), backup_metadata=True)
    assert MetadataStore(tmp_path).get(source, result.digest) is None
    jpeg = tmp_path / "density.jpg"
    Image.new("RGB", (30, 40)).save(jpeg, dpi=(300, 300))
    payload = capture_metadata(jpeg.read_bytes())
    with Image.open(io.BytesIO(restored_bytes(load_image(jpeg), payload))) as image:
        assert image.info["dpi"] == (300, 300)
