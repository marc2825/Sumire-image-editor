"""A ZIP opened in a tab: its images in the list, its folders in the folder bar, read only.

The tab works like a folder tab (list, thumbnails, ←/→, zoom, comparison, labels, tags, notes),
except that nothing may change the ZIP or the images in it: editing, saving, renaming, moving,
deleting, converting and the like are switched off in the window and refused where they start
(``writes_files``), so shortcuts, menus and drops cannot reach them either. Labels, tags and notes
go to Sumīre's records (the ZIP's folder), never into the ZIP. Chosen images can be exported as
copies of their bytes (``archive.export_entries``).
"""
from __future__ import annotations

import functools
from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QLabel, QVBoxLayout

from .archive import ArchiveEntry, export_entries, read_catalog
from .i18n import tr
from .labels import ReviewLabels

FOLDER_MARK = "\0zip:"  # folder bar rows inside a ZIP carry this before the folder's path in the ZIP


def writes_files(method):
    """Refuse ``method`` in a ZIP tab: it would change images or files there."""
    @functools.wraps(method)
    def guarded(self, *args, **kwargs):
        if getattr(self, "archive", None) is not None:
            self.info(tr("ZIPの中の画像は変更できません（読み取り専用）。取り出すときは「ZIPから書き出す」を使ってください。"))
            return None
        return method(self, *args, **kwargs)
    return guarded


def modified_key(path):
    """Sort key for 「更新日時順」: the file's time, or the time stored in the ZIP for an image in it."""
    if isinstance(path, ArchiveEntry):
        return path.modified
    return path.stat().st_mtime_ns


class ArchiveFeatures:
    def init_archive(self):
        self.archive = None  # ArchiveCatalog of the ZIP shown in this tab
        self.archive_folder = ""  # the folder inside the ZIP that the list shows
        self.archive_target = None  # the folder inside the ZIP to show after it is (re)listed

    @property
    def read_only(self):
        return self.archive is not None

    def choose_archive(self):
        if self.busy() or self.saving:
            return
        raw, _ = QFileDialog.getOpenFileName(self, tr("ZIPを開く"), "", tr("ZIPファイル (*.zip)"))
        if raw:
            self.open_inputs([raw])

    def open_archive(self, path):
        """List the ZIP (its directory only) and show its images; nothing is extracted."""
        if self.workspace_inputs:
            try:
                self.remember_workspace()
            except OSError:
                pass
        restoring = self.restoring_workspace is not None
        workspace = self.restoring_workspace if restoring else self.saved_workspace([str(path)])
        self.restoring_workspace = None
        target = self.archive_target if self.archive_target is not None else workspace.get("archive_folder", "")
        self.archive_target = None
        order = workspace.get("sort", "name_asc")
        if not isinstance(order, str) or order not in {"manual", "name_asc", "name_desc", "date_asc", "date_desc"}:
            order = "name_asc"
        self.loading = True
        self.info(tr("ZIPの中身を読み込み中…"))
        self.update_controls()

        def scan(cancel):
            catalog = read_catalog(path, cancel)
            return catalog, ReviewLabels(catalog.path.parent)

        def done(result):
            catalog, labels = result
            self.loading = False
            self.document = None
            self.canvas.set_document(None)
            self.documents.clear()
            self.owned.clear()
            self.operation_history.clear()
            self.batch_failures.clear()
            self.excluded_paths = set()
            self.archive = catalog
            self.receipts = None
            self.source_indexes = {}
            self.label_indexes = {catalog.path.parent: labels}
            self.workspace_inputs = [str(catalog.path)]
            self.watched_folders = set()
            self.sync_watch_scope()
            self.folder_root = None
            title = workspace.get("title")
            self.custom_title = " ".join(title.split())[:60] or None if isinstance(title, str) else None
            self.filter_combo.blockSignals(True)
            self.filter_combo.setCurrentIndex(max(0, self.filter_combo.findData(workspace.get("filter", "all"))))
            self.filter_combo.blockSignals(False)
            self.clear_search()
            if restoring and isinstance(workspace.get("search"), str):
                self.search.blockSignals(True)
                self.search.setText(workspace["search"])
                self.search.blockSignals(False)
                self.proxy.text = workspace["search"].strip()
            self.proxy.label = self.filter_combo.currentData()
            self.sort_combo.blockSignals(True)
            self.sort_combo.setCurrentIndex(self.sort_combo.findData(order))
            self.sort_combo.blockSignals(False)
            folder = target if isinstance(target, str) and target in catalog.folders else ""
            if not folder:
                # A ZIP of one folder (the usual way to zip a folder): go straight into it.
                while not catalog.entries_in(folder) and len(catalog.subfolders(folder)) == 1:
                    folder = catalog.subfolders(folder)[0]
            self.show_archive_folder(folder, workspace.get("current"), workspace.get("order") if order == "manual" else None)
            count = len(catalog.entries)
            message = tr("ZIPを開きました（読み取り専用） · 画像 {count} 枚").format(count=count)
            if count and not self.model.paths:
                message += tr(" · 画像はフォルダーの中にあります（一覧の上の欄から開けます）")
            skipped = catalog.skipped_text()
            self.info(message + (" · " + skipped if skipped else "") if count or skipped else tr("このZIPには対応する画像がありません。"))

        def failed(message):
            self.loading = False
            self.error(message)
            self.update_controls()

        self.load_job = self.run_job(scan, done, failed)
        self.load_job.signals.cancelled.connect(self._load_cancelled)

    def show_archive_folder(self, folder, current=None, stored_order=None):
        """List the images directly in ``folder`` of the ZIP (like a folder: its subfolders go in the folder bar)."""
        catalog = self.archive
        if catalog is None:
            return
        self.archive_folder = folder
        order = self.sort_combo.currentData() or "name_asc"
        entries = self.ordered_paths(catalog.entries_in(folder), order)
        if isinstance(stored_order, list):
            found = {str(entry): entry for entry in entries}
            restored = [found[raw] for raw in dict.fromkeys(raw for raw in stored_order if isinstance(raw, str)) if raw in found]
            placed = set(restored)
            entries = restored + [entry for entry in entries if entry not in placed]
        folder_records = catalog.path.parent
        if folder_records not in self.label_indexes:
            self.label_indexes[folder_records] = ReviewLabels(folder_records)
        labels = self.label_indexes[folder_records]  # the records of the ZIP's folder (never the ZIP)
        selection = self.list.selectionModel()
        selection.blockSignals(True)
        self.index = -1
        self.document = None
        self.canvas.set_document(None)
        self.model.set_paths(entries)
        self.model.labels.update({entry: label for entry in entries if (label := labels.get(entry))})
        self.model.notes.update({entry: note for entry in entries if (note := labels.note(entry))})
        self.model.tags.update({entry: tags for entry in entries if (tags := labels.tags_of(entry))})
        self.refresh_tag_filter()
        self.proxy.refresh()
        selection.blockSignals(False)
        self.name.clear()
        self.setWindowTitle(f"{catalog.path.name} — Sumīre")
        self.count_label.setText(tr("画像  {count} 枚").format(count=len(entries)))
        self.refresh_folders()
        self.update_page()
        visible = self.visible_paths()
        target = next((entry for entry in visible if str(entry) == current), visible[0] if visible else None)
        if target is not None:
            self._load_index(self.model.rows[target])
        else:
            self.ensure_visible_current()
            self.update_controls()

    def open_archive_folder(self, folder):
        if self.archive is None or self.busy() or self.saving or folder not in self.archive.folders:
            return
        if folder != self.archive_folder:
            self.guard(lambda: self.show_archive_folder(folder))

    def archive_location(self):
        """「name.zip / folder / folder」 for the folder bar."""
        if self.archive is None:
            return ""
        return " / ".join([self.archive.path.name, *(self.archive_folder.split("/") if self.archive_folder else [])])

    def archive_folder_rows(self):
        """(row data, text, icon) for the folder bar: the folder above and the folders inside."""
        rows = []
        if self.archive_folder:
            parent = self.archive_folder.rsplit("/", 1)[0] if "/" in self.archive_folder else ""
            rows.append((FOLDER_MARK + parent, tr("..（上のフォルダー）"), "folder_up"))
        rows.extend((FOLDER_MARK + folder, folder.rsplit("/", 1)[-1], "folder") for folder in self.archive.subfolders(self.archive_folder))
        return rows

    def folder_row_opened(self, raw):
        if raw.startswith(FOLDER_MARK):
            self.open_archive_folder(raw[len(FOLDER_MARK):])
        else:
            self.open_folder_in_tab(Path(raw))

    def open_archive_parent(self):
        if self.archive is not None and self.archive_folder:
            self.open_archive_folder(self.archive_folder.rsplit("/", 1)[0] if "/" in self.archive_folder else "")

    def export_from_archive(self):
        """Write the chosen images of the ZIP (their bytes, unchanged) into a folder chosen by the user."""
        entries = [path for path in self.selected_or_current() if isinstance(path, ArchiveEntry)]
        if self.archive is None or not entries or self.busy() or self.saving:
            return
        dialog = ArchiveExportDialog(len(entries), any(entry.folder for entry in entries), self)
        if not self.confirm_dialog(dialog, accepted=QDialog.DialogCode.Accepted):
            return
        folder = QFileDialog.getExistingDirectory(self, tr("書き出し先のフォルダー"), str(self.archive.path.parent))
        if not folder or self.busy() or self.saving:
            return
        destination = Path(folder).resolve()
        if destination == self.archive.path or destination.is_relative_to(self.archive.path):
            self.error(tr("ZIPの中には書き出せません。別のフォルダーを選んでください。"))
            return
        keep = dialog.keep_folders.isChecked()
        self.begin_batch_progress(len(entries))
        self.info(tr("ZIPから書き出し中…"))

        def work(cancel, report):
            return export_entries(entries, destination, keep_folders=keep, cancel=cancel, progress=report)

        def done(written):
            self.batch_job = None
            self.batch_progress.hide()
            renamed = sum(1 for entry, path in written.items() if path.name != entry.name)
            self.info(tr("ZIPから書き出しました · {count}枚 · {folder}").format(count=len(written), folder=destination)
                      + (tr(" · 同じ名前があったため {count} 枚に番号を付けました").format(count=renamed) if renamed else ""))
            self.update_controls()

        def failed(message):
            self.batch_job = None
            self.batch_progress.hide()
            self.error(message)
            self.update_controls()

        self.batch_job = self.run_job(work, done, failed, progress=self.update_batch_progress)
        self.batch_job.signals.cancelled.connect(lambda: failed(tr("書き出しを中止しました。書き出し済みのファイルは残っています。")))
        self.update_controls()

    def read_only_widgets(self):
        """Controls that would change the images (or files next to them); off in a ZIP tab."""
        workflow = ("save_as", "save_selected", "delete_selected", "number_selected", "cut_files", "copy_files", "paste_files",
                    "duplicates", "convert_all", "compress_all", "convert_selected", "compress_selected", "collage",
                    "merge_labels", "export_accepted", "reset_list")
        return [self.manual_save, self.metadata_button, self.metadata_delete_button, self.batch_button, self.batch_delete_button, self.export_accepted_button,
                self.rename_button, self.file_label, self.number_button, self.restore_original_button, self.restore_original_action,
                self.metadata_restore, self.mask_export, self.reset_edits_action, self.reset_edits_button, self.crop_tool,
                self.share_button, *self.share_actions.values(), self.editor_actions["edit"], self.editor_actions["color"],
                self.editor_actions["upscale"], self.app_actions["save_project"], *(self.workflow_actions[key] for key in workflow),
                self.new_folder_button, self.shape_combo, self.brush, self.brush_box, self.strength, self.strength_box,
                self.expansion, self.expansion_box, *self.transform_buttons, self.color_button_adjust, self.auto_sort_action,
                *(button for _, button in self.mode_buttons), self.weak_button, self.strong_button, self.color_button]

    def apply_read_only_controls(self):
        archive = self.archive is not None
        self.workflow_actions["export_archive"].setVisible(archive)
        if self.tools_scroll.isHidden() != archive:
            self.tools_scroll.setVisible(not archive)
            self.read_only_note.setVisible(archive)
        if not archive:
            return
        for widget in self.read_only_widgets():
            widget.setEnabled(False)
        self.canvas.locked = True  # no strokes or text; zoom and panning stay
        self.workflow_actions["export_archive"].setEnabled(bool(self.document or self.selected_paths()) and not self.busy() and not self.saving)
        self.save_next_button.setText(tr("次へ →"))
        self.save_next_button.setEnabled(self.document is not None and not self.busy())


class ArchiveExportDialog(QDialog):
    def __init__(self, count, has_folders, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("ZIPから書き出す"))
        layout = QVBoxLayout(self)
        label = QLabel(tr("選んだ画像 {count} 枚を、元のデータのままフォルダーへ書き出します。ZIPは変更しません。"
                          "同じ名前のファイルがあるときは、上書きせずに番号を付けます。").format(count=count))
        label.setWordWrap(True)
        layout.addWidget(label)
        self.keep_folders = QCheckBox(tr("ZIPの中のフォルダー構成を保つ"))
        self.keep_folders.setEnabled(has_folders)
        layout.addWidget(self.keep_folders)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("書き出し先を選ぶ…"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("キャンセル"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
