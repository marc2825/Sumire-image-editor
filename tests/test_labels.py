import sqlite3

import pytest
from PIL import Image

from sumire.export import file_digest, save_image
from sumire.labels import REVIEW_LABELS, ReviewLabels
from sumire.organize import rename_images
from sumire.session import Receipts


@pytest.mark.parametrize("label", REVIEW_LABELS)
def test_labels_persist_without_changing_image_and_can_be_cleared(tmp_path, label):
    source = tmp_path / "日本語.png"
    Image.new("RGB", (20, 20), "red").save(source)
    before = source.read_bytes()
    index = ReviewLabels(tmp_path)
    index.set(source, label)
    assert ReviewLabels(tmp_path).get(source) == label
    assert source.read_bytes() == before
    assert str(source).encode() not in index.path.read_bytes()
    index.set(source, None)
    assert ReviewLabels(tmp_path).get(source) is None


@pytest.mark.parametrize("label_first", [True, False])
def test_labels_and_receipts_share_database_and_survive_overwrite(tmp_path, label_first):
    source = tmp_path / "image.png"
    Image.new("RGBA", (20, 20), "red").save(source)
    labels, receipts = ReviewLabels(tmp_path), Receipts(tmp_path)
    if label_first:
        labels.set(source, "accepted")
    result = save_image(Image.new("RGBA", (20, 20), "blue"), source, source=source,
                        overwrite_source=True, source_digest=file_digest(source))
    receipts.record(source, result)
    if not label_first:
        labels.set(source, "accepted")
    assert ReviewLabels(tmp_path).get(source) == "accepted"
    assert Receipts(tmp_path).get(source)["digest"] == result.digest.hex()


@pytest.mark.parametrize("second_label", [None, "rejected"])
def test_labels_follow_cyclic_rename_including_unlabelled_image(tmp_path, second_label):
    first, second = tmp_path / "0.png", tmp_path / "1.png"
    Image.new("RGB", (10, 10), "red").save(first)
    Image.new("RGB", (10, 10), "blue").save(second)
    labels = ReviewLabels(tmp_path)
    labels.set(first, "pending")
    if second_label:
        labels.set(second, second_label)
    mapping = {first: second, second: first}
    rename_images(mapping)
    labels.remap_paths(mapping)
    reopened = ReviewLabels(tmp_path)
    assert reopened.get(second) == "pending"
    assert reopened.get(first) == second_label


@pytest.mark.parametrize("database", ["corrupt", "foreign", "symlink"])
def test_unwritable_or_foreign_database_does_not_claim_label_saved(tmp_path, database):
    index = ReviewLabels(tmp_path)
    if database == "corrupt":
        index.path.write_bytes(b"invalid sqlite")
    elif database == "foreign":
        with sqlite3.connect(index.path) as connection:
            connection.execute("CREATE TABLE other (data TEXT)")
    else:
        target = tmp_path / "other.sqlite3"
        target.write_bytes(b"keep this file")
        try:
            index.path.symlink_to(target)
        except OSError as error:
            if getattr(error, "winerror", None) == 1314:
                pytest.skip("Windows symlink creation requires Developer Mode or administrator privileges")
            raise
    before = index.path.read_bytes()
    with pytest.raises(OSError):
        index.set(tmp_path / "image.png", "accepted")
    assert index.get(tmp_path / "image.png") is None
    assert not ReviewLabels(tmp_path).labels
    assert index.path.read_bytes() == before


def test_same_named_images_in_different_folders_have_independent_labels(tmp_path):
    folders = [tmp_path / "first", tmp_path / "second"]
    for folder, label in zip(folders, ("accepted", "rejected")):
        folder.mkdir()
        ReviewLabels(folder).set(folder / "image.png", label)
    assert ReviewLabels(folders[0]).get(folders[0] / "image.png") == "accepted"
    assert ReviewLabels(folders[1]).get(folders[1] / "image.png") == "rejected"
