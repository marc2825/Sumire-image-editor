"""Folders inside a tab: browse nested folders, create one, and move images into it.

The tab stays based on the folder it opened (its "root"). The list shows the
images of the folder currently being browsed; the strip above it shows where
that is, its subfolders, and lets images be dropped onto a folder to move them.
"""
from __future__ import annotations
from .i18n import tr

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QDialog, QHBoxLayout, QInputDialog, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from .export import Cancelled, check_cancel
from .folders import create_folder, folder_images, label_folders, move_image, move_images, subfolders
from .icons import icon
from .imaging import ImageProblem
from .library import LibraryView
from .ui import ElidedLabel, tool_button
from .archive_features import writes_files

FOLDER_ROLE = Qt.ItemDataRole.UserRole


class FolderList(QListWidget):
    """Subfolders (and the parent) of the browsed folder; images can be dropped on a row."""

    folderOpened = Signal(str)
    imagesDropped = Signal(list, str)

    def __init__(self):
        super().__init__()
        self.setObjectName("folderList")
        self.setAccessibleName(tr("フォルダー"))
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.itemClicked.connect(lambda item: self.folderOpened.emit(item.data(FOLDER_ROLE)))
        self.itemActivated.connect(lambda item: self.folderOpened.emit(item.data(FOLDER_ROLE)))

    def _target(self, event):
        if not event.mimeData().hasFormat(LibraryView.MIME):
            return None
        return self.itemAt(event.position().toPoint())

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(LibraryView.MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        item = self._target(event)
        if item is not None:
            self.setCurrentItem(item)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.clearSelection()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        item = self._target(event)
        self.clearSelection()
        if item is None:
            event.ignore()
            return
        paths = json.loads(bytes(event.mimeData().data(LibraryView.MIME)))
        event.acceptProposedAction()
        self.imagesDropped.emit(paths, item.data(FOLDER_ROLE))


class FolderFeatures:
    def init_folders(self):
        self.folder_root: Path | None = None
        # Set just before loading a folder browsed inside the tab (or reloaded / restored),
        # so that only those loads keep the root. Opening a folder from 「ファイル」 starts a new root.
        self.browse_target: Path | None = None

    def build_folder_bar(self, layout):
        self.folder_bar = QWidget()
        column = QVBoxLayout(self.folder_bar)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.folder_up_button = tool_button("folder_up", tr("上のフォルダーへ"),
                                            lambda: self.open_archive_parent() if self.archive is not None else self.open_parent_folder())
        row.addWidget(self.folder_up_button)
        self.folder_path_label = ElidedLabel("", Qt.TextElideMode.ElideLeft)
        self.folder_path_label.setObjectName("muted")
        row.addWidget(self.folder_path_label, 1)
        self.reload_folder_button = tool_button("reload", tr("フォルダーを再読み込み · Ctrl+R"), lambda: self.reload_action.trigger())
        self.reload_folder_button.setAccessibleName(tr("フォルダーを再読み込み"))
        row.addWidget(self.reload_folder_button)
        self.new_folder_button = tool_button("folder_plus", tr("新しいフォルダーを作る"), self.create_subfolder)
        row.addWidget(self.new_folder_button)
        column.addLayout(row)
        self.folder_list = FolderList()
        self.folder_list.folderOpened.connect(self.folder_row_opened)
        self.folder_list.imagesDropped.connect(lambda raws, folder: self.move_to_folder([Path(raw) for raw in raws], Path(folder)))
        column.addWidget(self.folder_list)
        self.folder_bar.hide()
        layout.addWidget(self.folder_bar)

    def browsed_folder(self):
        """The folder shown in this tab, when the tab shows exactly one folder."""
        if len(self.workspace_inputs) == 1:
            folder = Path(self.workspace_inputs[0])
            if folder.is_dir():
                return folder.resolve()
        return None

    def settle_folder_root(self, inputs):
        """Keep the root while browsing inside it; any other opened folder becomes the new root."""
        current = Path(inputs[0]).resolve() if len(inputs) == 1 and Path(inputs[0]).is_dir() else None
        browsing, self.browse_target = self.browse_target == current, None
        if current is None:
            self.folder_root = None
            return False
        if browsing and self.folder_root is not None and current.is_relative_to(self.folder_root):
            return True
        self.folder_root = current
        return False

    def folder_location(self, tab_name=False):
        """「root / sub / sub」 for the browsed folder; ``tab_name`` puts the tab's own name first."""
        current, root = self.browsed_folder(), self.folder_root
        if current is None or root is None or not current.is_relative_to(root):
            return ""
        first = (self.custom_title if tab_name and self.custom_title else None) or root.name or str(root)
        return " / ".join([first, *current.relative_to(root).parts])

    def refresh_folders(self):
        current = self.browsed_folder()
        archive = self.archive is not None
        visible = archive or (current is not None and self.folder_root is not None)
        self.folder_bar.setVisible(visible)
        self.folder_list.clear()
        if not visible:
            return
        if archive:
            # Inside a ZIP: its folders, the ZIP's name first; marked read only.
            self.folder_path_label.setText(self.archive_location() + tr(" · 読み取り専用"))
            self.folder_path_label.setToolTip(tr("{zip}\nZIPの中の画像は変更しません（読み取り専用）。").format(zip=self.archive.path))
            self.folder_up_button.setEnabled(bool(self.archive_folder))
            rows = self.archive_folder_rows()
        else:
            self.folder_path_label.setText(self.folder_location())
            self.folder_path_label.setToolTip(str(current))
            at_root = current == self.folder_root
            self.folder_up_button.setEnabled(not at_root)
            rows = []
            if not at_root:
                rows.append((current.parent, tr("..（上のフォルダー）"), "folder_up"))
            rows.extend((folder, folder.name, "folder") for folder in subfolders(current))
        for folder, text, glyph in rows:
            item = QListWidgetItem(icon(glyph, "text_muted"), text)
            item.setData(FOLDER_ROLE, str(folder))
            item.setToolTip(tr("クリックで開く") if archive else tr("{folder}\nクリックで開く · 画像をドロップすると移動").format(folder=folder))
            self.folder_list.addItem(item)
        row_height = max(24, self.folder_list.sizeHintForRow(0)) if rows else 0
        self.folder_list.setFixedHeight(min(len(rows), 4) * row_height + 4 if rows else 0)
        self.folder_list.setVisible(bool(rows))
        if self.workspace_host is not None:
            self.workspace_host.update_tab(self)

    def update_folder_controls(self, idle):
        if not hasattr(self, "folder_bar"):
            return
        for widget in (self.folder_list, self.new_folder_button):
            widget.setEnabled(idle)
        self.reload_folder_button.setEnabled(idle and bool(self.workspace_inputs))
        if self.archive is not None:
            self.folder_up_button.setEnabled(idle and bool(self.archive_folder))
            self.new_folder_button.setEnabled(False)
            return
        current = self.browsed_folder()
        self.folder_up_button.setEnabled(idle and current is not None and current != self.folder_root)

    def open_folder_in_tab(self, folder):
        folder = Path(folder).resolve()
        if self.busy() or self.saving or not folder.is_dir() or self.folder_root is None or not folder.is_relative_to(self.folder_root):
            return
        if folder != self.browsed_folder():
            self.browse_target = folder
            self.load_inputs([str(folder)])

    def open_parent_folder(self):
        current = self.browsed_folder()
        if current is not None and self.folder_root is not None and current != self.folder_root:
            self.open_folder_in_tab(current.parent)

    @writes_files
    def create_subfolder(self, move_paths=None):
        current = self.browsed_folder()
        if current is None or self.busy() or self.saving:
            return None
        dialog = QInputDialog(self)
        dialog.setWindowTitle(tr("新しいフォルダー"))
        dialog.setLabelText(tr("「{name}」の中に作るフォルダーの名前").format(name=current.name))
        dialog.setTextValue(tr("新しいフォルダー"))
        dialog.setOkButtonText(tr("作成して移動") if move_paths else tr("作成"))
        dialog.setCancelButtonText(tr("キャンセル"))
        if not self.confirm_dialog(dialog, accepted=QInputDialog.DialogCode.Accepted):
            return None
        try:
            folder = create_folder(current, dialog.textValue())
        except ImageProblem as error:
            self.error(str(error))
            return None
        self.refresh_folders()
        if move_paths:
            self.move_to_folder(move_paths, folder)
        else:
            self.info(tr("フォルダーを作成しました · {name}").format(name=folder.name))
        return folder

    def populate_move_menu(self, menu, paths):
        """「フォルダーへ移動」: the parent, the subfolders and a new folder."""
        current = self.browsed_folder()
        if current is None or self.folder_root is None:
            return
        target = menu.addMenu(tr("フォルダーへ移動"))
        target.setIcon(icon("folder"))
        if current != self.folder_root:
            target.addAction(icon("folder_up"), tr("上のフォルダー（{name}）").format(name=current.parent.name), lambda: self.move_to_folder(paths, current.parent))
        for folder in subfolders(current):
            target.addAction(icon("folder"), folder.name, lambda value=folder: self.move_to_folder(paths, value))
        target.addSeparator()
        target.addAction(icon("folder_plus"), tr("新しいフォルダーを作って移動…"), lambda: self.create_subfolder(move_paths=paths))
        target.setEnabled(bool(paths) and not self.busy() and not self.saving)

    def move_to_folder(self, paths, folder):
        folder = Path(folder).resolve()
        self.move_to_folders({path: folder for path in paths})

    @writes_files
    def move_to_folders(self, targets, create=False):
        """Move each image into its folder ({path: folder}); ``create`` makes missing folders."""
        if self.busy() or self.saving:
            return
        targets = {path: Path(folder) for path, folder in targets.items() if path in self.model.rows and path.parent != Path(folder)}
        if not targets:
            return
        current = self.document.path if self.document else None
        unsaved = [path for path in targets if path in self.documents and self.documents[path].dirty and path != current]
        if unsaved:
            self.error(tr("未保存の編集がある画像は移動できません。保存してから移動してください。"))
            return
        action = lambda: self._move_to_folders(targets, create)
        if current in targets and self.document.dirty:
            self.guard(action)
        else:
            action()

    def _move_to_folders(self, targets, create):
        if self.busy() or self.saving:
            return
        targets = {path: folder for path, folder in targets.items() if path in self.model.rows}
        folders = list(dict.fromkeys(targets.values()))
        name = folders[0].name if len(folders) == 1 else None
        self.autosave_timer.stop()
        self.finalizing = True
        self.update_controls()
        self.info(tr("「{name}」へ移動中…").format(name=name) if name else tr("フォルダーへ移動中…"))

        def work(cancel):
            moved, failed = {}, {}
            for folder in folders:
                group = [path for path, target in targets.items() if target == folder]
                if create:
                    try:
                        if folder.is_symlink():
                            raise OSError()
                        folder.mkdir(exist_ok=True)
                    except OSError:
                        failed.update(dict.fromkeys(group, tr("移動先のフォルダーを作れません。場所とアクセス権を確認してください。")))
                        continue
                done_here, failed_here = move_images(group, folder, cancel=cancel)
                moved.update(done_here)
                failed.update(failed_here)
            return moved, failed

        def done(result):
            self.finalizing = False
            moved, failed = result
            if moved:
                self.exclude_from_list(list(moved), message=False)
                self.excluded_paths.difference_update(moved)
                self.operation_history.append(("move", {new: old for old, new in moved.items()}))
            self.refresh_folders()
            self.update_controls()
            key = self.shortcut_hint("undo_organize")
            text = (tr("「{name}」へ移動しました · {count}枚").format(name=name, count=len(moved)) if name else
                    tr("フォルダーへ移動しました · {count}枚").format(count=len(moved)))
            text += tr("（{key}で戻せます）").format(key=key) if moved and key else ""
            if failed:
                self.error(text + tr(" / 移動できなかった画像 {count}枚").format(count=len(failed)))
                self.show_text_window(tr("移動できなかった画像"), "\n\n".join(f"{path}\n{reason}" for path, reason in failed.items()))
            else:
                self.report(text)

        def fail(message):
            self.finalizing = False
            self.refresh_folders()
            self.update_controls()
            self.error(message)

        self.run_job(work, done, fail)

    @writes_files
    def move_labelled(self, groups, destinations, names=None):
        """Move each label's images ({label: [path]}) into its folder ({label: folder}), as they are.

        ``names`` maps a path to a new file stem. Records (labels, notes…) move with the
        files, and 「直前の整理操作を戻す」 brings them back.
        """
        paths = [path for label_paths in groups.values() for path in label_paths]
        current = self.document.path if self.document else None
        unsaved = [path for path in paths if path in self.documents and self.documents[path].dirty and path != current]
        if unsaved:
            self.error(tr("未保存の編集がある画像は移動できません。保存してから移動してください。"))
            return
        action = lambda: self._move_labelled(groups, destinations, names)
        if current in paths and self.document.dirty:
            self.guard(action)
        else:
            action()

    def _move_labelled(self, groups, destinations, names):
        if self.busy() or self.saving:
            return
        groups = {label: [path for path in paths if path in self.model.rows] for label, paths in groups.items()}
        self.autosave_timer.stop()
        self.finalizing = True
        self.update_controls()
        self.info(tr("ラベルごとに移動中…"))

        def work(cancel):
            moved, failed, counts = {}, {}, {}
            for label, paths in groups.items():
                folder = destinations[label]
                try:
                    folder.mkdir(parents=True, exist_ok=True)
                except OSError:
                    failed.update({path: tr("移動先のフォルダーを作れません。場所とアクセス権を確認してください。") for path in paths})
                    continue
                reserved = set()
                for path in paths:
                    try:
                        check_cancel(cancel)
                    except Cancelled:
                        return moved, failed, counts
                    try:
                        name = names[path] + path.suffix if names and path in names else None
                        target = move_image(path, folder, name=name, reserved=frozenset(reserved), cancel=cancel)
                        reserved.add(target)
                        moved[path] = target
                        counts[label] = counts.get(label, 0) + 1
                    except Cancelled:
                        return moved, failed, counts
                    except ImageProblem as error:
                        failed[path] = str(error)
                    except OSError:
                        failed[path] = tr("画像を移動できません。アクセス権と、ほかのアプリで開いていないかを確認してください。")
            return moved, failed, counts

        def done(result):
            from .labels import REVIEW_LABELS
            self.finalizing = False
            moved, failed, counts = result
            if moved:
                self.exclude_from_list(list(moved), message=False)
                self.excluded_paths.difference_update(moved)
                self.operation_history.append(("move", {new: old for old, new in moved.items()}))
            self.refresh_folders()
            self.update_controls()
            key = self.shortcut_hint("undo_organize")
            summary = " · ".join(tr("{text} {count}枚").format(text=text, count=counts[label]) for label, text in REVIEW_LABELS.items() if counts.get(label))
            text = tr("ラベルごとに移動しました · {summary}").format(summary=summary or "0") + (tr("（{key}で戻せます）").format(key=key) if moved and key else "")
            if failed:
                self.error(text + tr(" / 移動できなかった画像 {count}枚").format(count=len(failed)))
                self.show_text_window(tr("移動できなかった画像"), "\n\n".join(f"{path}\n{reason}" for path, reason in failed.items()))
            else:
                self.report(text)

        def fail(message):
            self.finalizing = False
            self.refresh_folders()
            self.update_controls()
            self.error(message)

        self.run_job(work, done, fail)

    def paste_folder(self):
        """Where pasted files go: the folder shown in the tab, or the shown image's folder."""
        folder = self.browsed_folder()
        if folder is None and self.document is not None and not self.is_clipboard_path(self.document.path):
            folder = self.document.path.parent
        return folder

    @writes_files
    def clip_files(self, cut=False):
        """Ctrl+C / Ctrl+X in the list: the selected image files (or the shown one) on the clipboard."""
        from PySide6.QtWidgets import QApplication
        from .file_clipboard import file_mime
        paths = [path for path in self.selected_or_current() if not self.is_clipboard_path(path)]
        if not paths or self.busy():
            return
        QApplication.clipboard().setMimeData(file_mime(paths, cut))
        self.info((tr("切り取りました · {count}枚（貼り付けると移動します）") if cut else tr("ファイルをコピーしました · {count}枚")).format(count=len(paths)))

    def paste_files(self):
        """Ctrl+V with files on the clipboard: copy them (or move them, if cut) into the tab's folder.

        Returns False when the clipboard has no image files (the caller then pastes a picture).
        """
        from PySide6.QtWidgets import QApplication
        from .file_clipboard import clipboard_files, copy_files
        paths, cut = clipboard_files(QApplication.clipboard().mimeData())
        if not paths:
            return False
        if self.archive is not None:
            self.info(tr("ZIPの中には貼り付けられません（読み取り専用）。"))
            return True
        if self.busy() or self.saving:
            return True
        folder = self.paste_folder()
        if folder is None:
            self.error(tr("貼り付け先のフォルダーがありません。フォルダーを開いてから貼り付けてください。"))
            return True
        if cut:
            sources = [path for path in paths if path.resolve().parent != folder.resolve()]
            if not sources:
                self.info(tr("同じフォルダーには移動できません。"))
                return True
            unsaved = [path for path in sources if path in self.documents and self.documents[path].dirty]
            if unsaved:
                self.error(tr("未保存の編集がある画像は移動できません。保存してから移動してください。"))
                return True
        self.autosave_timer.stop()
        self.finalizing = True
        self.update_controls()
        self.info(tr("貼り付け中…"))

        def work(cancel):
            if not cut:
                return copy_files(paths, folder, cancel)
            moved, failed = move_images(sources, folder, cancel=cancel)
            return moved, failed

        def done(result):
            self.finalizing = False
            changed, failed = result
            here = [path for path in changed.values() if path.parent == folder and path not in self.model.rows]
            if cut and changed:
                gone = [path for path in changed if path in self.model.rows]
                if gone:
                    self.exclude_from_list(gone, message=False)
                    self.excluded_paths.difference_update(gone)
                self.operation_history.append(("move", {new: old for old, new in changed.items()}))
                QApplication.clipboard().clear()  # cut files paste once, as in Explorer
            if here and self.browsed_folder() == folder:
                self.replace_list(list(self.model.paths) + here)
                self.refresh_record_indexes()
                if not self.document:
                    self.ensure_visible_current(here[0])
            self.refresh_folders()
            self.update_controls()
            key = self.shortcut_hint("undo_organize")
            text = (tr("移動しました · {count}枚").format(count=len(changed)) + (tr("（{key}で戻せます）").format(key=key) if key and changed else "")
                    if cut else tr("貼り付けました · {count}枚").format(count=len(changed)))
            if failed:
                self.error(text + tr(" / 貼り付けられなかった画像 {count}枚").format(count=len(failed)))
            else:
                self.report(text)

        def fail(message):
            self.finalizing = False
            self.update_controls()
            self.error(message)

        self.run_job(work, done, fail)
        return True

    def merge_target(self):
        """(the folder holding the label folders, those folders) for this tab, or None."""
        folder = self.browsed_folder()
        if folder is None:
            return None
        root, found = label_folders(folder)
        return (root, found) if found else None

    @writes_files
    def merge_label_folders(self):
        """Gather the images of the label folders (採用・保留・不採用) into one folder."""
        from .output_dialogs import MergeLabelFoldersDialog
        target = self.merge_target() if not self.busy() and not self.saving else None
        if target is None:
            self.info(tr("このタブのフォルダーには、採用・保留・不採用のフォルダーがありません。"))
            return
        root, found = target
        counts = {folder: len(folder_images(folder)) for folder in found}
        counts = {folder: count for folder, count in counts.items() if count}
        if not counts:
            self.info(tr("ラベルのフォルダーに画像がありません。"))
            return
        dialog = MergeLabelFoldersDialog(root, counts, self)
        if not self.confirm_dialog(dialog, accepted=QDialog.DialogCode.Accepted) or self.busy() or self.saving:
            return
        destination, remove_empty = dialog.destination(), dialog.remove_empty.isChecked()
        current = self.document.path if self.document else None
        if current is not None and current.parent in counts and self.document.dirty:
            self.guard(lambda: self._merge_label_folders(list(counts), destination, remove_empty))
        else:
            self._merge_label_folders(list(counts), destination, remove_empty)

    def _merge_label_folders(self, folders, destination, remove_empty):
        if self.busy() or self.saving:
            return
        unsaved = [path for path, document in self.documents.items() if document.dirty and path.parent in folders]
        if unsaved:
            self.error(tr("未保存の編集がある画像は移動できません。保存してから移動してください。"))
            return
        self.autosave_timer.stop()
        self.finalizing = True
        self.update_controls()
        self.info(tr("ラベルのフォルダーをまとめています…"))
        browsed = self.browsed_folder()

        def work(cancel):
            moved, failed, kept = {}, {}, []
            try:
                if destination.is_symlink():
                    raise OSError()
                destination.mkdir(exist_ok=True)
            except OSError:
                return moved, {folder: tr("まとめ先のフォルダーを作れません。場所とアクセス権を確認してください。") for folder in folders}, kept
            for folder in folders:
                if folder == destination:
                    continue
                done_here, failed_here = move_images(folder_images(folder), destination, cancel=cancel)
                moved.update(done_here)
                failed.update(failed_here)
                if remove_empty:
                    from .storage import remove_empty_records
                    try:
                        remove_empty_records(folder)  # Sumīre's own records, once nothing is recorded in them
                        folder.rmdir()  # only when nothing at all is left in it
                    except OSError:
                        kept.append(folder)
            return moved, failed, kept

        def done(result):
            self.finalizing = False
            moved, failed, kept = result
            if moved:
                self.operation_history.append(("move", {new: old for old, new in moved.items()}))
            gone = [path for path in moved if path in self.model.rows]
            if gone:
                self.exclude_from_list(gone, message=False)
                self.excluded_paths.difference_update(gone)
            if browsed is not None and (browsed in folders or browsed == destination) and destination.is_dir():
                # Show where the images are now.
                if browsed == destination:
                    self.replace_list(list(self.model.paths) + [path for path in moved.values() if path not in self.model.rows])
                    self.refresh_record_indexes()
                else:
                    self.open_folder_in_tab(destination) if self.folder_root is not None and destination.is_relative_to(self.folder_root) \
                        else self.load_inputs([str(destination)])
            self.refresh_folders()
            self.update_controls()
            key = self.shortcut_hint("undo_organize")
            text = tr("「{name}」にまとめました · {count}枚").format(name=destination.name or str(destination), count=len(moved))
            text += tr("（{key}で戻せます）").format(key=key) if moved and key else ""
            if remove_empty and kept:
                text += tr(" · ほかのファイルが残ったフォルダーは削除していません")
            if failed:
                self.error(text + tr(" / 移動できなかった画像 {count}枚").format(count=len(failed)))
                self.show_text_window(tr("移動できなかった画像"), "\n\n".join(f"{path}\n{reason}" for path, reason in failed.items()))
            else:
                self.report(text)

        def fail(message):
            self.finalizing = False
            self.refresh_folders()
            self.update_controls()
            self.error(message)

        self.run_job(work, done, fail)

    def undo_move(self, mapping):
        """Move images back to where they were ({moved: original}); returns True when all came back."""
        returned, problems = [], []
        for moved, original in mapping.items():
            try:
                if not original.parent.exists():
                    original.parent.mkdir()  # a label folder removed when its images were gathered
                returned.append(move_image(moved, original.parent, name=original.name))
            except (ImageProblem, OSError):
                problems.append(moved)
        current = self.browsed_folder()
        here = [path for path in returned if path.parent == current and path not in self.model.rows]
        if here:
            self.replace_list(list(self.model.paths) + here)
            self.refresh_record_indexes()
        self.refresh_folders()
        if problems:
            self.error(tr("元のフォルダーへ戻せなかった画像があります · {count}枚").format(count=len(problems)))
        else:
            self.info(tr("移動を取り消しました · {count}枚").format(count=len(returned)))
        return not problems
