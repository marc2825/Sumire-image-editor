"""Independent workspaces, import choices, safe closing, and direct renaming."""
from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox

from sumire.imaging import ImageProblem
from sumire.preferences import Preferences
from sumire.workspace_tabs import WorkspaceWindow

from test_gui import draw, wait_saved


@pytest.fixture
def tabs(qtbot):
    host = WorkspaceWindow()
    host.show()
    yield host
    for page in host.workspaces():
        qtbot.waitUntil(lambda: not page.busy() and not page.saving, timeout=15000)
        page.auto.setChecked(False)
        page.autosave_timer.stop()
        page.pending_action = None
        if page.document:
            page.document.saved_revision = page.document.revision
    host.close_all_tabs()
    qtbot.waitUntil(lambda: host.tabs.count() == 0, timeout=10000)
    host.close()


def picture(path, patterned):
    path.parent.mkdir(parents=True, exist_ok=True)
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", "synthetic private prompt")
    patterned.save(path, pnginfo=info)
    return path


def ready(qtbot, page):
    qtbot.waitUntil(lambda: page.document is not None and page.canvas.ready and not page.busy() and not page.saving, timeout=10000)


def open_page(qtbot, tabs, path, mode=None):
    tabs.open_inputs([str(path)], mode=mode)
    page = tabs.current_workspace()
    ready(qtbot, page)
    return page


def test_launch_resumes_legacy_saved_workspace(qtbot, tmp_path, patterned):
    source = picture(tmp_path / "old.png", patterned)
    Preferences().save({"inputs": [str(source)], "recent": [[str(source)]], "settings": {"overwrite": False}})
    host = WorkspaceWindow()
    host.show()
    host.resume_session()
    page = host.current_workspace()
    ready(qtbot, page)
    assert host.tabs.count() == 1 and page.document.path == source
    assert not page.overwrite.isChecked()
    assert host.welcome.recent_workspaces() == [[str(source)]]
    host.close()
    qtbot.waitUntil(lambda: not host.isVisible())


def test_append_keeps_edits_undo_selection_and_exact_image_scope(qtbot, tabs, tmp_path, patterned, monkeypatch):
    source = picture(tmp_path / "first" / "one.png", patterned)
    extra = picture(tmp_path / "other" / "two.png", patterned)
    sibling = picture(extra.parent / "unselected.png", patterned)
    page = open_page(qtbot, tabs, source.parent)
    page.auto.setChecked(False)
    draw(page)
    ready(qtbot, page)
    document, pixels, history = page.document, page.document.image.tobytes(), list(page.document.undo_stack)
    page.set_review_label("accepted")
    monkeypatch.setattr(tabs, "choose_open_mode", lambda *args: "append")
    tabs.open_inputs([str(extra)])
    ready(qtbot, page)
    assert tabs.tabs.count() == 1 and page.document is document
    assert page.document.image.tobytes() == pixels and page.document.undo_stack == history
    assert page.document.dirty and page.model.labels[source] == "accepted"
    assert page.selected_paths() == [source] and set(page.model.paths) == {source, extra}
    assert extra.parent not in page.watched_folders
    page.poll_folders()
    page.poll_folders()
    assert sibling not in page.model.paths
    tabs.open_inputs([str(extra)], mode="append")
    ready(qtbot, page)
    assert len(page.model.paths) == 2


def test_new_tab_preserves_previous_work_and_shortcuts_affect_current_only(qtbot, tabs, tmp_path, patterned, monkeypatch):
    first = picture(tmp_path / "first.png", patterned)
    second = picture(tmp_path / "second.png", patterned)
    a = open_page(qtbot, tabs, first)
    a.auto.setChecked(False)
    draw(a)
    ready(qtbot, a)
    document = a.document
    monkeypatch.setattr(tabs, "choose_open_mode", lambda *args: "new")
    b = open_page(qtbot, tabs, second)
    b.auto.setChecked(False)
    draw(b)
    ready(qtbot, b)
    tabs.activateWindow()
    b.canvas.setFocus()
    QTest.keyClick(b.canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: b.document.revision == 0 and not b.finalizing, timeout=10000)
    assert a.document is document and a.document.revision == 1
    assert tabs.tabs.count() == 2 and a.document.dirty
    QTest.keyClick(b.canvas, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: tabs.current_workspace() is a)
    assert a.document is document and not a.canvas.compare and not b.canvas.compare


@pytest.mark.parametrize("choice,count", [("現在のタブに追加", 1), ("新しいタブで開く", 2)])
def test_actual_open_choice_dialog(qtbot, tabs, tmp_path, patterned, choice, count):
    a = picture(tmp_path / "a.png", patterned)
    b = picture(tmp_path / "b.png", patterned)
    page = open_page(qtbot, tabs, a)
    def choose():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QMessageBox)
        next(button for button in dialog.buttons() if button.text() == choice).click()
    QTimer.singleShot(50, choose)
    tabs.open_inputs([str(b)])
    ready(qtbot, tabs.current_workspace())
    assert tabs.tabs.count() == count
    assert page.document.path == a


def test_cancel_open_and_failed_append_keep_workspace(qtbot, tabs, tmp_path, patterned, monkeypatch):
    source = picture(tmp_path / "a.png", patterned)
    page = open_page(qtbot, tabs, source)
    monkeypatch.setattr(tabs, "choose_open_mode", lambda *args: None)
    tabs.open_inputs([str(source)])
    assert tabs.tabs.count() == 1 and page.model.paths == [source]
    tabs.open_inputs([str(tmp_path / "missing.png")], mode="append")
    qtbot.waitUntil(lambda: not page.loading)
    assert page.model.paths == [source] and page.document.path == source
    assert "見つかりません" in page.status.text()


def test_close_last_tab_returns_to_welcome_and_keeps_recent(qtbot, tabs, tmp_path, patterned):
    source = picture(tmp_path / "a.png", patterned)
    page = open_page(qtbot, tabs, source)
    tabs.close_tab(page)
    qtbot.waitUntil(lambda: tabs.tabs.count() == 0)
    assert tabs.isVisible() and tabs.stack.currentWidget() is tabs.welcome
    assert tabs.welcome.document is None and [str(source)] in tabs.welcome.recent_workspaces()


def test_cancel_close_all_keeps_unsaved_document(qtbot, tabs, tmp_path, patterned, monkeypatch):
    page = open_page(qtbot, tabs, picture(tmp_path / "a.png", patterned))
    page.auto.setChecked(False)
    draw(page)
    ready(qtbot, page)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    tabs.close_all_tabs()
    assert tabs.tabs.count() == 1 and page.document.dirty and tabs.close_mode is None


def test_failed_save_prevents_application_close(qtbot, tabs, tmp_path, patterned, monkeypatch):
    import sumire.window as module
    page = open_page(qtbot, tabs, picture(tmp_path / "a.png", patterned))
    page.auto.setChecked(False)
    draw(page)
    ready(qtbot, page)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Save)
    def fail(*args, **kwargs):
        raise ImageProblem("synthetic save failure")
    monkeypatch.setattr(module, "save_image", fail)
    monkeypatch.setattr("sumire.batch_features.save_image", fail)  # whole-list work saves from here
    tabs.close()
    qtbot.waitUntil(lambda: page.save_failed and not page.saving)
    assert tabs.isVisible() and tabs.tabs.count() == 1 and page.document.dirty
    assert tabs.close_mode is None


def test_successful_save_then_close_all_returns_to_welcome(qtbot, tabs, tmp_path, patterned):
    open_page(qtbot, tabs, picture(tmp_path / "a.png", patterned))
    b = open_page(qtbot, tabs, picture(tmp_path / "b.png", patterned), "new")
    draw(b)
    tabs.close_all_tabs()
    qtbot.waitUntil(lambda: tabs.tabs.count() == 0, timeout=15000)
    assert tabs.isVisible() and tabs.stack.currentWidget() is tabs.welcome


def test_metadata_buttons_are_visible_and_scope_is_one_tab(qtbot, tabs, tmp_path, patterned):
    one = picture(tmp_path / "one.png", patterned)
    two = picture(tmp_path / "two.png", patterned)
    open_page(qtbot, tabs, one)
    b = open_page(qtbot, tabs, two, "new")
    assert b.metadata_delete_button.isVisible() and b.batch_delete_button.isVisible()
    assert not tabs.welcome.metadata_delete_button.isVisible()
    b.metadata_delete_button.click()
    qtbot.waitUntil(lambda: b.document.output is not None and not b.saving, timeout=10000)
    with Image.open(two) as image:
        assert "parameters" not in image.info
    with Image.open(one) as image:
        assert image.info["parameters"] == "synthetic private prompt"


def test_f2_and_double_click_rename_in_place_and_escape_cancels(qtbot, tabs, tmp_path, patterned):
    source = picture(tmp_path / "名前.png", patterned)
    page = open_page(qtbot, tabs, source)
    original = source.read_bytes()
    tabs.activateWindow()
    page.canvas.setFocus()
    QTest.keyClick(page.canvas, Qt.Key.Key_F2)
    assert page.file_label.editing
    page.file_label.editor.setText("取り消し")
    QTest.keyClick(page.file_label.editor, Qt.Key.Key_Escape)
    assert not page.file_label.editing and source.exists()
    QTest.mouseDClick(page.file_label.label, Qt.MouseButton.LeftButton)
    assert page.file_label.editing
    page.file_label.editor.setText("新しい名前")
    QTest.keyClick(page.file_label.editor, Qt.Key.Key_Return)
    target = source.with_name("新しい名前.png")
    qtbot.waitUntil(lambda: not page.busy() and page.document.path == target and page.canvas.ready, timeout=10000)
    assert target.read_bytes() == original and not source.exists()
    assert page.workspace_inputs == [str(target)] and len(page.model.paths) == 1


def test_invalid_name_and_collision_preserve_both_images(qtbot, tabs, tmp_path, patterned):
    source = picture(tmp_path / "a.png", patterned)
    other = picture(tmp_path / "b.png", patterned)
    page = open_page(qtbot, tabs, source)
    original, existing = source.read_bytes(), other.read_bytes()
    page.rename_current()
    page.file_label.editor.setText("CON")
    QTest.keyClick(page.file_label.editor, Qt.Key.Key_Return)
    assert source.exists() and "使用できない" in page.status.text()
    page.rename_current()
    page.file_label.editor.setText("b")
    QTest.keyClick(page.file_label.editor, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not page.busy(), timeout=10000)
    assert source.read_bytes() == original and other.read_bytes() == existing


def test_list_name_can_be_edited_without_changing_suffix(qtbot, tabs, tmp_path, patterned):
    source = picture(tmp_path / "a.png", patterned)
    page = open_page(qtbot, tabs, source)
    page.list.edit(page.proxy.index(0, 0))
    editor = page.list.findChild(QLineEdit)
    assert editor is not None and editor.text() == "a"
    editor.setText("from-list")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    target = source.with_stem("from-list")
    qtbot.waitUntil(lambda: page.document.path == target and not page.busy(), timeout=10000)
    assert target.is_file() and not source.exists()


def test_rename_updates_other_tab_without_losing_its_edits(qtbot, tabs, tmp_path, patterned):
    source = picture(tmp_path / "a.png", patterned)
    a = open_page(qtbot, tabs, source)
    b = open_page(qtbot, tabs, source, "new")
    b.auto.setChecked(False)
    draw(b)
    ready(qtbot, b)
    document, pixels = b.document, b.document.image.tobytes()
    tabs.tabs.setCurrentWidget(a)
    target = source.with_stem("renamed")
    a.rename_paths({source: target})
    qtbot.waitUntil(lambda: a.document.path == target and not a.busy())
    assert b.model.paths == [target] and b.document is document and b.document.path == target
    assert b.document.image.tobytes() == pixels and b.document.dirty


def test_narrow_window_keeps_metadata_actions_inside_toolbar(qtbot, tabs, tmp_path, patterned):
    page = open_page(qtbot, tabs, picture(tmp_path / "a.png", patterned))
    tabs.resize(800, 600)
    qtbot.wait(100)
    # The image's own actions sit above it, on two rows when the column is narrow.
    assert page.image_bar_compact
    for button in (page.metadata_delete_button, page.save_next_button):
        assert button.mapTo(page.image_bar, button.rect().topLeft()).x() >= 0
        assert button.mapTo(page.image_bar, button.rect().bottomRight()).x() < page.image_bar.width()
    assert page.batch_delete_button.width() >= page.batch_delete_button.sizeHint().width()
    # The whole-tab actions have their own row below the header and stay inside the panel.
    assert page.batch_delete_button.geometry().top() > page.library_menu_button.geometry().bottom()
    assert page.reset_labels_button.geometry().right() < page.library_panel.width()
    # The app-wide controls are in the tab row, not in the tab's own (hidden) bar.
    assert not page.top_bar.isVisible()
    for button in (page.file_button, page.save_mode_button, page.help_button):
        assert button.isVisible()
        assert button.mapTo(tabs.tabs, button.rect().topLeft()).x() >= 0
        assert button.mapTo(tabs.tabs, button.rect().bottomRight()).x() < tabs.tabs.width()


def test_file_menu_opens_into_new_tab_and_closes_back_to_welcome(qtbot, tabs, tmp_path, patterned, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    tabs.welcome.update_file_menu()
    assert not tabs.welcome.close_tab_action.isEnabled()
    first = picture(tmp_path / "first" / "a.png", patterned)
    a = open_page(qtbot, tabs, first)
    folder = tmp_path / "second"
    second = picture(folder / "b.png", patterned)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_args: str(folder))
    monkeypatch.setattr(tabs, "choose_open_mode", lambda *_args: "new")
    a.open_folder_action.trigger()
    b = tabs.current_workspace()
    ready(qtbot, b)
    assert tabs.tabs.count() == 2 and b.document.path == second and a.document.path == first
    b.update_file_menu()
    assert b.close_tab_action.isEnabled() and b.close_all_tabs_action.isEnabled()
    b.close_all_tabs_action.trigger()
    qtbot.waitUntil(lambda: tabs.tabs.count() == 0)
    assert tabs.stack.currentWidget() is tabs.welcome and tabs.welcome.file_button.isVisible()


def test_append_loads_stored_labels_before_applying_current_filter(qtbot, tabs, tmp_path, patterned):
    from sumire.labels import ReviewLabels
    a = picture(tmp_path / "first" / "a.png", patterned)
    b = picture(tmp_path / "other" / "b.png", patterned)
    ReviewLabels(b.parent).set(b, "accepted")
    page = open_page(qtbot, tabs, a)
    page.set_review_label("accepted")
    page.filter_combo.setCurrentIndex(page.filter_combo.findData("accepted"))
    ready(qtbot, page)
    tabs.open_inputs([str(b)], mode="append")
    ready(qtbot, page)
    assert page.model.labels[b] == "accepted" and set(page.visible_paths()) == {a, b}


def test_append_folder_watches_only_explicit_folders_and_undo_keeps_additions(qtbot, tabs, tmp_path, patterned):
    first = tmp_path / "first"
    a = picture(first / "a.png", patterned)
    b = picture(first / "b.png", patterned)
    other = tmp_path / "other"
    c = picture(other / "c.png", patterned)
    page = open_page(qtbot, tabs, first)
    page.reorder_selection([str(a)], "")
    assert page.model.paths == [b, a]
    tabs.open_inputs([str(other)], mode="append")
    ready(qtbot, page)
    assert page.watched_folders == {first, other}
    page.undo_organization()
    assert page.model.paths == [a, b, c]


def test_selected_open_mode_waits_for_rename_started_by_chooser(qtbot, tabs, tmp_path, patterned, monkeypatch):
    a = picture(tmp_path / "a.png", patterned)
    b = picture(tmp_path / "b.png", patterned)
    page = open_page(qtbot, tabs, a)
    def choose(*args):
        page.loading = True
        QTimer.singleShot(50, lambda: setattr(page, "loading", False))
        return "append"
    monkeypatch.setattr(tabs, "choose_open_mode", choose)
    tabs.open_inputs([str(b)])
    assert len(tabs.pending_inputs) == 1
    qtbot.waitUntil(lambda: b in page.model.rows and not page.loading, timeout=10000)
    assert page.document.path == a and not tabs.pending_inputs


def test_external_open_uses_choice_and_preserves_current_tab(qtbot, tabs, tmp_path, patterned, monkeypatch):
    a = picture(tmp_path / "a.png", patterned)
    b = picture(tmp_path / "b.png", patterned)
    page = open_page(qtbot, tabs, a)
    monkeypatch.setattr(tabs, "choose_open_mode", lambda *args: "new")
    tabs.receive_external([str(b)])
    qtbot.waitUntil(lambda: tabs.tabs.count() == 2 and tabs.current_workspace().document is not None, timeout=10000)
    assert page.model.paths == [a] and tabs.current_workspace().document.path == b


def test_batch_metadata_button_processes_all_current_tab_images_only(qtbot, tabs, tmp_path, patterned, batch_approved):
    a = picture(tmp_path / "group" / "a.png", patterned)
    b = picture(a.parent / "b.png", patterned)
    other = picture(tmp_path / "other" / "c.png", patterned)
    first = open_page(qtbot, tabs, a.parent)
    open_page(qtbot, tabs, other, "new")
    tabs.tabs.setCurrentWidget(first)
    first.batch_delete_button.click()
    qtbot.waitUntil(lambda: first.batch_job is None and first.document.output is not None, timeout=15000)
    for path in (a,b):
        with Image.open(path) as image:
            assert "parameters" not in image.info
    with Image.open(other) as image:
        assert "parameters" in image.info


def test_application_close_waits_for_save_then_closes_all_pages(qtbot, tabs, tmp_path, patterned):
    open_page(qtbot, tabs, picture(tmp_path / "a.png", patterned))
    page = open_page(qtbot, tabs, picture(tmp_path / "b.png", patterned), "new")
    draw(page)
    tabs.close()
    qtbot.waitUntil(lambda: not tabs.isVisible(), timeout=15000)
    assert tabs.tabs.count() == 0 and tabs.welcome.closing


def test_closing_all_remembers_settings_of_last_active_tab(qtbot, tabs, tmp_path, patterned):
    a = open_page(qtbot, tabs, picture(tmp_path / "a.png", patterned))
    open_page(qtbot, tabs, picture(tmp_path / "b.png", patterned), "new")
    tabs.tabs.setCurrentWidget(a)
    a.auto.setChecked(False)
    a.brush.setValue(123)
    tabs.close_all_tabs()
    qtbot.waitUntil(lambda: tabs.tabs.count() == 0)
    assert tabs.preferences.data["settings"]["brush"] == 123
    assert tabs.welcome.brush.value() == 123


def test_close_tab_ignores_completed_thumbnail_callbacks(qtbot, tabs, tmp_path, patterned):
    source = picture(tmp_path / "a.png", patterned)
    page = open_page(qtbot, tabs, source)
    page.model._thumbnail(source, 0)
    # Complete the worker without dispatching its queued GUI callback yet.
    page.model.pool.waitForDone()
    tabs.close_tab(page)
    qtbot.wait(100)
    assert tabs.tabs.count() == 0


def test_tab_row_holds_the_current_tabs_app_controls_and_images_have_their_own_bar(qtbot, tabs, tmp_path, patterned):
    a = open_page(qtbot, tabs, picture(tmp_path / "a.png", patterned))
    b = open_page(qtbot, tabs, picture(tmp_path / "b" / "b.png", patterned), "new")
    assert tabs.tabs.currentWidget() is b
    assert b.file_button.parentWidget().parentWidget() is tabs.tabs.leading
    assert b.help_button.parentWidget().parentWidget() is tabs.tabs.trailing
    assert not a.top_bar.isVisible() and not b.top_bar.isVisible()
    tabs.tabs.setCurrentWidget(a)
    assert a.file_button.isVisible() and not b.file_button.isVisible()
    assert a.file_button.parentWidget().parentWidget() is tabs.tabs.leading
    # The image's controls sit above it, the view tools below it.
    assert a.save_next_button.parentWidget() is a.image_bar and a.compare_button.parentWidget() is a.view_bar
    assert a.image_bar.geometry().bottom() <= a.canvas.geometry().top() <= a.view_bar.geometry().top()
    tabs.close_tab(a)
    qtbot.waitUntil(lambda: tabs.tabs.count() == 1)
    assert b.file_button.isVisible() and tabs.tabs.leading.findChildren(type(b.file_button), "fileMenu") == [b.file_button]


def test_quitting_asks_first_and_says_what_is_lost(qtbot, tabs, tmp_path, patterned, monkeypatch):
    import sumire.workspace_tabs as module
    from PySide6.QtWidgets import QMessageBox
    from sumire.preferences import Preferences
    monkeypatch.setitem(module.QUIT_CONFIRMATION, "enabled", True)
    open_page(qtbot, tabs, picture(tmp_path / "a.png", patterned))
    shown = []

    def answer(box, reply, hide=False):
        shown.append(box.informativeText())
        box.checkBox().setChecked(hide)
        return reply

    monkeypatch.setattr(QMessageBox, "exec", lambda box: answer(box, QMessageBox.StandardButton.Cancel))
    tabs.close()
    assert tabs.isVisible() and tabs.tabs.count() == 1 and "履歴は消えます" in shown[0]
    monkeypatch.setattr(QMessageBox, "exec", lambda box: answer(box, QMessageBox.StandardButton.Ok, hide=True))
    tabs.close()
    qtbot.waitUntil(lambda: not tabs.isVisible(), timeout=15000)
    assert len(shown) == 2 and Preferences().data.get("hide_quit_confirmation") is True
