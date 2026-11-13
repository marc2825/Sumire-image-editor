"""Removal is local to the list; resetting edits is confirmed and undoable."""
import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from sumire.imaging import Document, ImageProblem, Stroke, Tool

from test_batch_confirmation import reply_to_confirmation
from test_gui import draw, poll_watched, wait_saved, window
from test_workspace_tabs import open_page, picture, ready, tabs
from test_session_tabs import finish_close, restarted


@pytest.mark.parametrize("key", [None, Qt.Key.Key_Escape, Qt.Key.Key_Return])
def test_cancel_list_removal_preserves_selection_files_and_edits(qtbot, window, key):
    window.auto.setChecked(False)
    draw(window)
    qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready)
    document, paths = window.document, list(window.model.paths)
    before = {path: path.read_bytes() for path in paths}
    pixels = document.image.tobytes()
    observed = reply_to_confirmation(key=key, delay=50)
    window.workflow_actions["remove_selected"].trigger()
    assert "画像ファイルは削除・移動しません" in observed["info"]
    assert "key_failed" not in observed
    assert observed["default"] == observed["escape"] == QMessageBox.StandardButton.Cancel
    assert window.model.paths == paths and window.document is document
    assert document.image.tobytes() == pixels and document.dirty
    assert {path: path.read_bytes() for path in paths} == before


def test_right_click_remove_keeps_files_and_stays_out_until_reload(qtbot, window):
    window.watch_timer.stop()
    original = {path: path.read_bytes() for path in window.model.paths}
    source = window.document.path
    window.set_review_label("accepted")
    window.batch_failures[source] = "synthetic failure"
    index = window.proxy.mapFromSource(window.model.index(window.index))
    QTest.mouseClick(window.list.viewport(), Qt.MouseButton.RightButton, pos=window.list.visualRect(index).center())
    window.show_library_context_menu(window.list.visualRect(index).center())
    assert window.workflow_actions["remove_selected"] in window.context_menu.actions()
    window.context_menu.hide()
    reply_to_confirmation(QMessageBox.StandardButton.Ok)
    window.workflow_actions["remove_selected"].trigger()
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready)
    assert source not in window.model.rows and source in window.excluded_paths
    assert source not in window.model.labels and source not in window.batch_failures
    assert "採用 0" in window.review_summary.text()
    for _ in range(2):
        poll_watched(qtbot, window)
    window.accept_watched_images([source])
    assert source not in window.model.rows
    assert {path: path.read_bytes() for path in original} == original
    window.reload_action.trigger()
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready and source in window.model.rows)
    assert not window.excluded_paths
    assert window.model.labels[source] == "accepted"
    assert {path: path.read_bytes() for path in original} == original


def test_remove_multiple_and_all_images_keeps_tab_reloadable(qtbot, window):
    paths = list(window.model.paths)
    window.select_paths(paths)
    reply_to_confirmation(QMessageBox.StandardButton.Ok)
    window.workflow_actions["remove_selected"].trigger()
    assert not window.model.paths and window.document is None
    assert window.workspace_inputs and window.reload_action.isEnabled()
    assert all(path.is_file() for path in paths)
    window.reload_workspace()
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready)
    assert window.model.paths == paths


def test_removal_is_limited_to_selected_tab(qtbot, tabs, tmp_path, patterned):
    source = picture(tmp_path / "a.png", patterned)
    a = open_page(qtbot, tabs, source)
    b = open_page(qtbot, tabs, source, "new")
    reply_to_confirmation(QMessageBox.StandardButton.Ok)
    b.workflow_actions["remove_selected"].trigger()
    assert b.model.paths == [] and a.model.paths == [source] and a.document.path == source


def test_unsaved_cancel_after_removal_confirmation_keeps_image(qtbot, window, monkeypatch):
    window.auto.setChecked(False)
    draw(window)
    qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready)
    path = window.document.path
    monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.Cancel)
    reply_to_confirmation(QMessageBox.StandardButton.Ok)
    window.remove_selected()
    assert path in window.model.rows and window.document.dirty and not window.excluded_paths


def test_exclusions_survive_session_restore_but_not_explicit_reload(qtbot, tabs, restarted, tmp_path, patterned):
    a = picture(tmp_path / "group" / "a.png", patterned)
    b = picture(a.parent / "b.png", patterned)
    page = open_page(qtbot, tabs, a.parent)
    page.select_paths([b])
    reply_to_confirmation(QMessageBox.StandardButton.Ok)
    page.remove_selected()
    finish_close(qtbot, tabs)
    host = restarted()
    page = host.current_workspace()
    ready(qtbot, page)
    assert page.model.paths == [a] and b in page.excluded_paths
    page.reload_workspace()
    ready(qtbot, page)
    assert page.model.paths == [a, b] and not page.excluded_paths


@pytest.mark.parametrize("accept", [False, True])
def test_reset_confirmation_and_undo_redo_restore_pixels_and_mask(qtbot, window, accept):
    window.auto.setChecked(False)
    draw(window)
    qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready)
    document = window.document
    pixels, mask, revision = document.image.tobytes(), document.edit_mask.tobytes(), document.revision
    file_before = document.path.read_bytes()
    observed = reply_to_confirmation(QMessageBox.StandardButton.Ok if accept else QMessageBox.StandardButton.Cancel)
    window.reset_edits_button.click()
    qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready)
    assert "元画像に戻します" in observed["info"] and "元に戻す" in observed["info"]
    assert observed["default"] == QMessageBox.StandardButton.Cancel
    if not accept:
        assert document.image.tobytes() == pixels and document.edit_mask.tobytes() == mask
        assert document.revision == revision
    else:
        assert document.image.tobytes() == document.original.tobytes()
        assert document.edit_mask.getbbox() is None and document.dirty
        window.history()
        qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready)
        assert document.image.tobytes() == pixels and document.edit_mask.tobytes() == mask
        window.history(redo=True)
        qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready)
        assert document.image.tobytes() == document.original.tobytes() and document.edit_mask.getbbox() is None
    assert document.path.read_bytes() == file_before


@pytest.mark.parametrize("overwrite", [False, True])
def test_reset_autosaves_using_current_save_mode(qtbot, window, overwrite):
    window.overwrite.setChecked(overwrite)
    original = window.document.original.tobytes()
    draw(window)
    wait_saved(qtbot, window)
    qtbot.waitUntil(lambda: window.canvas.ready)
    reply_to_confirmation(QMessageBox.StandardButton.Ok)
    window.reset_edits_action.trigger()
    wait_saved(qtbot, window)
    with Image.open(window.document.output) as saved:
        assert saved.convert("RGBA").tobytes() == original
    assert window.document.edit_mask.getbbox() is None


def test_reset_failure_keeps_pixels_mask_and_history(qtbot, window, monkeypatch):
    import sumire.imaging as module
    window.auto.setChecked(False)
    draw(window)
    qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready)
    document = window.document
    pixels, mask = document.image.tobytes(), document.edit_mask.tobytes()
    state = document.revision, document.edited, list(document.undo_stack)
    def fail(*_):
        raise ImageProblem("synthetic reset failure")
    monkeypatch.setattr(module.zlib, "compress", fail)
    reply_to_confirmation(QMessageBox.StandardButton.Ok)
    window.reset_edits()
    qtbot.waitUntil(lambda: not window.finalizing and "synthetic reset failure" in window.status.text())
    assert document.image.tobytes() == pixels and document.edit_mask.tobytes() == mask
    assert (document.revision, document.edited, document.undo_stack) == state


def test_reset_does_not_claim_to_recover_baked_in_pixels(tmp_path, patterned):
    document = Document(tmp_path / "baked.png", patterned)
    document.original_edited = document.edited = True
    document.edit_mask.paste(255, (0, 0, 20, 20))
    assert document.reset_edits()
    assert document.edited and document.edit_mask.getbbox() is None
    assert document.image.tobytes() == patterned.tobytes()


def test_reset_with_no_changes_preserves_pending_autosave_after_undo(qtbot, window):
    original = window.document.original.tobytes()
    draw(window)
    wait_saved(qtbot, window)
    qtbot.waitUntil(lambda: window.canvas.ready)
    window.history()
    qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready and window.document.dirty)
    assert window.document.edit_mask.getbbox() is None
    reply_to_confirmation(QMessageBox.StandardButton.Ok)
    window.reset_edits()
    wait_saved(qtbot, window)
    with Image.open(window.document.output) as saved:
        assert saved.convert("RGBA").tobytes() == original
