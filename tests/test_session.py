import sqlite3
import os
from pathlib import Path

import pytest
from PIL import Image

from sumire.export import file_digest, save_image
from sumire.library import scan_paths
from sumire.session import APPLICATION_ID, Receipts, source_key
from sumire.organize import rename_images


def test_receipt_reopens_and_source_change_invalidates(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGBA", (20, 20), "red").save(source)
    folder = tmp_path / "Sumīre"
    receipts = Receipts(folder)
    result = save_image(Image.new("RGBA", (20, 20), "black"), folder / "source.png", source=source)
    receipts.record(source, result)
    reopened = Receipts(folder)
    assert reopened.get(source)["digest"] == result.digest.hex()
    raw = receipts.path.read_bytes()
    assert str(source.parent).encode() not in raw
    assert b"exif" not in raw
    Image.new("RGBA", (20, 20), "green").save(source)
    assert reopened.get(source) is None


def test_untrusted_receipt_paths_and_corrupt_database_ignored(tmp_path):
    folder = tmp_path / "Sumīre"
    folder.mkdir()
    path = folder / ".sumire-index.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
        connection.execute("CREATE TABLE receipts (source TEXT PRIMARY KEY, name TEXT, format TEXT, digest TEXT)")
        connection.execute("INSERT INTO receipts VALUES (?, ?, ?, ?)", ("key", "../outside.png", "PNG", "0" * 64))
    assert not Receipts(folder).records
    path.write_bytes(b"broken index")
    assert not Receipts(folder).records


def test_folder_scan_is_flat_deduplicated_and_naturally_sorted(tmp_path):
    for name in ["10.png", "1.png", "2.png", "note.txt"]:
        (tmp_path / name).touch()
    output = tmp_path / "Sumīre"
    output.mkdir()
    (output / "1.png").touch()
    assert [p.name for p in scan_paths([str(tmp_path), str(tmp_path / "1.png")])] == ["1.png", "2.png", "10.png"]


def test_overwrite_receipts_follow_new_fingerprint_without_accumulating(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGBA", (20, 20), "white").save(source)
    receipts = Receipts(tmp_path)
    for color in ("red", "green", "black"):
        previous_key = source_key(source)
        result = save_image(Image.new("RGBA", (20, 20), color), source, source=source,
                            overwrite_source=True, source_digest=file_digest(source))
        receipts.record(source, result, previous_key=previous_key)
        assert len(receipts.records) == 1
        assert receipts.get(source, overwrite=True)["digest"] == result.digest.hex()
        assert receipts.get(source, overwrite=False) is None
        receipts = Receipts(tmp_path)
        assert len(receipts.records) == 1


@pytest.mark.parametrize("overwrite", [False, True])
def test_receipts_follow_swapped_source_paths(tmp_path, overwrite):
    sources = [tmp_path / "0.png", tmp_path / "1.png"]
    folder = tmp_path if overwrite else tmp_path / "Sumīre"
    receipts = Receipts(folder)
    digests = {}
    for source, color in zip(sources, ("red", "blue")):
        image = Image.new("RGBA", (20, 20), color)
        image.save(source)
        result = save_image(image, folder / source.name, source=source,
                            overwrite_source=overwrite, source_digest=file_digest(source) if overwrite else None)
        os.utime(source, ns=(1000000000, 1000000000))
        receipts.record(source, result)
        digests[source] = result.digest.hex()
    mapping = {sources[0]: sources[1], sources[1]: sources[0]}
    keys = {path: source_key(path) for path in sources}
    rename_images(mapping)
    receipts.remap_sources(mapping, keys)
    reopened = Receipts(folder)
    assert len(reopened.records) == 2
    for old, new in mapping.items():
        record = reopened.get(new, overwrite=overwrite)
        assert record["digest"] == digests[old]
        assert record["name"] == (new.name if overwrite else old.name)


@pytest.mark.parametrize("edited", [True, False, None])
def test_receipt_keeps_edit_state_through_reopen_resave_and_rename(tmp_path, edited):
    source = tmp_path / "source.png"
    image = Image.new("RGBA", (20, 20), "red")
    image.save(source)
    index = Receipts(tmp_path)
    result = save_image(image, source, source=source, overwrite_source=True, source_digest=file_digest(source))
    index.record(source, result, edited=edited)
    reopened = Receipts(tmp_path)
    assert reopened.get(source)["edited"] is edited
    previous_key = source_key(source)
    result = save_image(image, source, source=source, overwrite_source=True, source_digest=file_digest(source))
    reopened.record(source, result, previous_key=previous_key, edited=edited)
    keys = {source: source_key(source)}
    target = source.with_name("renamed.png")
    rename_images({source: target})
    reopened.remap_sources({source: target}, keys)
    assert Receipts(tmp_path).get(target)["edited"] is edited


def test_legacy_receipt_migration_preserves_unknown_edit_state_and_existing_rows(tmp_path):
    source = tmp_path / "old.png"
    Image.new("RGBA", (20, 20), "red").save(source)
    path = tmp_path / ".sumire-index.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
        connection.execute("CREATE TABLE receipts (source TEXT PRIMARY KEY, name TEXT, format TEXT, digest TEXT)")
        connection.execute("INSERT INTO receipts VALUES (?, ?, ?, ?)", (source_key(source), source.name, "PNG", file_digest(source).hex()))
    index = Receipts(tmp_path)
    assert index.get(source)["edited"] is None
    new = tmp_path / "new.png"
    Image.new("RGBA", (20, 20), "blue").save(new)
    result = save_image(Image.new("RGBA", (20, 20), "black"), new, source=new, overwrite_source=True, source_digest=file_digest(new))
    index.record(new, result, edited=True)
    reopened = Receipts(tmp_path)
    assert reopened.get(source)["edited"] is None
    assert reopened.get(new)["edited"] is True
