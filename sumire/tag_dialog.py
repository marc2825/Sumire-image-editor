"""Tags for one or many images (tick to add, untick to remove, leave half-ticked to keep as it is),
and the editor of the tag buttons (オリジナルタグ)."""
from __future__ import annotations
from .i18n import tr

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
)

from .labels import MAX_QUICK_TAGS, MAX_TAG_LENGTH, MAX_TAGS, clean_tags, ordered_tags, split_tags


class TagDialog(QDialog):
    """``current`` maps each image to its tags; ``known`` is every tag of the list (offered for reuse)."""

    def __init__(self, current: dict, known, parent=None):
        super().__init__(parent)
        self.current = {path: clean_tags(tags) for path, tags in current.items()}
        self.setWindowTitle(tr("タグ"))
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("{count}枚の画像のタグ").format(count=len(self.current))))
        note = QLabel(tr("チェックしたタグを付け、外したタグを取ります。半分のチェック（一部の画像だけにあるタグ）は、そのままにします。"))
        note.setObjectName("faint")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.list = QListWidget()
        self.list.setMinimumHeight(160)
        layout.addWidget(self.list, 1)
        counts: dict[str, int] = {}
        for tags in self.current.values():
            for tag in tags:
                counts[tag.casefold()] = counts.get(tag.casefold(), 0) + 1
        names = {tag.casefold(): tag for tag in [*known, *(tag for tags in self.current.values() for tag in tags)]}
        for key, tag in sorted(names.items(), key=lambda item: item[1].casefold()):
            count = counts.get(key, 0)
            state = (Qt.CheckState.Checked if count == len(self.current) and count else
                     Qt.CheckState.PartiallyChecked if count else Qt.CheckState.Unchecked)
            self.add_item(tag, state)
        row = QHBoxLayout()
        self.entry = QLineEdit()
        self.entry.setPlaceholderText(tr("新しいタグ（カンマ・読点で区切って複数）"))
        self.entry.returnPressed.connect(self.add_typed)
        row.addWidget(self.entry, 1)
        add = QPushButton(tr("追加"))
        add.clicked.connect(self.add_typed)
        row.addWidget(add)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("適用"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("キャンセル"))
        buttons.accepted.connect(self.accept_typed)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def add_item(self, tag, state):
        item = QListWidgetItem(tag)
        flags = item.flags() | Qt.ItemFlag.ItemIsUserCheckable
        if state == Qt.CheckState.PartiallyChecked:
            flags |= Qt.ItemFlag.ItemIsUserTristate  # so "keep as it is" can be chosen again
        item.setFlags(flags)
        item.setCheckState(state)
        self.list.addItem(item)
        return item

    def items(self):
        return [self.list.item(row) for row in range(self.list.count())]

    def add_typed(self):
        existing = {item.text().casefold(): item for item in self.items()}
        for tag in split_tags(self.entry.text()):
            item = existing.get(tag.casefold()) or self.add_item(tag, Qt.CheckState.Checked)
            item.setCheckState(Qt.CheckState.Checked)
        self.entry.clear()

    def accept_typed(self):
        # Text typed but not added yet counts too (pressing 適用 should not lose it).
        if self.entry.text().strip():
            self.add_typed()
        self.accept()

    def result_tags(self) -> dict:
        """{path: tags} after the choices; only images whose tags change."""
        add = {item.text() for item in self.items() if item.checkState() == Qt.CheckState.Checked}
        remove = {item.text().casefold() for item in self.items() if item.checkState() == Qt.CheckState.Unchecked}
        changed = {}
        for path, tags in self.current.items():
            new = clean_tags([*(tag for tag in tags if tag.casefold() not in remove), *add])[:MAX_TAGS]
            if new != tags:
                changed[path] = new
        return changed


class QuickTagDialog(QDialog):
    """The tag buttons below the labels: add, rename, delete and reorder them.

    ``chosen()`` gives the new list and {old name: new name} for renamed buttons; ``rename_existing``
    says whether the images of the tab carrying an old name should get the new one.
    """

    def __init__(self, tags, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("オリジナルタグの編集"))
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        note = QLabel(tr("仕分けの欄にボタンとして並べるタグです。ボタンを押すたびに、選んだ画像に付けたり外したりします。"
                         "上から{count}個は、キーの4〜9でも付け外しできます。").format(count=6))
        note.setObjectName("faint")
        note.setWordWrap(True)
        layout.addWidget(note)
        body = QHBoxLayout()
        self.list = QListWidget()
        self.list.setMinimumHeight(180)
        self.list.itemChanged.connect(self.clean_item)
        body.addWidget(self.list, 1)
        side = QVBoxLayout()
        self.buttons = {}
        for key, text, handler in (("add", tr("追加"), self.add), ("rename", tr("名前を変更"), self.rename),
                                   ("remove", tr("削除"), self.remove), ("up", tr("上へ"), lambda: self.move(-1)),
                                   ("down", tr("下へ"), lambda: self.move(1))):
            button = QPushButton(text)
            button.clicked.connect(handler)
            side.addWidget(button)
            self.buttons[key] = button
        side.addStretch(1)
        body.addLayout(side)
        layout.addLayout(body)
        self.entry = QLineEdit()
        self.entry.setPlaceholderText(tr("新しいタグの名前"))
        self.entry.setMaxLength(MAX_TAG_LENGTH)
        self.entry.returnPressed.connect(self.add)
        layout.addWidget(self.entry)
        self.rename_existing = QCheckBox(tr("名前を変えたタグは、このタブの画像に付いているものも変える"))
        self.rename_existing.setChecked(True)
        layout.addWidget(self.rename_existing)
        hint = QLabel(tr("削除してもボタンがなくなるだけで、画像に付いているタグは残ります。"))
        hint.setObjectName("faint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("保存"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("キャンセル"))
        buttons.accepted.connect(self.accept_typed)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for tag in tags:
            self.add_item(tag, tag)
        self.list.currentRowChanged.connect(self.update_buttons)
        self.update_buttons()

    def add_item(self, text, original=None):
        item = QListWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        item.setData(Qt.ItemDataRole.UserRole, original)
        self.list.addItem(item)
        return item

    def names(self):
        return [self.list.item(row).text() for row in range(self.list.count())]

    def add(self):
        name = " ".join(self.entry.text().split())[:MAX_TAG_LENGTH]
        if not name:
            self.entry.setFocus()
            return
        existing = [row for row, text in enumerate(self.names()) if text.casefold() == name.casefold()]
        if existing:
            self.list.setCurrentRow(existing[0])
        elif self.list.count() < MAX_QUICK_TAGS:
            self.add_item(name)
            self.list.setCurrentRow(self.list.count() - 1)
        self.entry.clear()
        self.update_buttons()

    def rename(self):
        item = self.list.currentItem()
        if item is not None:
            self.list.editItem(item)

    def remove(self):
        row = self.list.currentRow()
        if row >= 0:
            self.list.takeItem(row)
        self.update_buttons()

    def move(self, step):
        row = self.list.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(target, item)
        self.list.setCurrentRow(target)

    def clean_item(self, item):
        """A rename keeps one line and the length limit; an empty or duplicate name goes back."""
        text = " ".join(item.text().split())[:MAX_TAG_LENGTH]
        others = {self.list.item(row).text().casefold() for row in range(self.list.count()) if self.list.item(row) is not item}
        if not text or text.casefold() in others:
            text = item.data(Qt.ItemDataRole.UserRole) or tr("タグ")
        if text != item.text():
            self.list.blockSignals(True)
            item.setText(text)
            self.list.blockSignals(False)

    def update_buttons(self, *args):
        row = self.list.currentRow()
        self.buttons["add"].setEnabled(self.list.count() < MAX_QUICK_TAGS)
        self.entry.setEnabled(self.list.count() < MAX_QUICK_TAGS)
        for key in ("rename", "remove"):
            self.buttons[key].setEnabled(row >= 0)
        self.buttons["up"].setEnabled(row > 0)
        self.buttons["down"].setEnabled(0 <= row < self.list.count() - 1)

    def accept_typed(self):
        if self.entry.text().strip():
            self.add()
        self.accept()

    def chosen(self):
        tags = ordered_tags(self.names())
        renames = {}
        for row in range(self.list.count()):
            item = self.list.item(row)
            original = item.data(Qt.ItemDataRole.UserRole)
            if original and original != item.text() and item.text() in tags:
                renames[original] = item.text()
        return tags, renames
