"""Offline help, navigation, and explicitly configured GitHub documentation links."""
import pytest
from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QMessageBox

from sumire import help as help_module
from sumire.help import HelpDialog, TOPICS, github_document_url, read_help_document
from sumire.workspace_tabs import WorkspaceWindow

from test_gui import window


@pytest.fixture
def help_dialog(qtbot):
    dialog = HelpDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


def test_bundled_help_loads_all_topics_without_opening_browser(help_dialog, monkeypatch):
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    for index, topic in enumerate(TOPICS):
        help_dialog.topics.setCurrentRow(index)
        text = help_dialog.browser.toPlainText()
        assert text.strip() and "読み込めませんでした" not in text
    assert "圧縮は暗号化ではありません" in read_help_document("METADATA.md")
    assert not opened and not help_dialog.online_button.isEnabled()


def test_search_filters_topics_and_recovers_from_no_matches(help_dialog):
    help_dialog.search.setText("Ctrl+Tab")
    visible = [i for i in range(len(TOPICS)) if not help_dialog.topics.item(i).isHidden()]
    assert visible and "Ctrl+Tab" in help_dialog.browser.toPlainText()
    help_dialog.search.setText("no-such-help-topic-987")
    assert "見つかりません" in help_dialog.browser.toPlainText()
    assert not help_dialog.online_button.isEnabled()
    help_dialog.search.clear()
    assert all(not help_dialog.topics.item(i).isHidden() for i in range(len(TOPICS)))
    assert "見つかりません" not in help_dialog.browser.toPlainText()


def test_links_between_bundled_documents_stay_offline(help_dialog, monkeypatch):
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    help_dialog.search.setText("Ctrl+Tab")
    help_dialog.open_link(QUrl("METADATA.md"))
    assert help_dialog.search.text() == ""
    assert "メタデータの削除・退避・復元" in help_dialog.browser.toPlainText()
    assert not opened


def test_enter_in_help_search_keeps_dialog_open_and_does_not_open_online(help_dialog, monkeypatch):
    monkeypatch.setattr(help_module, "PUBLIC_DOCUMENTATION_REPOSITORY", "https://github.com/example/sumire")
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    help_dialog.search.setText("上書き")
    help_dialog.search.setFocus()
    QTest.keyClick(help_dialog.search, Qt.Key.Key_Return)
    assert help_dialog.isVisible() and not opened


def test_unset_public_url_does_not_use_git_remote(help_dialog, monkeypatch):
    assert help_module.PUBLIC_DOCUMENTATION_REPOSITORY == ""
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    help_dialog.open_online()
    assert not opened and github_document_url("USER_GUIDE.md") == ""


def test_github_button_opens_the_selected_document(help_dialog, monkeypatch):
    monkeypatch.setattr(help_module, "PUBLIC_DOCUMENTATION_REPOSITORY", "https://github.com/example/sumire")
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True)
    index = next(i for i, topic in enumerate(TOPICS) if topic.filename == "USER_GUIDE.md")
    help_dialog.topics.setCurrentRow(index)
    assert help_dialog.online_button.isEnabled()
    help_dialog.online_button.click()
    assert opened == ["https://github.com/example/sumire/blob/main/sumire/help_docs/USER_GUIDE.md"]
    assert help_dialog.isVisible()


def test_browser_failure_keeps_offline_help_available(help_dialog, monkeypatch):
    monkeypatch.setattr(help_module, "PUBLIC_DOCUMENTATION_REPOSITORY", "https://github.com/example/sumire")
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: False)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[1:]))
    help_dialog.show_topic(0)
    help_dialog.open_online()
    assert warnings and "この画面でも読めます" in warnings[0][1]
    assert "Sumīreの機能一覧" in help_dialog.browser.toPlainText()


def test_missing_bundled_file_does_not_crash(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(help_module.resources, "files", lambda name: tmp_path)
    assert "読み込めませんでした" in read_help_document("USER_GUIDE.md")
    assert "指定した説明はありません" in read_help_document("../private.txt")


def test_question_button_and_f1_open_help_without_changing_document(window, monkeypatch):
    dialogs = []
    monkeypatch.setattr(QDialog, "exec", lambda dialog: dialogs.append(dialog.windowTitle()) or QDialog.DialogCode.Rejected)
    document, pixels, path = window.document, window.document.image.tobytes(), window.document.path
    window.help_button.click()
    QTest.keyClick(window.canvas, Qt.Key.Key_F1)
    assert len(dialogs) == 2 and all("ヘルプ" in title for title in dialogs)
    assert window.document is document and document.path == path and document.image.tobytes() == pixels


def test_help_button_is_available_on_initial_screen(qtbot, monkeypatch):
    host = WorkspaceWindow()
    host.show()
    dialogs = []
    monkeypatch.setattr(QDialog, "exec", lambda dialog: dialogs.append(dialog.windowTitle()) or QDialog.DialogCode.Rejected)
    assert host.welcome.help_button.isVisible()
    host.welcome.help_button.click()
    assert len(dialogs) == 1 and host.tabs.count() == 0
    host.close()


def test_headings_and_paragraphs_have_spacing(help_dialog):
    """Headings get room above them; paragraphs are separated; table cells stay compact."""
    for index in range(len(TOPICS)):
        help_dialog.topics.setCurrentRow(index)
        document = help_dialog.browser.document()
        headings, paragraphs, block = [], [], document.begin()
        while block.isValid():
            fmt = block.blockFormat()
            (headings if fmt.headingLevel() else paragraphs).append(fmt)
            block = block.next()
        assert headings[0].topMargin() == 0
        assert all(fmt.topMargin() >= 18 and fmt.bottomMargin() >= 8 for fmt in headings[1:])
        assert any(fmt.bottomMargin() >= 8 for fmt in paragraphs)
