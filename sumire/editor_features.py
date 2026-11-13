"""Image-wide operations accessed from menus rather than persistent controls."""
from .i18n import tr
from pathlib import Path
from uuid import uuid4

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog

from .canvas import qimage
from .editing import EditSpec, apply_edit
from .imaging import clean_pixels, ImageProblem, validate_opened, MAX_PIXELS, MAX_DIMENSION
from .stealth import remove_stealth


class EditorFeatures:
    def finish_editor_aux(self):
        self.finalizing = False
        self.update_controls()
        if self.document and not self.canvas.ready:
            self.effect_timer.start()
        if self.auto.isChecked() and self.document and self.document.dirty:
            self.autosave_timer.start()

    def create_editor_actions(self):
        self.editor_actions = {}
        for name, title, callback in (
                ("edit", tr("画像を切り抜く…"), lambda: self.edit_image("crop")),
                ("color", tr("色調の調整…"), lambda: self.edit_image("color")),
                ("metadata", tr("メタデータの内容を確認…"), self.inspect_source_metadata),
                ("copy", tr("編集結果を画像としてコピー"), self.copy_image),
                ("paste", tr("クリップボードの画像を開く"), self.paste_image),
                ("upscale", tr("超解像を適用…"), self.upscale_image),
                ("quality", tr("JPEGの保存品質…"), self.choose_jpeg_quality),
                ("fullscreen", tr("全画面表示"), self.toggle_fullscreen)):
            self.editor_actions[name] = self._action(title, callback)
        self.inverse_action = self._action(tr("選択範囲を反転（外側に適用）"), checkable=True,
                                           tooltip=tr("次に指定する長方形・楕円・多角形・投げ縄の外側に適用します。ブラシには適用しません。"))
        self.inverse_action.toggled.connect(self.selection_direction_changed)
        self.navigator_action = self._action(tr("ナビゲーター"), checkable=True)
        self.navigator_action.toggled.connect(lambda checked: self.canvas.navigator.setVisible(checked))

    def selection_direction_changed(self, checked):
        self.canvas.invert_selection = checked
        titles = {"rectangle": tr("長方形"), "ellipse": tr("楕円"), "polygon": tr("多角形"), "lasso": tr("投げ縄")}
        for index in range(self.shape_combo.count()):
            title = titles.get(self.shape_combo.itemData(index))
            if title:
                self.shape_combo.setItemText(index, (tr("外側：") if checked else "") + title)
        self.tool_changed()

    def toggle_fullscreen(self):
        host = self.workspace_host or self
        host.showNormal() if host.isFullScreen() else host.showFullScreen()

    def choose_jpeg_quality(self):
        if self.busy() or self.saving:
            return
        dialog = QInputDialog(self)
        dialog.setWindowTitle(tr("JPEGの保存品質"))
        dialog.setLabelText(tr("品質（1〜100、次のJPEG保存から適用）"))
        dialog.setInputMode(QInputDialog.InputMode.IntInput)
        dialog.setIntRange(1, 100)
        dialog.setIntValue(self.jpeg_quality)
        dialog.setOkButtonText(tr("適用"))
        dialog.setCancelButtonText(tr("キャンセル"))
        if self.confirm_dialog(dialog, accepted=QDialog.DialogCode.Accepted):
            self.jpeg_quality = dialog.intValue()
            self.format_combo.setItemText(1, tr("JPEG · 品質{jpeg_quality}・白背景").format(jpeg_quality=self.jpeg_quality))
            self.export_settings_changed()

    def edit_image(self, mode="crop"):
        if not self.document or self.busy() or self.saving:
            return
        from .editor_dialogs import ImageEditDialog
        document = self.document
        dialog = ImageEditDialog(document.image, self, mode)
        # Keep the dialog alive until its edit specification has been read.
        accepted = self.confirm_dialog(dialog, accepted=QDialog.DialogCode.Accepted)
        if not accepted:
            return
        spec = dialog.spec()
        changes_geometry = spec.crop != (0, 0, *document.image.size) or spec.size is not None or spec.rotation or spec.horizontal or spec.vertical
        if self.overwrite.isChecked() and changes_geometry and not self.confirm_geometry_overwrite():
            return
        self.apply_image_edit(spec)

    def transform_image(self, rotation=0, horizontal=False, vertical=False):
        """Rotate or flip at once. Lossless and reversible, so no overwrite confirmation."""
        if not self.document or self.busy() or self.saving:
            return
        self.apply_image_edit(EditSpec(crop=(0, 0, *self.document.image.size), rotation=rotation,
                                       horizontal=horizontal, vertical=vertical))

    def apply_image_edit(self, spec):
        if not self.document or self.busy() or self.saving:
            return
        self.autosave_timer.stop()
        self.finalizing = True
        self.canvas.ready = False
        self.update_controls()
        document = self.document
        def done(changed):
            self.finalizing = False
            self.canvas.refresh()
            if changed or document.dirty:
                self.after_edit()
            else:
                self.prepare_effect()
                self.update_controls()
        def failed(message):
            self.finish_editor_aux()
            self.error(message)
            self.prepare_effect()
        self.run_job(lambda cancel: apply_edit(document, spec), done, failed)

    def picked_color(self, color):
        self.color = color
        self.update_color_button()
        self.tool_changed()
        self.info(tr("色を取得しました · {upper}").format(upper=color.upper()))

    def metadata_file(self):
        """The file the current image is kept in: its saved output, or the source until then."""
        document = self.document
        if document is None:
            return None
        if document.output and document.saved_revision == document.revision and document.output.is_file():
            return document.output
        return document.path

    def inspect_source_metadata(self):
        if not self.document or self.busy() or self.saving:
            return
        if getattr(self.document, "project", False) or self.is_clipboard_path(self.document.path):
            self.text_dialog(tr("メタデータの内容"), tr("編集中の画像はメタデータを持ちません。元の画像ファイルを開くと、内容を確認できます。"))
            return
        from .metadata import describe_metadata
        source = self.metadata_file()
        self.autosave_timer.stop()
        self.finalizing = True
        self.update_controls()
        def done(entries):
            from .editor_dialogs import MetadataDialog
            self.finish_editor_aux()
            where = tr("保存した画像") if source != self.document.path else tr("画像")
            MetadataDialog(tr("{where}：{source}").format(where=where, source=source), entries,
                           tr("対応している形式の検査結果です。意味の分からない情報は「不明」として載せています。"
                           "未知の方法で埋め込まれた情報は表示できません。"), self).exec()
        def failed(message):
            self.finish_editor_aux()
            self.error(message)
        self.run_job(lambda cancel: describe_metadata(source), done, failed)

    def copy_image(self):
        if not self.document or self.busy() or self.saving:
            return
        pixels = self.document.image.copy()
        self.autosave_timer.stop()
        self.finalizing = True
        self.update_controls()
        def done(image):
            self.finish_editor_aux()
            QApplication.clipboard().setImage(qimage(image))
            self.info(tr("編集結果をコピーしました · メタデータ：無し"))
            self.update_controls()
        def failed(message):
            self.finish_editor_aux()
            self.error(message)
        self.run_job(lambda cancel: clean_pixels(remove_stealth(pixels)), done, failed)

    def is_clipboard_path(self, path):
        return path.parent.resolve() == (self.preferences.path.parent / "clipboard-images").resolve()

    def paste_image(self):
        if self.busy() or self.saving:
            return
        image = QApplication.clipboard().image()
        if image.isNull():
            self.info(tr("クリップボードに画像がありません。"))
            return
        if image.width() * image.height() > MAX_PIXELS or max(image.width(), image.height()) > MAX_DIMENSION:
            self.error(tr("画像が大きすぎます。上限は2,400万画素・1辺32,768pxです。"))
            return
        image = image.copy()
        # A private, persistent source makes tab restoration possible; it is not
        # the user's output. The first save always asks for an output filename.
        path = self.preferences.path.parent / "clipboard-images" / f"clipboard-{uuid4().hex}.png"
        self.autosave_timer.stop()
        self.finalizing = True
        self.update_controls()
        def work(cancel):
            import io
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            if not image.save(buffer, "PNG"):
                raise ImageProblem(tr("クリップボードの画像を読み込めません。"))
            with Image.open(io.BytesIO(bytes(buffer.data()))) as opened:
                validate_opened(opened)
                pixels = clean_pixels(remove_stealth(opened))
            path.parent.mkdir(parents=True, exist_ok=True)
            pixels.save(path, format="PNG")
            return path
        def done(source):
            self.finish_editor_aux()
            page = self.workspace_host.new_tab() if self.workspace_host else self
            page.auto.setChecked(False)
            page.overwrite.setChecked(False)
            page.load_inputs([str(source)])
        def failed(message):
            self.finish_editor_aux()
            self.error(message)
        self.run_job(work, done, failed)

    def clipboard_target(self, document):
        if document.output:
            return document.output
        raw, _ = QFileDialog.getSaveFileName(self, tr("クリップボードの画像を保存"), "clipboard.png", tr("画像 (*.png *.jpg *.jpeg *.webp)"))
        if not raw:
            return None
        target = Path(raw).resolve()
        if not target.suffix:
            target = target.with_suffix(".png")
        if target.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} or target.exists() or self.is_clipboard_path(target):
            raise ImageProblem(tr("画像の保存先には、新しいPNG / JPEG / WebPのファイル名を指定してください。"))
        return target
