import threading

import pytest

from sumire.export import Cancelled
from sumire.imaging import ImageProblem
from sumire.organize import rename_images, renamed_path


@pytest.mark.parametrize("stem", ["", ".", "..", "../outside", "a/b", "a\\b", "CON", "COM1", "bad:", "bad.", "bad ", "bad\x00"])
def test_invalid_rename_is_rejected(tmp_path, stem):
    with pytest.raises(ImageProblem):
        renamed_path(tmp_path / "source.png", stem)


def test_name_keeps_directory_and_extension(tmp_path):
    source = tmp_path / "photo.JPEG"
    assert renamed_path(source, "日本語 123") == tmp_path / "日本語 123.JPEG"


def test_renaming_cycle_preserves_bytes(tmp_path):
    paths = [tmp_path / f"{number}.png" for number in range(3)]
    for number, path in enumerate(paths):
        path.write_bytes(bytes([number]) * 100)
    mapping = dict(zip(paths, paths[1:] + paths[:1]))
    before = {path: path.read_bytes() for path in paths}
    progress = []
    rename_images(mapping, progress=lambda done, total: progress.append((done, total)))
    for old, new in mapping.items():
        assert new.read_bytes() == before[old]
    assert progress == [(1, 3), (2, 3), (3, 3)]
    assert not list(tmp_path.glob(".sumire-rename-*"))


def test_existing_unrelated_file_is_never_overwritten(tmp_path):
    source, target = tmp_path / "old.png", tmp_path / "0.png"
    source.write_bytes(b"original")
    target.write_bytes(b"unrelated")
    with pytest.raises(ImageProblem):
        rename_images({source: target})
    assert source.read_bytes() == b"original"
    assert target.read_bytes() == b"unrelated"
    assert not list(tmp_path.glob(".sumire-rename-*"))


@pytest.mark.parametrize("fail_at", [2, 4, 5])
def test_link_failure_rolls_back_all_files(tmp_path, monkeypatch, fail_at):
    import sumire.organize as module
    paths = [tmp_path / f"{number}.png" for number in range(3)]
    for number, path in enumerate(paths):
        path.write_bytes(bytes([number]) * 100)
    before = {path: path.read_bytes() for path in paths}
    link = module.os.link
    calls = 0
    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise OSError("synthetic failure")
        return link(*args, **kwargs)
    monkeypatch.setattr(module.os, "link", fail_once)
    with pytest.raises(OSError):
        rename_images(dict(zip(paths, paths[1:] + paths[:1])))
    assert {path: path.read_bytes() for path in paths} == before
    assert not list(tmp_path.glob(".sumire-rename-*"))


def test_cancel_after_first_rename_restores_originals(tmp_path):
    paths = [tmp_path / f"old{number}.png" for number in range(3)]
    for number, path in enumerate(paths):
        path.write_bytes(bytes([number]))
    before = {path: path.read_bytes() for path in paths}
    cancel = threading.Event()
    with pytest.raises(Cancelled):
        rename_images({path: tmp_path / f"{number}.png" for number, path in enumerate(paths)}, cancel=cancel,
                      progress=lambda done, total: cancel.set())
    assert {path: path.read_bytes() for path in paths} == before
    assert len(list(tmp_path.iterdir())) == 3


def test_duplicate_names_use_windows_case_rules(tmp_path):
    with pytest.raises(ImageProblem):
        rename_images({tmp_path / "a.png": tmp_path / "name.png", tmp_path / "b.png": tmp_path / "NAME.PNG"})
