"""Selection, review workflow, workspace persistence, and library analysis UI."""
from .i18n import tr
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from PySide6.QtCore import QFile, QItemSelectionModel, QSize, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox, QGridLayout,
    QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListView, QMenu,
    QMessageBox, QProgressBar, QPushButton, QSizePolicy, QSlider, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .analysis import find_duplicates
from .compare import ComparisonDialog
from .backups import store as originals
from .export import check_cancel, file_digest
from .folders import label_folder_target
from .icons import icon, swatch
from .imaging import ImageProblem, load_image
from .labels import MAX_TAGS, REVIEW_LABELS, ReviewLabels, clean_tags
from .shortcuts import QUICK_TAG_COMMANDS
from .text_tool import TextStyle
from .library import COMPACT_GRID, LIST_ICON, LibraryDelegate, LibraryFilter, LibraryModel, LibraryView
from .monitor import FolderMonitor
from .organize import sequence_stems
from .preferences import Preferences
from .theme import TOKENS
from .ui import Popover, SegmentComboBox, fact_table, html_text, repolish, section_label, tool_button

MAX_COMPARE = 6
AUTO_SORT_TIP = tr(
    "採用・保留・不採用のフォルダーがある場所で、ラベルを付けた画像をすぐそのフォルダーへ移します。\n"
    "・画像のフォルダーの中にラベルのフォルダーがあるとき：その中の、付けたラベルのフォルダーへ\n"
    "・画像がラベルのフォルダーの中にあるとき：隣の、付けたラベルのフォルダーへ（例：「保留」の中で採用にすると「採用」へ）\n"
    "・まだないラベルのフォルダーは作ります。ラベルのフォルダーが1つもない場所では移しません。\n"
    "・ラベルを外したときは移しません。\n"
    "・フォルダー名は日本語・英語・中国語のどれでも認識します（採用 / Accept / 采用 など）。\n"
    "・画像ファイルはそのまま移り、ラベルとメモも一緒に移ります。「直前の整理操作を戻す」で戻せます。")


def tint_combo(combo):
    """Show the chosen item's colour in the closed combo box as well."""
    color = combo.itemData(combo.currentIndex(), Qt.ItemDataRole.ForegroundRole)
    combo.setStyleSheet(f"QComboBox {{ color: {color.name()}; font-weight: 600; }}" if isinstance(color, QColor) else "")


class Workbench:
    def init_workbench(self):
        self.preferences = self.shared_preferences or Preferences()
        self.workspace_inputs = []
        self.excluded_paths = set()
        self.restoring_workspace = None
        self.deferred_session = None
        self.operation_history = []
        self.batch_failures = {}
        self.watched_folders = set()
        self.watch_pending = set()
        self.watch_monitor = FolderMonitor(self)
        self.watch_monitor.discovered.connect(self.accept_watched_images)
        self.watch_timer = QTimer(self)
        self.watch_timer.setInterval(1200)
        self.watch_timer.timeout.connect(self.poll_folders)
        self.watch_timer.start()
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(220)
        self.search_timer.timeout.connect(self.apply_search)

    def build_library_panel(self):
        """Left panel: search, filters, thumbnail list; bulk work lives in menus."""
        self.model = LibraryModel(self)
        if self.workspace_host is not None:
            self.model.cacheChanged.connect(self.workspace_host.trim_memory)
        self.proxy = LibraryFilter(self)
        self.proxy.setSourceModel(self.model)
        self.build_library_menu()
        panel = QWidget()
        self.library_panel = panel
        panel.setObjectName("panel")
        panel.setMinimumWidth(208)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(8)
        self.library_title = QWidget()
        header = QHBoxLayout(self.library_title)
        self.library_header = header
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)
        self.count_label = section_label(tr("画像"))
        header.addWidget(self.count_label)
        header.addStretch(1)
        self.undo_organize_button = tool_button("undo", tr("直前の整理操作を戻す"),
                                                lambda: self.workflow_actions["undo_organize"].trigger())
        self.undo_organize_button.setAccessibleName(tr("直前の整理操作を戻す"))
        header.addWidget(self.undo_organize_button)
        self.library_menu_button = tool_button("more", tr("一覧の操作 · 連番・形式の変換・圧縮・重複の削除"))
        self.library_menu_button.setAccessibleName(tr("一覧の操作"))
        self.library_menu_button.setMenu(self.library_menu)
        self.library_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        header.addWidget(self.library_menu_button)
        # Whole-tab actions form a 2×2 grid beside and under the count (採用の書き出しは
        # 仕分けをリセットの真上) and stack in one column when the panel is narrow,
        # so they never widen the left panel in 800px windows.
        self.library_actions = QGridLayout()
        self.library_actions.setHorizontalSpacing(6)
        self.library_actions.setVerticalSpacing(6)
        self.library_actions_wide = None
        self.export_accepted_button = QToolButton()
        self.export_accepted_button.setText(tr("ラベルごとに書き出す…"))
        self.export_accepted_button.clicked.connect(lambda *_args: self.workflow_actions["export_accepted"].trigger())
        self.export_accepted_button.setToolTip(tr("採用・保留・不採用の画像を、ラベルごとのフォルダーへ移動・書き出しします。実行前に確認します。"))
        self.export_accepted_button.setAccessibleName(tr("ラベルごとに画像を書き出す"))
        self.batch_delete_button = QToolButton()
        self.batch_delete_button.setText(tr("メタデータ一括削除"))
        self.batch_delete_button.clicked.connect(self.batch_button.trigger)
        self.batch_delete_button.setToolTip(tr("絞り込みや選択にかかわらず、このタブの全画像が対象です。"))
        self.batch_delete_button.setAccessibleName(tr("このタブの全画像のメタデータを一括削除"))
        self.reset_labels_button = QToolButton()
        self.reset_labels_button.setText(tr("仕分けをリセット"))
        self.reset_labels_button.clicked.connect(lambda *_args: self.workflow_actions["reset_labels"].trigger())
        self.reset_labels_button.setToolTip(tr("このタブの全画像の不採用・保留・採用を外し、未判定に戻します。画像・メモは変わりません。"))
        self.reset_labels_button.setAccessibleName(tr("このタブの全画像の仕分けをリセット"))
        self.export_accepted_button.setObjectName("acceptedExport")
        for button in self.library_action_buttons():
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setProperty("variant", "listAction")  # less side padding: two fit side by side
            button.setMinimumWidth(button.sizeHint().width())
        layout.addLayout(self.library_actions)
        self.arrange_library_actions(True)
        self.build_folder_bar(layout)
        panel.installEventFilter(self)
        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("名前・メモ・タグで検索"))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icon("search", "text_muted"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.search.setToolTip(tr("ファイル名・メモ・タグの一部で絞り込みます · Ctrl+F"))
        self.search.setAccessibleName(tr("画像を名前・メモ・タグで検索"))
        self.search.textChanged.connect(lambda _text: self.search_timer.start())
        search_row.addWidget(self.search, 1)
        self.filter_button = tool_button("filter", tr("並び順・ラベルの絞り込み・一覧 / グリッド"), self.show_filter_popover)
        self.filter_button.setAccessibleName(tr("並び順・絞り込み・表示"))
        search_row.addWidget(self.filter_button)
        layout.addLayout(search_row)
        self.selection_bar = QFrame()
        self.selection_bar.setObjectName("selectionBar")
        bar = QHBoxLayout(self.selection_bar)
        bar.setContentsMargins(10, 3, 3, 3)
        bar.setSpacing(2)
        self.selection_label = QLabel()
        bar.addWidget(self.selection_label, 1)
        self.selection_menu = QMenu(self)
        self.selection_menu.aboutToShow.connect(lambda: self.populate_selection_menu(self.selection_menu))
        self.selection_menu_button = QToolButton()
        self.selection_menu_button.setText(tr("操作  ▾"))
        self.selection_menu_button.setProperty("variant", "ghost")
        self.selection_menu_button.setMenu(self.selection_menu)
        self.selection_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.selection_menu_button.setToolTip(tr("選択した画像へのラベル・メタデータ削除・連番・比較"))
        bar.addWidget(self.selection_menu_button)
        bar.addWidget(tool_button("close", tr("選択を解除（表示中の画像だけを選択）"), self._select_only_current))
        self.selection_bar.hide()
        layout.addWidget(self.selection_bar)
        self.list = LibraryView()
        self.list.setObjectName("library")
        self.list.setModel(self.proxy)
        self.library_delegate = LibraryDelegate(self.list)
        self.list.setItemDelegate(self.library_delegate)
        self.model.renameRequested.connect(lambda path, stem: self.rename_source(Path(path), stem))
        self.list.setIconSize(LIST_ICON)
        self.list.setUniformItemSizes(True)
        self.list.setMouseTracking(True)
        self.list.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.show_library_context_menu)
        self.list.selectionModel().currentChanged.connect(lambda index, previous: self.request_index(self.source_row(index)))
        self.list.selectionModel().selectionChanged.connect(lambda *_args: self.update_controls())
        self.list.clicked.connect(lambda index: self.request_index(self.source_row(index)))
        self.list.reordered.connect(self.reorder_selection)
        self.list.filesDropped.connect(self.open_inputs)
        self.list.setMinimumHeight(120)
        layout.addWidget(self.list, 1)
        self.batch_progress = QProgressBar()
        self.batch_progress.setObjectName("batchProgress")
        self.batch_progress.setFormat(tr("%v / %m 枚 · %p%"))
        self.batch_progress.setAccessibleName(tr("一括処理の進捗"))
        self.batch_progress.hide()
        layout.addWidget(self.batch_progress)
        self.review_summary = self._label("", "faint")
        layout.addWidget(self.review_summary)
        self.model.dataChanged.connect(self.update_summary)
        self.build_filter_popover()
        return panel

    def build_filter_popover(self):
        self.filter_popover = Popover(self, 280)
        layout = self.filter_popover.content
        layout.addWidget(section_label(tr("並び順")))
        # Only the direction is coloured: ascending blue, descending red, the rest plain.
        self.sort_combo = SegmentComboBox()
        for key, direction, value in [(tr("名前順 · "), tr("昇順 ↑"), "name_asc"), (tr("名前順 · "), tr("降順 ↓"), "name_desc"),
                                      (tr("更新日時 · "), tr("古い順 ↑"), "date_asc"), (tr("更新日時 · "), tr("新しい順 ↓"), "date_desc"),
                                      (tr("手動の順番"), "", "manual")]:
            tone = TOKENS["sort_asc"] if value.endswith("_asc") else TOKENS["sort_desc"] if value.endswith("_desc") else None
            self.sort_combo.add_segments([(key, None)] + ([(direction, tone)] if direction else []), value)
        self.sort_combo.setToolTip(tr("一覧・左右キー・一括処理・連番に使う順番です。手動の順番は一覧内のドラッグで変えられます。"))
        self.sort_combo.currentIndexChanged.connect(self.sort_images)
        layout.addWidget(self.sort_combo)
        layout.addWidget(section_label(tr("ラベルで絞り込み")))
        self.filter_combo = QComboBox()
        tones = {"all": "text", "unlabelled": "text_muted", "accepted": "accent", "pending": "warn", "rejected": "danger"}
        for text, label in [(tr("すべてのラベル"), "all"), (tr("ラベルなし"), "unlabelled"), *[(text, label) for label, text in REVIEW_LABELS.items()]]:
            self.filter_combo.addItem(text, label)
            color = TOKENS[tones[label]]
            self.filter_combo.setItemData(self.filter_combo.count() - 1, QColor(color), Qt.ItemDataRole.ForegroundRole)
            if label in REVIEW_LABELS:
                self.filter_combo.setItemIcon(self.filter_combo.count() - 1, swatch(color, 10))
        self.filter_combo.currentIndexChanged.connect(self.filter_changed)
        self.filter_combo.currentIndexChanged.connect(lambda *_args: tint_combo(self.filter_combo))
        tint_combo(self.filter_combo)
        layout.addWidget(self.filter_combo)
        layout.addWidget(section_label(tr("タグで絞り込み")))
        self.tag_combo = QComboBox()
        self.tag_combo.addItem(tr("すべてのタグ"), None)
        self.tag_combo.currentIndexChanged.connect(self.tag_filter_changed)
        layout.addWidget(self.tag_combo)
        layout.addWidget(section_label(tr("表示")))
        row = QHBoxLayout()
        row.setSpacing(8)
        # The combo holds the choice (settings and tests use it); two buttons switch it in one click.
        self.view_combo = QComboBox()
        self.view_combo.addItems([tr("一覧"), tr("グリッド")])
        self.view_combo.currentIndexChanged.connect(self.update_library_view)
        self.view_combo.hide()
        segmented = QFrame()
        segmented.setObjectName("segmented")
        switch = QHBoxLayout(segmented)
        switch.setContentsMargins(3, 3, 3, 3)
        switch.setSpacing(2)
        self.view_buttons = []
        for index, text in enumerate((tr("一覧"), tr("グリッド"))):
            button = QPushButton(text)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.clicked.connect(lambda checked=False, value=index: self.view_combo.setCurrentIndex(value))
            switch.addWidget(button)
            self.view_buttons.append(button)
        row.addWidget(segmented)
        self.thumbnail_size = QSlider(Qt.Orientation.Horizontal)
        self.thumbnail_size.setRange(40, 240)
        self.thumbnail_size.setValue(128)
        self.thumbnail_size.setToolTip(tr("グリッドのサムネイルサイズ"))
        self.thumbnail_size.setAccessibleName(tr("グリッドのサムネイルサイズ"))
        self.thumbnail_size.valueChanged.connect(self.update_library_view)
        row.addWidget(self.thumbnail_size, 1)
        layout.addLayout(row)
        self.filter_reset = QPushButton(tr("絞り込みを解除"))
        self.filter_reset.setProperty("variant", "link")
        self.filter_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.filter_reset.clicked.connect(self.reset_filters)
        layout.addWidget(self.filter_reset, 0, Qt.AlignmentFlag.AlignLeft)

    def show_filter_popover(self):
        if self.filter_popover.isVisible():
            self.filter_popover.hide()
            return
        self.filter_popover.show_for(self.filter_button, align_right=False)

    def build_library_menu(self):
        self.library_menu = QMenu(self)
        self.library_menu.setToolTipsVisible(True)
        self.workflow_actions = {}
        actions = [
            ("export_accepted", tr("ラベルごとに書き出す…"), self.export_labels),
            ("save_as", tr("別名で保存…"), self.save_as),
            ("save_selected", tr("メタデータを削除して保存"), self.save_selected),
            ("remove_selected", tr("一覧から外す"), self.remove_selected),
            ("delete_selected", tr("画像を削除…"), self.delete_selected),
            ("number_selected", tr("選択画像を連番へ"), lambda: self.number_images(self.selected_paths())),
            ("note", tr("メモ…"), self.edit_note),
            ("tags", tr("タグ…"), self.edit_tags),
            ("cut_files", tr("切り取り"), lambda: self.clip_files(cut=True)),
            ("copy_files", tr("ファイルをコピー"), lambda: self.clip_files(cut=False)),
            ("paste_files", tr("貼り付け"), self.paste_image),
            ("undo_organize", tr("直前の整理操作を戻す\tCtrl+Alt+Z"), self.undo_organization),
            ("compare", tr("複数枚を並べて比較…"), self.compare_images),
            ("duplicates", tr("重複を削除…"), self.analyze_duplicates),
            ("reset_labels", tr("仕分けをすべてリセット"), self.reset_review_labels),
            ("reset_list", tr("一覧を初期状態に戻す…"), self.reset_whole_list),
            ("convert_all", tr("一覧全体の形式を変換…"), lambda: self.convert_images(list(self.model.paths), "convert")),
            ("compress_all", tr("一覧全体の容量削減…"), lambda: self.convert_images(list(self.model.paths), "compress")),
            ("convert_selected", tr("形式を変換…"), lambda: self.convert_images(self.selected_or_current(), "convert")),
            ("compress_selected", tr("容量削減…"), lambda: self.convert_images(self.selected_or_current(), "compress")),
            ("collage", tr("コラージュを作成…"), self.make_collage),
            ("merge_labels", tr("ラベルのフォルダーをまとめる…"), self.merge_label_folders),
        ]
        for key, text, callback in actions:
            action = QAction(text, self)
            action.triggered.connect(lambda *_args, function=callback: function())
            self.workflow_actions[key] = action
        self.workflow_actions["remove_selected"].setToolTip(tr("元ファイルは残したまま、このタブの一覧から外します。再読み込みで戻せます。"))
        self.workflow_actions["delete_selected"].setToolTip(tr("選んだ画像ファイルをごみ箱へ移します。実行前に確認します。"))
        self.workflow_actions["save_as"].setToolTip(tr("表示中の画像を、名前・形式を指定して新しいファイルに保存します（メタデータなし）。"))
        self.workflow_actions["duplicates"].setToolTip(tr("内容が完全に同じ画像を探し、残す1枚を選んで残りをごみ箱へ移します。実行前に確認します。"))
        self.workflow_actions["collage"].setToolTip(tr("選択した画像（1枚から）を、並べ方を選んで1枚にまとめます。画像はあとから追加できます。"))
        self.workflow_actions["merge_labels"].setToolTip(tr("このタブのフォルダーにある採用・保留・不採用のフォルダーの画像を、1つのフォルダーに集めます。実行前に確認します。"))
        self.workflow_actions["reset_list"].setToolTip(tr("この起動中の上書きを元画像に戻し、表示中の画像の加工を消して、"
                                                      "ラベル・メモ・並び順・絞り込み・検索も解除します。実行前に確認します。"))
        for key, tip in (
                ("convert_selected", tr("PNG・JPEG・WebP・AVIFなどの別の形式で、新しいファイルとして書き出します。元画像は変わりません。")),
                ("convert_all", tr("一覧の全画像を、別の形式の新しいファイルとして書き出します。元画像は変わりません。")),
                ("compress_selected", tr("画質や寸法を下げて、ファイルを小さくした画像を書き出します。元画像は変わりません。")),
                ("compress_all", tr("一覧の全画像について、ファイルを小さくした画像を書き出します。元画像は変わりません。"))):
            self.workflow_actions[key].setToolTip(tip)
        self.watch_action = QAction(tr("フォルダーの追加画像を取り込む"), self)
        self.watch_action.setCheckable(True)
        self.watch_action.setChecked(True)
        self.label_menu = QMenu(tr("ラベル"), self)
        self.label_menu.setToolTipsVisible(True)
        for action in self.label_actions.values():
            self.label_menu.addAction(action)
        self.auto_sort_action = QAction(tr("ラベルのフォルダーへ自動で振り分ける"), self)
        self.auto_sort_action.setCheckable(True)
        self.auto_sort_action.setToolTip(AUTO_SORT_TIP)
        self.label_menu.addSeparator()
        self.label_menu.addAction(self.auto_sort_action)
        # Whole-tab work that has no button of its own (一括削除・リセット・採用の書き出し・
        # 整理を戻す are buttons in the panel header).
        menu = self.library_menu
        for item in (self.number_button, None, self.workflow_actions["convert_all"], self.workflow_actions["compress_all"],
                     None, self.workflow_actions["merge_labels"], self.workflow_actions["duplicates"], self.workflow_actions["reset_list"], None, self.watch_action):
            menu.addSeparator() if item is None else menu.addAction(item)

    def populate_selection_menu(self, menu):
        """Actions for the selected images, shared by the selection bar and right-click."""
        menu.clear()
        menu.setToolTipsVisible(True)
        menu.addMenu(self.label_menu)
        menu.addSeparator()
        self.populate_move_menu(menu, self.selected_or_current())
        for item in (self.workflow_actions["save_as"], self.workflow_actions["save_selected"],
                     self.workflow_actions["convert_selected"], self.workflow_actions["compress_selected"], None,
                     self.workflow_actions["compare"], self.workflow_actions["collage"], self.workflow_actions["number_selected"], None,
                     self.rename_button, self.workflow_actions["note"], self.workflow_actions["tags"], None,
                     self.workflow_actions["cut_files"], self.workflow_actions["copy_files"], self.workflow_actions["paste_files"], None,
                     self.workflow_actions["remove_selected"],
                     self.workflow_actions["delete_selected"]):
            menu.addSeparator() if item is None else menu.addAction(item)

    def remove_selected(self):
        paths = self.selected_paths()
        if not paths or self.busy() or self.saving:
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle(tr("一覧から外す"))
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(tr("選択した画像 {count} 枚を、このタブの一覧から外しますか？").format(count=len(paths)))
        dialog.setInformativeText(tr("画像ファイルは削除・移動しません。他のタブにも影響しません。\n"
                                  "「ファイル → 一覧を再読み込み」で戻せます。"))
        dialog.setDetailedText("\n".join(str(path) for path in paths))
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        dialog.button(QMessageBox.StandardButton.Ok).setText(tr("一覧から外す"))
        dialog.button(QMessageBox.StandardButton.Cancel).setText(tr("キャンセル"))
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        dialog.setEscapeButton(QMessageBox.StandardButton.Cancel)
        accepted = self.confirm_dialog(dialog)
        if not accepted or any(path not in self.model.rows for path in paths):
            return
        action = lambda: self.exclude_from_list(paths)
        if self.document and self.document.path in paths:
            self.guard(action)
        else:
            action()

    def delete_selected(self):
        """Move the selected images (or the shown one) to the recycle bin, after a confirmation."""
        paths = [path for path in self.selected_or_current() if path in self.model.rows]
        if not paths or self.busy() or self.saving:
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle(tr("画像を削除"))
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(tr("画像 {count} 枚をごみ箱へ移しますか？").format(count=len(paths)))
        dialog.setInformativeText(tr("画像ファイルをごみ箱へ移し、一覧から外します。戻すときは、ごみ箱から元に戻してください。\n"
                                  "ごみ箱のない場所（ネットワーク上のフォルダーなど）の画像は、削除せずにそのまま残します。"))
        dialog.setDetailedText("\n".join(str(path) for path in paths))
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        dialog.button(QMessageBox.StandardButton.Ok).setText(tr("ごみ箱へ移す"))
        dialog.button(QMessageBox.StandardButton.Cancel).setText(tr("キャンセル"))
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        dialog.setEscapeButton(QMessageBox.StandardButton.Cancel)
        if not self.confirm_dialog(dialog) or any(path not in self.model.rows for path in paths):
            return
        action = lambda: self.trash_images(paths, tr("ごみ箱へ移しました · {count}枚"))
        if self.document and self.document.path in paths:
            self.guard(action)
        else:
            action()

    def exclude_from_list(self, paths, message=True):
        excluded = set(paths)
        visible = self.visible_paths()
        current = self.document.path if self.document else None
        position = visible.index(current) if current in visible else 0
        preferred = next((path for path in visible[position:] + visible[:position] if path not in excluded), None)
        self.excluded_paths.update(excluded)
        self.batch_failures = {path: reason for path, reason in self.batch_failures.items() if path not in excluded}
        if current in excluded:
            self.document = None
            self.index = -1
            self.canvas.set_document(None)
        for path in excluded:
            if path in self.documents and not self.documents[path].dirty:
                self.documents.pop(path)
        self.replace_list([path for path in self.model.paths if path not in excluded])
        self.ensure_visible_current(preferred if current in excluded else current)
        if message:
            self.info(tr("一覧から外しました · {count}枚").format(count=len(excluded)))

    def show_library_context_menu(self, position):
        if not self.list.indexAt(position).isValid() and not self.selected_paths():
            return
        if not hasattr(self, "context_menu"):
            self.context_menu = QMenu(self)
        self.populate_selection_menu(self.context_menu)
        self.context_menu.popup(self.list.viewport().mapToGlobal(position))

    def _select_only_current(self):
        selection = self.list.selectionModel()
        selection.blockSignals(True)
        selection.clearSelection()
        selection.blockSignals(False)
        self._select_current()
        self.update_controls()

    def focus_search(self):
        self.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search.selectAll()

    def clear_search(self):
        self.search_timer.stop()
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.proxy.text = ""

    def apply_search(self):
        text = self.search.text().strip()
        if text == self.proxy.text:
            return
        if self.busy() or self.saving or self.pending_action is not None:
            # Retry after the current load/save so typed text is never dropped.
            self.search_timer.start()
            return
        self.guard(self.apply_filter)
        if self.pending_action is None and not self.saving and self.proxy.text != text:
            # Leaving an unsaved image was cancelled; keep showing the active filter.
            self.search.blockSignals(True)
            self.search.setText(self.proxy.text)
            self.search.blockSignals(False)

    def reset_filters(self):
        self.filter_popover.hide()
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        if self.proxy.tag is not None:
            self.tag_combo.blockSignals(True)
            self.tag_combo.setCurrentIndex(0)
            self.tag_combo.blockSignals(False)
            self.proxy.tag = None
            if self.filter_combo.currentData() == "all" and not self.proxy.text:
                self.apply_filter()
        if self.filter_combo.currentData() != "all":
            self.filter_combo.setCurrentIndex(0)
        elif self.proxy.text:
            self.apply_search()

    def selected_paths(self):
        selected = {Path(index.data(Qt.ItemDataRole.UserRole)) for index in self.list.selectionModel().selectedIndexes()}
        return [path for path in self.model.paths if path in selected]

    def visible_paths(self):
        return [Path(self.proxy.index(row, 0).data(Qt.ItemDataRole.UserRole)) for row in range(self.proxy.rowCount())]

    def source_row(self, index):
        return self.proxy.mapToSource(index).row() if index.isValid() else -1

    def update_summary(self, *args):
        counts = Counter(self.model.labels.values())
        total, shown = len(self.model.paths), self.proxy.rowCount()
        text = " · ".join(f"{label_text} {counts[label]}" for label, label_text in REVIEW_LABELS.items())
        text += tr(" · 未判定 {value}").format(value=total - sum(counts.values()))
        if shown != total:
            text += tr("\n表示 {shown} / {total}").format(shown=shown, total=total)
        self.review_summary.setText(text)

    def update_workbench_controls(self):
        ready = bool(self.model.paths) and not self.busy() and not self.saving
        widths = []
        for button in self.library_action_buttons():
            button.ensurePolished()
            button.setMinimumWidth(button.sizeHint().width())
            widths.append(button.sizeHint().width())
        # Stacked, the actions need only the widest button.
        self.library_panel.setMinimumWidth(max(208, self.library_header.minimumSize().width() + 24, max(widths) + 24))
        self.update_library_actions_layout()
        self.list.setEditTriggers((QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
                                  if ready else QAbstractItemView.EditTrigger.NoEditTriggers)
        selected = self.selected_paths()
        self.filter_combo.setEnabled(ready)
        self.search.setEnabled(bool(self.model.paths) or bool(self.proxy.text))
        self.library_menu_button.setEnabled(bool(self.model.paths))
        undoable = ready and bool(self.operation_history)
        self.workflow_actions["undo_organize"].setEnabled(undoable)
        self.undo_organize_button.setEnabled(undoable)
        key = self.shortcut_hint("undo_organize") if hasattr(self, "bindings") else ""
        self.undo_organize_button.setToolTip(tr("直前の整理操作を戻す（仕分け・並べ替え・名前・メモ）") + (" · " + key if key else ""))
        labelled = ready and any(self.model.labels.get(path) for path in self.model.paths)
        self.workflow_actions["reset_labels"].setEnabled(labelled)
        self.reset_labels_button.setEnabled(labelled)
        self.workflow_actions["export_accepted"].setEnabled(labelled)
        self.export_accepted_button.setEnabled(labelled)
        for key in ("duplicates", "compare", "convert_all", "compress_all"):
            self.workflow_actions[key].setEnabled(ready)
        self.workflow_actions["merge_labels"].setEnabled(not self.busy() and not self.saving and self.browsed_folder() is not None)
        for key in ("save_selected", "number_selected", "remove_selected", "delete_selected", "convert_selected", "compress_selected",
                    "cut_files", "copy_files", "paste_files"):
            self.workflow_actions[key].setEnabled(ready and bool(selected or self.document))
        self.workflow_actions["save_as"].setEnabled(ready and self.document is not None)
        self.workflow_actions["collage"].setEnabled(ready and bool(selected or self.document))
        self.workflow_actions["note"].setEnabled(ready and self.document is not None)
        self.workflow_actions["tags"].setEnabled(ready and bool(selected or self.document))
        self.selection_bar.setVisible(len(selected) > 1)
        self.selection_label.setText(tr("{count}枚を選択中").format(count=len(selected)))
        self.selection_label.setToolTip(tr("Ctrl+クリックで1枚ずつ追加・解除、Shift+クリックで範囲を選べます。"))
        active = self.proxy.active
        if self.filter_button.property("active") != active:
            self.filter_button.setProperty("active", active)
            repolish(self.filter_button)
        self.filter_button.setToolTip(tr("並び順・ラベルの絞り込み・一覧 / グリッド") + (tr(" · 絞り込み中") if active else ""))
        self.filter_reset.setEnabled(active)
        self.update_summary()

    def filter_changed(self):
        if not self.busy() and not self.saving:
            self.guard(self.apply_filter)
            if self.pending_action is None and not self.saving and self.proxy.label != self.filter_combo.currentData():
                self.filter_combo.blockSignals(True)
                self.filter_combo.setCurrentIndex(self.filter_combo.findData(self.proxy.label))
                self.filter_combo.blockSignals(False)

    def tag_filter_changed(self):
        if self.busy() or self.saving:
            return
        self.guard(self.apply_filter)

    def refresh_tag_filter(self):
        """The tag choices follow the tags of the list; a tag no longer used stops filtering."""
        current = self.proxy.tag
        known = self.model.known_tags()
        self.tag_combo.blockSignals(True)
        self.tag_combo.clear()
        self.tag_combo.addItem(tr("すべてのタグ"), None)
        for tag in known:
            self.tag_combo.addItem("#" + tag, tag)
        index = self.tag_combo.findData(current) if current is not None else 0
        self.tag_combo.setCurrentIndex(max(0, index))
        self.tag_combo.setEnabled(bool(known))
        self.tag_combo.blockSignals(False)
        if current is not None and index < 0:
            self.apply_filter()

    def apply_filter(self):
        selection = self.list.selectionModel()
        selection.blockSignals(True)
        self.proxy.tag = self.tag_combo.currentData()
        self.proxy.label = self.filter_combo.currentData()
        self.proxy.text = self.search.text().strip()
        self.proxy.refresh()
        selection.blockSignals(False)
        self.ensure_visible_current()
        self.update_controls()

    def ensure_visible_current(self, preferred=None):
        visible = self.visible_paths()
        path = self.document.path if self.document else None
        if preferred in visible:
            self.request_index(self.model.rows[preferred])
        elif path in visible:
            self._select_current()
        elif visible:
            self.request_index(self.model.rows[visible[0]])
        else:
            self.document = None
            self.index = -1
            self.list.clearSelection()
            self.canvas.set_document(None)
            self.position_label.show_message(tr("該当する画像はありません"))
            self.image_size_label.clear()
            self.update_controls()

    def update_library_view(self):
        if not hasattr(self, "list"):
            return
        grid = self.view_combo.currentIndex() == 1
        for index, button in enumerate(getattr(self, "view_buttons", [])):
            button.setChecked(index == self.view_combo.currentIndex())
        size = self.thumbnail_size.value()
        self.model.grid_size = size if grid else 0
        self.library_delegate.grid = grid
        self.list.setViewMode(QListView.ViewMode.IconMode if grid else QListView.ViewMode.ListMode)
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setMovement(QListView.Movement.Static)
        self.list.setIconSize(QSize(size, size) if grid else LIST_ICON)
        compact = grid and size < COMPACT_GRID
        self.list.setGridSize(QSize(size + 12, size + 12) if compact else QSize(size + 20, size + 62) if grid else QSize())
        self.list.doItemsLayout()
        self.thumbnail_size.setEnabled(grid)
        if grid and not compact and self.splitter.sizes()[0] < 350:
            sizes = self.splitter.sizes()
            self.splitter.setSizes([460, max(280, sum(sizes) - 460 - sizes[2]), sizes[2]])
        if self.filter_popover.isVisible():
            # The panel may have widened; keep the popover open under its button.
            self.filter_popover.show_for(self.filter_button, align_right=False)
        self._select_current()

    def reorder_selection(self, raw_paths, before):
        if self.busy() or self.saving:
            return
        selected = {Path(path) for path in raw_paths}
        moving = [path for path in self.model.paths if path in selected]
        if not moving or (before and Path(before) in selected):
            return
        previous = list(self.model.paths)
        remaining = [path for path in previous if path not in selected]
        position = remaining.index(Path(before)) if before and Path(before) in remaining else len(remaining)
        self.operation_history.append(("order", previous))
        self.sort_combo.blockSignals(True)
        self.sort_combo.setCurrentIndex(self.sort_combo.findData("manual"))
        self.sort_combo.blockSignals(False)
        self.replace_list(remaining[:position] + moving + remaining[position:])
        self.select_paths(moving)

    def select_paths(self, paths):
        selection = self.list.selectionModel()
        selection.clearSelection()
        for path in paths:
            index = self.proxy.mapFromSource(self.model.index(self.model.rows[path]))
            if index.isValid():
                selection.select(index, QItemSelectionModel.SelectionFlag.Select)

    def label_index(self, path):
        if path.parent not in self.label_indexes:
            self.label_indexes[path.parent] = ReviewLabels(path.parent)
        return self.label_indexes[path.parent]

    def apply_review_label(self, label):
        if not self.document or self.busy() or self.saving:
            self.update_controls()
            return
        paths = self.selected_paths() or [self.document.path]
        before = {path: self.model.labels.get(path) for path in paths}
        visible = self.visible_paths()
        current = self.document.path
        successor = None
        if current in visible:
            successor = next((path for path in visible[visible.index(current) + 1:] if path not in paths), None)
        self.write_labels(dict.fromkeys(paths, label), before)
        if all(self.model.labels.get(path) == label for path in paths):
            targets = self.label_folder_targets(paths, label)
            if targets:
                # Moving the shown image away also moves on to the next one.
                self.move_to_folders(targets, create=True)
                return
            if len(paths) == 1 and self.auto_advance.isChecked() and successor:
                self.guard(lambda: self.ensure_visible_current(successor))
            elif current not in self.visible_paths():
                self.guard(lambda: self.ensure_visible_current(successor))

    def label_folder_targets(self, paths, label):
        """{path: label folder} when 「ラベルのフォルダーへ自動で振り分ける」 is on (never for removing a label)."""
        if label is None or not self.auto_sort_action.isChecked():
            return {}
        targets = {path: label_folder_target(path, label) for path in paths}
        return {path: folder for path, folder in targets.items() if folder is not None}

    def library_action_buttons(self):
        return (self.export_accepted_button, self.batch_delete_button, self.reset_labels_button)

    def arrange_library_actions(self, wide):
        """2×2 beside the count when there is room; one column when the panel is narrow."""
        if wide == self.library_actions_wide:
            return
        self.library_actions_wide = wide
        grid = self.library_actions
        for widget in (self.library_title, *self.library_action_buttons()):
            grid.removeWidget(widget)
        if wide:
            grid.addWidget(self.library_title, 0, 0)
            grid.addWidget(self.export_accepted_button, 0, 1)
            grid.addWidget(self.batch_delete_button, 1, 0)
            grid.addWidget(self.reset_labels_button, 1, 1)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
        else:
            for row, widget in enumerate((self.library_title, self.batch_delete_button, self.export_accepted_button, self.reset_labels_button)):
                grid.addWidget(widget, row, 0, 1, 2)

    def update_library_actions_layout(self, width=None):
        width = self.library_panel.width() if width is None else width
        left = max(self.library_title.minimumSizeHint().width(), self.batch_delete_button.sizeHint().width())
        right = max(self.export_accepted_button.sizeHint().width(), self.reset_labels_button.sizeHint().width())
        self.arrange_library_actions(width >= left + right + self.library_actions.horizontalSpacing() + 24)

    def selected_or_current(self):
        return self.selected_paths() or ([self.document.path] if self.document else [])

    def reset_whole_list(self):
        """Return this tab to its initial state, as far as it can be.

        Overwritten images whose originals were kept this run get their exact
        original files back; the shown image loses its edits and mask (undoable);
        labels, the manual order, filters and the search are cleared. Edits saved
        before this run and overwrites without a kept original can't be undone.
        """
        if self.busy() or self.saving or not self.model.paths:
            return
        paths = list(self.model.paths)

        def expected(path):
            return self.documents[path].source_digest if path in self.documents else self.owned.get(path)

        restorable = [path for path in paths if originals().has(path) and expected(path) is not None]
        document = self.document
        current_edits = document is not None and document.path not in restorable and (document.edited or document.dirty)
        labelled = {path: self.model.labels[path] for path in paths if self.model.labels.get(path)}
        noted = {path: self.model.notes[path] for path in paths if self.model.notes.get(path)}
        tagged = {path: self.model.tags[path] for path in paths if self.model.tags.get(path)}
        dialog = QMessageBox(self)
        dialog.setWindowTitle(tr("一覧を初期状態に戻す"))
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setTextFormat(Qt.TextFormat.RichText)
        dialog.setText(html_text(tr("このタブの画像 {count} 枚を初期状態に戻しますか？").format(count=len(paths))))
        rows = [(tr("元画像に戻す"), tr("{count}枚（この起動中に残した元画像）").format(count=len(restorable))),
                (tr("表示中の画像"), tr("加工とマスクを消す") if current_edits else ""),
                (tr("ラベル"), tr("{count}枚から外す").format(count=len(labelled))),
                (tr("メモ"), tr("{count}枚から消す").format(count=len(noted)) if noted else ""),
                (tr("タグ"), tr("{count}枚から外す").format(count=len(tagged)) if tagged else ""),
                (tr("一覧"), tr("名前順に並べ、絞り込みと検索を解除"))]
        dialog.setInformativeText(fact_table(rows, [tr("元画像に戻したファイルは「元に戻す」で取り消せません。")]))
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        dialog.button(QMessageBox.StandardButton.Ok).setText(tr("初期状態に戻す"))
        dialog.button(QMessageBox.StandardButton.Cancel).setText(tr("キャンセル"))
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        dialog.setEscapeButton(QMessageBox.StandardButton.Cancel)
        if not self.confirm_dialog(dialog) or self.busy() or self.saving:
            return
        self.autosave_timer.stop()
        # The list: labels (undoable with 整理を戻す), filters and search, then name order.
        if labelled:
            self.write_labels(dict.fromkeys(labelled, None), labelled)
        for path, text in noted.items():  # each can be brought back with 整理を戻す
            try:
                self.label_index(path).set_note(path, "")
            except (OSError, ValueError):
                continue
            self.model.set_note(path, "")
            self.operation_history.append(("note", (path, text)))
        if tagged:
            self.write_tags(dict.fromkeys(tagged, ()), tagged)
        self.reset_filters()
        if self.sort_combo.currentIndex() != 0:
            self.sort_combo.setCurrentIndex(0)
        self.sort_images()
        # The files: put the kept originals back, exactly.
        restored, failed = [], []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for path in restorable:
                try:
                    originals().restore(path, expected(path))
                    restored.append(path)
                except (ImageProblem, OSError):
                    failed.append(path)
        finally:
            QApplication.restoreOverrideCursor()
        for path in restored:
            self.documents.pop(path, None)
            self.owned.pop(path, None)
            self.model.cache.pop(path, None)
            self.model.state(path, "")
        message = tr("一覧を初期状態に戻しました · 元画像に戻した画像 {count}枚").format(count=len(restored))
        if failed:
            message += tr(" · 戻せなかった画像 {count}枚（ほかのアプリで変更されたなど）").format(count=len(failed))
        self.update_controls()
        self.info(message)
        if document is not None and document.path in restored and document.path in self.model.rows:
            self.document = None
            self.after_load_message = message
            self._load_index(self.model.rows[document.path])
        elif current_edits and self.document is document:
            self.reset_document_edits(document)

    def reset_review_labels(self):
        """Return every labelled image in this tab to 未判定 after confirmation (undoable)."""
        if self.busy() or self.saving:
            return
        labelled = {path: self.model.labels[path] for path in self.model.paths if self.model.labels.get(path)}
        if not labelled:
            self.info(tr("リセットする仕分けはありません。"))
            return
        if not self.confirm_label_reset(labelled) or self.busy() or self.saving:
            return
        labelled = {path: label for path, label in labelled.items() if path in self.model.rows}
        current = self.document.path if self.document else None
        self.write_labels(dict.fromkeys(labelled, None), labelled)
        if all(self.model.labels.get(path) is None for path in labelled):
            key = self.shortcut_hint("undo_organize")
            self.info(tr("仕分けをリセットしました · {count}枚（").format(count=len(labelled)) + (tr("{key}で戻せます）").format(key=key) if key else tr("「直前の整理操作を戻す」で戻せます）")))
        if current is not None and current not in self.visible_paths():
            # A label filter may now hide the current image; follow the filter as labelling does.
            self.guard(self.ensure_visible_current)

    def confirm_label_reset(self, labelled):
        counts = Counter(labelled.values())
        dialog = QMessageBox(self)
        dialog.setWindowTitle(tr("仕分けのリセットを確認"))
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setTextFormat(Qt.TextFormat.RichText)
        dialog.setText(html_text(tr("このタブの画像 {count} 枚の仕分けを解除しますか？").format(count=len(labelled))))
        key = self.shortcut_hint("undo_organize")
        rows = [(tr("未判定に戻す"), " · ".join(tr("{text} {counts} 枚").format(text=text, counts=counts[label])
                                              for label, text in REVIEW_LABELS.items() if counts[label])),
                (tr("対象"), tr("このタブの一覧全体（選択・絞り込みに関係なく）")),
                (tr("変わらないもの"), tr("画像・メモ・保存記録")),
                (tr("取り消し"), tr("直後なら「直前の整理操作を戻す」") + (tr("（{key}）").format(key=key) if key else ""))]
        dialog.setInformativeText(fact_table(rows))
        dialog.setDetailedText("\n".join(f"{REVIEW_LABELS[label]}\t{path}" for path, label in labelled.items()))
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        dialog.button(QMessageBox.StandardButton.Ok).setText(tr("リセット"))
        dialog.button(QMessageBox.StandardButton.Cancel).setText(tr("キャンセル"))
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        dialog.setEscapeButton(QMessageBox.StandardButton.Cancel)
        return self.confirm_dialog(dialog)

    def write_labels(self, values, history=None):
        grouped = defaultdict(dict)
        for path, label in values.items():
            grouped[path.parent][path] = label
        changed = {}
        selection = self.list.selectionModel()
        selection.blockSignals(True)
        try:
            for folder, updates in grouped.items():
                index = self.label_index(next(iter(updates)))
                if len(updates) == 1:
                    path, label = next(iter(updates.items()))
                    index.set(path, label)
                else:
                    index.set_many(updates)
                for path, label in updates.items():
                    self.model.set_label(path, label)
                    changed[path] = history[path] if history is not None else None
        except OSError:
            self.error(tr("ラベルを保存できませんでした。管理記録の保存先の空き容量とアクセス権を確認してください。"))
        else:
            labels = set(values.values())
            if labels == {None}:
                self.info(tr("ラベルを外しました · {count}枚").format(count=len(values)))
            elif len(labels) == 1 and history is not None:
                self.info(tr("「{REVIEW_LABELS}」を付けました · {count}枚").format(REVIEW_LABELS=REVIEW_LABELS[next(iter(labels))], count=len(values)))
            else:
                self.info(tr("ラベルを元に戻しました · {count}枚").format(count=len(values)))
        finally:
            selection.blockSignals(False)
        if history is not None and changed:
            self.operation_history.append(("labels", changed))
        self.update_controls()

    def write_tags(self, values, history=None, message=None):
        """{path: tags} into each folder's records; ``history`` (the tags before) makes it undoable."""
        grouped = defaultdict(dict)
        for path, tags in values.items():
            grouped[path.parent][path] = tags
        written = {}
        try:
            for folder, updates in grouped.items():
                self.label_index(next(iter(updates))).set_tags(updates)
                for path, tags in updates.items():
                    self.model.set_tags(path, tags)
                    written[path] = history[path] if history is not None else None
        except (OSError, ValueError):
            self.error(tr("タグを保存できませんでした。管理記録の保存先の空き容量とアクセス権を確認してください。"))
        else:
            self.info(message or tr("タグを変更しました · {count}枚").format(count=len(values)))
        if history is not None and written:
            self.operation_history.append(("tags", written))
        self.refresh_tag_filter()
        if self.proxy.tag is not None:
            self.apply_filter()
        self.update_controls()

    def edit_tags(self):
        paths = self.selected_or_current()
        if not paths or self.busy() or self.saving:
            return
        from .tag_dialog import TagDialog
        current = {path: self.model.tags.get(path, ()) for path in paths}
        dialog = TagDialog(current, self.model.known_tags(), self)
        if not self.confirm_dialog(dialog, accepted=QDialog.DialogCode.Accepted) or self.busy() or self.saving:
            return
        changed = {path: tags for path, tags in dialog.result_tags().items() if path in self.model.rows}
        if changed:
            self.write_tags(changed, {path: current[path] for path in changed})

    # --- オリジナルタグ: tags the user keeps as buttons below the labels ---------------------------

    def build_quick_tag_buttons(self):
        for button in self.quick_tag_buttons:
            self.quick_tag_grid.removeWidget(button)
            button.deleteLater()
        self.quick_tag_buttons = []
        for number, tag in enumerate(self.quick_tags):
            button = QPushButton()
            button.setObjectName("toggle")
            button.setCheckable(True)
            button.setProperty("tag", tag)
            button.setAccessibleName(tag)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.setText(button.fontMetrics().elidedText(tag, Qt.TextElideMode.ElideRight, 80))
            button.clicked.connect(lambda checked=False, index=number: self.press_quick_tag(index))
            self.quick_tag_grid.addWidget(button, *divmod(number, 3))
            self.quick_tag_buttons.append(button)
        for column in range(3):
            self.quick_tag_grid.setColumnStretch(column, 1)
        if hasattr(self, "bindings"):
            self.update_quick_tag_hints()

    def update_quick_tag_hints(self):
        for number, button in enumerate(self.quick_tag_buttons):
            key = self.shortcut_hint(QUICK_TAG_COMMANDS[number]) if number < len(QUICK_TAG_COMMANDS) else ""
            button.setToolTip((key + " · " if key else "") +
                              tr("「{tag}」を付け外しします。複数選択した画像にはまとめて付けます。").format(tag=button.property("tag")))

    def update_quick_tag_states(self, enabled):
        paths = [path for path in self.selected_or_current() if path in self.model.rows] if enabled else []
        for button in self.quick_tag_buttons:
            tag = str(button.property("tag")).casefold()
            button.setEnabled(enabled)
            button.setChecked(bool(paths) and all(tag in {value.casefold() for value in self.model.tags.get(path, ())}
                                                  for path in paths))
        self.quick_tag_edit.setEnabled(not self.busy() and not self.saving)

    def press_quick_tag(self, index):
        """Add the button's tag to the chosen images, or take it off when they all have it."""
        if self.busy() or self.saving or not self.document:
            return
        if index >= len(self.quick_tags):
            self.info(tr("オリジナルタグ{number}はまだありません。「編集」で追加できます。").format(number=index + 1))
            return
        tag = self.quick_tags[index]
        key = tag.casefold()
        if "quick_tags" not in self.preferences.data:
            # Keep the buttons as they are now: the default is named in the current language, and a later
            # change of language must not rename the button away from the tags already given (issue #3).
            try:
                self.preferences.save({**self.preferences.data, "quick_tags": list(self.quick_tags)})
            except OSError:
                pass
        current = {path: self.model.tags.get(path, ()) for path in self.selected_or_current() if path in self.model.rows}
        if not current:
            return
        remove = all(key in {value.casefold() for value in tags} for tags in current.values())
        changed = {}
        for path, tags in current.items():
            new = clean_tags([value for value in tags if value.casefold() != key] if remove else [*tags, tag])
            if not remove and key not in {value.casefold() for value in new}:
                self.error(tr("タグは1枚に{count}個までです。").format(count=MAX_TAGS))
                return
            if new != tags:
                changed[path] = new
        if changed:
            message = (tr("「{tag}」を外しました · {count}枚") if remove else tr("「{tag}」を付けました · {count}枚")).format(tag=tag, count=len(changed))
            self.write_tags(changed, {path: current[path] for path in changed}, message)

    def edit_quick_tags(self):
        if self.busy() or self.saving:
            return
        from .tag_dialog import QuickTagDialog
        dialog = QuickTagDialog(self.quick_tags, self)
        if not self.confirm_dialog(dialog, accepted=QDialog.DialogCode.Accepted) or self.busy() or self.saving:
            return
        tags, renames = dialog.chosen()
        data = dict(self.preferences.data)
        data["quick_tags"] = tags
        try:
            self.preferences.save(data)
        except OSError:
            self.error(tr("設定を保存できません。設定の保存先を確認してください。"))
            return
        host = self.workspace_host
        for page in [self] if host is None else [host.welcome, *host.workspaces()]:
            page.quick_tags = list(tags)
            page.build_quick_tag_buttons()
            page.update_controls()
        if renames and dialog.rename_existing.isChecked():
            folded = {old.casefold(): new for old, new in renames.items()}
            current = {path: values for path, values in self.model.tags.items()
                       if path in self.model.rows and any(value.casefold() in folded for value in values)}
            changed = {path: clean_tags([folded.get(value.casefold(), value) for value in values]) for path, values in current.items()}
            changed = {path: values for path, values in changed.items() if values != current[path]}
            if changed:
                self.write_tags(changed, {path: current[path] for path in changed},
                                tr("オリジナルタグを保存し、タグの名前を変えました · {count}枚").format(count=len(changed)))
                return
        self.info(tr("オリジナルタグを保存しました。"))

    def edit_note(self):
        if not self.document or self.busy() or self.saving:
            return
        path = self.document.path
        previous = self.label_index(path).note(path)
        text, accepted = QInputDialog.getMultiLineText(self, tr("画像のメモ（最大4000文字）"), path.name, previous)
        if accepted:
            try:
                self.label_index(path).set_note(path, text)
            except (OSError, ValueError):
                self.error(tr("メモを保存できません。文字数・フォルダーのアクセス権を確認してください。"))
                return
            self.operation_history.append(("note", (path, previous)))
            self.model.set_note(path, text)
            self.info(tr("メモを保存しました。一覧の画像にマウスを置くと読めます。"))
            self.update_controls()

    def undo_organization(self):
        if self.busy() or self.saving or not self.operation_history:
            return
        kind, value = self.operation_history[-1]
        if kind == "rename":
            mapping, digests = value
            try:
                if any(file_digest(path) != digest for path, digest in digests.items()):
                    raise ImageProblem(tr("名前変更後に画像が変更されています。元の名前へ戻せません。"))
            except OSError:
                self.error(tr("名前変更後の画像を確認できません。"))
                return
            except ImageProblem as error:
                self.error(str(error))
                return
            self.rename_paths(mapping, undoing=True)
            return
        if kind == "move":
            self.operation_history.pop()
            self.undo_move(value)
            self.update_controls()
            return
        self.operation_history.pop()
        if kind == "labels":
            self.write_labels(value)
            if any(self.model.labels.get(path) != label for path, label in value.items()):
                self.operation_history.append((kind, value))
            self.guard(self.ensure_visible_current)
        elif kind == "order":
            self.sort_combo.blockSignals(True)
            self.sort_combo.setCurrentIndex(self.sort_combo.findData("manual"))
            self.sort_combo.blockSignals(False)
            previous = [path for path in value if path in self.model.rows]
            known = set(previous)
            self.replace_list(previous + [path for path in self.model.paths if path not in known])
        elif kind == "tags":
            self.write_tags(value)
        elif kind == "note":
            path, text = value
            try:
                self.label_index(path).set_note(path, text)
                self.model.set_note(path, text)
            except OSError:
                self.operation_history.append((kind, value))
                self.error(tr("メモを元に戻せませんでした。"))
        self.update_controls()

    def export_labels(self):
        """Move (default) or copy the images of a label, or of each label, into label folders."""
        if self.busy() or self.saving:
            return
        counts = Counter(self.model.labels.get(path) for path in self.model.paths)
        counts = {label: counts[label] for label in REVIEW_LABELS}
        labelled = [path for path in self.model.paths if self.model.labels.get(path) in REVIEW_LABELS]
        if not labelled:
            self.info(tr("ラベルを付けた画像がありません。"))
            return
        from .output_dialogs import LabelExportDialog
        dialog = LabelExportDialog(counts, self.default_new_folder_parent(labelled), self.format_combo.currentData(), self)
        if not self.confirm_dialog(dialog, accepted=QDialog.DialogCode.Accepted) or self.busy() or self.saving:
            return
        try:
            destinations = dialog.destinations()
        except ImageProblem as error:
            self.error(str(error))
            return
        groups = {label: [path for path in self.model.paths if self.model.labels.get(path) == label and path in self.model.rows]
                  for label in destinations}
        groups = {label: paths for label, paths in groups.items() if paths}
        names = {}
        if dialog.renumber.isChecked():
            for paths in groups.values():
                names.update(zip(paths, sequence_stems(len(paths))))
        if not groups:
            return
        if dialog.moving():
            self.move_labelled(groups, destinations, names or None)
        else:
            # Exports include unsaved edits; nothing needs saving first.
            folders = {path: destinations[label] for label, paths in groups.items() for path in paths}
            self._start_batch(paths=list(folders), export_folder=folders, names=names or None, format=dialog.format())

    def default_new_folder_parent(self, paths):
        """The folder of the open workspace (or of the first image) for 「現在のフォルダー内」."""
        folders = [Path(raw) for raw in self.workspace_inputs if Path(raw).is_dir()]
        folder = folders[0] if folders else paths[0].parent
        if self.is_clipboard_path(folder / "image.png"):
            # Never write user output into the private clipboard store.
            pictures = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
            return Path(pictures) if pictures else Path.home()
        return folder

    def save_selected(self):
        paths = self.selected_paths()
        if paths and not self.busy() and not self.saving:
            self.guard(lambda: self._start_batch(paths=paths))

    def compare_images(self):
        paths = self.selected_paths()
        if len(paths) > MAX_COMPARE:
            QMessageBox.warning(self, tr("比較する枚数が多すぎます"), tr("並べて比較できるのは{MAX_COMPARE}枚までです。{MAX_COMPARE}枚以下にしてください。").format(MAX_COMPARE=MAX_COMPARE))
            return
        if len(paths) < 2:
            visible = self.visible_paths()
            if not self.document or len(visible) < 2:
                self.info(tr("比較する画像を2枚以上選択してください（Ctrl / Shift + クリック）。"))
                return
            current = visible.index(self.document.path) if self.document.path in visible else 0
            paths = [visible[current], visible[(current + 1) % len(visible)]]
        self.start_comparison(paths)

    def start_comparison(self, paths):
        if self.busy() or self.saving:
            return
        snapshots = {path: self.documents[path].image.copy() for path in paths if path in self.documents}
        self.finalizing = True
        self.update_controls()
        def process(cancel):
            images = []
            for path in paths:
                check_cancel(cancel)
                images.append(snapshots[path] if path in snapshots else self.review_pixels(path))
            return images
        def done(images):
            self.finalizing = False
            self.update_controls()
            dialog = ComparisonDialog(paths, images, self)
            dialog.exec()
        def failed(message):
            self.finalizing = False
            self.error(message)
        self.run_job(process, done, failed)

    def review_pixels(self, path):
        index = self.source_index(path) if self.overwrite.isChecked() else self.receipts
        record = index.get(path, overwrite=self.overwrite.isChecked()) if index else None
        if record:
            target = index.folder / record["name"]
            if target.is_file() and file_digest(target).hex() == record["digest"]:
                return load_image(target)
        return load_image(path)

    def analyze_duplicates(self):
        if self.busy() or self.saving:
            return
        paths = list(self.model.paths)
        self.begin_batch_progress(len(paths))
        self.info(tr("同じ内容の画像を検査中…"))
        def done(result):
            self.batch_job = None
            self.update_controls()
            groups, errors = result
            self.show_duplicate_groups(groups, errors)
        def failed(message):
            self.batch_job = None
            self.error(message)
        self.batch_job = self.run_job(lambda cancel, report: find_duplicates(paths, cancel=cancel, progress=report),
                                      done, failed, progress=self.update_batch_progress)
        self.batch_job.signals.cancelled.connect(lambda: failed(tr("画像の検査を中止しました。")))
        self.update_controls()

    def show_duplicate_groups(self, groups, errors):
        if not groups:
            self.info(tr("重複している画像はありません") + (tr(" · 読み込めない画像 {count}枚").format(count=len(errors)) if errors else ""))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("重複を削除"))
        dialog.resize(720, 500)
        layout = QVBoxLayout(dialog)
        intro = QLabel(tr("内容が完全に同じ画像が {count} 組あります。チェックした画像をごみ箱へ移します。\n各組の1枚目（一覧で先にある画像）を残す設定にしています。").format(count=len(groups)))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        tree = QTreeWidget()
        tree.setHeaderLabels([tr("画像"), tr("場所")])
        tree.setRootIsDecorated(True)
        order = {path: number for number, path in enumerate(self.model.paths)}
        items = []
        for number, group in enumerate(groups, 1):
            group = sorted(group, key=lambda path: order.get(path, len(order)))
            parent = QTreeWidgetItem(tree, [tr("{number}組目 · {count}枚").format(number=number, count=len(group)), ""])
            parent.setFlags(parent.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            for position, path in enumerate(group):
                item = QTreeWidgetItem(parent, [path.name, str(path.parent)])
                item.setData(0, Qt.ItemDataRole.UserRole, str(path))
                item.setCheckState(0, Qt.CheckState.Unchecked if position == 0 else Qt.CheckState.Checked)
                items.append((item, parent))
            parent.setExpanded(True)
        tree.resizeColumnToContents(0)
        layout.addWidget(tree, 1)
        if errors:
            note = QLabel(tr("読み込めず検査できなかった画像：{count}枚").format(count=len(errors)))
            note.setObjectName("faint")
            layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        remove = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("キャンセル"))
        def checked():
            return [Path(item.data(0, Qt.ItemDataRole.UserRole)) for item, _ in items if item.checkState(0) == Qt.CheckState.Checked]
        def refresh(*_args):
            chosen = checked()
            # Never remove every copy of a picture.
            whole = [parent for parent in {id(p): p for _, p in items}.values()
                     if all(parent.child(i).checkState(0) == Qt.CheckState.Checked for i in range(parent.childCount()))]
            remove.setEnabled(bool(chosen) and not whole)
            remove.setText(tr("{count}枚をごみ箱へ移す").format(count=len(chosen)))
            remove.setToolTip(tr("各組で最低1枚は残してください。") if whole else "")
        tree.itemChanged.connect(refresh)
        refresh()
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if not self.confirm_dialog(dialog, accepted=QDialog.DialogCode.Accepted):
            return
        chosen = [path for path in checked() if path in self.model.rows]
        if chosen and not self.busy() and not self.saving:
            action = lambda: self.trash_images(chosen)
            if self.document and self.document.path in chosen:
                self.guard(action)
            else:
                action()

    def trash_images(self, paths, done=None):
        """Move files to the recycle bin (never delete permanently) and drop them from the list."""
        moved, failed = [], []
        for path in paths:
            if path in self.documents and self.documents[path].dirty and self.document is not self.documents[path]:
                failed.append(path)
                continue
            (moved if QFile.moveToTrash(str(path)) else failed).append(path)
        if moved:
            self.exclude_from_list(moved, message=False)
            self.excluded_paths.difference_update(moved)
        text = (done or tr("重複をごみ箱へ移しました · {count}枚")).format(count=len(moved))
        if failed:
            self.error(text + tr(" / 移せなかった画像 {count}枚（ごみ箱のない場所や、使用中のファイル）").format(count=len(failed)))
        else:
            self.report(text)

    def poll_folders(self):
        self.sync_watch_scope()
        if self.closing or not self.watch_action.isChecked() or self.busy() or self.saving or self.canvas.stroke:
            return
        if self.watch_pending:
            # A deferred file may have changed again while editing or saving.
            # Recheck its signature in the worker before adding it to the list.
            self.watch_pending.clear()
            self.watch_monitor.changed()
        self.watch_monitor.poll(set(self.model.rows) | self.excluded_paths)

    def sync_watch_scope(self):
        scope = self.watched_folders if self.watch_action.isChecked() and not self.closing else set()
        if scope != self.watch_monitor.folders:
            self.watch_pending.clear()
        self.watch_monitor.set_scope(scope)

    def accept_watched_images(self, stable):
        if self.closing or not self.watch_action.isChecked():
            self.watch_pending.clear()
            return
        stable = set(stable)
        if self.busy() or self.saving or self.canvas.stroke:
            self.watch_pending = stable
            return
        self.watch_pending = set()
        paths = list(self.model.paths)
        additions = sorted(path for path in stable if path not in self.model.rows and path not in self.excluded_paths)
        if not additions:
            return
        self.replace_list(paths + additions)
        for path in additions:
            index = self.label_index(path)
            if index.get(path):
                self.model.set_label(path, index.get(path))
        self.update_summary()
        if not self.document:
            self.ensure_visible_current()
        self.info(tr("新しい画像を追加しました · {count}枚").format(count=len(additions)))

    def workspace_key(self, inputs):
        return hashlib.sha256(json.dumps(sorted(str(Path(raw).resolve()) for raw in inputs)).encode()).hexdigest()

    def saved_workspace(self, inputs):
        workspaces = self.preferences.data.get("workspaces", {})
        value = workspaces.get(self.workspace_key(inputs), {}) if isinstance(workspaces, dict) else {}
        return value if isinstance(value, dict) else {}

    def workspace_settings(self):
        return {
            "auto": self.auto.isChecked(), "overwrite": self.overwrite.isChecked(),
            "mode": self.mode, "strengths": {**self.mode_strengths, self.mode: self.strength.value()}, "brush": self.brush.value(),
            "color": self.color, "shape": self.shape_combo.currentData(), "expansion": self.expansion.value(),
            "format": self.format_combo.currentData(), "output": str(self.output_folder) if self.custom_folder else None,
            "auto_advance": self.auto_advance.isChecked(), "auto_sort": self.auto_sort_action.isChecked(), "grid": self.view_combo.currentIndex(),
            "thumbnail": self.thumbnail_size.value(), "watch": self.watch_action.isChecked(),
            "novelai_adjust": self.novelai_adjust.isChecked(), "novelai_metadata": self.novelai_metadata.isChecked(),
            "show_mask": self.mask_toggle.isChecked(),
            "metadata_backup": self.metadata_backup.isChecked(),
            "strip_metadata": self.strip_metadata.isChecked(),
            "keep_originals": self.keep_originals.isChecked(),
            "jpeg_quality": self.jpeg_quality,
            "inverse_selection": self.inverse_action.isChecked(),
            "navigator": self.navigator_action.isChecked(),
            "text": self.text_style.to_settings(),
            "quick_tags_open": self.quick_tag_toggle.isChecked(),
        }

    def workspace_state(self, *, session=False):
        if self.deferred_session is not None:
            value = dict(self.deferred_session.get("workspace", {}))
            if not session:
                value.pop("search", None)
                value.pop("excluded", None)
            return value
        value = {"order": [str(path) for path in self.model.paths],
                 "current": str(self.document.path) if self.document else None,
                 "filter": self.filter_combo.currentData(), "sort": self.sort_combo.currentData()}
        # The tab name belongs to the folder the tab opened, not to folders browsed inside it.
        at_root = self.folder_root is None or self.browsed_folder() == self.folder_root
        if self.custom_title and (at_root or session):
            value["title"] = self.custom_title
        if session:
            value.update(search=self.search.text(), excluded=[str(path) for path in sorted(self.excluded_paths)])
            if self.folder_root is not None:
                value["root"] = str(self.folder_root)
        return value

    def session_state(self):
        return {"inputs": list(self.workspace_inputs), "settings": self.workspace_settings(),
                "workspace": self.workspace_state(session=True)}

    def remember_workspace(self):
        settings = self.workspace_settings()
        data = dict(self.preferences.data)
        workspaces = dict(data.get("workspaces", {})) if isinstance(data.get("workspaces", {}), dict) else {}
        if self.workspace_inputs:
            workspaces[self.workspace_key(self.workspace_inputs)] = self.workspace_state()
        recent = data.get("recent", [])
        recent = [entry for entry in recent if isinstance(entry, list)] if isinstance(recent, list) else []
        if self.workspace_inputs:
            recent = [list(self.workspace_inputs)] + [entry for entry in recent if entry != self.workspace_inputs]
        data.update(settings=settings, workspaces=workspaces, inputs=self.workspace_inputs, recent=recent[:8])
        data["record_folders"] = sorted(str(folder) for folder in self.known_record_folders())
        self.preferences.save(data)

    def restore_settings(self, data=None):
        data = self.preferences.data.get("settings", {}) if data is None else data
        if not isinstance(data, dict):
            return
        if "overwrite" not in data and self.preferences.data:
            # A profile from before the first-run choice (0.4.0) overwrote by default; keep it so.
            data = {**data, "overwrite": True}
        quality = data.get("jpeg_quality", 95)
        self.jpeg_quality = quality if type(quality) is int and 1 <= quality <= 100 else 95
        self.format_combo.setItemText(1, tr("JPEG · 品質{jpeg_quality}・白背景").format(jpeg_quality=self.jpeg_quality))
        for widget, key in [(self.auto, "auto"), (self.overwrite, "overwrite"), (self.auto_advance, "auto_advance"),
                            (self.auto_sort_action, "auto_sort"),
                            (self.watch_action, "watch"), (self.novelai_adjust, "novelai_adjust"), (self.novelai_metadata, "novelai_metadata"), (self.mask_toggle, "show_mask"),
                            (self.metadata_backup, "metadata_backup"), (self.inverse_action, "inverse_selection"),
                            (self.strip_metadata, "strip_metadata"), (self.keep_originals, "keep_originals"),
                            (self.navigator_action, "navigator"), (self.quick_tag_toggle, "quick_tags_open")]:
            if isinstance(data.get(key), bool):
                widget.setChecked(data[key])
        if isinstance(data.get("brush"), int):
            self.brush.setValue(data["brush"])
        mode = data.get("mode", "mosaic")
        if isinstance(mode, str) and mode in self.mode_strengths:
            self.set_mode(mode)
        strengths = data.get("strengths", {})
        if isinstance(strengths, dict):
            for mode in self.mode_strengths:
                value = strengths.get(mode)
                if isinstance(value, int):
                    self.mode_strengths[mode] = max(0 if mode == "fill" else 2, min(100, value))
        self.strength.setValue(self.mode_strengths[self.mode])
        if "text" in data:
            self.text_style = TextStyle.from_settings(data["text"])
        color = data.get("color", "#000000")
        if isinstance(color, str) and len(color) == 7 and color.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in color[1:]):
            self.color = color
            self.update_color_button()
        for combo, key in [(self.shape_combo, "shape"), (self.format_combo, "format")]:
            index = combo.findData(data.get(key))
            if index >= 0:
                combo.setCurrentIndex(index)
        for widget, key, low, high in [(self.view_combo, "grid", 0, 1), (self.thumbnail_size, "thumbnail", 40, 240), (self.expansion, "expansion", 0, 3)]:
            value = data.get(key)
            if isinstance(value, int) and low <= value <= high:
                widget.setCurrentIndex(value) if isinstance(widget, QComboBox) else widget.setValue(value)
        if isinstance(data.get("output"), str):
            self.output_folder = Path(data["output"]).resolve()
            self.custom_folder = True
        else:
            self.output_folder = None
            self.custom_folder = False
        self.tool_changed()
        self.update_controls()

    def resume_workspace(self):
        inputs = self.preferences.data.get("inputs", [])
        if isinstance(inputs, list):
            inputs = [raw for raw in inputs if isinstance(raw, str) and Path(raw).exists()]
            if inputs:
                self.open_inputs(inputs)
