"""Editable bindings must stay unambiguous, persistent, and safe while typing."""
import pytest
from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox

from sumire.preferences import Preferences
from sumire.shortcuts import ShortcutDialog, defaults, load_bindings

from test_gui import window
from test_workspace_tabs import tabs, open_page, picture


def set_key(dialog, command, key, index=0):
    dialog.editors[command][index].setKeySequence(QKeySequence(key))


@pytest.mark.parametrize("key,label", [(Qt.Key.Key_1, "accepted"), (Qt.Key.Key_2, "pending"), (Qt.Key.Key_3, "rejected")])
def test_default_review_keys_label_without_zooming(qtbot, window, key, label):
    page = window
    scale = page.canvas.scale
    QTest.keyClick(page.canvas, key)
    assert page.model.labels[page.document.path] == label
    assert page.canvas.scale == scale
    QTest.keyClick(page.canvas, key)
    assert page.model.labels[page.document.path] == label  # pressing it again keeps the label
    QTest.keyClick(page.canvas, Qt.Key.Key_0, Qt.KeyboardModifier.AltModifier)
    assert page.document.path not in page.model.labels
    QTest.keyClick(page.canvas, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
    assert page.canvas.scale == 1
    assert [page.key_hints[label].key for label in ("accepted", "pending", "rejected")] == ["1", "2", "3"]


def test_number_keys_are_text_in_search_and_rename(qtbot, window):
    window.search.setFocus()
    QTest.keyClicks(window.search, "123")
    assert window.search.text() == "123"
    assert not window.model.labels
    window.search.clear()
    window.rename_current()
    window.file_label.editor.selectAll()
    QTest.keyClicks(window.file_label.editor, "123")
    assert window.file_label.editor.text() == "123"
    assert not window.model.labels
    window.file_label.cancel_edit()


def test_dialog_cancel_conflict_clear_reset_and_save(qtbot, tmp_path):
    preferences = Preferences()
    preferences.save({"settings": {"auto": False}, "other": "kept"})
    original = preferences.path.read_bytes()
    dialog = ShortcutDialog(preferences)
    qtbot.addWidget(dialog)
    set_key(dialog, "pending", "Q")
    dialog.reject()
    assert preferences.path.read_bytes() == original
    dialog = ShortcutDialog(preferences)
    qtbot.addWidget(dialog)
    set_key(dialog, "pending", "1")
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "重複" in dialog.error.text() and "「採用」" in dialog.error.text()
    assert preferences.path.read_bytes() == original
    set_key(dialog, "pending", "")
    set_key(dialog, "accepted", "Q")
    dialog.accept()
    saved = Preferences()
    assert saved.data["other"] == "kept" and saved.data["settings"] == {"auto": False}
    assert load_bindings(saved)["pending"] == []
    assert load_bindings(saved)["accepted"] == ["Q"]
    dialog = ShortcutDialog(saved)
    qtbot.addWidget(dialog)
    reset = next(button for button in dialog.findChildren(QDialogButtonBox)[0].buttons() if button.text() == "初期設定に戻す")
    reset.click()
    dialog.accept()
    assert Preferences().data["shortcuts"] == {}
    assert load_bindings(Preferences()) == defaults()


def test_save_failure_leaves_dialog_and_bindings_unchanged(qtbot, monkeypatch):
    preferences = Preferences()
    dialog = ShortcutDialog(preferences)
    qtbot.addWidget(dialog)
    set_key(dialog, "pending", "Q")
    def fail(data):
        raise OSError("synthetic denied write")
    monkeypatch.setattr(preferences, "save", fail)
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "保存できません" in dialog.error.text()
    assert load_bindings(preferences) == defaults()


@pytest.mark.parametrize("changes", [{"pending": ["1"]}, {"save": ["Ctrl+K, Ctrl+S"]},
                                     {"save": "Ctrl+K"}, {"pan": ["Ctrl"]}, {"save": [None]}])
def test_invalid_profiles_fall_back_to_working_defaults(changes):
    preferences = Preferences()
    preferences.data = {"shortcuts": changes}
    assert load_bindings(preferences) == defaults()


def test_settings_capture_keys_then_apply_to_all_tabs_and_new_tabs(qtbot, tabs, tmp_path, patterned):
    source = picture(tmp_path / "test.png", patterned)
    a = open_page(qtbot, tabs, source)
    b = tabs.new_tab()
    tabs.tabs.setCurrentWidget(a)
    observed = {}
    def configure():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, ShortcutDialog)
        editor = dialog.editors["pending"][0]
        editor.setFocus()
        QTest.keyClick(editor, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier)
        assert tabs.tabs.count() == 2  # Capture cannot open a background tab.
        assert editor.keySequence().toString() == "Ctrl+T"
        set_key(dialog, "pending", "Q")
        set_key(dialog, "save", "Ctrl+K")
        set_key(dialog, "new_tab", "Ctrl+N")
        set_key(dialog, "mask", "V")
        observed["captured"] = True
        dialog.accept()
    QTimer.singleShot(50, configure)
    a.app_actions["shortcuts"].trigger()
    assert observed["captured"]
    assert a.bindings["pending"] == b.bindings["pending"] == ["Q"]
    assert "Ctrl+K" in a.manual_save.text() and "Ctrl+S" not in a.manual_save.text()
    assert "Q" in a.label_buttons["pending"].toolTip()
    assert "Ctrl+N" in a.new_tab_action.text() and "Ctrl+N" in tabs.tabs.add_button.toolTip()
    tabs.activateWindow()
    a.canvas.setFocus()
    qtbot.waitUntil(lambda: tabs.isActiveWindow() and QApplication.focusWidget() is a.canvas
                    and QApplication.activeModalWidget() is None)
    qtbot.wait(10)  # Let Qt finish closing and deleting the modal dialog.
    QTest.keyClick(a.canvas, Qt.Key.Key_2)
    assert source not in a.model.labels
    QTest.keyClick(a.canvas, Qt.Key.Key_Q)
    assert a.model.labels[source] == "pending"
    before = a.mask_toggle.isChecked()
    QTest.keyClick(a.canvas, Qt.Key.Key_M)
    assert a.mask_toggle.isChecked() == before
    QTest.keyClick(a.canvas, Qt.Key.Key_V)
    assert a.mask_toggle.isChecked() != before
    QTest.keyClick(a.canvas, Qt.Key.Key_N, Qt.KeyboardModifier.ControlModifier)
    assert tabs.tabs.count() == 3
    c = tabs.current_workspace()
    assert c.bindings["pending"] == ["Q"]
    assert load_bindings(Preferences())["save"] == ["Ctrl+K"]


def test_custom_hold_keys_compare_pan_and_release(qtbot, window):
    preferences = window.preferences
    preferences.save({**preferences.data, "shortcuts": {"compare": ["C"], "pan": ["P"]}})
    window._shortcuts()
    QTest.keyPress(window.canvas, Qt.Key.Key_C)
    assert window.canvas.compare
    QApplication.sendEvent(window.canvas, QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_C,
                                                   Qt.KeyboardModifier.NoModifier, "c", True))
    assert window.canvas.compare  # Holding the key through auto-repeat keeps comparing.
    QTest.keyRelease(window.canvas, Qt.Key.Key_C)
    assert not window.canvas.compare
    QTest.keyPress(window.canvas, Qt.Key.Key_P)
    assert window.canvas.space_down
    QTest.keyRelease(window.canvas, Qt.Key.Key_P)
    assert not window.canvas.space_down
    QTest.keyPress(window.canvas, Qt.Key.Key_Space)
    assert not window.canvas.space_down
    QTest.keyRelease(window.canvas, Qt.Key.Key_Space)
    QTest.keyPress(window.canvas, Qt.Key.Key_Tab)
    assert not window.canvas.compare
    QTest.keyRelease(window.canvas, Qt.Key.Key_Tab)


def test_empty_binding_disables_previous_key(qtbot, window):
    window.preferences.save({**window.preferences.data, "shortcuts": {"accepted": []}})
    window._shortcuts()
    QTest.keyClick(window.canvas, Qt.Key.Key_1)
    assert not window.model.labels
    assert not window.key_hints["accepted"].isVisible()
    assert "1" not in window.label_buttons["accepted"].toolTip()


def test_restart_loads_bindings_and_alternative_keys(qtbot):
    from sumire.window import Window
    Preferences().save({"shortcuts": {"pending": ["Q", "W"], "compare": [], "mask": ["Tab"]}})
    page = Window()
    qtbot.addWidget(page)
    assert page.bindings["pending"] == ["Q", "W"]
    assert page.canvas.bindings["mask"] == ["Tab"]
    assert page.bindings["compare"] == []
    assert "Q / W" in page.label_buttons["pending"].toolTip()
    page.close()


def test_canvas_binding_can_use_tab_and_compare_releases_with_modifier(qtbot, window):
    window.preferences.save({**window.preferences.data, "shortcuts": {"compare": ["Ctrl+C"], "mask": ["Tab"]}})
    window._shortcuts()
    before = window.mask_toggle.isChecked()
    QTest.keyClick(window.canvas, Qt.Key.Key_Tab)
    assert window.mask_toggle.isChecked() != before
    QTest.keyPress(window.canvas, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert window.canvas.compare
    QTest.keyRelease(window.canvas, Qt.Key.Key_C)  # A released modifier must not leave comparison stuck.
    assert not window.canvas.compare


def test_plus_button_follows_tabs_and_docks_only_on_overflow(qtbot, tabs):
    tabs.resize(1000, 720)
    tabs.new_tab()
    tabs.new_tab()
    bar, button = tabs.tabs.tabBar(), tabs.tabs.add_button
    qtbot.waitUntil(lambda: button.x() == bar.x() + bar.tabRect(1).right() + 5)
    tabs.grab()  # Painting must not let QTabWidget put the button back in its corner.
    assert button.x() == bar.x() + bar.tabRect(1).right() + 5
    assert button.geometry().left() > bar.tabRect(1).right()
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert tabs.tabs.count() == 3
    for index in range(8):
        tabs.new_tab()
    qtbot.waitUntil(lambda: bar.sizeHint().width() > bar.width())
    # On overflow it docks in the space kept for it, left of the app-wide controls.
    space = tabs.tabs.corner_space
    qtbot.waitUntil(lambda: button.x() == space.mapTo(tabs.tabs, space.rect().topLeft()).x())
    assert button.geometry().right() < tabs.tabs.trailing.mapTo(tabs.tabs, tabs.tabs.trailing.rect().topLeft()).x()
    tabs.resize(1900, 720)  # the tab row also holds the app-wide controls
    qtbot.waitUntil(lambda: bar.sizeHint().width() <= bar.width())
    qtbot.waitUntil(lambda: button.x() == bar.x() + bar.tabRect(tabs.tabs.count() - 1).right() + 5)
    tabs.tabs.tabBar().moveTab(0, tabs.tabs.count() - 1)
    page = tabs.tabs.widget(0)
    tabs.close_tab(page)
    qtbot.waitUntil(lambda: tabs.tabs.count() == 10)
    qtbot.waitUntil(lambda: button.x() == bar.x() + bar.tabRect(9).right() + 5)
