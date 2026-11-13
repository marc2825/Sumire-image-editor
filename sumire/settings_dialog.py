"""Settings in one place, laid out like the help: categories on the left, controls on the right.

Every control mirrors an existing widget or action of the workspace, so the
quick save popover, menus and this dialog always agree.
"""
from __future__ import annotations
from .i18n import LANGUAGES, language, tr

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)

from .ui import TopicSidebar, section_label


def note(text):
    label = QLabel(text)
    label.setObjectName("faint")
    label.setWordWrap(True)
    label.setContentsMargins(26, 0, 0, 4)
    return label


class SettingsDialog(QDialog):
    PAGES = (tr("保存"), tr("管理記録"), tr("ショートカット"), tr("表示・取り込み"), tr("NovelAI連携"), tr("Windows連携"), tr("情報"))

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.followers = []
        self.setObjectName("settingsDialog")
        self.setWindowTitle(tr("Sumīre 設定"))
        self.setMinimumSize(560, 360)
        available = self.screen().availableGeometry()
        self.resize(min(820, available.width() - 48), min(560, available.height() - 80))
        self.setSizeGripEnabled(True)
        layout = QVBoxLayout(self)
        splitter = QSplitter()
        self.sidebar = TopicSidebar(self.PAGES, tr("設定の項目"))
        self.sidebar.setMinimumWidth(150)
        self.sidebar.setMaximumWidth(220)
        self.topics = self.sidebar.topics
        self.pages = QStackedWidget()
        self.headings = []
        for title, builder in zip(self.PAGES, (self.save_page, self.records_page, self.shortcuts_page, self.view_page,
                                                self.novelai_page, self.windows_page, self.about_page)):
            self.headings.append([])
            content = QWidget()
            column = QVBoxLayout(content)
            column.setContentsMargins(18, 14, 18, 14)
            column.setSpacing(8)
            column.addWidget(section_label(title))
            builder(column)
            column.addStretch(1)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(content)
            self.pages.addWidget(scroll)
        splitter.addWidget(self.sidebar)
        splitter.addWidget(self.pages)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([180, 620])
        layout.addWidget(splitter, 1)
        footer = QHBoxLayout()
        self.reset_button = QPushButton(tr("設定を初期状態に戻す…"))
        self.reset_button.setToolTip(tr("すべての設定を、最初に起動したときの状態に戻します。実行前に確認します。"))
        self.reset_button.clicked.connect(self.reset_all)
        footer.addWidget(self.reset_button)
        footer.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        layout.addLayout(footer)
        self.topics.currentRowChanged.connect(self.show_page)
        self.sidebar.headingChosen.connect(self.jump_to)
        self.topics.setCurrentRow(0)

    def reset_all(self):
        answer = QMessageBox(QMessageBox.Icon.Warning, tr("設定を初期状態に戻す"), tr("すべての設定を初期状態に戻しますか？"),
                             QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel, self)
        answer.setInformativeText(tr("保存方法・メタデータ・表示・NovelAI連携・ツールの設定、ショートカットキー、編集プリセット、"
                                  "上書き・終了の確認の表示を、最初の状態に戻します。\n\n"
                                  "管理記録（ラベル・メモ・復元用のメタデータ）とその保存先、Windowsの右クリックメニュー、"
                                  "最近使ったフォルダー、表示言語はそのままです。"))
        answer.button(QMessageBox.StandardButton.Ok).setText(tr("初期状態に戻す"))
        answer.button(QMessageBox.StandardButton.Cancel).setText(tr("キャンセル"))
        answer.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if answer.exec() == QMessageBox.StandardButton.Ok and self.window.reset_all_settings():
            self.accept()

    def heading(self, layout, title):
        """A sub-heading of the page being built, listed under the topics for jumping."""
        if self.headings[-1]:
            layout.addSpacing(10)
        label = section_label(title)
        layout.addWidget(label)
        self.headings[-1].append((title, label))
        return label

    def show_page(self, index):
        self.pages.setCurrentIndex(index)
        if 0 <= index < len(self.headings):
            self.sidebar.set_headings([title for title, _ in self.headings[index]])

    def jump_to(self, row):
        index = self.pages.currentIndex()
        if not 0 <= index < len(self.headings) or not 0 <= row < len(self.headings[index]):
            return
        scroll = self.pages.widget(index)
        label = self.headings[index][row][1]
        scroll.verticalScrollBar().setValue(max(0, label.mapTo(scroll.widget(), QPoint(0, 0)).y() - 8))

    def mirror(self, source, text=None):
        """A checkbox that follows and drives a QCheckBox or checkable QAction of the window."""
        box = QCheckBox(text or source.text().split("\t")[0])
        box.setChecked(source.isChecked())
        box.setEnabled(source.isEnabled())
        box.toggled.connect(lambda checked: source.setChecked(checked) if source.isChecked() != checked else None)
        follow = lambda checked: box.setChecked(checked) if box.isChecked() != checked else None
        source.toggled.connect(follow)
        self.followers.append((source, follow))
        return box

    def done(self, result):
        # The window outlives this dialog; stop its widgets from updating deleted checkboxes.
        for source, follow in self.followers:
            try:
                source.toggled.disconnect(follow)
            except (RuntimeError, TypeError):
                pass
        self.followers.clear()
        super().done(result)

    def open_page(self, title):
        if title in self.PAGES:
            self.topics.setCurrentRow(self.PAGES.index(title))

    # --- pages ---------------------------------------------------------------------
    def save_page(self, layout):
        window = self.window
        idle = not window.busy() and not window.saving
        if not idle:
            layout.addWidget(note(tr("処理中は保存方法を変更できません。完了してから開き直してください。")))
        # Each note follows its option's state, with the same text as the save panel.
        self.save_notes = {}
        self.heading(layout, tr("保存方法"))
        layout.addWidget(self.mirror(window.auto))
        layout.addWidget(self.save_note("auto"))
        self.overwrite = self.mirror(window.overwrite)
        layout.addWidget(self.overwrite)
        layout.addWidget(self.save_note("overwrite"))
        self.heading(layout, tr("上書き前の元画像"))
        self.keep_originals = self.mirror(window.keep_originals)
        layout.addWidget(self.keep_originals)
        layout.addWidget(self.save_note("keep_originals"))
        self.overwrite_notice = QCheckBox(tr("初めて上書きするときに確認を表示する"))
        self.overwrite_notice.setChecked(window.preferences.data.get("hide_overwrite_notice") is not True)
        self.overwrite_notice.toggled.connect(self.notice_changed)
        layout.addWidget(self.overwrite_notice)
        self.notice_note = note("")
        layout.addWidget(self.notice_note)
        self.heading(layout, tr("メタデータ"))
        layout.addWidget(self.mirror(window.strip_metadata))
        layout.addWidget(self.save_note("strip_metadata"))
        layout.addWidget(note(tr("「メタデータを削除」と一括削除は、この設定にかかわらず削除します。")))
        layout.addWidget(self.mirror(window.metadata_backup))
        layout.addWidget(self.save_note("metadata_backup"))
        for source in (window.auto, window.overwrite, window.keep_originals, window.strip_metadata, window.metadata_backup):
            source.toggled.connect(self.refresh_save_notes)
            self.followers.append((source, self.refresh_save_notes))
        self.refresh_save_notes()
        self.heading(layout, tr("別フォルダーに保存するとき"))
        self.format = QComboBox()
        for index in range(window.format_combo.count()):
            self.format.addItem(window.format_combo.itemText(index), window.format_combo.itemData(index))
        self.format.setCurrentIndex(window.format_combo.currentIndex())
        self.format.currentIndexChanged.connect(window.format_combo.setCurrentIndex)
        layout.addWidget(self.format)
        folder_row = QHBoxLayout()
        self.folder = QLabel()
        self.folder.setObjectName("muted")
        self.folder.setWordWrap(True)
        self.folder.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        folder_row.addWidget(self.folder, 1)
        self.change_folder = QPushButton(tr("保存先を変更…"))
        self.change_folder.clicked.connect(lambda: (window.choose_output(), self.refresh_save()))
        folder_row.addWidget(self.change_folder)
        layout.addLayout(folder_row)
        self.heading(layout, tr("JPEGの保存品質"))
        quality_row = QHBoxLayout()
        quality_row.addWidget(QLabel(tr("品質")))
        self.quality = QSpinBox()
        self.quality.setRange(1, 100)
        self.quality.setValue(window.jpeg_quality)
        self.quality.valueChanged.connect(self.quality_changed)
        quality_row.addWidget(self.quality)
        quality_row.addStretch(1)
        layout.addLayout(quality_row)
        layout.addWidget(note(tr("1〜100。大きいほど画質が良く、ファイルは大きくなります（既定95）。JPEGで保存するときだけ使います。")))
        for widget in (self.format, self.change_folder, self.quality, self.overwrite, self.keep_originals):
            widget.setEnabled(widget.isEnabled() and idle)
        self.overwrite.toggled.connect(lambda *_args: self.refresh_save())
        self.refresh_save()

    def save_note(self, key):
        label = note("")
        self.save_notes[key] = label
        return label

    def refresh_save_notes(self, *_args):
        notes = self.window.save_notes()
        for key, label in self.save_notes.items():
            label.setText(notes[key])
        self.notice_note.setText(tr("起動するたびに、最初の上書きの前に一度だけ表示します。") if self.overwrite_notice.isChecked()
                                 else tr("確認を表示せずに上書きします。"))

    def language_changed(self, *_args):
        from .i18n import save_language, switch_note
        if save_language(self.window.preferences, self.language.currentData()):
            self.language_note.setText(switch_note(self.language.currentData()))

    def quit_confirmation_changed(self, show):
        data = dict(self.window.preferences.data)
        if show:
            data.pop("hide_quit_confirmation", None)
        else:
            data["hide_quit_confirmation"] = True
        try:
            self.window.preferences.save(data)
        except OSError:
            pass

    def notice_changed(self, show):
        self.refresh_save_notes()
        data = dict(self.window.preferences.data)
        if show:
            data.pop("hide_overwrite_notice", None)
        else:
            data["hide_overwrite_notice"] = True
        try:
            self.window.preferences.save(data)
        except OSError:
            pass

    def refresh_save(self):
        window = self.window
        separate = not window.overwrite.isChecked()
        self.format.setEnabled(separate and not window.busy() and not window.saving)
        self.change_folder.setEnabled(separate and not window.busy() and not window.saving)
        self.folder.setText(tr("保存先：") + (str(window.output_folder or tr("画像のあるフォルダー / Sumīre")) if separate else tr("元画像と同じ場所")))

    def quality_changed(self, value):
        window = self.window
        if window.jpeg_quality == value:
            return
        window.jpeg_quality = value
        window.format_combo.setItemText(1, tr("JPEG · 品質{value}・白背景").format(value=value))
        self.format.setItemText(1, tr("JPEG · 品質{value}・白背景").format(value=value))
        window.export_settings_changed()

    def records_page(self, layout):
        window = self.window
        mode = window.preferences.data.get("storage", "folder")
        layout.addWidget(note(tr("保存済みの状態・ラベル・メモ・加工マスク・復元用メタデータを記録しています。")))
        layout.addWidget(QLabel(tr("現在の保存先：") + (tr("アプリ専用の領域") if mode == "app" else tr("画像・出力フォルダー内"))))
        button = QPushButton(tr("保存先の変更・移行・削除…"))
        button.clicked.connect(lambda: (self.accept(), window.show_record_settings()))
        layout.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)

    def shortcuts_page(self, layout):
        layout.addWidget(note(tr("キーの割り当てを変更できます。同じキーを2つの操作に割り当てることはできません。")))
        button = QPushButton(tr("ショートカットキーを設定…"))
        button.clicked.connect(lambda: (self.accept(), self.window.show_shortcut_settings()))
        layout.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)

    def view_page(self, layout):
        window = self.window
        self.heading(layout, tr("表示言語"))
        self.language = QComboBox()
        for code, name in LANGUAGES.items():
            self.language.addItem(name, code)  # each language in its own words
        saved = window.preferences.data.get("language")
        self.language.setCurrentIndex(max(0, self.language.findData(saved if saved in LANGUAGES else language())))
        self.language.setAccessibleName("表示言語 / Language / 显示语言")
        self.language.currentIndexChanged.connect(self.language_changed)
        layout.addWidget(self.language)
        self.language_note = note(tr("次に起動したときから切り替わります。"))
        layout.addWidget(self.language_note)
        self.heading(layout, tr("表示"))
        layout.addWidget(self.mirror(window.navigator_action, tr("ナビゲーターを表示")))
        layout.addWidget(note(tr("拡大中に、画像全体のどこを表示しているかを右下に表示します。")))
        layout.addWidget(self.mirror(window.watch_action))
        layout.addWidget(note(tr("開いているフォルダーに新しく追加された画像を、一覧へ自動で加えます。")))
        layout.addWidget(self.mirror(window.auto_advance))
        layout.addWidget(note(tr("仕分けのラベルを付けると、自動で次の画像へ進みます。")))
        self.quit_confirmation = QCheckBox(tr("終了するときに確認を表示する"))
        self.quit_confirmation.setChecked(window.preferences.data.get("hide_quit_confirmation") is not True)
        self.quit_confirmation.toggled.connect(self.quit_confirmation_changed)
        layout.addWidget(self.quit_confirmation)
        layout.addWidget(note(tr("ウィンドウを閉じるときに、終了してよいかと、終了で消えるもの（編集の履歴・上書き前の元画像）を表示します。")))
        fullscreen = QPushButton(tr("全画面表示に切り替え"))
        fullscreen.clicked.connect(lambda: (self.accept(), window.editor_actions["fullscreen"].trigger()))
        layout.addWidget(fullscreen, 0, Qt.AlignmentFlag.AlignLeft)

    def novelai_page(self, layout):
        layout.addWidget(self.mirror(self.window.novelai_adjust))
        layout.addWidget(note(tr("「共有… → NovelAIでi2i」を選んだときに、渡す前の切り抜き・縮小の画面を表示します。")))

    def windows_page(self, layout):
        window = self.window
        layout.addWidget(note(tr("画像やフォルダーの右クリックに「Sumīreで開く」を追加します。"
                              "Windows 11では「その他のオプションを確認」の中に表示されます。"
                              "exeを移動したら登録し直し、exeを削除する前には解除してください。")))
        row = QHBoxLayout()
        for action in (window.explorer_install, window.explorer_remove):
            button = QPushButton(action.text())
            button.clicked.connect(lambda *_args, value=action: (self.accept(), value.trigger()))
            button.setEnabled(action.isEnabled())
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)

    def about_page(self, layout):
        window = self.window
        text = QLabel(window.diagnostic_text())
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text.setWordWrap(True)
        layout.addWidget(text)
        row = QHBoxLayout()
        for title, key in ((tr("ライセンス・このアプリについて"), "about"), (tr("前回のエラー詳細…"), "error"), (tr("ヘルプを開く"), "help")):
            button = QPushButton(title)
            button.clicked.connect(lambda *_args, value=key: (self.accept(), window.app_actions[value].trigger()))
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
