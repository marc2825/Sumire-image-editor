from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import zipfile

import pytest
from PIL import Image, PngImagePlugin

from sumire.export import Cancelled, file_digest, save_image
from sumire.imaging import Document, ImageProblem, Stroke, Tool, make_effect
from sumire.labels import ReviewLabels
from sumire.masks import MaskStore
from sumire.metadata import MetadataStore, capture_metadata, unpack_backup
from sumire.organize import pending_renames, recover_rename, rename_images
from sumire.preferences import Preferences
from sumire.projects import read_project, write_project
from sumire.session import Receipts
from sumire.storage import APPLICATION_ID, connect_owned, delete_records, migrate_records, record_path


def saved_fixture(folder):
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / "画像.png"
    image = Image.new("RGBA", (24, 20), "red")
    result = save_image(image, source, source=folder / "absent.png", format="PNG")
    Receipts(folder).record(source, result, edited=True)
    ReviewLabels(folder).set(source, "accepted")
    ReviewLabels(folder).set_note(source, "確認済み")
    mask = Image.new("L", image.size)
    mask.paste(255, (3, 4, 12, 17))
    MaskStore(folder).store(source, result.digest, mask)
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", "synthetic saved prompt")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", pnginfo=info)
    MetadataStore(folder).store(source, result.digest, capture_metadata(buffer.getvalue()))
    return source, result, mask


def test_mask_reopen_and_external_modification_rejection(tmp_path):
    source, result, mask = saved_fixture(tmp_path)
    assert MaskStore(tmp_path).get(source, result.digest, mask.size).tobytes() == mask.tobytes()
    assert MaskStore(tmp_path).get(source, b"x" * 32, mask.size) is None
    assert MaskStore(tmp_path).get(source, result.digest, (10, 10)) is None
    assert b"IHDR" in record_path(tmp_path).read_bytes()  # Only the small binary PNG mask.


@pytest.mark.parametrize("initial", ["folder", "app"])
def test_storage_roundtrip_preserves_all_records_and_source_bytes(tmp_path, initial):
    preferences = Preferences()
    if initial == "app":
        preferences.save({"storage": "app"})
    folder = tmp_path / "images"
    source, result, mask = saved_fixture(folder)
    original = source.read_bytes()
    target_mode = "app" if initial == "folder" else "folder"
    assert migrate_records([folder], target_mode, preferences) == 1
    assert not record_path(folder, initial).exists()
    assert Receipts(folder).get(source)["edited"] is True
    assert ReviewLabels(folder).get(source) == "accepted"
    assert ReviewLabels(folder).note(source) == "確認済み"
    assert MaskStore(folder).get(source, result.digest, mask.size).tobytes() == mask.tobytes()
    assert source.read_bytes() == original
    assert migrate_records([folder], initial, preferences) == 1
    assert source.read_bytes() == original


def test_storage_does_not_mix_folders_with_same_name(tmp_path):
    one, two = [tmp_path / parent / "images" for parent in ("one", "two")]
    first, *_ = saved_fixture(one)
    second, *_ = saved_fixture(two)
    ReviewLabels(two).set(second, "rejected")
    migrate_records([one, two], "app", Preferences())
    assert record_path(one) != record_path(two)
    assert ReviewLabels(one).get(first) == "accepted"
    assert ReviewLabels(two).get(second) == "rejected"


def test_storage_migration_rolls_back_if_settings_write_fails(tmp_path, monkeypatch):
    folder = tmp_path / "images"
    source, *_ = saved_fixture(folder)
    destination = record_path(folder, "app")
    with closing(connect_owned(destination)) as connection:
        with connection:
            connection.execute("CREATE TABLE keep(value TEXT)")
            connection.execute("INSERT INTO keep VALUES ('previous')")
    original, previous = source.read_bytes(), destination.read_bytes()
    preferences = Preferences()
    monkeypatch.setattr(preferences, "save", lambda data: (_ for _ in ()).throw(OSError("full")))
    with pytest.raises(OSError):
        migrate_records([folder], "app", preferences)
    assert record_path(folder, "folder").is_file()
    assert destination.read_bytes() == previous
    assert source.read_bytes() == original
    assert not list(destination.parent.glob(".sumire-migrate-*"))
    assert not list(destination.parent.glob(".sumire-previous-*"))


def test_storage_rejects_foreign_destination(tmp_path):
    folder = tmp_path / "images"
    saved_fixture(folder)
    target = record_path(folder, "app")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"unrelated")
    with pytest.raises((OSError, sqlite3.Error)):
        migrate_records([folder], "app", Preferences())
    assert target.read_bytes() == b"unrelated"
    assert record_path(folder, "folder").exists()


def test_delete_records_keeps_photos_and_projects(tmp_path):
    source, *_ = saved_fixture(tmp_path)
    original = source.read_bytes()
    project = tmp_path / "keep.sumire"
    project.write_bytes(b"keep project")
    assert delete_records([tmp_path]) == 1
    assert source.read_bytes() == original and project.read_bytes() == b"keep project"
    assert ReviewLabels(tmp_path).get(source) is None
    assert Receipts(tmp_path).get(source) is None


def test_project_roundtrip_restores_eraser_without_original_file(tmp_path, patterned):
    source = tmp_path / "original.png"
    patterned.save(source)
    document = Document(source, patterned)
    stroke = Stroke(document, Tool(mode="fill"), make_effect(document.image, Tool(mode="fill")))
    stroke.add((50, 50))
    stroke.finish()
    path = tmp_path / "編集.sumire"
    state = {"edited": True, "original_edited": False, "original_known": True}
    write_project(path, document.original, document.image, document.edit_mask, state)
    source.unlink()
    restored = read_project(path)
    assert restored.image.tobytes() == document.image.tobytes()
    assert restored.edit_mask.tobytes() == document.edit_mask.tobytes()
    assert restored.original.tobytes() == patterned.tobytes()
    tool = Tool(mode="erase", diameter=600)
    eraser = Stroke(restored, tool, None)
    eraser.add((80, 60))
    eraser.finish()
    assert restored.image.tobytes() == patterned.tobytes()
    assert restored.edit_mask.getbbox() is None
    assert not restored.edited
    assert restored.undo()
    assert restored.image.tobytes() == document.image.tobytes()


def test_project_removes_metadata_and_stealth(tmp_path, patterned, encode_stealth, decode_stealth):
    image = encode_stealth(patterned)
    image.info["Description"] = "PRIVATE"
    path = tmp_path / "image.sumire"
    state = {"edited": False, "original_edited": False, "original_known": True}
    write_project(path, image, image, Image.new("L", image.size), state)
    with zipfile.ZipFile(path) as archive:
        for name in ("original.png", "image.png"):
            with Image.open(io.BytesIO(archive.read(name))) as output:
                assert not output.info and decode_stealth(output) is None


def test_project_cancel_and_existing_file_protection(tmp_path, patterned):
    path = tmp_path / "existing.sumire"
    path.write_bytes(b"keep")
    state = {"edited": False, "original_edited": False, "original_known": True}
    with pytest.raises(ImageProblem):
        write_project(path, patterned, patterned, Image.new("L", patterned.size), state)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        write_project(path, patterned, patterned, Image.new("L", patterned.size), state, cancel=cancel, expected_digest=file_digest(path))
    assert path.read_bytes() == b"keep"
    assert not list(tmp_path.glob(".sumire-project-*"))


@pytest.mark.parametrize("kind", ["extra_member", "oversize", "bad_json"])
def test_project_rejects_invalid_archives(tmp_path, kind):
    path = tmp_path / "bad.sumire"
    stream = io.BytesIO()
    Image.new("RGBA", (5, 5)).save(stream, format="PNG")
    mask = io.BytesIO()
    Image.new("L", (5, 5)).save(mask, format="PNG")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("original.png", stream.getvalue())
        archive.writestr("image.png", stream.getvalue())
        archive.writestr("mask.png", mask.getvalue())
        archive.writestr("project.json", b"bad" if kind == "bad_json" else " " * 5000 if kind == "oversize" else json.dumps({"version": 1, "edited": False, "original_edited": False, "original_known": True}))
        if kind == "extra_member":
            archive.writestr("../file", "no extraction")
    with pytest.raises(ImageProblem):
        read_project(path)


def test_integrated_rename_preserves_receipts_labels_notes_masks(tmp_path):
    source, result, mask = saved_fixture(tmp_path)
    target = tmp_path / "renamed.png"
    rename_images({source: target}, record_folders={tmp_path})
    assert not source.exists()
    assert Receipts(tmp_path).get(target)["edited"] is True
    assert ReviewLabels(tmp_path).get(target) == "accepted"
    assert ReviewLabels(tmp_path).note(target) == "確認済み"
    assert ReviewLabels(tmp_path).get(source) is None
    assert MaskStore(tmp_path).get(target, result.digest, mask.size).tobytes() == mask.tobytes()
    assert unpack_backup(MetadataStore(tmp_path).get(target, result.digest))[1] == [(b"tEXt", b"parameters\0synthetic saved prompt")]
    assert not pending_renames(tmp_path)


CRASH_METADATA = r'''
import os, sys
from pathlib import Path
import sumire.organize as module
folder = Path(sys.argv[1])
phase = sys.argv[2]
paths = [folder / name / '画像.png' for name in ('a', 'b')]
mapping = {path: path.with_name('renamed.png') for path in paths}
original = module.apply_records
def crash_apply(refs, token):
    if phase == 'before':
        os._exit(33)
    original(refs[:1], token)
    if phase == 'partial':
        os._exit(33)
    original(refs[1:], token)
    os._exit(33)
module.apply_records = crash_apply
module.rename_images(mapping, record_folders={p.parent for p in paths})
'''


@pytest.mark.parametrize("phase", ["before", "partial", "after"])
@pytest.mark.parametrize("storage", ["folder", "app"])
def test_killed_metadata_update_rolls_forward_idempotently(tmp_path, phase, storage):
    Preferences().save({"storage": storage})
    fixtures = [saved_fixture(tmp_path / name) for name in ("a", "b")]
    originals = {source: source.read_bytes() for source, _, _ in fixtures}
    result = subprocess.run([sys.executable, "-c", CRASH_METADATA, str(tmp_path), phase], capture_output=True, timeout=15)
    assert result.returncode == 33, result.stderr.decode()
    assert pending_renames(tmp_path / "a") and pending_renames(tmp_path / "b")
    # Recover from the second folder to cover duplicate recovery records.
    recover_rename(pending_renames(tmp_path / "b")[0])
    for source, result, mask in fixtures:
        target = source.with_name("renamed.png")
        assert target.read_bytes() == originals[source] and not source.exists()
        assert Receipts(target.parent).get(target)["edited"] is True
        assert ReviewLabels(target.parent).get(target) == "accepted"
        assert ReviewLabels(target.parent).note(target) == "確認済み"
        assert MaskStore(target.parent).get(target, result.digest, mask.size).tobytes() == mask.tobytes()
        assert unpack_backup(MetadataStore(target.parent).get(target, result.digest))[1] == [(b"tEXt", b"parameters\0synthetic saved prompt")]
        assert not pending_renames(target.parent)
        assert not list(target.parent.glob(".sumire-rename-*"))
