"""Reusable interface components shared by the main window panels."""
from __future__ import annotations
from .i18n import tr

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPalette
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QSpinBox, QStackedWidget, QStyle,
    QStyledItemDelegate, QStyleOptionComboBox, QStyleOptionViewItem, QStylePainter, QToolButton, QVBoxLayout, QWidget,
)

from .icons import app_mark, icon
from .theme import TOKENS, tint_caption


SEGMENTS_ROLE = Qt.ItemDataRole.UserRole + 40


def draw_segments(painter, rect, segments, base: QColor, font):
    """Draw text pieces side by side; a piece with a colour name is painted in that colour."""
    metrics = QFontMetrics(font)
    painter.setFont(font)
    x = rect.left()
    for text, color in segments:
        width = metrics.horizontalAdvance(text)
        painter.setPen(QColor(color) if color else base)
        painter.drawText(QRect(x, rect.top(), width + 2, rect.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        x += width


class SegmentDelegate(QStyledItemDelegate):
    """Popup rows of a SegmentComboBox: the normal row background, then coloured text pieces."""

    def paint(self, painter, option, index):
        segments = index.data(SEGMENTS_ROLE)
        if not segments:
            return super().paint(painter, option, index)
        item = QStyleOptionViewItem(option)
        self.initStyleOption(item, index)
        item.text = ""
        widget = option.widget
        style = widget.style() if widget else QGuiApplication.instance().style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, item, painter, widget)
        painter.save()
        draw_segments(painter, option.rect.adjusted(8, 0, -4, 0), segments,
                      option.palette.color(QPalette.ColorRole.Text), option.font)
        painter.restore()


class SegmentComboBox(QComboBox):
    """A combo box whose items may colour only part of their text (e.g. just 昇順 / 降順)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(SegmentDelegate(self))

    def add_segments(self, segments, data=None):
        self.addItem("".join(text for text, _ in segments), data)
        self.setItemData(self.count() - 1, list(segments), SEGMENTS_ROLE)

    def paintEvent(self, event):
        segments = self.itemData(self.currentIndex(), SEGMENTS_ROLE) if self.currentIndex() >= 0 else None
        if not segments:
            return super().paintEvent(event)
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        option.currentText = ""
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        rect = self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
                                           QStyle.SubControl.SC_ComboBoxEditField, self)
        base = QColor(TOKENS["text"] if self.isEnabled() else TOKENS["text_disabled"])
        draw_segments(painter, rect.adjusted(2, 0, 0, 0), segments if self.isEnabled() else [(t, None) for t, _ in segments],
                      base, self.font())


def repolish(widget: QWidget):
    """Re-apply stylesheet rules after a dynamic property changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def tool_button(icon_name: str, tooltip: str, handler=None, *, text: str = "", variant: str = "icon",
                checkable: bool = False) -> QToolButton:
    button = QToolButton()
    button.setIcon(icon(icon_name))
    button.setIconSize(QSize(16, 16))
    button.setToolTip(tooltip)
    button.setAccessibleName(text or tooltip.split(" · ")[0])
    button.setProperty("variant", variant)
    button.setCheckable(checkable)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if text:
        button.setText(text)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    if handler:
        button.clicked.connect(lambda *_args: handler())
    return button


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("divider")
    line.setFrameShape(QFrame.Shape.NoFrame)
    return line


def section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("section")
    return label


class ElidedLabel(QLabel):
    """A single-line label that shortens long file names instead of widening panels.

    ``text()`` keeps returning the full text; only the painted text is elided.
    """

    def __init__(self, text: str = "", mode=Qt.TextElideMode.ElideMiddle):
        super().__init__()
        self._full = ""
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(40)
        self.setText(text)

    def setText(self, text: str):
        self._full = text or ""
        self.setToolTip(self._full)
        self._refresh()

    def text(self) -> str:
        return self._full

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self):
        elided = QFontMetrics(self.font()).elidedText(self._full, self._mode, max(0, self.width()))
        super().setText(elided)

    def sizeHint(self):
        hint = super().sizeHint()
        return QSize(min(QFontMetrics(self.font()).horizontalAdvance(self._full) + 4, 480), hint.height())


class FilenameField(QStackedWidget):
    """An elided file name that can be renamed in place without changing its suffix."""
    editStarted = Signal()
    renameRequested = Signal(str)

    def __init__(self):
        super().__init__()
        self.label = ElidedLabel()
        self.label.setObjectName("fileName")
        self.editor = QLineEdit()
        self.editor.setAccessibleName(tr("画像の名前を変更（拡張子は維持）"))
        self.editor.setToolTip(tr("拡張子を除く名前 · Enterで確定 / Escで取消"))
        self.addWidget(self.label)
        self.addWidget(self.editor)
        self.label.installEventFilter(self)
        self.editor.installEventFilter(self)
        self.editing = False
        self._text = ""
        self.rename_hint = "F2"
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def text(self):
        return self._text

    def setText(self, text):
        if text != self._text:
            self.cancel_edit()
        self._text = text
        self.label.setText(text)
        self.setToolTip(text + tr("\nダブルクリックで名前を変更") + (" · " + self.rename_hint if self.rename_hint else ""))

    def begin_edit(self):
        if not self.isEnabled() or not self._text:
            return
        self.editStarted.emit()
        self.editor.setText(Path(self._text).stem)
        self.editing = True
        self.setCurrentWidget(self.editor)
        self.editor.setFocus()
        self.editor.selectAll()

    def cancel_edit(self):
        self.editing = False
        self.setCurrentWidget(self.label)

    def commit_edit(self):
        if not self.editing:
            return
        stem = self.editor.text()
        self.cancel_edit()
        if stem != Path(self._text).stem:
            self.renameRequested.emit(stem)

    def eventFilter(self, watched, event):
        if watched is self.label and event.type() == QEvent.Type.MouseButtonDblClick and event.button() == Qt.MouseButton.LeftButton:
            self.begin_edit()
            return True
        if watched is self.editor:
            keys = (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape, Qt.Key.Key_F2)
            if event.type() == QEvent.Type.ShortcutOverride and event.key() in keys:
                event.accept()
                return True
            if event.type() == QEvent.Type.KeyPress and event.key() in keys:
                if event.key() == Qt.Key.Key_Escape:
                    self.cancel_edit()
                elif event.key() == Qt.Key.Key_F2:
                    self.editor.selectAll()
                else:
                    self.commit_edit()
                return True
            if event.type() == QEvent.Type.FocusOut:
                self.commit_edit()
        return super().eventFilter(watched, event)


class ValueLabel(QLabel):
    """Setting name on the left and its current value on the right.

    ``text()`` returns both parts so the label stays readable to assistive
    technology and to tests.
    """

    def __init__(self):
        super().__init__()
        self._name = ""
        self._value = ""
        self.setObjectName("valueRow")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(20)

    def set_parts(self, name: str, value: str):
        self._name, self._value = name, value
        super().setText(f"{name}  {value}")
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        area = self.contentsRect()
        value_font = QFont(self.font())
        value_font.setWeight(QFont.Weight.DemiBold)
        value_width = QFontMetrics(value_font).horizontalAdvance(self._value) + 2
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        name = QFontMetrics(self.font()).elidedText(self._name, Qt.TextElideMode.ElideRight, max(0, area.width() - value_width - 8))
        painter.drawText(area, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
        painter.setFont(value_font)
        painter.setPen(QColor(TOKENS["text_strong"] if self.isEnabled() else TOKENS["text_disabled"]))
        painter.drawText(area, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._value)


class Popover(QFrame):
    """A light-dismiss panel anchored under a button (filters, save settings).

    Clicking outside closes it; clicking the anchor again closes it without
    reopening because the closing mouse press is not replayed.
    """

    def __init__(self, parent: QWidget, width: int = 320):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.body = QFrame()
        self.body.setObjectName("popover")
        self.body.setFixedWidth(width)
        outer.addWidget(self.body)
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(16, 14, 16, 16)
        self.content.setSpacing(10)

    def fit_content(self):
        """Resize to the current content; rows may have been shown or hidden while closed."""
        layout = self.content
        layout.invalidate()
        layout.activate()
        width = self.body.width() or self.body.minimumWidth()
        height = layout.totalHeightForWidth(width) if layout.hasHeightForWidth() else layout.totalSizeHint().height()
        self.body.setFixedHeight(max(height, layout.totalMinimumSize().height()))
        self.resize(width, self.body.height())

    def show_for(self, anchor: QWidget, align_right: bool = True):
        self.fit_content()
        size = self.size()
        bottom_left = anchor.mapToGlobal(QPoint(0, anchor.height() + 6))
        x = bottom_left.x() + anchor.width() - size.width() if align_right else bottom_left.x()
        y = bottom_left.y()
        screen = QGuiApplication.screenAt(bottom_left) or QGuiApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            x = max(area.left() + 8, min(x, area.right() - size.width() - 8))
            if y + size.height() > area.bottom() - 8:
                y = max(area.top() + 8, anchor.mapToGlobal(QPoint(0, 0)).y() - size.height() - 6)
        self.move(x, y)
        self.show()


class TopicSidebar(QWidget):
    """Topics on top and, below them, the headings of the open topic; a heading click jumps to it."""

    headingChosen = Signal(int)

    def __init__(self, topics, accessible_name):
        super().__init__()
        from PySide6.QtWidgets import QListWidget
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.topics = QListWidget()
        self.topics.setObjectName("topicList")
        self.topics.setAccessibleName(accessible_name)
        for title in topics:
            self.topics.addItem(title)
        layout.addWidget(self.topics, 3)
        self.outline_title = section_label(tr("このページの項目"))
        self.outline_title.setContentsMargins(8, 6, 0, 0)
        layout.addWidget(self.outline_title)
        self.outline = QListWidget()
        self.outline.setObjectName("outlineList")
        self.outline.setAccessibleName(tr("このページの項目"))
        self.outline.setCursor(Qt.CursorShape.PointingHandCursor)
        self.outline.itemClicked.connect(lambda item: self.headingChosen.emit(self.outline.row(item)))
        layout.addWidget(self.outline, 2)
        self.set_headings([])

    def set_headings(self, headings):
        self.outline.clear()
        for heading in headings:
            self.outline.addItem(heading)
        visible = len(headings) > 1
        self.outline_title.setVisible(visible)
        self.outline.setVisible(visible)


class ZoomField(QLineEdit):
    """The zoom percentage; type a number and press Enter to zoom to it."""

    zoomRequested = Signal(float)

    def __init__(self):
        super().__init__("100%")
        self.setObjectName("zoomField")
        self.setFixedWidth(62)
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setToolTip(tr("表示倍率 · 数値を入力してEnterで変更（例：150）"))
        self.setAccessibleName(tr("表示倍率"))
        self.scale = 1.0

    def event(self, event):
        # Typing a number (and Enter) belongs to the field, not to one-key shortcuts such as Enter = save and next.
        if (event.type() == QEvent.Type.ShortcutOverride and not event.modifiers()
                & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier)):
            event.accept()
            return True
        return super().event(event)
        self.editingFinished.connect(self.commit)

    def show_scale(self, scale):
        self.scale = scale
        if not self.hasFocus():
            self.setText(f"{round(scale * 100)}%")

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.setText(str(round(self.scale * 100)))
        self.selectAll()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.setText(f"{round(self.scale * 100)}%")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.setText(f"{round(self.scale * 100)}%")
            self.clearFocus()
            return
        super().keyPressEvent(event)
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()

    def commit(self):
        text = self.text().strip().rstrip("%％").strip()
        try:
            value = float(text.translate(str.maketrans("０１２３４５６７８９．", "0123456789.")))
        except ValueError:
            value = None
        if value is not None and value > 0:
            self.zoomRequested.emit(max(1.0, min(3200.0, value)))
        self.setText(f"{round(self.scale * 100)}%" if not self.hasFocus() else str(round(self.scale * 100)))
        parent = self.parentWidget()
        if self.hasFocus() and parent is not None:
            self.clearFocus()


COPYRIGHT = "© 2026 marc2825"


class WelcomePage(QWidget):
    """Dedicated empty state: one drop target, open buttons and recent folders."""

    filesDropped = Signal(list)
    recentRequested = Signal(list)
    recentRemoved = Signal(list)
    saveSettingsRequested = Signal()
    languageChosen = Signal(str)

    def __init__(self, open_folder, open_files):
        super().__init__()
        self.setObjectName("welcome")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setAcceptDrops(True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 32, 32, 32)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.zone = QFrame()
        self.zone.setObjectName("dropZone")
        self.zone.setMaximumWidth(620)
        self.zone.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row.addWidget(self.zone, 6)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)
        # The language, in each language's own words so it can be found from any of them.
        from .i18n import LANGUAGES
        languages = QHBoxLayout()
        languages.addStretch(1)
        self.language_note = QLabel()
        self.language_note.setObjectName("faint")
        self.language_note.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.language_note.hide()
        languages.addWidget(self.language_note)
        self.language = QComboBox()
        for code, name in LANGUAGES.items():
            self.language.addItem(name, code)
        self.language.setAccessibleName("表示言語 / Language / 显示语言")
        self.language.setToolTip("表示言語 / Language / 显示语言")
        self.language.activated.connect(lambda index: self.languageChosen.emit(self.language.itemData(index)))
        languages.addWidget(self.language)
        outer.addLayout(languages)

        layout = QVBoxLayout(self.zone)
        layout.setContentsMargins(40, 36, 40, 32)
        layout.setSpacing(0)
        mark = QLabel()
        pixmap = app_mark(128)
        pixmap.setDevicePixelRatio(2)
        mark.setPixmap(pixmap)
        mark.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(mark)
        layout.addSpacing(16)
        title = QLabel(tr("フォルダーや画像をドロップ"))
        title.setObjectName("heroTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(title)
        layout.addSpacing(8)
        text = QLabel(tr("『なぞって加工 → 保存 → 次の画像へ』"))
        text.setObjectName("heroText")
        text.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(text)
        layout.addSpacing(24)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        self.open_folder_button = QPushButton(tr("フォルダーを開く"))
        self.open_folder_button.setObjectName("primary")
        self.open_folder_button.setIcon(icon("folder", "on_accent"))
        self.open_folder_button.setToolTip("Ctrl+O")
        self.open_folder_button.clicked.connect(lambda *_args: open_folder())
        self.open_files_button = QPushButton(tr("画像を開く"))
        self.open_files_button.setIcon(icon("image"))
        self.open_files_button.clicked.connect(lambda *_args: open_files())
        for button in (self.open_folder_button, self.open_files_button):
            button.setMinimumHeight(36)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addSpacing(28)
        self.recent_title = section_label(tr("最近使ったフォルダー"))
        layout.addWidget(self.recent_title)
        layout.addSpacing(6)
        self.recent_box = QVBoxLayout()
        self.recent_box.setSpacing(2)
        layout.addLayout(self.recent_box)
        layout.addSpacing(20)
        footer = QHBoxLayout()
        footer.setSpacing(6)
        self.note = QLabel()
        self.note.setObjectName("faint")
        self.note.setWordWrap(True)
        footer.addWidget(self.note, 1)
        change = QPushButton(tr("保存方法を変更"))
        change.setProperty("variant", "link")
        change.setCursor(Qt.CursorShape.PointingHandCursor)
        change.clicked.connect(lambda *_args: self.saveSettingsRequested.emit())
        footer.addWidget(change, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(footer)
        self.recent_buttons: list[QPushButton] = []
        self.recent_rows: list[QWidget] = []

    def set_language(self, code: str, note: str = ""):
        self.language.setCurrentIndex(max(0, self.language.findData(code)))
        self.language_note.setText(note)
        self.language_note.setVisible(bool(note))

    def set_note(self, text: str):
        self.note.setText(text)

    def set_recent(self, entries: list[list[str]]):
        for row in self.recent_rows:
            self.recent_box.removeWidget(row)
            row.deleteLater()
        self.recent_rows, self.recent_buttons = [], []
        for inputs in entries[:5]:
            title, location = describe_inputs(inputs)
            button = QPushButton()
            button.setObjectName("recent")
            button.setIcon(icon("folder" if Path(inputs[0]).is_dir() else "image", "text_muted"))
            metrics = QFontMetrics(button.font())
            title = metrics.elidedText(title, Qt.TextElideMode.ElideMiddle, 200)
            location = metrics.elidedText(location, Qt.TextElideMode.ElideMiddle, 300)
            button.setText(f"{title}    {location}" if location else title)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.setToolTip("\n".join(inputs))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda *_args, value=list(inputs): self.recentRequested.emit(value))
            remove = QToolButton()
            remove.setObjectName("recentRemove")
            remove.setText("✕")
            remove.setToolTip(tr("一覧から消す（フォルダー・画像は削除しません）"))
            remove.setAccessibleName(tr("{title}を最近使った一覧から消す").format(title=title))
            remove.setCursor(Qt.CursorShape.PointingHandCursor)
            remove.clicked.connect(lambda *_args, value=list(inputs): self.recentRemoved.emit(value))
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(2)
            line.addWidget(button, 1)
            line.addWidget(remove)
            self.recent_box.addWidget(row)
            self.recent_rows.append(row)
            self.recent_buttons.append(button)
        empty = not self.recent_buttons
        self.recent_title.setVisible(not empty)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_drag(True)

    def dragLeaveEvent(self, event):
        self._set_drag(False)

    def dropEvent(self, event):
        self._set_drag(False)
        self.filesDropped.emit([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
        event.acceptProposedAction()

    def _set_drag(self, active: bool):
        self.zone.setProperty("drag", active)
        repolish(self.zone)


def describe_inputs(inputs: list[str]) -> tuple[str, str]:
    """Short title and location for a remembered workspace."""
    first = Path(inputs[0])
    title = first.name or str(first)
    if len(inputs) > 1:
        title += tr(" ほか{value}件").format(value=len(inputs) - 1)
    location = str(first.parent) if first.parent != first else ""
    return title, location


class DialogTint(QObject):
    """Tints each dialog's native title bar when it first appears (Windows 11)."""

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.Show and isinstance(watched, QDialog) and watched.isWindow()
                and not watched.property("captionTinted")):
            watched.setProperty("captionTinted", True)
            tint_caption(watched)
        return False


def install_dialog_tint(app):
    """Only Windows can tint title bars, so the app-wide filter is installed there only."""
    import sys
    if sys.platform == "win32" and app is not None and getattr(app, "_sumire_dialog_tint", None) is None:
        app._sumire_dialog_tint = DialogTint(app)
        app.installEventFilter(app._sumire_dialog_tint)


class NumberBox(QSpinBox):
    """A number field (beside a slider): typing in it never triggers the window's
    one-key shortcuts, and Enter applies the value instead of saving."""

    def event(self, event):
        if (event.type() == QEvent.Type.ShortcutOverride and not event.modifiers()
                & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier)):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.setValue(self.value())  # drop what was typed
            self.clearFocus()
            return
        super().keyPressEvent(event)
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.selectAll()


def slider_with_box(slider, suffix, accessible_name):
    """(label row layout, number box) kept in step with ``slider``, including its range."""
    box = NumberBox()
    box.setObjectName("sliderValue")
    box.setRange(slider.minimum(), slider.maximum())
    box.setValue(slider.value())
    box.setSuffix(suffix)
    box.setKeyboardTracking(False)  # apply on Enter, focus change or the arrows, not per digit
    box.setAccessibleName(accessible_name)
    box.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
    box.setAlignment(Qt.AlignmentFlag.AlignRight)
    box.setFixedWidth(76)

    def follow(value):
        box.blockSignals(True)
        box.setValue(value)
        box.blockSignals(False)

    slider.valueChanged.connect(follow)
    slider.rangeChanged.connect(lambda low, high: (box.blockSignals(True), box.setRange(low, high), box.blockSignals(False)))
    box.valueChanged.connect(slider.setValue)
    return box
