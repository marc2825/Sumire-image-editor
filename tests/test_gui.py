import threading
from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QMessageBox, QPlainTextEdit

from sumire.canvas import Canvas
from sumire.imaging import Document, ImageProblem, Tool, load_image, make_effect
from sumire.export import SaveResult, Verification, file_digest
from sumire.session import Receipts
from sumire.labels import REVIEW_LABELS, ReviewLabels
from sumire.library import LIST_ICON
from sumire.window import Window


@pytest.fixture
def window(qtbot, tmp_path, patterned):
    for name in ["image1.png", "image2.png", "image10.png"]:
        patterned.save(tmp_path / name)
    widget = Window()
    # This fixture owns shutdown. pytest-qt otherwise closes/deletes registered
    # widgets before fixture finalizers, while asynchronous saves may still run.
    with qtbot.waitExposed(widget):
        widget.show()
    widget.open_inputs([str(tmp_path)])
    qtbot.waitUntil(lambda: widget.document is not None and widget.canvas.ready, timeout=10000)
    with qtbot.waitActive(widget):
        widget.activateWindow()
    widget.canvas.setFocus()
    qtbot.waitUntil(lambda: widget.isActiveWindow() and QApplication.focusWidget() is widget.canvas, timeout=5000)
    yield widget
    qtbot.waitUntil(lambda: not widget.finalizing and not widget.saving and not widget.loading and widget.batch_job is None, timeout=15000)
    widget.auto.setChecked(False)
    widget.pending_action = None
    widget.autosave_timer.stop()
    if widget.document:
        widget.document.saved_revision = widget.document.revision
    widget.close()


def draw(widget, start=(35, 45), end=(90, 45)):
    canvas = widget.canvas if isinstance(widget, Window) else widget
    def pos(point):
        return (QPointF(*point) * canvas.scale + canvas.offset).toPoint()
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=pos(start))
    QTest.mouseMove(canvas, pos(end))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=pos(end))


def wait_saved(qtbot, window):
    qtbot.waitUntil(lambda: window.document.saved_revision == window.document.revision and not window.saving and not window.finalizing, timeout=10000)


def move_down(window):
    """Drag the current image one place down in the list."""
    paths, index = window.model.paths, window.index
    window.reorder_selection([str(paths[index])], str(paths[index + 2]) if index + 2 < len(paths) else "")


def poll_watched(qtbot, window):
    window.watch_monitor.changed()
    window.poll_folders()
    qtbot.waitUntil(lambda: window.watch_monitor.job is None, timeout=10000)


@pytest.mark.parametrize("overwrite", [False, True])
def test_autosave_undo_redo_and_arrow_navigation(qtbot, window, overwrite):
    window.overwrite.setChecked(overwrite)
    original = window.document.image.tobytes()
    source = window.document.path.read_bytes()
    draw(window)
    wait_saved(qtbot, window)
    target = window.document.output
    assert target
    if overwrite:
        assert target == window.document.path
    else:
        assert target.parent.name == "Sumīre"
    with Image.open(target) as image:
        assert image.tobytes() == window.document.image.tobytes()
        assert not image.info
    assert (window.document.path.read_bytes() != source) == overwrite
    qtbot.waitUntil(lambda: window.canvas.ready)
    QTest.keyClick(window.canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: window.document.revision == 0)
    wait_saved(qtbot, window)
    assert window.document.image.tobytes() == original
    assert not window.document.edited
    assert "未編集" in window.model.data(window.model.index(0))
    assert window.status.text() == window.ready_hint()
    with Image.open(target) as image:
        assert image.tobytes() == original
    QTest.keyClick(window.canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    qtbot.waitUntil(lambda: window.document.revision == 1)
    wait_saved(qtbot, window)
    assert window.document.image.tobytes() != original
    assert window.document.edited
    QTest.keyClick(window.canvas, Qt.Key.Key_Right)
    qtbot.waitUntil(lambda: window.index == 1 and window.canvas.ready)
    assert not window.document.undo_stack
    assert window.document.image.tobytes() == original
    QTest.keyClick(window.canvas, Qt.Key.Key_Left)
    qtbot.waitUntil(lambda: window.index == 0 and window.canvas.ready)
    assert window.document.undo_stack
    assert window.metadata_state.text() == "メタデータ：無し"


def test_navigation_flushes_debounced_save(qtbot, window):
    draw(window)
    qtbot.waitUntil(lambda: not window.finalizing)
    first = window.document
    window.navigate(1)
    qtbot.waitUntil(lambda: window.index == 1 and window.canvas.ready, timeout=10000)
    assert first.output and first.output.exists()
    assert first.saved_revision == first.revision


@pytest.mark.parametrize("overwrite", [False, True])
def test_save_failure_keeps_image_and_cancels_navigation(qtbot, window, monkeypatch, overwrite):
    import sumire.window as module
    def fail(*args, **kwargs):
        raise ImageProblem("テスト用の保存失敗")
    monkeypatch.setattr(module, "save_image", fail)
    monkeypatch.setattr("sumire.batch_features.save_image", fail)  # whole-list work saves from here
    original = window.document.path.read_bytes()
    window.overwrite.setChecked(overwrite)
    draw(window)
    qtbot.waitUntil(lambda: not window.finalizing)
    window.navigate(1)
    qtbot.waitUntil(lambda: "保存失敗" in window.status.text())
    assert window.index == 0
    assert window.document.undo_stack
    assert window.document.dirty
    assert window.pending_action is None
    assert not window.canvas.locked
    assert window.document.path.read_bytes() == original


@pytest.mark.parametrize("edited", [False, True])
def test_current_metadata_button_preserves_pixels_and_edits(qtbot, window, edited):
    window.overwrite.setChecked(False)
    source = window.document.path
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", "private test prompt")
    load_image(source).save(source, pnginfo=info)
    original = source.read_bytes()
    window.open_inputs([str(source)])
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready, timeout=10000)
    window.auto.setChecked(False)
    assert not window.overwrite.isChecked()
    if edited:
        draw(window)
        qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready)
    expected = window.document.image.tobytes()
    window.metadata_button.trigger()
    wait_saved(qtbot, window)
    assert source.read_bytes() == original
    assert window.document.output != source
    assert window.document.edited == edited
    with Image.open(window.document.output) as clean:
        assert not clean.info
        assert clean.tobytes() == expected


def test_default_overwrite_autosave_undo_and_switch_to_separate_output(qtbot, window):
    source = window.document.path
    original = source.read_bytes()
    pixels = window.document.image.tobytes()
    assert window.overwrite.isChecked()
    assert not window.overwrite_note.isHidden()
    assert source.read_bytes() == original
    assert not window.format_combo.isEnabled() and not window.name.isEnabled()
    assert "上書き" in window.save_next_button.text()
    draw(window)
    wait_saved(qtbot, window)
    assert window.document.output == source
    assert source.read_bytes() != original
    assert window.document.source_digest == file_digest(source)
    window.history(False)
    wait_saved(qtbot, window)
    assert not window.document.edited
    with Image.open(source) as clean:
        assert not clean.info
        assert clean.tobytes() == pixels
    restored = source.read_bytes()
    window.overwrite.setChecked(False)
    window.metadata_button.trigger()
    wait_saved(qtbot, window)
    assert window.document.output != source
    assert window.document.output.parent.name == "Sumīre"
    assert source.read_bytes() == restored


def test_overwrite_metadata_button_uses_source_jpeg_format(qtbot, window):
    source = window.document.path.parent / "photo.jpg"
    exif = Image.Exif()
    exif[315] = "private artist"
    Image.new("RGB", (40, 30), "red").save(source, exif=exif)
    window.open_inputs([str(source)])
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready, timeout=10000)
    assert window.format_combo.currentData() == "PNG"
    window.overwrite.setChecked(True)
    window.metadata_button.trigger()
    wait_saved(qtbot, window)
    assert window.document.output == source
    with Image.open(source) as image:
        assert image.format == "JPEG"
        assert not image.getexif()
        assert image.size == (40, 30)


def test_overwrite_rejects_external_source_changes(qtbot, window):
    source = window.document.path
    window.overwrite.setChecked(True)
    Image.new("RGB", window.document.image.size, "green").save(source)
    external = source.read_bytes()
    window.metadata_button.trigger()
    qtbot.waitUntil(lambda: not window.saving and "元画像が変更" in window.status.text(), timeout=10000)
    assert source.read_bytes() == external
    assert window.document.saved_revision is None


def test_overwrite_batch_removes_metadata_and_reprocesses_saved_images(qtbot, window, monkeypatch, batch_approved):
    import sumire.window as module
    original = module.save_image
    calls = []
    def track(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(result.path)
        return result
    monkeypatch.setattr(module, "save_image", track)
    monkeypatch.setattr("sumire.batch_features.save_image", track)  # whole-list work saves from here
    folder = window.document.path.parent
    paths = list(window.model.paths)
    for path in paths:
        info = PngImagePlugin.PngInfo()
        info.add_itxt("workflow", "private test workflow")
        load_image(path).save(path, pnginfo=info)
    window.open_inputs([str(folder)])
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready, timeout=10000)
    assert window.overwrite.isChecked()
    window.start_batch()
    qtbot.waitUntil(lambda: window.batch_job is None and "一括処理完了" in window.status.text(), timeout=10000)
    assert "保存 3" in window.status.text()
    assert calls == paths
    for path in paths:
        with Image.open(path) as clean:
            assert not clean.info
    assert not list(window.output_folder.glob("*.png"))
    window.open_inputs([str(folder)])
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready, timeout=10000)
    assert window.document.saved_revision == 0
    assert window.document.output == window.document.path
    window.start_batch()
    qtbot.waitUntil(lambda: window.batch_job is None and "一括処理完了" in window.status.text(), timeout=10000)
    assert "保存 3 / 失敗 0" in window.status.text()
    assert calls == paths * 2


@pytest.mark.parametrize("overwrite", [False, True])
@pytest.mark.parametrize("batch", [False, True])
def test_novelai_cleanup_of_old_saved_receipts(qtbot, window, patterned, encode_stealth, decode_stealth, overwrite, batch, batch_approved):
    window.overwrite.setChecked(overwrite)
    source = window.document.path
    if overwrite:
        target = source
    else:
        target = window.output_folder / source.name
        target.parent.mkdir(exist_ok=True)
    edited = patterned.copy()
    edited.paste((0, 0, 0, 255), (20, 20, 100, 80))
    encode_stealth(edited).save(target)
    # Simulate an older version's successful receipt: chunks are clean, but
    # the prompt is still independently recoverable from the alpha carrier.
    with Image.open(target) as old:
        assert not old.info
        assert decode_stealth(old) is not None
    digest = file_digest(target)
    receipt = Receipts(target.parent)
    receipt.record(source, SaveResult(target, Verification("PNG", edited.size, ("IHDR", "IDAT", "IEND")), digest))
    window.open_inputs([str(source)])
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready, timeout=10000)
    assert window.document.saved_revision is None
    assert "保存済み" not in window.save_state.text()
    assert window.document.image.convert("RGB").tobytes() == edited.convert("RGB").tobytes()
    assert file_digest(target) == digest  # Opening an image does not save it.
    if batch:
        window.batch_button.trigger()
        qtbot.waitUntil(lambda: window.batch_job is None and "一括処理完了" in window.status.text(), timeout=10000)
        assert "保存 1 / 失敗 0" in window.status.text()
    else:
        window.metadata_button.trigger()
        wait_saved(qtbot, window)
    assert window.document.output == target
    with Image.open(target) as clean:
        assert not clean.info
        assert decode_stealth(clean) is None
        assert decode_stealth(clean, "rgb") is None
        assert clean.getchannel("A").getextrema() == (255, 255)
        assert clean.convert("RGB").tobytes() == edited.convert("RGB").tobytes()


def test_overwrite_bmp_is_rejected_without_changing_file(qtbot, window):
    source = window.document.path.parent / "bitmap.bmp"
    Image.new("RGB", (40, 30), "white").save(source)
    before = source.read_bytes()
    window.open_inputs([str(source)])
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready, timeout=10000)
    window.overwrite.setChecked(True)
    window.metadata_button.trigger()
    assert "上書きできるのはPNG / JPEG / WebP" in window.status.text() and "形式を変換" in window.status.text()
    assert source.read_bytes() == before


def test_edits_during_save_flush_latest_before_navigation(qtbot, window, monkeypatch):
    import sumire.window as module
    original = module.save_image
    started, release = threading.Event(), threading.Event()
    def slow(*args, **kwargs):
        started.set()
        if not release.wait(5):
            raise ImageProblem("テスト待機がタイムアウト")
        return original(*args, **kwargs)
    monkeypatch.setattr(module, "save_image", slow)
    monkeypatch.setattr("sumire.batch_features.save_image", slow)  # whole-list work saves from here
    try:
        draw(window, (30, 30), (50, 30))
        qtbot.waitUntil(lambda: started.is_set() and window.canvas.ready, timeout=10000)
        draw(window, (90, 90), (120, 90))
        qtbot.waitUntil(lambda: not window.finalizing)
        first = window.document
        window.navigate(1)
        assert window.canvas.locked
        assert window.index == 0
    finally:
        release.set()
    qtbot.waitUntil(lambda: window.index == 1 and window.canvas.ready, timeout=10000)
    assert first.saved_revision == 2
    with Image.open(first.output) as output:
        assert output.tobytes() == first.image.tobytes()


def test_enter_cleans_unedited_image_and_moves(qtbot, window):
    first = window.document
    QTest.keyClick(window.canvas, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: window.index == 1 and window.canvas.ready, timeout=10000)
    assert first.saved_revision == 0
    assert first.output.exists()
    assert not window.document.undo_stack


def test_manual_mode_cancel_retains_edits(qtbot, window, monkeypatch):
    window.auto.setChecked(False)
    draw(window)
    qtbot.waitUntil(lambda: not window.finalizing)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)
    window.navigate(1)
    assert window.index == 0
    assert window.document.dirty
    assert not (window.output_folder / "image1.png").exists()


def test_escape_cancels_active_stroke(qtbot, window):
    image = window.document.image.tobytes()
    point = (QPointF(40, 40) * window.canvas.scale + window.canvas.offset).toPoint()
    QTest.mousePress(window.canvas, Qt.MouseButton.LeftButton, pos=point)
    assert window.canvas.stroke
    QTest.keyClick(window.canvas, Qt.Key.Key_Escape)
    QTest.mouseRelease(window.canvas, Qt.MouseButton.LeftButton, pos=point)
    assert window.document.image.tobytes() == image
    assert not window.document.undo_stack
    assert not window.canvas.locked
    assert window.shape_combo.isEnabled()


def test_cancel_next_stroke_still_autosaves_previous_edit(qtbot, window):
    window.autosave_timer.setInterval(700)
    draw(window)
    qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready)
    first_revision = window.document.revision
    point = (QPointF(120, 80) * window.canvas.scale + window.canvas.offset).toPoint()
    QTest.mousePress(window.canvas, Qt.MouseButton.LeftButton, pos=point)
    qtbot.waitUntil(lambda: not window.autosave_timer.isActive(), timeout=3000)
    assert window.canvas.stroke is not None
    QTest.keyClick(window.canvas, Qt.Key.Key_Escape)
    QTest.mouseRelease(window.canvas, Qt.MouseButton.LeftButton, pos=point)
    wait_saved(qtbot, window)
    assert window.document.revision == first_revision == 1
    assert window.document.output.exists()


@pytest.mark.parametrize("overwrite", [False, True])
def test_batch_reprocesses_saved_edits_without_duplicates(qtbot, window, monkeypatch, overwrite, batch_approved):
    import sumire.window as module
    window.overwrite.setChecked(overwrite)
    paths = list(window.model.paths)
    sources = {path: path.read_bytes() for path in paths}
    expected = {path: load_image(path).tobytes() for path in paths}
    # Save two edited images, then evict the first from the decoded cache.
    for index in range(2):
        draw(window)
        wait_saved(qtbot, window)
        expected[window.document.path] = window.document.image.tobytes()
        window.navigate(1)
        qtbot.waitUntil(lambda: window.index == index + 1 and window.canvas.ready, timeout=10000)
    assert paths[0] not in window.documents
    assert paths[1] in window.documents
    original = module.save_image
    calls = []
    def track(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(result.path)
        return result
    monkeypatch.setattr(module, "save_image", track)
    monkeypatch.setattr("sumire.batch_features.save_image", track)  # whole-list work saves from here
    window.start_batch()
    qtbot.waitUntil(lambda: window.batch_job is None and "一括処理完了" in window.status.text(), timeout=15000)
    assert "保存 3 / 失敗 0" in window.status.text()
    outputs = paths if overwrite else sorted(window.output_folder.glob("*.png"))
    assert len(outputs) == 3
    assert len(calls) == 3
    for path in paths:
        output = path if overwrite else window.output_folder / path.name
        with Image.open(output) as clean:
            assert not clean.info
            assert clean.tobytes() == expected[path]
        if not overwrite:
            assert path.read_bytes() == sources[path]
    window.start_batch()
    qtbot.waitUntil(lambda: window.batch_job is None and "一括処理完了" in window.status.text(), timeout=15000)
    assert "保存 3 / 失敗 0" in window.status.text()
    assert calls[:3] == calls[3:]
    assert (paths if overwrite else sorted(window.output_folder.glob("*.png"))) == outputs
    for path in paths:
        output = path if overwrite else window.output_folder / path.name
        assert load_image(output).tobytes() == expected[path]


def test_saved_receipt_restores_pixels_without_sharing_history(qtbot, window):
    draw(window)
    wait_saved(qtbot, window)
    saved = window.document.image.tobytes()
    source_folder = window.document.path.parent
    window.open_inputs([str(source_folder)])
    qtbot.waitUntil(lambda: not window.loading and window.document is not None and window.canvas.ready, timeout=10000)
    assert window.document.saved_revision == 0
    assert window.document.image.tobytes() == saved
    assert not window.document.undo_stack
    assert "保存済み" in window.save_state.text()


def test_zoom_does_not_change_brush_coordinates(qtbot, patterned):
    results = []
    for scale in [0.5, 1, 2]:
        canvas = Canvas()
        qtbot.addWidget(canvas)
        canvas.resize(600, 400)
        canvas.show()
        document = Document(Path("image.png"), patterned)
        canvas.set_document(document)
        canvas.scale = scale
        canvas.offset = QPointF(25, 25)
        canvas.tool = Tool("fill", 12, color="#000000", expansion=1)
        canvas.effect = make_effect(document.image, canvas.tool)
        canvas.ready = True
        canvas.strokeFinished.connect(lambda stroke: stroke.finish())
        draw(canvas, (30, 40), (90, 40))
        results.append(document.image.tobytes())
        assert document.image.getpixel((60, 40)) == (0, 0, 0, 255)
        assert document.image.getpixel((60, 20)) == patterned.getpixel((60, 20))
        canvas.close()
    assert results[0] == results[1] == results[2]


def test_mode_strengths_and_fill_opacity_autosave(qtbot, window):
    window.strength.setValue(32)
    window.set_mode("blur")
    assert "ぼかしの強さ" in window.strength_label.text()
    window.strength.setValue(8)
    window.set_mode("fill")
    assert window.strength.isEnabled() and window.strength.isVisible()
    assert window.strength.value() == 100
    window.strength.setValue(50)
    assert window.strength_box.value() == 50 and window.strength_box.suffix() == "%"
    window.set_mode("mosaic")
    assert window.strength.value() == 32
    window.set_mode("blur")
    assert window.strength.value() == 8
    window.set_mode("fill")
    assert window.strength.value() == 50
    qtbot.waitUntil(lambda: window.canvas.ready)
    before = window.document.image.getpixel((60, 45))
    draw(window)
    wait_saved(qtbot, window)
    after = window.document.image.getpixel((60, 45))
    assert all(abs(after[i] - before[i] / 2) <= 1 for i in range(3))
    with Image.open(window.document.output) as saved:
        assert saved.getpixel((60, 45)) == after
    window.history(False)
    wait_saved(qtbot, window)
    assert not window.document.edited
    assert "未編集" in window.model.data(window.model.index(window.index))
    qtbot.waitUntil(lambda: window.canvas.ready)
    window.strength.setValue(0)
    qtbot.waitUntil(lambda: window.canvas.ready)
    revision = window.document.revision
    draw(window)
    qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready)
    assert window.document.revision == revision
    assert "確定中" not in window.status.text()
    assert "未編集" in window.model.data(window.model.index(window.index))
    window.navigate(1)
    qtbot.waitUntil(lambda: window.index == 1 and window.canvas.ready)
    window.navigate(-1)
    qtbot.waitUntil(lambda: window.index == 0 and window.canvas.ready)
    assert "未編集" in window.model.data(window.model.index(0))


def test_fast_effect_finishes_before_pool_start_returns(qtbot, window, monkeypatch):
    original_start = window.pool.start

    def finish_immediately(job):
        original_start(job)
        assert window.pool.waitForDone(5000)

    monkeypatch.setattr(window.pool, "start", finish_immediately)
    qtbot.waitUntil(lambda: window.effect_job is None)
    for strength in (12, 26):
        window.strength.setValue(strength)
        window.effect_timer.stop()
        window.prepare_effect()
        qtbot.waitUntil(lambda: window.canvas.ready and window.effect_job is None)
        assert not window.effect_restart


def test_natural_sort_and_thumbnail_bounds(window):
    assert [p.name for p in window.model.paths] == ["image1.png", "image2.png", "image10.png"]
    assert window.model.pool.maxThreadCount() == 1
    assert len(window.model.cache) <= 160


def test_sort_and_manual_move_keep_current_image_and_history(qtbot, window):
    import os
    draw(window)
    wait_saved(qtbot, window)
    document = window.document
    pixels = document.image.tobytes()
    window.sort_combo.setCurrentIndex(window.sort_combo.findData("name_desc"))
    assert [path.name for path in window.model.paths] == ["image10.png", "image2.png", "image1.png"]
    assert window.document is document and window.index == 2
    window.reorder_selection([str(document.path)], str(window.model.paths[1]))
    assert window.sort_combo.currentData() == "manual"
    assert window.index == 1 and window.model.paths[1] == document.path
    assert window.document.image.tobytes() == pixels and window.document.undo_stack
    for path, timestamp in zip(window.model.paths, [300, 100, 200]):
        os.utime(path, ns=(timestamp, timestamp))
    window.sort_combo.setCurrentIndex(window.sort_combo.findData("date_asc"))
    assert window.document is document and window.index == 0
    assert window.list.currentIndex().row() == window.index


@pytest.mark.parametrize("overwrite", [False, True])
def test_single_rename_keeps_saved_edits_receipts_and_undo(qtbot, window, monkeypatch, overwrite):
    window.overwrite.setChecked(overwrite)
    draw(window)
    wait_saved(qtbot, window)
    old = window.document.path
    target = old.with_name("新しい名前.png")
    before = old.read_bytes()
    window.rename_button.trigger()
    window.file_label.editor.setText("新しい名前")
    QTest.keyClick(window.file_label.editor, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: window.batch_job is None and window.document.path == target and window.canvas.ready, timeout=10000)
    assert not old.exists() and target.read_bytes() == before
    assert window.document.undo_stack
    receipt = window.source_index(target) if overwrite else window.receipts
    assert receipt.get(target, overwrite=overwrite)
    assert window.document.output == (target if overwrite else window.output_folder / old.name)
    window.history(False)
    wait_saved(qtbot, window)
    assert not window.document.edited and not old.exists()
    window.open_inputs([str(target)])
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready, timeout=10000)
    assert window.document.saved_revision == 0


def test_bulk_numbering_uses_manual_order_and_keeps_pixels(qtbot, window, monkeypatch):
    draw(window)
    wait_saved(qtbot, window)
    window.reorder_selection([str(window.document.path)], str(window.model.paths[2]))
    before = {path: path.read_bytes() for path in window.model.paths}
    old_order = list(window.model.paths)
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    window.number_button.trigger()
    qtbot.waitUntil(lambda: window.batch_job is None and window.canvas.ready and window.model.paths[0].stem == "00", timeout=10000)
    assert [path.name for path in window.model.paths] == ["00.png", "01.png", "02.png"]
    assert window.index == 1 and window.document.path.name == "01.png"
    for old, new in zip(old_order, window.model.paths):
        assert new.read_bytes() == before[old]
    assert window.batch_progress.value() == window.batch_progress.maximum() == 3
    window.history(False)
    wait_saved(qtbot, window)
    assert not window.document.edited


def test_batch_progress_reports_failures_and_completion(qtbot, window, monkeypatch, batch_approved):
    import sumire.window as module
    original = module.save_image
    events = []
    window.batch_progress.valueChanged.connect(events.append)
    def fail_second(*args, **kwargs):
        if kwargs["source"].name == "image2.png":
            raise ImageProblem("synthetic failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(module, "save_image", fail_second)
    monkeypatch.setattr("sumire.batch_features.save_image", fail_second)  # whole-list work saves from here
    window.start_batch()
    assert window.batch_progress.isVisible()
    qtbot.waitUntil(lambda: window.batch_job is None and "一括処理完了" in window.status.text(), timeout=10000)
    assert "保存 2 / 失敗 1" in window.status.text()
    assert events == [0, 1, 2, 3]
    assert window.batch_progress.value() == window.batch_progress.maximum() == 3


def test_list_keyboard_selection_opens_matching_image(qtbot, window):
    window.list.setFocus()
    QTest.keyClick(window.list, Qt.Key.Key_Down)
    qtbot.waitUntil(lambda: window.index == 1 and window.canvas.ready, timeout=10000)
    assert window.list.currentIndex().row() == window.index
    assert window.document.path.name == "image2.png"


@pytest.mark.parametrize("overwrite", [False, True])
def test_batch_cancel_keeps_completed_receipts_and_can_rerun_all(qtbot, window, monkeypatch, overwrite, batch_approved):
    import sumire.window as module
    window.overwrite.setChecked(overwrite)
    original = module.save_image
    count = 0
    def cancel_after_first(*args, **kwargs):
        nonlocal count
        result = original(*args, **kwargs)
        count += 1
        if count == 1:
            kwargs["cancel"].set()
        return result
    monkeypatch.setattr(module, "save_image", cancel_after_first)
    monkeypatch.setattr("sumire.batch_features.save_image", cancel_after_first)  # whole-list work saves from here
    window.start_batch()
    qtbot.waitUntil(lambda: window.batch_job is None and "一括処理を中止" in window.status.text(), timeout=10000)
    index = window.source_index(window.document.path) if overwrite else window.receipts
    assert sum(index.get(path, overwrite=overwrite) is not None for path in window.model.paths) == 1
    assert window.document.saved_revision == 0
    assert window.document.output.exists()
    assert window.batch_progress.value() == 1
    assert window.batch_progress.maximum() == 3
    window.start_batch()
    qtbot.waitUntil(lambda: window.batch_job is None and "一括処理完了" in window.status.text(), timeout=10000)
    assert "保存 3 / 失敗 0" in window.status.text()
    assert count == 4
    index = window.source_index(window.document.path) if overwrite else window.receipts
    assert sum(index.get(path, overwrite=overwrite) is not None for path in window.model.paths) == 3
    if not overwrite:
        assert len(list(window.output_folder.glob("*.png"))) == 3


def test_switching_modes_during_slow_effect_coalesces_snapshots(qtbot, window, monkeypatch):
    import sumire.window as module
    original = module.make_effect
    started, release = threading.Event(), threading.Event()
    calls = []
    def slow(image, tool):
        calls.append(tool.strength)
        started.set()
        release.wait(5)
        return original(image, tool)
    qtbot.waitUntil(lambda: window.effect_job is None)
    monkeypatch.setattr(module, "make_effect", slow)
    window.strength.setValue(22)
    qtbot.waitUntil(started.is_set, timeout=5000)
    try:
        for strength in [23, 24, 25]:
            window.strength.setValue(strength)
            window.prepare_effect()
        assert len(calls) == 1
    finally:
        release.set()
    qtbot.waitUntil(lambda: window.canvas.ready and window.effect_job is None, timeout=10000)
    assert calls[-1] == 25
    assert len(calls) == 2


@pytest.mark.parametrize("overwrite", [False, True])
def test_review_labels_persist_through_save_sort_rename_and_reopen(qtbot, window, overwrite, batch_approved):
    window.overwrite.setChecked(overwrite)
    source = window.document.path
    before = source.read_bytes()
    for label in ("rejected", "pending", "accepted"):  # ends on 採用
        text = REVIEW_LABELS[label]
        QTest.mouseClick(window.label_buttons[label], Qt.MouseButton.LeftButton)
        assert window.model.labels[source] == label
        assert text in window.model.data(window.model.index(window.index))
        assert window.label_buttons[label].isChecked()
        assert sum(button.isChecked() for button in window.label_buttons.values()) == 1
        assert ReviewLabels(source.parent).get(source) == label
    assert source.read_bytes() == before and not window.document.dirty
    window.start_batch()
    qtbot.waitUntil(lambda: window.batch_job is None and window.canvas.ready, timeout=10000)
    assert ReviewLabels(source.parent).get(source) == "accepted"
    move_down(window)
    assert "採用" in window.model.data(window.model.index(window.index))
    target = source.with_name("選別済み.png")
    window.rename_paths({source: target})
    qtbot.waitUntil(lambda: window.batch_job is None and window.document.path == target and window.canvas.ready, timeout=10000)
    assert ReviewLabels(target.parent).get(target) == "accepted"
    assert ReviewLabels(target.parent).get(source) is None
    window.open_inputs([str(target)])
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready and window.document.path == target, timeout=10000)
    assert window.model.labels[target] == "accepted"
    # Pressing the same label again keeps it; 「ラベルを解除」 removes it.
    QTest.mouseClick(window.label_buttons["accepted"], Qt.MouseButton.LeftButton)
    assert window.model.labels[target] == "accepted" and window.label_buttons["accepted"].isChecked()
    window.set_review_label(None)
    assert target not in window.model.labels and ReviewLabels(target.parent).get(target) is None


def test_label_shortcuts_and_failed_write_restore_controls(qtbot, window, monkeypatch):
    source = window.document.path
    QTest.keyClick(window.canvas, Qt.Key.Key_2)
    assert window.model.labels[source] == "pending"
    QTest.keyClick(window.canvas, Qt.Key.Key_0, Qt.KeyboardModifier.AltModifier)
    assert source not in window.model.labels
    window.set_review_label("pending")
    def fail(*args):
        raise OSError("synthetic denied write")
    monkeypatch.setattr(ReviewLabels, "set", fail)
    QTest.mouseClick(window.label_buttons["accepted"], Qt.MouseButton.LeftButton)
    assert window.model.labels[source] == "pending"
    assert window.label_buttons["pending"].isChecked()
    assert not window.label_buttons["accepted"].isChecked()
    assert "ラベルを保存できません" in window.status.text()


def test_novelai_opens_with_unsaved_edits_and_keeps_original(qtbot, window, monkeypatch):
    from sumire.novelai import NOVELAI_URL
    from PySide6.QtGui import QDesktopServices
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True)
    window.auto.setChecked(False)
    source = window.document.path
    before = source.read_bytes()
    draw(window)
    qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready)
    pixels = window.document.image.tobytes()
    assert window.share_button.accessibleName() == "共有" and window.share_button.menu() is window.share_menu
    window.share_actions["novelai"].trigger()
    qtbot.waitUntil(lambda: window.novelai_dialog is not None, timeout=10000)
    dialog = window.novelai_dialog
    try:
        assert opened == [NOVELAI_URL]
        with Image.open(dialog.prepared.path) as image:
            assert image.tobytes() == pixels and not image.info
        assert source.read_bytes() == before
        assert window.document.dirty and window.document.undo_stack
        assert QApplication.clipboard().mimeData().hasImage()
    finally:
        dialog.close()
        QApplication.clipboard().clear()
    assert window.novelai_dialog is None
    assert not dialog.prepared.path.exists()


def test_novelai_preparation_failure_does_not_open_browser(qtbot, window, monkeypatch):
    import sumire.window as module
    from PySide6.QtGui import QDesktopServices
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    def fail(*args):
        raise ImageProblem("画像準備のテストエラー")
    monkeypatch.setattr(module, "prepare_image", fail)
    window.share_actions["novelai"].trigger()
    qtbot.waitUntil(lambda: window.novelai_job is None, timeout=10000)
    assert opened == [] and window.novelai_dialog is None
    assert window.share_button.isEnabled()
    assert "テストエラー" in window.status.text()


def test_cancel_novelai_preparation_resumes_autosave_and_brush(qtbot, window, monkeypatch):
    import sumire.window as module
    from sumire.export import check_cancel
    from PySide6.QtGui import QDesktopServices
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    window.auto.setChecked(False)
    draw(window)
    qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready)
    started, release = threading.Event(), threading.Event()
    def slow(*args):
        started.set()
        release.wait(5)
        check_cancel(args[2])
        raise AssertionError("Preparation should have been cancelled")
    monkeypatch.setattr(module, "prepare_image", slow)
    window.auto.setChecked(True)
    # Simulate a brush setting whose debounce expires while preparing the PNG.
    window.strength.setValue(24)
    window.open_novelai()
    try:
        qtbot.waitUntil(started.is_set, timeout=5000)
        assert not window.share_button.isEnabled() and not window.share_actions["novelai"].isEnabled()
        assert not window.label_buttons["accepted"].isEnabled()
        window.navigate(1)
        assert window.index == 0
        qtbot.waitUntil(lambda: not window.autosave_timer.isActive() and not window.effect_timer.isActive())
        window.cancel_work()
    finally:
        release.set()
    qtbot.waitUntil(lambda: window.novelai_job is None, timeout=10000)
    wait_saved(qtbot, window)
    qtbot.waitUntil(lambda: window.canvas.ready, timeout=10000)
    assert opened == [] and window.novelai_dialog is None
    assert window.share_button.isEnabled()


def test_filter_counts_navigation_and_auto_advance(qtbot, window):
    first, second, third = window.model.paths
    window.set_review_label("accepted")
    window.filter_combo.setCurrentIndex(window.filter_combo.findData("accepted"))
    assert window.visible_paths() == [first]
    assert not window.next.isEnabled() and not window.previous.isEnabled()
    window.filter_combo.setCurrentIndex(window.filter_combo.findData("unlabelled"))
    qtbot.waitUntil(lambda: window.document is not None and window.document.path == second and window.canvas.ready)
    assert window.visible_paths() == [second, third]
    window.auto_advance.setChecked(True)
    window.set_review_label("rejected")
    qtbot.waitUntil(lambda: window.document is not None and window.document.path == third and window.canvas.ready)
    window.set_review_label("pending")
    qtbot.waitUntil(lambda: window.document is None)
    assert window.proxy.rowCount() == 0
    assert "未判定 0" in window.review_summary.text()
    assert "採用 1" in window.review_summary.text()
    window.filter_combo.setCurrentIndex(window.filter_combo.findData("all"))
    qtbot.waitUntil(lambda: window.document is not None and window.canvas.ready)


def test_multi_selection_labels_and_save_only_selected(qtbot, window, monkeypatch):
    import sumire.window as module
    from PySide6.QtCore import QItemSelectionModel
    paths = list(window.model.paths)
    selection = window.list.selectionModel()
    selection.select(window.proxy.index(2, 0), QItemSelectionModel.SelectionFlag.Select)
    window.set_review_label("pending")
    assert set(window.model.labels) == {paths[0], paths[2]}
    calls = []
    original = module.save_image
    def record(*args, **kwargs):
        calls.append(kwargs["source"])
        return original(*args, **kwargs)
    monkeypatch.setattr(module, "save_image", record)
    monkeypatch.setattr("sumire.batch_features.save_image", record)  # whole-list work saves from here
    window.save_selected()
    qtbot.waitUntil(lambda: window.batch_job is None and window.canvas.ready, timeout=10000)
    assert calls == [paths[0], paths[2]]
    assert not window.source_index(paths[1]).get(paths[1])


def test_grid_and_drag_reordering_preserve_group_and_allow_undo(window):
    paths = list(window.model.paths)
    window.view_combo.setCurrentIndex(1)
    window.thumbnail_size.setValue(180)
    assert window.model.grid_size == 180
    assert window.list.iconSize().width() == 180
    window.reorder_selection([str(paths[0]), str(paths[2])], str(paths[1]))
    assert window.model.paths == [paths[0], paths[2], paths[1]]
    assert window.selected_paths() == [paths[0], paths[2]]
    window.undo_organization()
    assert window.model.paths == paths
    window.view_combo.setCurrentIndex(0)
    assert window.list.iconSize() == LIST_ICON


def test_accepted_export_uses_unsaved_edits_without_replacing_sources(qtbot, window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    window.auto.setChecked(False)
    source = window.document.path
    originals = {path: path.read_bytes() for path in window.model.paths}
    window.set_review_label("accepted")
    draw(window)
    qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready)
    expected = window.document.image.tobytes()
    destination = tmp_path / "accepted-output"
    destination.mkdir()
    def choose(self, dialog, accepted=None):
        dialog.move.setChecked(False)  # copy: the edited image, without metadata
        dialog.chooser.chosen = destination
        dialog.chooser.elsewhere.setChecked(True)
        dialog.renumber.setChecked(False)
        return True
    monkeypatch.setattr(type(window), "confirm_dialog", choose)
    window.export_labels()
    qtbot.waitUntil(lambda: window.batch_job is None and window.canvas.ready, timeout=10000)
    assert list(destination.glob("*.png")) == [destination / source.name]
    with Image.open(destination / source.name) as image:
        assert image.tobytes() == expected and not image.info
    assert window.document.dirty and window.document.output is None
    assert {path: path.read_bytes() for path in window.model.paths} == originals


def test_failure_reasons_are_shown_after_the_batch(qtbot, window, monkeypatch, batch_approved):
    import sumire.window as module
    original = module.save_image
    calls = []
    fail_once = True
    def save(*args, **kwargs):
        nonlocal fail_once
        source = kwargs["source"]
        calls.append(source)
        if source.name == "image2.png" and fail_once:
            fail_once = False
            raise ImageProblem("書き込み先のテストエラー")
        return original(*args, **kwargs)
    monkeypatch.setattr(module, "save_image", save)
    monkeypatch.setattr("sumire.batch_features.save_image", save)  # whole-list work saves from here
    window.start_batch()
    qtbot.waitUntil(lambda: window.batch_job is None and window.canvas.ready, timeout=10000)
    assert window.batch_failures == {window.model.paths[1]: "書き込み先のテストエラー"}
    report = window.report_window
    assert report.windowTitle() == "保存できなかった画像" and report.isVisible()
    assert "書き込み先のテストエラー" in report.findChild(QPlainTextEdit).toPlainText()
    report.close()
    assert calls == window.model.paths


def test_memo_rename_and_organization_undo(qtbot, window, monkeypatch):
    source = window.document.path
    target = source.with_name("renamed.png")
    window.set_review_label("pending")
    monkeypatch.setattr(QInputDialog, "getMultiLineText", lambda *args: ("手を修正", True))
    window.edit_note()
    assert window.label_index(source).note(source) == "手を修正"
    window.rename_paths({source: target})
    qtbot.waitUntil(lambda: window.batch_job is None and window.document.path == target and window.canvas.ready, timeout=10000)
    assert window.label_index(target).note(target) == "手を修正"
    window.undo_organization()
    qtbot.waitUntil(lambda: window.batch_job is None and window.document.path == source and window.canvas.ready, timeout=10000)
    assert source.exists() and not target.exists()
    window.undo_organization()
    assert window.label_index(source).note(source) == ""
    window.undo_organization()
    assert source not in window.model.labels


def test_workspace_restores_manual_order_filter_current_and_tool_settings(qtbot, window):
    paths = list(window.model.paths)
    window.set_review_label("pending")
    window.navigate(1)
    qtbot.waitUntil(lambda: window.index == 1 and window.canvas.ready)
    window.set_review_label("pending")
    move_down(window)
    window.filter_combo.setCurrentIndex(window.filter_combo.findData("pending"))
    window.auto.setChecked(False)
    window.overwrite.setChecked(False)
    window.set_mode("fill")
    window.strength.setValue(37)
    window.brush.setValue(111)
    window.auto_advance.setChecked(True)
    window.view_combo.setCurrentIndex(1)
    window.thumbnail_size.setValue(160)
    window.watch_action.setChecked(False)
    window.remember_workspace()
    originals = {path: path.read_bytes() for path in paths}
    reopened = Window()
    qtbot.addWidget(reopened)
    reopened.show()
    reopened.resume_workspace()
    qtbot.waitUntil(lambda: reopened.document is not None and reopened.canvas.ready, timeout=10000)
    assert reopened.document.path == paths[1]
    assert reopened.model.paths == [paths[0], paths[2], paths[1]]
    assert reopened.visible_paths() == [paths[0], paths[1]]
    assert not reopened.auto.isChecked() and not reopened.overwrite.isChecked()
    assert reopened.mode == "fill" and reopened.strength.value() == 37 and reopened.brush.value() == 111
    assert reopened.auto_advance.isChecked() and reopened.model.grid_size == 160
    assert not reopened.watch_action.isChecked()
    assert {path: path.read_bytes() for path in paths} == originals
    reopened.close()


def test_folder_monitor_waits_for_stable_file_and_keeps_current(qtbot, window, tmp_path, patterned):
    window.watch_timer.stop()
    current = window.document
    path = tmp_path / "new.png"
    path.touch()
    poll_watched(qtbot, window)
    assert path not in window.model.rows
    patterned.save(path)
    poll_watched(qtbot, window)
    assert path not in window.model.rows
    poll_watched(qtbot, window)
    assert path in window.model.rows and len(window.model.paths) == 4
    assert window.document is current
    poll_watched(qtbot, window)
    assert len(window.model.paths) == 4


@pytest.mark.parametrize("count", [1, 2])
def test_open_files_keeps_only_selected_images_with_monitoring_enabled(qtbot, window, tmp_path, patterned, monkeypatch, count):
    from PySide6.QtWidgets import QFileDialog
    window.watch_timer.stop()
    window.watch_action.setChecked(True)
    selected = window.model.paths[:count]
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *_args: ([str(path) for path in selected], ""))
    window.open_files()
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready, timeout=10000)
    assert window.model.paths == selected
    assert not window.watched_folders
    added = tmp_path / "new-sibling.png"
    patterned.save(added)
    for _ in range(3):
        window.poll_folders()
    assert window.model.paths == selected
    assert window.document.path == selected[0]


def test_resuming_selected_image_does_not_import_siblings(qtbot, window):
    window.watch_timer.stop()
    selected, sibling = window.model.paths[:2]
    window.open_inputs([str(selected)])
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready, timeout=10000)
    window.remember_workspace()
    # Older versions could persist extra images added by parent-folder watching.
    data = dict(window.preferences.data)
    workspace = data["workspaces"][window.workspace_key([str(selected)])]
    workspace.update(sort="manual", order=[str(selected), str(sibling)])
    window.preferences.save(data)
    reopened = Window()
    qtbot.addWidget(reopened)
    reopened.show()
    reopened.watch_timer.stop()
    reopened.resume_workspace()
    qtbot.waitUntil(lambda: reopened.document is not None and reopened.canvas.ready, timeout=10000)
    for _ in range(3):
        reopened.poll_folders()
    assert reopened.model.paths == [selected]
    assert not reopened.watched_folders
    reopened.close()


def test_mixed_inputs_only_monitor_explicit_folders(qtbot, window, tmp_path, patterned):
    window.watch_timer.stop()
    selected = window.model.paths[0]
    folder = tmp_path / "explicit-folder"
    folder.mkdir()
    included = folder / "included.png"
    patterned.save(included)
    window.open_inputs([str(selected), str(folder)])
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready, timeout=10000)
    assert set(window.model.paths) == {selected, included}
    assert window.watched_folders == {folder}
    excluded = tmp_path / "unselected-sibling.png"
    monitored = folder / "new-image.png"
    patterned.save(excluded)
    patterned.save(monitored)
    for _ in range(3):
        poll_watched(qtbot, window)
    assert set(window.model.paths) == {selected, included, monitored}


def test_duplicate_analysis_reports_results_without_modifying_images(qtbot, window, monkeypatch):
    result = []
    originals = {path: path.read_bytes() for path in window.model.paths}
    monkeypatch.setattr(window, "show_duplicate_groups", lambda *args: result.append(args))
    window.analyze_duplicates()
    qtbot.waitUntil(lambda: window.batch_job is None and bool(result), timeout=10000)
    assert len(result[0][0]) == 1 and len(result[0][0][0]) == 3
    assert not result[0][1]
    assert {path: path.read_bytes() for path in window.model.paths} == originals


def test_selected_numbering_changes_only_selected_and_keeps_labels(qtbot, window, monkeypatch):
    paths = list(window.model.paths)
    window.select_paths([paths[0], paths[2]])
    window.set_review_label("accepted")
    monkeypatch.setattr(QDialog, "exec", lambda *_args: QDialog.DialogCode.Accepted)
    window.number_images(window.selected_paths())
    qtbot.waitUntil(lambda: window.batch_job is None and window.canvas.ready, timeout=10000)
    assert window.model.paths == [paths[0].with_name("00.png"), paths[1], paths[2].with_name("01.png")]
    assert paths[1].exists()
    assert set(window.model.labels) == {paths[0].with_name("00.png"), paths[2].with_name("01.png")}


def test_cancel_filter_change_keeps_actual_filter_and_unsaved_edits(qtbot, window, monkeypatch):
    window.auto.setChecked(False)
    draw(window)
    qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Cancel)
    window.filter_combo.setCurrentIndex(window.filter_combo.findData("accepted"))
    assert window.filter_combo.currentData() == window.proxy.label == "all"
    assert window.document.dirty and len(window.visible_paths()) == 3


def test_open_folder_offers_recovery_before_scanning(qtbot, window, monkeypatch):
    import json
    import os
    source = window.document.path
    token = "a" * 32
    temporary = source.parent / f".sumire-rename-{token}-0.tmp"
    os.link(source, temporary)
    journal = source.parent / f".sumire-rename-{token}.json"
    journal.write_text(json.dumps({"id": token, "phase": "renaming", "entries": [
        {"old": str(source), "new": str(source.with_name("target.png")), "temp": str(temporary), "digest": file_digest(source).hex()}]}))
    questions = []
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: questions.append(True) or QMessageBox.StandardButton.Yes)
    window.open_inputs([str(source.parent)])
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready, timeout=10000)
    assert questions and source.exists()
    assert not journal.exists() and not temporary.exists()


def test_accepted_export_reuses_saved_edits_after_cache_eviction(qtbot, window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    window.overwrite.setChecked(False)
    first = window.document.path
    window.set_review_label("accepted")
    draw(window)
    wait_saved(qtbot, window)
    expected = window.document.image.tobytes()
    original = first.read_bytes()
    window.navigate(1)
    qtbot.waitUntil(lambda: window.index == 1 and window.canvas.ready)
    window.navigate(1)
    qtbot.waitUntil(lambda: window.index == 2 and window.canvas.ready)
    assert first not in window.documents
    destination = tmp_path / "accepted-cached"
    destination.mkdir()
    def choose(self, dialog, accepted=None):
        dialog.move.setChecked(False)
        dialog.chooser.chosen = destination
        dialog.chooser.elsewhere.setChecked(True)
        dialog.renumber.setChecked(False)
        return True
    monkeypatch.setattr(type(window), "confirm_dialog", choose)
    window.export_labels()
    qtbot.waitUntil(lambda: window.batch_job is None and window.canvas.ready, timeout=10000)
    with Image.open(destination / first.name) as output:
        assert output.tobytes() == expected
    assert first.read_bytes() == original


def test_undo_reordering_keeps_newly_watched_image_and_current(qtbot, window, tmp_path, patterned):
    window.watch_timer.stop()
    paths = list(window.model.paths)
    move_down(window)
    new = tmp_path / "added.png"
    patterned.save(new)
    poll_watched(qtbot, window)
    poll_watched(qtbot, window)
    window.request_index(window.model.rows[new])
    qtbot.waitUntil(lambda: window.document.path == new and window.canvas.ready, timeout=10000)
    window.undo_organization()
    assert window.model.paths == paths + [new]
    assert window.document.path == new


@pytest.mark.parametrize("empty", [False, True])
def test_switch_folder_replaces_old_library_and_monitor(qtbot, window, tmp_path, patterned, empty):
    old_paths = set(window.model.paths)
    window.navigate(1)
    qtbot.waitUntil(lambda: window.index == 1 and window.canvas.ready)
    folder = tmp_path / "another-folder"
    folder.mkdir()
    target = folder / "new.png"
    if not empty:
        patterned.save(target)
    window.open_inputs([str(folder)])
    qtbot.waitUntil(lambda: not window.loading, timeout=10000)
    assert window.workspace_inputs == [str(folder)]
    assert not old_paths.intersection(window.model.paths)
    assert window.watched_folders == {folder}
    if empty:
        assert window.document is None and window.canvas.document is None
        assert window.model.paths == []
        patterned.save(target)
        window.poll_folders()
        window.poll_folders()
    qtbot.waitUntil(lambda: window.document is not None and window.document.path == target and window.canvas.ready, timeout=10000)
    assert window.model.paths == [target]


def test_new_folder_does_not_inherit_previous_label_filter(qtbot, window, tmp_path, patterned):
    window.set_review_label("accepted")
    window.filter_combo.setCurrentIndex(window.filter_combo.findData("accepted"))
    folder = tmp_path / "unlabelled-folder"
    folder.mkdir()
    target = folder / "new.png"
    patterned.save(target)
    window.open_inputs([str(folder)])
    qtbot.waitUntil(lambda: not window.loading, timeout=10000)
    assert window.filter_combo.currentData() == "all"
    qtbot.waitUntil(lambda: window.document is not None and window.document.path == target and window.canvas.ready)


@pytest.mark.parametrize("overwrite", [False, True])
def test_edited_state_survives_cache_eviction_and_navigation_without_new_edits(qtbot, window, overwrite):
    window.overwrite.setChecked(overwrite)
    first = window.document.path
    draw(window)
    wait_saved(qtbot, window)
    expected = window.document.image.tobytes()
    for index in (1, 2, 0):
        window.request_index(index)
        qtbot.waitUntil(lambda: window.index == index and window.canvas.ready)
    assert window.document.path == first
    assert window.document.image.tobytes() == expected
    assert window.document.edited
    assert "未編集" not in window.model.data(window.model.index(0))
    window.save_next()
    qtbot.waitUntil(lambda: window.index == 1 and window.canvas.ready)
    assert "未編集" not in window.model.data(window.model.index(0))


def test_reopened_edited_source_stays_edited_after_new_stroke_and_undo(qtbot, window):
    source = window.document.path
    draw(window)
    wait_saved(qtbot, window)
    edited_pixels = window.document.image.tobytes()
    window.open_inputs([str(source)])
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready)
    assert window.document.edited and window.document.edit_state is True
    window.set_mode("fill")
    qtbot.waitUntil(lambda: window.canvas.ready)
    draw(window, (120, 100), (140, 100))
    wait_saved(qtbot, window)
    window.history(False)
    wait_saved(qtbot, window)
    assert window.document.image.tobytes() == edited_pixels
    assert window.document.edit_state is True
    assert "未編集" not in window.model.data(window.model.index(0))


@pytest.mark.parametrize("overwrite", [False, True])
def test_batch_keeps_edit_state_for_image_outside_cache(qtbot, window, overwrite, batch_approved):
    window.overwrite.setChecked(overwrite)
    source = window.document.path
    draw(window)
    wait_saved(qtbot, window)
    for index in (1, 2):
        window.request_index(index)
        qtbot.waitUntil(lambda: window.index == index and window.canvas.ready)
    assert source not in window.documents
    window.start_batch()
    qtbot.waitUntil(lambda: window.batch_job is None and window.canvas.ready, timeout=10000)
    index = Receipts(source.parent if overwrite else window.output_folder)
    assert index.get(source)["edited"] is True
    assert index.get(window.model.paths[2])["edited"] is False
    assert "未編集" not in window.model.data(window.model.index(0))


@pytest.mark.parametrize("overwrite", [False, True])
def test_metadata_only_jpeg_stays_unedited_after_reopen(qtbot, window, tmp_path, patterned, overwrite):
    source = tmp_path / "metadata-only.jpg"
    patterned.convert("RGB").save(source)
    window.overwrite.setChecked(overwrite)
    window.open_inputs([str(source)])
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready)
    window.save(force=True)
    wait_saved(qtbot, window)
    window.open_inputs([str(source)])
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready)
    assert window.document.edit_state is False
    assert "未編集" in window.model.data(window.model.index(0))


def test_legacy_overwrite_record_is_neutral_instead_of_unedited(qtbot, window):
    import sqlite3
    from sumire.session import APPLICATION_ID, source_key
    source = window.document.path
    with sqlite3.connect(source.parent / ".sumire-index.sqlite3") as connection:
        connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
        connection.execute("CREATE TABLE receipts (source TEXT PRIMARY KEY, name TEXT, format TEXT, digest TEXT)")
        connection.execute("INSERT INTO receipts VALUES (?, ?, ?, ?)", (source_key(source), source.name, "PNG", file_digest(source).hex()))
    window.open_inputs([str(source)])
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready)
    assert window.document.edit_state is None
    assert "未編集" not in window.model.data(window.model.index(0))
    window.save(force=True)
    wait_saved(qtbot, window)
    assert Receipts(source.parent).get(source)["edited"] is None
    assert "未編集" not in window.model.data(window.model.index(0))


@pytest.mark.parametrize("overwrite", [False, True])
def test_eraser_and_mask_history_autosave_restore_original(qtbot, window, overwrite):
    window.overwrite.setChecked(overwrite)
    original = window.document.image.tobytes()
    draw(window)
    wait_saved(qtbot, window)
    processed, mask = window.document.image.tobytes(), window.document.edit_mask.tobytes()
    assert window.document.edit_mask.getbbox() is not None
    qtbot.waitUntil(lambda: window.canvas.ready)
    QTest.keyClick(window.canvas, Qt.Key.Key_M)
    assert window.mask_toggle.isChecked() and window.canvas.show_mask
    assert not window.canvas.mask_overlay.isNull()
    QTest.keyClick(window.canvas, Qt.Key.Key_E)
    qtbot.waitUntil(lambda: window.canvas.ready)
    assert window.mode == "erase" and window.strength.isHidden()
    draw(window)
    wait_saved(qtbot, window)
    assert window.document.image.tobytes() == original
    assert window.document.edit_mask.getbbox() is None
    window.history(False)
    wait_saved(qtbot, window)
    assert window.document.image.tobytes() == processed
    assert window.document.edit_mask.tobytes() == mask
    window.history(True)
    wait_saved(qtbot, window)
    assert window.document.image.tobytes() == original and window.document.edit_mask.getbbox() is None
    window.set_mode("mosaic")
    assert not window.strength.isHidden() and window.strength.isEnabled()


def test_mask_export_is_binary_and_overlay_does_not_change_saved_image(qtbot, window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from sumire.export import verify_export
    window.auto.setChecked(False)
    source = window.document.path
    before = source.read_bytes()
    draw(window)
    qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready)
    pixels, mask = window.document.image.tobytes(), window.document.edit_mask.tobytes()
    window.mask_toggle.setChecked(True)
    target = tmp_path / "mask.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(target), "PNG (*.png)"))
    window.export_edit_mask()
    qtbot.waitUntil(lambda: not window.finalizing and target.exists(), timeout=10000)
    verify_export(target, window.document.image.size, "PNG")
    with Image.open(target) as image:
        assert image.convert("L").tobytes() == mask
        assert set(image.convert("L").tobytes()) == {0, 255}
    assert source.read_bytes() == before and window.document.image.tobytes() == pixels
    window.save(force=True)
    wait_saved(qtbot, window)
    with Image.open(source) as image:
        assert image.tobytes() == pixels


def test_mask_export_refuses_to_replace_source(qtbot, window, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    source = window.document.path
    original = source.read_bytes()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(source), "PNG (*.png)"))
    window.export_edit_mask()
    qtbot.waitUntil(lambda: not window.finalizing)
    assert source.read_bytes() == original
    assert "元画像" in window.status.text()


def test_cached_image_keeps_mask_and_other_image_starts_empty(qtbot, window):
    draw(window)
    wait_saved(qtbot, window)
    first, mask = window.document, window.document.edit_mask.tobytes()
    window.mask_toggle.setChecked(True)
    window.navigate(1)
    qtbot.waitUntil(lambda: window.index == 1 and window.canvas.ready)
    assert window.document.edit_mask.getbbox() is None
    window.navigate(-1)
    qtbot.waitUntil(lambda: window.index == 0 and window.canvas.ready)
    assert window.document is first and window.document.edit_mask.tobytes() == mask


def test_mask_and_eraser_keys_do_not_consume_filename_typing(window):
    window.overwrite.setChecked(False)
    window.name.setFocus()
    window.name.selectAll()
    QTest.keyClicks(window.name, "example")
    assert window.name.text() == "example"
    assert window.mode == "mosaic" and not window.mask_toggle.isChecked()


def test_explorer_registration_buttons_call_install_and_remove(qtbot, window, monkeypatch):
    import sumire.window as module
    calls = []
    monkeypatch.setattr(module, "configure_context_menu", lambda **options: calls.append(options["remove"]))
    window.setup_explorer()
    qtbot.waitUntil(lambda: not window.finalizing)
    assert calls == [False] and "Sumīreで開く" in window.status.text()
    window.setup_explorer(True)
    qtbot.waitUntil(lambda: not window.finalizing)
    assert calls == [False, True] and "解除" in window.status.text()

