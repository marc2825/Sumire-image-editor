"""Bundled user documentation, with optional links to its public GitHub copy."""
from .i18n import DEFAULT, language, tr
from dataclasses import dataclass
from importlib import resources
from urllib.parse import quote, urlsplit

from PySide6.QtCore import QEvent, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextFormat, QTextLength
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLineEdit,
    QMessageBox, QPushButton, QSplitter, QTextBrowser, QVBoxLayout,
)

from .theme import TOKENS
from .ui import TopicSidebar

# Set only after a public documentation repository has been chosen.
# Never derive this from the developer's (possibly private) Git remote.
PUBLIC_DOCUMENTATION_REPOSITORY = ""
DOCUMENTATION_REF = "main"


@dataclass(frozen=True)
class HelpTopic:
    title: str
    filename: str


TOPICS = (
    HelpTopic(tr("機能一覧"), "FEATURES.md"),
    HelpTopic(tr("はじめての操作"), "USER_GUIDE.md"),
    HelpTopic(tr("ショートカット"), "SHORTCUTS.md"),
    HelpTopic(tr("メタデータ・復元"), "METADATA.md"),
    HelpTopic(tr("よくある質問"), "FAQ.md"),
)


def help_folder(code=None):
    """Japanese help is in help_docs/, the other languages in help_docs/<code>/."""
    code = language() if code is None else code
    return ("help_docs",) if code == DEFAULT else ("help_docs", code)


def read_help_document(filename):
    if filename not in {topic.filename for topic in TOPICS}:
        return tr("# ヘルプ\n\n指定した説明はありません。")
    try:
        try:
            return resources.files("sumire").joinpath(*help_folder(), filename).read_text(encoding="utf-8")
        except FileNotFoundError:
            # A page not translated yet is shown in Japanese.
            return resources.files("sumire").joinpath("help_docs", filename).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return tr("# ヘルプを読み込めませんでした\n\n配布ZIPをすべて展開し直してください。画像や作業内容への影響はありません。")


def github_document_url(filename, repository=None):
    repository = PUBLIC_DOCUMENTATION_REPOSITORY if repository is None else repository
    if not repository or filename not in {topic.filename for topic in TOPICS}:
        return ""
    parsed = urlsplit(repository)
    parts = parsed.path.strip("/").split("/")
    if (parsed.scheme != "https" or parsed.netloc != "github.com" or len(parts) != 2
            or any(part in ("", ".", "..") for part in parts) or parsed.query or parsed.fragment):
        return ""
    folder = "/".join(help_folder())
    return f"https://github.com/{'/'.join(parts)}/blob/{quote(DOCUMENTATION_REF, safe='')}/sumire/{folder}/{filename}"


def space_blocks(document):
    """Give headings room above them and paragraphs a little air.

    Qt renders Markdown with almost no spacing between blocks, which made the
    help read as one dense column. Table cells stay compact. Section headings
    (level 2) get the accent colour and a rule underneath, so they stand apart
    from the text instead of being only a little larger.
    """
    document.setDocumentMargin(14)
    cursor = QTextCursor(document)
    block, first = document.begin(), True
    while block.isValid():
        cursor.setPosition(block.position())
        if cursor.currentTable() is None:
            fmt = block.blockFormat()
            level = fmt.headingLevel()
            if level:
                fmt.setTopMargin(0 if first else (28 if level <= 2 else 18))
                fmt.setBottomMargin(12 if level == 2 else 10)
                if level == 2:
                    fmt.setProperty(QTextFormat.Property.BlockTrailingHorizontalRulerWidth,
                                    QTextLength(QTextLength.Type.PercentageLength, 100))
                heading = QTextCharFormat()
                heading.setForeground(QColor(TOKENS["accent"] if level <= 2 else TOKENS["text_strong"]))
                heading.setFontWeight(700)
                text = QTextCursor(block)
                text.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                text.mergeCharFormat(heading)
            else:
                fmt.setTopMargin(0)
                fmt.setBottomMargin(4 if block.textList() else 10)
            fmt.setLineHeight(150, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
            cursor.setBlockFormat(fmt)
            first = False
        block = block.next()


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("helpDialog")
        self.setWindowTitle(tr("Sumīre ヘルプ"))
        self.setMinimumSize(520, 320)
        available = self.screen().availableGeometry()
        self.resize(min(900, available.width() - 48), min(680, available.height() - 80))
        self.setSizeGripEnabled(True)
        self.documents = [read_help_document(topic.filename) for topic in TOPICS]
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("ヘルプを検索（例：上書き、タブ、メタデータ）"))
        self.search.setAccessibleName(tr("ヘルプを検索"))
        self.search.setClearButtonEnabled(True)
        self.search.installEventFilter(self)
        layout.addWidget(self.search)
        splitter = QSplitter()
        self.sidebar = TopicSidebar([topic.title for topic in TOPICS], tr("ヘルプの項目"))
        self.sidebar.setMinimumWidth(150)
        self.sidebar.setMaximumWidth(240)
        self.topics = self.sidebar.topics
        self.sidebar.headingChosen.connect(self.jump_to_heading)
        self.heading_blocks = []
        splitter.addWidget(self.sidebar)
        self.browser = QTextBrowser()
        self.browser.setAccessibleName(tr("ヘルプ本文"))
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.anchorClicked.connect(self.open_link)
        splitter.addWidget(self.browser)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([190, 650])
        layout.addWidget(splitter, 1)
        footer = QHBoxLayout()
        self.online_button = QPushButton(tr("GitHubでこのページを開く"))
        self.online_button.clicked.connect(self.open_online)
        footer.addWidget(self.online_button)
        footer.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        layout.addLayout(footer)
        self.topics.currentRowChanged.connect(self.show_topic)
        self.search.textChanged.connect(self.filter_topics)
        self.topics.setCurrentRow(0)

    def show_topic(self, index):
        if not 0 <= index < len(TOPICS):
            return
        self.browser.setMarkdown(self.documents[index])
        space_blocks(self.browser.document())
        self.heading_blocks = []
        block = self.browser.document().begin()
        while block.isValid():
            if block.blockFormat().headingLevel() == 2:
                self.heading_blocks.append(block.position())
            block = block.next()
        self.sidebar.set_headings([self.browser.document().findBlock(position).text() for position in self.heading_blocks])
        self.browser.moveCursor(self.browser.textCursor().MoveOperation.Start)
        text = self.search.text().strip()
        if text:
            self.browser.find(text)
        available = bool(github_document_url(TOPICS[index].filename))
        self.online_button.setEnabled(available)
        self.online_button.setText(tr("GitHubでこのページを開く") if available else tr("GitHub版は公開準備中"))
        self.online_button.setToolTip(tr("表示中のページを既定のブラウザーで開きます。") if available else "")

    def jump_to_heading(self, row):
        if not 0 <= row < len(self.heading_blocks):
            return
        document = self.browser.document()
        block = document.findBlock(self.heading_blocks[row])
        top = document.documentLayout().blockBoundingRect(block).top()
        self.browser.verticalScrollBar().setValue(int(top))

    def filter_topics(self, query):
        query = query.strip().casefold()
        visible = []
        for index, topic in enumerate(TOPICS):
            matches = not query or query in (topic.title + "\n" + self.documents[index]).casefold()
            self.topics.item(index).setHidden(not matches)
            if matches:
                visible.append(index)
        if not visible:
            self.browser.setPlainText(tr("一致する説明が見つかりません。別の言葉で検索してください。"))
            self.sidebar.set_headings([])
            self.online_button.setEnabled(False)
            return
        current = self.topics.currentRow()
        index = current if current in visible else visible[0]
        self.topics.setCurrentRow(index)
        self.show_topic(index)

    def eventFilter(self, watched, event):
        if watched is self.search and event.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                event.accept()
                if event.type() == QEvent.Type.KeyPress and self.search.text().strip():
                    if not self.browser.find(self.search.text().strip()):
                        self.browser.moveCursor(self.browser.textCursor().MoveOperation.Start)
                        self.browser.find(self.search.text().strip())
                return True
        return super().eventFilter(watched, event)

    def open_link(self, url):
        if url.isRelative():
            if not url.path():
                self.browser.scrollToAnchor(url.fragment())
                return
            for index, topic in enumerate(TOPICS):
                if url.path() == topic.filename:
                    self.search.clear()
                    self.topics.setCurrentRow(index)
                    if url.fragment():
                        self.browser.scrollToAnchor(url.fragment())
                    return
        elif url.scheme() in ("https", "http"):
            self.open_browser(url)

    def open_online(self):
        index = self.topics.currentRow()
        if 0 <= index < len(TOPICS):
            url = github_document_url(TOPICS[index].filename)
            if url:
                self.open_browser(QUrl(url))

    def open_browser(self, url):
        if not QDesktopServices.openUrl(url):
            QMessageBox.warning(self, tr("ブラウザーを開けません"), tr("既定のブラウザーを確認してください。操作方法はこの画面でも読めます。"))
