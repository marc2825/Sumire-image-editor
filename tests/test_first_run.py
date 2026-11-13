"""First-run save choice and the record location for new and upgraded profiles."""
import pytest
from PySide6.QtWidgets import QDialog

from sumire.onboarding import FirstRunDialog
from sumire.preferences import Preferences
from sumire.storage import record_path
from sumire.workspace_tabs import WorkspaceWindow

from test_gui import draw, wait_saved
from test_workspace_tabs import open_page, picture, tabs


def choose(monkeypatch, mode, backup=True, accept=True):
    def run(dialog):
        if mode == "overwrite":
            dialog.overwrite_choice.setChecked(True)
        elif mode == "separate":
            dialog.separate_choice.setChecked(True)
        dialog.backup.setChecked(backup)
        return QDialog.DialogCode.Accepted if accept else QDialog.DialogCode.Rejected
    monkeypatch.setattr(FirstRunDialog, "exec", run)


def test_start_button_waits_for_an_explicit_choice(qtbot):
    dialog = FirstRunDialog()
    qtbot.addWidget(dialog)
    assert dialog.save_mode() is None and not dialog.start_button.isEnabled()
    dialog.separate_choice.setChecked(True)
    assert dialog.start_button.isEnabled()
    assert dialog.settings() == {"overwrite": False, "metadata_backup": True, "strip_metadata": False}


def test_new_profile_chooses_separate_folder_and_app_records(qtbot, tabs, monkeypatch, tmp_path, patterned):
    assert tabs.first_run
    choose(monkeypatch, "separate", backup=False)
    assert tabs.first_run_setup()
    data = Preferences().data
    assert data["storage"] == "app"
    assert data["settings"]["overwrite"] is False and data["settings"]["metadata_backup"] is False
    assert not tabs.welcome.overwrite.isChecked() and not tabs.welcome.metadata_backup.isChecked()
    assert not tabs.first_run_setup()
    source = picture(tmp_path / "photos" / "one.png", patterned)
    page = open_page(qtbot, tabs, source.parent)
    assert not page.overwrite.isChecked()


def test_new_profile_keeps_recovery_records_out_of_image_folder(qtbot, tabs, monkeypatch, tmp_path, patterned):
    choose(monkeypatch, "overwrite")
    tabs.first_run_setup()
    source = picture(tmp_path / "photos" / "one.png", patterned)
    page = open_page(qtbot, tabs, source.parent)
    assert page.overwrite.isChecked() and page.metadata_backup.isChecked()
    draw(page)
    wait_saved(qtbot, page)
    page.set_review_label("accepted")
    assert not list(source.parent.glob(".sumire-index.sqlite3*"))
    database = record_path(source.parent)
    assert database.is_file() and database.is_relative_to(Preferences().path.parent / "records")


def test_closing_the_dialog_keeps_defaults_and_is_not_asked_again(tabs, monkeypatch):
    choose(monkeypatch, None, accept=False)
    assert tabs.first_run_setup()
    data = Preferences().data
    assert data["storage"] == "app" and "settings" not in data
    assert tabs.welcome.overwrite.isChecked()
    assert "初期設定" in tabs.welcome.status.text()
    restarted = WorkspaceWindow()
    assert not restarted.first_run and not restarted.first_run_setup()
    restarted.close()


@pytest.mark.parametrize("data", [{"settings": {"overwrite": True}}, {"inputs": [], "recent": []}])
def test_existing_profile_keeps_records_in_image_folders(tmp_path, data):
    Preferences().save(data)
    host = WorkspaceWindow()
    try:
        assert not host.first_run and not host.first_run_setup()
        assert "storage" not in Preferences().data
        assert record_path(tmp_path / "photos") == (tmp_path / "photos" / ".sumire-index.sqlite3").resolve()
    finally:
        host.close()


def test_the_dialog_says_what_closing_it_means_and_that_is_what_happens(qtbot, tabs, monkeypatch):
    from PySide6.QtWidgets import QLabel
    dialog = FirstRunDialog()
    qtbot.addWidget(dialog)
    texts = " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert "選ばずに閉じた場合は、元画像に上書きして自動で保存します。" in texts
    choose(monkeypatch, None, accept=False)
    tabs.first_run_setup()
    assert tabs.welcome.overwrite.isChecked() and tabs.welcome.auto.isChecked()
