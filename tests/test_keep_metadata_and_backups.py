"""Keeping metadata on save, the metadata viewer, originals kept before overwriting,
and the editor/UI requests that came with them."""
import base64
import io
import json
import os
import struct
import time

import pytest
from PIL import Image, PngImagePlugin
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from sumire import backups
from sumire.editing import EditSpec, adjust_colors, check_colors
from sumire.export import file_digest, save_image
from sumire.imaging import ImageProblem, load_image
from sumire.metadata import capture_metadata, describe_metadata, inspect_metadata, restored_bytes
from sumire.novelai import CropPreview
from sumire.window import Window
from tests.test_gui import wait_saved


def prompt_png(path, image, text="synthetic private prompt"):
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", text)
    image.save(path, pnginfo=info)
    return path


# --- export ---------------------------------------------------------------------

def test_keep_metadata_writes_the_source_text_and_stealth_into_the_output(tmp_path, patterned, encode_stealth):
    source = prompt_png(tmp_path / "source.png", encode_stealth(patterned))
    edited = load_image(source)
    edited.paste((0, 0, 0, 255), (60, 40, 100, 80))
    result = save_image(edited, tmp_path / "out.png", source=source, format="PNG", keep_metadata=True)
    assert result.metadata_kept
    with Image.open(result.path) as saved:
        assert saved.info["parameters"] == "synthetic private prompt"
    assert "Stealth PNGInfo（隠し情報）" in inspect_metadata(result.path)
    # The visible pixels are the edited ones.
    assert load_image(result.path).tobytes() == edited.tobytes()


def test_keep_metadata_is_skipped_when_the_format_changes_and_off_strips(tmp_path, patterned):
    source = prompt_png(tmp_path / "source.png", patterned)
    as_jpeg = save_image(load_image(source), tmp_path / "out.jpg", source=source, format="JPEG", keep_metadata=True)
    assert not as_jpeg.metadata_kept and inspect_metadata(as_jpeg.path) == []
    stripped = save_image(load_image(source), tmp_path / "clean.png", source=source, format="PNG")
    assert not stripped.metadata_kept and inspect_metadata(stripped.path) == []


def small_jpeg(color):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, "JPEG")
    return buffer.getvalue()


def exif_with_pictures(thumbnail, maker_preview):
    """EXIF with a maker note holding a preview and an IFD1 thumbnail, like a camera's."""
    exif = Image.Exif()
    exif[315] = "synthetic artist"
    exif.get_ifd(0x8769)[0x927C] = b"MAKER" + maker_preview
    exif[0x8825] = {1: "N", 2: (35.0, 0.0, 0.0)}
    tiff = bytearray(exif.tobytes()[6:])
    order = "<" if tiff[:2] == b"II" else ">"
    ifd0 = struct.unpack_from(order + "I", tiff, 4)[0]
    next_at = ifd0 + 2 + struct.unpack_from(order + "H", tiff, ifd0)[0] * 12
    ifd1 = len(tiff)
    struct.pack_into(order + "I", tiff, next_at, ifd1)
    data_at = ifd1 + 2 + 2 * 12 + 4
    tiff += (struct.pack(order + "H", 2) + struct.pack(order + "HHII", 0x0201, 4, 1, data_at)
             + struct.pack(order + "HHII", 0x0202, 4, 1, len(thumbnail)) + struct.pack(order + "I", 0) + thumbnail)
    return b"Exif\0\0" + bytes(tiff)


def segment(marker, payload):
    return b"\xff" + marker + struct.pack(">H", len(payload) + 2) + payload


def test_kept_metadata_never_carries_a_picture_of_the_unedited_image(tmp_path):
    thumbnail, maker, xmp_copy, photoshop, jfxx = (small_jpeg(color) for color in
                                                   ("red", "green", "blue", "yellow", "white"))
    source = tmp_path / "photo.jpg"
    xmp = (b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:Description GImage:Data="'
           + base64.b64encode(xmp_copy) + b'"/></x:xmpmeta>')
    Image.new("RGB", (64, 48), "purple").save(source, "JPEG", exif=exif_with_pictures(thumbnail, maker), xmp=xmp)
    data = source.read_bytes()
    source.write_bytes(data[:2] + segment(b"\xfe", b"synthetic comment")
                       + segment(b"\xed", b"Photoshop 3.0\x008BIM\x04\x0c\0\0" + struct.pack(">I", len(photoshop)) + photoshop)
                       + segment(b"\xe2", b"MPF\0II*\0synthetic index") + segment(b"\xe0", b"JFXX\0\x10" + jfxx) + data[2:])
    edited = load_image(source)
    edited.paste("black", (0, 0, 64, 48))
    result = save_image(edited, tmp_path / "out.jpg", source=source, format="JPEG", keep_metadata=True)
    raw = result.path.read_bytes()
    assert result.metadata_kept
    assert raw.count(b"\xff\xd8\xff") == 1  # only the image itself
    for picture in (thumbnail, maker, xmp_copy, photoshop, jfxx):
        assert picture not in raw
    assert b"GImage" not in raw and b"MPF\0" not in raw and b"JFXX" not in raw
    with Image.open(result.path) as saved:
        exif = saved.getexif()
        assert exif[315] == "synthetic artist"
        assert exif.get_ifd(0x8825)[1] == "N"
        assert 0x927C not in exif.get_ifd(0x8769)
        assert saved.info["comment"] == b"synthetic comment"
    # Restoring metadata into an edited copy leaves the same pictures out.
    restored = restored_bytes(edited, capture_metadata(source.read_bytes()))
    assert restored.count(b"\xff\xd8\xff") == 1 and thumbnail not in restored


def test_kept_png_text_with_an_image_and_unknown_chunks_are_left_out(tmp_path, patterned):
    preview = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(preview, "PNG")
    preview = preview.getvalue()
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", "synthetic prompt")
    info.add_itxt("workflow", '{"image": "data:image/png;base64,' + base64.b64encode(preview).decode() + '"}', zip=True)
    info.add(b"prVW", preview)
    source = tmp_path / "source.png"
    patterned.save(source, pnginfo=info, exif=exif_with_pictures(small_jpeg("red"), b""))
    result = save_image(load_image(source), tmp_path / "out.png", source=source, format="PNG", keep_metadata=True)
    raw = result.path.read_bytes()
    assert raw.count(b"\x89PNG") == 1 and b"\xff\xd8\xff" not in raw and b"prVW" not in raw
    with Image.open(result.path) as saved:
        assert saved.info["parameters"] == "synthetic prompt"
        assert "workflow" not in saved.info
        assert saved.getexif()[315] == "synthetic artist"


def test_overwrite_calls_the_backup_hook_before_replacing(tmp_path, patterned):
    source = prompt_png(tmp_path / "source.png", patterned)
    original = source.read_bytes()
    seen = []
    save_image(load_image(source), source, source=source, format="PNG", overwrite_source=True,
               source_digest=file_digest(source), backup=lambda path: seen.append(path.read_bytes()))
    assert seen == [original] and source.read_bytes() != original


# --- metadata viewer ------------------------------------------------------------

def test_describe_metadata_lists_categories_items_and_unknown_parts(tmp_path, patterned, encode_stealth):
    path = tmp_path / "meta.png"
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", "a cat\nSteps: 20")
    info.add_text("Comment", json.dumps({"prompt": "1girl", "uc": "bad"}))
    info.add(b"zzZz", b"opaque")
    exif = Image.Exif()
    exif[271] = "Maker"
    exif[0x8825] = {1: "N", 2: (35, 30, 0), 3: "E", 4: (139, 45, 0)}
    encode_stealth(patterned).save(path, pnginfo=info, exif=exif)
    entries = describe_metadata(path)
    categories = {category for category, _, _ in entries}
    assert {"EXIF", "GPS・位置情報", "生成情報", "Stealth PNGInfo（画素に埋め込まれた情報）", "不明"} <= categories
    assert ("EXIF", "メーカー（Make）", "Maker") in entries
    assert ("GPS・位置情報", "緯度・経度", "35.500000, 139.750000") in entries
    stealth = [content for category, _, content in entries if category.startswith("Stealth")]
    assert "synthetic private NovelAI prompt" in stealth[0]
    assert ("不明", "zzZzチャンク", "不明（6バイト）") in entries


def test_metadata_dialog_groups_entries_as_category_blocks(qtbot):
    from sumire.editor_dialogs import MetadataDialog
    dialog = MetadataDialog("画像：a.png", [("EXIF", "機種（Model）", "X"), ("EXIF", "向き（Orientation）", "1"), ("不明", "APP9セグメント", "不明（3バイト）")])
    qtbot.addWidget(dialog)
    assert dialog.text == "[EXIF]\n機種（Model）：X\n向き（Orientation）：1\n\n[不明]\nAPP9セグメント：不明（3バイト）"


# --- originals kept before overwriting ------------------------------------------

def test_backup_store_keeps_the_first_original_and_restores_it(tmp_path):
    image = tmp_path / "a.png"
    image.write_bytes(b"first")
    store = backups.OriginalBackups(tmp_path / "temp")
    (tmp_path / "temp").mkdir()
    store.keep(image)
    image.write_bytes(b"second")
    store.keep(image)  # the earliest original of the run wins
    assert store.has(image)
    with pytest.raises(ImageProblem):
        store.restore(image, file_digest(tmp_path / "a.png") + b"x")
    store.restore(image, file_digest(image))
    assert image.read_bytes() == b"first"
    root = store.root
    store.cleanup()
    assert not root.exists() and not store.has(image)


def test_stale_backup_folders_are_removed_only_when_old(tmp_path):
    old, fresh = tmp_path / (backups.PREFIX + "old"), tmp_path / (backups.PREFIX + "new")
    old.mkdir()
    fresh.mkdir()
    past = time.time() - backups.STALE_SECONDS - 60
    os.utime(old, (past, past))
    backups.remove_stale(tmp_path)
    assert not old.exists() and fresh.exists()


# --- window ---------------------------------------------------------------------

@pytest.fixture
def keeping(monkeypatch):
    """The shipped default: saving keeps metadata."""
    import sumire.window as window_module
    monkeypatch.setattr(window_module, "STRIP_METADATA_DEFAULT", False)


@pytest.fixture
def prompt_window(qtbot, tmp_path, patterned, keeping):
    prompt_png(tmp_path / "image.png", patterned)
    widget = Window()
    with qtbot.waitExposed(widget):
        widget.show()
    widget.open_inputs([str(tmp_path)])
    qtbot.waitUntil(lambda: widget.document is not None and widget.canvas.ready, timeout=10000)
    yield widget
    qtbot.waitUntil(lambda: not widget.busy() and not widget.saving, timeout=10000)
    widget.close()


def test_default_save_keeps_metadata_and_the_delete_button_strips_it(qtbot, prompt_window):
    window = prompt_window
    assert not window.strip_metadata.isChecked()
    assert window.metadata_state.text() == "メタデータ：有り" and "生成プロンプト" in window.metadata_state.toolTip()
    window.save(force=True)
    wait_saved(qtbot, window)
    with Image.open(window.document.path) as saved:
        assert saved.info["parameters"] == "synthetic private prompt"
    assert window.metadata_state.text() == "メタデータ：有り"
    window.metadata_button.trigger()
    qtbot.waitUntil(lambda: window.metadata_state.text() == "メタデータ：無し" and not window.saving, timeout=10000)
    with Image.open(window.document.path) as saved:
        assert "parameters" not in saved.info


def test_kept_metadata_output_reloads_as_saved(qtbot, prompt_window):
    window = prompt_window
    window.save(force=True)
    wait_saved(qtbot, window)
    window.documents.clear()
    window.reload_workspace()
    qtbot.waitUntil(lambda: window.document is not None and window.canvas.ready and not window.loading, timeout=10000)
    assert window.document.saved_revision == window.document.revision and window.document.metadata


def test_overwrite_keeps_the_original_and_restore_puts_it_back(qtbot, prompt_window, monkeypatch):
    window = prompt_window
    original = window.document.path.read_bytes()
    assert not window.restore_original_action.isEnabled()
    window.strip_metadata.setChecked(True)
    window.save(force=True)
    wait_saved(qtbot, window)
    assert window.document.path.read_bytes() != original
    window.update_controls()
    assert window.restore_original_action.isEnabled()
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    window.restore_original_action.trigger()
    qtbot.waitUntil(lambda: window.document is not None and window.canvas.ready and not window.loading, timeout=10000)
    assert window.document.path.read_bytes() == original
    assert window.metadata_state.text() == "メタデータ：有り"


def test_first_overwrite_explains_once_and_can_be_hidden(qtbot, prompt_window, monkeypatch):
    import sumire.window as window_module
    window = prompt_window
    monkeypatch.setitem(window_module.OVERWRITE_NOTICE, "shown", False)
    original = window.document.path.read_bytes()
    seen = []

    def answer(button_text, hide=False):
        def respond():
            box = QApplication.activeModalWidget()
            seen.append(box.windowTitle())
            box.checkBox().setChecked(hide)
            next(button for button in box.buttons() if button.text() == button_text).click()
        QTimer.singleShot(50, respond)

    answer("キャンセル")
    window.save(force=True)
    assert seen == ["元画像に上書きします"] and window.document.path.read_bytes() == original and not window.saving
    answer("上書きする", hide=True)
    window.save(force=True)
    wait_saved(qtbot, window)
    assert len(seen) == 2 and window.preferences.data["hide_overwrite_notice"] is True
    window_module.OVERWRITE_NOTICE["shown"] = False
    window.save(force=True)  # hidden for good: no dialog this time
    wait_saved(qtbot, window)
    assert len(seen) == 2


def test_zoom_field_accepts_a_typed_percentage(qtbot, prompt_window):
    window = prompt_window
    window.zoom_label.setFocus()
    window.zoom_label.setText("150")
    window.zoom_label.commit()
    qtbot.waitUntil(lambda: abs(window.canvas.scale - 1.5) < 0.01)
    window.canvas.setFocus()
    assert window.zoom_label.text() == "150%"


def test_list_and_grid_switch_in_one_click_and_small_tiles(qtbot, prompt_window):
    window = prompt_window
    window.view_buttons[1].click()
    assert window.view_combo.currentIndex() == 1 and window.view_buttons[1].isChecked()
    window.thumbnail_size.setValue(48)
    assert window.list.gridSize().width() == 60
    window.view_buttons[0].click()
    assert window.view_combo.currentIndex() == 0 and window.view_buttons[0].isChecked()


def test_settings_and_help_list_the_open_pages_headings(qtbot, prompt_window):
    from sumire.help import HelpDialog
    from sumire.settings_dialog import SettingsDialog
    settings = SettingsDialog(prompt_window)
    qtbot.addWidget(settings)
    headings = [settings.sidebar.outline.item(row).text() for row in range(settings.sidebar.outline.count())]
    assert headings[:3] == ["保存方法", "上書き前の元画像", "メタデータ"]
    settings.resize(700, 360)
    settings.show()
    settings.jump_to(len(headings) - 1)
    assert settings.pages.currentWidget().verticalScrollBar().value() > 0
    settings.reject()
    help_dialog = HelpDialog()
    qtbot.addWidget(help_dialog)
    assert help_dialog.sidebar.outline.count() > 2
    help_dialog.show()
    help_dialog.jump_to_heading(help_dialog.sidebar.outline.count() - 1)
    assert help_dialog.browser.verticalScrollBar().value() > 0


# --- editor ---------------------------------------------------------------------

def test_color_adjustments_are_identity_at_defaults_and_validated(patterned):
    assert adjust_colors(patterned, EditSpec()).tobytes() == patterned.tobytes()
    for spec in (EditSpec(hue=60), EditSpec(exposure=0.5), EditSpec(temperature=40), EditSpec(gamma=1.5),
                 EditSpec(highlights=-30, shadows=30), EditSpec(white=220, black=10), EditSpec(red=1.2, blue=0.8),
                 EditSpec(sharpness=2)):
        changed = adjust_colors(patterned, spec)
        assert changed.size == patterned.size and changed.getchannel("A").tobytes() == patterned.getchannel("A").tobytes()
        assert changed.tobytes() != patterned.tobytes()
    with pytest.raises(ImageProblem):
        check_colors(EditSpec(white=10, black=20))
    with pytest.raises(ImageProblem):
        check_colors(EditSpec(hue=200))


def test_color_dialog_has_its_own_undo_and_redo(qtbot, patterned):
    from sumire.editor_dialogs import ImageEditDialog
    dialog = ImageEditDialog(patterned, None, "color")
    qtbot.addWidget(dialog)
    assert not dialog.color_details.isVisibleTo(dialog)
    brightness = dialog.color_controls["brightness"][0]
    brightness.setValue(150)
    dialog.record_colors()
    dialog.color_controls["hue"][0].setValue(40)
    dialog.record_colors()
    assert dialog.spec().brightness == 1.5 and dialog.spec().hue == 40
    dialog.step_colors(-1)
    assert dialog.spec().hue == 0 and dialog.spec().brightness == 1.5
    dialog.step_colors(-1)
    assert dialog.spec().brightness == 1 and not dialog.color_undo.isEnabled()
    dialog.step_colors(1)
    dialog.step_colors(1)
    assert dialog.spec().hue == 40 and not dialog.color_redo.isEnabled()


def test_crop_frame_starts_on_the_whole_image_and_corners_drag(qtbot, patterned):
    preview = CropPreview(patterned, (160, 120))
    qtbot.addWidget(preview)
    preview.show()
    assert preview.crop == (0, 0, 160, 120)
    QTest.mousePress(preview, Qt.MouseButton.LeftButton, pos=QPoint(1, 1))
    QTest.mouseMove(preview, QPoint(41, 21))
    QTest.mouseRelease(preview, Qt.MouseButton.LeftButton, pos=QPoint(41, 21))
    assert preview.crop == (40, 20, 120, 100)
    QTest.mousePress(preview, Qt.MouseButton.LeftButton, pos=QPoint(100, 70))
    QTest.mouseMove(preview, QPoint(80, 60))
    QTest.mouseRelease(preview, Qt.MouseButton.LeftButton, pos=QPoint(80, 60))
    assert preview.crop == (20, 10, 120, 100)
    # A press outside the frame never starts a new rectangle.
    preview.crop = (40, 20, 40, 40)
    QTest.mousePress(preview, Qt.MouseButton.LeftButton, pos=QPoint(150, 110))
    QTest.mouseMove(preview, QPoint(155, 115))
    assert preview.crop == (40, 20, 40, 40)


def test_new_built_in_preset_is_offered_once_to_saved_settings(qtbot, monkeypatch):
    from sumire.app_features import DEFAULT_PRESETS
    from sumire.preferences import Preferences
    # Settings saved before the finer preset existed, with two built-ins deleted.
    Preferences().save({"presets": {"黒塗り": DEFAULT_PRESETS["黒塗り"]}})
    window = Window()
    qtbot.addWidget(window)
    assert list(window.presets) == ["とても細かいモザイク", "黒塗り"]
    window.apply_preset("とても細かいモザイク")
    assert window.mode == "mosaic" and window.strength.value() == 6
    assert window.preset_save.text() == "現在の設定を登録" and window.preset_save.property("variant") is None
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.preset_combo.setCurrentIndex(window.preset_combo.findData("とても細かいモザイク"))
    window.delete_preset()
    again = Window()
    qtbot.addWidget(again)
    assert list(again.presets) == ["黒塗り"]  # a deleted built-in stays deleted


def test_dragging_images_shows_a_grabbing_hand(qtbot, prompt_window, monkeypatch):
    import sumire.library as library
    seen = {}

    def exec_drag(drag, *args):
        seen.update(pixmap=drag.pixmap(), hot=drag.hotSpot(), cursor=drag.dragCursor(Qt.DropAction.MoveAction))
        return Qt.DropAction.IgnoreAction

    monkeypatch.setattr(library.QDrag, "exec", exec_drag)
    view = prompt_window.list
    view.selectionModel().select(view.model().index(0, 0), view.selectionModel().SelectionFlag.ClearAndSelect)
    view.startDrag(Qt.DropAction.MoveAction)
    size = seen["pixmap"].deviceIndependentSize()
    assert not seen["pixmap"].isNull() and size.width() == 28
    assert (seen["hot"].x(), seen["hot"].y()) == (14, 14)  # the hand is centred on the pointer
    assert seen["cursor"].size().width() == 1  # no arrow drawn over the hand


def test_tool_notes_are_tooltips_and_saved_images_keep_the_drawing_hint(qtbot, prompt_window):
    window = prompt_window
    window.set_mode("mosaic")
    assert "完全には隠せません" in window.strength.toolTip() and "完全には隠せません" in window.strength_label.toolTip()
    assert window.strength_description.isHidden()
    window.set_mode("fill")
    window.strength.setValue(100)
    assert "元の画素を完全に置き換えます" in window.strength.toolTip() and window.strength_description.isHidden()
    window.strength.setValue(60)
    assert window.strength_description.isHidden() and "透ける" in window.strength.toolTip()
    window.save(force=True)
    wait_saved(qtbot, window)
    assert window.status.text() == window.ready_hint()
    assert "保存済み" in window.save_state.text()


def test_copyright_sits_at_the_foot_of_the_start_page(qtbot):
    window = Window()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    window.update_controls()
    assert window.pages.currentWidget() is window.welcome
    assert window.credit.isVisible() and window.credit.text() == "© 2026 marc2825"
    assert window.credit.parent() is window.welcome


def test_help_section_headings_are_coloured_and_underlined(qtbot):
    from PySide6.QtGui import QTextFormat
    from sumire.help import HelpDialog
    from sumire.theme import TOKENS
    dialog = HelpDialog()
    qtbot.addWidget(dialog)
    block = dialog.browser.document().findBlock(dialog.heading_blocks[0])
    assert block.blockFormat().hasProperty(QTextFormat.Property.BlockTrailingHorizontalRulerWidth)
    assert block.begin().fragment().charFormat().foreground().color().name() == TOKENS["accent"]


# --- collage canvas ----------------------------------------------------------------

def view_point(canvas, x, y):
    rect = canvas.to_view(x, y)
    return QPoint(round(rect.x()), round(rect.y()))


@pytest.fixture
def collage(qtbot):
    from sumire.output_dialogs import CollageDialog
    images = [Image.new("RGBA", (200, 100), "red"), Image.new("RGBA", (200, 100), "blue")]
    dialog = CollageDialog(["a.png", "b.png"], images)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    dialog.layout_combo.setCurrentIndex(0)  # side by side
    return dialog, images


def test_collage_crops_in_place_and_a_click_outside_finishes(qtbot, collage):
    dialog, images = collage
    canvas = dialog.canvas
    x, y, scale, _ = canvas.placement(1)[1:]
    QTest.mouseDClick(canvas, Qt.MouseButton.LeftButton, pos=view_point(canvas, x + 100 * scale, y + 50 * scale))
    assert canvas.cropping == 1 and "枠の外をクリック" in dialog.hint.text()
    # Drag the left edge of the frame 50 source pixels inwards.
    start = view_point(canvas, x, y + 50 * scale)
    end = view_point(canvas, x + 50 * scale, y + 50 * scale)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert canvas.cropping == 1 and canvas.live_crop[0] in range(48, 53) and canvas.crops[1] == (0, 0, 200, 100)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPoint(3, 3))  # outside the frame
    assert canvas.cropping is None and canvas.crops[1][0] in range(48, 53)
    assert "切り抜き：" in dialog.image_list.item(1).text()
    collage_image = dialog.renderer()()
    assert collage_image.width < 400  # the cropped image takes less room
    dialog.uncrop_button.click()
    assert canvas.crops[1] == (0, 0, 200, 100) and images[1].size == (200, 100)


def test_free_layout_moves_resizes_and_renders_what_is_shown(qtbot, collage):
    dialog, _ = collage
    canvas = dialog.canvas
    dialog.arrangement.setCurrentIndex(dialog.arrangement.findData("free"))
    assert canvas.free and (dialog.canvas_width.value(), dialog.canvas_height.value()) == canvas.canvas_size
    assert dialog.form.isRowVisible(dialog.canvas_size_row) and not dialog.form.isRowVisible(dialog.layout_combo)
    dialog.canvas_width.setValue(300)
    dialog.canvas_height.setValue(300)
    first = canvas.pieces[0]
    # Move the red image down by 100 output pixels.
    start = view_point(canvas, first.x + 50, first.y + 50)
    end = view_point(canvas, first.x + 50, first.y + 150)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    moved = canvas.pieces[0]
    assert abs(moved.y - (first.y + 100)) < 3 and canvas.order[-1] == 0 and canvas.selected == 0
    # Drag its bottom-right corner to make it bigger, keeping the proportions.
    width, height = moved.shown_size()
    corner = view_point(canvas, moved.x + width, moved.y + height)
    bigger = view_point(canvas, moved.x + width + 60, moved.y + height + 30)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=corner)
    QTest.mouseMove(canvas, bigger)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=bigger)
    resized = canvas.pieces[0]
    assert resized.scale > moved.scale and (resized.x, resized.y) == (moved.x, moved.y)
    result = dialog.renderer()()
    assert result.size == (300, 300)
    middle = (round(resized.x + resized.shown_size()[0] / 2), round(resized.y + resized.shown_size()[1] / 2))
    assert result.getpixel(middle)[:3] == (255, 0, 0)


def test_free_collage_render_clips_and_layers(patterned):
    from sumire.collage import FreeLayout, Piece, render_free_collage
    images = [Image.new("RGBA", (100, 50), "red"), Image.new("RGBA", (40, 40), "blue")]
    layout = FreeLayout((120, 80), None, ((0, Piece((0, 0, 100, 50), -20, 10, 1.0)), (1, Piece((10, 10, 20, 20), 70, 40, 2.0))))
    result = render_free_collage(images, layout)
    assert result.size == (120, 80)
    assert result.getpixel((0, 20)) == (255, 0, 0, 255)       # partly outside on the left
    assert result.getpixel((75, 45)) == (0, 0, 255, 255)      # drawn over the red one
    assert result.getpixel((115, 5)) == (0, 0, 0, 0)          # transparent background


def test_save_option_notes_follow_each_option(qtbot, prompt_window):
    from sumire.settings_dialog import SettingsDialog
    window = prompt_window
    notes = lambda: (window.auto_note.text(), window.overwrite_note.text(), window.keep_originals_note.text(),
                     window.strip_note.text(), window.backup_note.text())
    on = notes()
    window.auto.setChecked(False)
    window.metadata_backup.setChecked(False)
    window.strip_metadata.setChecked(True)
    window.keep_originals.setChecked(False)
    off = notes()
    assert all(on[index] != off[index] for index in (0, 2, 3, 4))  # overwrite itself is still on
    assert "「保存」を押したとき" in off[0] and "元のファイルは残しません" in off[2] and "残しません" in off[4]
    dialog = SettingsDialog(window)
    qtbot.addWidget(dialog)
    assert dialog.save_notes["auto"].text() == off[0]
    window.auto.setChecked(True)  # the settings page follows the window
    assert dialog.save_notes["auto"].text() == on[0]
    window.overwrite.setChecked(False)
    assert "別フォルダー" in dialog.save_notes["overwrite"].text() and "そのまま残ります" in window.keep_originals_note.text()
    dialog.overwrite_notice.setChecked(False)
    assert dialog.notice_note.text() == "確認を表示せずに上書きします。"
    dialog.done(0)


def test_reset_whole_list_restores_kept_originals_labels_and_order(qtbot, tmp_path, patterned, monkeypatch):
    from tests.test_gui import draw
    for name in ("a.png", "b.png"):
        patterned.save(tmp_path / name)
    originals_bytes = {name: (tmp_path / name).read_bytes() for name in ("a.png", "b.png")}
    window = Window()
    qtbot.addWidget(window)
    window.show()
    window.open_inputs([str(tmp_path)])
    qtbot.waitUntil(lambda: window.document is not None and window.canvas.ready, timeout=10000)
    for index in range(2):
        if index:
            window.navigate(1)
            qtbot.waitUntil(lambda: window.index == 1 and window.canvas.ready, timeout=10000)
        draw(window)
        wait_saved(qtbot, window)
    assert all((tmp_path / name).read_bytes() != data for name, data in originals_bytes.items())
    window.label_buttons["accepted"].click()
    window.label_index(window.document.path).set_note(window.document.path, "synthetic note")
    window.model.set_note(window.document.path, "synthetic note")
    window.sort_combo.setCurrentIndex(window.sort_combo.findData("name_desc"))
    assert window.model.labels.get(window.document.path)
    monkeypatch.setattr(window, "confirm_dialog", lambda dialog, **kwargs: True)
    window.reset_whole_list()
    qtbot.waitUntil(lambda: window.document is not None and window.canvas.ready and not window.busy(), timeout=10000)
    assert all((tmp_path / name).read_bytes() == data for name, data in originals_bytes.items())
    assert not any(window.model.labels.get(path) for path in window.model.paths)
    assert not any(window.model.notes.get(path) for path in window.model.paths)
    assert window.sort_combo.currentData() == "name_asc" and [path.name for path in window.model.paths] == ["a.png", "b.png"]
    assert not window.document.edited and "元画像に戻した画像 2枚" in window.status.text()
    assert window.workflow_actions["reset_list"] in window.library_menu.actions()


def test_settings_reset_returns_every_setting_to_its_first_value(qtbot, prompt_window, monkeypatch):
    from sumire.app_features import DEFAULT_PRESETS
    from sumire.preferences import Preferences
    from sumire.settings_dialog import SettingsDialog
    window = prompt_window
    window.auto.setChecked(False)
    window.overwrite.setChecked(False)
    window.brush.setValue(321)
    window.thumbnail_size.setValue(50)
    window.preferences.save({**window.preferences.data, "hide_overwrite_notice": True,
                             "presets": {"自作": DEFAULT_PRESETS["黒塗り"]}})
    window.show_presets({"自作": DEFAULT_PRESETS["黒塗り"]})
    window.remember_workspace()
    dialog = SettingsDialog(window)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Ok)
    dialog.reset_button.click()
    assert window.auto.isChecked() and window.overwrite.isChecked()
    assert window.brush.value() == 60 and window.thumbnail_size.value() == window.default_settings["thumbnail"]
    assert list(window.presets) == list(DEFAULT_PRESETS)
    data = Preferences().data
    assert "hide_overwrite_notice" not in data and "presets" not in data and data["settings"]["overwrite"] is True
    assert window.status.text() == "設定を初期状態に戻しました。"


def test_sliders_take_typed_numbers_without_triggering_shortcuts(qtbot, prompt_window):
    window = prompt_window
    window.activateWindow()
    box = window.brush_box
    box.setFocus()
    box.selectAll()
    QTest.keyClicks(box, "250")
    QTest.keyClick(box, Qt.Key.Key_Return)
    assert window.brush.value() == 250 and window.index == 0 and not window.saving
    window.brush.setValue(120)
    assert box.value() == 120  # the box follows the slider
    window.set_mode("fill")
    assert window.strength_box.suffix() == "%" and window.strength_box.minimum() == 0
    window.strength_box.setValue(40)
    assert window.strength.value() == 40
    window.expansion_box.setValue(3)
    assert window.expansion.value() == 3 and window.tool().expansion == 3


def test_share_menu_hands_a_clean_png_for_dragging_without_opening_a_site(qtbot, prompt_window, monkeypatch):
    from PySide6.QtGui import QDesktopServices
    window = prompt_window
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    assert [action.text() for action in window.share_menu.actions()] == ["NovelAIでi2i", "画像をコピー", "ドラッグして渡す"]
    window.share_actions["drag"].trigger()
    qtbot.waitUntil(lambda: window.novelai_dialog is not None, timeout=10000)
    dialog = window.novelai_dialog
    try:
        assert dialog.windowTitle() == "画像を渡す" and dialog.open_button.isHidden() and opened == []
        with Image.open(dialog.prepared.path) as image:
            assert not image.info  # no metadata in the image handed over
    finally:
        dialog.close()
    zoom = window.zoom_label
    zoom.setFocus()
    zoom.selectAll()
    QTest.keyClicks(zoom, "150")
    QTest.keyClick(zoom, Qt.Key.Key_Return)
    assert window.index == 0 and not window.saving  # Enter zoomed; it did not save and move on
