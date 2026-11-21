"""Images inside a ZIP: listing, reading, safety checks and exporting (the ZIP is never changed).

Every ZIP here is made by the test from generated images.
"""
import hashlib
import io
import os
import struct
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from sumire.archive import (MAX_ENTRY_BYTES, ArchiveEntry, export_entries, export_name, read_catalog, read_entry,
                            safe_member)
from sumire.imaging import ImageProblem, load_image, load_thumbnail
from sumire.labels import ReviewLabels


def png(color=(200, 60, 40), size=(40, 30)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def make_zip(path, members, compression=zipfile.ZIP_DEFLATED):
    with zipfile.ZipFile(path, "w", compression) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_lists_images_and_folders_without_decoding(tmp_path):
    archive = make_zip(tmp_path / "set.zip", {"b.png": png(), "a.jpg": b"not decoded when listing", "readme.txt": b"x",
                                               "sub/c.png": png((1, 2, 3)), "sub/deep/d.webp": b"", "other/": b""})
    catalog = read_catalog(archive)
    assert sorted(entry.member for entry in catalog.entries) == ["a.jpg", "b.png", "sub/c.png", "sub/deep/d.webp"]
    assert {entry.member for entry in catalog.entries_in("")} == {"a.jpg", "b.png"}
    assert catalog.subfolders("") == ["sub"] and catalog.subfolders("sub") == ["sub/deep"]  # rebuilt from the names
    entry = next(entry for entry in catalog.entries if entry.member == "sub/c.png")
    assert (entry.name, entry.stem, entry.suffix, entry.folder) == ("c.png", "c", ".png", "sub")
    assert not hasattr(entry, "__fspath__") and not isinstance(entry, Path)
    with pytest.raises(TypeError):
        open(entry, "rb")  # an entry can never be mistaken for a file
    assert "set.zip › sub/c.png" in str(entry)


def test_reads_entries_and_thumbnails_unchanged(tmp_path):
    data = png((10, 200, 30), (64, 48))
    archive = make_zip(tmp_path / "a.zip", {"x/y.png": data}, zipfile.ZIP_STORED)
    before = digest(archive)
    entry = read_catalog(archive).entries[0]
    assert read_entry(entry) == data
    image = load_image(entry)
    assert image.size == (64, 48) and image.getpixel((0, 0)) == (10, 200, 30, 255)
    thumbnail = load_thumbnail(entry, (32, 32))
    assert max(thumbnail.size) <= 32
    found = []
    load_image(entry, found)
    assert digest(archive) == before  # reading never writes


@pytest.mark.parametrize("name", ["/abs.png", "../up.png", "a/../b.png", "C:/x.png", "a//b.png", "./a.png", "a\x01.png"])
def test_unsafe_names_are_left_out(tmp_path, name):
    assert safe_member(name) is None
    archive = make_zip(tmp_path / "bad.zip", {"ok.png": png()})
    with zipfile.ZipFile(archive, "a") as handle:
        handle.writestr(zipfile.ZipInfo(name), png())
    catalog = read_catalog(archive)
    assert [entry.member for entry in catalog.entries] == ["ok.png"]
    assert catalog.skipped["name"] == 1 and "名前が不正" in catalog.skipped_text()


def test_backslashes_become_folders(tmp_path):
    assert safe_member("dir\\sub\\a.png") == "dir/sub/a.png"
    assert safe_member("..\\a.png") is None


@pytest.mark.filterwarnings("ignore:Duplicate name")
def test_duplicate_encrypted_and_link_entries_are_left_out(tmp_path):
    archive = tmp_path / "odd.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("same.png", png())
        handle.writestr("same.png", png((0, 0, 0)))  # a second entry of the same name
        link = zipfile.ZipInfo("link.png")
        link.create_system = 3
        link.external_attr = (0o120777 << 16)
        handle.writestr(link, "target.png")
        handle.writestr("fine.png", png())
    raw = bytearray(archive.read_bytes())
    # Mark fine.png as encrypted (general purpose flag bit 0) in its central directory record.
    position = raw.rfind(b"fine.png") - 46
    assert raw[position:position + 4] == b"PK\x01\x02"
    flags = struct.unpack_from("<H", raw, position + 8)[0]
    struct.pack_into("<H", raw, position + 8, flags | 1)
    archive.write_bytes(bytes(raw))
    catalog = read_catalog(archive)
    assert catalog.entries == []
    assert catalog.skipped == {"duplicate": 2, "special": 1, "encrypted": 1}


def test_zip_bomb_sizes_are_refused(tmp_path):
    archive = tmp_path / "bomb.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as handle:
        handle.writestr("big.bmp", b"\0" * (17 * 1024 * 1024))  # compresses far beyond the allowed ratio
        handle.writestr("ok.png", png())
    raw = bytearray(archive.read_bytes())
    # A declared size past the limit is refused before anything is decompressed.
    position = raw.rfind(b"ok.png") - 46
    struct.pack_into("<I", raw, position + 24, MAX_ENTRY_BYTES + 1)
    archive.write_bytes(bytes(raw))
    catalog = read_catalog(archive)
    assert catalog.entries == [] and catalog.skipped["size"] == 2


def test_too_many_entries_and_broken_zip_are_reported(tmp_path, monkeypatch):
    from sumire import archive as module
    many = make_zip(tmp_path / "many.zip", {f"{n}.png": b"" for n in range(5)})
    monkeypatch.setattr(module, "MAX_ENTRIES", 4)
    with pytest.raises(ImageProblem, match="多すぎ"):
        read_catalog(many)
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"PK\x03\x04 not really a zip")
    with pytest.raises(ImageProblem, match="ZIP形式"):
        read_catalog(broken)
    with pytest.raises(ImageProblem, match="見つかりません"):
        read_catalog(tmp_path / "missing.zip")


def test_a_changed_or_removed_zip_is_noticed(tmp_path):
    archive = make_zip(tmp_path / "a.zip", {"a.png": png(), "b.png": png((0, 0, 255))})
    entries = read_catalog(archive).entries
    make_zip(archive, {"a.png": png((9, 9, 9)), "b.png": png((0, 0, 255))})
    os.utime(archive, ns=(1, 1))
    with pytest.raises(ImageProblem, match="変更されました"):
        read_entry(entries[0])
    archive.unlink()
    with pytest.raises(ImageProblem, match="見つかりません"):
        load_image(entries[1])


def test_a_damaged_entry_fails_alone(tmp_path):
    archive = make_zip(tmp_path / "a.zip", {"good.png": png(), "bad.png": png((1, 1, 1))}, zipfile.ZIP_STORED)
    raw = bytearray(archive.read_bytes())
    start = raw.find(b"bad.png") + len(b"bad.png") + 20  # inside bad.png's data
    raw[start] ^= 0xFF
    stamp = archive.stat()
    archive.write_bytes(bytes(raw))
    os.utime(archive, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    catalog = read_catalog(archive)
    good, bad = sorted(catalog.entries, key=lambda entry: entry.member != "good.png")
    with pytest.raises(ImageProblem):
        load_image(bad)  # the CRC check catches it
    assert load_image(good).size == (40, 30)


def test_export_writes_only_the_chosen_entries_byte_for_byte(tmp_path):
    images = {"a.png": png(), "dir/b.png": png((1, 2, 3)), "dir/c.png": png((4, 5, 6))}
    archive = make_zip(tmp_path / "set.zip", images)
    before = digest(archive)
    entries = {entry.member: entry for entry in read_catalog(archive).entries}
    out = tmp_path / "out"
    out.mkdir()
    (out / "b.png").write_bytes(b"existing")  # never overwritten
    reported = []
    written = export_entries([entries["dir/b.png"], entries["a.png"]], out, progress=lambda done, total: reported.append((done, total)))
    assert written[entries["dir/b.png"]] == out / "b_2.png" and (out / "b.png").read_bytes() == b"existing"
    assert (out / "b_2.png").read_bytes() == images["dir/b.png"] and (out / "a.png").read_bytes() == images["a.png"]
    assert not (out / "c.png").exists() and reported == [(1, 2), (2, 2)]
    kept = tmp_path / "kept"
    export_entries([entries["dir/c.png"]], kept, keep_folders=True)
    assert (kept / "dir" / "c.png").read_bytes() == images["dir/c.png"]
    assert sorted(path.name for path in kept.rglob("*")) == ["c.png", "dir"]
    assert digest(archive) == before


def test_export_names_are_safe_on_windows():
    entry = ArchiveEntry(Path("/tmp/a.zip"), 'x:y/CON.png', 'x:y/CON.png', 1, 1, 0, (1980, 1, 1, 0, 0, 0), (0, 0))
    assert str(export_name(entry, True)) == "x_y/_CON.png"
    assert str(export_name(entry, False)) == "_CON.png"


def test_labels_for_zip_images_are_kept_apart(tmp_path):
    first = make_zip(tmp_path / "one.zip", {"a.png": png()})
    second = make_zip(tmp_path / "two.zip", {"a.png": png()})
    one, two = read_catalog(first).entries[0], read_catalog(second).entries[0]
    labels = ReviewLabels(tmp_path)
    labels.set_many({one: "accepted"})
    labels = ReviewLabels(tmp_path)
    assert labels.get(one) == "accepted" and labels.get(two) is None  # same name, another ZIP
    make_zip(first, {"a.png": png((0, 0, 0))})  # changed content: the label is not carried over
    assert ReviewLabels(tmp_path).get(read_catalog(first).entries[0]) is None
