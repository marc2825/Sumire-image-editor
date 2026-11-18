"""1.3.0: the text tool (T) and オリジナルタグ, tags kept as buttons below the labels."""
from PIL import Image
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from sumire.labels import quick_tags
from sumire.shortcuts import defaults, validate
from sumire.tag_dialog import QuickTagDialog
from sumire.text_tool import TextStyle, render_text, text_stroke, to_pil
from sumire.window import Window

from test_gui import window  # noqa: F401  (fixture)


def idle(qtbot, window):
    qtbot.waitUntil(lambda: not window.busy() and not window.saving and not window.finalizing, timeout=10000)


def widget_point(window, x, y):
    return (QPointF(x, y) * window.canvas.scale + window.canvas.offset).toPoint()


# --- text ----------------------------------------------------------------------------

def test_text_is_drawn_with_a_margin_and_only_where_it_lands(qapp, patterned, tmp_path):
    from sumire.imaging import Document
    style = TextStyle(size=24, color="#ff0000", bold=True)
    image, margin = render_text("Ab\nCd", style)
    layer = to_pil(image)
    assert margin > 0 and layer.mode == "RGBA" and layer.getchannel("A").getbbox() is not None
    assert layer.height > 2 * 24  # two lines
    document = Document(tmp_path / "a.png", patterned.copy())
    assert text_stroke(document, "   ", style, (10, 10)) is None  # nothing to write
    stroke = text_stroke(document, "Ab", style, (140, 95))  # partly outside: only the part on the image
    assert stroke is not None
    stroke.apply()
    x0, y0, x1, y1 = stroke.box
    assert 140 - margin <= x0 and x1 <= 160 and y1 <= 120
    assert document.edit_mask.getbbox() is not None


def test_text_style_settings_are_checked():
    assert TextStyle.from_settings({"family": "X", "size": 30, "color": "#ABCDEF", "bold": True}) == TextStyle("X", 30, "#abcdef", True)
    assert TextStyle.from_settings({"size": 99999, "color": "red", "bold": "yes"}) == TextStyle()
    assert TextStyle.from_settings(None) == TextStyle()


def test_text_tool_writes_text_as_one_undoable_edit(qtbot, window, monkeypatch):
    window.auto.setChecked(False)
    document = window.document
    before = document.image.copy()
    QTest.keyClick(window.canvas, Qt.Key.Key_T)
    assert window.mode == "text" and window.text_button.isChecked()
    assert window.shape_combo.isHidden() and window.brush.isHidden() and window.strength.isHidden()
    qtbot.waitUntil(lambda: window.canvas.ready, timeout=5000)
    seen = {}

    def accept(self, dialog, **kwargs):
        dialog.text.setPlainText("Sumīre")
        dialog.size_box.setValue(28)
        dialog.color = "#ff0000"
        dialog.bold.setChecked(True)
        seen["preview"] = window.canvas.text_preview
        return True

    monkeypatch.setattr(Window, "confirm_dialog", accept)
    QTest.mouseClick(window.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, widget_point(window, 8, 8))
    idle(qtbot, window)
    assert seen["preview"] is not None  # shown on the image while typing
    assert window.canvas.text_preview is None
    assert window.text_style == TextStyle(window.text_style.family, 28, "#ff0000", True)  # remembered for the next text
    assert document.edited and document.dirty
    box = document.edit_mask.getbbox()
    assert box is not None and box[0] >= 0 and box[1] >= 0
    red = [color for _, color in document.image.crop(box).getcolors(1 << 20) if color[0] > 200 and color[1] < 60 and color[2] < 60]
    assert red  # the glyphs are in the pixels
    assert window.workspace_settings()["text"]["size"] == 28
    window.history(False)
    idle(qtbot, window)
    assert document.image.tobytes() == before.tobytes() and document.edit_mask.getbbox() is None
    QTest.keyClick(window.canvas, Qt.Key.Key_T)
    assert window.mode == "mosaic" and not window.shape_combo.isHidden()


def test_cancelling_the_text_changes_nothing(qtbot, window, monkeypatch):
    window.set_mode("text")
    qtbot.waitUntil(lambda: window.canvas.ready, timeout=5000)
    monkeypatch.setattr(Window, "confirm_dialog", lambda self, dialog, **kwargs: dialog.text.setPlainText("x") or False)
    before = window.document.image.tobytes()
    window.place_text(QPointF(5, 5))
    idle(qtbot, window)
    assert window.document.image.tobytes() == before and not window.document.dirty
    assert window.canvas.text_preview is None


def test_text_mode_is_not_saved_as_a_preset(window, monkeypatch):
    window.set_mode("text")
    errors = []
    monkeypatch.setattr(window, "error", errors.append)
    window.save_preset()
    assert errors and "テキスト" in errors[0]


# --- オリジナルタグ ------------------------------------------------------------------

def test_quick_tags_start_with_needs_fixing_and_keep_their_order():
    assert quick_tags({}) == ["要修正"]
    assert quick_tags({"quick_tags": []}) == []
    assert quick_tags({"quick_tags": ["b", " a ", "B", 3, "x" * 60]}) == ["b", "a", "x" * 40]


def test_default_shortcuts_have_no_conflicts():
    bindings = defaults()
    validate(bindings)
    assert bindings["text"] == ["T"] and bindings["quick_tag_1"] == ["4"] and bindings["quick_tag_6"] == ["9"]


def test_tag_button_adds_removes_and_undoes(qtbot, window):
    first, second, _ = window.model.paths
    assert [button.text() for button in window.quick_tag_buttons] == ["要修正"]
    assert "4" in window.quick_tag_buttons[0].toolTip()
    window.select_paths([first, second])
    window.press_quick_tag(0)
    tagged = [path for path in window.model.paths if "要修正" in window.model.tags.get(path, ())]
    assert tagged and window.document.path in tagged
    assert window.quick_tag_buttons[0].isChecked()
    window.press_quick_tag(0)  # all chosen images have it: take it off
    assert not any("要修正" in window.model.tags.get(path, ()) for path in window.model.paths)
    window.press_quick_tag(0)
    window.undo_organization()
    assert not any("要修正" in window.model.tags.get(path, ()) for path in window.model.paths)
    window.press_quick_tag(5)  # no sixth button yet
    assert "まだありません" in window.status.text()


def test_tag_buttons_are_edited_saved_and_renamed_in_the_tab(qtbot, window, monkeypatch):
    path = window.document.path
    window.press_quick_tag(0)
    assert window.model.tags[path] == ("要修正",)

    def edit(self, dialog, **kwargs):
        item = dialog.list.item(0)
        item.setText("直す")  # rename
        dialog.entry.setText("背景")
        dialog.add()
        dialog.entry.setText("直す")  # a duplicate is not added twice
        dialog.add()
        return True

    monkeypatch.setattr(Window, "confirm_dialog", edit)
    window.edit_quick_tags()
    assert window.quick_tags == ["直す", "背景"]
    assert window.preferences.data["quick_tags"] == ["直す", "背景"]
    assert window.model.tags[path] == ("直す",)  # the tab's images follow the rename
    assert [button.text() for button in window.quick_tag_buttons] == ["直す", "背景"]
    window.undo_organization()
    assert window.model.tags[path] == ("要修正",)
    window.reset_all_settings()
    assert window.quick_tags == ["要修正"]


def test_quick_tag_dialog_limits_and_reorders(qtbot):
    dialog = QuickTagDialog(["a", "b"])
    qtbot.addWidget(dialog)
    dialog.list.setCurrentRow(1)
    dialog.move(-1)
    assert dialog.names() == ["b", "a"]
    dialog.list.item(0).setText("a")  # would duplicate: goes back
    assert dialog.names() == ["b", "a"]
    dialog.list.setCurrentRow(0)
    dialog.remove()
    for number in range(20):
        dialog.entry.setText(f"t{number}")
        dialog.add()
    tags, renames = dialog.chosen()
    assert len(tags) == 9 and tags[0] == "a" and renames == {}
    assert not dialog.buttons["add"].isEnabled()


def test_icons_for_the_new_buttons_draw(qapp):
    from sumire.icons import icon
    for name in ("text", "tag"):
        assert not icon(name).pixmap(16, 16).toImage().isNull()
    assert isinstance(Image.new("L", (1, 1)), Image.Image)
    assert QApplication.instance() is not None
