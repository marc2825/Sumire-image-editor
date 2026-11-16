"""Tags for one or many images: tick to add, untick to remove, leave half-ticked to keep as it is."""
from __future__ import annotations
from .i18n import tr

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout

from .labels import MAX_TAGS, clean_tags, split_tags


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
