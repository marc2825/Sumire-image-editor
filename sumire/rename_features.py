"""Renaming images in a tab: one image, numbered names, and the journaled rename itself."""
from __future__ import annotations
from .i18n import tr

from collections import OrderedDict
from pathlib import Path

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit, QVBoxLayout

from .export import file_digest
from .imaging import ImageProblem
from .labels import ReviewLabels
from .organize import rename_images, renamed_path, sequence_stems
from .session import Receipts


class RenameFeatures:
    def rename_current(self):
        if not self.document or self.busy() or self.saving:
            return
        self.file_label.begin_edit()

    def remember_rename_source(self):
        self.inline_rename_source = self.document.path if self.document else None

    def rename_inline(self, stem):
        source = getattr(self, "inline_rename_source", None)
        if source is not None:
            self.rename_source(source, stem)

    def rename_source(self, source, stem):
        if source not in self.model.rows or self.busy() or self.saving:
            return
        try:
            target = renamed_path(source, stem)
        except ImageProblem as error:
            self.error(str(error))
            return
        self.rename_paths({source: target})

    def number_images(self, paths=None):
        if not self.model.paths or self.busy() or self.saving:
            return
        paths = paths if isinstance(paths, list) else self.model.paths
        if not paths:
            return
        stems = sequence_stems(len(paths))
        mapping = {path: renamed_path(path, stem) for path, stem in zip(paths, stems)}
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("順に連番へ改名"))
        dialog.resize(620, 440)
        layout = QVBoxLayout(dialog)
        layout.addWidget(self._label(tr("{count}枚を、一覧の順番で {stems} 〜 {stems2} の連番に変更します。（画像自体は変わりません）").format(count=len(mapping), stems=stems[0], stems2=stems[-1])))
        preview = QPlainTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText("\n".join(f"{old}  →  {new.name}" for old, new in mapping.items()))
        layout.addWidget(preview)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("名前を変更"))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.rename_paths(mapping)

    def rename_paths(self, mapping, undoing=False):
        if self.busy() or self.saving or not mapping or all(str(old) == str(new) for old, new in mapping.items()):
            return
        if self.workspace_host is not None and not self.workspace_host.can_rename(self, mapping):
            self.error(tr("同じ画像を別のタブで処理中です。完了してから名前を変更してください。"))
            return
        self.guard(lambda: self._rename_paths(mapping, undoing=undoing))

    def _rename_paths(self, mapping, undoing=False):
        paths = [mapping.get(path, path) for path in self.model.paths]
        selected = self.document.path if self.document else self.model.paths[max(0, self.index)]
        self.begin_batch_progress(len(mapping))
        self.canvas.ready = False
        self.info(tr("画像の名前を変更中…"))
        record_folders = self.workspace_host.rename_record_folders(mapping) if self.workspace_host is not None else set()

        def process(cancel, report):
            image_folders = {path.parent for path in mapping}
            folders = image_folders | set(record_folders) | ({self.receipts.folder} if self.receipts else set())
            expected = self.operation_history[-1][1][1] if undoing else None
            # The records (save receipts, labels, notes, tags, masks) are renamed in the same journaled
            # transaction as the files: if one cannot be updated, the whole rename stops with an error.
            rename_images(mapping, cancel=cancel, progress=report, expected_digests=expected, record_folders=folders)
            indexes = {folder: Receipts(folder) for folder in folders}
            label_indexes = {folder: ReviewLabels(folder) for folder in image_folders}
            digests = {new: file_digest(new) for new in mapping.values()}
            return indexes, label_indexes, digests

        def done(result):
            self.batch_job = None
            indexes, label_indexes, digests = result
            self.source_indexes.update(indexes)
            if self.receipts and self.receipts.folder in indexes:
                self.receipts = indexes[self.receipts.folder]
            self.label_indexes.update(label_indexes)
            documents = OrderedDict()
            for old, document in self.documents.items():
                document.path = mapping.get(old, old)
                document.output = mapping.get(document.output, document.output)
                documents[document.path] = document
            self.documents = documents
            self.clean_states = {mapping.get(path, path): state for path, state in self.clean_states.items()}
            self.owned = {mapping.get(path, path): digest for path, digest in self.owned.items()}
            self.batch_failures = {mapping.get(path, path): message for path, message in self.batch_failures.items()}
            self.workspace_inputs = [str(mapping.get(Path(raw).resolve(), Path(raw))) for raw in self.workspace_inputs]
            if undoing:
                self.operation_history.pop()
            else:
                self.operation_history.append(("rename", ({new: old for old, new in mapping.items()}, digests)))
            self.replace_list(paths, mapping)
            self.sort_combo.blockSignals(True)
            self.sort_combo.setCurrentIndex(self.sort_combo.findData("manual"))
            self.sort_combo.blockSignals(False)
            if self.document:
                self.name.setText(self.document.output.stem if self.document.output else self.document.path.stem)
                self.setWindowTitle(f"{self.document.path.name} — Sumīre")
                self.prepare_effect()
            else:
                self._load_index(self.model.rows[mapping.get(selected, selected)])
            self.info(tr("名前を変更しました · {count}枚").format(count=len(mapping)))
            self.update_controls()
            self.pathsRenamed.emit(mapping)

        def failed(message):
            self.batch_job = None
            self.error(message)
            if self.document:
                self.prepare_effect()
            else:
                self._load_index(self.model.rows[selected])

        self.batch_job = self.run_job(process, done, failed, progress=self.update_batch_progress)
        self.batch_job.signals.cancelled.connect(lambda: failed(tr("名前の変更を中止し、元の名前に戻しました。")))
        self.update_controls()
