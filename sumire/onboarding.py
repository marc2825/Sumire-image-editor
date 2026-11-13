"""First-run choice of how images are saved, shown once for a new settings profile."""
from __future__ import annotations
from .i18n import tr

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QLabel, QRadioButton, QVBoxLayout,
)

OVERWRITE, SEPARATE = "overwrite", "separate"


class FirstRunDialog(QDialog):
    """Ask before the first save instead of silently defaulting to overwriting originals.

    Nothing is preselected: the user picks overwrite or a separate folder explicitly.
    Closing the dialog keeps the previous defaults (overwrite, metadata backup on).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("保存方法を選んでください"))
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        intro = QLabel(tr("最初に保存の方法を選んでください（あとから右上の保存方法で変更できます）。\n選ばずに閉じた場合は、元画像に上書きして自動で保存します。"))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.choices = QButtonGroup(self)
        self.overwrite_choice = QRadioButton(tr("元画像に上書き保存する"))
        self.separate_choice = QRadioButton(tr("別フォルダーに保存して、元画像を残す"))
        for button, note in ((self.overwrite_choice, tr("同じ場所・名前・形式で置き換えます。置き換える前の元画像は、アプリを終了するまで一時的に残します。")),
                             (self.separate_choice, tr("画像のあるフォルダー内の「Sumīre」に保存します。元画像は変更しません。"))):
            self.choices.addButton(button)
            layout.addWidget(button)
            hint = QLabel(note)
            hint.setObjectName("faint")
            hint.setWordWrap(True)
            hint.setContentsMargins(26, 0, 0, 4)
            layout.addWidget(hint)
        self.strip = QCheckBox(tr("保存するときにメタデータを削除する"))
        layout.addWidget(self.strip)
        strip_note = QLabel(tr("オフのときは、生成情報やEXIFなどのメタデータを残して保存します。"
                            "オンにすると、保存のたびに削除します（右上の「メタデータを削除」はいつでも使えます）。"))
        strip_note.setObjectName("faint")
        strip_note.setWordWrap(True)
        strip_note.setContentsMargins(26, 0, 0, 4)
        layout.addWidget(strip_note)
        self.backup = QCheckBox(tr("削除前のメタデータを復元用に残す"))
        self.backup.setChecked(True)
        layout.addWidget(self.backup)
        backup_note = QLabel(tr("メタデータを削除するときに、アプリ専用の領域へ圧縮して残します（画像のフォルダーには置きません）。"
                             "プロンプトや位置情報も残り、暗号化はされません。"))
        backup_note.setObjectName("faint")
        backup_note.setWordWrap(True)
        backup_note.setContentsMargins(26, 0, 0, 4)
        layout.addWidget(backup_note)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        self.start_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.start_button.setText(tr("この設定で始める"))
        self.start_button.setObjectName("primary")
        self.start_button.setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        layout.addWidget(self.buttons)
        self.choices.buttonToggled.connect(lambda *_args: self.start_button.setEnabled(self.choices.checkedButton() is not None))
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

    def save_mode(self):
        if self.overwrite_choice.isChecked():
            return OVERWRITE
        return SEPARATE if self.separate_choice.isChecked() else None

    def settings(self):
        """Save settings for the chosen mode, merged into the profile's defaults."""
        return {"overwrite": self.save_mode() == OVERWRITE, "metadata_backup": self.backup.isChecked(),
                "strip_metadata": self.strip.isChecked()}
