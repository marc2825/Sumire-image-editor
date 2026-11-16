"""The redesigned window: empty state, save state, search, selection and menus."""
import pytest
from PySide6.QtCore import QItemSelectionModel, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu

from sumire.library import state_summary
from sumire.preferences import Preferences
from sumire.window import Window

from test_gui import draw, wait_saved, window


def test_empty_state_page_until_a_list_is_opened(qtbot, tmp_path, patterned):
    patterned.save(tmp_path / "one.png")
    widget = Window()
    qtbot.addWidget(widget)
    with qtbot.waitExposed(widget):
        widget.show()
    assert widget.pages.currentWidget() is widget.welcome
    assert not widget.save_next_button.isVisible() and not widget.undo_button.isVisible()
    assert not widget.workspace_label.isVisible() and not widget.workspace_separator.isVisible()
    assert "上書き" in widget.welcome.note.text()
    widget.welcome.filesDropped.emit([str(tmp_path)])
    qtbot.waitUntil(lambda: widget.document is not None and widget.canvas.ready, timeout=10000)
    assert widget.pages.currentWidget() is widget.splitter
    assert widget.save_next_button.isVisible() and widget.canvas.hasFocus()
    # Native font metrics may elide the long temporary folder name on Windows.
    assert widget.workspace_title() == tmp_path.name
    assert widget.file_button.isVisible() and widget.file_button.text().startswith("ファイル")
    assert widget.workspace_label.text() == tmp_path.name
    widget.auto.setChecked(False)
    widget.close()


def test_recent_workspaces_are_remembered_and_reopen(qtbot, window, tmp_path, patterned):
    first = window.workspace_inputs
    other = tmp_path / "other"
    other.mkdir()
    patterned.save(other / "a.png")
    window.open_inputs([str(other)])
    qtbot.waitUntil(lambda: window.document is not None and window.document.path.parent == other and window.canvas.ready, timeout=10000)
    window.remember_workspace()
    recent = window.recent_workspaces()
    assert recent[0] == [str(other)] and first in recent
    window.populate_recent_menu()
    titles = [action.text() for action in window.recent_menu.actions()]
    assert titles[0].startswith("other")
    window.open_recent(first)
    qtbot.waitUntil(lambda: window.document is not None and window.document.path.parent != other and window.canvas.ready, timeout=10000)
    assert Preferences().data["recent"][0] == [str(other)]


def test_missing_recent_folder_is_skipped(qtbot, window, tmp_path):
    missing = str(tmp_path / "removed")
    window.preferences.save({**window.preferences.data, "recent": [[missing], window.workspace_inputs]})
    assert window.recent_workspaces() == [window.workspace_inputs]
    window.open_recent([missing])
    assert "見つかりません" in window.status.text()


def test_save_state_shows_unsaved_saving_and_saved(qtbot, window):
    assert "未編集" in window.save_state.text()
    window.auto.setChecked(False)
    draw(window)
    qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready)
    assert "未保存" in window.save_state.text()
    assert "手動保存" in window.save_mode_button.text()
    window.save()
    assert "保存中" in window.save_state.text()
    wait_saved(qtbot, window)
    assert "保存済み" in window.save_state.text()
    assert "上書き" in window.save_mode_button.text()


def test_save_failure_is_shown_until_the_next_save(qtbot, window, monkeypatch):
    import sumire.window as module
    from sumire.imaging import ImageProblem
    window.auto.setChecked(False)
    draw(window)
    qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready)
    original = module.save_image
    def fail(*args, **kwargs):
        raise ImageProblem("synthetic failure")
    monkeypatch.setattr(module, "save_image", fail)
    monkeypatch.setattr("sumire.batch_features.save_image", fail)  # whole-list work saves from here
    window.save()
    qtbot.waitUntil(lambda: not window.saving)
    assert "保存失敗" in window.save_state.text()
    monkeypatch.setattr(module, "save_image", original)
    monkeypatch.setattr("sumire.batch_features.save_image", original)  # whole-list work saves from here
    window.save()
    wait_saved(qtbot, window)
    assert "保存済み" in window.save_state.text()


def test_overwrite_toggle_shows_output_settings_only_for_separate_folder(window):
    assert window.overwrite.isChecked() and window.output_group.isHidden()
    window.overwrite.setChecked(False)
    assert not window.output_group.isHidden() and window.format_combo.isEnabled()
    assert "別フォルダー" in window.save_mode_button.text()
    window.overwrite.setChecked(True)
    assert window.output_group.isHidden()


def test_name_search_filters_navigation_and_resets_on_new_folder(qtbot, window):
    first, second, third = window.model.paths
    window.search.setText("10")
    qtbot.waitUntil(lambda: window.proxy.text == "10" and window.document is not None
                    and window.document.path == third and window.canvas.ready, timeout=10000)
    assert window.visible_paths() == [third]
    assert window.filter_button.property("active") is True
    assert "表示 1 / 3" in window.review_summary.text()
    window.reset_filters()
    qtbot.waitUntil(lambda: window.proxy.text == "" and len(window.visible_paths()) == 3
                    and not window.loading and window.canvas.ready, timeout=10000)
    window.search.setText("image2")
    qtbot.waitUntil(lambda: window.visible_paths() == [second] and window.document is not None
                    and window.document.path == second and not window.loading and window.canvas.ready, timeout=10000)
    window.open_inputs([str(first.parent)])
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready, timeout=10000)
    assert window.search.text() == "" and window.proxy.text == "" and len(window.visible_paths()) == 3


def test_enter_in_search_does_not_save_or_advance(qtbot, window):
    document = window.document
    window.search.setFocus()
    qtbot.waitUntil(lambda: QApplication.focusWidget() is window.search)
    QTest.keyClick(window.search, Qt.Key.Key_Return)
    assert window.document is document and not window.saving
    assert QApplication.focusWidget() is window.canvas


def test_selection_bar_and_context_menu_cover_selected_images(window):
    assert window.selection_bar.isHidden()
    selection = window.list.selectionModel()
    selection.select(window.proxy.index(2, 0), QItemSelectionModel.SelectionFlag.Select)
    assert not window.selection_bar.isHidden() and "2枚" in window.selection_label.text()
    menu = QMenu()
    window.populate_selection_menu(menu)
    actions = [action for action in menu.actions() if not action.isSeparator()]
    assert window.workflow_actions["save_selected"] in actions and window.rename_button in actions
    assert window.label_menu.menuAction() in actions
    window._select_only_current()
    assert window.selection_bar.isHidden() and window.selected_paths() == [window.document.path]


def test_strength_keys_replace_weaker_and_stronger_buttons(qtbot, window):
    window.strength.setValue(20)
    QTest.keyClick(window.canvas, Qt.Key.Key_Period)
    assert window.strength.value() == 22
    QTest.keyClick(window.canvas, Qt.Key.Key_Comma)
    QTest.keyClick(window.canvas, Qt.Key.Key_Comma)
    assert window.strength.value() == 18
    window.set_mode("fill")
    window.strength.setValue(100)
    QTest.keyClick(window.canvas, Qt.Key.Key_Comma)
    assert window.strength.value() == 90
    assert not window.fill_row.isHidden() and not window.weak_button.isHidden()
    window.weak_button.click()
    assert window.strength.value() == 50
    window.set_mode("erase")
    QTest.keyClick(window.canvas, Qt.Key.Key_Period)
    assert window.fill_row.isHidden() and window.strength.isHidden()


def test_list_and_grid_rows_paint_state_and_label(qtbot, window):
    window.set_review_label("accepted")
    window.model.set_note(window.document.path, "メモ")
    assert not window.list.grab().isNull()
    window.view_combo.setCurrentIndex(1)
    assert window.library_delegate.grid and not window.list.grab().isNull()
    window.view_combo.setCurrentIndex(0)
    assert not window.library_delegate.grid


def test_state_summary_tones():
    assert state_summary("未編集") == ("未編集", "neutral")
    assert state_summary("未編集 · 保存済み · メタデータ：無し") == ("保存済み · 未編集", "ok")
    assert state_summary("保存済み · メタデータ：無し") == ("保存済み", "ok")
    assert state_summary("編集中 · 未保存") == ("編集中", "warn")
    assert state_summary("保存失敗 · 変更を保持") == ("保存失敗", "danger")
    assert state_summary("読み込みエラー") == ("読み込みエラー", "danger")


def test_moved_operations_remain_reachable_from_menus(window):
    image_actions = window.image_menu.actions() + [action for menu in window.image_menu.findChildren(type(window.image_menu))
                                                    for action in menu.actions()]
    for action in (window.manual_save, window.metadata_button, window.metadata_restore, window.mask_export):
        assert action in image_actions
    library_actions = window.library_menu.actions()
    for action in (window.number_button, window.watch_action, window.workflow_actions["duplicates"]):
        assert action in library_actions
    assert window.batch_delete_button.isVisible() and window.reset_labels_button.isVisible()
    assert window.export_accepted_button.isVisible() and window.undo_organize_button.isVisible()
    for action in (window.open_folder_action, window.open_files_action, window.app_actions["open_project"],
                   window.recent_menu.menuAction(), window.app_actions["save_project"]):
        assert action in window.file_menu.actions()


@pytest.mark.parametrize("via", ["click", "keyboard"])
def test_file_menu_opens_folder_from_click_or_alt_f(qtbot, window, tmp_path, patterned, monkeypatch, via):
    folder = tmp_path / "日本語 & フォルダー"
    folder.mkdir()
    patterned.save(folder / "one.png")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_args: str(folder))
    observed = []
    def choose():
        observed.append(window.file_menu.isVisible())
        window.file_menu.hide()
        window.open_folder_action.trigger()
    QTimer.singleShot(50, choose)
    if via == "click":
        QTest.mouseClick(window.file_button, Qt.MouseButton.LeftButton)
    else:
        QTest.keyClick(window.canvas, Qt.Key.Key_F, Qt.KeyboardModifier.AltModifier)
    qtbot.waitUntil(lambda: window.document is not None and window.document.path.parent == folder
                    and not window.loading and window.canvas.ready, timeout=10000)
    assert observed == [True]
    assert window.file_button.text().startswith("ファイル")
    assert window.workspace_label.text() == folder.name


def test_workspace_title_is_display_only_and_file_menu_remains_available(window):
    before = window.document
    QTest.mouseClick(window.workspace_label, Qt.MouseButton.LeftButton)
    assert not window.file_menu.isVisible() and window.document is before
    assert not hasattr(window.workspace_label, "menu")
    window.loading = True
    window.update_controls()
    assert window.file_button.isEnabled() and not window.open_folder_action.isEnabled()
    window.loading = False
    window.update_controls()
