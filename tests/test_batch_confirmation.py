"""Confirm bulk deletion through the same buttons and modal dialog users see."""
import pytest
from PIL import Image, PngImagePlugin
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from test_gui import draw, wait_saved, window


def reply_to_confirmation(answer=QMessageBox.StandardButton.Cancel, *, during=None, delay=0, key=None):
    observed = {}

    def reply():
        dialog = QApplication.activeModalWidget()
        if not isinstance(dialog, QMessageBox):
            observed["unexpected_dialog"] = dialog
            if dialog:
                dialog.reject()
            return
        observed.update(title=dialog.windowTitle(), text=dialog.text(), info=dialog.informativeText(),
                        paths=dialog.detailedText(), default=dialog.standardButton(dialog.defaultButton()),
                        escape=dialog.standardButton(dialog.escapeButton()),
                        accept_text=dialog.button(QMessageBox.StandardButton.Ok).text())
        try:
            if during:
                during(dialog)
        finally:
            if key is not None:
                dialog.activateWindow()
                dialog.defaultButton().setFocus()
                # A delayed assertion turns an offscreen focus failure into a
                # test failure instead of leaving a modal event loop running.
                watchdog = QTimer(dialog)
                watchdog.setSingleShot(True)
                def failed_key():
                    if dialog.isVisible():
                        observed["key_failed"] = True
                        dialog.reject()
                watchdog.timeout.connect(failed_key)
                watchdog.start(500)
                QTest.keyClick(dialog.defaultButton(), key)
            else:
                dialog.button(answer).click()

    QTimer.singleShot(delay, reply)
    return observed


@pytest.mark.parametrize("entry", ["button", "menu"])
def test_cancel_confirms_whole_tab_even_when_filtered(qtbot, window, monkeypatch, entry):
    paths = list(window.model.paths)
    original = {path: path.read_bytes() for path in paths}
    window.set_review_label("accepted")
    window.filter_combo.setCurrentIndex(window.filter_combo.findData("accepted"))
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready)
    assert window.proxy.rowCount() == 1
    assert len(window.selected_paths()) == 1
    guarded = []
    monkeypatch.setattr(window, "guard", lambda action: guarded.append(action))
    observed = reply_to_confirmation()
    if entry == "button":
        window.batch_delete_button.click()
    else:
        window.batch_button.trigger()
    assert observed["title"] == "メタデータの一括削除を確認"
    assert "3 枚" in observed["text"]
    assert "key_failed" not in observed
    assert "一覧全体（選択・絞り込みに関係なく）" in observed["info"]
    assert "元画像に上書き" in observed["info"]
    assert "アプリの終了まで残す" in observed["info"]
    assert "復元用に残す（管理記録に圧縮して保存）" in observed["info"]
    assert "<table" in observed["info"]  # label · value rows, not a run of sentences
    assert observed["paths"].splitlines() == [str(path) for path in paths]
    assert observed["default"] == observed["escape"] == QMessageBox.StandardButton.Cancel
    assert observed["accept_text"] == "削除して保存"
    assert not guarded and window.batch_job is None and not window.saving
    assert all(path.read_bytes() == original[path] for path in paths)


def test_separate_output_and_disabled_backup_are_shown(window):
    window.overwrite.setChecked(False)
    window.metadata_backup.setChecked(False)
    original = {path: path.read_bytes() for path in window.model.paths}
    observed = reply_to_confirmation()
    window.start_batch()
    assert "別フォルダーへ保存" in observed["info"]
    assert str(window.output_folder) in observed["info"]
    assert window.format_combo.currentText() in observed["info"]
    assert ">残さない<" in observed["info"]
    assert "元画像に上書き" not in observed["info"]
    assert all(path.read_bytes() == content for path, content in original.items())
    assert not list(window.output_folder.glob("*.png"))


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Escape])
def test_default_enter_and_escape_cancel_without_saving_edits(qtbot, window, key):
    window.auto.setChecked(False)
    source = window.document.path
    original = source.read_bytes()
    draw(window)
    qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready)
    edited = window.document.image.tobytes()
    assert window.document.dirty
    observed = reply_to_confirmation(key=key, delay=50)
    window.start_batch()
    assert "3 枚" in observed["text"]
    assert "key_failed" not in observed
    assert window.document.dirty and window.document.undo_stack
    assert window.document.image.tobytes() == edited
    assert source.read_bytes() == original
    assert not window.saving and window.batch_job is None and window.pending_action is None


def test_confirmed_deletion_uses_only_paths_listed_in_dialog(qtbot, window, patterned):
    paths = list(window.model.paths)
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", "private batch confirmation test")
    for path in paths:
        patterned.save(path, pnginfo=info)
    window.open_inputs([str(paths[0].parent)])
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready, timeout=10000)
    later = paths[0].parent / "later.png"

    def add_image(dialog):
        # Simulate folder monitoring adding an image while the dialog is open.
        patterned.save(later, pnginfo=info)
        window.replace_list([*paths, later])

    observed = reply_to_confirmation(QMessageBox.StandardButton.Ok, during=add_image)
    window.batch_delete_button.click()
    qtbot.waitUntil(lambda: window.batch_job is None and "一括処理完了" in window.status.text(), timeout=15000)
    assert observed["paths"].splitlines() == [str(path) for path in paths]
    assert "保存 3 / 失敗 0" in window.status.text()
    for path in paths:
        with Image.open(path) as image:
            assert "parameters" not in image.info
    with Image.open(later) as image:
        assert "parameters" in image.info


def test_removed_paths_require_confirmation_again(window):
    paths = list(window.model.paths)
    original = {path: path.read_bytes() for path in paths}
    reply_to_confirmation(QMessageBox.StandardButton.Ok,
                          during=lambda dialog: window.replace_list(paths[:-1]))
    window.start_batch()
    assert "確認中に一覧が変更されました" in window.status.text()
    assert not window.saving and window.batch_job is None
    assert all(path.read_bytes() == content for path, content in original.items())


def test_pending_autosave_waits_until_confirmation_closes(qtbot, window):
    source = window.document.path
    original = source.read_bytes()
    draw(window)
    qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready)
    assert window.document.dirty and window.autosave_timer.isActive()
    interval = window.autosave_timer.interval()
    during = {}

    def inspect(dialog):
        during.update(content=source.read_bytes(), saving=window.saving,
                      dirty=window.document.dirty, timer=window.autosave_timer.isActive())

    reply_to_confirmation(during=inspect, delay=interval + 50)
    window.start_batch()
    assert during == dict(content=original, saving=False, dirty=True, timer=False)
    assert window.batch_job is None and window.autosave_timer.interval() == interval
    wait_saved(qtbot, window)
    assert source.read_bytes() != original
