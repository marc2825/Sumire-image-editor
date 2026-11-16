"""Shared keyboard bindings and their settings editor."""
from .i18n import tr
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHeaderView, QKeySequenceEdit, QLabel,
    QLineEdit, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

# Stable identifiers keep user settings independent of translated UI labels.
COMMANDS = {
    "open_folder": (tr("フォルダーを開く"), ("Ctrl+O",)),
    "file_menu": (tr("ファイルメニューを開く"), ("Alt+F",)),
    "reload": (tr("一覧を再読み込み"), ("Ctrl+R",)),
    "save": (tr("保存"), ("Ctrl+S",)),
    "save_next": (tr("保存して次へ"), ("Return",)),
    "previous": (tr("前の画像"), ("Left",)),
    "next": (tr("次の画像"), ("Right",)),
    "undo": (tr("元に戻す"), ("Ctrl+Z",)),
    "redo": (tr("やり直す"), ("Ctrl+Shift+Z", "Ctrl+Y")),
    "new_tab": (tr("新しいタブ"), ("Ctrl+T",)),
    "close_tab": (tr("現在のタブを閉じる"), ("Ctrl+W",)),
    "next_tab": (tr("次のタブ"), ("Ctrl+Tab",)),
    "previous_tab": (tr("前のタブ"), ("Ctrl+Shift+Tab",)),
    "rename": (tr("画像の名前を変更"), ("F2",)),
    "search": (tr("名前・メモ・タグで検索"), ("Ctrl+F",)),
    "accepted": (tr("採用"), ("1",)),
    "pending": (tr("保留"), ("2",)),
    "rejected": (tr("不採用"), ("3",)),
    "clear_label": (tr("ラベルを解除"), ("Alt+0",)),
    "undo_organize": (tr("直前の整理操作を戻す"), ("Ctrl+Alt+Z",)),
    "eraser": (tr("消しゴムの切り替え（キャンバス上）"), ("E",)),
    "mask": (tr("加工マスクの表示（キャンバス上）"), ("M",)),
    "compare": (tr("元画像と比較（押している間）"), ("Tab",)),
    "pan": (tr("表示位置を動かす（押しながらドラッグ）"), ("Space",)),
    "fit": (tr("全体表示"), ("F",)),
    "actual_size": (tr("原寸表示"), ("Ctrl+1",)),
    "zoom_in": (tr("拡大"), ("+", "=")),
    "zoom_out": (tr("縮小"), ("-",)),
    "brush_smaller": (tr("ブラシを小さくする"), ("[",)),
    "brush_larger": (tr("ブラシを大きくする"), ("]",)),
    "strength_down": (tr("強さ・不透明度を下げる"), (",",)),
    "strength_up": (tr("強さ・不透明度を上げる"), (".",)),
    "cancel_stroke": (tr("描画中のストロークを取り消す"), ("Esc",)),
    "help": (tr("ヘルプを開く"), ("F1",)),
    "copy_image": (tr("コピー（一覧では画像ファイル、ほかでは編集結果）"), ("Ctrl+C",)),
    "cut_files": (tr("画像ファイルを切り取る"), ("Ctrl+X",)),
    "paste_image": (tr("貼り付け（画像ファイルはタブのフォルダーへ、画像は新しく開く）"), ("Ctrl+V",)),
    "fullscreen": (tr("全画面表示"), ("F11",)),
}
CANVAS_COMMANDS = {"eraser", "mask", "pan", "cancel_stroke"}
HOST_COMMANDS = {"new_tab", "close_tab", "next_tab", "previous_tab"}
PORTABLE = QKeySequence.SequenceFormat.PortableText


def defaults():
    return {name: list(keys) for name, (_, keys) in COMMANDS.items()}


def normalize(keys):
    if not isinstance(keys, (list, tuple)) or len(keys) > 2:
        raise ValueError(tr("キーは1つの操作に2個まで設定できます。"))
    result = []
    for raw in keys:
        if not isinstance(raw, str) or not raw or len(raw) > 80:
            raise ValueError(tr("キーの指定が正しくありません。"))
        sequence = QKeySequence.fromString(raw, PORTABLE)
        if sequence.count() != 1 or sequence[0].key() in {Qt.Key.Key_unknown, Qt.Key.Key_Control,
                Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta}:
            raise ValueError(tr("修飾キーだけ、または複数回に分けて押すキーは設定できません。"))
        result.append(sequence.toString(PORTABLE))
    return result


def validate(bindings):
    used = {}
    for name, keys in bindings.items():
        for key in keys:
            if key in used:
                raise ValueError(tr("「{COMMANDS}」と「{COMMANDS2}」で {key} が重複しています。").format(COMMANDS=COMMANDS[used[key]][0], COMMANDS2=COMMANDS[name][0], key=key))
            used[key] = name


def load_bindings(preferences):
    bindings = defaults()
    raw = preferences.data.get("shortcuts", {})
    try:
        if isinstance(raw, dict):
            for name in COMMANDS.keys() & raw.keys():
                bindings[name] = normalize(raw[name])
            # Preserve valid assignments made before these commands existed.
            # Their new defaults yield to an explicit older assignment.
            for name in ("copy_image", "cut_files", "paste_image", "fullscreen"):
                if name not in raw:
                    assigned = {key for other, keys in bindings.items() if other != name for key in keys}
                    bindings[name] = [key for key in bindings[name] if key not in assigned]
        validate(bindings)
    except ValueError:
        # An invalid or conflicting profile must not install ambiguous shortcuts.
        return defaults()
    return bindings


KEY_LABELS = (("Return", "Enter"), ("Right", "→"), ("Left", "←"), ("Up", "↑"), ("Down", "↓"))


def hint(bindings, name):
    # Show the label printed on the keyboard: Qt names Enter "Return" and arrows "Right" etc.
    labels = []
    for key in bindings[name]:
        text = QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText)
        for qt_name, label in KEY_LABELS:
            text = "+".join(label if part == qt_name else part for part in text.split("+"))
        labels.append(text)
    return " / ".join(labels)


def matches(event, keys):
    return any(event.keyCombination() == QKeySequence(key)[0] for key in keys)


class ShortcutDialog(QDialog):
    def __init__(self, preferences, parent=None):
        super().__init__(parent)
        self.preferences = preferences
        self.setWindowTitle(tr("ショートカットキー設定"))
        self.resize(740, 600)
        layout = QVBoxLayout(self)
        description = QLabel(tr("欄を選んでキーを押します。各操作に2個まで設定でき、×で解除します。\n"
                             "保存すると全タブにすぐ反映します。文字入力中は入力欄の操作が優先されます。"))
        description.setWordWrap(True)
        layout.addWidget(description)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("操作名で検索"))
        self.search.setAccessibleName(tr("ショートカットの操作名で検索"))
        layout.addWidget(self.search)
        self.table = QTableWidget(len(COMMANDS), 3)
        self.table.setHorizontalHeaderLabels([tr("操作"), tr("キー1"), tr("キー2")])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2):
            self.table.setColumnWidth(column, 175)
        self.editors = {}
        bindings = load_bindings(preferences)
        for row, (name, (title, _)) in enumerate(COMMANDS.items()):
            item = QTableWidgetItem(title)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 0, item)
            editors = []
            for column in (1, 2):
                editor = QKeySequenceEdit()
                editor.setMaximumSequenceLength(1)
                editor.setClearButtonEnabled(True)
                editor.setFinishingKeyCombinations([])  # Tab itself can be assigned.
                editor.findChild(QLineEdit).setPlaceholderText(tr("未設定"))
                editor.setAccessibleName(tr("{title} キー{column}").format(title=title, column=column))
                self.table.setCellWidget(row, column, editor)
                editors.append(editor)
            self.editors[name] = editors
        layout.addWidget(self.table)
        self.search.textChanged.connect(self.filter_rows)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setObjectName("shortcutError")
        self.error.setStyleSheet("color: #ff8b95")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr("保存"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("キャンセル"))
        reset = buttons.addButton(tr("初期設定に戻す"), QDialogButtonBox.ButtonRole.ResetRole)
        reset.clicked.connect(lambda: self.set_bindings(defaults()))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.set_bindings(bindings)

    def set_bindings(self, bindings):
        for name, editors in self.editors.items():
            for index, editor in enumerate(editors):
                editor.setKeySequence(QKeySequence(bindings[name][index]) if index < len(bindings[name]) else QKeySequence())
        self.error.clear()

    def filter_rows(self, text):
        for row in range(self.table.rowCount()):
            self.table.setRowHidden(row, text.casefold() not in self.table.item(row, 0).text().casefold())

    def accept(self):
        try:
            bindings = {name: normalize([editor.keySequence().toString(PORTABLE) for editor in editors
                                        if not editor.keySequence().isEmpty()])
                        for name, editors in self.editors.items()}
            validate(bindings)
            changes = {name: keys for name, keys in bindings.items() if keys != defaults()[name]}
            self.preferences.save({**self.preferences.data, "shortcuts": changes})
        except (ValueError, OSError) as error:
            self.error.setText(str(error) if isinstance(error, ValueError) else tr("設定を保存できません。保存先と空き容量を確認してください。"))
            return
        super().accept()
