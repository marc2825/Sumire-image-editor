"""Whole-list work in a tab: removing metadata from every image and exporting many at once."""
from __future__ import annotations
from .i18n import tr

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from .export import Cancelled, available_target, check_cancel, detect_format, file_digest, kept_format, save_image
from .imaging import ImageProblem, load_image
from .masks import MaskStore
from .session import Receipts, source_key
from .ui import fact_table, html_text
from .backups import store as originals


class BatchFeatures:
    def begin_batch_progress(self, total):
        self.batch_progress.setRange(0, total)
        self.batch_progress.setValue(0)
        self.batch_progress.show()

    def update_batch_progress(self, completed, total):
        self.batch_progress.setRange(0, total)
        self.batch_progress.setValue(completed)

    def start_batch(self):
        if self.busy() or self.saving or not self.model.paths:
            return
        if any(self.is_clipboard_path(path) for path in self.model.paths):
            self.info(tr("クリップボードの画像は一括処理できません。1枚ずつ保存するか、「縮小・形式を指定して書き出す」で保存先を選んでください。"))
            return
        paths = list(self.model.paths)
        if not self.confirm_batch_deletion(paths):
            return
        if any(path not in self.model.rows for path in paths):
            self.info(tr("確認中に一覧が変更されました。もう一度実行してください。"))
            return
        self.guard(lambda: self._start_batch(paths=paths))

    def confirm_batch_deletion(self, paths):
        overwrite = self.overwrite.isChecked()
        dialog = QMessageBox(self)
        dialog.setWindowTitle(tr("メタデータの一括削除を確認"))
        dialog.setIcon(QMessageBox.Icon.Warning if overwrite else QMessageBox.Icon.Question)
        dialog.setTextFormat(Qt.TextFormat.RichText)
        dialog.setText(html_text(tr("このタブの画像 {count} 枚のメタデータを削除しますか？").format(count=len(paths))))
        rows = [(tr("対象"), tr("「{workspace_title}」の一覧全体（選択・絞り込みに関係なく）").format(workspace_title=self.workspace_title()))]
        if overwrite:
            rows += [(tr("保存方法"), tr("元画像に上書き（同じ場所・名前・形式）")),
                     (tr("元画像"), tr("アプリの終了まで残す（「上書き前に戻す」で戻せる）") if self.keep_originals.isChecked()
                      else tr("残さない（削除したメタデータは「元に戻す」で戻らない）"))]
        else:
            rows += [(tr("保存方法"), tr("別フォルダーへ保存（元画像は変えない）")), (tr("保存先"), str(self.output_folder)),
                     (tr("形式"), self.format_combo.currentText())]
        rows.append((tr("削除前の情報"), tr("復元用に残す（管理記録に圧縮して保存）") if self.metadata_backup.isChecked() else tr("残さない")))
        dialog.setInformativeText(fact_table(rows, [tr("モザイクなどの加工はそのまま保ちます。")]))
        dialog.setDetailedText("\n".join(str(path) for path in paths))
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        dialog.button(QMessageBox.StandardButton.Ok).setText(tr("削除して保存"))
        dialog.button(QMessageBox.StandardButton.Cancel).setText(tr("キャンセル"))
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        dialog.setEscapeButton(QMessageBox.StandardButton.Cancel)
        return self.confirm_dialog(dialog)

    def _start_batch(self, paths=None, export_folder=None, names=None, format=None):
        """Save or export ``paths``; ``names`` maps a path to a new file stem and
        ``format="SOURCE"`` keeps each PNG / JPEG / WebP format (others become PNG).

        ``export_folder`` is one folder, or {path: folder} to export into several."""
        paths = list(self.model.paths if paths is None else paths)
        if export_folder is None and any(self.is_clipboard_path(path) and
                (path not in self.documents or self.documents[path].output is None) for path in paths):
            self.info(tr("クリップボードの画像は個別に保存するか、保存先を選んで書き出してください。"))
            return
        backup_metadata = self.metadata_backup.isChecked()
        project_paths = {path for path, doc in self.documents.items() if getattr(doc, "project", False)}
        previous_failures = dict(self.batch_failures) if export_folder == getattr(self, "failed_export_folder", None) else {}
        self.begin_batch_progress(len(paths))
        export_folders = export_folder if isinstance(export_folder, dict) else None
        folder = self.output_folder if export_folder is None or export_folders is not None else export_folder
        receipts = Receipts(folder) if export_folder is not None and export_folders is None else self.receipts
        export_receipts = {target: Receipts(target) for target in set(export_folders.values())} if export_folders else {}
        chosen_format = format or self.format_combo.currentData()
        jpeg_quality = self.jpeg_quality
        overwrite = self.overwrite.isChecked() and export_folder is None
        keep_original = originals().keep if overwrite and self.keep_originals.isChecked() else None
        # Keep cached edits and reload verified outputs for other saved images.
        snapshots = {path: doc.image.copy() for path, doc in self.documents.items()}
        mask_snapshots = {path: doc.edit_mask.copy() for path, doc in self.documents.items()}
        source_digests = {path: doc.source_digest for path, doc in self.documents.items()}
        source_formats = {path: doc.source_format for path, doc in self.documents.items()}
        snapshot_states = {path: doc.edit_state for path, doc in self.documents.items()}
        geometry_snapshots = {path: list(doc.geometry_steps) for path, doc in self.documents.items()}
        geometry_digests = {path: doc.geometry_source_digest for path, doc in self.documents.items()}
        self.canvas.ready = False
        self.info(tr("保存済みを含む全画像を1枚ずつ処理中…"))
        indexes = {}

        def process(cancel, report):
            saved, failed = [], {}
            cancelled = False
            receipt_failures = 0
            saved_states = {}
            for path in paths:
                try:
                    check_cancel(cancel)
                    format = chosen_format if chosen_format != "SOURCE" else kept_format(source_formats.get(path) or detect_format(path))
                    if overwrite and path.parent not in indexes:
                        indexes[path.parent] = Receipts(path.parent)
                    index = indexes[path.parent] if overwrite else export_receipts[export_folders[path]] if export_folders else receipts
                    record = index.get(path, overwrite=overwrite)
                    edited = snapshot_states.get(path, False)
                    if path not in snapshot_states and record:
                        output = index.folder / record["name"]
                        if output.is_file() and file_digest(output).hex() == record["digest"]:
                            edited = record["edited"]
                    image = snapshots.get(path)
                    image_digest = None
                    if export_folder and image is None:
                        image = self.review_pixels(path)
                    source_digest = source_digests.get(path)
                    source_format = source_formats.get(path)
                    target = path if overwrite else None
                    owned_digest = None
                    if not overwrite:
                        record = index.get(path, overwrite=False)
                        if record:
                            output = index.folder / record["name"]
                            digest = bytes.fromhex(record["digest"])
                            if output.is_file() and file_digest(output) == digest:
                                if image is None:
                                    image = load_image(output)
                                    if file_digest(output) != digest:
                                        raise ImageProblem(tr("読み込み中に保存済み画像が変更されました。"))
                                    image_digest = digest
                                if record["format"] == format:
                                    target = output
                                    owned_digest = digest
                    if image is None:
                        source_digest = file_digest(path)
                        image = load_image(path)
                        source_format = image.format
                        if file_digest(path) != source_digest:
                            raise ImageProblem(tr("読み込み中に元画像が変更されました。"))
                    mask = mask_snapshots.get(path)
                    if mask is None:
                        prior_digest = image_digest or owned_digest or source_digest or file_digest(path)
                        mask = MaskStore(path.parent).get(path, prior_digest, image.size)
                    if target is None:
                        target = available_target(export_folders[path] if export_folders else folder,
                                                  names.get(path, path.stem) if names else path.stem, format)
                    previous_key = source_key(path) if overwrite else None
                    result = save_image(image, target, source=path, format=source_format if overwrite else format, cancel=cancel,
                                        owned_digest=owned_digest, overwrite_source=overwrite, source_digest=source_digest,
                                        backup_metadata=backup_metadata and path not in project_paths, jpeg_quality=jpeg_quality,
                                        backup=keep_original)
                    saved.append((path, result))
                    try:
                        index.record(path, result, previous_key=previous_key, edited=edited)
                    except OSError:
                        receipt_failures += 1
                    if mask is not None and export_folder is None:
                        try:
                            MaskStore(path.parent).store(path, result.digest, mask)
                            if not overwrite:
                                steps = geometry_snapshots.get(path)
                                if steps is None and image_digest:
                                    steps = MaskStore(path.parent).get_geometry(path, image_digest, source_digest or file_digest(path))
                                if steps is not None:
                                    MaskStore(path.parent).store_geometry(path, result.digest, steps, geometry_digests.get(path) or source_digest or file_digest(path))
                        except OSError:
                            receipt_failures += 1
                    saved_states[path] = edited
                except Cancelled:
                    cancelled = True
                    break
                except ImageProblem as error:
                    failed[path] = str(error)
                except OSError:
                    failed[path] = tr("画像の読み込み・保存に失敗しました。空き容量・アクセス権・元画像の存在を確認してください。")
                finally:
                    report(len(saved) + len(failed), len(paths))
            return saved, failed, cancelled, receipt_failures, saved_states

        def done(result):
            self.batch_job = None
            saved, failed, cancelled, receipt_failures, saved_states = result
            attempted = {path for path, _ in saved} | set(failed)
            self.batch_failures = {path: reason for path, reason in previous_failures.items() if cancelled and path not in attempted}
            self.batch_failures.update(failed)
            self.failed_export_folder = export_folder
            if overwrite:
                self.source_indexes.update(indexes)
            for path, output in saved:
                self.owned[output.path] = output.digest
                document = self.documents.get(path)
                self.model.state(path, "書出済み · メタデータ：無し" if export_folder else "未編集 · 保存済み · メタデータ：無し" if saved_states[path] is False else "保存済み · メタデータ：無し")
                if document and export_folder is None:
                    document.output = output.path
                    document.saved_revision = document.revision
                    if overwrite:
                        document.source_digest = output.digest
                if overwrite:
                    self.model.cache.pop(path, None)
            for path in failed:
                self.model.state(path, "保存失敗")
            self.info(tr("{value} · 保存 {count} / 失敗 {count2}").format(value=tr('一括処理を中止') if cancelled else tr('一括処理完了'), count=len(saved), count2=len(failed)))
            if failed:
                self.show_text_window(tr("保存できなかった画像"), "\n\n".join(f"{path}\n{reason}" for path, reason in failed.items()))
            if receipt_failures:
                self.info(self.status.text() + tr(" / 再開用の記録失敗 {receipt_failures}").format(receipt_failures=receipt_failures))
            self.update_controls()
            if self.document:
                self.prepare_effect()
                if self.auto.isChecked() and self.document.dirty:
                    self.autosave_timer.start()
            else:
                self._load_index(self.index)

        def failed(message):
            self.batch_job = None
            self.error(message + tr(" 完了した分は保存済みです。"))
            if self.document:
                self.prepare_effect()
            else:
                self._load_index(self.index)

        self.batch_job = self.run_job(process, done, failed, progress=self.update_batch_progress)
        self.batch_job.signals.cancelled.connect(lambda: failed(tr("一括処理を中止しました。")))
        self.update_controls()
