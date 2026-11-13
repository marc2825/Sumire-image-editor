"""Resetting all review labels, and whole-image operations in the right panel."""
from PySide6.QtWidgets import QMessageBox

from sumire.editor_dialogs import ImageEditDialog
from sumire.output_dialogs import UpscaleDialog
from sumire.labels import ReviewLabels

from test_batch_confirmation import reply_to_confirmation
from test_gui import window
from test_workspace_tabs import open_page, picture, tabs


def label_all(window):
    first, second, third = window.model.paths
    window.write_labels({first: "accepted", second: "pending", third: "rejected"}, {first: None, second: None, third: None})
    return first, second, third


def test_whole_tab_buttons_form_a_grid_and_stack_when_narrow(qtbot, tabs, tmp_path, patterned):
    page = open_page(qtbot, tabs, picture(tmp_path / "a.png", patterned))
    def placed(wide):
        export, delete, reset = (button.geometry() for button in page.library_action_buttons())
        more = page.library_menu_button.mapTo(page.library_panel, page.library_menu_button.rect().center())
        if wide:
            # 採用を書き出す sits right above 仕分けをリセット; ⋯ moved to its left.
            return (abs(export.left() - reset.left()) <= 2 and export.bottom() < reset.top()
                    and abs(delete.center().y() - reset.center().y()) <= 2 and delete.right() < reset.left()
                    and more.x() < page.export_accepted_button.mapTo(page.library_panel, export.topLeft() * 0).x())
        return delete.bottom() < export.top() and export.bottom() < reset.top() and abs(delete.left() - reset.left()) <= 2
    tabs.resize(1320, 850)
    page.splitter.setSizes([340, 700, 280])
    qtbot.waitUntil(lambda: placed(True))
    tabs.resize(800, 600)
    qtbot.waitUntil(lambda: placed(False))
    panel = page.library_panel
    assert panel.minimumWidth() <= 262 and panel.width() >= panel.minimumWidth()
    assert all(button.isVisible() for button in page.library_action_buttons())
    # The right panel's content must fit without horizontal clipping.
    assert page.tools_scroll.widget().minimumSizeHint().width() <= page.tools_scroll.viewport().width()


def test_reset_needs_labels(window):
    assert not window.reset_labels_button.isEnabled()
    window.set_review_label("accepted")
    assert window.reset_labels_button.isEnabled() and window.workflow_actions["reset_labels"].isEnabled()


def test_cancel_keeps_labels_and_dialog_defaults_to_cancel(qtbot, window):
    paths = label_all(window)
    observed = reply_to_confirmation()
    window.reset_labels_button.click()
    assert observed["title"] == "仕分けのリセットを確認" and "3 枚" in observed["text"]
    assert "不採用 1 枚" in observed["info"] and "採用 1 枚" in observed["info"]
    assert "選択・絞り込みにかかわらず" in observed["info"] and "メモ" in observed["info"]
    assert observed["default"] == observed["escape"] == QMessageBox.StandardButton.Cancel
    assert observed["accept_text"] == "リセット"
    assert [window.model.labels.get(path) for path in paths] == ["accepted", "pending", "rejected"]


def test_reset_clears_every_label_keeps_notes_and_files_and_can_be_undone(qtbot, window):
    paths = label_all(window)
    folder = paths[0].parent
    ReviewLabels(folder).set_note(paths[0], "残すメモ")
    window.model.set_note(paths[0], "残すメモ")
    files = {path: path.read_bytes() for path in paths}
    reply_to_confirmation(QMessageBox.StandardButton.Ok)
    window.reset_labels_button.click()
    assert not any(window.model.labels.get(path) for path in paths)
    stored = ReviewLabels(folder)
    assert not any(stored.get(path) for path in paths) and stored.note(paths[0]) == "残すメモ"
    assert all(path.read_bytes() == files[path] for path in paths)
    assert "未判定 3" in window.review_summary.text() and "仕分けをリセットしました · 3枚" in window.status.text()
    assert not window.reset_labels_button.isEnabled()
    window.undo_organization()
    assert [window.model.labels.get(path) for path in paths] == ["accepted", "pending", "rejected"]
    assert [ReviewLabels(folder).get(path) for path in paths] == ["accepted", "pending", "rejected"]


def test_reset_applies_to_the_whole_tab_while_filtered(qtbot, window):
    paths = label_all(window)
    window.filter_combo.setCurrentIndex(window.filter_combo.findData("accepted"))
    qtbot.waitUntil(lambda: not window.loading and window.visible_paths() == [paths[0]])
    reply_to_confirmation(QMessageBox.StandardButton.Ok)
    window.workflow_actions["reset_labels"].trigger()
    qtbot.waitUntil(lambda: not window.loading and not window.saving)
    assert not any(window.model.labels.get(path) for path in paths)
    assert window.visible_paths() == [] and window.document is None


def test_reset_is_limited_to_this_tab(qtbot, tabs, tmp_path, patterned):
    first = open_page(qtbot, tabs, picture(tmp_path / "a" / "one.png", patterned).parent)
    first.set_review_label("accepted")
    second = open_page(qtbot, tabs, picture(tmp_path / "b" / "two.png", patterned).parent, mode="new")
    second.set_review_label("pending")
    reply_to_confirmation(QMessageBox.StandardButton.Ok)
    second.reset_labels_button.click()
    assert first.model.labels.get(first.document.path) == "accepted"
    assert ReviewLabels(tmp_path / "a").get(first.document.path) == "accepted"


def test_crop_button_details_section_and_bottom_crop_icon(qtbot, window, monkeypatch):
    assert not hasattr(window, "crop_button")
    assert not hasattr(window, "upscale_button") and not hasattr(window, "image_tools")
    assert window.details_toggle.text() == "詳細設定・その他" and window.tool_details.isHidden()
    window.details_toggle.setChecked(True)
    assert not window.tool_details.isHidden() and window.color_button_adjust.isEnabled()
    assert [button.text() for button in window.transform_buttons] == ["右へ90°", "左へ90°", "左右反転", "上下反転"]
    assert window.crop_tool in window.view_controls and window.crop_tool.isEnabled()
    menu_actions = window.image_menu.actions() + [action for menu in window.image_menu.findChildren(type(window.image_menu))
                                                  for action in menu.actions()]
    assert window.editor_actions["edit"] not in menu_actions and window.editor_actions["upscale"] in menu_actions
    opened = []
    monkeypatch.setattr(type(window), "confirm_dialog",
                        lambda self, dialog, accepted=None: opened.append((type(dialog), getattr(dialog, "mode", None))) or False)
    window.crop_tool.click()
    window.color_button_adjust.click()
    window.editor_actions["upscale"].trigger()
    assert opened == [(ImageEditDialog, "crop"), (ImageEditDialog, "color"), (UpscaleDialog, None)]
    assert "image_tools_open" not in window.workspace_settings()


def test_rotate_and_flip_apply_at_once_and_can_be_undone(qtbot, window):
    from PIL import Image
    window.auto.setChecked(False)
    window.overwrite.setChecked(True)
    original = window.document.image.copy()
    window.transform_buttons[0].click()
    qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready)
    assert window.document.image.size == (120, 160)
    assert window.document.image.tobytes() == original.transpose(Image.Transpose.ROTATE_270).tobytes()
    window.transform_buttons[2].click()
    qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready)
    window.history(False)
    qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready)
    window.history(False)
    qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready)
    assert window.document.image.tobytes() == original.tobytes()
