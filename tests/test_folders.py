"""Folders inside a tab: browsing nested folders, creating one, and moving images with their records."""
from pathlib import Path

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from PySide6.QtWidgets import QMenu

import sumire.folders as folders
from sumire.export import file_digest
from sumire.folder_features import FOLDER_ROLE
from sumire.folders import create_folder, move_image, move_images, subfolders
from sumire.imaging import ImageProblem
from sumire.labels import ReviewLabels
from sumire.masks import MaskStore
from sumire.metadata import MetadataStore, capture_metadata

from test_gui import window
from test_workspace_tabs import open_page, picture, tabs


def image(path, color="red", size=(20, 10)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def test_subfolders_are_visible_folders_in_natural_order(tmp_path):
    for name in ("b10", "b2", ".hidden", "a"):
        (tmp_path / name).mkdir()
    image(tmp_path / "file.png")
    assert [path.name for path in subfolders(tmp_path)] == ["a", "b2", "b10"]


@pytest.mark.parametrize("name", ["", "a/b", "con", "end.", "x:y"])
def test_folder_names_are_checked(tmp_path, name):
    with pytest.raises(ImageProblem):
        create_folder(tmp_path, name)


def test_existing_folder_is_not_reused(tmp_path):
    create_folder(tmp_path, "sub")
    with pytest.raises(ImageProblem):
        create_folder(tmp_path, "sub")


def test_move_keeps_bytes_and_records_and_never_overwrites(tmp_path):
    source = image(tmp_path / "a.png")
    bytes_before = source.read_bytes()
    digest = file_digest(source)
    labels = ReviewLabels(tmp_path)
    labels.set(source, "accepted")
    labels.set_note(source, "memo")
    MaskStore(tmp_path).store(source, digest, Image.new("L", (20, 10), 255))
    info = PngInfo()
    info.add_text("parameters", "prompt")
    with_meta = tmp_path / "meta.png"
    Image.new("RGB", (4, 4)).save(with_meta, pnginfo=info)
    MetadataStore(tmp_path).store(source, digest, capture_metadata(with_meta.read_bytes()))
    sub = create_folder(tmp_path, "sub")
    occupied = image(sub / "a.png", "blue")
    occupied_bytes = occupied.read_bytes()
    target = move_image(source, sub)
    assert target == sub / "a_2.png" and not source.exists()
    assert target.read_bytes() == bytes_before and occupied.read_bytes() == occupied_bytes
    moved_labels = ReviewLabels(sub)
    assert moved_labels.get(target) == "accepted" and moved_labels.note(target) == "memo"
    assert ReviewLabels(tmp_path).get(source) is None
    assert MaskStore(sub).get(target, digest, (20, 10)) is not None
    assert MetadataStore(sub).get(target, digest) is not None
    back = move_image(target, tmp_path, name="a.png")
    assert back == source and ReviewLabels(tmp_path).get(source) == "accepted"


def test_move_across_drives_copies_and_verifies(tmp_path, monkeypatch):
    source = image(tmp_path / "a.png")
    data = source.read_bytes()
    sub = create_folder(tmp_path, "sub")
    def no_links(*_args):
        raise OSError("cross-device link")
    monkeypatch.setattr(folders.os, "link", no_links)
    target = move_image(source, sub)
    assert target.read_bytes() == data and not source.exists()


def test_failed_move_leaves_the_source_and_no_copy(tmp_path, monkeypatch):
    source = image(tmp_path / "a.png")
    ReviewLabels(tmp_path).set(source, "pending")
    sub = create_folder(tmp_path, "sub")
    original_unlink = Path.unlink
    def refuse(self, *args, **kwargs):
        if self == source:
            raise PermissionError("in use")
        return original_unlink(self, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", refuse)
    moved, failed = move_images([source], sub)
    assert not moved and source in failed and source.exists()
    assert not (sub / "a.png").exists() and ReviewLabels(sub).get(sub / "a.png") is None
    assert ReviewLabels(tmp_path).get(source) == "pending"


def wait_idle(qtbot, page):
    qtbot.waitUntil(lambda: not page.loading and not page.finalizing and page.batch_job is None, timeout=10000)


def test_browse_nested_folders_inside_the_tab(qtbot, tabs, tmp_path, patterned):
    root = tmp_path / "pics"
    picture(root / "a.png", patterned)
    picture(root / "sub" / "deep" / "c.png", patterned)
    picture(root / "sub" / "b.png", patterned)
    page = open_page(qtbot, tabs, root)
    index = tabs.tabs.indexOf(page)
    assert not page.folder_bar.isHidden() and page.folder_root == root.resolve()
    assert [page.folder_list.item(i).text() for i in range(page.folder_list.count())] == ["sub"]
    assert not page.folder_up_button.isEnabled()
    page.folder_list.item(0).setSelected(True)
    page.folder_list.folderOpened.emit(page.folder_list.item(0).data(FOLDER_ROLE))
    qtbot.waitUntil(lambda: page.browsed_folder() == (root / "sub").resolve() and page.document is not None, timeout=10000)
    wait_idle(qtbot, page)
    assert [path.name for path in page.model.paths] == ["b.png"]
    assert page.folder_root == root.resolve() and tabs.tabs.tabText(index) == "pics"
    assert page.folder_location() == "pics / sub" and page.workspace_label.text() == "pics / sub"
    assert [page.folder_list.item(i).text() for i in range(page.folder_list.count())] == ["..（上のフォルダー）", "deep"]
    assert page.folder_up_button.isEnabled()
    assert page.session_state()["workspace"]["root"] == str(root.resolve())
    page.open_folder_in_tab(root / "sub" / "deep")
    qtbot.waitUntil(lambda: page.browsed_folder() == (root / "sub" / "deep").resolve(), timeout=10000)
    wait_idle(qtbot, page)
    assert page.folder_location() == "pics / sub / deep"
    page.open_parent_folder()
    qtbot.waitUntil(lambda: page.browsed_folder() == (root / "sub").resolve(), timeout=10000)
    page.open_folder_in_tab(tmp_path)  # above the tab's folder: ignored
    wait_idle(qtbot, page)
    assert page.browsed_folder() == (root / "sub").resolve()
    page.reload_workspace()
    wait_idle(qtbot, page)
    assert page.folder_root == root.resolve()


def test_move_images_into_a_folder_and_undo(qtbot, window, tmp_path):
    page = window
    sub = create_folder(tmp_path, "sub")
    page.refresh_folders()
    first, second, third = page.model.paths
    page.write_labels({second: "accepted"}, {second: None})
    page.move_to_folder([second, third], sub)
    wait_idle(qtbot, page)
    assert page.model.paths == [first] and (sub / second.name).exists() and not second.exists()
    assert ReviewLabels(sub).get(sub / second.name) == "accepted"
    assert "「sub」へ移動しました · 2枚" in page.status.text()
    assert page.undo_organize_button.isEnabled()
    page.undo_organize_button.click()
    assert set(page.model.paths) == {first, second, third} and second.exists() and not (sub / second.name).exists()
    assert page.model.labels.get(second) == "accepted"


def test_drop_on_a_folder_row_moves_and_menu_lists_folders(qtbot, window, tmp_path):
    page = window
    sub = create_folder(tmp_path, "sub")
    page.refresh_folders()
    target = page.model.paths[2]
    page.select_paths([target])
    menu = QMenu()
    page.populate_selection_menu(menu)
    move_menu = next(action.menu() for action in menu.actions() if action.text() == "フォルダーへ移動")
    assert [action.text() for action in move_menu.actions() if action.text()] == ["sub", "新しいフォルダーを作って移動…"]
    page.folder_list.imagesDropped.emit([str(target)], str(sub))
    wait_idle(qtbot, page)
    assert target not in page.model.paths and (sub / target.name).exists()


def test_new_folder_from_the_strip_and_move_into_it(qtbot, window, tmp_path, monkeypatch):
    page = window
    names = iter(["作品", "選んだ画像"])
    def answer(self, dialog, accepted=None):
        dialog.setTextValue(next(names))
        return True
    monkeypatch.setattr(type(page), "confirm_dialog", answer)
    page.new_folder_button.click()
    assert (tmp_path / "作品").is_dir() and page.folder_list.item(0).text() == "作品"
    moving = page.model.paths[1]
    page.create_subfolder(move_paths=[moving])
    wait_idle(qtbot, page)
    assert (tmp_path / "選んだ画像" / moving.name).exists() and moving not in page.model.paths


def test_unsaved_images_other_than_the_current_one_are_not_moved(qtbot, window, tmp_path):
    page = window
    sub = create_folder(tmp_path, "sub")
    other = page.model.paths[1]
    class Dirty:
        dirty = True
    page.documents[other] = Dirty()
    page.move_to_folder([other], sub)
    assert other.exists() and "未保存の編集" in page.status.text()
    page.documents.pop(other)


def test_opening_another_folder_from_the_file_menu_starts_a_new_root(qtbot, tabs, tmp_path, patterned):
    root = tmp_path / "pics"
    picture(root / "a.png", patterned)
    picture(root / "sub" / "b.png", patterned)
    page = open_page(qtbot, tabs, root)
    page.load_inputs([str(root / "sub")])
    qtbot.waitUntil(lambda: page.browsed_folder() == (root / "sub").resolve(), timeout=10000)
    wait_idle(qtbot, page)
    assert page.folder_root == (root / "sub").resolve() and page.folder_location() == "sub"
