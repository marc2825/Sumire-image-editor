"""Restart the actual tab host against its persisted session."""
import pytest
from PIL import Image
from PySide6.QtWidgets import QMessageBox

from sumire.preferences import Preferences
from sumire.projects import write_project
from sumire.workspace_tabs import WorkspaceWindow

from test_gui import draw
from test_workspace_tabs import open_page, picture, ready, tabs


@pytest.fixture
def restarted(qtbot):
    hosts = []
    def make():
        host = WorkspaceWindow()
        hosts.append(host)
        host.show()
        host.resume_session()
        return host
    yield make
    for host in hosts:
        for page in host.workspaces():
            qtbot.waitUntil(lambda: not page.busy() and not page.saving, timeout=15000)
            page.auto.setChecked(False)
            page.autosave_timer.stop()
            if page.document:
                page.document.saved_revision = page.document.revision
        host.close_all_tabs()
        qtbot.waitUntil(lambda: host.tabs.count() == 0)
        host.close()


def finish_close(qtbot, host):
    host.close()
    qtbot.waitUntil(lambda: not host.isVisible(), timeout=15000)


def test_restart_restores_order_active_tab_duplicate_folder_settings_and_search(qtbot, tabs, restarted, tmp_path, patterned):
    one = picture(tmp_path / "日本語 & folder" / "one.png", patterned)
    two = picture(one.parent / "two.png", patterned)
    a = open_page(qtbot, tabs, one.parent)
    a.auto.setChecked(False)
    a.overwrite.setChecked(False)
    a.brush.setValue(111)
    a.sort_combo.setCurrentIndex(a.sort_combo.findData("manual"))
    a.replace_list([two, one])
    a.search.setText("two")
    qtbot.waitUntil(lambda: a.document.path == two and a.canvas.ready and not a.loading)
    b = open_page(qtbot, tabs, one.parent, "new")
    b.auto.setChecked(False)
    b.overwrite.setChecked(True)
    b.brush.setValue(222)
    empty = tabs.new_tab()
    empty.brush.setValue(333)
    tabs.tabs.tabBar().moveTab(2, 0)
    tabs.tabs.setCurrentWidget(b)
    originals = {path: path.read_bytes() for path in (one, two)}
    finish_close(qtbot, tabs)
    assert len(Preferences().data["session"]["tabs"]) == 3
    host = restarted()
    assert host.tabs.count() == 3 and host.tabs.currentIndex() == 2
    restored_b = host.current_workspace()
    ready(qtbot, restored_b)
    assert restored_b.brush.value() == 222 and restored_b.overwrite.isChecked()
    restored_a = host.tabs.widget(1)
    assert restored_a.deferred_session is not None and restored_a.document is None
    assert host.tabs.widget(0).brush.value() == 333
    host.tabs.setCurrentWidget(restored_a)
    ready(qtbot, restored_a)
    assert restored_a.model.paths == [two, one] and restored_a.document.path == two
    assert restored_a.search.text() == "two" and restored_a.visible_paths() == [two]
    assert not restored_a.auto.isChecked() and not restored_a.overwrite.isChecked()
    assert restored_a.brush.value() == 111
    assert {path: path.read_bytes() for path in originals} == originals


@pytest.mark.parametrize("all_tabs", [False, True])
def test_closed_tabs_stay_closed_after_quitting(qtbot, tabs, restarted, tmp_path, patterned, all_tabs):
    a = open_page(qtbot, tabs, picture(tmp_path / "a.png", patterned))
    b = open_page(qtbot, tabs, picture(tmp_path / "b.png", patterned), "new")
    if all_tabs:
        tabs.close_all_tabs()
        qtbot.waitUntil(lambda: tabs.tabs.count() == 0)
    else:
        tabs.close_tab(a)
        qtbot.waitUntil(lambda: tabs.tabs.count() == 1)
    expected = b.document.path if not all_tabs else None
    finish_close(qtbot, tabs)
    host = restarted()
    if all_tabs:
        assert host.tabs.count() == 0 and host.stack.currentWidget() is host.welcome
        assert not host.welcome.workspace_label.isVisible()
        assert not host.welcome.workspace_separator.isVisible()
    else:
        ready(qtbot, host.current_workspace())
        assert host.tabs.count() == 1 and host.current_workspace().document.path == expected


def test_missing_and_invalid_inputs_are_skipped_with_empty_tab_preserved(qtbot, restarted, tmp_path, patterned):
    source = picture(tmp_path / "valid.png", patterned)
    Preferences().save({"session": {"version": 1, "current": 0, "tabs": [
        {"inputs": [str(tmp_path / "missing.png")]}, None, {"inputs": 42},
        {"inputs": [str(source), "\x00bad", str(tmp_path / "gone.png")]}, {"inputs": []}]}})
    host = restarted()
    ready(qtbot, host.current_workspace())
    assert host.tabs.count() == 2 and host.current_workspace().model.paths == [source]
    assert host.tabs.widget(1).workspace_inputs == []
    host.resume_session()
    assert host.tabs.count() == 2


def test_cancelled_application_close_does_not_commit_session(qtbot, tabs, tmp_path, patterned, monkeypatch):
    a = open_page(qtbot, tabs, picture(tmp_path / "a.png", patterned))
    a.auto.setChecked(False)
    draw(a)
    ready(qtbot, a)
    open_page(qtbot, tabs, picture(tmp_path / "b.png", patterned), "new")
    tabs.tabs.setCurrentWidget(a)
    monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.Cancel)
    tabs.close()
    qtbot.waitUntil(lambda: tabs.close_mode is None)
    assert tabs.isVisible() and tabs.tabs.count() == 1 and a.document.dirty
    assert tabs.closing_session is None and "session" not in tabs.preferences.data


def test_session_save_failure_keeps_window_open_and_can_retry(qtbot, tabs, restarted, tmp_path, patterned, monkeypatch):
    source = picture(tmp_path / "a.png", patterned)
    open_page(qtbot, tabs, source)
    save = tabs.preferences.save
    def fail(_):
        raise OSError("synthetic settings failure")
    monkeypatch.setattr(tabs.preferences, "save", fail)
    tabs.close()
    qtbot.waitUntil(lambda: "タブ一覧を保存できません" in tabs.welcome.status.text())
    assert tabs.isVisible() and "タブ一覧を保存できません" in tabs.welcome.status.text()
    assert tabs.closing_session["tabs"][0]["inputs"] == [str(source)]
    monkeypatch.setattr(tabs.preferences, "save", save)
    finish_close(qtbot, tabs)
    host = restarted()
    ready(qtbot, host.current_workspace())
    assert host.current_workspace().document.path == source


def test_inactive_session_state_survives_another_exit_without_loading(qtbot, restarted, tmp_path, patterned):
    a = picture(tmp_path / "a.png", patterned)
    b = picture(tmp_path / "b.png", patterned)
    Preferences().save({"session": {"version": 1, "current": 1, "tabs": [
        {"inputs": [str(a)], "workspace": {"order": [str(a)], "current": str(a)}, "settings": {"brush": 127}},
        {"inputs": [str(b)]}]}})
    host = restarted()
    ready(qtbot, host.current_workspace())
    assert host.tabs.widget(0).document is None
    finish_close(qtbot, host)
    host2 = restarted()
    ready(qtbot, host2.current_workspace())
    a_page = host2.tabs.widget(0)
    host2.tabs.setCurrentWidget(a_page)
    ready(qtbot, a_page)
    assert a_page.document.path == a and a_page.brush.value() == 127


def test_project_tab_is_restored_without_writing_images(qtbot, tabs, restarted, tmp_path, patterned):
    project = tmp_path / "test.sumire"
    write_project(project, patterned, patterned, Image.new("L", patterned.size),
                  {"edited": False, "original_edited": False, "original_known": True})
    page = open_page(qtbot, tabs, project)
    page.auto.setChecked(False)
    page.document.saved_revision = page.document.revision
    before = project.read_bytes()
    finish_close(qtbot, tabs)
    host = restarted()
    ready(qtbot, host.current_workspace())
    assert host.current_workspace().document.project
    assert project.read_bytes() == before
    assert not list(tmp_path.glob("Sumīre/*.png"))


def test_rename_updates_deferred_file_tab_and_exclusions(qtbot, restarted, tmp_path, patterned):
    source = picture(tmp_path / "a.png", patterned)
    other = picture(tmp_path / "b.png", patterned)
    Preferences().save({"session": {"version": 1, "current": 0, "tabs": [
        {"inputs": [str(source)]},
        {"inputs": [str(source)], "workspace": {"current": str(source)}},
        {"inputs": [str(source.parent)], "workspace": {"excluded": [str(source)]}}]}})
    host = restarted()
    page = host.current_workspace()
    ready(qtbot, page)
    target = source.with_stem("renamed")
    page.rename_paths({source: target})
    qtbot.waitUntil(lambda: not page.busy() and page.document.path == target)
    deferred = host.tabs.widget(1)
    assert deferred.workspace_inputs == [str(target)]
    host.tabs.setCurrentWidget(deferred)
    ready(qtbot, deferred)
    assert deferred.document.path == target
    excluded = host.tabs.widget(2)
    host.tabs.setCurrentWidget(excluded)
    ready(qtbot, excluded)
    assert excluded.model.paths == [other] and target in excluded.excluded_paths


def test_restore_tab_with_all_explicit_images_excluded(qtbot, restarted, tmp_path, patterned):
    source = picture(tmp_path / "a.png", patterned)
    Preferences().save({"session": {"version": 1, "current": 0, "tabs": [
        {"inputs": [str(source)], "workspace": {"excluded": [str(source)]}}]}})
    host = restarted()
    page = host.current_workspace()
    qtbot.waitUntil(lambda: not page.loading)
    assert page.workspace_inputs == [str(source)] and page.model.paths == [] and page.document is None
    page.reload_workspace()
    ready(qtbot, page)
    assert page.document.path == source
