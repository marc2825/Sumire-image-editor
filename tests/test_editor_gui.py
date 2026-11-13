import pytest
from PIL import Image
from PySide6.QtCore import QPointF, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox

from sumire.canvas import qimage
from sumire.editing import EditSpec
from sumire.editor_dialogs import ImageEditDialog
from sumire.export import verify_export
from sumire.workspace_tabs import WorkspaceWindow

from test_gui import window, draw, wait_saved
from test_workspace_tabs import tabs, open_page, picture, ready


def settled(qtbot, page):
    qtbot.waitUntil(lambda: not page.busy() and not page.saving and page.canvas.ready, timeout=15000)


def position(page, point):
    return (QPointF(*point) * page.canvas.scale + page.canvas.offset).toPoint()


@pytest.mark.parametrize("overwrite", [False, True])
def test_geometry_save_undo_redo_and_reload(qtbot, window, overwrite):
    page = window
    page.overwrite.setChecked(overwrite)
    source = page.document.path
    original = source.read_bytes()
    page.apply_image_edit(EditSpec(crop=(10, 20, 80, 70), rotation=90))
    settled(qtbot, page)
    wait_saved(qtbot, page)
    assert page.document.image.size == (70, 80)
    verify_export(page.document.output, (70, 80), "PNG")
    assert (source.read_bytes() != original) == overwrite
    page.history()
    settled(qtbot, page)
    wait_saved(qtbot, page)
    assert page.document.image.size == (160, 120)
    page.history(True)
    settled(qtbot, page)
    wait_saved(qtbot, page)
    page.documents.clear()
    page.reload_workspace()
    settled(qtbot, page)
    assert page.document.image.size == (70, 80)
    assert page.document.edit_mask.size == page.document.original.size == (70, 80)
    assert page.document.edited


def test_edit_dialog_cancel_and_overwrite_confirmation_cancel(qtbot, window):
    page = window
    original, pixels = page.document.path.read_bytes(), page.document.image.tobytes()
    def cancel():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, ImageEditDialog)
        dialog.set_crop((10, 20, 80, 70))
        dialog.reject()
    QTimer.singleShot(40, cancel)
    page.edit_image()
    assert page.document.image.tobytes() == pixels and not page.document.dirty
    dialogs = []
    def accept_then_cancel():
        dialog = QApplication.activeModalWidget()
        dialogs.append(type(dialog))
        if isinstance(dialog, ImageEditDialog):
            dialog.set_crop((10, 20, 80, 70))
            dialog.accept()
            QTimer.singleShot(40, accept_then_cancel)
        else:
            assert isinstance(dialog, QMessageBox)
            assert dialog.defaultButton() == dialog.button(QMessageBox.StandardButton.Cancel)
            dialog.reject()
    QTimer.singleShot(40, accept_then_cancel)
    page.edit_image()
    assert len(dialogs) == 2
    assert page.document.image.tobytes() == pixels and page.document.path.read_bytes() == original


@pytest.mark.parametrize("shape", ["polygon", "lasso"])
def test_free_selections_apply_once_and_undo_mask(qtbot, window, shape):
    page = window
    page.auto.setChecked(False)
    page.set_mode("fill")
    page.expansion.setValue(0)
    page.shape_combo.setCurrentIndex(page.shape_combo.findData(shape))
    settled(qtbot, page)
    canvas = page.canvas
    points = [(20, 20), (100, 25), (40, 95)]
    if shape == "polygon":
        for point in points:
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=position(page, point))
        assert canvas.stroke is not None and not page.document.dirty
        QTest.keyClick(canvas, Qt.Key.Key_Return)
    else:
        # The lasso applies where its line crosses itself; the end is not joined to the start.
        points = [*points, (40, 10)]
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=position(page, points[0]))
        for point in points[1:]:
            QTest.mouseMove(canvas, position(page, point))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=position(page, points[-1]))
        assert canvas.flash_points  # shown for a moment before it is applied
    settled(qtbot, page)
    assert len(page.document.undo_stack) == 1
    assert page.document.edit_mask.getpixel((40, 40) if shape == "polygon" else (55, 45)) == 255
    assert page.document.edit_mask.getpixel((140, 100)) == 0
    assert page.document.output is None  # Enter finished the polygon; it did not save.
    page.history()
    settled(qtbot, page)
    assert not page.document.edit_mask.getbbox()


def test_polygon_cancel_inverse_selection_eyedropper_and_straight_line(qtbot, window):
    page = window
    page.auto.setChecked(False)
    page.set_mode("fill")
    page.brush.setValue(4)
    page.expansion.setValue(0)
    settled(qtbot, page)
    pixel = page.document.image.getpixel((35, 45))
    QTest.mouseClick(page.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, position(page, (35, 45)))
    assert page.color == "#%02x%02x%02x" % pixel[:3] and not page.document.dirty
    settled(qtbot, page)
    QTest.mouseClick(page.canvas, Qt.MouseButton.LeftButton, pos=position(page, (20, 40)))
    settled(qtbot, page)
    QTest.mouseClick(page.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, position(page, (100, 40)))
    settled(qtbot, page)
    assert page.document.edit_mask.getpixel((60, 40)) == 255
    page.shape_combo.setCurrentIndex(page.shape_combo.findData("polygon"))
    settled(qtbot, page)
    revision = page.document.revision
    QTest.mouseClick(page.canvas, Qt.MouseButton.LeftButton, pos=position(page, (20, 20)))
    QTest.keyClick(page.canvas, Qt.Key.Key_Escape)
    assert page.canvas.stroke is None and page.document.revision == revision
    page.shape_combo.setCurrentIndex(page.shape_combo.findData("rectangle"))
    assert page.inverse_action.isEnabled()
    page.inverse_action.setChecked(True)
    assert page.shape_combo.currentText().startswith("外側：")
    settled(qtbot, page)
    draw(page, (20, 20), (100, 80))
    settled(qtbot, page)
    assert page.document.edit_mask.getpixel((140, 100)) == 255
    assert page.document.edit_mask.getpixel((60, 60)) == 0


def test_shrinking_compression_keeps_document_dirty_and_original_files(qtbot, window, tmp_path, monkeypatch):
    from sumire.convert import Encoding
    page = window
    page.auto.setChecked(False)
    draw(page)
    settled(qtbot, page)
    source = page.document.path
    original = source.read_bytes()
    pixels, revision = page.document.image.tobytes(), page.document.revision
    folder = tmp_path / "resized"
    monkeypatch.setattr(type(page), "confirm_dialog", lambda self, dialog, accepted=None: True)
    page.prepare_conversion(list(page.model.paths), Encoding("JPEG", quality=80, max_side=80), folder, "compress")
    qtbot.waitUntil(lambda: page.batch_job is None and page.status.text().startswith("容量削減しました"), timeout=20000)
    assert len(list(folder.glob("*.jpg"))) == 3
    for path in folder.glob("*.jpg"):
        with Image.open(path) as image:
            assert image.size == (80, 60) and image.format == "JPEG" and not image.getexif()
    assert page.document.image.size == (160, 120) and page.document.image.tobytes() == pixels
    assert page.document.revision == revision and page.document.dirty and page.document.output is None
    assert source.read_bytes() == original


def test_clipboard_paste_is_new_tab_copy_is_clean_and_first_save_asks(qtbot, tabs, tmp_path, patterned, monkeypatch):
    source = picture(tmp_path / "source.png", patterned)
    a = open_page(qtbot, tabs, source)
    a.copy_image()
    settled(qtbot, a)
    copied = QApplication.clipboard().image()
    assert not copied.isNull() and copied.textKeys() == []
    copied.setText("private prompt", "synthetic private value")
    QApplication.clipboard().setImage(copied)
    a.paste_image()
    qtbot.waitUntil(lambda: tabs.tabs.count() == 2, timeout=10000)
    b = tabs.current_workspace()
    ready(qtbot, b)
    assert b.is_clipboard_path(b.document.path)
    assert not b.auto.isChecked() and not b.overwrite.isChecked() and not b.overwrite.isEnabled()
    with Image.open(b.document.path) as image:
        assert not image.info
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: ("", ""))
    b.save(force=True)
    assert b.document.output is None
    target = tmp_path / "shared.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    b.save(force=True)
    settled(qtbot, b)
    assert b.document.output == target
    verify_export(target, patterned.size, "PNG")
    assert tabs.tabs.count() == 2 and a.document.path == source


def test_navigator_moves_view_and_fullscreen_roundtrip(qtbot, window):
    page = window
    page.navigator_action.setChecked(True)
    assert page.canvas.navigator.isVisible()
    page.canvas.zoom(2)
    offset = QPointF(page.canvas.offset)
    QTest.mouseClick(page.canvas.navigator, Qt.MouseButton.LeftButton, pos=page.canvas.navigator.rect().bottomRight())
    assert page.canvas.offset != offset
    page.toggle_fullscreen()
    assert page.isFullScreen()
    page.toggle_fullscreen()
    assert not page.isFullScreen()


def test_copy_and_noop_edit_resume_pending_autosave(qtbot, window):
    page = window
    page.auto.setChecked(False)
    draw(page)
    settled(qtbot, page)
    page.auto.setChecked(True)
    assert page.autosave_timer.isActive()
    page.copy_image()
    wait_saved(qtbot, page)
    settled(qtbot, page)
    page.auto.setChecked(False)
    draw(page, (40, 65), (100, 65))
    settled(qtbot, page)
    page.auto.setChecked(True)
    page.apply_image_edit(EditSpec())
    wait_saved(qtbot, page)
    settled(qtbot, page)


def test_metadata_menu_shows_contents_and_text_copy_wins(qtbot, window, monkeypatch):
    from sumire.editor_dialogs import MetadataDialog
    shown = []
    original = window.document.path.read_bytes()
    monkeypatch.setattr(MetadataDialog, "exec", lambda dialog: shown.append(dialog.text))
    window.inspect_source_metadata()
    qtbot.waitUntil(lambda: bool(shown))
    assert shown[0] == "メタデータは見つかりませんでした。"
    assert window.document.path.read_bytes() == original
    window.search.setText("text to copy")
    window.search.selectAll()
    window.search.setFocus()
    QTest.keyClick(window.search, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert QApplication.clipboard().text() == "text to copy"
    assert not window.finalizing


def test_quality_setting_controls_normal_jpeg_save_and_is_remembered(qtbot, window, monkeypatch):
    window.overwrite.setChecked(False)
    window.format_combo.setCurrentIndex(1)
    def set_quality():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        dialog.setIntValue(63)
        dialog.accept()
    QTimer.singleShot(40, set_quality)
    window.choose_jpeg_quality()
    assert window.jpeg_quality == 63 and window.workspace_settings()["jpeg_quality"] == 63
    assert "品質63" in window.format_combo.itemText(1)
    window.save(force=True)
    settled(qtbot, window)
    verify_export(window.document.output, window.document.image.size, "JPEG")


def test_dialog_fits_short_windows_and_preview_is_reversible(qtbot, window):
    original = window.document.image.tobytes()
    dialog = ImageEditDialog(window.document.image, window)
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "画像を切り抜く" and not dialog.color_fields
    dialog.resize(680, 450)
    dialog.show()
    qtbot.wait(10)
    assert dialog.height() <= 450
    dialog.set_crop((10, 20, 80, 70))
    dialog.resize_enabled.setChecked(True)
    dialog.resize_width.setValue(40)
    dialog.update_preview()
    assert dialog.resize_height.value() == 35
    assert dialog.spec().size == (40, 35) and dialog.spec().rotation == 0 and dialog.spec().brightness == 1
    dialog.reject()
    color = ImageEditDialog(window.document.image, window, "color")
    qtbot.addWidget(color)
    assert color.windowTitle() == "色調の調整" and not hasattr(color, "crop_preview")
    color.color_fields[0].setValue(130)
    color.update_preview()
    assert color.spec().brightness == 1.3 and color.spec().crop == (0, 0, *window.document.image.size) and color.spec().size is None
    color.reject()
    assert window.document.image.tobytes() == original


def test_clipboard_tab_resumes_saved_dimensions_and_source(qtbot, tabs, tmp_path, patterned, monkeypatch):
    page = open_page(qtbot, tabs, picture(tmp_path / "original.png", patterned))
    QApplication.clipboard().setImage(qimage(patterned))
    page.paste_image()
    qtbot.waitUntil(lambda: tabs.tabs.count() == 2)
    pasted = tabs.current_workspace()
    ready(qtbot, pasted)
    pasted._start_batch([pasted.document.path])
    assert pasted.batch_job is None and pasted.document.output is None
    pasted.apply_image_edit(EditSpec(crop=(10, 20, 80, 60)))
    settled(qtbot, pasted)
    target = tmp_path / "clipboard-output.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    pasted.save(force=True)
    settled(qtbot, pasted)
    cached_source = pasted.document.path
    tabs.close()
    qtbot.waitUntil(lambda: not tabs.isVisible(), timeout=10000)
    resumed = WorkspaceWindow()
    resumed.show()
    resumed.resume_session()
    current = resumed.current_workspace()
    ready(qtbot, current)
    assert current.document.path == cached_source and current.document.output == target
    assert current.document.image.size == current.document.original.size == (80, 60)
    assert not current.overwrite.isChecked() and not current.auto.isChecked()
    resumed.close()
    qtbot.waitUntil(lambda: not resumed.isVisible(), timeout=10000)


def test_lasso_uses_only_the_first_closed_region_and_never_joins_the_ends(qtbot, window):
    from sumire.canvas import loop_closed_by_last_segment
    assert loop_closed_by_last_segment([(0, 0), (10, 0), (10, 10)]) is None
    loop = loop_closed_by_last_segment([(0, 0), (10, 0), (10, 10), (0, -10)])
    assert loop[0] == (5, 0) and loop[1:] == [(10, 0), (10, 10)]
    page = window
    page.auto.setChecked(False)
    page.set_mode("fill")
    page.expansion.setValue(0)
    page.shape_combo.setCurrentIndex(page.shape_combo.findData("lasso"))
    assert page.shape_combo.currentText() == "投げ縄" and "始点と終点は結びません" in page.shape_combo.toolTip()
    settled(qtbot, page)
    canvas = page.canvas

    def lasso(points):
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=position(page, points[0]))
        for point in points[1:]:
            QTest.mouseMove(canvas, position(page, point))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=position(page, points[-1]))
        settled(qtbot, page)

    # An open U shape encloses nothing: nothing is applied.
    lasso([(20, 20), (20, 90), (90, 90), (90, 22)])
    assert not page.document.edit_mask.getbbox() and not page.document.undo_stack
    assert "閉じた範囲" in page.status.text()
    # A figure eight drawn left to right: the right loop closes first (at 70, 50) and
    # is the only one applied; the left loop, closed later, is not.
    lasso([(10, 30), (50, 70), (90, 30), (90, 70), (50, 30), (10, 70), (14, 10)])
    assert page.document.edit_mask.getpixel((85, 50)) == 255
    assert page.document.edit_mask.getpixel((20, 50)) == 0
