"""Smaller interface requests: eraser toggle, wheel-safe choices, settings, tabs, list order, comparison."""
from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox

import sumire.workbench as workbench
from sumire.compare import ComparisonDialog
from sumire.preferences import Preferences
from sumire.settings_dialog import SettingsDialog

from test_gui import window
from test_workspace_tabs import open_page, picture, tabs


def test_eraser_button_and_key_toggle_back_to_the_previous_tool(window):
    window.set_mode("blur")
    window.erase_button.click()
    assert window.mode == "erase" and window.erase_button.isChecked()
    window.erase_button.click()
    assert window.mode == "blur" and not window.erase_button.isChecked()
    window.canvas.eraserRequested.emit()
    window.canvas.eraserRequested.emit()
    assert window.mode == "blur"


def wheel(widget, delta=-120):
    event = QWheelEvent(QPointF(5, 5), QPointF(widget.mapToGlobal(QPoint(5, 5))), QPoint(0, 0), QPoint(0, delta),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)


def test_scrolling_over_a_choice_list_never_changes_it(window):
    window.details_toggle.setChecked(True)
    for combo in (window.shape_combo, window.preset_combo):
        before = combo.currentIndex()
        wheel(combo)
        wheel(combo, 120)
        assert combo.currentIndex() == before
    for slider in (window.expansion, window.expansion_box, window.brush):
        before = slider.value()
        wheel(slider)
        wheel(slider, 120)
        assert slider.value() == before


def test_review_buttons_are_coloured_before_they_are_chosen(window):
    style = window.styleSheet()
    for label in ("rejected", "pending"):
        assert f'QPushButton#reviewLabel[label="{label}"] {{' in style
    assert "QPushButton#reviewLabel { padding: 6px 14px; font-weight: 700; color:" in style


def test_reset_edits_button_has_a_frame_and_no_ellipsis(window):
    assert window.reset_edits_button.property("variant") is None
    assert window.reset_edits_button.text() == "加工・マスクを初期化"
    assert "text-align: center" in window.styleSheet().split("QPushButton#toggle {")[1].split("}")[0]


def test_welcome_does_not_claim_offline_or_show_status(qtbot):
    from sumire.window import Window
    page = Window()
    qtbot.addWidget(page)
    assert "オフライン" not in page.welcome.note.text() and page.welcome.note.text().startswith("保存方法：")
    assert page.status.text() == ""


def test_gear_opens_settings_that_mirror_the_window(qtbot, window, monkeypatch):
    assert window.settings_button.accessibleName() == "設定" and not hasattr(window, "app_menu")
    opened = []
    monkeypatch.setattr(SettingsDialog, "exec", lambda self: opened.append([self.topics.item(i).text() for i in range(self.topics.count())]) or 0)
    window.settings_button.click()
    assert opened and opened[0][0] == "保存" and "Windows連携" in opened[0]
    dialog = SettingsDialog(window)
    qtbot.addWidget(dialog)
    overwrite = window.overwrite.isChecked()
    dialog.overwrite.setChecked(not overwrite)
    assert window.overwrite.isChecked() is (not overwrite)
    window.overwrite.setChecked(overwrite)
    assert dialog.overwrite.isChecked() is overwrite
    dialog.quality.setValue(70)
    assert window.jpeg_quality == 70 and "品質70" in window.format_combo.itemText(1)
    dialog.reject()
    window.overwrite.setChecked(not overwrite)  # no stale follower on the deleted dialog
    window.overwrite.setChecked(overwrite)


def test_only_the_sort_direction_and_labels_are_coloured(window):
    from sumire.theme import TOKENS
    from sumire.ui import SEGMENTS_ROLE
    segments = {window.sort_combo.itemData(i): window.sort_combo.itemData(i, SEGMENTS_ROLE) for i in range(window.sort_combo.count())}
    assert segments["name_asc"] == [("名前順 · ", None), ("昇順 ↑", TOKENS["sort_asc"])]
    assert segments["name_desc"] == [("名前順 · ", None), ("降順 ↓", TOKENS["sort_desc"])]
    assert segments["date_desc"][1] == ("新しい順 ↓", TOKENS["sort_desc"]) and segments["manual"] == [("手動の順番", None)]
    assert TOKENS["sort_asc"] != TOKENS["sort_desc"] and window.sort_combo.styleSheet() == ""
    assert window.sort_combo.currentText() == "名前順 · 昇順 ↑"
    window.sort_combo.grab()  # the partly coloured text paints without errors
    colours = {window.filter_combo.itemData(i, Qt.ItemDataRole.ForegroundRole).name() for i in range(window.filter_combo.count())}
    assert len(colours) >= 3
    window.filter_combo.setCurrentIndex(window.filter_combo.findData("rejected"))
    assert "color:" in window.filter_combo.styleSheet()


def test_list_stays_draggable_and_drops_below_the_lower_half(window):
    window.update_library_view()
    view = window.list
    assert view.dragEnabled() and view.viewport().acceptDrops()
    first = view.visualRect(window.proxy.index(0, 0))
    before, _ = view.insertion_point(QPoint(first.center().x(), first.bottom() - 2))
    assert before == str(window.model.paths[1])
    before, _ = view.insertion_point(QPoint(first.center().x(), first.top() + 2))
    assert before == str(window.model.paths[0])
    paths = list(window.model.paths)
    window.reorder_selection([str(paths[0])], str(paths[2]))
    assert window.model.paths == [paths[1], paths[0], paths[2]] and window.sort_combo.currentData() == "manual"
    menu = QMenu()
    window.populate_selection_menu(menu)
    texts = [action.text() for action in menu.actions()]
    assert not any(text in ("1つ上へ移動", "1つ下へ移動") for text in texts)
    assert "別名で保存…" in texts and "メタデータを削除して保存" in texts


def test_library_menu_lists_only_work_without_its_own_button(window):
    texts = [action.text().split("\t")[0] for action in window.library_menu.actions() if action.text()]
    # 「整理を戻す」 has its own button above the list; the whole-list work is all in this menu.
    for gone in ("採用画像を書き出す…", "直前の整理操作を戻す",
                 "似ている画像を探す…", "失敗理由を確認・失敗分だけ再処理…", "一覧全体を縮小して書き出す…"):
        assert gone not in texts
    for present in ("全画像のメタデータを一括削除…", "仕分けをすべてリセット…", "ラベルごとに書き出す…",
                    "重複を削除…", "一覧全体の形式を変換…", "一覧全体の容量削減…"):
        assert present in texts


def test_undo_arrow_follows_the_organisation_history(window):
    assert not window.undo_organize_button.isEnabled()
    window.set_review_label("accepted")
    assert window.undo_organize_button.isEnabled() and "直前の整理操作を戻す" in window.undo_organize_button.toolTip()
    window.undo_organize_button.click()
    assert window.model.labels.get(window.document.path) is None


def test_image_menu_and_canvas_menu_share_the_four_commands(window, monkeypatch):
    texts = [action.text().split("\t")[0] for action in window.image_menu.actions() if not action.isSeparator()]
    assert texts[:3] == [window.manual_save.text().split("\t")[0], "別名で保存…", window.metadata_button.text()]
    assert not any(text.startswith("メタデータを復元") for text in texts)
    other = next(action.menu() for action in window.image_menu.actions() if action.menu() is not None)
    assert other.title() == "その他" and other.actions()[0] is window.editor_actions["upscale"]  # 超解像 is one level down
    shown = []
    monkeypatch.setattr(QMenu, "popup", lambda self, *args: shown.append(self))
    window.show_canvas_menu(QPoint(10, 10))
    assert shown == [window.image_menu]


def test_comparison_accepts_up_to_six_and_warns_above(qtbot, window, monkeypatch, patterned, tmp_path):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text, *args: warnings.append(text))
    monkeypatch.setattr(type(window), "start_comparison", lambda self, paths: warnings.append(len(paths)))
    extra = []
    for number in range(5):
        path = tmp_path / f"extra{number}.png"
        patterned.save(path)
        extra.append(path)
    window.reload_workspace()
    qtbot.waitUntil(lambda: not window.loading and len(window.model.paths) == 8 and window.document is not None, timeout=10000)
    window.select_paths(window.model.paths[:7])
    window.compare_images()
    assert warnings == ["並べて比較できるのは6枚までです。6枚以下にしてください。"]
    window.select_paths(window.model.paths[:3])
    window.compare_images()
    assert warnings[-1] == 3


def test_each_comparison_view_zooms_on_its_own(qtbot, patterned, tmp_path):
    paths = [tmp_path / f"{name}.png" for name in "abcd"]
    dialog = ComparisonDialog(paths, [patterned] * 4)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: all(view.scale > 0 for view in dialog.views))
    dialog.fit()
    scales = [view.scale for view in dialog.views]
    dialog.views[0].zoom(2)
    assert dialog.views[0].scale == scales[0] * 2 and [view.scale for view in dialog.views[1:]] == scales[1:]
    dialog.linked.setChecked(True)
    assert all(view.scale == dialog.views[0].scale for view in dialog.views)


def test_duplicates_go_to_the_trash_after_choosing_which_to_keep(qtbot, window, monkeypatch):
    trashed = []
    class FakeFile:
        @staticmethod
        def moveToTrash(path):
            trashed.append(Path(path))
            Path(path).unlink()
            return True
    monkeypatch.setattr(workbench, "QFile", FakeFile)
    monkeypatch.setattr(type(window), "confirm_dialog", lambda self, dialog, accepted=None: True)
    first, second, third = window.model.paths
    window.analyze_duplicates()
    qtbot.waitUntil(lambda: window.batch_job is None and "重複をごみ箱へ移しました" in window.status.text(), timeout=10000)
    assert sorted(trashed) == sorted([second, third]) and first.exists()
    assert window.model.paths == [first]


def test_tabs_can_be_renamed_and_remember_the_name(qtbot, tabs, tmp_path, patterned, monkeypatch):
    folder = picture(tmp_path / "shots" / "a.png", patterned).parent
    page = open_page(qtbot, tabs, folder)
    page.set_custom_title("  仕上げ  候補 ")
    index = tabs.tabs.indexOf(page)
    assert tabs.tabs.tabText(index) == "仕上げ 候補" and page.workspace_label.text() == "仕上げ 候補"
    assert page.workspace_state(session=True)["title"] == "仕上げ 候補"
    assert tabs.session_state()["tabs"][0]["workspace"]["title"] == "仕上げ 候補"
    page.set_custom_title("")
    assert tabs.tabs.tabText(index) == "shots" and "title" not in page.workspace_state()
    monkeypatch.setattr(type(page), "confirm_dialog", lambda self, dialog, accepted=None: dialog.setTextValue("別名") or True)
    tabs.rename_tab(page)
    assert tabs.tabs.tabText(index) == "別名"


def test_ready_hint_follows_the_save_settings(window):
    window.auto.setChecked(True)
    window.overwrite.setChecked(True)
    assert window.ready_hint() == "なぞると自動保存 · →で次へ · Enterで上書き保存して次へ"
    window.info(window.ready_hint())
    window.auto.setChecked(False)
    assert window.status.text() == window.ready_hint() == "なぞって加工 · →で次へ · Enterで上書き保存して次へ"
    window.overwrite.setChecked(False)
    assert window.ready_hint().endswith("Enterで保存して次へ")
    assert "· ←" in window.previous.toolTip() and "Left" not in window.previous.toolTip()
