"""Writing new files from the workspace: conversion, compression, save-as, collages, in-place 超解像."""
from __future__ import annotations
from .i18n import tr

from pathlib import Path
import shutil
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from .backups import store as originals
from .convert import TARGETS, Encoding, commit, encode, format_bytes, replace_original, size_summary, stage, writable
from .editing import EditSpec
from .export import available_target, check_cancel, detect_format, file_digest
from .imaging import ImageProblem
from .ui import fact_table, html_text

SAVE_AS_QUALITY = {"JPEG": None, "AVIF": 80, "HEIF": 80}


class OutputFeatures:
    # --- conversion and compression -------------------------------------------------
    def convert_images(self, paths, mode):
        """``mode`` is "convert" (format) or "compress" (size); originals are never changed."""
        if not paths or self.busy() or self.saving:
            return
        from .output_dialogs import ConvertDialog
        paths = list(paths)
        sample = paths[0]
        snapshot = self.documents[sample].image if sample in self.documents else None
        try:
            original_size = sample.stat().st_size
        except OSError:
            original_size = 0
        source = (sample.name, original_size, (lambda: snapshot) if snapshot is not None else (lambda: self.review_pixels(sample)))
        dialog = ConvertDialog(mode, len(paths), self.default_new_folder_parent(paths), source,
                               backup=self.metadata_backup.isChecked(), source_format=detect_format(sample),
                               keep_originals=self.keep_originals.isChecked(), parent=self)
        if not self.confirm_dialog(dialog, accepted=QDialog.DialogCode.Accepted) or self.busy() or self.saving:
            return
        try:
            folder = dialog.destination()
            encoding = dialog.encoding()
        except ImageProblem as error:
            self.error(str(error))
            return
        paths = [path for path in paths if path in self.model.rows]
        if paths:
            self.prepare_conversion(paths, encoding, folder, mode, replace=dialog.replace_originals())

    def prepare_conversion(self, paths, encoding, folder, mode, replace=False):
        """Encode every image into hidden staging files, then confirm with the real sizes.

        ``replace`` (size reduction only) puts each result in place of its original
        instead of into ``folder``; only images whose format stays the same.
        """
        label = tr("容量削減") if mode == "compress" else tr("変換")
        try:
            if replace:
                created = False
                staging = Path(tempfile.mkdtemp(prefix="sumire-staging-"))
            else:
                created = not folder.exists()
                folder.mkdir(parents=True, exist_ok=True)
                staging = Path(tempfile.mkdtemp(prefix=".sumire-staging-", dir=folder))
        except OSError:
            self.error(tr("保存先のフォルダーを作成できません。場所とアクセス権を確認してください。"))
            return
        projects = {path for path, doc in self.documents.items() if getattr(doc, "project", False)}
        self.autosave_timer.stop()
        snapshots = {path: doc.image for path, doc in self.documents.items() if path in paths}
        self.begin_batch_progress(len(paths))
        self.info(tr("{label}後のサイズを計算中…").format(label=label))

        def work(cancel, report):
            staged, failed = [], {}
            for number, path in enumerate(paths, 1):
                try:
                    check_cancel(cancel)
                    digest = None
                    if replace:
                        source_format = detect_format(path)
                        if source_format != encoding.format:
                            raise ImageProblem(tr("形式が変わるため上書きしません（{source} → {target}）。").format(
                                source=TARGETS.get(source_format, (source_format or "?",))[0], target=TARGETS[encoding.format][0]))
                        if path in projects or self.is_clipboard_path(path):
                            raise ImageProblem(tr("編集プロジェクトとクリップボードの画像は上書きしません。"))
                        digest = file_digest(path)
                    image = snapshots[path] if path in snapshots else self.review_pixels(path)
                    raw = encode(image, encoding)
                    check_cancel(cancel)
                    staged.append((path, stage(raw, staging), path.stat().st_size, len(raw), digest))
                except ImageProblem as error:
                    failed[path] = str(error)
                except OSError:
                    failed[path] = tr("画像の読み込み・一時保存に失敗しました。空き容量とアクセス権を確認してください。")
                report(number, len(paths))
            return staged, failed

        def discard():
            shutil.rmtree(staging, ignore_errors=True)
            if created:
                try:
                    folder.rmdir()
                except OSError:
                    pass

        def done(result):
            self.batch_job = None
            self.update_controls()
            staged, failed = result
            if not staged:
                discard()
                self.error(tr("{label}できる画像がありませんでした。").format(label=label) + (tr(" 失敗 {count}枚").format(count=len(failed)) if failed else ""))
                if failed:
                    self.show_failures_text(failed)
                return
            if not self.confirm_conversion(staged, failed, encoding, folder, mode, replace) or self.busy() or self.saving:
                discard()
                self.info(tr("{label}を取り消しました。ファイルは書き出していません。").format(label=label))
                return
            self.commit_conversion(staged, failed, encoding, folder, staging, mode, replace)

        def failed(message):
            self.batch_job = None
            discard()
            self.error(message)

        self.batch_job = self.run_job(work, done, failed, progress=self.update_batch_progress)
        self.batch_job.signals.cancelled.connect(lambda: failed(tr("{label}を中止しました。ファイルは書き出していません。").format(label=label)))
        self.update_controls()

    def confirm_conversion(self, staged, failed, encoding, folder, mode, replace=False):
        before = sum(item[2] for item in staged)
        after = sum(item[3] for item in staged)
        compress = mode == "compress"
        name = TARGETS[encoding.format][0]
        dialog = QMessageBox(self)
        dialog.setWindowTitle(tr("容量削減の確認") if compress else tr("形式変換の確認"))
        dialog.setIcon(QMessageBox.Icon.Warning if replace else QMessageBox.Icon.Question)
        dialog.setTextFormat(Qt.TextFormat.RichText)
        prefix = tr("元画像 合計") if len(staged) > 1 else tr("元画像")
        dialog.setText(html_text(size_summary(before, after, (tr("圧縮後") if compress else tr("変換後")) + (tr(" 合計") if len(staged) > 1 else ""), prefix)))
        quality = tr("品質{quality}・").format(quality=encoding.quality) if encoding.quality else ""
        backup = self.metadata_backup.isChecked()
        rows = [(tr("対象"), tr("{count}枚").format(count=len(staged))),
                (tr("形式"), tr("{name}（{quality}{value}）").format(name=name, quality=quality, value=tr('非可逆') if encoding.lossy else tr('可逆'))),
                (tr("縮小"), tr("長辺を{max_side}px以下に").format(max_side=encoding.max_side) if encoding.max_side else ""),
                (tr("保存先"), tr("元画像に上書き（同じ場所・名前）") if replace else str(folder)),
                (tr("元画像"), (tr("置き換える（アプリの終了まで残し、「上書き前に戻す」で戻せる）") if self.keep_originals.isChecked()
                                else tr("置き換える（元のファイルは残らない）")) if replace else tr("変更しない")),
                (tr("メタデータ"), tr("含めない（復元用に管理記録へ残す）") if backup else tr("含めない")),
                (tr("処理できない画像"), tr("{count}枚（詳細を参照）").format(count=len(failed)) if failed else "")]
        dialog.setInformativeText(fact_table(rows, [tr("編集中の画像は、今の加工を含めて置き換えます。編集の履歴は消えます。") if replace else ""]))
        details = [f"{path.name}\t{size_summary(old, new, '', '')}" for path, _, old, new, _ in staged]
        details += [tr("{name}\t失敗：{reason}").format(name=path.name, reason=reason) for path, reason in failed.items()]
        dialog.setDetailedText("\n".join(details))
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        dialog.button(QMessageBox.StandardButton.Ok).setText(tr("上書きする") if replace else tr("書き出す"))
        dialog.button(QMessageBox.StandardButton.Cancel).setText(tr("キャンセル"))
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel if replace else QMessageBox.StandardButton.Ok)
        dialog.setEscapeButton(QMessageBox.StandardButton.Cancel)
        return self.confirm_dialog(dialog)

    def commit_conversion(self, staged, failed, encoding, folder, staging, mode, replace=False):
        label = tr("容量削減") if mode == "compress" else tr("変換")
        backup = self.metadata_backup.isChecked()
        keep_original = originals().keep if replace and self.keep_originals.isChecked() else None
        projects = {path for path, doc in self.documents.items() if getattr(doc, "project", False)}
        self.begin_batch_progress(len(staged))

        def work(cancel, report):
            written, problems, reserved = [], dict(failed), set()
            for number, (path, temporary, old, new, digest) in enumerate(staged, 1):
                try:
                    check_cancel(cancel)
                    keep = backup and path not in projects and not self.is_clipboard_path(path)
                    if replace:
                        written_digest = replace_original(temporary, path, digest, backup=keep, keep_original=keep_original, cancel=cancel)
                        written.append((path, path, old, new, written_digest))
                        continue
                    target = available_target(folder, path.stem, encoding.format, reserved)
                    reserved.add(target)
                    commit(temporary, target, source=path, backup=keep, cancel=cancel)
                    written.append((path, target, old, new, None))
                except ImageProblem as error:
                    problems[path] = str(error)
                except OSError:
                    problems[path] = tr("書き出しに失敗しました。空き容量とアクセス権を確認してください。")
                report(number, len(staged))
            return written, problems

        def finish(result=None, message=None):
            self.batch_job = None
            shutil.rmtree(staging, ignore_errors=True)
            self.update_controls()
            self.prepare_effect()
            if self.auto.isChecked() and self.document and self.document.dirty:
                self.autosave_timer.start()
            if message:
                self.error(message)
            if result is None:
                return
            written, problems = result
            before, after = sum(item[2] for item in written), sum(item[3] for item in written)
            text = tr("{label}しました · {count}枚 · ").format(label=label, count=len(written)) + size_summary(before, after, tr("圧縮後") if mode == "compress" else tr("変換後"))
            if replace and self.reload_replaced({path: written_digest for path, _, _, _, written_digest in written}):
                # The shown image reloads; report the result once it has.
                self.after_load_message = text + (tr(" / 失敗 {count}枚").format(count=len(problems)) if problems else tr(" · 元画像に上書き"))
            if problems:
                self.error(text + tr(" / 失敗 {count}枚").format(count=len(problems)))
                self.show_failures_text(problems)
            else:
                self.info(text + (tr(" · 元画像に上書き") if replace else f" · {folder}"))

        self.batch_job = self.run_job(work, finish, lambda message: finish(message=message + tr(" 完了した分は書き出し済みです。")),
                                      progress=self.update_batch_progress)
        self.batch_job.signals.cancelled.connect(lambda: finish(message=tr("{label}を中止しました。完了した分は書き出し済みです。").format(label=label)))
        self.update_controls()

    def reload_replaced(self, digests):
        """Images whose files were replaced: drop their cached edits and show them anew."""
        current = self.document.path if self.document else None
        for path, digest in digests.items():
            self.documents.pop(path, None)
            self.owned[path] = digest
            self.model.cache.pop(path, None)
            self.model.state(path, "")
        if current in digests:
            self.document = None
            self._load_index(self.model.rows[current])
            return True
        return False

    def show_failures_text(self, failures):
        self.show_text_window(tr("処理できなかった画像"), "\n\n".join(f"{path}\n{reason}" for path, reason in failures.items()))

    # --- save as -----------------------------------------------------------------------
    def save_as(self):
        """Save the displayed image (with edits, without metadata) under a new name and format."""
        if not self.document or self.busy() or self.saving:
            return
        document = self.document
        filters = {f"{label} (*{extension}{' *.jpeg' if format == 'JPEG' else ''}{' *.tiff' if format == 'TIFF' else ''}{' *.heif' if format == 'HEIF' else ''})": format
                   for format, (label, extension) in TARGETS.items() if writable(format)}
        source_format = document.source_format if document.source_format in filters.values() else "PNG"
        initial = next(text for text, format in filters.items() if format == source_format)
        suggested = document.path.with_name(document.path.stem + "_copy" + TARGETS[source_format][1])
        raw, chosen = QFileDialog.getSaveFileName(self, tr("別名で保存"), str(suggested), ";;".join(filters), initial,
                                                  QFileDialog.Option.DontConfirmOverwrite)
        if not raw:
            return
        target = Path(raw)
        suffixes = {".jpeg": "JPEG", ".tiff": "TIFF", ".heif": "HEIF",
                    **{extension: format for format, (_, extension) in TARGETS.items()}}
        format = suffixes.get(target.suffix.lower())
        if format is None:
            format = filters.get(chosen, "PNG")
            target = target.with_name(target.name + TARGETS[format][1])
        target = target.resolve()
        if not writable(format):
            self.error(tr("この形式では保存できません。PNG / JPEG / WebP などを選んでください。"))
            return
        if target == document.path.resolve() or target.exists():
            self.error(tr("既にあるファイルには保存できません。新しい名前を指定してください（元画像の置き換えは「上書き保存」）。"))
            return
        quality = self.jpeg_quality if format == "JPEG" else SAVE_AS_QUALITY.get(format)
        encoding = Encoding(format, quality=quality, lossless=format == "WEBP")
        pixels = document.image.copy()
        backup = (self.metadata_backup.isChecked() and not getattr(document, "project", False)
                  and not self.is_clipboard_path(document.path))
        source, source_digest = document.path, document.source_digest

        def work(cancel):
            raw = encode(pixels, encoding)
            check_cancel(cancel)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = stage(raw, target.parent)
            try:
                commit(temporary, target, source=source, source_digest=source_digest if backup else None, backup=backup, cancel=cancel)
            finally:
                temporary.unlink(missing_ok=True)
            return target

        self.info(tr("別名で保存中…"))
        self.auxiliary_job(work, lambda path: tr("別名で保存しました · {name} · メタデータ：無し").format(name=path.name))

    # --- in-place 超解像 ---------------------------------------------------------------
    def upscale_image(self):
        if not self.document or self.busy() or self.saving:
            return
        from .output_dialogs import UpscaleDialog
        document = self.document
        dialog = UpscaleDialog(document.image.size, self)
        if not self.confirm_dialog(dialog, accepted=QDialog.DialogCode.Accepted) or document is not self.document:
            return
        try:
            size = dialog.target_size()
        except ImageProblem as error:
            self.error(str(error))
            return
        if self.overwrite.isChecked() and not self.confirm_geometry_overwrite():
            return
        self.apply_image_edit(EditSpec(crop=(0, 0, *document.image.size), size=size))

    def confirm_geometry_overwrite(self):
        confirm = QMessageBox(QMessageBox.Icon.Warning, tr("元画像の寸法・向きを変更"), tr("この編集を保存すると元画像の画素・寸法・向きが置き換わります。"),
                              QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel, self)
        confirm.setInformativeText(tr("作業中は「元に戻す」で戻せます。保存後も、アプリを終了するまでは「⋯ → 上書き前の元画像に戻す」で戻せます。")
                                   if self.keep_originals.isChecked() else
                                   tr("作業中は「元に戻す」で戻せますが、保存すると元の寸法の画像は残りません。元画像を残すには、別フォルダーへ保存してください。"))
        confirm.button(QMessageBox.StandardButton.Ok).setText(tr("編集を適用"))
        confirm.button(QMessageBox.StandardButton.Cancel).setText(tr("キャンセル"))
        confirm.setDefaultButton(QMessageBox.StandardButton.Cancel)
        return self.confirm_dialog(confirm)

    # --- collage -----------------------------------------------------------------------
    def make_collage(self):
        from .collage import MAX_COLLAGE
        paths = self.selected_paths()
        if self.busy() or self.saving:
            return
        if len(paths) < 2:
            self.info(tr("コラージュにする画像を2枚以上選択してください（Ctrl / Shift + クリック）。"))
            return
        if len(paths) > MAX_COLLAGE:
            QMessageBox.warning(self, tr("画像が多すぎます"), tr("コラージュにできるのは{MAX_COLLAGE}枚までです。{MAX_COLLAGE}枚以下にしてください。").format(MAX_COLLAGE=MAX_COLLAGE))
            return
        snapshots = {path: self.documents[path].image.copy() for path in paths if path in self.documents}
        self.finalizing = True
        self.update_controls()

        def work(cancel):
            images = []
            for path in paths:
                check_cancel(cancel)
                images.append(snapshots[path] if path in snapshots else self.review_pixels(path))
            return images

        def done(images):
            self.finalizing = False
            self.update_controls()
            self.finish_collage(paths, images)

        def failed(message):
            self.finalizing = False
            self.error(message)
        self.run_job(work, done, failed)

    def finish_collage(self, paths, images):
        from .export import save_image
        from .output_dialogs import CollageDialog
        dialog = CollageDialog([path.name for path in paths], images, self)
        if not self.confirm_dialog(dialog, accepted=QDialog.DialogCode.Accepted):
            return
        render = dialog.renderer()
        folder = self.default_new_folder_parent(paths)
        suggested = available_target(folder, "collage", "PNG")
        raw, chosen = QFileDialog.getSaveFileName(self, tr("コラージュを保存"), str(suggested),
                                                  "PNG (*.png);;JPEG (*.jpg *.jpeg);;WebP (*.webp)", "",
                                                  QFileDialog.Option.DontConfirmOverwrite)
        if not raw:
            return
        target = Path(raw)
        format = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}.get(target.suffix.lower())
        if format is None:
            format = "JPEG" if chosen.startswith("JPEG") else "WEBP" if chosen.startswith("WebP") else "PNG"
            target = target.with_name(target.name + {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[format])
        target = target.resolve()
        if target.exists():
            self.error(tr("既にあるファイルには保存できません。新しい名前を指定してください。"))
            return
        quality = self.jpeg_quality

        def work(cancel):
            check_cancel(cancel)
            collage = render(cancel)
            check_cancel(cancel)
            return save_image(collage, target, source=paths[0], format=format, jpeg_quality=quality, cancel=cancel).path

        self.info(tr("コラージュを作成中…"))
        self.auxiliary_job(work, lambda path: tr("コラージュを保存しました · {name}（{count}枚） · メタデータ：無し").format(name=path.name, count=len(paths)))

    @staticmethod
    def describe_bytes(size):
        return format_bytes(size)
