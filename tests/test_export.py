import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin

from sumire.export import Cancelled, HiddenMetadata, available_target, file_digest, save_image, verify_export
from sumire.imaging import ImageProblem, load_image


@pytest.mark.parametrize("format,extension", [("PNG", "png"), ("JPEG", "jpg"), ("WEBP", "webp")])
def test_save_formats_original_size_and_source_unchanged(tmp_path, patterned, format, extension):
    source = tmp_path / "original.png"
    patterned.save(source)
    before = source.read_bytes()
    target = tmp_path / "output" / f"clean.{extension}"
    result = save_image(patterned, target, source=source, format=format)
    assert result.verification.size == patterned.size
    assert source.read_bytes() == before
    assert not list(target.parent.glob(".sumire-*.tmp"))
    with Image.open(target) as output:
        if format in {"PNG", "WEBP"}:
            assert output.convert("RGBA").tobytes() == patterned.tobytes()
        else:
            from PIL import ImageChops, ImageStat
            delta = ImageStat.Stat(ImageChops.difference(patterned.convert("RGB"), output.convert("RGB")))
            assert max(delta.mean) < 4


def test_all_png_metadata_removed_and_exiftool(tmp_path):
    source, target = tmp_path / "private.png", tmp_path / "clean.png"
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", "Stable Diffusion prompt")
    info.add_text("Software", "A1111", zip=True)
    info.add_itxt("Comment", '{"prompt": "NovelAI"}', zip=True)
    info.add_itxt("workflow", '{"nodes": "ComfyUI"}')
    info.add_text("XML:com.adobe.xmp", "<x:xmpmeta>private</x:xmpmeta>")
    exif = Image.Exif()
    exif[315] = "private artist"
    exif[34853] = {1: "N", 2: (35.0, 0.0, 0.0), 3: "E", 4: (139.0, 0.0, 0.0)}
    Image.new("RGBA", (30, 20), (150, 60, 40, 100)).save(source, pnginfo=info, exif=exif)
    result = save_image(load_image(source), target, source=source)
    assert set(result.verification.containers) == {"IHDR", "IDAT", "IEND"}
    with Image.open(target) as image:
        assert not image.info and not image.getexif()
    if shutil.which("exiftool"):
        raw = subprocess.run(["exiftool", "-j", "-G1", str(target)], capture_output=True, check=True)
        fields = json.loads(raw.stdout)[0]
        assert not any(key.startswith(("IFD", "GPS:", "ExifIFD:", "XMP", "IPTC:")) for key in fields)
        assert not any(text in raw.stdout for text in (b"Stable Diffusion", b"NovelAI", b"ComfyUI", b"private artist"))


@pytest.mark.parametrize("overwrite", [False, True])
@pytest.mark.parametrize("format,ext", [("PNG", "png"), ("WEBP", "webp"), ("JPEG", "jpg")])
def test_novelai_prompt_removed_from_pixels_and_file_metadata(tmp_path, patterned, encode_stealth, decode_stealth, overwrite, format, ext):
    image = encode_stealth(patterned)
    source = tmp_path / f"source.{ext if overwrite else 'png'}"
    exif = Image.Exif()
    exif[315] = "synthetic private artist"
    source_pixels = image.convert("RGB") if overwrite and format == "JPEG" else image
    source_pixels.save(source, exif=exif, lossless=True)
    before = source.read_bytes()
    assert decode_stealth(image) is not None
    target = source if overwrite else tmp_path / f"clean.{ext}"
    # Pass raw pixels directly to exercise the export guard as well as loading.
    save_image(image, target, source=source, format=format,
               overwrite_source=overwrite, source_digest=file_digest(source) if overwrite else None)
    with Image.open(target) as cleaned:
        assert not cleaned.getexif()
        assert decode_stealth(cleaned) is None
        assert decode_stealth(cleaned, "rgb") is None
        assert cleaned.convert("RGBA").getchannel("A").getextrema() == (255, 255)
        if format in {"PNG", "WEBP"}:
            assert cleaned.convert("RGB").tobytes() == patterned.convert("RGB").tobytes()
    verify_export(target, patterned.size, format)
    if not overwrite:
        assert source.read_bytes() == before


@pytest.mark.parametrize("format,ext", [("PNG", "png"), ("WEBP", "webp")])
def test_verifier_rejects_stealth_even_when_file_metadata_is_empty(tmp_path, patterned, encode_stealth, format, ext):
    target = tmp_path / f"hidden.{ext}"
    encode_stealth(patterned).save(target, lossless=True)
    with pytest.raises(HiddenMetadata, match="隠しメタデータ"):
        verify_export(target, patterned.size, format)


def test_stealth_verification_failure_preserves_source(tmp_path, patterned, encode_stealth, monkeypatch):
    import sumire.export as module
    source = tmp_path / "source.png"
    image = encode_stealth(patterned)
    image.save(source)
    before = source.read_bytes()
    monkeypatch.setattr(module, "remove_stealth", lambda image: image)
    with pytest.raises(HiddenMetadata):
        save_image(image, source, source=source, overwrite_source=True, source_digest=file_digest(source))
    assert source.read_bytes() == before
    assert not list(tmp_path.glob(".sumire-*.tmp"))


@pytest.mark.parametrize("format,ext", [("JPEG", "jpg"), ("WEBP", "webp")])
def test_exif_gps_xmp_comments_removed(tmp_path, format, ext):
    source, target = tmp_path / f"private.{ext}", tmp_path / f"clean.{ext}"
    exif = Image.Exif()
    exif[315] = "private artist"
    exif[34853] = {1: "N", 2: (35.0, 0.0, 0.0)}
    Image.new("RGB", (30, 20), "red").save(source, format=format, exif=exif, xmp=b"<x:xmpmeta>private</x:xmpmeta>")
    if format == "JPEG":
        data = source.read_bytes()
        payload = b"private comment"
        comment = b"\xff\xfe" + (len(payload) + 2).to_bytes(2, "big") + payload
        iptc = b"Photoshop 3.0\x00private IPTC"
        app13 = b"\xff\xed" + (len(iptc) + 2).to_bytes(2, "big") + iptc
        source.write_bytes(data[:2] + comment + app13 + data[2:])
    save_image(load_image(source), target, source=source, format=format)
    assert b"private" not in target.read_bytes()
    verify_export(target, (30, 20), format)


def test_export_rebuilds_pixels_even_if_input_has_metadata(tmp_path):
    image = Image.new("RGBA", (30, 20))
    image.info["exif"] = b"private"
    image.info["icc_profile"] = b"private"
    image.info["parameters"] = "private"
    save_image(image, tmp_path / "out.png", source=tmp_path / "source.png")
    assert b"private" not in (tmp_path / "out.png").read_bytes()


def test_jpeg_alpha_uses_explicit_white_background(tmp_path):
    image = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    target = tmp_path / "out.jpg"
    save_image(image, target, source=tmp_path / "original.png", format="JPEG")
    with Image.open(target) as output:
        assert output.getpixel((0, 0)) == (255, 255, 255)


@pytest.mark.parametrize("format,extension", [("PNG", "png"), ("WEBP", "webp")])
def test_lossless_alpha_and_hidden_rgb_preserved_outside_edits(tmp_path, format, extension):
    image = Image.new("RGBA", (40, 30))
    image.putdata([(x * 6, y * 8, 120, [0, 64, 128, 255][x % 4]) for y in range(30) for x in range(40)])
    path = tmp_path / f"alpha.{extension}"
    save_image(image, path, source=tmp_path / "original.png", format=format)
    with Image.open(path) as output:
        assert output.convert("RGBA").tobytes() == image.tobytes()


def test_source_and_existing_files_protected(tmp_path, patterned):
    source = tmp_path / "original.png"
    patterned.save(source)
    original = source.read_bytes()
    with pytest.raises(ImageProblem, match="元画像"):
        save_image(patterned, source, source=source)
    target = tmp_path / "other.png"
    target.write_bytes(b"other person file")
    with pytest.raises(ImageProblem, match="同名"):
        save_image(patterned, target, source=source)
    assert source.read_bytes() == original
    assert target.read_bytes() == b"other person file"


def test_own_output_replaced_and_external_changes_protected(tmp_path, patterned):
    target, source = tmp_path / "out.png", tmp_path / "source.png"
    first = save_image(patterned, target, source=source)
    second = save_image(Image.new("RGBA", patterned.size, "white"), target, source=source, owned_digest=first.digest)
    assert second.digest != first.digest
    target.write_bytes(b"external change")
    with pytest.raises(ImageProblem):
        save_image(patterned, target, source=source, owned_digest=second.digest)
    assert target.read_bytes() == b"external change"


def test_verification_failure_leaves_no_partial_or_replaces_existing(tmp_path, patterned, monkeypatch):
    import sumire.export as export
    target = tmp_path / "out.png"
    source = tmp_path / "original.png"
    first = save_image(patterned, target, source=source)
    before = target.read_bytes()
    def reject(*_args, **_kwargs):
        raise ImageProblem("synthetic verification failure")
    monkeypatch.setattr(export, "verify_export", reject)
    with pytest.raises(ImageProblem):
        save_image(patterned, target, source=source, owned_digest=first.digest)
    assert target.read_bytes() == before
    assert not list(tmp_path.glob(".sumire-*.tmp"))


def test_disk_failure_cleans_temporary(tmp_path, patterned, monkeypatch):
    def fail(*_args, **_kwargs):
        raise OSError("no space")
    monkeypatch.setattr(Image.Image, "save", fail)
    target = tmp_path / "out.png"
    with pytest.raises(OSError):
        save_image(patterned, target, source=tmp_path / "source.png")
    assert not target.exists()
    assert not list(tmp_path.glob(".sumire-*.tmp"))


@pytest.mark.parametrize("phase", ["before", "after-encode"])
def test_cancel_creates_no_output(tmp_path, patterned, monkeypatch, phase):
    event = threading.Event()
    if phase == "before":
        event.set()
    else:
        original = Image.Image.save
        def save_then_cancel(self, *args, **kwargs):
            original(self, *args, **kwargs)
            event.set()
        monkeypatch.setattr(Image.Image, "save", save_then_cancel)
    with pytest.raises(Cancelled):
        save_image(patterned, tmp_path / "out.png", source=tmp_path / "source.png", cancel=event)
    assert not (tmp_path / "out.png").exists()
    assert not list(tmp_path.glob(".sumire-*.tmp"))


def test_name_collision_and_windows_invalid_names(tmp_path):
    (tmp_path / "image.png").touch()
    assert available_target(tmp_path, "image", "PNG").name == "image_2.png"
    for name in ["../escape", "a/b", "a\\b", "CON", "COM1", "a:", "name.", "", "bad\x00name"]:
        with pytest.raises(ImageProblem):
            available_target(tmp_path, name, "PNG")


def test_validator_rejects_injected_png_text(tmp_path):
    path = tmp_path / "not-clean.png"
    info = PngImagePlugin.PngInfo()
    info.add_text("secret", "private")
    Image.new("RGBA", (30, 20)).save(path, pnginfo=info)
    with pytest.raises(ImageProblem):
        verify_export(path, (30, 20), "PNG")


@pytest.mark.parametrize("position", ["before-eoi", "after-eoi"])
def test_validator_rejects_trailing_jpeg_metadata(tmp_path, position):
    path = tmp_path / "injected.jpg"
    Image.new("RGB", (30, 20), "red").save(path)
    data = path.read_bytes()
    comment = b"\xff\xfe\x00\x09private"
    path.write_bytes(data[:-2] + comment + data[-2:] if position == "before-eoi" else data + comment)
    with pytest.raises(ImageProblem):
        verify_export(path, (30, 20), "JPEG")


def test_source_hardlink_is_protected(tmp_path, patterned):
    import os
    source, alias = tmp_path / "original.png", tmp_path / "alias.png"
    patterned.save(source)
    os.link(source, alias)
    with pytest.raises(ImageProblem, match="元画像"):
        save_image(patterned, alias, source=source)


@pytest.mark.parametrize("format,ext", [("PNG", "png"), ("JPEG", "jpg"), ("WEBP", "webp")])
def test_explicit_source_overwrite_keeps_format_and_strips_metadata(tmp_path, format, ext):
    source = tmp_path / f"image.{ext}"
    exif = Image.Exif()
    exif[315] = "private artist"
    Image.new("RGB", (40, 30), "red").save(source, format=format, exif=exif)
    original = file_digest(source)
    result = save_image(Image.new("RGBA", (40, 30), "black"), source, source=source, format=format,
                        overwrite_source=True, source_digest=original)
    assert result.path == source
    assert result.digest != original
    verify_export(source, (40, 30), format)
    with Image.open(source) as image:
        assert image.format == format
        assert image.convert("RGB").getpixel((20, 20)) == (0, 0, 0)
        assert not image.getexif()
    assert not list(tmp_path.glob(".sumire-*.tmp"))


def test_source_overwrite_requires_loaded_digest_and_rejects_stale_file(tmp_path, patterned):
    source = tmp_path / "image.png"
    patterned.save(source)
    before = source.read_bytes()
    digest = file_digest(source)
    with pytest.raises(ImageProblem):
        save_image(patterned, source, source=source, overwrite_source=True)
    assert source.read_bytes() == before
    Image.new("RGB", patterned.size, "green").save(source)
    external = source.read_bytes()
    with pytest.raises(ImageProblem, match="元画像が変更"):
        save_image(patterned, source, source=source, overwrite_source=True, source_digest=digest)
    assert source.read_bytes() == external


@pytest.mark.parametrize("failure", ["verify", "cancel", "replace", "external", "deleted"])
def test_failed_source_overwrite_never_commits_partial_file(tmp_path, patterned, monkeypatch, failure):
    import sumire.export as export
    source = tmp_path / "image.png"
    patterned.save(source)
    original = source.read_bytes()
    digest = file_digest(source)
    cancel = threading.Event()
    verify = export.verify_export
    def checked(*args, **kwargs):
        result = verify(*args, **kwargs)
        if failure == "verify":
            raise ImageProblem("verification failure")
        if failure == "cancel":
            cancel.set()
        if failure == "external":
            source.write_bytes(b"external change")
        if failure == "deleted":
            source.unlink()
        return result
    monkeypatch.setattr(export, "verify_export", checked)
    if failure == "replace":
        def reject(*_args):
            raise PermissionError("read only")
        monkeypatch.setattr(export.os, "replace", reject)
    with pytest.raises((ImageProblem, Cancelled, PermissionError)):
        save_image(Image.new("RGBA", patterned.size, "black"), source, source=source,
                   overwrite_source=True, source_digest=digest, cancel=cancel)
    if failure == "deleted":
        assert not source.exists()
    else:
        assert source.read_bytes() == (b"external change" if failure == "external" else original)
    assert not list(tmp_path.glob(".sumire-*.tmp"))


def test_source_overwrite_cannot_change_format_or_target_alias(tmp_path, patterned):
    import os
    source, alias = tmp_path / "source.jpg", tmp_path / "alias.jpg"
    patterned.convert("RGB").save(source)
    before = source.read_bytes()
    digest = file_digest(source)
    with pytest.raises(ImageProblem, match="形式"):
        save_image(patterned, source, source=source, overwrite_source=True, source_digest=digest)
    os.link(source, alias)
    with pytest.raises(ImageProblem, match="元画像"):
        save_image(patterned, alias, source=source, format="JPEG", overwrite_source=True, source_digest=digest)
    assert source.read_bytes() == alias.read_bytes() == before
