"""First-run save choice and the record location for new and upgraded profiles."""
import pytest
from PySide6.QtWidgets import QDialog

from sumire.onboarding import FirstRunDialog
from sumire.preferences import Preferences
from sumire.storage import record_path
from sumire.workspace_tabs import WorkspaceWindow

from test_gui import draw, wait_saved
from test_workspace_tabs import open_page, picture, tabs


@pytest.fixture(autouse=True)
def real_default(monkeypatch):
    from sumire import window
    monkeypatch.setattr(window, "OVERWRITE_DEFAULT", False)


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


def test_closing_the_dialog_saves_to_a_separate_folder_and_is_not_asked_again(tabs, monkeypatch):
    """Closing without a choice must never lead to replacing originals."""
    choose(monkeypatch, None, accept=False)
    assert tabs.first_run_setup()
    data = Preferences().data
    assert data["storage"] == "app" and data["settings"] == {"overwrite": False}
    assert not tabs.welcome.overwrite.isChecked() and tabs.welcome.auto.isChecked()
    assert "別フォルダー" in tabs.welcome.status.text()
    restarted = WorkspaceWindow()
    try:
        assert not restarted.first_run and not restarted.first_run_setup()
        assert not restarted.welcome.overwrite.isChecked()
    finally:
        restarted.close()


def test_a_new_profile_never_starts_by_overwriting(tabs, monkeypatch):
    """Before the choice is made, and even if it cannot be saved, the default keeps originals."""
    assert tabs.first_run and not tabs.welcome.overwrite.isChecked()
    choose(monkeypatch, None, accept=False)
    monkeypatch.setattr(Preferences, "save", lambda self, data: (_ for _ in ()).throw(OSError("disk full")))
    assert not tabs.first_run_setup()
    assert not tabs.welcome.overwrite.isChecked()


@pytest.mark.parametrize("data", [{"settings": {"overwrite": True}}, {"inputs": [], "recent": []},
                                  {"settings": {"auto": True}}])
def test_existing_profile_keeps_records_in_image_folders(tmp_path, data):
    Preferences().save(data)
    host = WorkspaceWindow()
    try:
        assert not host.first_run and not host.first_run_setup()
        # A profile from before the first-run choice keeps overwriting, as it always did.
        assert host.welcome.overwrite.isChecked()
        assert "storage" not in Preferences().data
        assert record_path(tmp_path / "photos") == (tmp_path / "photos" / ".sumire-index.sqlite3").resolve()
    finally:
        host.close()


def test_the_dialog_says_what_closing_it_means_and_that_is_what_happens(qtbot, tabs, monkeypatch):
    from PySide6.QtWidgets import QLabel
    dialog = FirstRunDialog()
    qtbot.addWidget(dialog)
    texts = " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert "選ばずに閉じた場合は、元画像を変更せず、別フォルダーに保存します。" in texts
    choose(monkeypatch, None, accept=False)
    tabs.first_run_setup()
    assert not tabs.welcome.overwrite.isChecked() and tabs.welcome.auto.isChecked()


def test_an_existing_choice_to_separate_is_kept(tmp_path):
    Preferences().save({"settings": {"overwrite": False, "auto": False}})
    host = WorkspaceWindow()
    try:
        assert not host.welcome.overwrite.isChecked() and not host.welcome.auto.isChecked()
    finally:
        host.close()
