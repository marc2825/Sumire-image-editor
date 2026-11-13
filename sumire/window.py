from __future__ import annotations
from .i18n import LANGUAGES, language, switch_note, tr

from collections import OrderedDict
from pathlib import Path
from time import monotonic
from PIL import Image

from PySide6.QtCore import QEvent, QModelIndex, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QAbstractScrollArea, QAbstractSpinBox, QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSlider,
    QPlainTextEdit, QSplitter, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from .canvas import Canvas
from .export import Cancelled, HiddenMetadata, available_target, check_cancel, detect_format, file_digest, kept_format, load_verified_export, save_image, verify_export
from .imaging import SUPPORTED, Document, ImageProblem, Tool, format_names, load_image, make_effect
from .library import filename_key, scan_paths
from .labels import REVIEW_LABELS, ReviewLabels
from .novelai import NovelAIImportDialog, ImageAdjustmentDialog, prepare_image
from .organize import pending_renames, recover_rename, rename_images, renamed_path, sequence_stems
from .session import Receipts, source_key
from .theme import TOKENS, dark_palette, stylesheet
from .icons import icon, swatch
from .ui import COPYRIGHT, ElidedLabel, fact_table, html_text, install_dialog_tint, slider_with_box, FilenameField, PositionField, Popover, ValueLabel, WelcomePage, ZoomField, attach_key_hint, describe_inputs, divider, key_hint, section_label, tool_button
from .workers import Job
from .workbench import Workbench
from .explorer import configure_context_menu
from .app_features import AppFeatures
from .masks import MaskStore
from .shortcuts import ShortcutDialog, hint, load_bindings, matches
from .editor_features import EditorFeatures
from .output_features import OutputFeatures
from .folder_features import FolderFeatures
from .backups import store as originals
from .metadata import inspect_metadata

# The overwrite notice is shown once per run unless the user hides it for good.
OVERWRITE_NOTICE = {"shown": False}
SHAPE_TIPS = {
    "brush": tr("なぞった線の上に適用します。"),
    "rectangle": tr("ドラッグした長方形の範囲に適用します。"),
    "ellipse": tr("ドラッグした楕円の範囲に適用します。"),
    "polygon": tr("クリックで頂点を追加し、Enterかダブルクリックで適用します。Backspaceで頂点を戻し、Escで中止します。"),
    "lasso": tr("ドラッグして囲みます。線が交わってできた最初の閉じた範囲に、離すと適用します。始点と終点は結びません。Escで中止します。"),
}
BLUR_NOTE = tr("モザイク・ぼかしでは完全には隠せません。確実に隠す箇所は、塗りつぶし（不透明度100%）を使ってください。")
FILL_NOTE = tr("不透明度100%で、元の画素を完全に置き換えます。100%未満では元の画像が透けるので、確実に隠す箇所は100%にしてください。")
# Saving keeps the source's metadata unless the user turns deletion on (or uses the delete button).
STRIP_METADATA_DEFAULT = False
# 「ラベルを付けたら次へ」 starts on.
AUTO_ADVANCE_DEFAULT = True

class Window(FolderFeatures, OutputFeatures, EditorFeatures, AppFeatures, Workbench, QMainWindow):
    closed = Signal(object)
    closeCancelled = Signal()
    stateChanged = Signal()
    pathsRenamed = Signal(object)

    def __init__(self, *, workspace_host=None, preferences=None, persist_on_close=True):
        super().__init__()
        self.workspace_host = workspace_host
        self.shared_preferences = preferences
        self.persist_on_close = persist_on_close
        self.setWindowTitle(tr("Sumīre — 画像の仕上げ"))
        available = QApplication.primaryScreen().availableGeometry()
        self.setMinimumSize(800, 440)
        # Leave room for the native title bar and borders at fractional scaling.
        self.resize(min(1320, available.width() - 32), min(850, available.height() - 64))
        QApplication.instance().setPalette(dark_palette())
        self.setStyleSheet(stylesheet())
        install_dialog_tint(QApplication.instance())
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.jobs: set[Job] = set()
        self.document: Document | None = None
        self.documents: OrderedDict[Path, Document] = OrderedDict()
        self.owned: dict[Path, bytes] = {}
        self.receipts: Receipts | None = None
        self.source_indexes: dict[Path, Receipts] = {}
        self.label_indexes: dict[Path, ReviewLabels] = {}
        self.novelai_job: Job | None = None
        self.novelai_dialog: NovelAIImportDialog | None = None
        self.output_folder: Path | None = None
        self.custom_folder = False
        self.index = -1
        self.loading = False
        self.finalizing = False
        self.saving = False
        self.save_again = False
        self.save_failed = False
        self.save_job: Job | None = None
        self.batch_job: Job | None = None
        self.effect_job: Job | None = None
        self.effect_restart = False
        self.closing = False
        self.pending_action = None
        self.effect_generation = 0
        self.prepared_effect_key = None
        self.pending_effect_key = None
        self.workspace_active = True
        self.color = "#000000"
        self.jpeg_quality = 95
        self.custom_title = None
        self.after_load_message = None
        self.init_workbench()
        self.init_features()
        self.init_folders()
        self.bindings = load_bindings(self.preferences)
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.setInterval(300)
        self.autosave_timer.timeout.connect(self.save)
        self.effect_timer = QTimer(self)
        self.effect_timer.setSingleShot(True)
        self.effect_timer.setInterval(70)
        self.effect_timer.timeout.connect(self.prepare_effect)
        self._build_ui()
        self._shortcuts()
        QApplication.instance().installEventFilter(self)
        # The values the controls were built with: what "設定を初期状態に戻す" returns to.
        self.default_settings = self.workspace_settings()
        self.restore_settings()
        self.update_controls()
        self.refresh_welcome()
        self.move(available.x() + max(0, (available.width() - self.width()) // 2),
                  available.y() + max(0, (available.height() - self.height()) // 2))

    def _button(self, text, handler, tooltip="", primary=False, variant=None):
        button = QPushButton(text)
        button.clicked.connect(handler)
        button.setToolTip(tooltip)
        if primary:
            button.setObjectName("primary")
        if variant:
            button.setProperty("variant", variant)
        return button

    def _action(self, text, handler=None, hint="", checkable=False, tooltip=""):
        # Menus show the key as a hint only; the QShortcut objects own the keys,
        # so the same key is never registered twice (which would disable both).
        action = QAction(f"{text}\t{hint}" if hint else text, self)
        action.setCheckable(checkable)
        if tooltip:
            action.setToolTip(tooltip)
        if handler:
            action.triggered.connect(lambda *_args: handler())
        return action

    @staticmethod
    def _label(text, name="muted"):
        label = QLabel(text)
        label.setObjectName(name)
        label.setWordWrap(True)
        return label

    def _build_actions(self):
        action = self._action
        self.open_folder_action = action(tr("フォルダーを開く…"), self.open_folder, "Ctrl+O")
        self.open_files_action = action(tr("画像を開く…"), self.open_files)
        self.reload_action = action(tr("一覧を再読み込み"), self.reload_workspace, "Ctrl+R")
        self.manual_save = action(tr("保存"), self.save, "Ctrl+S")
        self.metadata_button = action(tr("メタデータを削除して保存"), lambda: self.save(force=True, strip=True),
                                      tooltip=tr("編集を保ったまま、メタデータを削除して現在の保存方法で保存します。"))
        self.metadata_restore = action(tr("メタデータを復元して別名保存…"), self.restore_metadata_copy,
                                       tooltip=tr("退避したメタデータを現在の加工結果に付け、別ファイルに保存します。"))
        self.mask_export = action(tr("加工マスクをPNGで保存…"), self.export_edit_mask,
                                  tooltip=tr("白：加工範囲 / 黒：それ以外"))
        self.reset_edits_action = action(tr("加工・マスクを初期化"), self.reset_edits,
                                         tooltip=tr("加工とマスクを消して元画像に戻します。実行前に確認します。"))
        self.rename_button = action(tr("名前を変更…"), self.rename_current, "F2")
        self.number_button = action(tr("順に連番へ改名（00, 01, 02…）"), self.number_images,
                                    tooltip=tr("一覧に並んでいる順に、桁をそろえた0からの連番へ改名します。実行前に確認します。"))
        self.restore_original_action = action(tr("上書き前の元画像に戻す"), self.restore_original,
                                              tooltip=tr("この起動中に最初に上書きする前の元画像に戻します。実行前に確認します。"))
        self.batch_button = action(tr("全画像のメタデータを一括削除"), self.start_batch,
                                   tooltip=tr("保存済みを含む一覧の全画像からメタデータを削除します。加工は保ちます。"))
        self.novelai_adjust = action(tr("NovelAIへ渡す前に切り抜き・縮小"), checkable=True)
        self.explorer_install = action(tr("右クリックに「Sumīreで開く」を追加"), lambda: self.setup_explorer(False))
        self.explorer_remove = action(tr("右クリックの登録を解除"), lambda: self.setup_explorer(True))
        self.label_actions = {}
        for number, (label, text) in enumerate(REVIEW_LABELS.items(), 1):
            self.label_actions[label] = action(text, lambda value=label: self.toggle_label(value), str(number))
        self.label_actions[None] = action(tr("ラベルを解除"), lambda: self.set_review_label(None), "Alt+0")
        self.create_app_actions()
        self.create_editor_actions()

    def _build_ui(self):
        self._build_actions()
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(root)
        layout.addWidget(self._build_top_bar())
        self.pages = QStackedWidget()
        self.welcome = WelcomePage(self.open_folder, self.open_files)
        self.welcome.filesDropped.connect(self.open_inputs)
        self.welcome.recentRequested.connect(self.open_recent)
        self.welcome.recentRemoved.connect(self.forget_recent)
        self.welcome.saveSettingsRequested.connect(self.show_save_settings)
        self.welcome.languageChosen.connect(self.choose_language)
        self.pages.addWidget(self.welcome)
        splitter = self.splitter = QSplitter()
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.build_library_panel())
        splitter.addWidget(self._build_center())
        splitter.addWidget(self._build_tools_panel())
        # Wide enough for the two whole-tab action buttons to sit side by side.
        splitter.setSizes([372, 668, 280])  # room for the list buttons two by two
        splitter.setStretchFactor(1, 1)
        self.pages.addWidget(splitter)
        layout.addWidget(self.pages, 1)
        layout.addWidget(self._build_status_bar())
        self._build_save_popover()
        self.workspace_widgets = [self.undo_button, self.redo_button, self.save_state, self.metadata_state, self.metadata_delete_button,
                                  self.save_next_button, *self.view_controls]
        self.update_color_button()
        self.tool_changed()
        self.update_library_view()

    def _build_top_bar(self):
        """App-wide controls: Sumīre and the file menu, then the save method, help and settings.

        In the tab window both groups move up into the tab row (``lend_app_controls``)
        and this bar is hidden; the current image's controls sit above the image.
        """
        bar = QFrame()
        bar.setObjectName("topBar")
        self.top_bar = bar
        self.top_row = QHBoxLayout(bar)
        self.top_row.setContentsMargins(16, 8, 12, 8)
        self.top_row.setSpacing(6)
        self.app_left = QWidget()
        row = QHBoxLayout(self.app_left)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        brand = QLabel("Sumīre")
        brand.setObjectName("brand")
        row.addWidget(brand)
        self.build_file_menu(row)
        self.app_right = QWidget()
        row = QHBoxLayout(self.app_right)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.save_mode_button = QToolButton()
        self.save_mode_button.setObjectName("saveMode")
        self.save_mode_button.setProperty("variant", "ghost")
        self.save_mode_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_mode_button.setAccessibleName(tr("保存方法・保存先"))
        self.save_mode_button.clicked.connect(self.show_save_settings)
        row.addWidget(self.save_mode_button)
        self.help_button = tool_button("help", tr("ヘルプ · F1"), self.show_help)
        self.help_button.setAccessibleName(tr("ヘルプ"))
        row.addWidget(self.help_button)
        self.build_app_menu(row)
        self.top_row.addWidget(self.app_left)
        self.top_row.addStretch(1)
        self.top_row.addWidget(self.app_right)
        # The tab already shows the folder's name; the label keeps it for assistive tools only.
        self.workspace_separator = QLabel("/", bar)
        self.workspace_label = ElidedLabel()
        self.workspace_label.setParent(bar)
        self.workspace_label.setTextFormat(Qt.TextFormat.PlainText)
        self.workspace_label.setAccessibleName(tr("現在の作業対象"))
        self.workspace_separator.hide()
        self.workspace_label.hide()
        return bar

    def lend_app_controls(self):
        """Hand the app-wide groups to the tab row; this window's own bar is then empty."""
        return self.app_left, self.app_right

    def take_back_app_controls(self):
        self.top_row.insertWidget(0, self.app_left)
        self.top_row.addWidget(self.app_right)

    def _build_image_bar(self):
        """The shown image's controls, centred above it; two rows when the column is narrow."""
        bar = self.image_bar = QFrame()
        bar.setObjectName("imageBar")
        bar.installEventFilter(self)
        column = QVBoxLayout(bar)
        column.setContentsMargins(10, 4, 10, 4)
        column.setSpacing(4)
        self.image_rows = []
        for _ in range(2):
            row = QHBoxLayout()
            row.setSpacing(6)
            column.addLayout(row)
            self.image_rows.append(row)
        self.undo_button = tool_button("undo", tr("元に戻す · Ctrl+Z"), lambda: self.history(False))
        self.redo_button = tool_button("redo", tr("やり直す · Ctrl+Shift+Z / Ctrl+Y"), lambda: self.history(True))
        self.save_state = QLabel()
        self.save_state.setObjectName("saveState")
        self.save_state.setTextFormat(Qt.TextFormat.RichText)
        self.metadata_state = QToolButton()
        self.metadata_state.setObjectName("metadataState")
        self.metadata_state.setCursor(Qt.CursorShape.PointingHandCursor)
        self.metadata_state.clicked.connect(lambda: self.editor_actions["metadata"].trigger())
        self.metadata_delete_button = QToolButton()
        self.metadata_delete_button.setText(tr("メタデータを削除"))
        self.metadata_delete_button.clicked.connect(self.metadata_button.trigger)
        self.metadata_delete_button.setToolTip(tr("表示中の画像のメタデータを削除し、現在の保存方法で保存します。"))
        self.metadata_delete_button.setAccessibleName(tr("表示中の画像のメタデータを削除"))
        # Light red: it throws away the overwrites of this run for the shown image.
        self.restore_original_button = QToolButton()
        self.restore_original_button.setObjectName("restoreOriginal")
        self.restore_original_button.setText(tr("上書き前に戻す"))
        self.restore_original_button.setAccessibleName(tr("上書き前の元画像に戻す"))
        self.restore_original_button.clicked.connect(self.restore_original_action.trigger)
        self.save_next_button = self._button(tr("保存して次へ →"), self.save_next, tr("Enter · 保存して次の画像へ（未編集でも保存）"), primary=True)
        self.save_next_button.setMinimumHeight(32)
        self.image_state_widgets = [self.undo_button, self.redo_button, self.save_state, self.metadata_state]
        self.image_action_widgets = [self.metadata_delete_button, self.restore_original_button, self.save_next_button]
        self.image_bar_compact = None
        self.arrange_image_bar(False)
        return bar

    def arrange_image_bar(self, compact):
        """One centred row, or the state on one row and the two buttons below it."""
        if compact == self.image_bar_compact:
            return
        self.image_bar_compact = compact
        for row in self.image_rows:
            while row.count():
                row.takeAt(0)
        first, second = self.image_rows
        first.addStretch(1)
        for widget in self.image_state_widgets:
            first.addWidget(widget)
        if compact:
            second.addStretch(1)
        else:
            first.addSpacing(10)
        for widget in self.image_action_widgets:
            (second if compact else first).addWidget(widget)
        first.addStretch(1)
        if compact:
            second.addStretch(1)

    def _build_center(self):
        center = QWidget()
        layout = QVBoxLayout(center)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = self.canvas_header = QFrame()
        header.setObjectName("canvasHeader")
        header.installEventFilter(self)
        row = QHBoxLayout(header)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(4)
        self.previous = tool_button("chevron_left", tr("前の画像 · ←"), lambda: self.navigate(-1))
        self.next = tool_button("chevron_right", tr("次の画像 · →"), lambda: self.navigate(1))
        row.addWidget(self.previous)
        row.addWidget(self.next)
        row.addSpacing(6)
        self.file_label = FilenameField()
        self.file_label.editStarted.connect(self.remember_rename_source)
        self.file_label.renameRequested.connect(self.rename_inline)
        self.file_label.setObjectName("fileName")
        self.file_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.file_label.setMinimumWidth(80)
        row.addWidget(self.file_label, 1)
        self.position_label = PositionField()
        self.position_label.jumpRequested.connect(self.jump_to_image)
        row.addWidget(self.position_label)
        row.addSpacing(12)
        # Hand the edited image (including unsaved edits) to other apps and services.
        self.share_menu = QMenu(self)
        self.share_menu.setToolTipsVisible(True)
        self.share_actions = {}
        for key, text, tip, handler in (
                ("novelai", tr("NovelAIでi2i"), tr("編集結果でNovelAIを開きます。Image2Imageはブラウザーで選びます。"),
                 lambda: self.open_novelai()),
                ("copy", tr("画像をコピー"), tr("編集結果を、メタデータのない画像としてコピーします。投稿欄やチャットに貼り付けられます。"),
                 lambda: self.editor_actions["copy"].trigger()),
                ("drag", tr("ドラッグして渡す"), tr("編集結果をメタデータのないPNGにして、ブラウザーの投稿欄やチャットアプリへドラッグできるようにします。"),
                 lambda: self.open_novelai(target="drag"))):
            action = self.share_menu.addAction(text)
            action.setToolTip(tip)
            action.triggered.connect(handler)
            self.share_actions[key] = action
        self.share_button = self._button(tr("共有…"), lambda: None, tr("編集結果（未保存の変更を含む）を、ほかのアプリやサービスへ渡します。"),
                                         variant="ghost")
        self.share_button.setMenu(self.share_menu)
        self.share_button.setIcon(icon("share"))
        self.share_button.setAccessibleName(tr("共有"))
        row.addWidget(self.share_button)
        # The everyday image commands; rarer ones (超解像 among them) stay one level down.
        self.image_menu = QMenu(self)
        self.image_menu.setToolTipsVisible(True)
        for action in (self.manual_save, self.workflow_actions["save_as"], self.metadata_button,
                       self.editor_actions["metadata"], self.restore_original_action):
            self.image_menu.addAction(action)
        self.image_menu.addSeparator()
        other = self.image_menu.addMenu(tr("その他"))
        other.setToolTipsVisible(True)
        for item in (self.editor_actions["upscale"], None,
                     self.workflow_actions["convert_selected"], self.workflow_actions["compress_selected"], None,
                     self.metadata_restore, None,
                     self.mask_export, self.editor_actions["copy"], self.inverse_action):
            other.addSeparator() if item is None else other.addAction(item)
        self.image_menu_button = tool_button("more", tr("この画像の操作 · 保存・別名で保存・メタデータ・その他"))
        self.image_menu_button.setAccessibleName(tr("この画像の操作"))
        self.image_menu_button.setMenu(self.image_menu)
        self.image_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        row.addWidget(self.image_menu_button)
        layout.addWidget(header)
        layout.addWidget(self._build_image_bar())
        self.canvas = Canvas()
        self.canvas.strokeStarted.connect(self.update_controls)
        self.canvas.strokeCancelled.connect(self.stroke_cancelled)
        self.canvas.lassoNotClosed.connect(lambda: self.info(tr("線が交わって閉じた範囲ができなかったため、適用しませんでした。")))
        self.canvas.strokeFinished.connect(self.finish_stroke)
        self.canvas.filesDropped.connect(self.open_inputs)
        self.canvas.colorPicked.connect(self.picked_color)
        self.canvas.zoomChanged.connect(lambda scale: self.zoom_label.show_scale(scale))
        self.canvas.eraserRequested.connect(self.toggle_eraser)
        self.canvas.maskToggleRequested.connect(lambda: self.mask_toggle.toggle() if self.mask_toggle.isEnabled() else None)
        self.canvas.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.canvas.customContextMenuRequested.connect(self.show_canvas_menu)
        layout.addWidget(self.canvas, 1)
        # Tools for looking at the shown image, centred under it.
        view_bar = self.view_bar = QFrame()
        view_bar.setObjectName("viewBar")
        row = QHBoxLayout(view_bar)
        row.setContentsMargins(10, 4, 10, 4)
        row.setSpacing(6)
        self.crop_tool = tool_button("crop", tr("画像を切り抜く · 切り抜きと寸法の変更"), lambda: self.editor_actions["edit"].trigger(),
                                     text=tr("切り抜き"), variant="ghost")
        self.compare_button = tool_button("compare", tr("押している間、元画像を表示 · Tabでも可"), text=tr("比較"), variant="ghost")
        self.compare_button.pressed.connect(lambda: self.compare(True))
        self.compare_button.released.connect(lambda: self.compare(False))
        self.mask_toggle = tool_button("mask", tr("加工範囲のマスクを表示 · M"), text=tr("マスク"), variant="ghost", checkable=True)
        self.mask_toggle.toggled.connect(self.show_edit_mask)
        row.addStretch(1)
        # The keys of compare and mask, small and faint beside their buttons.
        self.key_hints = getattr(self, "key_hints", {})
        self.key_hints.update(compare=key_hint(), mask=key_hint())
        for widget in (self.crop_tool, self.compare_button, self.key_hints["compare"], self.mask_toggle, self.key_hints["mask"]):
            row.addWidget(widget)
        row.addStretch(1)
        layout.addWidget(view_bar)
        return center

    def _build_tools_panel(self):
        container = QWidget()
        container.setObjectName("panel")
        container.setMinimumWidth(256)
        container.setMaximumWidth(340)
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        right = QWidget()
        right.setObjectName("panel")
        tools = QVBoxLayout(right)
        tools.setContentsMargins(16, 14, 16, 12)
        tools.setSpacing(10)
        tools.addWidget(section_label(tr("編集ツール")))
        segmented = QFrame()
        segmented.setObjectName("segmented")
        mode_row = QHBoxLayout(segmented)
        mode_row.setContentsMargins(3, 3, 3, 3)
        mode_row.setSpacing(2)
        self.mode_buttons = []
        for text, mode, tip in [(tr("モザイク"), "mosaic", BLUR_NOTE), (tr("ぼかし"), "blur", BLUR_NOTE),
                                (tr("塗りつぶし"), "fill", FILL_NOTE)]:
            button = self._button(text, lambda checked=False, m=mode: self.set_mode(m), tip)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setChecked(mode == "mosaic")
            self.mode_buttons.append((mode, button))
            mode_row.addWidget(button)
        tools.addWidget(segmented)
        self.erase_button = self._button(tr("消しゴム"), self.toggle_eraser,
                                         tr("E · なぞった部分を元画像に戻します。もう一度押すと元のツールに戻ります"))
        self.erase_button.setObjectName("toggle")
        self.erase_button.setIcon(icon("eraser"))
        self.erase_button.setCheckable(True)
        self.key_hints = getattr(self, "key_hints", {})
        self.key_hints["eraser"] = attach_key_hint(self.erase_button)
        self.mode_buttons.append(("erase", self.erase_button))
        tools.addWidget(self.erase_button)
        self.reset_edits_button = self._button(tr("加工・マスクを初期化"), self.reset_edits_action.trigger,
                                               self.reset_edits_action.toolTip())
        tools.addWidget(self.reset_edits_button)
        self.mode = "mosaic"
        self.mode_before_erase = "mosaic"
        self.mode_strengths = {"mosaic": 20, "blur": 20, "fill": 100, "erase": 100}
        self.shape_combo = QComboBox()
        for text, value in [(tr("ブラシ"), "brush"), (tr("長方形"), "rectangle"), (tr("楕円"), "ellipse"), (tr("多角形"), "polygon"), (tr("投げ縄"), "lasso")]:
            self.shape_combo.addItem(text, value)
            self.shape_combo.setItemData(self.shape_combo.count() - 1, SHAPE_TIPS[value], Qt.ItemDataRole.ToolTipRole)
        self.shape_combo.setMinimumContentsLength(12)
        self.shape_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.shape_combo.currentIndexChanged.connect(self.tool_changed)
        tools.addWidget(self.shape_combo)
        tools.addSpacing(2)
        # Each slider has a number box beside its name for typing a value directly.
        self.brush_label = ValueLabel()
        self.brush = QSlider(Qt.Orientation.Horizontal)
        self.brush.setRange(4, 600)
        self.brush.setValue(90)
        self.brush.setToolTip(tr("ブラシの直径（元画像のpx） · [ / ]"))
        self.brush.setAccessibleName(tr("ブラシの直径"))
        self.brush.valueChanged.connect(self.tool_changed)
        self.brush_box = slider_with_box(self.brush, " px", tr("ブラシの直径（数値）"))
        tools.addLayout(self._slider_heading(self.brush_label, self.brush_box))
        tools.addWidget(self.brush)
        self.strength_label = ValueLabel()
        self.strength = QSlider(Qt.Orientation.Horizontal)
        self.strength.setRange(2, 100)
        self.strength.setValue(20)
        self.strength.setAccessibleName(tr("モザイクの強さ"))
        self.strength.setToolTip(tr("強さ · , で弱く / . で強く"))
        self.strength.valueChanged.connect(self.tool_changed)
        self.strength_box = slider_with_box(self.strength, " px", tr("強さ（数値）"))
        self.strength_row = self._slider_heading(self.strength_label, self.strength_box)
        tools.addLayout(self.strength_row)
        tools.addWidget(self.strength)
        self.fill_row = QWidget()
        fill = QHBoxLayout(self.fill_row)
        fill.setContentsMargins(0, 0, 0, 0)
        fill.setSpacing(6)
        self.color_button = self._button("#000000", self.choose_color, tr("塗りつぶしの色を選択"))
        self.color_button.setAccessibleName(tr("塗りつぶしの色"))
        fill.addWidget(self.color_button, 1)
        self.weak_button = self._button(tr("半透明"), lambda: self.strength.setValue(50), tr("不透明度を50%にします"), variant="ghost")
        self.strong_button = self._button(tr("不透明"), lambda: self.strength.setValue(100), tr("不透明度を100%にします"), variant="ghost")
        fill.addWidget(self.weak_button)
        fill.addWidget(self.strong_button)
        self.fill_row.hide()
        tools.addWidget(self.fill_row)
        self.strength_description = self._label("", "faint")
        tools.addWidget(self.strength_description)
        tools.addSpacing(2)
        self.details_toggle = self._disclosure(tr("詳細設定・その他"))
        tools.addWidget(self.details_toggle)
        self.tool_details = QWidget()
        details = QVBoxLayout(self.tool_details)
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(8)
        details.addWidget(self._label(tr("編集プリセット"), "faint"))
        self.build_presets(details)
        expansion_label = self._label(tr("範囲の拡張"), "faint")
        self.expansion = QSlider(Qt.Orientation.Horizontal)
        self.expansion.setRange(0, 3)
        self.expansion.setValue(1)
        self.expansion.setPageStep(1)
        self.expansion.setTickPosition(QSlider.TickPosition.TicksBelow)
        tip = tr("なぞった・囲んだ範囲を、外側へこの画素数だけ広げて加工します。\n輪郭のきわが加工されずに残るのを防ぎます。")
        self.expansion.setToolTip(tip)
        expansion_label.setToolTip(tip)
        self.expansion.setAccessibleName(tr("範囲の拡張"))
        self.expansion.valueChanged.connect(self.tool_changed)
        self.expansion_box = slider_with_box(self.expansion, " px", tr("範囲の拡張（数値）"))
        details.addLayout(self._slider_heading(expansion_label, self.expansion_box))
        details.addWidget(self.expansion)
        details.addWidget(self._label(tr("画像の回転・反転"), "faint"))
        turns = QGridLayout()
        turns.setSpacing(6)
        self.transform_buttons = []
        for number, (text, tip, spec, glyph) in enumerate((
                (tr("右へ90°"), tr("画像を時計回りに90°回します"), {"rotation": 90}, "rotate_right"),
                (tr("左へ90°"), tr("画像を反時計回りに90°回します"), {"rotation": 270}, "rotate_left"),
                (tr("左右反転"), tr("画像を左右に反転します"), {"horizontal": True}, "flip_horizontal"),
                (tr("上下反転"), tr("画像を上下に反転します"), {"vertical": True}, "flip_vertical"))):
            button = self._button(text, lambda checked=False, value=spec: self.transform_image(**value), tip + tr("。「元に戻す」で取り消せます。"))
            button.setIcon(icon(glyph))
            button.setIconSize(QSize(18, 18))
            self.transform_buttons.append(button)
            turns.addWidget(button, *divmod(number, 2))
        details.addLayout(turns)
        details.addWidget(self._label(tr("色調"), "faint"))
        self.color_button_adjust = self._button(tr("色調の調整…"), lambda: self.editor_actions["color"].trigger(),
                                                tr("明るさ・コントラスト・彩度・色相などを、プレビューを見ながら調整します。"))
        details.addWidget(self.color_button_adjust)
        self.tool_details.hide()
        self.details_toggle.toggled.connect(self.show_details)
        tools.addWidget(self.tool_details)
        tools.addStretch(1)
        scroll = self.tools_scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(right)
        outer.addWidget(scroll, 1)

        footer = QFrame()
        footer.setObjectName("panelFooter")
        review = QVBoxLayout(footer)
        review.setContentsMargins(16, 12, 16, 14)
        review.setSpacing(8)
        heading = QHBoxLayout()
        heading.addWidget(section_label(tr("仕分け")))
        heading.addStretch(1)
        self.review_hint = ElidedLabel()
        self.review_hint.setMaximumWidth(160)
        self.review_hint.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self.review_hint.setObjectName("faint")
        heading.addWidget(self.review_hint)
        review.addLayout(heading)
        label_row = QHBoxLayout()
        label_row.setSpacing(6)
        self.label_buttons = {}
        for number, (label, text) in enumerate(REVIEW_LABELS.items(), 1):
            button = self._button(text, lambda checked=False, value=label: self.toggle_label(value),
                                  tr("{number} · もう一度押すと解除。複数選択した画像にはまとめて付けます。").format(number=number))
            button.setObjectName("reviewLabel")
            button.setProperty("label", label)
            button.setCheckable(True)
            self.label_buttons[label] = button
            label_row.addWidget(button)
        review.addLayout(label_row)
        self.auto_advance = QCheckBox(tr("ラベルを付けたら次へ"))
        self.auto_advance.setChecked(AUTO_ADVANCE_DEFAULT)
        review.addWidget(self.auto_advance)
        outer.addWidget(footer)
        return container

    def _build_status_bar(self):
        bottom = QFrame()
        bottom.setObjectName("statusBar")
        status = QHBoxLayout(bottom)
        status.setContentsMargins(16, 4, 10, 4)
        status.setSpacing(6)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.status.setMinimumHeight(28)
        status.addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(90)
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        status.addWidget(self.progress)
        self.cancel_button = self._button(tr("中止"), self.cancel_work, variant="ghost")
        self.cancel_button.hide()
        status.addWidget(self.cancel_button)
        status.addSpacing(8)
        # The shown image's size, beside the zoom.
        self.image_size_label = QLabel()
        self.image_size_label.setObjectName("muted")
        status.addWidget(self.image_size_label)
        status.addSpacing(6)
        self.zoom_label = ZoomField()
        self.zoom_label.zoomRequested.connect(lambda percent: self.canvas.zoom(percent / 100 / self.canvas.scale))
        fit = self.fit_button = tool_button("fit", tr("画面に合わせる · F"), self.canvas.fit, text=tr("全体"), variant="ghost")
        actual = self.actual_size_button = self._button(tr("原寸"), lambda: self.canvas.zoom(1 / self.canvas.scale), "Ctrl+1 · 100%", variant="ghost")
        self.view_controls = [self.crop_tool, self.compare_button, self.mask_toggle, self.zoom_label, fit, actual]
        for widget in (self.zoom_label, fit, actual):
            status.addWidget(widget)
        # Shown on the start page only, and not while something is loading.
        self.credit = QLabel(COPYRIGHT)
        self.credit.setObjectName("faint")
        status.addWidget(self.credit)
        return bottom

    def _build_save_popover(self):
        self.save_popover = Popover(self, 340)
        layout = self.save_popover.content
        self.save_settings = self.save_popover.body
        layout.addWidget(section_label(tr("保存方法")))
        self.auto = QCheckBox(tr("自動保存"))
        self.auto.setChecked(True)
        self.auto.setToolTip(tr("オフにすると、画像を移るときに保存するか確認します。"))
        self.auto.toggled.connect(self.auto_changed)
        layout.addWidget(self.auto)
        self.auto_note = self._label("", "faint")
        layout.addWidget(self.auto_note)
        self.overwrite = QCheckBox(tr("元画像に上書き保存"))
        self.overwrite.setChecked(True)
        self.overwrite.setToolTip(tr("オフにすると、別フォルダーに保存して元画像を残します。次の保存から適用します。"))
        self.overwrite.toggled.connect(self.overwrite_changed)
        layout.addWidget(self.overwrite)
        self.overwrite_note = self._label("", "faint")
        layout.addWidget(self.overwrite_note)
        self.keep_originals = QCheckBox(tr("上書き前の元画像を一時的に残す"))
        self.keep_originals.setChecked(True)
        self.keep_originals.setToolTip(tr("この起動中に最初に上書きする前の元画像を、一時フォルダーに残します。"))
        layout.addWidget(self.keep_originals)
        self.keep_originals_note = self._label("", "faint")
        layout.addWidget(self.keep_originals_note)
        self.output_group = QWidget()
        output = QVBoxLayout(self.output_group)
        output.setContentsMargins(0, 2, 0, 0)
        output.setSpacing(8)
        output.addWidget(section_label(tr("保存先")))
        self.folder_label = ElidedLabel(tr("画像のあるフォルダー / Sumīre"))
        self.folder_label.setObjectName("muted")
        output.addWidget(self.folder_label)
        folder_buttons = QHBoxLayout()
        folder_buttons.setSpacing(6)
        self.folder_change_button = self._button(tr("変更…"), lambda: (self.save_popover.hide(), self.choose_output()))
        folder_buttons.addWidget(self.folder_change_button)
        folder_buttons.addWidget(self._button(tr("フォルダーを開く"), lambda: (self.save_popover.hide(), self.reveal_output()), variant="ghost"))
        folder_buttons.addStretch(1)
        output.addLayout(folder_buttons)
        self.format_combo = QComboBox()
        for text, value in [(tr("PNG · 元の寸法・透過を保持"), "PNG"), (tr("JPEG · 品質95・白背景"), "JPEG"), (tr("WebP · 可逆圧縮・透過を保持"), "WEBP")]:
            self.format_combo.addItem(text, value)
        self.format_combo.currentIndexChanged.connect(self.export_settings_changed)
        output.addWidget(self.format_combo)
        self.name = QLineEdit()
        self.name.setPlaceholderText(tr("保存名（拡張子不要）"))
        self.name.editingFinished.connect(self.export_settings_changed)
        output.addWidget(self.name)
        layout.addWidget(self.output_group)
        layout.addWidget(divider())
        layout.addWidget(section_label(tr("メタデータ")))
        self.strip_metadata = QCheckBox(tr("保存するときにメタデータを削除"))
        self.strip_metadata.setChecked(STRIP_METADATA_DEFAULT)
        self.strip_metadata.setToolTip(tr("オフでも、「メタデータを削除」と一括削除では削除します。形式を変えて保存すると、メタデータは残りません。"))
        self.strip_metadata.toggled.connect(self.strip_metadata_changed)
        layout.addWidget(self.strip_metadata)
        self.strip_note = self._label("", "faint")
        layout.addWidget(self.strip_note)
        self.metadata_backup = QCheckBox(tr("削除前のメタデータを復元用に保存"))
        self.metadata_backup.setChecked(True)
        self.metadata_backup.setToolTip(tr("「⋯ → その他 → メタデータを復元して別名保存」で戻せます。"))
        layout.addWidget(self.metadata_backup)
        self.backup_note = self._label("", "faint")
        layout.addWidget(self.backup_note)
        for box in (self.auto, self.overwrite, self.keep_originals, self.metadata_backup):
            box.toggled.connect(self.update_save_notes)
        self.keep_originals.toggled.connect(lambda *_args: self.update_controls())
        self.update_save_notes()

    def show_save_settings(self):
        if self.save_popover.isVisible():
            self.save_popover.hide()
            return
        self.save_popover.show_for(self.save_mode_button)

    @staticmethod
    def _slider_heading(label, box):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(label, 1)
        row.addWidget(box)
        return row

    def _disclosure(self, text):
        toggle = QToolButton()
        toggle.setObjectName("disclosure")
        toggle.setText(text)
        toggle.setCheckable(True)
        toggle.setIcon(icon("chevron_right", "text_muted"))
        toggle.setIconSize(QSize(14, 14))
        toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        return toggle

    def show_details(self, show):
        self.tool_details.setVisible(show)
        self.details_toggle.setIcon(icon("chevron_down" if show else "chevron_right", "text_muted"))


    def _shortcuts(self):
        for shortcut in getattr(self, "shortcuts", []):
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self.bindings = load_bindings(self.preferences)
        self.compare(False)
        self.compare_key = None
        self.canvas.space_down = False
        self.canvas.pan_key = None
        self.canvas.bindings = self.bindings
        handlers = {
            "open_folder": self.open_folder, "save": self.save, "reload": self.reload_workspace,
            "file_menu": self.file_button.showMenu, "rename": self.rename_current,
            "undo": lambda: self.history(False), "redo": lambda: self.history(True),
            "next": lambda: self.navigate(1), "previous": lambda: self.navigate(-1),
            "save_next": self.save_next, "fit": self.canvas.fit,
            "actual_size": lambda: self.canvas.zoom(1 / self.canvas.scale),
            "zoom_in": lambda: self.canvas.zoom(1.25), "zoom_out": lambda: self.canvas.zoom(0.8),
            "brush_smaller": lambda: self.brush.setValue(self.brush.value() - 10),
            "brush_larger": lambda: self.brush.setValue(self.brush.value() + 10),
            "help": self.show_help, "strength_down": lambda: self.adjust_strength(-1),
            "strength_up": lambda: self.adjust_strength(1), "search": self.focus_search,
            "rejected": lambda: self.toggle_label("rejected"),
            "pending": lambda: self.toggle_label("pending"),
            "accepted": lambda: self.toggle_label("accepted"),
            "clear_label": lambda: self.set_review_label(None), "undo_organize": self.undo_organization,
            "copy_image": self.copy_image, "paste_image": self.paste_image, "fullscreen": self.toggle_fullscreen,
        }
        self.shortcuts = []
        for name, handler in handlers.items():
            for key in self.bindings[name]:
                shortcut = QShortcut(QKeySequence(key), self)
                shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
                shortcut.setAutoRepeat(name in {"next", "previous", "zoom_in", "zoom_out", "brush_smaller",
                                               "brush_larger", "strength_down", "strength_up"})
                shortcut.activated.connect(handler)
                self.shortcuts.append(shortcut)
        self.refresh_shortcut_hints()

    def shortcut_hint(self, name):
        return hint(self.bindings, name)

    def refresh_shortcut_hints(self):
        for action, name in ((self.open_folder_action, "open_folder"), (self.reload_action, "reload"),
                             (self.manual_save, "save"), (self.rename_button, "rename"),
                             (self.app_actions["help"], "help"),
                             (self.workflow_actions["undo_organize"], "undo_organize")):
            self.action_hint(action, name)
        for label, action in self.label_actions.items():
            self.action_hint(action, label or "clear_label")
        for key, name in (("copy", "copy_image"), ("paste", "paste_image"), ("fullscreen", "fullscreen")):
            self.action_hint(self.editor_actions[key], name)
        if self.workspace_host is not None:
            self.action_hint(self.new_tab_action, "new_tab")
            self.action_hint(self.close_tab_action, "close_tab")
        for widget, name, text in (
                (self.file_button, "file_menu", tr("フォルダー・画像・編集プロジェクトを開く")),
                (self.welcome.open_folder_button, "open_folder", tr("フォルダーを開く")),
                (self.undo_button, "undo", tr("元に戻す")), (self.redo_button, "redo", tr("やり直す")),
                (self.help_button, "help", tr("ヘルプ")),
                (self.reload_folder_button, "reload", tr("フォルダーを再読み込み（ほかのアプリで加えた画像も読み込みます）")),
                (self.save_next_button, "save_next", tr("メタデータを削除して保存し、次の画像へ（未編集でも保存）")),
                (self.search, "search", tr("ファイル名かメモの一部で絞り込みます")),
                (self.previous, "previous", tr("前の画像")), (self.next, "next", tr("次の画像")),
                (self.erase_button, "eraser", tr("なぞった部分を元画像に戻します。もう一度押すと元のツールへ")),
                (self.mask_toggle, "mask", tr("加工範囲のマスクを表示")),
                (self.compare_button, "compare", tr("押している間、元画像を表示")),
                (self.actual_size_button, "actual_size", tr("原寸表示（100%）")),
                (self.fit_button, "fit", tr("画面に合わせる"))):
            key = self.shortcut_hint(name)
            widget.setToolTip(text + (" · " + key if key else ""))
        self.file_label.rename_hint = self.shortcut_hint("rename")
        self.file_label.setToolTip(self.file_label.text() + tr("\nダブルクリックで名前を変更") +
                                  (" · " + self.file_label.rename_hint if self.file_label.rename_hint else ""))
        self.review_hint.setText(" / ".join(self.shortcut_hint(name) or tr("未設定") for name in REVIEW_LABELS))
        for name, label in self.key_hints.items():
            label.setText(self.shortcut_hint(name))
            label.setVisible(bool(label.text()))
        for label, button in self.label_buttons.items():
            key = self.shortcut_hint(label)
            button.setToolTip((key + " · " if key else "") + tr("もう一度押すと解除。複数選択した画像にはまとめて付けます。"))

    def action_hint(self, action, name):
        text, key = action.text().split("\t")[0], self.shortcut_hint(name)
        action.setText(text + ("\t" + key if key else ""))

    def show_shortcut_settings(self):
        dialog = ShortcutDialog(self.preferences, self)
        if self.confirm_dialog(dialog, accepted=QDialog.DialogCode.Accepted):
            if self.workspace_host is not None:
                self.workspace_host.apply_shortcuts()
            else:
                self._shortcuts()
            self.update_controls()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize and watched is getattr(self, "library_panel", None):
            self.update_library_actions_layout(event.size().width())
        if event.type() == QEvent.Type.Resize and watched is getattr(self, "image_bar", None):
            # The state and the two buttons need about this much room on one row.
            self.arrange_image_bar(event.size().width() < 640)
        if event.type() == QEvent.Type.Resize and watched is getattr(self, "canvas_header", None):
            # Keep the file name readable in narrow windows: sharing becomes icon-only.
            compact = event.size().width() < 560
            self.share_button.setText("" if compact else tr("共有…"))
        if (event.type() == QEvent.Type.KeyRelease and getattr(self, "compare_key", None) == event.key()):
            if not event.isAutoRepeat():
                self.compare_key = None
                self.compare(False)
            return True
        if (event.type() in {QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress}
                and hasattr(self, "bindings") and matches(event, self.bindings["compare"])):
            if (self.isVisible() and self.isActiveWindow() and QApplication.activeModalWidget() is None
                    and QApplication.activePopupWidget() is None and self.isAncestorOf(QApplication.focusWidget())
                    and not isinstance(QApplication.focusWidget(), (QLineEdit, QPlainTextEdit))):
                if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
                    self.compare_key = event.key()
                    self.compare(True)
                event.accept()
                return True
        if (event.type() == QEvent.Type.Wheel and isinstance(watched, QComboBox)
                and not watched.view().isVisible()):
            # Scrolling over a choice list scrolls the panel instead of changing the choice.
            area = watched.parentWidget()
            while area is not None and not isinstance(area, QAbstractScrollArea):
                area = area.parentWidget()
            if area is not None:
                QApplication.sendEvent(area.verticalScrollBar(), event)
            return True
        if (event.type() == QEvent.Type.Wheel and isinstance(watched, (QSlider, QAbstractSpinBox))
                and not watched.hasFocus()):
            # The same for sliders and number boxes in a scrolling panel, unless they were clicked first.
            # (QSlider, not QAbstractSlider: the panel's own scroll bar must still scroll.)
            area = watched.parentWidget()
            while area is not None and not isinstance(area, QAbstractScrollArea):
                area = area.parentWidget()
            if area is not None:
                QApplication.sendEvent(area.verticalScrollBar(), event)
                return True
        if event.type() == QEvent.Type.ApplicationDeactivate:
            self.compare_key = None
            self.compare(False)
            self.canvas.space_down = False
        if (event.type() == QEvent.Type.FocusOut and watched is getattr(self, "canvas", None)
                and getattr(self, "compare_key", None) is not None):
            self.compare_key = None
            self.compare(False)
        return super().eventFilter(watched, event)

    def run_job(self, function, done, failed=None, progress=None, *, finished=None):
        job = Job(function, progress=progress is not None)
        self.jobs.add(job)
        job.signals.done.connect(done)
        job.signals.failed.connect(failed or self.error)
        job.signals.finished.connect(lambda: self.jobs.discard(job))
        if finished:
            job.signals.finished.connect(finished)
        if progress:
            job.signals.progress.connect(progress)
        self.pool.start(job)
        return job

    def error(self, message):
        self.last_error = str(message)
        self.status.setText(message)
        self.status.setToolTip(str(message))
        self.status.setStyleSheet(f"color: {TOKENS['danger']}")
        self.update_controls()

    def info(self, message):
        self.status.setStyleSheet("")
        self.status.setText(message)
        self.status.setToolTip(str(message))

    def busy(self):
        return self.loading or self.finalizing or self.batch_job is not None or self.novelai_job is not None or self.canvas.stroke is not None

    def update_controls(self):
        blocked = self.busy()
        has = self.document is not None
        idle = not blocked and not self.saving
        paths = bool(self.model.paths)
        self.app_actions["save_project"].setEnabled(has and idle)
        for key in ("open_project", "records"):
            self.app_actions[key].setEnabled(idle)
        for widget in (self.preset_combo, self.preset_save, self.preset_delete):
            widget.setEnabled(idle)
        self.overwrite.setEnabled(not (has and getattr(self.document, "project", False)))
        if has and self.is_clipboard_path(self.document.path):
            self.overwrite.setEnabled(False)
        for key in ("edit", "color", "metadata", "copy", "upscale"):
            self.editor_actions[key].setEnabled(has and idle)
        for widget in (self.crop_tool, self.color_button_adjust, *self.transform_buttons):
            widget.setEnabled(has and idle)
        self.editor_actions["paste"].setEnabled(idle)
        self.editor_actions["quality"].setEnabled(idle)
        self.inverse_action.setEnabled(idle and self.shape_combo.currentData() != "brush")
        self.undo_button.setEnabled(has and not blocked and bool(self.document.undo_stack))
        self.redo_button.setEnabled(has and not blocked and bool(self.document.redo_stack))
        self.save_next_button.setEnabled(has and not blocked)
        self.manual_save.setEnabled(has and not blocked)
        self.metadata_button.setEnabled(has and idle)
        self.metadata_delete_button.setEnabled(has and idle)
        self.metadata_restore.setEnabled(has and idle)
        self.restore_original_action.setEnabled(has and idle and originals().has(self.document.path))
        kept = self.keep_originals.isChecked() and self.overwrite.isChecked()
        self.restore_original_button.setEnabled(kept and self.restore_original_action.isEnabled())
        self.restore_original_button.setToolTip(
            tr("この起動中に最初に上書きする前の元画像に戻します。実行前に確認します。") if self.restore_original_button.isEnabled()
            else tr("保存方法の「上書き前の元画像を一時的に残す」がオフのため使えません。") if not kept
            else tr("この画像は、この起動中にまだ上書きしていません。上書きした後に、元画像へ戻せます。"))
        self.keep_originals.setEnabled(self.overwrite.isChecked())
        self.keep_originals_note.setEnabled(self.overwrite.isChecked())
        self.share_button.setEnabled(has and idle)
        for action in self.share_actions.values():
            action.setEnabled(has and idle)
        self.mask_toggle.setEnabled(has and not blocked)
        self.mask_export.setEnabled(has and idle)
        self.reset_edits_action.setEnabled(has and idle)
        self.reset_edits_button.setEnabled(has and idle)
        self.compare_button.setEnabled(has)
        self.image_menu_button.setEnabled(has)
        selected = self.selected_paths()
        current_label = self.model.labels.get(self.document.path) if has else None
        if len(selected) > 1 and not all(self.model.labels.get(path) == current_label for path in selected):
            current_label = None
        for label, button in self.label_buttons.items():
            button.setEnabled(has and idle)
            button.setChecked(label == current_label)
        for action in self.label_actions.values():
            action.setEnabled(has and idle)
        visible = self.visible_paths()
        visible_row = visible.index(self.document.path) if has and self.document.path in visible else -1
        self.previous.setEnabled(visible_row > 0 and not blocked)
        self.next.setEnabled(0 <= visible_row < len(visible) - 1 and not blocked)
        for widget in (self.open_folder_action, self.open_files_action,
                       self.welcome.open_folder_button, self.welcome.open_files_button):
            widget.setEnabled(idle)
        self.save_settings.setEnabled(idle)
        self.reload_action.setEnabled(idle and bool(self.workspace_inputs))
        overwrite = self.overwrite.isChecked()
        self.save_next_button.setText(tr("上書きして次へ →") if overwrite else tr("保存して次へ →"))
        self.manual_save.setText(tr("上書き保存") if overwrite else tr("保存"))
        self.action_hint(self.manual_save, "save")
        self.metadata_button.setText(tr("メタデータを削除して上書き") if overwrite else tr("メタデータを削除して保存"))
        self.format_combo.setEnabled(not overwrite)
        self.name.setEnabled(not overwrite)
        self.folder_change_button.setEnabled(not overwrite)
        if self.output_group.isHidden() != overwrite:
            self.output_group.setVisible(not overwrite)
            if self.save_popover.isVisible():
                self.save_popover.fit_content()
        self.folder_label.setText(tr("元画像と同じ場所・名前・形式") if overwrite else str(self.output_folder or tr("画像のあるフォルダー / Sumīre")))
        self.batch_button.setEnabled(paths and idle)
        self.batch_delete_button.setEnabled(paths and idle)
        self.auto.setEnabled(not blocked)
        self.sort_combo.setEnabled(paths and idle)
        self.rename_button.setEnabled(has and idle)
        self.file_label.setEnabled(has and idle)
        self.number_button.setEnabled(paths and idle)
        self.shape_combo.setEnabled(not blocked)
        for _, button in self.mode_buttons:
            button.setEnabled(not blocked)
        self.brush.setEnabled(not blocked and self.shape_combo.currentData() == "brush")
        self.brush_box.setEnabled(self.brush.isEnabled())
        self.strength.setEnabled(not blocked and self.mode != "erase")
        self.strength_box.setEnabled(self.strength.isEnabled())
        for widget in (self.weak_button, self.strong_button, self.color_button):
            widget.setEnabled(not blocked and self.mode == "fill")
        self.canvas.locked = blocked or self.pending_action is not None
        cancellable = self.loading or self.saving or self.batch_job is not None or self.novelai_job is not None
        self.progress.setVisible((cancellable or self.finalizing) and self.batch_job is None)
        self.cancel_button.setVisible(cancellable)
        self.update_save_state()
        self.update_folder_controls(idle)
        self.file_label.setText(self.document.path.name if has else "")
        self.update_page()
        self.update_workbench_controls()
        self.stateChanged.emit()

    def save_mode_text(self):
        overwrite = self.overwrite.isChecked()
        return (tr("元画像に上書き") if overwrite else tr("別フォルダーへ保存")) + (tr(" · 自動保存") if self.auto.isChecked() else tr(" · 手動保存"))

    def update_save_state(self):
        """Show what the next save does and whether the current image is saved."""
        overwrite = self.overwrite.isChecked()
        self.save_mode_button.setText((tr("上書き") if overwrite else tr("別フォルダー")) + (tr(" · 自動保存") if self.auto.isChecked() else tr(" · 手動保存")) + "  ▾")
        self.save_mode_button.setToolTip(tr("保存方法：{save_mode_text}\nクリックで保存方法・保存先・メタデータの退避を変更").format(save_mode_text=self.save_mode_text())
                                         + (tr("\n元画像を置き換えます（バックアップなし）。") if overwrite else ""))
        document = self.document
        if document is None:
            text, tone, tip = "", "neutral", ""
        elif self.saving:
            text, tone, tip = tr("保存中…"), "info", tr("保存して、書き出した画像を確かめています。")
        elif self.save_failed and document.dirty:
            text, tone, tip = tr("保存失敗"), "danger", tr("編集は残っています。「保存」で再試行できます。")
        elif document.dirty:
            text, tone = tr("未保存"), "warn"
            tip = tr("まもなく自動保存します。") if self.auto.isChecked() else tr("「保存」、または「保存して次へ」で保存します。")
        elif document.saved_revision == document.revision and document.output:
            text, tone, tip = tr("保存済み"), "ok", tr("保存済み\n{output}").format(output=document.output)
        else:
            text, tone, tip = tr("未編集"), "neutral", tr("まだ編集・保存していません。")
        self.save_state.setText(f'<span style="color:{TOKENS[tone]}">●</span>&nbsp;{text}' if text else "")
        self.save_state.setToolTip(tip)
        self.save_state.setAccessibleName(tr("保存状態：{text}").format(text=text) if text else "")
        self.update_metadata_state()

    def update_metadata_state(self):
        """Whether the file that holds the current image has metadata; click for its contents."""
        document = self.document
        found = getattr(document, "metadata", None) if document else None
        if document is None:
            text, tip = "", ""
        elif getattr(document, "project", False) or self.is_clipboard_path(document.path):
            text, tip = tr("メタデータ：無し"), tr("編集中の画像はメタデータを持ちません。")
        elif found is None:
            text, tip = tr("メタデータ：不明"), tr("確認できませんでした。クリックで内容を表示します。")
        elif found:
            text = tr("メタデータ：有り")
            tip = tr("含まれる種類\n") + "\n".join(tr("・") + name for name in found) + tr("\nクリックで内容を表示します。")
        else:
            text, tip = tr("メタデータ：無し"), tr("対応する種類のメタデータは見つかりませんでした。クリックで確認できます。")
        self.metadata_state.setText(text)
        self.metadata_state.setToolTip(tip)
        self.metadata_state.setProperty("found", bool(found))
        self.metadata_state.style().unpolish(self.metadata_state)
        self.metadata_state.style().polish(self.metadata_state)
        self.metadata_state.setAccessibleName(text)

    def save_notes(self):
        """What each save option does in its current state (also shown on the settings page)."""
        overwrite = self.overwrite.isChecked()
        return {
            "auto": tr("編集のたびに保存します。") if self.auto.isChecked() else
                    tr("「保存」を押したときに保存します。画像を移るときは、保存するか確認します。"),
            "overwrite": tr("同じ名前・形式で置き換えます。") if overwrite else tr("元画像は変えずに、別フォルダーへ保存します。"),
            "keep_originals": (tr("別フォルダーに保存するので、元画像はそのまま残ります。") if not overwrite else
                               tr("アプリを終了するまで元画像もバックアップされます。（「⋯ → 上書き前の元画像に戻す」から戻せます）")
                               if self.keep_originals.isChecked() else tr("元のファイルは残しません。")),
            "strip_metadata": tr("保存のたびに削除します。") if self.strip_metadata.isChecked() else tr("元のメタデータを残して保存します。"),
            "metadata_backup": tr("削除したメタデータを管理記録に残します（暗号化はしません）。") if self.metadata_backup.isChecked()
                               else tr("削除したメタデータは残しません。あとから戻せません。"),
        }

    def update_save_notes(self, *_args):
        notes = self.save_notes()
        for key, label in (("auto", self.auto_note), ("overwrite", self.overwrite_note), ("keep_originals", self.keep_originals_note),
                           ("strip_metadata", self.strip_note), ("metadata_backup", self.backup_note)):
            label.setText(notes[key])
        if self.save_popover.isVisible():
            self.save_popover.fit_content()

    def strip_metadata_changed(self, strip):
        self.update_save_notes()

    def confirm_first_overwrite(self):
        """Explain overwriting before the first overwrite of a run; can be hidden for good."""
        if OVERWRITE_NOTICE["shown"] or self.preferences.data.get("hide_overwrite_notice") is True:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(tr("元画像に上書きします"))
        box.setText(tr("元の画像ファイルを、編集後の画像で置き換えます。"))
        box.setInformativeText(tr("※ 元画像はアプリの終了まで残り、「⋯ → 上書き前の元画像に戻す」で戻せます。")
                               if self.keep_originals.isChecked() else
                               tr("元のファイルは残りません。編集はCtrl+Zで戻せますが、アプリを終了すると戻せません。"))
        hide = QCheckBox(tr("今後この確認を表示しない"))
        box.setCheckBox(hide)
        accept = box.addButton(tr("上書きする"), QMessageBox.ButtonRole.AcceptRole)
        accept.setObjectName("primary")  # the expected choice, in the accent colour
        change = box.addButton(tr("保存方法を変更"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(tr("キャンセル"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(accept)
        box.exec()
        if box.clickedButton() is change:
            QTimer.singleShot(0, self.show_save_settings)
            return False
        if box.clickedButton() is not accept:
            return False
        OVERWRITE_NOTICE["shown"] = True
        if hide.isChecked():
            data = dict(self.preferences.data)
            data["hide_overwrite_notice"] = True
            try:
                self.preferences.save(data)
            except OSError:
                pass
        return True

    def restore_original(self):
        document = self.document
        if document is None or self.busy() or self.saving or not originals().has(document.path):
            return
        answer = QMessageBox.question(self, tr("上書き前の元画像に戻す"),
                                      tr("この起動中に最初に上書きする前の元画像に戻します。\n"
                                      "今の加工と、この画像の編集の履歴は消えます。"),
                                      QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Ok:
            return
        path = document.path
        self.autosave_timer.stop()
        try:
            originals().restore(path, document.source_digest)
        except (ImageProblem, OSError) as error:
            self.error(str(error) if isinstance(error, ImageProblem) else tr("元画像に戻せませんでした。書き込み権限を確認してください。"))
            return
        self.documents.pop(path, None)
        self.owned.pop(path, None)
        self.model.cache.pop(path, None)
        self.model.state(path, "")
        self.document = None
        self._load_index(self.model.rows[path])
        self.info(tr("上書き前の元画像に戻しました。"))

    def update_page(self):
        """Switch between the empty-state page and the three-panel workspace."""
        workspace = bool(self.model.paths) or bool(self.workspace_inputs)
        target = self.splitter if workspace else self.welcome
        if self.pages.currentWidget() is not target:
            self.save_popover.hide()
            self.pages.setCurrentWidget(target)
            if workspace:
                self.canvas.setFocus()
            else:
                self.refresh_welcome()
        for widget in self.workspace_widgets:
            widget.setVisible(workspace)
        self.credit.setVisible(not workspace and self.progress.isHidden() and self.cancel_button.isHidden())
        self.workspace_label.setText((self.folder_location(tab_name=True) or self.workspace_title()) if workspace else "")
        self.workspace_label.setToolTip(tr("現在の作業対象\n") + "\n".join(self.workspace_inputs) if workspace else tr("画像・フォルダーは「ファイル」から開けます。"))
        if not workspace:
            self.welcome.set_note(tr("保存方法：{save_mode_text}").format(save_mode_text=self.save_mode_text()))

    def workspace_title(self):
        if self.custom_title and self.workspace_inputs:
            return self.custom_title
        if not self.workspace_inputs:
            return tr("フォルダーを開く")
        if self.folder_root is not None and self.browsed_folder() is not None:
            # The tab keeps the name of the folder it opened while browsing inside it.
            return self.folder_root.name or str(self.folder_root)
        first = Path(self.workspace_inputs[0])
        title = first.name or str(first)
        return title + (tr(" ほか{value}件").format(value=len(self.workspace_inputs) - 1) if len(self.workspace_inputs) > 1 else "")

    def set_custom_title(self, title):
        """Name the tab; an empty name returns to the folder name."""
        title = " ".join(str(title or "").split())[:60]
        self.custom_title = title or None
        self.update_page()
        if self.workspace_host is not None:
            self.workspace_host.update_tab(self)

    def choose_language(self, code):
        """Chosen on the start page; applies from the next start, like the settings."""
        from .i18n import save_language
        if not save_language(self.preferences, code):
            self.error(tr("設定を保存できません。設定の保存先を確認してください。"))
            return
        self.welcome.set_language(code, switch_note(code) if code != language() else "")

    def refresh_welcome(self):
        self.welcome.set_recent(self.recent_workspaces())
        saved = self.preferences.data.get("language")
        self.welcome.set_language(saved if saved in LANGUAGES else language(),
                                  switch_note(saved) if saved in LANGUAGES and saved != language() else "")
        self.welcome.set_note(tr("保存方法：{save_mode_text}").format(save_mode_text=self.save_mode_text()))

    def recent_workspaces(self):
        entries = self.preferences.data.get("recent", [])
        result = []
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, list) and entry and all(isinstance(raw, str) for raw in entry):
                    existing = [raw for raw in entry if Path(raw).exists()]
                    if existing and existing not in result:
                        result.append(existing)
        return result[:8]

    def populate_recent_menu(self):
        self.recent_menu.clear()
        entries = self.recent_workspaces()
        for inputs in entries:
            title, location = describe_inputs(inputs)
            action = self.recent_menu.addAction(icon("folder" if Path(inputs[0]).is_dir() else "image", "text_muted"),
                                                f"{title}\t{location}".replace("&", "&&"))
            action.setEnabled(not self.busy() and not self.saving)
            action.triggered.connect(lambda *_args, value=list(inputs): self.open_recent(value))
        if not entries:
            self.recent_menu.addAction(tr("まだありません")).setEnabled(False)

    def forget_recent(self, inputs):
        """Drop an entry from the recent list; the folder and its images are untouched."""
        data = dict(self.preferences.data)
        recent = data.get("recent", [])
        recent = [entry for entry in recent if isinstance(entry, list)] if isinstance(recent, list) else []
        data["recent"] = [entry for entry in recent
                          if entry != inputs and [raw for raw in entry if isinstance(raw, str) and Path(raw).exists()] != inputs]
        try:
            self.preferences.save(data)
        except OSError:
            self.error(tr("設定を保存できません。設定の保存先を確認してください。"))
            return
        self.refresh_welcome()

    def open_recent(self, inputs):
        if self.busy() or self.saving:
            return
        existing = [raw for raw in inputs if Path(raw).exists()]
        if existing:
            self.open_inputs(existing)
        else:
            self.error(tr("フォルダー・画像が見つかりません。移動・削除された可能性があります。"))

    def tool(self):
        return Tool(self.mode, self.brush.value(), self.strength.value(), self.color, self.expansion.value(),
                    opacity=self.strength.value() if self.mode == "fill" else 100)

    def set_mode(self, mode):
        if self.busy() or mode not in self.mode_strengths:
            return
        self.mode_strengths[self.mode] = self.strength.value()
        self.mode = mode
        self.strength.blockSignals(True)
        self.strength.setRange(0 if mode == "fill" else 2, 100)
        self.strength.setValue(self.mode_strengths[mode])
        self.strength.blockSignals(False)
        for value, button in self.mode_buttons:
            button.setChecked(value == mode)
        self.color_button.setVisible(mode == "fill")
        self.fill_row.setVisible(mode == "fill")
        for widget in (self.strength, self.strength_label, self.strength_box):
            widget.setVisible(mode != "erase")
        self.tool_changed()
        self.update_controls()

    def toggle_eraser(self):
        """The eraser button and E switch the eraser on, and back to the previous tool."""
        if self.busy():
            self.erase_button.setChecked(self.mode == "erase")
            return
        if self.mode == "erase":
            self.set_mode(self.mode_before_erase if self.mode_before_erase in ("mosaic", "blur", "fill") else "mosaic")
        else:
            self.mode_before_erase = self.mode
            self.set_mode("erase")

    def adjust_strength(self, direction):
        """Keyboard replacement for the former weaker/stronger buttons."""
        if self.busy() or self.mode == "erase" or isinstance(QApplication.focusWidget(), QLineEdit):
            return
        self.strength.setValue(self.strength.value() + direction * (10 if self.mode == "fill" else 2))

    def tool_changed(self, *args):
        self.brush_label.set_parts(tr("ブラシの直径"), "")
        # Mode switches change the sliders with their signals blocked; bring the number boxes along.
        for box, slider in ((self.brush_box, self.brush), (self.strength_box, self.strength), (self.expansion_box, self.expansion)):
            box.blockSignals(True)
            box.setRange(slider.minimum(), slider.maximum())
            box.setValue(slider.value())
            box.blockSignals(False)
        value = self.strength.value()
        if self.mode == "erase":
            self.strength_description.setText(tr("なぞった部分を元画像に戻します。読み込む前に保存した加工は戻せません。"))
        elif self.mode == "fill":
            self.strength_label.set_parts(tr("塗りつぶしの不透明度"), "")
            self.strength_box.setSuffix("%")
            self.strength_description.setText("")
            self.strength.setAccessibleName(tr("塗りつぶしの不透明度"))
            tip = tr("{FILL_NOTE}\n, で下げる / . で上げる（10%ずつ）").format(FILL_NOTE=FILL_NOTE)
        else:
            label = tr("モザイクの強さ") if self.mode == "mosaic" else tr("ぼかしの強さ")
            self.strength_label.set_parts(label, "")
            self.strength_box.setSuffix(" px")
            self.strength_description.setText("")
            self.strength.setAccessibleName(label)
            tip = ((tr("モザイクの1マスの大きさです。") if self.mode == "mosaic" else tr("ぼかしの半径です。"))
                   + tr("\n{BLUR_NOTE}\n, で弱く / . で強く（2pxずつ）").format(BLUR_NOTE=BLUR_NOTE))
        if self.mode != "erase":
            self.strength.setToolTip(tip)
            self.strength_label.setToolTip(tip)
        self.strength_description.setVisible(bool(self.strength_description.text()))
        self.canvas.tool = self.tool()
        self.canvas.shape = self.shape_combo.currentData()
        self.inverse_action.setEnabled(not self.busy() and not self.saving and self.canvas.shape != "brush")
        self.shape_combo.setToolTip(SHAPE_TIPS[self.canvas.shape]
                                    + (tr("\n囲んだ範囲の外側に適用します。") if self.canvas.invert_selection and self.canvas.shape != "brush" else ""))
        key = (self.document, self.document.revision, self.tool().effect_key) if self.document else None
        if not self.canvas.stroke and (key != self.prepared_effect_key or self.canvas.effect is None):
            self.canvas.ready = False
            self.effect_timer.start()
        self.canvas.update()

    def update_color_button(self):
        self.color_button.setIcon(swatch(self.color))
        self.color_button.setText(self.color.upper())

    def show_edit_mask(self, visible):
        self.canvas.show_mask = visible
        self.canvas.refresh_mask()
        self.canvas.update()

    def auxiliary_job(self, work, message):
        self.finalizing = True
        self.update_controls()
        def resume():
            self.finalizing = False
            self.update_controls()
            if self.document and not self.canvas.ready:
                self.effect_timer.start()
            if self.auto.isChecked() and self.document and self.document.dirty:
                self.autosave_timer.start()
        def done(result):
            resume()
            self.info(message(result) if callable(message) else message)
        def failed(error):
            resume()
            self.error(error)
        job = self.run_job(work, done, failed)
        job.signals.cancelled.connect(lambda: failed(tr("処理を中止しました。")))
        return job

    def export_edit_mask(self):
        if not self.document or self.busy() or self.saving:
            return
        source = self.document.path
        raw, _ = QFileDialog.getSaveFileName(self, tr("加工範囲のマスクをPNGで保存"), str(source.with_name(source.stem + "_mask.png")), "PNG (*.png)")
        if not raw:
            return
        target = Path(raw)
        if target.suffix.lower() != ".png":
            if target.suffix:
                self.error(tr("加工マスクはPNG形式です。拡張子を.pngにしてください。"))
                return
            target = target.with_suffix(".png")
            if target.exists():
                self.error(tr("同名のPNGがあります。別の名前を指定してください。"))
                return
        pixels = self.document.edit_mask.copy()
        def export(cancel):
            owned = file_digest(target) if target.exists() else None
            return save_image(pixels, target, source=source, format="PNG", owned_digest=owned, cancel=cancel)
        self.info(tr("加工マスクを保存・検証中…"))
        self.auxiliary_job(export, lambda result: tr("加工マスクを保存しました · {name}").format(name=result.path.name))

    def setup_explorer(self, remove=False):
        if self.busy() or self.saving:
            return
        def configure(cancel):
            check_cancel(cancel)
            try:
                configure_context_menu(remove=remove)
            except (ValueError, OSError) as error:
                raise ImageProblem(str(error) if isinstance(error, ValueError) else tr("Windowsの右クリック項目を更新できません。接続・アクセス権を確認してください。")) from None
        self.info(tr("Windowsの右クリックメニューを更新中…"))
        self.auxiliary_job(configure, tr("右クリックの登録を解除しました。") if remove else tr("右クリックに「Sumīreで開く」を追加しました。"))

    def choose_color(self):
        color = QColorDialog.getColor(QColor(self.color), self, tr("塗りつぶしの色"))
        if color.isValid():
            self.color = color.name()
            self.update_color_button()
            self.tool_changed()

    def compare(self, enabled):
        if self.canvas.stroke or self.finalizing:
            return
        self.canvas.compare = enabled
        self.canvas.update()

    def prepare_effect(self):
        if self.closing or not self.workspace_active or not self.document or self.busy():
            return
        key = (self.document, self.document.revision, self.tool().effect_key)
        if self.canvas.effect is not None and self.prepared_effect_key == key:
            self.canvas.ready = True
            self.canvas.message = ""
            return
        if self.effect_job:
            if self.pending_effect_key == key and not self.effect_job.cancel.is_set():
                return
            # Coalesce slider changes instead of queuing full-resolution snapshots.
            self.effect_job.cancel.set()
            self.effect_generation += 1
            self.effect_restart = True
            return
        self.effect_generation += 1
        generation = self.effect_generation
        document = self.document
        revision = document.revision
        tool = self.tool()
        self.pending_effect_key = key
        # A worker owns this immutable snapshot while the GUI edits only after completion.
        pixels = (document.original if tool.mode == "erase" else document.image).copy()
        self.canvas.effect = None
        self.canvas.message = tr("ブラシを準備中…")
        self.canvas.ready = False
        self.canvas.update()

        def compute(cancel):
            check_cancel(cancel)
            result = pixels if tool.mode == "erase" else make_effect(pixels, tool)
            check_cancel(cancel)
            return result

        def done(effect):
            if generation != self.effect_generation or document is not self.document or revision != document.revision or tool.effect_key != self.tool().effect_key:
                return
            self.prepared_effect_key = key
            self.canvas.effect = effect
            self.canvas.ready = True
            self.canvas.message = ""
            self.canvas.update()
            if self.workspace_host is not None:
                self.workspace_host.trim_memory()

        def failed(message):
            if generation == self.effect_generation:
                self.canvas.message = tr("ブラシを準備できませんでした。設定を変えて再試行してください。")
                self.error(message)

        def finished():
            if self.effect_job is job:
                self.effect_job = None
            if self.effect_restart and not self.closing:
                self.effect_restart = False
                self.effect_timer.start()

        # Connect before starting: a small image can finish on the worker thread
        # before run_job returns, so connecting afterwards can miss the signal.
        job = self.effect_job = self.run_job(compute, done, failed, finished=finished)

    def reset_edits(self):
        if self.busy() or self.saving or self.document is None:
            return
        document = self.document
        dialog = QMessageBox(self)
        dialog.setWindowTitle(tr("加工・マスクの初期化を確認"))
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(tr("この画像の加工とマスクを初期化しますか？"))
        saving = (tr("初期化後、現在の設定で自動保存します。\n保存方法：") + self.save_mode_text()
                  if self.auto.isChecked() else tr("初期化後は未保存の状態になります（「保存」で保存）。"))
        dialog.setInformativeText(tr("すべての加工とマスクを消して、元画像に戻します。（※ 「元に戻す」で取り消せます）\n"))
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        dialog.button(QMessageBox.StandardButton.Ok).setText(tr("初期化"))
        dialog.button(QMessageBox.StandardButton.Cancel).setText(tr("キャンセル"))
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        dialog.setEscapeButton(QMessageBox.StandardButton.Cancel)
        if not self.confirm_dialog(dialog) or self.document is not document or self.busy() or self.saving:
            return
        self.reset_document_edits(document)

    def reset_document_edits(self, document):
        """Clear the shown image's edits and mask as one undoable edit, saved as usual."""
        self.autosave_timer.stop()
        self.finalizing = True
        self.canvas.ready = False
        self.update_controls()

        def done(changed):
            self.finalizing = False
            self.canvas.refresh()
            if changed or document.dirty:
                self.after_edit()
            else:
                self.prepare_effect()
                self.update_controls()
                self.info(tr("初期化する加工・マスクはありません。"))

        def failed(message):
            self.finalizing = False
            self.canvas.refresh()
            self.prepare_effect()
            self.update_controls()
            self.error(message)

        self.run_job(lambda cancel: document.reset_edits(), done, failed)

    def finish_stroke(self, stroke):
        self.finalizing = True
        self.info(tr("編集を確定中…"))
        self.update_controls()

        def done(changed):
            self.finalizing = False
            if changed or self.document.dirty:
                self.after_edit()
            else:
                if self.document.saved_revision == self.document.revision:
                    self.show_saved_state(self.document)
                else:
                    self.info(tr("変更はありません。"))
                self.prepare_effect()
                self.update_controls()

        def failed(message):
            stroke.cancel()
            self.finalizing = False
            self.canvas.refresh()
            self.error(message)
            self.prepare_effect()

        self.run_job(lambda cancel: stroke.finish(), done, failed)

    def after_edit(self):
        self.show_position()
        edited = self.document.edited
        unedited = self.document.edit_state is False
        self.model.state(self.document.path, "編集中 · 未保存" if edited else "未編集 · 保存待ち" if unedited else "変更なし · 保存待ち")
        prefix = tr("変更あり") if edited else tr("元画像の状態") if unedited else tr("読み込み時の状態")
        self.info(prefix + (tr(" · 自動保存待ち") if self.auto.isChecked() else tr(" · 「保存」で保存")))
        self.prepare_effect()
        self.update_controls()
        if self.auto.isChecked():
            self.autosave_timer.start()

    def stroke_cancelled(self):
        self.update_controls()
        # A previous autosave timer may have expired during the cancelled stroke.
        if self.auto.isChecked() and self.document and self.document.dirty:
            self.autosave_timer.start()

    def history(self, redo=False):
        if not self.document or self.busy():
            return
        document = self.document
        self.finalizing = True
        self.info(tr("やり直しています…") if redo else tr("元に戻しています…"))
        self.canvas.ready = False
        self.update_controls()

        def done(changed):
            self.finalizing = False
            if changed:
                self.canvas.refresh()
                self.after_edit()
            else:
                self.prepare_effect()
                self.update_controls()

        def failed(message):
            self.finalizing = False
            self.error(message)
            self.prepare_effect()

        self.run_job(lambda cancel: document.redo() if redo else document.undo(), done, failed)

    def ready_hint(self):
        """What drawing does under the current save settings, with the keys to continue."""
        next_key, save_next = (self.shortcut_hint(name) for name in ("next", "save_next"))
        parts = [tr("なぞると自動保存") if self.auto.isChecked() else tr("なぞって加工")]
        if next_key:
            parts.append(tr("{next_key}で次へ").format(next_key=next_key))
        if save_next:
            parts.append(tr("{save_next}で{value}して次へ").format(save_next=save_next, value=tr('上書き保存') if self.overwrite.isChecked() else tr('保存')))
        return " · ".join(parts)

    def auto_changed(self, enabled):
        if enabled and self.document and self.document.dirty:
            self.autosave_timer.start()
        elif not enabled:
            self.autosave_timer.stop()
        if self.status.text().startswith((tr("なぞると自動保存"), tr("なぞって加工"))):
            self.info(self.ready_hint())
        self.update_controls()

    def open_folder(self):
        if self.busy() or self.saving:
            return
        folder = QFileDialog.getExistingDirectory(self, tr("画像フォルダーを開く"))
        if folder:
            self.open_inputs([folder])

    def open_files(self):
        if self.busy() or self.saving:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, tr("画像を開く"), "", tr("画像 (") + " ".join("*" + suffix for suffix in sorted(SUPPORTED)) + ")")
        if paths:
            self.open_inputs(paths)

    def guard(self, action, force_save=False):
        if self.busy():
            return False
        if self.saving:
            self.pending_action = action
            if self.document and self.document.dirty:
                self.save_again = True
            self.update_controls()
            return True
        if self.document and (self.document.dirty or force_save):
            if self.auto.isChecked() or force_save:
                self.pending_action = action
                self.save()
                return True
            answer = QMessageBox.question(self, tr("未保存の変更"), tr("この画像の変更を保存してから移動しますか？"),
                                          QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                          QMessageBox.StandardButton.Save)
            if answer == QMessageBox.StandardButton.Cancel:
                return False
            if answer == QMessageBox.StandardButton.Save:
                self.pending_action = action
                self.save()
                return True
            self.documents.pop(self.document.path, None)
            self.document = None
            self.canvas.set_document(None)
        action()
        return True

    def open_inputs(self, inputs):
        if self.workspace_host is not None:
            self.workspace_host.open_inputs(inputs, source=self)
            return
        self.load_inputs(inputs)

    def load_inputs(self, inputs):
        """Replace this workspace; the tab host owns the user's open/append choice."""
        if self.busy():
            return
        from .projects import PROJECT_EXTENSIONS
        if len(inputs) == 1 and Path(inputs[0]).is_file() and Path(inputs[0]).suffix.lower() in PROJECT_EXTENSIONS:
            self.open_project(Path(inputs[0]).resolve())
            return
        self.guard(lambda: self._scan(inputs))

    def reload_workspace(self):
        if self.workspace_inputs and not self.busy() and not self.saving:
            self.browse_target = self.browsed_folder()
            self.load_inputs(list(self.workspace_inputs))

    def append_inputs(self, inputs):
        """Add only new paths, keeping decoded documents, edits, selection and filters."""
        if not self.workspace_inputs:
            self.load_inputs(inputs)
            return
        if self.busy() or self.saving:
            return
        try:
            self.remember_workspace()
        except OSError:
            pass
        folders = {Path(raw).resolve() if Path(raw).is_dir() else Path(raw).resolve().parent for raw in inputs}
        journals = [journal for folder in folders for journal in pending_renames(folder)]
        if journals and QMessageBox.question(self, tr("中断した名前変更の復旧"), tr("追加先に未完了の名前変更があります。復旧してから取り込みますか？"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            return
        existing = set(self.model.paths)
        overwrite = self.overwrite.isChecked()
        self.loading = True
        self.update_controls()
        self.info(tr("画像を現在のタブへ取り込み中…"))

        def scan(cancel):
            for journal in journals:
                if journal.exists():
                    check_cancel(cancel)
                    recover_rename(journal)
            paths = [path for path in scan_paths(inputs) if path not in existing]
            if not paths and not any(Path(raw).exists() for raw in inputs):
                raise ImageProblem(tr("追加する画像・フォルダーが見つかりません。"))
            labels, notes, states, indexes, source_receipts = {}, {}, {}, {}, {}
            for path in paths:
                check_cancel(cancel)
                if path.parent not in indexes:
                    indexes[path.parent] = ReviewLabels(path.parent)
                index = indexes[path.parent]
                if label := index.get(path):
                    labels[path] = label
                if note := index.note(path):
                    notes[path] = note
                if overwrite and path.parent not in source_receipts:
                    source_receipts[path.parent] = Receipts(path.parent)
                receipts = source_receipts[path.parent] if overwrite else self.receipts
                record = receipts.get(path, overwrite=overwrite)
                if record and (receipts.folder / record["name"]).is_file():
                    states[path] = "保存済み · 再開可能"
            return paths, labels, notes, states, indexes

        def done(result):
            paths, labels, notes, states, indexes = result
            self.excluded_paths.difference_update(paths)
            self.workspace_inputs = list(dict.fromkeys([*self.workspace_inputs, *[str(Path(raw).resolve()) for raw in inputs]]))
            self.watched_folders.update(Path(raw).resolve() for raw in inputs if Path(raw).is_dir())
            self.sync_watch_scope()
            self.label_indexes.update(indexes)
            self.operation_history = [(kind, [*value, *paths] if kind == "order" else value)
                                      for kind, value in self.operation_history]
            self.model.labels.update(labels)
            self.model.notes.update(notes)
            self.model.states.update(states)
            self.replace_list(self.ordered_paths([*self.model.paths, *paths], self.sort_combo.currentData()))
            self.loading = False
            self.update_controls()
            self.update_summary()
            if not self.document:
                self.ensure_visible_current()
            elif self.auto.isChecked() and self.document.dirty:
                self.autosave_timer.start()
            self.info(tr("現在のタブに追加しました · {count}枚").format(count=len(paths)))

        def failed(message):
            self.loading = False
            self.error(message)
            if self.auto.isChecked() and self.document and self.document.dirty:
                self.autosave_timer.start()

        self.load_job = self.run_job(scan, done, failed)
        self.load_job.signals.cancelled.connect(lambda: failed(tr("取り込みを中止しました。一覧と編集はそのままです。")))

    @staticmethod
    def ordered_paths(paths, order):
        if order == "manual":
            return list(paths)
        key = (lambda path: (path.stat().st_mtime_ns, filename_key(path), str(path))) if order.startswith("date") else (lambda path: (filename_key(path), str(path)))
        return sorted(paths, key=key, reverse=order.endswith("desc"))

    def replace_list(self, paths, mapping=None):
        mapping = mapping or {}
        states = {mapping.get(path, path): state for path, state in self.model.states.items()}
        labels = {mapping.get(path, path): label for path, label in self.model.labels.items()}
        notes = {mapping.get(path, path): note for path, note in self.model.notes.items()}
        selected_paths = [mapping.get(path, path) for path in self.selected_paths()]
        selection = self.list.selectionModel()
        selection.blockSignals(True)
        self.model.set_paths(paths, preserve_cache=True, mapping=mapping)
        self.model.states.update({path: value for path, value in states.items() if path in self.model.rows})
        self.model.labels.update({path: value for path, value in labels.items() if path in self.model.rows})
        self.model.notes.update({path: value for path, value in notes.items() if path in self.model.rows})
        self.proxy.refresh()
        if self.document:
            self.index = self.model.rows[self.document.path]
            self.show_position()
            self._select_current()
        selection.blockSignals(False)
        if selected_paths:
            self.select_paths([path for path in selected_paths if path in self.model.rows])
        self.count_label.setText(tr("画像  {count} 枚").format(count=len(paths)))
        self.update_controls()

    def sort_images(self):
        if not self.model.paths or self.busy() or self.saving:
            return
        try:
            paths = self.ordered_paths(self.model.paths, self.sort_combo.currentData())
        except OSError:
            self.error(tr("画像の更新日時を取得できません。フォルダーを確認してください。"))
            return
        if paths != self.model.paths:
            self.operation_history.append(("order", list(self.model.paths)))
        self.replace_list(paths)

    def show_canvas_menu(self, position):
        """Right-click on the image: the same commands as the ⋯ menu beside its name."""
        if not self.document or self.canvas.stroke:
            return
        self.update_controls()
        self.image_menu.popup(self.canvas.mapToGlobal(position))

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
            indexes = {folder: Receipts(folder) for folder in {path.parent for path in mapping}}
            label_indexes = {folder: ReviewLabels(folder) for folder in {path.parent for path in mapping}}
            if self.receipts:
                indexes[self.receipts.folder] = self.receipts
            for folder in record_folders:
                if folder not in indexes:
                    indexes[folder] = Receipts(folder)
            expected = self.operation_history[-1][1][1] if undoing else None
            rename_images(mapping, cancel=cancel, progress=report, expected_digests=expected, record_folders=set(indexes))
            indexes = {folder: Receipts(folder) for folder in indexes}
            label_indexes = {folder: ReviewLabels(folder) for folder in label_indexes}
            warnings = 0
            label_warnings = 0
            digests = {new: file_digest(new) for new in mapping.values()}
            return indexes, warnings, label_indexes, label_warnings, digests

        def done(result):
            self.batch_job = None
            indexes, warnings, label_indexes, label_warnings, digests = result
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
            self.info(tr("名前を変更しました · {count}枚").format(count=len(mapping)) + (tr(" / 保存記録の更新失敗 {warnings}").format(warnings=warnings) if warnings else "")
                      + (tr(" / ラベル記録の更新失敗 {label_warnings}（再設定してください）").format(label_warnings=label_warnings) if label_warnings else ""))
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

    def begin_batch_progress(self, total):
        self.batch_progress.setRange(0, total)
        self.batch_progress.setValue(0)
        self.batch_progress.show()

    def update_batch_progress(self, completed, total):
        self.batch_progress.setRange(0, total)
        self.batch_progress.setValue(completed)

    def _scan(self, inputs):
        folders = {Path(raw).resolve() if Path(raw).is_dir() else Path(raw).resolve().parent for raw in inputs}
        watched_folders = {Path(raw).resolve() for raw in inputs if Path(raw).is_dir()}
        journals = [journal for folder in folders for journal in pending_renames(folder)]
        if journals:
            answer = QMessageBox.question(self, tr("中断した名前変更の復旧"), tr("中断した名前変更があります。進み具合に応じて元の名前に戻すか、変更後の名前と管理記録をそろえて確定します。復旧しますか？"),
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Yes:
                return
        if self.workspace_inputs:
            try:
                self.remember_workspace()
            except OSError:
                pass
        restoring = self.restoring_workspace is not None
        workspace = self.restoring_workspace if restoring else self.saved_workspace(inputs)
        self.restoring_workspace = None
        excluded = workspace.get("excluded", []) if restoring else []
        self.excluded_paths = {Path(raw) for raw in excluded if isinstance(raw, str)} if isinstance(excluded, list) else set()
        self.loading = True
        self.info(tr("画像一覧を読み込み中…"))
        self.update_controls()
        overwrite = self.overwrite.isChecked()
        order = workspace.get("sort", "name_asc")
        if not isinstance(order, str) or order not in {"manual", "name_asc", "name_desc", "date_asc", "date_desc"}:
            order = "name_asc"
        self.batch_progress.hide()

        def scan(cancel):
            for journal in journals:
                if journal.exists():
                    check_cancel(cancel)
                    recover_rename(journal)
            paths = self.ordered_paths([path for path in scan_paths(inputs) if path not in self.excluded_paths], order)
            stored = workspace.get("order", [])
            if isinstance(stored, list) and order == "manual":
                found = {str(path): path for path in paths}
                restored = [found[raw] for raw in dict.fromkeys(raw for raw in stored if isinstance(raw, str)) if raw in found]
                restored_set = set(restored)
                paths = restored + [path for path in paths if path not in restored_set]
            check_cancel(cancel)
            if not paths and not self.excluded_paths and not any(Path(raw).is_dir() for raw in inputs):
                raise ImageProblem(tr("対応する画像（{format_names}）が見つかりません。").format(format_names=format_names()))
            source_folder = paths[0].parent if paths else next((Path(raw).resolve() for raw in inputs if Path(raw).is_dir()), Path(inputs[0]).resolve().parent)
            from .legacy import default_output_folder
            folder = self.output_folder if self.custom_folder else default_output_folder(source_folder)
            receipts = Receipts(folder)
            indexes = {}
            states = {}
            label_indexes = {}
            labels = {}
            for path in paths:
                check_cancel(cancel)
                if path.parent not in label_indexes:
                    label_indexes[path.parent] = ReviewLabels(path.parent)
                label = label_indexes[path.parent].get(path)
                if label:
                    labels[path] = label
                if overwrite and path.parent not in indexes:
                    indexes[path.parent] = Receipts(path.parent)
                index = indexes[path.parent] if overwrite else receipts
                record = index.get(path, overwrite=overwrite)
                if record and (index.folder / record["name"]).is_file():
                    states[path] = "保存済み · 再開可能"
            return paths, folder, receipts, states, indexes, label_indexes, labels

        def done(result):
            # Model resets and filter invalidation emit selection signals. Keep
            # navigation blocked until the new library is completely installed.
            selection = self.list.selectionModel()
            selection.blockSignals(True)
            paths, self.output_folder, self.receipts, states, self.source_indexes, self.label_indexes, labels = result
            self.index = -1
            self.document = None
            self.canvas.set_document(None)
            self.documents.clear()
            self.owned.clear()
            self.operation_history.clear()
            self.batch_failures.clear()
            self.model.set_paths(paths)
            self.model.states.update(states)
            self.model.labels.update(labels)
            self.model.notes.update({path: self.label_indexes[path.parent].note(path) for path in paths if self.label_indexes[path.parent].note(path)})
            self.workspace_inputs = list(inputs)
            self.watched_folders = watched_folders
            self.sync_watch_scope()
            if not self.settle_folder_root(inputs):
                # A newly opened folder takes its remembered tab name; browsing inside keeps the current one.
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
            self.proxy.refresh()
            self.sort_combo.blockSignals(True)
            self.sort_combo.setCurrentIndex(self.sort_combo.findData(order))
            self.sort_combo.blockSignals(False)
            selection.blockSignals(False)
            self.loading = False
            self.name.clear()
            self.setWindowTitle(f"{next(iter(folders)).name} — Sumīre")
            self.folder_label.setText(str(self.output_folder))
            self.count_label.setText(tr("画像  {count} 枚").format(count=len(paths)))
            self.refresh_folders()
            self.update_page()
            current = workspace.get("current")
            visible = self.visible_paths()
            target = next((path for path in visible if str(path) == current), visible[0] if visible else None)
            if target:
                self._load_index(self.model.rows[target])
            else:
                self.ensure_visible_current()
                self.info(tr("このフォルダーに対応する画像はありません。") if not paths else tr("現在の絞り込みに該当する画像はありません。"))

        def failed(message):
            self.loading = False
            self.error(message)

        self.load_job = self.run_job(scan, done, failed)
        self.load_job.signals.cancelled.connect(self._load_cancelled)

    def show_position(self):
        """「4 / 111」 above the image and its size in the status bar."""
        if self.document is None:
            self.image_size_label.clear()
            return
        self.position_label.set_position(self.index, len(self.model.paths))
        width, height = self.document.image.size
        self.image_size_label.setText(f"{width} × {height}")

    def jump_to_image(self, index):
        """The number typed above the image (1-based on screen)."""
        if 0 <= index < len(self.model.paths):
            if self.model.paths[index] in self.visible_paths():
                self.request_index(index)
            else:
                self.info(tr("{number}枚目は、絞り込みや検索で表示されていません。").format(number=index + 1))
        self.show_position()
        self.canvas.setFocus()

    def request_index(self, index):
        if (index != self.index or self.document is None) and 0 <= index < len(self.model.paths):
            self.guard(lambda: self._load_index(index))
        self._select_current()

    def navigate(self, delta):
        if isinstance(QApplication.focusWidget(), QLineEdit):
            return
        visible = self.visible_paths()
        if self.document and self.document.path in visible:
            row = visible.index(self.document.path) + delta
            if 0 <= row < len(visible):
                self.request_index(self.model.rows[visible[row]])

    def save_next(self):
        if isinstance(QApplication.focusWidget(), QLineEdit):
            # Enter finishes typing in the search or file-name field.
            self.canvas.setFocus()
            return
        if not self.document or self.busy():
            return
        visible = self.visible_paths()
        row = visible.index(self.document.path) + 1 if self.document.path in visible else len(visible)
        self.guard(lambda: self._load_index(self.model.rows[visible[row]]) if row < len(visible) else self.info(tr("最後の画像まで保存しました。")), force_save=True)

    def _select_current(self):
        if self.index >= 0:
            index = self.proxy.mapFromSource(self.model.index(self.index))
            if index.isValid():
                self.list.selectionModel().setCurrentIndex(index, self.list.selectionModel().SelectionFlag.NoUpdate)
                if not self.list.selectionModel().isSelected(index):
                    self.list.selectionModel().select(index, self.list.selectionModel().SelectionFlag.ClearAndSelect)
                self.list.scrollTo(index)

    def _load_index(self, index):
        if not 0 <= index < len(self.model.paths):
            return
        path = self.model.paths[index]
        if path in self.documents:
            self.documents.move_to_end(path)
            self._activate(self.documents[path], index)
            return
        self.loading = True
        self.canvas.locked = True
        self.info(tr("画像を読み込み中…"))
        self.update_controls()
        receipts = self.receipts
        overwrite = self.overwrite.isChecked()
        # A saved file that kept its metadata counts as saved only while metadata is being kept.
        keep_metadata = not self.strip_metadata.isChecked()

        def load(cancel):
            check_cancel(cancel)
            source_digest = file_digest(path)
            index = self.source_index(path) if overwrite else receipts
            record = index.get(path, overwrite=overwrite)
            digest = None
            target = index.folder / record["name"] if record else None
            matches = target is not None and target.is_file() and (source_digest if target == path else file_digest(target)).hex() == record["digest"]
            verified = False
            found = []
            if matches and target == path:
                try:
                    pixels, _ = load_verified_export(path, None, record["format"])
                    verified = True
                except HiddenMetadata:
                    pixels = load_image(path, found)
                    verified = keep_metadata
                document = Document(path, pixels)
            else:
                document = Document(path, load_image(path, None if matches else found))
                if matches:
                    try:
                        document.image, _ = load_verified_export(target, None, record["format"])
                        verified = True
                    except HiddenMetadata:
                        document.image = load_image(target, found)
                        verified = keep_metadata
                    if file_digest(target).hex() != record["digest"]:
                        raise ImageProblem(tr("読み込み中に保存済み画像が変更されました。画像を開き直してください。"))
                    recipe = MaskStore(path.parent).get_geometry(path, bytes.fromhex(record["digest"]), source_digest)
                    if recipe:
                        from .editing import EditSpec, geometry
                        try:
                            base = document.original
                            for step in recipe:
                                base = geometry(base, EditSpec(**step))
                            if base.size != document.image.size:
                                raise ImageProblem(tr("変換手順と出力寸法が一致しません。"))
                            document.original = base
                            document.geometry_steps = recipe
                            document.geometry_edited = True
                        except (TypeError, ValueError, KeyError):
                            raise ImageProblem(tr("保存済み画像の変換手順を確認できません。")) from None
                    elif document.image.size != document.original.size:
                        # The source may have been overwritten since this in-memory
                        # history began. A project retains the full recovery state.
                        document.original = document.image.copy()
                        document.original_edited = True
                        document.geometry_edited = True
                    document.edit_mask = Image.new("L", document.image.size)
            if file_digest(path) != source_digest:
                raise ImageProblem(tr("読み込み中に元画像が変更されました。画像を開き直してください。"))
            document.source_digest = source_digest
            document.geometry_source_digest = source_digest
            if matches:
                document.restore_edit_state(record["edited"], overwrite=overwrite)
                document.output = target
                document.saved_revision = 0 if verified else None
                digest = bytes.fromhex(record["digest"])
            mask = MaskStore(path.parent).get(path, digest or source_digest, document.image.size)
            if mask is not None:
                document.edit_mask = mask
            document.metadata = found
            check_cancel(cancel)
            return document, digest

        def done(result):
            self.loading = False
            document, digest = result
            if digest:
                self.owned[document.output] = digest
            self.documents[path] = document
            self._activate(document, index)
            self._trim_documents()

        def failed(message):
            self.loading = False
            self.model.state(path, "読み込みエラー")
            self.error(message)
            self._select_current()

        self.load_job = self.run_job(load, done, failed)
        self.load_job.signals.cancelled.connect(self._load_cancelled)

    def _load_cancelled(self):
        self.loading = False
        self.info(tr("読み込みを中止しました。"))
        self.update_controls()

    def _trim_documents(self):
        # At most two decoded documents and 256 MiB, excluding current transient workers.
        while len(self.documents) > 1 and (len(self.documents) > 2 or sum(d.memory for d in self.documents.values()) > 256 * 1024 * 1024):
            candidate = next((path for path, doc in self.documents.items() if doc is not self.document and not doc.dirty), None)
            if candidate is None:
                break
            self.documents.pop(candidate)
        if self.workspace_host is not None:
            self.workspace_host.trim_memory()

    def _activate(self, document, index):
        document.last_access = monotonic()
        self.document = document
        self.index = index
        self.save_failed = False
        self.canvas.set_document(document, render=self.workspace_active)
        self.name.setText(document.output.stem if document.output else document.path.stem)
        self._select_current()
        self.show_position()
        self.setWindowTitle(f"{document.path.name} — Sumīre")
        if document.saved_revision == document.revision:
            self.show_saved_state(document)
        else:
            self.model.state(document.path, "編集中 · 保存待ち" if document.edited else "未編集" if document.edit_state is False else "保存記録あり · 再検証待ち")
            self.info(self.ready_hint())
        if self.after_load_message:
            # A result to report once the image reloaded (for example after resetting the list).
            self.info(self.after_load_message)
            self.after_load_message = None
        self.update_controls()
        self.prepare_effect()

    @property
    def memory_usage(self):
        return sum(doc.memory for doc in self.documents.values()) + self.canvas.memory + self.model.cache_memory

    def set_workspace_active(self, active):
        if self.workspace_active == active and (active or self.canvas.image.isNull()):
            return
        self.workspace_active = active
        self.watch_timer.setInterval(1200 if active else 8000)
        if active:
            self.model.resume()
            self.canvas.restore_display()
            self.prepare_effect()
            self.poll_folders()
        else:
            self.effect_generation += 1
            self.effect_restart = False
            self.effect_timer.stop()
            if self.effect_job:
                self.effect_job.cancel.set()
            self.prepared_effect_key = self.pending_effect_key = None
            self.canvas.release_display()
            if self.canvas.stroke is not None:
                self.canvas.cancel_stroke()
            self.model.suspend()

    def show_saved_state(self, document, receipt_ok=True):
        unedited = document.edit_state is False
        metadata = tr("メタデータ：有り") if getattr(document, "metadata", None) else tr("メタデータ：無し")
        self.model.state(document.path, f"未編集 · 保存済み · {metadata}" if unedited else f"保存済み · {metadata}")
        # The top bar shows the saved state and metadata; the status keeps the drawing hint.
        self.info(self.ready_hint() if receipt_ok else tr("画像は保存済み · 再開用の記録を保存できませんでした"))

    def source_index(self, path):
        # Reuse receipt rows across strokes; do not reread a large folder's
        # entire index every time autosave overwrites one image.
        if path.parent not in self.source_indexes:
            self.source_indexes[path.parent] = Receipts(path.parent)
        return self.source_indexes[path.parent]

    def toggle_label(self, label):
        if self.document:
            paths = self.selected_paths() or [self.document.path]
            self.set_review_label(None if all(self.model.labels.get(path) == label for path in paths) else label)

    def set_review_label(self, label):
        self.apply_review_label(label)

    def open_novelai(self, target="novelai"):
        """Prepare a metadata-free PNG of the edited image and hand it over.

        ``target`` "novelai" opens NovelAI and copies the image; "drag" only shows
        the image to drag into a browser, a social site or a chat app.
        """
        if not self.document or self.busy() or self.saving:
            return
        crop, max_size = None, None
        if target == "novelai" and self.novelai_adjust.isChecked():
            adjustment = ImageAdjustmentDialog(self.document.image, self)
            if adjustment.exec() != QDialog.DialogCode.Accepted:
                return
            crop, max_size = adjustment.options()
        if self.novelai_dialog:
            self.novelai_dialog.close()
        # Use the visible editing result, including unsaved edits and Undo.
        pixels, source = self.document.image.copy(), self.document.path
        self.info(tr("NovelAIへ取り込む画像を準備中…") if target == "novelai" else tr("渡す画像を準備中…"))

        def resume():
            self.novelai_job = None
            self.update_controls()
            if self.document and not self.canvas.ready:
                self.effect_timer.start()
            if self.auto.isChecked() and self.document and self.document.dirty:
                self.autosave_timer.start()

        def done(prepared):
            resume()
            dialog = NovelAIImportDialog(prepared, self, target=target)
            self.novelai_dialog = dialog
            dialog.finished.connect(lambda _result: setattr(self, "novelai_dialog", None))
            dialog.show()
            if target == "novelai":
                dialog.copy_image()
                dialog.open_browser()
                self.info(tr("NovelAIに画像を貼り付けるかドラッグし、「Image2Image」を選んでください。"))
            else:
                self.info(tr("画像を、ブラウザーの投稿欄やチャットアプリへドラッグしてください。"))

        def failed(message):
            resume()
            self.error(message)

        self.novelai_job = self.run_job(lambda cancel: prepare_image(pixels, source, cancel, crop=crop, max_size=max_size)
                                      if crop or max_size else prepare_image(pixels, source, cancel), done, failed)
        self.novelai_job.signals.cancelled.connect(lambda: failed(tr("画像の準備を中止しました。")))
        self.update_controls()

    def export_settings_changed(self, *args):
        # New settings create a new owned output, leaving prior output untouched.
        if self.document:
            self.document.output = None
            self.document.saved_revision = None
            if self.document.revision:
                self.model.state(self.document.path, "変更あり · 保存設定を変更")
                if self.auto.isChecked():
                    self.autosave_timer.start()
        self.update_controls()

    def overwrite_changed(self, enabled):
        if self.busy() or self.saving:
            self.overwrite.blockSignals(True)
            self.overwrite.setChecked(not enabled)
            self.overwrite.blockSignals(False)
            return
        self.autosave_timer.stop()
        for document in self.documents.values():
            document.output = None
            document.saved_revision = None
            self.model.state(document.path, "編集中 · 保存先を変更" if document.edited else "未編集" if document.edit_state is False else "保存記録あり · 保存先を変更")
        self.info(tr("次の保存から元画像に上書きします。") if enabled else tr("次の保存から別フォルダーへ出力します。"))
        self.update_controls()

    def choose_output(self):
        if self.busy() or self.saving or self.overwrite.isChecked():
            return
        folder = QFileDialog.getExistingDirectory(self, tr("出力フォルダー"), str(self.output_folder or ""))
        if folder:
            self.output_folder = Path(folder).resolve()
            self.custom_folder = True
            self.receipts = Receipts(self.output_folder)
            self.folder_label.setText(str(self.output_folder))
            for document in self.documents.values():
                document.output = None
                document.saved_revision = None
            self.export_settings_changed()

    def reveal_output(self):
        folder = self.document.path.parent if self.overwrite.isChecked() and self.document else self.output_folder
        if folder and folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def save(self, force=False, strip=False):
        """``strip`` removes metadata even when the save settings keep it."""
        self.autosave_timer.stop()
        if not self.document or self.busy():
            return
        if self.saving:
            self.save_again = True
            return
        document = self.document
        if not force and document.saved_revision == document.revision and document.output:
            self._continue_pending()
            return
        try:
            overwrite = self.overwrite.isChecked()
            if overwrite and getattr(document, "project", False):
                raise ImageProblem(tr("編集プロジェクトの画像は別フォルダーへ保存してください。"))
            format = document.source_format if overwrite else self.format_combo.currentData()
            if overwrite and format not in {"PNG", "JPEG", "WEBP"}:
                raise ImageProblem(tr("上書きできるのはPNG / JPEG / WebPです。この形式は別フォルダーへ保存するか、形式を変換してください。"))
            clipboard = self.is_clipboard_path(document.path)
            if clipboard:
                overwrite = False
                target = self.clipboard_target(document)
                if target is None:
                    self.pending_action = None
                    self.closeCancelled.emit()
                    return
                self.custom_folder = True
                self.output_folder = target.parent
                self.receipts = Receipts(target.parent)
                format = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}[target.suffix.lower()]
            else:
                target = document.path if overwrite else document.output or available_target(self.output_folder, self.name.text().strip(), format)
            # An existing owned output retains its own encoding when the global preset changes.
            if document.output and not overwrite:
                format = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}[target.suffix.lower()]
            if overwrite and not self.confirm_first_overwrite():
                self.pending_action = None
                self.closeCancelled.emit()
                self.info(tr("保存を取りやめました。"))
                return
        except (ImageProblem, OSError) as error:
            self.pending_action = None
            self.error(str(error) if isinstance(error, ImageProblem) else tr("保存先にアクセスできません。フォルダーと書き込み権限を確認してください。"))
            self.closeCancelled.emit()
            return
        revision = document.revision
        edited = document.edit_state
        pixels = document.image.copy()
        mask = document.edit_mask.copy()
        geometry_steps = list(document.geometry_steps)
        geometry_source_digest = document.geometry_source_digest
        jpeg_quality = self.jpeg_quality
        owned_digest = self.owned.get(target)
        source_digest = document.source_digest
        backup_metadata = self.metadata_backup.isChecked() and not getattr(document, "project", False)
        keep_metadata = not (strip or self.strip_metadata.isChecked()) and not getattr(document, "project", False)
        keep_original = originals().keep if overwrite and self.keep_originals.isChecked() else None
        receipts = self.receipts
        self.saving = True
        self.save_failed = False
        self.info(tr("保存中…"))
        self.update_controls()

        def export(cancel):
            previous_key = source_key(document.path) if overwrite else None
            result = save_image(pixels, target, source=document.path, format=format, owned_digest=owned_digest, cancel=cancel,
                                overwrite_source=overwrite, source_digest=source_digest, backup_metadata=backup_metadata,
                                jpeg_quality=jpeg_quality, keep_metadata=keep_metadata, backup=keep_original)
            found = []
            if result.metadata_kept:
                try:
                    found = inspect_metadata(result.path)
                except ImageProblem:
                    found = None
            receipt_ok = True
            try:
                index = self.source_index(document.path) if overwrite else receipts
                index.record(document.path, result, previous_key=previous_key, edited=edited)
            except OSError:
                receipt_ok = False
            try:
                MaskStore(document.path.parent).store(document.path, result.digest, mask)
                if not overwrite:
                    MaskStore(document.path.parent).store_geometry(document.path, result.digest, geometry_steps, geometry_source_digest)
            except OSError:
                receipt_ok = False
            return result, receipt_ok, found

        def done(payload):
            result, receipt_ok, found = payload
            self.saving = False
            self.save_job = None
            document.output = result.path
            document.metadata = found
            document.saved_revision = revision
            self.owned[result.path] = result.digest
            if overwrite:
                document.source_digest = result.digest
                self.model.cache.pop(document.path, None)
            if document.revision == revision:
                self.show_saved_state(document, receipt_ok)
            else:
                self.model.state(document.path, "変更あり · 保存待ち")
            self.update_controls()
            again = self.save_again
            self.save_again = False
            if document.dirty and (self.auto.isChecked() or self.pending_action or again):
                self.save()
            else:
                self._continue_pending()

        def failed(message):
            self.saving = False
            self.save_job = None
            self.save_again = False
            self.pending_action = None
            self.save_failed = True
            self.model.state(document.path, "保存失敗 · 変更を保持")
            self.error(message + tr(" 編集は残っています。「保存」で再試行できます。"))
            self.closeCancelled.emit()

        self.save_job = self.run_job(export, done, failed)
        self.save_job.signals.cancelled.connect(lambda: failed(tr("保存を中止しました。")))

    def _continue_pending(self):
        if self.pending_action:
            action = self.pending_action
            self.pending_action = None
            action()
        self.update_controls()

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

    def confirm_dialog(self, dialog, *, accepted=QMessageBox.StandardButton.Ok):
        # Do not let an already scheduled autosave run inside the confirmation's event loop.
        autosave_pending = self.autosave_timer.isActive()
        self.autosave_timer.stop()
        # These shortcuts belong to a widget containing the dialog. Disable them
        # explicitly so Return reaches the dialog's default Cancel button.
        shortcuts = list(self.shortcuts)
        if self.workspace_host is not None:
            shortcuts.extend(self.workspace_host.shortcuts)
        enabled = [(shortcut, shortcut.isEnabled()) for shortcut in shortcuts]
        for shortcut, _ in enabled:
            shortcut.setEnabled(False)
        try:
            return dialog.exec() == accepted
        finally:
            dialog.deleteLater()
            for shortcut, was_enabled in enabled:
                shortcut.setEnabled(was_enabled)
            if autosave_pending and self.auto.isChecked() and self.document and self.document.dirty:
                self.autosave_timer.start()

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

    def cancel_work(self):
        if self.novelai_job:
            self.novelai_job.cancel.set()
        elif self.batch_job:
            self.batch_job.cancel.set()
        elif self.saving and self.save_job:
            self.save_job.cancel.set()
            self.pending_action = None
        elif self.loading:
            self.load_job.cancel.set()

    def show_help(self):
        self.feature_help()

    def closeEvent(self, event):
        if self.closing:
            event.accept()
            return
        if self.canvas.stroke:
            self.canvas.cancel_stroke()
        if self.loading or self.finalizing or self.batch_job or self.novelai_job:
            event.ignore()
            self.info(tr("処理中は閉じられません。「中止」するか、完了を待ってください。"))
            self.closeCancelled.emit()
            return
        if self.saving:
            event.ignore()
            self.pending_action = self.close
            self.info(tr("保存完了後に終了します…"))
            self.update_controls()
            return
        if self.document and self.document.dirty:
            event.ignore()
            if not self.guard(self._close_after_guard):
                self.closeCancelled.emit()
            return
        self.effect_generation += 1
        self.closing = True
        report = getattr(self, "report_window", None)
        if report is not None:
            try:
                report.close()
            except RuntimeError:
                pass
        self.model.generation += 1
        self.effect_restart = False
        self.effect_timer.stop()
        self.autosave_timer.stop()
        for job in self.jobs:
            job.cancel.set()
        for job in self.model.jobs:
            job.cancel.set()
        self.pool.waitForDone()
        self.model.pool.waitForDone()
        self.watch_timer.stop()
        self.watch_monitor.close()
        self.search_timer.stop()
        self.external_timer.stop()
        try:
            if self.persist_on_close:
                self.remember_workspace()
        except OSError:
            pass
        if self.novelai_dialog:
            self.novelai_dialog.close()
        QApplication.instance().removeEventFilter(self)
        if self.workspace_host is not None:
            self.canvas.set_document(None)
            self.document = None
            self.documents.clear()
            self.model.cache.clear()
        event.accept()
        self.closed.emit(self)

    def _close_after_guard(self):
        # Explicit discard removes the cached document; save makes dirty false.
        if self.document and self.document.path not in self.documents:
            self.document = None
        self.close()

