"""The refreshed layout: one bar above the image, sorting under it, folding panels, messages, colours."""
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from sumire import window as window_module
from sumire.theme import TOKENS

from test_gui import window  # noqa: F401  (fixture)


def contrast(first, second):
    def luminance(value):
        channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_text_and_control_edges_are_readable_on_the_panels():
    for name in ("text", "text_muted", "text_faint", "accent", "ok", "warn", "danger"):
        for ground in ("panel", "chrome", "canvas", "field"):
            assert contrast(TOKENS[name], TOKENS[ground]) >= 4.5, (name, ground)
    for ground in ("panel", "chrome", "canvas", "field"):
        assert contrast(TOKENS["line_strong"], TOKENS[ground]) >= 3, ground
    # The grounds have no hue, so they do not tint how the image looks.
    for name in ("canvas", "chrome", "panel", "field", "raised", "control"):
        value = TOKENS[name]
        assert value[1:3] == value[3:5] == value[5:7], name


def test_one_colour_one_meaning(window):
    # Violet: selection, primary action, focus. Green, yellow, red: the labels. The save state uses none of them.
    assert TOKENS["accent"] not in (TOKENS["ok"], TOKENS["warn"], TOKENS["danger"])
    window.update_controls()
    for colour in (TOKENS["ok"], TOKENS["warn"], TOKENS["accent"]):
        assert colour not in window.save_state.text()
    style = window.styleSheet()
    assert "QPushButton:focus, QToolButton:focus { border: 2px solid" in style
    assert "QCheckBox:focus, QRadioButton:focus { border-color:" in style


def test_image_bar_is_one_row_when_wide_and_two_when_narrow(qtbot, window):
    window.resize(1440, 900)
    qtbot.waitUntil(lambda: window.image_bar_compact is False and window.view_bar_compact is False)

    def middle(widget):
        return widget.mapTo(window.image_bar, widget.rect().center()).y()
    # The file name and 「保存して次へ」 on the same row, in a bar no taller than one row.
    qtbot.waitUntil(lambda: abs(middle(window.save_next_button) - middle(window.file_label)) <= 2 and window.image_bar.height() < 56)
    window.resize(800, 600)
    qtbot.waitUntil(lambda: window.image_bar_compact is True)
    for widget in (window.save_next_button, window.metadata_state):
        assert widget.mapTo(window.image_bar, widget.rect().bottomRight()).x() < window.image_bar.width()


def test_panels_fold_by_button_and_key_and_are_remembered(qtbot, window):
    window.resize(1440, 900)
    assert not window.library_panel.isHidden() and not window.tools_panel.isHidden()
    width = window.canvas.width()
    window.library_toggle.click()
    QTest.keyClick(window.canvas, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert window.library_panel.isHidden() and window.tools_panel.isHidden()
    qtbot.waitUntil(lambda: window.canvas.width() > width + 400)
    assert window.library_toggle.toolTip().startswith("一覧を表示") and "Ctrl+B" in window.library_toggle.toolTip()
    settings = window.workspace_settings()
    assert settings["show_library"] is False and settings["show_tools"] is False
    QTest.keyClick(window.canvas, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
    assert not window.library_panel.isHidden()
    window.restore_settings({**settings, "show_library": False, "show_tools": True})
    assert window.library_panel.isHidden() and not window.tools_panel.isHidden()


def test_narrow_window_folds_the_tools_then_the_list(qtbot, window, monkeypatch):
    monkeypatch.setitem(window_module.AUTO_FOLD, "enabled", True)
    window.resize(1440, 900)
    qtbot.waitUntil(lambda: not window.tools_panel.isHidden())
    window.resize(900, 600)
    qtbot.waitUntil(lambda: window.tools_panel.isHidden())
    assert not window.library_panel.isHidden()
    # Folded only for the room: still a panel the user shows.
    assert window.workspace_settings()["show_tools"] is True
    window.resize(1440, 900)
    qtbot.waitUntil(lambda: not window.tools_panel.isHidden())
    # One folded by hand stays folded when the window widens.
    window.toggle_library_panel()
    window.resize(700, 500)
    window.resize(1440, 900)
    qtbot.waitUntil(lambda: not window.tools_panel.isHidden())
    assert window.library_panel.isHidden()


def test_results_show_briefly_errors_stay_and_the_hint_only_once(qtbot, window):
    window.hide_toast()
    window.hint_shown = True
    window.info(window.ready_hint())
    assert window.toast.isHidden()
    window.info("「採用」を付けました · 1枚")
    assert window.toast.isVisible() and window.toast_timer.isActive() and window.status.text() == "「採用」を付けました · 1枚"
    # The image's own hint after moving on leaves the result to be read.
    window.info(window.ready_hint())
    assert window.toast.isVisible() and window.status.text() == window.ready_hint()
    window.error("保存できませんでした。")
    assert window.toast.isVisible() and not window.toast_timer.isActive() and window.toast.property("tone") == "danger"
    assert window.toast_close.isVisible()
    window.toast_close.click()
    assert window.toast.isHidden()
    # Work in progress appears only when it takes a while.
    window.info("画像を読み込み中…")
    assert window.toast.isHidden() and window.toast_delay.isActive()
    qtbot.waitUntil(lambda: window.toast.isVisible(), timeout=3000)
    canvas = window.canvas.geometry()
    canvas.moveTopLeft(window.canvas.mapTo(window.toast.parentWidget(), window.canvas.rect().topLeft()))
    assert canvas.contains(window.toast.geometry())


def test_clicking_a_button_leaves_the_keys_on_the_image(qtbot, window):
    assert QApplication.focusWidget() is window.canvas
    window.erase_button.click()
    QTest.mouseClick(window.label_buttons["pending"], Qt.MouseButton.LeftButton)
    QTest.mouseClick(window.mask_toggle, Qt.MouseButton.LeftButton)
    assert QApplication.focusWidget() is window.canvas
    assert window.label_buttons["pending"].focusPolicy() == Qt.FocusPolicy.TabFocus


def test_shape_buttons_follow_the_shape_choice(window):
    window.shape_buttons["ellipse"].click()
    assert window.shape_combo.currentData() == "ellipse" and window.canvas.shape == "ellipse"
    assert window.shape_buttons["ellipse"].isChecked() and not window.shape_buttons["brush"].isChecked()
    assert window.shape_label.text().endswith("楕円")
    window.shape_combo.setCurrentIndex(window.shape_combo.findData("lasso"))
    assert window.shape_buttons["lasso"].isChecked()
    window.set_mode("text")
    assert window.shape_row.isHidden() and window.expansion_row.isHidden()
    window.set_mode("mosaic")
    assert not window.shape_row.isHidden() and window.shape_combo.isHidden()


def test_actions_are_shown_only_where_they_can_do_something(qtbot, window):
    # 「上書き前に戻す」 only while originals are overwritten and kept.
    window.overwrite.setChecked(True)
    window.keep_originals.setChecked(True)
    assert not window.restore_original_button.isHidden()
    window.overwrite.setChecked(False)
    assert window.restore_original_button.isHidden()
    # 「メタデータを削除」 only while the image has (or may have) metadata.
    window.document.metadata = []
    window.update_controls()
    assert window.metadata_delete_button.isHidden() and "無し" in window.metadata_state.text()
    window.document.metadata = ["EXIF"]
    window.update_controls()
    assert not window.metadata_delete_button.isHidden()
