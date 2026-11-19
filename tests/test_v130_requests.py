"""1.3.0–1.4.0: the text tool (T) with its editable box, and オリジナルタグ (tags kept as buttons)."""
from PIL import Image
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from sumire.labels import quick_tags
from sumire.shortcuts import defaults, validate
from sumire.tag_dialog import QuickTagDialog
from dataclasses import replace

from sumire.text_tool import TextPlacement, TextStyle, placement_at, render_placed, text_layer, write_text
from sumire.window import Window

from test_gui import window  # noqa: F401  (fixture)


def idle(qtbot, window):
    qtbot.waitUntil(lambda: not window.busy() and not window.saving and not window.finalizing, timeout=10000)


def widget_point(window, x, y):
    return (QPointF(x, y) * window.canvas.scale + window.canvas.offset).toPoint()


# --- text ----------------------------------------------------------------------------

def test_text_is_drawn_only_where_it_lands_and_replaced_as_one_edit(qapp, patterned, tmp_path):
    from sumire.imaging import Document
    style = TextStyle(size=24, color="#ff0000", bold=True)
    document = Document(tmp_path / "a.png", patterned.copy())
    before = document.image.copy()
    assert render_placed(placement_at("   ", style, (10, 10)), document.image.size) is None  # nothing to draw
    placed = placement_at("Ab\nCd", style, (140, 95))  # partly outside: only the part on the image
    image, rect = render_placed(placed, document.image.size)
    assert rect.right() <= 160 and rect.bottom() <= 120 and image.width() == rect.width()
    corner = placed.corners()[0]
    assert abs(corner.x() - 140) < 0.01 and abs(corner.y() - 95) < 0.01  # placed by its top left
    layer = text_layer(placed, document.image.size)
    state, changed = write_text(document, placed, layer, None)
    assert changed and state.box[2] <= 160 and document.edit_mask.getbbox() is not None
    first = document.revision
    # Moving it: the old text is taken out (pixels and mask come back) and the new one written, as one edit.
    moved = replace(placed, center=(placed.center[0] - 100, placed.center[1] - 60), angle=30)
    state2, changed = write_text(document, moved, text_layer(moved, document.image.size), state)
    assert changed and document.revision != first and state2.box[2] < state.box[0]  # now left of where it was
    # Where the old text was, the image and the mask are back to how they were.
    assert document.image.crop(state.box).tobytes() == before.crop(state.box).tobytes()
    assert document.edit_mask.crop(state.box).getbbox() is None
    document.undo()
    assert document.revision == first  # Undo goes back to the previous placement
    _, changed = write_text(document, None, None, state)  # taking it out restores the image
    assert changed and document.image.tobytes() == before.tobytes() and document.edit_mask.getbbox() is None


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
        dialog.changed.emit()  # the debounced preview
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


# --- 1.4.0: editing the text through its box ---------------------------------------

def place(qtbot, window, monkeypatch, text="Sumīre", point=(10, 10)):
    def accept(self, dialog, **kwargs):
        dialog.text.setPlainText(text)
        dialog.size_box.setValue(24)
        return True
    monkeypatch.setattr(Window, "confirm_dialog", accept)
    window.set_mode("text")
    qtbot.waitUntil(lambda: window.canvas.ready, timeout=5000)
    window.place_text(QPointF(*point))
    idle(qtbot, window)
    return window.current_text_state()


def test_written_text_keeps_a_box_that_moves_rotates_resizes_and_undoes(qtbot, window, monkeypatch):
    window.auto.setChecked(False)
    document = window.document
    original = document.image.copy()
    state = place(qtbot, window, monkeypatch)
    assert state is not None and window.canvas.text_box is state
    first = state.placement
    canvas = window.canvas
    # Move: drag inside the box.
    start = first.corners()[0] + QPointF(4, 4)
    canvas.start_text_drag("move", start)
    canvas.drag_text(start + QPointF(30, 40), False)
    moved = canvas.text_drag["placement"]
    assert canvas.text_preview is not None and canvas.text_under is not None  # previewed over the old pixels
    canvas.text_drag = None
    window.transform_text(moved)
    idle(qtbot, window)
    assert window.current_text_state().placement == moved
    assert canvas.text_preview is None and canvas.text_under is None
    # Rotate, snapping to 15° with Shift.
    centre = QPointF(*moved.center)
    canvas.start_text_drag("rotate", centre + QPointF(0, -40))
    canvas.drag_text(centre + QPointF(40, -42), True)
    turned = canvas.text_drag["placement"]
    assert turned.angle % 15 == 0 and turned.angle != 0
    canvas.text_drag = None
    window.transform_text(turned)
    idle(qtbot, window)
    # Resize from a corner: the opposite corner stays where it is.
    corners = turned.corners()
    canvas.start_text_drag("corner2", corners[2])
    canvas.drag_text(corners[0] + (corners[2] - corners[0]) * 2, False)
    bigger = canvas.text_drag["placement"]
    assert bigger.style.size > turned.style.size
    fixed = bigger.corners()[0]
    assert abs(fixed.x() - corners[0].x()) < 0.5 and abs(fixed.y() - corners[0].y()) < 0.5
    canvas.text_drag = None
    window.transform_text(bigger)
    idle(qtbot, window)
    assert window.current_text_state().placement.style.size == bigger.style.size
    # Undo steps back through the placements, with the box where the text was.
    window.history(False)
    idle(qtbot, window)
    assert window.current_text_state().placement == turned and canvas.text_box is window.current_text_state()
    for _ in range(3):
        window.history(False)
        idle(qtbot, window)
    assert document.image.tobytes() == original.tobytes() and canvas.text_box is None


def test_text_is_rewritten_by_double_click_and_deleted(qtbot, window, monkeypatch):
    document = window.document
    original = document.image.copy()
    state = place(qtbot, window, monkeypatch, "ab")
    top_left = state.placement.corners()[0]

    def rewrite(self, dialog, **kwargs):
        assert dialog.value() == "ab" and dialog.ok_button.text() == "適用"
        dialog.text.setPlainText("ab cd")  # added to
        dialog.changed.emit()
        assert window.canvas.text_under is not None  # the old text hidden under the preview
        return True

    monkeypatch.setattr(Window, "confirm_dialog", rewrite)
    window.edit_text()
    idle(qtbot, window)
    rewritten = window.current_text_state().placement
    assert rewritten.text == "ab cd" and rewritten.size()[0] > state.placement.size()[0]
    corner = rewritten.corners()[0]
    assert abs(corner.x() - top_left.x()) < 0.5 and abs(corner.y() - top_left.y()) < 0.5  # grows from its top left
    window.canvas.setFocus()
    QTest.keyClick(window.canvas, Qt.Key.Key_Delete)
    idle(qtbot, window)
    assert document.image.tobytes() == original.tobytes() and window.current_text_state() is None
    assert "消しました" in window.status.text()


def test_clicking_beside_the_text_lets_go_and_the_next_click_adds_new_text(qtbot, window, monkeypatch):
    state = place(qtbot, window, monkeypatch, "ab", (5, 5))
    canvas = window.canvas
    assert canvas.text_hit(canvas.to_screen(QPointF(*state.placement.center))) == "move"
    requested = []
    canvas.textRequested.connect(requested.append)
    away = widget_point(window, 150, 110)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, away)
    assert canvas.text_box is None and not window.text_selected and not requested
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, away)
    assert requested
    QTest.keyClick(canvas, Qt.Key.Key_T)  # another tool: the box is not shown
    assert window.mode != "text" and canvas.text_box is None


def test_text_moved_off_the_image_stays_where_it_was(qtbot, window, monkeypatch):
    state = place(qtbot, window, monkeypatch, "ab")
    away = replace(state.placement, center=(5000, 5000))
    window.transform_text(away)
    idle(qtbot, window)
    assert window.current_text_state() is state and "外" in window.status.text()


def test_placement_corners_follow_the_angle(qapp):
    style = TextStyle(size=20)
    flat = TextPlacement("ab", style, (50, 50))
    width, height = flat.size()
    turned = replace(flat, angle=90)
    top_left = turned.corners()[0]
    assert abs(top_left.x() - (50 + height / 2)) < 0.01 and abs(top_left.y() - (50 - width / 2)) < 0.01
    inside = turned.to_block(QPointF(50, 50))
    assert abs(inside.x() - width / 2) < 0.01 and abs(inside.y() - height / 2) < 0.01


# --- 1.4.0: the sorting area -------------------------------------------------------

def test_labels_are_at_the_bottom_and_custom_tags_fold_above_them(qtbot, window):
    footer = window.label_buttons["accepted"].parentWidget()
    layout = footer.layout()
    order = [layout.itemAt(index) for index in range(layout.count())]
    assert order[-1].layout() is not None and window.label_buttons["accepted"] in [
        order[-1].layout().itemAt(i).widget() for i in range(order[-1].layout().count())]
    assert window.quick_tag_panel.isHidden()  # folded at first
    window.quick_tag_toggle.setChecked(True)
    assert not window.quick_tag_panel.isHidden()
    assert window.workspace_settings()["quick_tags_open"] is True
    tag_top = window.quick_tag_toggle.mapTo(footer, window.quick_tag_toggle.rect().topLeft()).y()
    label_top = window.label_buttons["accepted"].mapTo(footer, window.label_buttons["accepted"].rect().topLeft()).y()
    assert tag_top < label_top


# --- issues #3 and #4 --------------------------------------------------------------

def test_default_tag_buttons_are_saved_before_tags_are_given(window):
    assert "quick_tags" not in window.preferences.data
    window.press_quick_tag(0)
    assert window.preferences.data["quick_tags"] == ["要修正"]  # a later language change keeps it


def test_text_preview_is_debounced_and_drawn_at_screen_resolution(qtbot, window):
    from sumire.text_tool import TextDialog
    dialog = TextDialog(TextStyle(size=2000), window)
    qtbot.addWidget(dialog)
    fired = []
    dialog.changed.connect(lambda: fired.append(1))
    for letter in "abc":
        dialog.text.insertPlainText(letter)
    assert not fired  # not on every key
    qtbot.waitUntil(lambda: bool(fired), timeout=2000)
    assert len(fired) == 1
    image, rect = render_placed(placement_at("abc", TextStyle(size=2000), (0, 0)), (160, 120), 0.25)
    assert rect.width() <= 160 and rect.height() <= 120 and image.width() <= 40


def test_robustness_notes_of_issue_4(tmp_path):
    from sumire import provenance
    from sumire.imaging import ImageProblem, Tool, load_image, make_effect
    assert provenance.has_thumbnail(None) is False
    try:
        make_effect(Image.new("RGBA", (4, 4)), Tool("fill", color="not a colour"))
    except ImageProblem:
        pass
    else:
        raise AssertionError("an invalid fill colour must raise ImageProblem")
    grey = Image.new("I;16", (4, 1))
    grey.putdata([0, 16384, 32768, 65535])
    grey.save(tmp_path / "grey16.png")
    loaded = load_image(tmp_path / "grey16.png")
    assert [loaded.getpixel((x, 0))[0] for x in range(4)] == [0, 64, 128, 255]  # scaled, not clipped to white
