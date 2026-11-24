"""A ZIP opened in a tab: listing, thumbnails, ←/→, folders, zoom, comparison, labels, export, read only.

Every ZIP is made here from generated images; the ZIP's bytes are checked to stay the same.
"""
import hashlib
import io
import os
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog

from sumire.archive import ArchiveEntry
from sumire.compare import ComparisonDialog
from sumire.labels import ReviewLabels
from sumire.window import Window


def png(color, size=(48, 36)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


IMAGES = {"b.png": png((200, 0, 0)), "a.png": png((0, 200, 0)), "c.jpg": png((0, 0, 200)),
          "sub/d.png": png((10, 10, 10)), "sub/deeper/e.png": png((20, 20, 20)), "notes.txt": b"text"}


def make_zip(path, members=IMAGES):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def idle(qtbot, window):
    qtbot.waitUntil(lambda: not window.busy() and not window.saving and not window.finalizing, timeout=10000)


@pytest.fixture
def zipped(tmp_path):
    return make_zip(tmp_path / "set.zip")


@pytest.fixture
def opened(qtbot, zipped):
    widget = Window()
    with qtbot.waitExposed(widget):
        widget.show()
    widget.open_inputs([str(zipped)])
    qtbot.waitUntil(lambda: widget.document is not None, timeout=10000)
    idle(qtbot, widget)
    widget.canvas.setFocus()
    yield widget
    widget.close()


def names(window):
    return [path.name for path in window.visible_paths()]


def test_opens_a_zip_and_lists_its_images_without_extracting(qtbot, opened, zipped, tmp_path):
    before = digest(zipped)
    assert opened.archive is not None and opened.read_only
    assert names(opened) == ["a.png", "b.png", "c.jpg"]  # the top folder only, in name order; not the text file
    assert all(isinstance(path, ArchiveEntry) for path in opened.model.paths)
    assert opened.model.index(0).data(Qt.ItemDataRole.DisplayRole).split("\n")[0] == "a.png"  # the name only, as for files
    assert opened.document.path.name == "a.png" and opened.document.image.getpixel((0, 0))[:3] == (0, 200, 0)
    assert "ZIP（読み取り専用）" in opened.status.text()
    assert "set.zip" in opened.folder_path_label.text() and "読み取り専用" in opened.folder_path_label.text()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["set.zip"]  # nothing extracted next to it
    assert digest(zipped) == before


def test_thumbnails_are_made_on_demand(qtbot, opened):
    model = opened.model
    index = model.index(1)
    model.data(index, Qt.ItemDataRole.DecorationRole)
    qtbot.waitUntil(lambda: model.paths[1] in model.cache, timeout=5000)
    icon = model.cache[model.paths[1]]
    assert not icon.pixmap(32, 32).isNull()


def test_arrow_keys_move_through_the_zip(qtbot, opened):
    opened.canvas.setFocus()
    QTest.keyClick(opened.canvas, Qt.Key.Key_Right)
    idle(qtbot, opened)
    qtbot.waitUntil(lambda: opened.document.path.name == "b.png", timeout=5000)
    assert opened.index == 1 and opened.position_label.text().replace(" ", "").startswith("2")
    QTest.keyClick(opened.canvas, Qt.Key.Key_Left)
    qtbot.waitUntil(lambda: opened.document.path.name == "a.png", timeout=5000)
    assert opened.list.currentIndex().data(Qt.ItemDataRole.UserRole) == str(opened.document.path)  # list follows


def test_folders_inside_the_zip_are_browsed(qtbot, opened, zipped):
    rows = [opened.folder_list.item(row).text() for row in range(opened.folder_list.count())]
    assert rows == ["sub"] and not opened.folder_up_button.isEnabled()
    opened.folder_row_opened(opened.folder_list.item(0).data(Qt.ItemDataRole.UserRole))  # a click on 「sub」
    idle(qtbot, opened)
    assert names(opened) == ["d.png"] and opened.archive_folder == "sub"
    assert opened.folder_path_label.text().startswith("set.zip / sub")
    opened.open_archive_folder("sub/deeper")
    idle(qtbot, opened)
    assert names(opened) == ["e.png"] and opened.document.path.member == "sub/deeper/e.png"
    opened.open_archive_parent()
    idle(qtbot, opened)
    assert opened.archive_folder == "sub"
    opened.open_archive_folder("../..")  # not a folder of this ZIP: nothing happens
    assert opened.archive_folder == "sub"


def test_zoom_and_comparison_work_for_zip_images(qtbot, opened, monkeypatch):
    scale = opened.canvas.scale
    opened.canvas.zoom(2)
    assert opened.canvas.scale == pytest.approx(min(16, scale * 2))
    opened.canvas.fit()
    shown = []
    monkeypatch.setattr(ComparisonDialog, "exec", lambda self: shown.append(self) or 0)
    opened.select_paths(opened.model.paths[:3])
    opened.compare_images()
    idle(qtbot, opened)
    assert len(shown) == 1 and len(shown[0].views) == 3  # the three images, read from the ZIP


def test_labels_are_kept_in_records_and_the_zip_is_unchanged(qtbot, opened, zipped):
    before = digest(zipped)
    opened.auto_advance.setChecked(False)
    opened.press_label("accepted")
    entry = opened.document.path
    assert opened.model.labels[entry] == "accepted"
    assert ReviewLabels(zipped.parent).get(entry) == "accepted"
    opened.write_tags({entry: ("要修正",)}, {entry: ()})
    assert opened.model.tags[entry] == ("要修正",)
    assert digest(zipped) == before
    opened.reload_workspace()
    qtbot.waitUntil(lambda: opened.document is not None and not opened.busy(), timeout=10000)
    assert opened.model.labels[opened.model.paths[0]] == "accepted"  # kept after opening it again


def test_only_the_chosen_images_are_exported(qtbot, opened, zipped, tmp_path, monkeypatch):
    before = digest(zipped)
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.png").write_bytes(b"already here")
    monkeypatch.setattr(Window, "confirm_dialog", lambda self, dialog, **kwargs: True)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(out))
    opened.select_paths([path for path in opened.model.paths if path.name in ("a.png", "c.jpg")])
    assert opened.workflow_actions["export_archive"].isVisible() and opened.workflow_actions["export_archive"].isEnabled()
    opened.export_from_archive()
    qtbot.waitUntil(lambda: opened.batch_job is None, timeout=10000)
    assert sorted(path.name for path in out.iterdir()) == ["a.png", "a_2.png", "c.jpg"]
    assert (out / "a.png").read_bytes() == b"already here"  # never overwritten
    assert (out / "a_2.png").read_bytes() == IMAGES["a.png"] and (out / "c.jpg").read_bytes() == IMAGES["c.jpg"]
    assert "書き出しました" in opened.status.text()
    assert digest(zipped) == before


def test_writing_is_refused_in_a_zip(qtbot, opened, zipped, tmp_path, monkeypatch):
    before = digest(zipped)
    listing = sorted(path.name for path in tmp_path.iterdir())
    for widget in (opened.manual_save, opened.metadata_button, opened.rename_button, opened.crop_tool, opened.reset_edits_button,
                   opened.workflow_actions["delete_selected"], opened.workflow_actions["save_as"], opened.new_folder_button,
                   opened.workflow_actions["convert_selected"], opened.workflow_actions["collage"], opened.share_button,
                   opened.erase_button, opened.text_button):
        assert not widget.isEnabled(), widget
    assert opened.canvas.locked and opened.save_next_button.text() == "次へ"
    assert opened.tools_scroll.isHidden() and not opened.read_only_note.isHidden()  # a note instead of the tools
    assert opened.list.editTriggers() == opened.list.EditTrigger.NoEditTriggers
    monkeypatch.setattr(Window, "confirm_dialog", lambda self, dialog, **kwargs: True)
    entry = opened.document.path
    for attempt in (lambda: opened.save(force=True), opened.delete_selected, lambda: opened.rename_paths({entry: entry}),
                    lambda: opened.move_to_folders({entry: tmp_path}), opened.save_as, lambda: opened.transform_image(rotation=90),
                    lambda: opened.number_images([entry]), lambda: opened.convert_images([entry], "convert"),
                    opened.make_collage, lambda: opened.create_subfolder(), opened.analyze_duplicates, opened.start_batch,
                    opened.save_project, opened.reset_edits, opened.export_labels):
        assert attempt() is None
        assert "読み取り専用" in opened.status.text()
    QTest.mouseClick(opened.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, opened.canvas.rect().center())
    QTest.keyClick(opened.canvas, Qt.Key.Key_E)  # tool keys do nothing harmful either
    QTest.keyClick(opened.canvas, Qt.Key.Key_Return)
    idle(qtbot, opened)
    assert not opened.document.dirty and opened.document.edit_mask.getbbox() is None
    assert digest(zipped) == before and sorted(path.name for path in tmp_path.iterdir()) == listing


def test_a_broken_image_does_not_stop_the_others(qtbot, tmp_path):
    members = dict(IMAGES)
    members["b.png"] = b"\x89PNG\r\n\x1a\n broken"
    zipped = make_zip(tmp_path / "mixed.zip", members)
    window = Window()
    window.show()
    window.open_inputs([str(zipped)])
    qtbot.waitUntil(lambda: window.document is not None, timeout=10000)
    idle(qtbot, window)
    window.navigate(1)  # b.png
    idle(qtbot, window)
    assert window.model.states.get(window.model.paths[1]) == "読み込みエラー"
    window._load_index(2)
    idle(qtbot, window)
    assert window.document.path.name == "c.jpg"
    window.close()


def test_a_changed_or_deleted_zip_is_reported_and_reloads(qtbot, opened, zipped):
    make_zip(zipped, {"a.png": png((1, 2, 3)), "z.png": png((4, 5, 6))})
    os.utime(zipped, ns=(1, 1))
    opened.documents.clear()
    opened._load_index(1)
    idle(qtbot, opened)
    assert "変更されました" in opened.status.text()
    opened.reload_workspace()
    qtbot.waitUntil(lambda: opened.document is not None and not opened.busy(), timeout=10000)
    assert names(opened) == ["a.png", "z.png"]
    zipped.unlink()
    opened.documents.clear()
    opened._load_index(1)
    idle(qtbot, opened)
    assert "見つかりません" in opened.status.text()


def test_unsafe_entries_are_left_out_and_counted(qtbot, tmp_path):
    zipped = make_zip(tmp_path / "odd.zip", {"ok.png": png((1, 1, 1))})
    with zipfile.ZipFile(zipped, "a") as handle:
        handle.writestr(zipfile.ZipInfo("../evil.png"), png((2, 2, 2)))
        handle.writestr(zipfile.ZipInfo("/abs.png"), png((3, 3, 3)))
    window = Window()
    window.show()
    window.open_inputs([str(zipped)])
    qtbot.waitUntil(lambda: window.document is not None, timeout=10000)
    idle(qtbot, window)
    assert names(window) == ["ok.png"] and "名前が不正 2" in window.status.text()
    window.close()


def test_a_folder_opened_after_a_zip_is_writable_again(qtbot, opened, tmp_path, patterned):
    folder = tmp_path / "plain"
    folder.mkdir()
    patterned.save(folder / "x.png")
    opened.load_inputs([str(folder)])
    qtbot.waitUntil(lambda: opened.document is not None and opened.document.path == folder / "x.png", timeout=10000)
    idle(qtbot, opened)
    assert opened.archive is None and not opened.read_only
    assert opened.manual_save.isEnabled() and opened.erase_button.isEnabled() and not opened.canvas.locked
    assert not opened.tools_scroll.isHidden() and opened.read_only_note.isHidden()
    assert not opened.workflow_actions["export_archive"].isVisible()


def test_tabs_open_a_zip_in_a_tab_of_its_own(qtbot, zipped, tmp_path, patterned):
    from sumire.workspace_tabs import WorkspaceWindow
    host = WorkspaceWindow()
    host.show()
    folder = tmp_path / "plain"
    folder.mkdir()
    patterned.save(folder / "x.png")
    host.open_inputs([str(folder)])
    qtbot.waitUntil(lambda: host.tabs.count() == 1 and host.workspaces()[0].document is not None, timeout=10000)
    host.open_inputs([str(zipped)])  # no "add to this tab?" question: a ZIP gets its own tab
    qtbot.waitUntil(lambda: host.tabs.count() == 2 and host.workspaces()[1].document is not None, timeout=10000)
    zip_tab = host.workspaces()[1]
    assert zip_tab.archive is not None and host.tabs.tabText(1).endswith("set.zip")
    zip_tab.append_inputs([str(folder)])
    assert "新しいタブ" in zip_tab.status.text() and zip_tab.archive is not None
    state = zip_tab.session_state()
    assert state["inputs"] == [str(zipped)] and "archive_folder" in state["workspace"]
    for page in host.workspaces():
        qtbot.waitUntil(lambda: not page.busy(), timeout=10000)
    host.close_all_tabs()
    qtbot.waitUntil(lambda: host.tabs.count() == 0, timeout=10000)
    host.close()


def test_metadata_of_a_zip_image_can_be_read(qtbot, tmp_path, monkeypatch):
    from PIL import PngImagePlugin
    from sumire import editor_dialogs
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", "a generated prompt")
    buffer = io.BytesIO()
    Image.new("RGB", (32, 24), (5, 6, 7)).save(buffer, "PNG", pnginfo=info)
    zipped = make_zip(tmp_path / "gen.zip", {"gen.png": buffer.getvalue()})
    before = digest(zipped)
    window = Window()
    window.show()
    window.open_inputs([str(zipped)])
    qtbot.waitUntil(lambda: window.document is not None, timeout=10000)
    idle(qtbot, window)
    assert window.document.metadata  # 「メタデータ：有り」
    shown = []
    monkeypatch.setattr(editor_dialogs.MetadataDialog, "exec", lambda self: shown.append(self) or 0)
    window.editor_actions["metadata"].trigger()
    idle(qtbot, window)
    assert shown and "a generated prompt" in shown[0].text
    assert digest(zipped) == before
    window.close()


def test_the_right_click_menu_of_a_zip_offers_only_reading_actions(qtbot, opened):
    from PySide6.QtWidgets import QMenu
    menu = QMenu(opened)
    opened.populate_selection_menu(menu)
    texts = [action.text() for action in menu.actions() if action.text()]
    assert "ZIPから書き出す…" in texts and "複数枚を並べて比較…" in texts
    assert not any(text.startswith(("画像を削除", "切り取り", "別名で保存", "フォルダーへ移動")) for text in texts)


def test_a_zip_of_one_folder_opens_inside_it(qtbot, tmp_path):
    zipped = make_zip(tmp_path / "wrapped.zip", {"photos/a.png": png((1, 1, 1)), "photos/more/b.png": png((2, 2, 2))})
    window = Window()
    window.show()
    window.open_inputs([str(zipped)])
    qtbot.waitUntil(lambda: window.document is not None, timeout=10000)
    idle(qtbot, window)
    assert window.archive_folder == "photos" and names(window) == ["a.png"]
    several = make_zip(tmp_path / "several.zip", {"x/a.png": png((1, 1, 1)), "y/b.png": png((2, 2, 2))})
    window.load_inputs([str(several)])
    qtbot.waitUntil(lambda: window.archive is not None and window.archive.path == several and not window.busy(), timeout=10000)
    assert window.archive_folder == "" and names(window) == [] and "フォルダーの中" in window.status.text()
    assert [window.folder_list.item(row).text() for row in range(window.folder_list.count())] == ["x", "y"]
    window.close()


def test_a_zip_tab_comes_back_after_a_restart(qtbot, zipped):
    from sumire.workspace_tabs import WorkspaceWindow
    host = WorkspaceWindow()
    host.show()
    host.open_inputs([str(zipped)])
    qtbot.waitUntil(lambda: host.tabs.count() == 1 and host.workspaces()[0].document is not None, timeout=10000)
    page = host.workspaces()[0]
    idle(qtbot, page)
    page.open_archive_folder("sub/deeper")
    idle(qtbot, page)
    host.close()
    qtbot.waitUntil(lambda: not host.isVisible(), timeout=10000)
    resumed = WorkspaceWindow()
    resumed.show()
    resumed.resume_session()
    qtbot.waitUntil(lambda: resumed.tabs.count() == 1 and resumed.current_workspace().document is not None, timeout=10000)
    current = resumed.current_workspace()
    idle(qtbot, current)
    assert current.archive is not None and current.archive_folder == "sub/deeper"
    assert current.document.path.member == "sub/deeper/e.png"
    resumed.close()
    qtbot.waitUntil(lambda: not resumed.isVisible(), timeout=10000)
