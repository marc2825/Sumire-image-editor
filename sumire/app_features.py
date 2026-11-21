"""Projects, presets, record settings, help and queued external opens."""
from .i18n import tr
from pathlib import Path
import platform
import sys

from PySide6 import __version__ as qt_version
from PIL import __version__ as pillow_version
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
    QInputDialog, QLabel, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
    QToolButton, QVBoxLayout,
)

from . import DISPLAY_VERSION
from .export import check_cancel, file_digest
from .labels import ReviewLabels, quick_tags, record_folder
from .projects import PROJECT_EXTENSIONS, read_project, write_project
from .session import Receipts
from .storage import delete_records, migrate_records, record_path
from .ui import COPYRIGHT, tool_button
from .archive_features import writes_files

DEFAULT_PRESETS = {
    "とても細かいモザイク": {"mode": "mosaic", "brush": 60, "strength": 6, "color": "#000000", "shape": "brush", "expansion": 1},
    "細かいモザイク": {"mode": "mosaic", "brush": 60, "strength": 12, "color": "#000000", "shape": "brush", "expansion": 1},
    "強いモザイク": {"mode": "mosaic", "brush": 120, "strength": 40, "color": "#000000", "shape": "brush", "expansion": 1},
    "黒塗り": {"mode": "fill", "brush": 90, "strength": 100, "color": "#000000", "shape": "brush", "expansion": 1},
}
# Built-in presets that settings saved before "preset_defaults" existed had already been offered.
FIRST_DEFAULTS = ("細かいモザイク", "強いモザイク", "黒塗り")


def valid_preset(value):
    return (isinstance(value, dict) and value.get("mode") in {"mosaic", "blur", "fill", "erase"}
            and type(value.get("brush")) is int and 4 <= value["brush"] <= 600
            and type(value.get("strength")) is int and (0 if value["mode"] == "fill" else 2) <= value["strength"] <= 100
            and value.get("shape") in {"brush", "rectangle", "ellipse", "polygon", "lasso"}
            and type(value.get("expansion")) is int and 0 <= value["expansion"] <= 3
            and isinstance(value.get("color"), str) and len(value["color"]) == 7 and value["color"].startswith("#")
            and all(c in "0123456789abcdefABCDEF" for c in value["color"][1:]))


class AppFeatures:
    def init_features(self):
        raw = self.preferences.data.get("presets", DEFAULT_PRESETS)
        self.presets = {name: value for name, value in raw.items() if isinstance(name, str) and 0 < len(name) <= 60 and valid_preset(value)} if isinstance(raw, dict) else dict(DEFAULT_PRESETS)
        # Offer built-in presets added since the presets were last saved, once:
        # a deleted built-in stays deleted.
        offered = self.preferences.data.get("preset_defaults", FIRST_DEFAULTS)
        offered = set(offered) if isinstance(offered, list | tuple) else set(FIRST_DEFAULTS)
        added = {name: value for name, value in DEFAULT_PRESETS.items() if name not in offered and name not in self.presets}
        self.presets = added | self.presets
        self.last_error = ""
        self.external_requests = []
        self.external_timer = QTimer(self)
        self.external_timer.setInterval(120)
        self.external_timer.timeout.connect(self.process_external)

    def create_app_actions(self):
        self.app_actions = {}
        for key, title, callback in [
            ("open_project", tr("編集プロジェクトを開く…"), self.choose_project),
            ("save_project", tr("元画像を含む編集プロジェクトを保存…"), self.save_project),
            ("records", tr("管理記録の保存先・移行・削除…"), self.show_record_settings),
            ("shortcuts", tr("ショートカットキー設定…"), self.show_shortcut_settings),
            ("help", tr("ヘルプ\tF1"), self.show_help),
            ("about", tr("Sumīreについて"), self.show_about),
            ("error", tr("前回のエラー詳細…"), self.show_error_details),
        ]:
            action = QAction(title, self)
            action.triggered.connect(lambda *_args, function=callback: function())
            self.app_actions[key] = action

    def build_file_menu(self, layout):
        """Keep opening files separate from the displayed workspace name."""
        menu = self.file_menu = QMenu(tr("ファイル"), self)
        menu.setToolTipsVisible(True)
        for action in (self.open_folder_action, self.open_files_action, self.open_archive_action, self.app_actions["open_project"]):
            menu.addAction(action)
        self.recent_menu = QMenu(tr("最近使ったフォルダー"), self)
        self.recent_menu.aboutToShow.connect(self.populate_recent_menu)
        menu.addMenu(self.recent_menu)
        menu.addAction(self.reload_action)
        menu.addAction(self.editor_actions["paste"])
        menu.addSeparator()
        menu.addAction(self.app_actions["save_project"])
        if self.workspace_host is not None:
            menu.addSeparator()
            self.new_tab_action = menu.addAction(tr("新しいタブ\tCtrl+T"), self.workspace_host.new_tab)
            self.close_tab_action = menu.addAction(tr("現在のタブを閉じる\tCtrl+W"), lambda: self.workspace_host.close_tab(self))
            self.close_all_tabs_action = menu.addAction(tr("すべての作業タブを閉じる"), self.workspace_host.close_all_tabs)
            menu.aboutToShow.connect(self.update_file_menu)
        self.file_button = QToolButton()
        self.file_button.setObjectName("fileMenu")
        self.file_button.setText(tr("ファイル  ▾"))
        self.file_button.setProperty("variant", "ghost")
        self.file_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.file_button.setAccessibleName(tr("ファイル"))
        self.file_button.setToolTip(tr("フォルダー・画像・編集プロジェクトを開く · Alt+F"))
        self.file_button.setMenu(menu)
        self.file_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        layout.addWidget(self.file_button)

    def update_file_menu(self):
        host = self.workspace_host
        self.close_tab_action.setEnabled(host.tabs.indexOf(self) >= 0)
        self.close_all_tabs_action.setEnabled(host.tabs.count() > 0)

    def build_app_menu(self, layout):
        """The gear opens every setting in one dialog (categories like the help)."""
        self.explorer_install.setToolTip(tr("Windowsの画像・フォルダーから直接開けます。Windows 11では「その他のオプションを確認」の中に表示されます。"))
        self.settings_button = tool_button("settings", tr("設定"), self.show_settings)
        self.settings_button.setAccessibleName(tr("設定"))
        layout.addWidget(self.settings_button)

    def show_settings(self, page=None):
        from .settings_dialog import SettingsDialog
        dialog = SettingsDialog(self)
        if page:
            dialog.open_page(page)
        self.settings_dialog = dialog
        try:
            dialog.exec()
        finally:
            self.settings_dialog = None
            dialog.deleteLater()

    def build_presets(self, layout):
        self.preset_combo = QComboBox()
        self.preset_combo.addItem(tr("プリセットを選択"), None)
        for name in self.presets:
            self.preset_combo.addItem(tr(name), name)  # built-in names are stored in Japanese
        self.preset_combo.setToolTip(tr("ツール・ブラシサイズ・強さ・色・形・範囲の拡張をまとめて切り替えます。"))
        self.preset_combo.activated.connect(lambda index: self.apply_preset(self.preset_combo.itemData(index)))
        layout.addWidget(self.preset_combo)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.preset_save = self._button(tr("現在の設定を登録"), self.save_preset, tr("今のツール・ブラシサイズ・強さ・色・形・範囲の拡張に名前を付けて登録します。"))
        self.preset_delete = self._button(tr("削除"), self.delete_preset, tr("選んでいるプリセットを削除します。"))
        row.addWidget(self.preset_save, 1)
        row.addWidget(self.preset_delete)
        layout.addLayout(row)

    def reset_all_settings(self):
        """Every setting back to its first-run value, in all tabs.

        Records (labels, notes, metadata backups) and where they are kept, the
        Windows integration and the recent folders are left as they are.
        """
        host = self.workspace_host
        pages = [self] if host is None else [host.welcome, *host.workspaces()]
        if any(page.busy() or page.saving for page in pages):
            self.error(tr("処理中は設定を戻せません。完了してから、もう一度お試しください。"))
            return False
        data = dict(self.preferences.data)
        for key in ("shortcuts", "presets", "preset_defaults", "hide_overwrite_notice", "hide_quit_confirmation", "quick_tags"):
            data.pop(key, None)
        data["settings"] = dict(self.default_settings)
        try:
            self.preferences.save(data)
        except OSError:
            self.error(tr("設定を保存できません。設定の保存先を確認してください。"))
            return False
        for page in pages:
            page.restore_settings(page.default_settings)
            page.show_presets(dict(DEFAULT_PRESETS))
            page.quick_tags = quick_tags(data)
            page.build_quick_tag_buttons()
        if host is not None:
            host.apply_shortcuts()
        else:
            self._shortcuts()
            self.update_controls()
        self.info(tr("設定を初期状態に戻しました。"))
        return True

    @writes_files
    def restore_metadata_copy(self):
        from .metadata import MetadataStore, restore_copy, unpack_backup
        from .imaging import ImageProblem
        if not self.document or self.busy() or self.saving:
            return
        document = self.document
        try:
            payload = None
            for path, digest in ((document.output, self.owned.get(document.output)), (document.path, document.source_digest)):
                if path and digest:
                    payload = MetadataStore(path.parent).get(path, digest)
                    if payload:
                        break
            if payload is None:
                self.error(tr("この画像の復元用メタデータがありません。復元できるのは、退避を有効にして削除した画像だけです。"))
                return
            format = unpack_backup(payload)[0]
            extension = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[format]
            suggested = document.path.with_name(document.path.stem + "_metadata" + extension)
            raw, _ = QFileDialog.getSaveFileName(self, tr("メタデータを復元して別名保存"), str(suggested), f"{format} (*{extension})")
            if not raw:
                return
            target = Path(raw)
            if not target.suffix:
                target = target.with_suffix(extension)
            pixels = document.image.copy()
            protected = [document.path] + ([document.output] if document.output else [])
            if target.resolve() in {path.resolve() for path in protected} or target.exists():
                self.error(tr("復元先には新しいファイル名を指定してください。元画像や既存ファイルは上書きしません。"))
                return
        except (OSError, ImageProblem):
            self.error(tr("復元用メタデータを読み込めません。管理記録と保存先を確認してください。"))
            return
        self.info(tr("メタデータを復元して別名保存中…"))
        self.auxiliary_job(lambda cancel: restore_copy(pixels, target, payload, protected=protected, cancel=cancel),
                           lambda path: tr("復元した画像を別名保存しました · {name} · メタデータ：有り").format(name=path.name))

    def apply_preset(self, name):
        value = self.presets.get(name)
        if self.busy() or self.saving or not valid_preset(value):
            return
        self.set_mode(value["mode"])
        self.brush.setValue(value["brush"])
        self.strength.setValue(value["strength"])
        self.color = value["color"]
        self.update_color_button()
        self.shape_combo.setCurrentIndex(self.shape_combo.findData(value["shape"]))
        self.expansion.setValue(value["expansion"])
        self.tool_changed()

    def save_preset(self):
        if self.busy() or self.saving:
            return
        if self.mode == "text":
            self.error(tr("テキストは編集プリセットに登録できません。ほかのツールを選んでから登録してください。"))
            return
        name, accepted = QInputDialog.getText(self, tr("編集プリセットを登録"), tr("名前（60文字以内）"), text=self.preset_combo.currentData() or "")
        name = name.strip()
        if not accepted or not name:
            return
        if len(name) > 60:
            self.error(tr("プリセット名は60文字以内で入力してください。"))
            return
        if name in self.presets and QMessageBox.question(self, tr("プリセットを更新"), tr("「{name}」の設定を置き換えますか？").format(name=name)) != QMessageBox.StandardButton.Yes:
            return
        values = dict(self.presets)
        values[name] = {"mode": self.mode, "brush": self.brush.value(), "strength": self.strength.value(), "color": self.color,
                        "shape": self.shape_combo.currentData(), "expansion": self.expansion.value()}
        self.persist_presets(values, name)

    def delete_preset(self):
        name = self.preset_combo.currentData()
        if self.busy() or self.saving or name not in self.presets:
            return
        if QMessageBox.question(self, tr("プリセットを削除"), tr("「{name}」を削除しますか？").format(name=name)) != QMessageBox.StandardButton.Yes:
            return
        self.persist_presets({key: value for key, value in self.presets.items() if key != name})

    def persist_presets(self, values, selected=None):
        try:
            self.preferences.save({**self.preferences.data, "presets": values, "preset_defaults": list(DEFAULT_PRESETS)})
        except OSError:
            self.error(tr("プリセットを保存できません。設定の保存先を確認してください。"))
            return
        self.show_presets(values, selected)

    def show_presets(self, values, selected=None):
        self.presets = values
        self.preset_combo.clear()
        self.preset_combo.addItem(tr("プリセットを選択"), None)
        for name in values:
            self.preset_combo.addItem(tr(name), name)  # built-in names are stored in Japanese
        self.preset_combo.setCurrentIndex(max(0, self.preset_combo.findData(selected)))

    def receive_external(self, inputs):
        self.external_requests.append(list(inputs))
        self.external_timer.start()

    def process_external(self):
        if self.closing or self.busy() or self.saving or self.pending_action is not None or QApplication.activeModalWidget():
            return
        if not self.external_requests:
            self.external_timer.stop()
            return
        inputs = self.external_requests.pop(0)
        self.showNormal() if self.isMinimized() else self.show()
        self.raise_()
        self.activateWindow()
        if inputs:
            self.open_inputs(inputs)

    def known_record_folders(self):
        folders = {record_folder(path) for path in self.model.paths}
        stored = self.preferences.data.get("record_folders", [])
        if isinstance(stored, list):
            folders.update(Path(folder) for folder in stored if isinstance(folder, str))
        if self.output_folder:
            folders.add(self.output_folder)
        workspaces = self.preferences.data.get("workspaces", {})
        if isinstance(workspaces, dict):
            for workspace in workspaces.values():
                if isinstance(workspace, dict) and isinstance(workspace.get("order"), list):
                    folders.update(Path(path).parent for path in workspace["order"] if isinstance(path, str))
        return folders

    def refresh_record_indexes(self, deleted=False):
        self.source_indexes = {}
        self.label_indexes = {folder: ReviewLabels(folder) for folder in {p.parent for p in self.model.paths}}
        self.receipts = Receipts(self.output_folder) if self.output_folder else None
        self.model.labels = {path: self.label_indexes[path.parent].get(path) for path in self.model.paths if self.label_indexes[path.parent].get(path)}
        self.model.notes = {path: self.label_indexes[path.parent].note(path) for path in self.model.paths if self.label_indexes[path.parent].note(path)}
        self.model.tags = {path: self.label_indexes[path.parent].tags_of(path) for path in self.model.paths if self.label_indexes[path.parent].tags_of(path)}
        self.refresh_tag_filter()
        if deleted:
            self.operation_history.clear()
            self.filter_combo.blockSignals(True)
            self.filter_combo.setCurrentIndex(0)
            self.filter_combo.blockSignals(False)
            self.clear_search()
            self.proxy.label = "all"
            for document in self.documents.values():
                document.edit_mask.paste(0, (0, 0, *document.image.size))
            self.canvas.refresh()
        selection = self.list.selectionModel()
        selection.blockSignals(True)
        self.proxy.refresh()
        selection.blockSignals(False)
        self.update_summary()
        if self.model.paths:
            self.model.dataChanged.emit(self.model.index(0), self.model.index(len(self.model.paths) - 1), [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole])
        self._select_current()

    def switch_record_storage(self, mode):
        if self.busy() or self.saving:
            return
        folders = self.known_record_folders()
        def work(cancel):
            check_cancel(cancel)
            return migrate_records(folders, mode, self.preferences)
        def done(count):
            self.refresh_record_indexes()
            return tr("管理記録の保存先を変更しました · {count}フォルダーを移行").format(count=count)
        self.auxiliary_job(work, done)

    def show_record_settings(self):
        if self.busy() or self.saving:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("管理記録の保存先・削除"))
        dialog.resize(580, 340)
        layout = QVBoxLayout(dialog)
        layout.addWidget(self._label(tr("保存済み状態・ラベル・メモ・加工マスク・復元用メタデータの保存先を選びます。設定と作業位置はアプリ設定領域に保存します。")))
        combo = QComboBox()
        combo.addItem(tr("画像・出力フォルダー内"), "folder")
        combo.addItem(tr("アプリ専用の領域（画像フォルダーに記録を置かない）"), "app")
        combo.setCurrentIndex(max(0, combo.findData(self.preferences.data.get("storage", "folder"))))
        layout.addWidget(combo)
        location = QLabel()
        location.setWordWrap(True)
        location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        def preview():
            folder = self.document.path.parent if self.document else Path.cwd()
            location.setText(tr("このフォルダーの記録：\n{record_path}\n\n設定・作業位置：\n{path}").format(record_path=record_path(folder, combo.currentData()), path=self.preferences.path))
        combo.currentIndexChanged.connect(preview)
        preview()
        layout.addWidget(location)
        move = QPushButton(tr("保存先を変更して既存の記録を移行"))
        move.clicked.connect(lambda: (dialog.accept(), self.switch_record_storage(combo.currentData())))
        layout.addWidget(move)
        remove = QPushButton(tr("現在の一覧・出力先の管理記録を削除"))
        def erase():
            if QMessageBox.question(dialog, tr("管理記録を削除"), tr("この一覧と出力先の保存記録・ラベル・メモ・加工マスク・復元用メタデータを削除します。削除するとメタデータは戻せません（画像と保存済みプロジェクトは残ります）。削除しますか？")) != QMessageBox.StandardButton.Yes:
                return
            folders = {record_folder(path) for path in self.model.paths}
            if self.output_folder:
                folders.add(self.output_folder)
            dialog.accept()
            def removed(count):
                self.refresh_record_indexes(deleted=True)
                return tr("管理記録を削除しました · {count}件").format(count=count)
            self.auxiliary_job(lambda cancel: delete_records(folders), removed)
        remove.clicked.connect(erase)
        remove.setEnabled(bool(self.model.paths))
        layout.addWidget(remove)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        self.confirm_dialog(dialog, accepted=QDialog.DialogCode.Accepted)

    def choose_project(self):
        if self.busy() or self.saving:
            return
        raw, _ = QFileDialog.getOpenFileName(self, tr("編集プロジェクトを開く"), "", tr("Sumīreプロジェクト (*.sumire *.sumi)"))
        if raw:
            self.open_inputs([raw])

    @writes_files
    def save_project(self):
        if not self.document or self.busy() or self.saving:
            return
        raw, _ = QFileDialog.getSaveFileName(self, tr("元画像を含む編集プロジェクトを保存"), str(self.document.path.with_suffix(".sumire")), tr("Sumīreプロジェクト (*.sumire)"))
        if not raw:
            return
        target = Path(raw)
        if not target.suffix:
            target = target.with_suffix(".sumire")
            if target.exists():
                self.error(tr("同名のプロジェクトがあります。別の名前を選んでください。"))
                return
        if target.suffix.lower() not in PROJECT_EXTENSIONS:
            self.error(tr("編集プロジェクトは.sumireで保存してください。"))
            return
        document = self.document
        # auxiliary_job locks edits before the worker starts; these immutable
        # references avoid cloning several full-resolution buffers at once.
        original, image, mask = document.original, document.image, document.edit_mask
        state = {"edited": document.edited, "original_edited": document.original_edited, "original_known": document.original_edit_status_known,
                 "geometry": document.geometry_edited}
        initial = document.initial_original if document.geometry_edited else None
        try:
            digest = file_digest(target) if target.exists() else None
        except OSError:
            self.error(tr("保存先のプロジェクトを確認できません。"))
            return
        self.auxiliary_job(lambda cancel: write_project(target, original, image, mask, state, cancel=cancel, expected_digest=digest, initial=initial),
                           lambda path: tr("編集プロジェクトを保存しました · {name}（加工前の画像を含みます）").format(name=path.name))

    def open_project(self, path):
        self.guard(lambda: self._open_project(path))

    def _open_project(self, path):
        if self.workspace_inputs:
            try:
                self.remember_workspace()
            except OSError:
                pass
        self.loading = True
        self.update_controls()
        def work(cancel):
            check_cancel(cancel)
            return read_project(path)
        def done(document):
            selection = self.list.selectionModel()
            selection.blockSignals(True)
            self.document = None
            self.index = -1
            self.documents.clear()
            self.owned.clear()
            self.operation_history.clear()
            self.archive = None
            self.archive_folder = ""
            self.model.set_paths([path])
            self.overwrite.blockSignals(True)
            self.overwrite.setChecked(False)
            self.overwrite.blockSignals(False)
            self.filter_combo.blockSignals(True)
            self.filter_combo.setCurrentIndex(0)
            self.filter_combo.blockSignals(False)
            self.clear_search()
            self.proxy.label = "all"
            self.proxy.refresh()
            selection.blockSignals(False)
            self.workspace_inputs = [str(path)]
            self.custom_title = None
            self.folder_root = None
            self.refresh_folders()
            self.watched_folders.clear()
            self.excluded_paths.clear()
            self.restoring_workspace = None
            self.sync_watch_scope()
            self.batch_failures.clear()
            if not self.custom_folder:
                from .legacy import default_output_folder
                self.output_folder = default_output_folder(path.parent)
            self.receipts = Receipts(self.output_folder)
            self.source_indexes.clear()
            self.label_indexes = {path.parent: ReviewLabels(path.parent)}
            self.documents[path] = document
            self.loading = False
            self.count_label.setText(tr("画像  1 枚"))
            self.refresh_record_indexes()
            self._activate(document, 0)
            self.info(tr("編集プロジェクトを開きました。画像は別フォルダーへ書き出します。"))
        def failed(message):
            self.loading = False
            self.error(message)
        self.load_job = self.run_job(work, done, failed)
        self.load_job.signals.cancelled.connect(self._load_cancelled)

    def diagnostic_text(self):
        return (tr("Sumīre {version__}\nOS: {system} {release}\nPython: {python_version}\nPySide6: {qt_version}\nPillow: {pillow_version}\n起動形式: {value}\nエラー: {value2}").format(version__=DISPLAY_VERSION, system=platform.system(), release=platform.release(), python_version=platform.python_version(), qt_version=qt_version, pillow_version=pillow_version, value='exe' if getattr(sys, 'frozen', False) else 'Python', value2=self.last_error or tr('記録なし')))

    def show_error_details(self):
        self.text_dialog(tr("前回のエラー詳細"), self.diagnostic_text(), copy=True)

    def show_about(self):
        self.text_dialog(tr("Sumīreについて"), tr("Sumīre {version__}\n画像の仕上げ・選別・メタデータ削除\n{COPYRIGHT}　MIT License\n\nこのアプリは次のライブラリーを使っています。\nQt・PySide6：Copyright (C) The Qt Company Ltd. and other contributors. GNU LGPL v3（ライセンス文は licenses/Qt、差し替え方法は QT_REPLACEMENT.md）\nPillow：MIT-CMU\nNoto Sans JP：© 2014-2021 Adobe. SIL Open Font License 1.1\nほかのライセンスは THIRD_PARTY_NOTICES.md と licenses フォルダーにあります。\n\n画像の処理と記録はPC内で行います。NovelAIへの共有では、ブラウザーでNovelAIのページを開くだけです。\n\n").format(version__=DISPLAY_VERSION, COPYRIGHT=COPYRIGHT) + self.diagnostic_text())

    def show_text_window(self, title, text):
        """A non-blocking report (e.g. failed images after a batch); closes with the window."""
        dialog = QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.setWindowTitle(title)
        dialog.resize(650, 420)
        layout = QVBoxLayout(dialog)
        view = QPlainTextEdit(text)
        view.setReadOnly(True)
        layout.addWidget(view)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        # Non-modal: the report never blocks editing, other tabs or later dialogs.
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        previous = getattr(self, "report_window", None)
        if previous is not None:
            try:
                previous.close()
            except RuntimeError:
                pass
        self.report_window = dialog
        dialog.destroyed.connect(lambda *_args: setattr(self, "report_window", None) if self.report_window is dialog else None)
        dialog.show()
        return dialog

    def text_dialog(self, title, text, copy=False):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(650, 470)
        layout = QVBoxLayout(dialog)
        view = QPlainTextEdit(text)
        view.setReadOnly(True)
        layout.addWidget(view)
        if copy:
            button = QPushButton(tr("詳細をコピー"))
            button.clicked.connect(lambda: QApplication.clipboard().setText(text))
            layout.addWidget(button)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def feature_help(self):
        from .help import HelpDialog
        dialog = HelpDialog(self)
        dialog.exec()
        dialog.deleteLater()
