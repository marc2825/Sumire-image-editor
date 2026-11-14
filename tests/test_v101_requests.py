"""1.1.0: label keys, moving on after labelling, restore button, jump field, memo search,
key hints, overwriting size reduction, reload button, unregistering and structured confirmations."""
import pytest
from PIL import Image, PngImagePlugin
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QMessageBox

from sumire import window as window_module
from sumire.labels import REVIEW_LABELS
from sumire.theme import TOKENS
from sumire.ui import fact_table

from test_gui import draw, wait_saved, window  # noqa: F401  (fixture)


def test_labels_are_accept_hold_reject_on_one_two_three(window):
    assert list(REVIEW_LABELS) == ["accepted", "pending", "rejected"]
    assert [button.text() for button in window.label_buttons.values()] == ["採用", "保留", "不採用"]
    assert window.review_hint.text() == "1 / 2 / 3"
    QTest.keyClick(window.canvas, Qt.Key.Key_1)
    assert window.model.labels[window.document.path] == "accepted"


def test_moving_on_after_labelling_is_on_by_default(qtbot, monkeypatch, tmp_path, patterned):
    monkeypatch.setattr(window_module, "AUTO_ADVANCE_DEFAULT", True)
    for name in ("a.png", "b.png"):
        patterned.save(tmp_path / name)
    page = window_module.Window()
    qtbot.addWidget(page)
    page.show()
    page.open_inputs([str(tmp_path)])
    qtbot.waitUntil(lambda: page.document is not None and page.canvas.ready, timeout=10000)
    assert page.auto_advance.isChecked()
    first = page.document.path
    page.set_review_label("accepted")
    qtbot.waitUntil(lambda: page.document.path != first and page.canvas.ready, timeout=10000)


def test_restore_button_follows_kept_originals(qtbot, window):
    button = window.restore_original_button
    assert window.image_action_widgets == [window.metadata_delete_button, button, window.save_next_button]
    assert not button.isEnabled() and "まだ上書きしていません" in button.toolTip()
    draw(window)
    wait_saved(qtbot, window)
    qtbot.waitUntil(lambda: window.restore_original_button.isEnabled(), timeout=5000)
    window.keep_originals.setChecked(False)
    assert not button.isEnabled() and "オフ" in button.toolTip()
    window.keep_originals.setChecked(True)
    assert button.isEnabled()


def test_position_field_jumps_to_the_typed_number_and_size_is_in_the_status_bar(qtbot, window):
    field = window.position_label
    assert field.text() == "1 / 3"
    width, height = window.document.image.size
    assert window.image_size_label.text() == f"{width} × {height}"
    field.box.setText("3")
    field.box.editingFinished.emit()
    qtbot.waitUntil(lambda: window.index == 2 and window.canvas.ready, timeout=10000)
    assert field.text() == "3 / 3"
    # Typing digits there must not label the image (1–3 are label keys).
    field.box.setFocus()
    QTest.keyClick(field.box, Qt.Key.Key_1)
    assert not window.model.labels


def test_search_finds_notes_as_well_as_names(qtbot, window):
    first, second, third = window.model.paths
    window.model.set_note(second, "背景を差し替える候補")
    window.search.setText("差し替え")
    qtbot.waitUntil(lambda: window.visible_paths() == [second], timeout=5000)
    window.search.setText("image10")
    qtbot.waitUntil(lambda: window.visible_paths() == [third], timeout=5000)
    assert window.search.placeholderText() == "名前・メモで検索"


def test_compare_mask_and_eraser_show_their_keys(window):
    for name, button, key in (("compare", window.compare_button, "Tab"), ("mask", window.mask_toggle, "M"),
                              ("eraser", window.erase_button, "E")):
        hint = window.key_hints[name]
        # Inside the button, right after its text, small and underlined: 消しゴム（E）.
        assert hint.key == key and hint.text() == f"（<u>{key}</u>）"
        assert hint.parent() is button and hint.isVisible()
        assert button.width() // 2 < hint.x() and hint.geometry().right() < button.width()
    hint = window.key_hints["eraser"]
    hint.set_key("")
    assert not hint.isVisible() and window.erase_button.styleSheet() == ""


def test_upscale_is_under_more_in_the_image_menu(window):
    top = [action for action in window.image_menu.actions() if not action.isSeparator()]
    assert window.editor_actions["upscale"] not in top
    other = next(action.menu() for action in top if action.menu() is not None)
    assert window.editor_actions["upscale"] in other.actions()


def test_reload_button_in_the_folder_row(qtbot, window, monkeypatch):
    calls = []
    monkeypatch.setattr(type(window), "reload_workspace", lambda self: calls.append(True))
    window.reload_action.triggered.disconnect()
    window.reload_action.triggered.connect(lambda *_args: window.reload_workspace())
    assert window.reload_folder_button.isEnabled() and "Ctrl+R" in window.reload_folder_button.toolTip()
    window.reload_folder_button.click()
    assert calls == [True]


def test_first_overwrite_button_is_the_green_primary_one(window, monkeypatch):
    monkeypatch.setitem(window_module.OVERWRITE_NOTICE, "shown", False)
    seen = []

    def inspect(box):
        accept = next(button for button in box.buttons() if button.text() == "上書きする")
        # The colour actually drawn, not only the name the style sheet matches on.
        seen.append((accept.objectName(), box.defaultButton() is accept, accept.palette().button().color().name()))
        return 0
    monkeypatch.setattr(QMessageBox, "exec", inspect)
    window.confirm_first_overwrite()
    assert seen == [("primary", True, TOKENS["accent"])]


def test_fact_table_lists_facts_and_escapes_text():
    html = fact_table([("保存先", r"C:\a <b> & c"), ("空", "")], ["注意 & 備考"])
    assert "保存先" in html and "C:\\a &lt;b&gt; &amp; c" in html and "空" not in html
    assert "<table" in html and "注意 &amp; 備考" in html


def png_with_text(path, size=(160, 120)):
    image = Image.new("RGB", size)
    image.putdata([((x * 7) % 256, (y * 5) % 256, (x + y) % 256) for y in range(size[1]) for x in range(size[0])])
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", "private prompt")
    image.save(path, pnginfo=info)


def test_size_reduction_can_overwrite_images_of_the_same_format(qtbot, window, monkeypatch, tmp_path):
    from sumire import backups
    first, second, third = window.model.paths
    jpeg = third.with_suffix(".jpg")
    Image.open(third).convert("RGB").save(jpeg, quality=95)
    png_with_text(first)
    before = first.read_bytes()
    window.append_inputs([str(jpeg)])
    qtbot.waitUntil(lambda: jpeg in window.model.rows and not window.loading, timeout=10000)
    confirmations = []

    def confirm(self, dialog, accepted=None):
        if isinstance(dialog, QMessageBox):
            confirmations.append({"text": dialog.text(), "info": dialog.informativeText(), "ok": dialog.button(QMessageBox.StandardButton.Ok).text()})
            return True
        dialog.options["png_colors"][0].setChecked(True)
        dialog.replace.setChecked(True)
        assert not dialog.chooser.isEnabled() and "PNG" in dialog.replace_note.text()
        assert dialog.destination() is None
        return True
    monkeypatch.setattr(type(window), "confirm_dialog", confirm)
    window.convert_images([first, jpeg], "compress")
    qtbot.waitUntil(lambda: window.batch_job is None and "容量削減しました" in window.status.text(), timeout=20000)
    info = confirmations[0]["info"]
    assert confirmations[0]["ok"] == "上書きする" and "元画像に上書き" in info and "形式が変わるため上書きしません" not in info
    assert "処理できない画像" in info  # the JPEG stays as it is
    with Image.open(first) as image:
        assert image.format == "PNG" and image.mode == "P" and "parameters" not in image.info
    assert first.read_bytes() != before and jpeg.exists()
    assert backups.store().has(first)  # the original can still be brought back this run
    assert not list(first.parent.glob("圧縮済み*"))


def test_unregister_option_removes_the_right_click_entry(monkeypatch):
    import sumire.__main__ as entry
    from sumire import explorer
    calls, messages = [], []
    monkeypatch.setattr(explorer, "configure_context_menu", lambda remove=False: calls.append(remove))
    monkeypatch.setattr(QMessageBox, "information", lambda parent, title, text: messages.append(text))
    monkeypatch.setattr(entry, "configure", lambda app: (None, []))  # keep the shared test app's style
    monkeypatch.setattr(entry.sys, "argv", ["sumire", "--unregister"])
    assert entry.main() == 0
    assert calls == [True] and "解除しました" in messages[0]


def test_typing_a_zoom_percentage_zooms(qtbot, window):
    """1.00.0 never connected Enter in the zoom field, so a typed percentage did nothing."""
    zoom = window.zoom_label
    zoom.setFocus()
    zoom.selectAll()
    QTest.keyClicks(zoom, "150")
    QTest.keyClick(zoom, Qt.Key.Key_Return)
    assert abs(window.canvas.scale - 1.5) < 0.01
    assert window.index == 0 and not window.saving


def test_the_mosaic_brush_starts_as_the_fine_mosaic_preset(window):
    from sumire.app_features import DEFAULT_PRESETS
    preset = DEFAULT_PRESETS["細かいモザイク"]
    assert window.mode == preset["mode"] == "mosaic"
    assert (window.brush.value(), window.strength.value(), window.expansion.value()) == (preset["brush"], preset["strength"], preset["expansion"])
    assert (window.color, window.shape_combo.currentData()) == (preset["color"], preset["shape"])
    assert window.default_settings["strengths"]["mosaic"] == preset["strength"]
