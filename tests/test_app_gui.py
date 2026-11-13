from pathlib import Path
import threading

import pytest
from PIL import Image
from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMessageBox, QPushButton

from sumire import DISPLAY_VERSION
from sumire.export import file_digest
from sumire.labels import ReviewLabels
from sumire.preferences import Preferences
from sumire.projects import read_project
from sumire.storage import record_path

from test_gui import draw, wait_saved, window


@pytest.mark.parametrize("overwrite", [True, False])
def test_masks_survive_eviction_and_workspace_reopen(qtbot, window, overwrite):
    window.overwrite.setChecked(overwrite)
    source = window.document.path
    draw(window)
    wait_saved(qtbot, window)
    mask = window.document.edit_mask.tobytes()
    assert any(mask)
    for index in (1, 2, 0):
        window.request_index(index)
        qtbot.waitUntil(lambda: not window.loading and window.canvas.ready, timeout=10000)
    assert window.document.path == source
    assert window.document.edit_mask.tobytes() == mask
    window.open_inputs([str(source.parent)])
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready, timeout=10000)
    assert window.document.edit_mask.tobytes() == mask


def test_external_change_does_not_restore_stale_mask(qtbot, window):
    source = window.document.path
    draw(window)
    wait_saved(qtbot, window)
    Image.new("RGBA", window.document.image.size, "purple").save(source)
    window.open_inputs([str(source.parent)])
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready, timeout=10000)
    assert window.document.edit_mask.getbbox() is None


def test_batch_format_change_keeps_mask_of_evicted_edited_image(qtbot, window):
    window.overwrite.setChecked(False)
    source = window.document.path
    draw(window)
    wait_saved(qtbot, window)
    mask = window.document.edit_mask.tobytes()
    for index in (1, 2):
        window.request_index(index)
        qtbot.waitUntil(lambda: not window.loading and window.canvas.ready, timeout=10000)
    assert source not in window.documents
    window.format_combo.setCurrentIndex(window.format_combo.findData("WEBP"))
    window._start_batch([source])
    qtbot.waitUntil(lambda: window.batch_job is None, timeout=10000)
    window.request_index(window.model.rows[source])
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready, timeout=10000)
    assert window.document.output.suffix == ".webp"
    assert window.document.edit_mask.tobytes() == mask


def test_folder_with_project_suffix_opens_as_image_folder(qtbot, window, tmp_path):
    folder = tmp_path / "images.sumire"
    folder.mkdir()
    source = folder / "image.png"
    Image.new("RGB", (20, 30), "blue").save(source)
    window.open_inputs([str(folder)])
    qtbot.waitUntil(lambda: window.document is not None and window.document.path == source and window.canvas.ready, timeout=10000)
    assert window.model.paths == [source]


def test_external_open_waits_for_inflight_save(qtbot, window, tmp_path, monkeypatch):
    import sumire.window as module
    other = tmp_path / "別フォルダー"
    other.mkdir()
    target = other / "new.png"
    Image.new("RGB", (30, 40), "green").save(target)
    started, release = threading.Event(), threading.Event()
    save = module.save_image
    def delayed(*args, **kwargs):
        started.set()
        assert release.wait(10)
        return save(*args, **kwargs)
    monkeypatch.setattr(module, "save_image", delayed)
    source = window.document.path
    draw(window)
    qtbot.waitUntil(started.is_set, timeout=10000)
    try:
        window.receive_external([str(other)])
        window.process_external()
        assert window.document.path == source and window.external_requests
    finally:
        release.set()
    qtbot.waitUntil(lambda: window.document is not None and window.document.path == target and window.canvas.ready, timeout=15000)
    assert not window.external_requests


def test_external_image_open_does_not_import_its_parent_folder(qtbot, window):
    selected = window.model.paths[1]
    window.watch_timer.stop()
    window.receive_external([str(selected)])
    qtbot.waitUntil(lambda: window.document is not None and window.document.path == selected and window.canvas.ready, timeout=10000)
    for _ in range(3):
        window.poll_folders()
    assert window.model.paths == [selected]
    assert not window.watched_folders


def test_external_open_respects_unsaved_cancel(qtbot, window, tmp_path, monkeypatch):
    window.auto.setChecked(False)
    source = window.document.path
    draw(window)
    qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready, timeout=10000)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    window.receive_external([str(tmp_path / "elsewhere")])
    qtbot.waitUntil(lambda: not window.external_requests)
    assert window.document.path == source and window.document.dirty


def test_project_gui_reopens_original_and_exports_without_rewriting_project(qtbot, window, tmp_path, monkeypatch):
    original = window.document.original.tobytes()
    draw(window)
    wait_saved(qtbot, window)
    edited = window.document.image.tobytes()
    path = tmp_path / "保存した編集.sumire"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
    window.save_project()
    qtbot.waitUntil(lambda: not window.finalizing, timeout=10000)
    assert path.exists()
    digest = file_digest(path)
    window.open_inputs([str(path)])
    qtbot.waitUntil(lambda: not window.loading and window.document is not None and getattr(window.document, "project", False) and window.canvas.ready, timeout=10000)
    assert not window.overwrite.isChecked() and not window.overwrite.isEnabled()
    assert window.document.original.tobytes() == original
    assert window.document.image.tobytes() == edited
    assert window.document.edit_mask.getbbox()
    window.set_mode("erase")
    window.brush.setValue(600)
    qtbot.waitUntil(lambda: window.canvas.ready, timeout=10000)
    draw(window)
    wait_saved(qtbot, window)
    assert window.document.image.tobytes() == original
    assert window.document.edit_mask.getbbox() is None
    assert window.document.output.suffix == ".png"
    assert file_digest(path) == digest
    with Image.open(window.document.output) as image:
        assert image.convert("RGBA").tobytes() == original
    assert read_project(path).image.tobytes() == edited


def test_record_migration_preserves_open_document_and_rename_metadata(qtbot, window):
    source = window.document.path
    draw(window)
    wait_saved(qtbot, window)
    window.set_review_label("accepted")
    document = window.document
    mask = document.edit_mask.tobytes()
    window.switch_record_storage("app")
    qtbot.waitUntil(lambda: not window.finalizing, timeout=10000)
    assert window.document is document
    assert window.document.edit_mask.tobytes() == mask
    assert record_path(source.parent).is_file()
    assert not (source.parent / ".sumire-index.sqlite3").exists()
    assert window.model.labels[source] == "accepted"
    target = source.with_name("renamed.png")
    window.rename_paths({source: target})
    qtbot.waitUntil(lambda: window.batch_job is None and window.document.path == target and window.canvas.ready, timeout=10000)
    assert ReviewLabels(target.parent).get(target) == "accepted"
    assert window.document.edit_mask.tobytes() == mask


def test_named_preset_roundtrip_including_colour_shape_and_expansion(qtbot, window, monkeypatch):
    window.set_mode("fill")
    window.brush.setValue(170)
    window.strength.setValue(65)
    window.color = "#123456"
    window.shape_combo.setCurrentIndex(window.shape_combo.findData("ellipse"))
    window.expansion.setValue(3)
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("半透明の楕円", True))
    window.save_preset()
    window.apply_preset("強いモザイク")
    assert window.mode == "mosaic"
    window.apply_preset("半透明の楕円")
    assert window.mode == "fill" and window.brush.value() == 170 and window.strength.value() == 65
    assert window.color == "#123456" and window.shape_combo.currentData() == "ellipse" and window.expansion.value() == 3
    assert Preferences().data["presets"]["半透明の楕円"]["color"] == "#123456"
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.preset_combo.setCurrentIndex(window.preset_combo.findData("半透明の楕円"))
    window.delete_preset()
    assert "半透明の楕円" not in Preferences().data["presets"]


def test_help_about_and_error_copy_are_accessible(window, monkeypatch, qapp):
    titles = []
    def inspect(dialog):
        titles.append(dialog.windowTitle())
        copy = next((button for button in dialog.findChildren(QPushButton) if button.text() == "詳細をコピー"), None)
        if copy:
            copy.click()
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(QDialog, "exec", inspect)
    window.show_help()
    window.show_about()
    window.error("保存先へ書き込めません。")
    window.show_error_details()
    assert len(titles) == 3 and "Sumīreについて" in titles
    text = qapp.clipboard().text()
    assert f"Sumīre {DISPLAY_VERSION}" in text and "保存先へ書き込めません。" in text


def test_about_shows_the_library_notices_lgpl_asks_for(window, monkeypatch):
    """LGPLv3 4(c): where the app shows copyright notices, Qt's notice and a pointer to the licence texts appear too."""
    shown = []
    monkeypatch.setattr(type(window), "text_dialog", lambda self, title, text, *args, **kwargs: shown.append(text))
    window.show_about()
    text = shown[0]
    assert "© 2026 marc2825" in text and "MIT License" in text
    assert "Copyright (C) The Qt Company Ltd. and other contributors." in text and "GNU LGPL v3" in text
    assert "licenses/Qt" in text and "QT_REPLACEMENT.md" in text
    assert "SIL Open Font License 1.1" in text
