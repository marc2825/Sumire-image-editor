"""Application window with independent, explicitly opened workspaces."""
from .i18n import tr
from .archive import is_archive
from .labels import quick_tags
from collections import OrderedDict, deque
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QTimer, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QHBoxLayout, QInputDialog, QMainWindow, QMenu, QMessageBox, QStackedWidget, QTabWidget, QWidget,
)

from .preferences import Preferences
from .projects import PROJECT_EXTENSIONS
from .backups import store as originals
from .ui import tool_button
from .window import Window
from .shortcuts import HOST_COMMANDS, hint, load_bindings


# The quit confirmation; tests turn it off where closing is not what they check.
QUIT_CONFIRMATION = {"enabled": True}


class WorkspaceTabs(QTabWidget):
    """Tabs in one row with the app-wide controls: Sumīre and the file menu before
    them, the save method, help and settings after them. The new-tab button stays
    beside the last tab, or at the edge on overflow."""
    def __init__(self, new_tab):
        super().__init__()
        self.tabBar().setExpanding(False)
        self.add_button = tool_button("plus", tr("新しいタブ"), new_tab)
        self.leading = QWidget()
        self.leading_row = QHBoxLayout(self.leading)
        self.leading_row.setContentsMargins(14, 0, 10, 0)
        self.leading_row.setSpacing(6)
        self.setCornerWidget(self.leading, Qt.Corner.TopLeftCorner)
        # Reserve room for the new-tab button on overflow, but position the button
        # independently: QTabWidget moves its actual corner widgets again while painting.
        right = QWidget()
        right_row = QHBoxLayout(right)
        right_row.setContentsMargins(0, 0, 10, 0)
        right_row.setSpacing(6)
        self.corner_space = QWidget()
        right_row.addWidget(self.corner_space)
        self.trailing = QWidget()
        self.trailing_row = QHBoxLayout(self.trailing)
        self.trailing_row.setContentsMargins(0, 0, 0, 0)
        right_row.addWidget(self.trailing)
        self.setCornerWidget(right, Qt.Corner.TopRightCorner)
        self.add_button.setParent(self)
        self.add_button.show()
        self.position_timer = QTimer(self)
        self.position_timer.setSingleShot(True)
        self.position_timer.timeout.connect(self.position_add_button)
        self.tabBar().installEventFilter(self)
        self.tabBar().tabMoved.connect(self.schedule_position)
        self.currentChanged.connect(self.schedule_position)

    def schedule_position(self, *_):
        self.position_timer.start(0)

    def position_add_button(self):
        bar, button = self.tabBar(), self.add_button
        size = button.sizeHint()
        if self.corner_space.size() != size:
            self.corner_space.setFixedSize(size)
        button.resize(size)
        end = bar.tabRect(self.count() - 1).right() + 1 if self.count() else 0
        inline_x = bar.x() + end + 4
        space_x = self.corner_space.mapTo(self, QPoint(0, 0)).x()
        fits = (bar.sizeHint().width() <= bar.width() and
                inline_x + button.width() <= space_x + self.corner_space.width())
        x = inline_x if fits else space_x
        button.move(x, bar.y() + max(0, (bar.height() - button.height()) // 2))
        button.raise_()

    def eventFilter(self, watched, event):
        if event.type() in {QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.LayoutRequest,
                            QEvent.Type.Show, QEvent.Type.StyleChange, QEvent.Type.FontChange}:
            self.schedule_position()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.schedule_position()

    def tabInserted(self, index):
        super().tabInserted(index)
        if hasattr(self, "position_timer"):
            self.schedule_position()

    def tabRemoved(self, index):
        super().tabRemoved(index)
        self.schedule_position()


class WorkspaceWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.preferences = Preferences()
        # A profile without any saved data is a new installation (not an upgrade).
        self.first_run = not self.preferences.data
        self.pending_inputs = deque()
        self.close_mode = None
        self.close_order = []
        self.shutdown_ready = False
        self.session_started = False
        self.restoring_session = False
        self.closing_session = None
        self.app_controls_owner = None
        self.quit_confirmed = False
        self.memory_limit = 512 * 1024 * 1024
        self.trimming_memory = False
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.welcome = self._workspace(persist=False)
        self.welcome.top_bar.show()  # the start page is shown on its own, with its own bar
        self.stack.addWidget(self.welcome)
        self.tabs = WorkspaceTabs(self.new_tab)
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setAccessibleName(tr("作業タブ"))
        self.tabs.tabCloseRequested.connect(lambda index: self.close_tab(self.tabs.widget(index)))
        self.tabs.currentChanged.connect(self.tab_changed)
        self.tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self.tab_menu)
        self.tabs.tabBarDoubleClicked.connect(lambda index: self.rename_tab(self.tabs.widget(index)) if index >= 0 else None)
        self.stack.addWidget(self.tabs)
        self.resize(self.welcome.size())
        self.setMinimumSize(800, 474)
        self.move(self.welcome.pos())
        self.setStyleSheet(self.welcome.styleSheet())
        self.setWindowTitle(tr("Sumīre — 画像の仕上げ"))
        self.request_timer = QTimer(self)
        self.request_timer.setInterval(150)
        self.request_timer.timeout.connect(self.process_external)
        self.apply_shortcuts()

    def apply_shortcuts(self):
        for shortcut in getattr(self, "shortcuts", []):
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self.shortcuts = []
        bindings = load_bindings(self.preferences)
        callbacks = {"new_tab": self.new_tab, "close_tab": self.close_current_tab,
                     "next_tab": lambda: self.cycle_tab(1), "previous_tab": lambda: self.cycle_tab(-1)}
        for name in HOST_COMMANDS:
            for key in bindings[name]:
                shortcut = QShortcut(QKeySequence(key), self)
                shortcut.setAutoRepeat(False)
                shortcut.activated.connect(callbacks[name])
                self.shortcuts.append(shortcut)
        key = hint(bindings, "new_tab")
        self.tabs.add_button.setToolTip(tr("新しいタブ") + (" · " + key if key else ""))
        for page in [self.welcome, *self.workspaces()]:
            page._shortcuts()
            page.update_controls()

    def _workspace(self, *, persist=True):
        page = Window(workspace_host=self, preferences=self.preferences, persist_on_close=persist)
        page.setWindowFlags(Qt.WindowType.Widget)
        page.top_bar.hide()  # its app-wide controls show in the tab row while it is the current tab
        page.closed.connect(self.workspace_closed)
        page.closeCancelled.connect(self.cancel_close)
        page.stateChanged.connect(lambda: self.update_tab(page))
        page.pathsRenamed.connect(lambda mapping: self.propagate_rename(page, mapping))
        return page

    def current_workspace(self):
        return self.tabs.currentWidget() or self.welcome

    def workspaces(self):
        return [self.tabs.widget(index) for index in range(self.tabs.count())]

    def first_run_setup(self):
        """Choose the save method once and keep recovery records out of image folders.

        Only a brand-new settings profile gets here. Existing profiles keep their
        record location (image folders by default) so earlier records stay visible.
        """
        if not self.first_run:
            return False
        self.first_run = False
        from .onboarding import FirstRunDialog
        dialog = FirstRunDialog(self)
        chosen = dialog.exec() == QDialog.DialogCode.Accepted and dialog.save_mode() is not None
        data = dict(self.preferences.data)
        data.setdefault("storage", "app")
        # The tag buttons are saved now, in the language of the first start (issue #3).
        data.setdefault("quick_tags", quick_tags({}))
        settings = data.get("settings", {})
        settings = settings if isinstance(settings, dict) else {}
        # Closing without a choice must not lead to replacing originals: save to a separate folder.
        data["settings"] = {**settings, **(dialog.settings() if chosen else {"overwrite": False})}
        dialog.deleteLater()
        try:
            self.preferences.save(data)
        except OSError:
            self.welcome.error(tr("初回の設定を保存できませんでした。設定の保存先と空き容量を確認してください。"))
            return False
        for page in [self.welcome, *self.workspaces()]:
            page.restore_settings()
            page.update_controls()
        if not chosen:
            self.welcome.info(tr("保存方法を選ばなかったため、元画像は変更せず、別フォルダー（画像のあるフォルダー内の「Sumīre」）に保存します。右上の保存方法から変更できます。"))
        return True

    def session_state(self):
        return {"version": 1, "current": self.tabs.currentIndex(),
                "tabs": [page.session_state() for page in self.workspaces()]}

    def resume_session(self):
        """Recreate tab order immediately; decode only the selected tab."""
        if self.session_started or self.tabs.count():
            return
        self.session_started = True
        saved = self.preferences.data.get("session")
        if "session" not in self.preferences.data:
            inputs = self.preferences.data.get("inputs", [])
            workspace = {}
            if isinstance(inputs, list) and all(isinstance(raw, str) for raw in inputs):
                try:
                    workspace = self.welcome.saved_workspace(inputs)
                except (OSError, ValueError):
                    pass
            saved = {"version": 1, "current": 0, "tabs": [{"inputs": inputs,
                     "settings": self.preferences.data.get("settings", {}), "workspace": workspace}]} if inputs else None
        if not isinstance(saved, dict) or saved.get("version") != 1 or not isinstance(saved.get("tabs"), list):
            return
        selected = saved.get("current", 0)
        selected = selected if type(selected) is int else 0
        restored = []
        self.restoring_session = True
        try:
            for number, state in enumerate(saved["tabs"]):
                if not isinstance(state, dict) or not isinstance(state.get("inputs"), list):
                    continue
                inputs = []
                for raw in state["inputs"]:
                    try:
                        if isinstance(raw, str) and raw and Path(raw).exists():
                            inputs.append(str(Path(raw).resolve()))
                    except (OSError, ValueError):
                        continue
                if state["inputs"] and not inputs:
                    continue
                page = self._workspace()
                settings = state.get("settings", {})
                if isinstance(settings, dict):
                    page.restore_settings(settings)
                workspace = state.get("workspace", {})
                page.deferred_session = {"workspace": workspace if isinstance(workspace, dict) else {}}
                page.workspace_inputs = inputs
                title = page.deferred_session["workspace"].get("title")
                page.custom_title = " ".join(title.split())[:60] or None if isinstance(title, str) else None
                root = page.deferred_session["workspace"].get("root")
                try:
                    if isinstance(root, str) and len(inputs) == 1 and Path(inputs[0]).is_relative_to(Path(root).resolve()):
                        page.folder_root = Path(root).resolve()
                        page.browse_target = Path(inputs[0]).resolve()
                except (OSError, ValueError):
                    pass
                self.tabs.addTab(page, page.workspace_title() if inputs else tr("新しいタブ"))
                page.update_controls()
                restored.append(number)
        finally:
            self.restoring_session = False
        if restored:
            self.stack.setCurrentWidget(self.tabs)
            target = min(range(len(restored)), key=lambda index: abs(restored[index] - selected))
            self.tabs.setCurrentIndex(target)
            self.tab_changed(target)

    def restore_page(self, page):
        if page.deferred_session is None or self.close_mode:
            return
        state, page.deferred_session = page.deferred_session, None
        if page.workspace_inputs:
            inputs, page.workspace_inputs = list(page.workspace_inputs), []
            page.restoring_workspace = state.get("workspace", {})
            page.load_inputs(inputs)

    def new_tab(self):
        if self.close_mode:
            return None
        source = self.current_workspace()
        try:
            source.remember_workspace()
        except OSError:
            pass
        page = self._workspace()
        index = self.tabs.addTab(page, tr("新しいタブ"))
        self.stack.setCurrentWidget(self.tabs)
        self.tabs.setCurrentIndex(index)
        self.update_tab(page)
        return page

    def choose_open_mode(self, page, inputs):
        dialog = QMessageBox(self)
        dialog.setWindowTitle(tr("画像・フォルダーの開き方"))
        dialog.setText(tr("選んだ画像・フォルダーをどこに開きますか？"))
        dialog.setInformativeText(tr("追加：現在の一覧と編集を保ったまま、同じ保存設定で作業します（ファイルは移動しません）。\n新しいタブ：独立した一覧で作業します。"))
        append = dialog.addButton(tr("現在のタブに追加"), QMessageBox.ButtonRole.AcceptRole)
        new = dialog.addButton(tr("新しいタブで開く"), QMessageBox.ButtonRole.ActionRole)
        dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(append)
        dialog.exec()
        return "append" if dialog.clickedButton() is append else "new" if dialog.clickedButton() is new else None

    def open_inputs(self, inputs, *, source=None, mode=None):
        inputs = [str(Path(raw).resolve()) for raw in inputs]
        if not inputs:
            return
        page = source if source in self.workspaces() else self.current_workspace()
        if self.opening_blocked(page, inputs, mode):
            self.pending_inputs.append((inputs, page, mode))
            self.request_timer.start()
            page.info(tr("処理が終わったら画像・フォルダーを開きます…"))
            return
        project = len(inputs) == 1 and Path(inputs[0]).is_file() and Path(inputs[0]).suffix.lower() in PROJECT_EXTENSIONS
        archives = [raw for raw in inputs if is_archive(raw)]
        if archives and len(inputs) > 1:
            # Each ZIP goes to a tab of its own; the other images and folders open as usual.
            for raw in archives:
                self.open_inputs([raw], source=page, mode="new")
            rest = [raw for raw in inputs if raw not in archives]
            if rest:
                self.open_inputs(rest, source=page, mode=mode)
            return
        occupied = bool(page.workspace_inputs or page.model.paths)
        if project or archives or page.archive is not None:
            mode = "new"  # a ZIP is shown read only in its own tab; nothing is added to it
        elif mode is None:
            mode = self.choose_open_mode(page, inputs) if occupied else "append"
        if mode is None:
            return
        # Committing an inline name edit while the chooser opens can start a rename.
        if self.opening_blocked(page, inputs, mode):
            self.pending_inputs.append((inputs, page, mode))
            self.request_timer.start()
            return
        if page is self.welcome or (mode == "new" and occupied):
            page = self.new_tab()
            page.load_inputs(inputs)
        elif mode == "new":
            page.load_inputs(inputs)
        else:
            page.append_inputs(inputs)

    def receive_external(self, inputs):
        self.pending_inputs.append((list(inputs), None, None))
        self.request_timer.start()

    def opening_blocked(self, page, inputs, mode):
        if self.close_mode or (mode != "new" and (page.busy() or page.saving)):
            return True
        # Do not mistake another tab's in-progress rename journal for a crashed operation.
        folders = {Path(raw) if Path(raw).is_dir() else Path(raw).parent for raw in inputs}
        return any(tab.batch_job is not None and folders.intersection(path.parent for path in tab.model.paths)
                   for tab in self.workspaces())

    def process_external(self):
        if not self.pending_inputs:
            self.request_timer.stop()
            return
        inputs, page, mode = self.pending_inputs[0]
        if page is not None and page is not self.welcome and page not in self.workspaces():
            page, mode = None, "new"
        target = page or self.current_workspace()
        if QApplication.activeModalWidget() or self.opening_blocked(target, inputs, mode):
            return
        self.pending_inputs.popleft()
        self.showNormal() if self.isMinimized() else self.show()
        self.raise_()
        self.activateWindow()
        if inputs:
            self.open_inputs(inputs, source=page, mode=mode)

    def update_tab(self, page):
        if not hasattr(self, "tabs"):
            return
        index = self.tabs.indexOf(page)
        if index < 0:
            return
        title = page.workspace_title() if page.workspace_inputs else tr("新しいタブ")
        if page.document and page.document.dirty:
            title = "● " + title
        self.tabs.setTabText(index, title.replace("&", "&&"))
        self.tabs.schedule_position()
        self.tabs.setTabToolTip(index, "\n".join(page.workspace_inputs) or tr("画像・フォルダーを開いてください"))
        if page is self.tabs.currentWidget():
            self.setWindowTitle(page.windowTitle())
        self.trim_memory()

    def trim_memory(self):
        if self.trimming_memory or not hasattr(self, "tabs"):
            return
        self.trimming_memory = True
        try:
            pages = self.workspaces()
            for page in pages:
                if page is not self.tabs.currentWidget():
                    page.set_workspace_active(False)
            usage = sum(page.memory_usage for page in pages)
            # Current documents (including Undo and eraser originals) and dirty
            # documents are protected even when they exceed the cache budget.
            candidates = sorted(((getattr(doc, "last_access", 0), page, path, doc)
                                 for page in pages for path, doc in page.documents.items()
                                 if doc is not page.document and not doc.dirty), key=lambda item: item[0])
            for _, page, path, doc in candidates:
                if usage <= self.memory_limit:
                    break
                page.documents.pop(path)
                usage -= doc.memory
            for page in sorted(pages, key=lambda page: page is self.tabs.currentWidget()):
                # Keep a small visible working set even when protected documents
                # alone exceed the budget, avoiding a decode/evict/repaint loop.
                minimum = 32 if page is self.tabs.currentWidget() else 0
                while usage > self.memory_limit and len(page.model.cache) > minimum:
                    _, cached = page.model.cache.popitem(last=False)
                    usage -= max((size.width() * size.height() * 4 for size in cached.availableSizes()), default=0)
        finally:
            self.trimming_memory = False

    def place_app_controls(self):
        """Show the current tab's app-wide controls in the tab row."""
        page = self.tabs.currentWidget()
        owner = self.app_controls_owner
        if owner is page:
            return
        if owner is not None and owner in self.workspaces():
            owner.take_back_app_controls()
        self.app_controls_owner = page
        if page is not None:
            left, right = page.lend_app_controls()
            self.tabs.leading_row.addWidget(left)
            self.tabs.trailing_row.addWidget(right)
            left.show()
            right.show()
        self.tabs.schedule_position()

    def tab_changed(self, index):
        self.place_app_controls()
        if self.restoring_session:
            return
        for page in self.workspaces():
            page.compare(False)
            page.save_popover.hide()
            page.filter_popover.hide()
            page.set_workspace_active(page is self.tabs.currentWidget())
        self.trim_memory()
        if index >= 0:
            page = self.tabs.widget(index)
            self.restore_page(page)
            self.update_tab(page)
            if page.document:
                page.canvas.setFocus()

    def cycle_tab(self, delta):
        if self.tabs.count():
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + delta) % self.tabs.count())

    def close_current_tab(self):
        self.close_tab(self.tabs.currentWidget())

    def close_tab(self, page):
        if page in self.workspaces():
            page.file_label.commit_edit()
            page.close()

    def tab_menu(self, position):
        index = self.tabs.tabBar().tabAt(position)
        menu = QMenu(self)
        if index >= 0:
            page = self.tabs.widget(index)
            rename = menu.addAction(tr("タブの名前を変更…"), lambda: self.rename_tab(page))
            rename.setEnabled(bool(page.workspace_inputs))
            menu.addSeparator()
            menu.addAction(tr("このタブを閉じる"), lambda: self.close_tab(self.tabs.widget(index)))
        menu.addAction(tr("すべての作業タブを閉じる"), self.close_all_tabs)
        menu.exec(self.tabs.tabBar().mapToGlobal(position))

    def rename_tab(self, page):
        if page not in self.workspaces() or not page.workspace_inputs:
            return
        folder = Path(page.workspace_inputs[0])
        dialog = QInputDialog(self)
        dialog.setWindowTitle(tr("タブの名前を変更"))
        dialog.setLabelText(tr("タブの名前（60文字まで）\n空欄にするとフォルダー名（{value}）に戻ります。").format(value=folder.name or folder))
        dialog.setTextValue(page.workspace_title())
        dialog.setOkButtonText(tr("変更"))
        dialog.setCancelButtonText(tr("キャンセル"))
        if page.confirm_dialog(dialog, accepted=QDialog.DialogCode.Accepted):
            page.set_custom_title(dialog.textValue())

    def workspace_closed(self, page):
        if not hasattr(self, "tabs"):
            return
        index = self.tabs.indexOf(page)
        if index < 0:
            return
        if self.app_controls_owner is page:
            # Give the controls back first, so they are deleted with their page.
            page.take_back_app_controls()
            self.app_controls_owner = None
        self.tabs.removeTab(index)
        page.deleteLater()
        if not self.tabs.count():
            self.welcome.restore_settings()
            self.welcome.refresh_welcome()
            self.stack.setCurrentWidget(self.welcome)
            self.setWindowTitle(tr("Sumīre — 画像の仕上げ"))
        if self.close_mode:
            QTimer.singleShot(0, self.close_next)

    def cancel_close(self):
        self.quit_confirmed = False
        self.close_mode = None
        self.close_order.clear()
        self.closing_session = None

    def close_all_tabs(self):
        if self.close_mode:
            return
        self.close_mode = "tabs"
        self.closing_session = None
        self.prepare_close_order()
        self.close_next()

    def prepare_close_order(self):
        current = self.tabs.currentWidget()
        self.close_order = [page for page in self.workspaces() if page is not current]
        if current:
            self.close_order.append(current)

    def close_next(self):
        if not self.close_mode:
            return
        if self.tabs.count():
            page = next((page for page in self.close_order if page in self.workspaces()), self.tabs.widget(0))
            self.tabs.setCurrentWidget(page)
            self.close_tab(page)
        else:
            application = self.close_mode == "application"
            self.close_mode = None
            self.close_order.clear()
            if application:
                self.shutdown_ready = True
                self.close()
            else:
                self.pending_inputs.clear()
                self.request_timer.stop()

    def confirm_quit(self):
        """Ask before quitting, saying what is lost; can be turned off for good."""
        if not QUIT_CONFIRMATION["enabled"] or self.preferences.data.get("hide_quit_confirmation") is True:
            return True
        unsaved = [page for page in self.workspaces() if page.document is not None and page.document.dirty]
        details = [tr("※ 操作履歴は消えます。")]
        kept = len(originals().files)
        if kept:
            details.append(tr("上書き前に残した元画像（{kept}枚）は削除され、「上書き前の元画像に戻す」ができなくなります。").format(kept=kept))
        if unsaved:
            if all(page.auto.isChecked() for page in unsaved):
                details.append(tr("保存していない加工は、終了する前に保存します。"))
            else:
                details.append(tr("保存していない加工があります。自動保存がオフのタブでは、画像ごとに保存するか確認します。"))
        box = QMessageBox(QMessageBox.Icon.Question, tr("Sumīreを終了"), tr("Sumīreを終了しますか？"),
                          QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel, self)
        box.setInformativeText("\n".join(details))
        box.button(QMessageBox.StandardButton.Ok).setText(tr("終了する"))
        box.button(QMessageBox.StandardButton.Cancel).setText(tr("キャンセル"))
        box.setDefaultButton(QMessageBox.StandardButton.Ok)
        hide = QCheckBox(tr("今後この確認を表示しない"))
        box.setCheckBox(hide)
        if box.exec() != QMessageBox.StandardButton.Ok:
            return False
        if hide.isChecked():
            try:
                self.preferences.save({**self.preferences.data, "hide_quit_confirmation": True})
            except OSError:
                pass
        return True

    def closeEvent(self, event):
        if not self.shutdown_ready and not self.close_mode and not self.quit_confirmed:
            if not self.confirm_quit():
                event.ignore()
                return
            self.quit_confirmed = True
        if self.shutdown_ready or not self.tabs.count():
            self.request_timer.stop()
            self.pending_inputs.clear()
            try:
                self.welcome.remember_workspace()
                snapshot = self.closing_session if self.closing_session is not None else self.session_state()
                self.preferences.save({**self.preferences.data, "session": snapshot})
            except OSError:
                self.shutdown_ready = False
                self.welcome.error(tr("終了時のタブ一覧を保存できませんでした。設定の保存先と空き容量を確認し、もう一度終了してください。"))
                event.ignore()
                return
            self.welcome.close()
            event.accept()
        else:
            event.ignore()
            if not self.close_mode:
                self.closing_session = self.session_state()
                self.close_mode = "application"
                self.prepare_close_order()
                self.close_next()

    def can_rename(self, source, mapping):
        return not any(page is not source and set(mapping).intersection(page.model.paths)
                       and (page.busy() or page.saving) for page in self.workspaces())

    def rename_record_folders(self, mapping):
        return {page.receipts.folder for page in self.workspaces()
                if page.receipts and set(mapping).intersection(page.model.paths)}

    def propagate_rename(self, source, mapping):
        for page in self.workspaces():
            if page is source:
                continue
            page.workspace_inputs = [str(mapping.get(Path(raw).resolve(), Path(raw))) for raw in page.workspace_inputs]
            page.excluded_paths = {mapping.get(path, path) for path in page.excluded_paths}
            if page.deferred_session is not None:
                workspace = page.deferred_session.get("workspace", {})
                for key in ("order", "excluded"):
                    values = workspace.get(key)
                    if isinstance(values, list):
                        workspace[key] = [str(mapping.get(Path(raw), Path(raw))) for raw in values if isinstance(raw, str)]
                current = workspace.get("current")
                if isinstance(current, str):
                    workspace["current"] = str(mapping.get(Path(current), Path(current)))
                page.update_controls()
                continue
            if not set(mapping).intersection(page.model.paths):
                page.update_controls()
                continue
            for document in page.documents.values():
                document.path = mapping.get(document.path, document.path)
                document.output = mapping.get(document.output, document.output)
            page.documents = OrderedDict((doc.path, doc) for doc in page.documents.values())
            page.owned = {mapping.get(path, path): digest for path, digest in page.owned.items()}
            page.batch_failures = {mapping.get(path, path): error for path, error in page.batch_failures.items()}
            page.operation_history.clear()
            page.replace_list([mapping.get(path, path) for path in page.model.paths], mapping)
            if page.document:
                page.setWindowTitle(f"{page.document.path.name} — Sumīre")
            page.update_controls()
