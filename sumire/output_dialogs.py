"""Dialogs for writing new files: accepted export, conversion, compression and collages."""
from __future__ import annotations
from .i18n import tr

from pathlib import Path
from typing import cast

from PySide6.QtCore import QSize, QThreadPool, QTimer, Qt
from PySide6.QtGui import QIcon, QImage, QPixmap, QStandardItemModel
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QRadioButton, QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from .collage import MAX_COLLAGE, CollageSpec, FreeLayout, check_canvas, collage_layouts, render_collage, render_free_collage
from .convert import Encoding, TARGETS, encode, prepared_pixels, size_summary, writable
from .watermark import MAX_SIZE as MARK_MAX, MIN_SIZE as MARK_MIN, POSITIONS, Watermark, preview as watermark_preview
from .editing import UPSCALE_FACTORS, upscaled_size
from .imaging import HEIF_PLUGIN, MAX_DIMENSION, ImageProblem
from .organize import sequence_stems
from .ui import ElidedLabel
from .workers import Job

INVALID = '<>:"/\\|?*'


def faint(text):
    label = QLabel(text)
    label.setObjectName("faint")
    label.setWordWrap(True)
    return label


def folder_name_problem(name):
    if (not name or name in {".", ".."} or name.endswith((".", " ")) or any(c in name for c in INVALID)
            or any(ord(c) < 32 for c in name)):
        return tr("フォルダー名に使えない文字が含まれています。")
    return ""


def dialog_buttons(dialog, ok_text):
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
    ok.setText(ok_text)
    ok.setObjectName("primary")
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("キャンセル"))
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    return buttons, ok


class DestinationChooser(QWidget):
    """A new folder inside the current folder (default), or any folder the user picks."""

    def __init__(self, parent_folder: Path, default_name: str, parent=None):
        super().__init__(parent)
        self.parent_folder = Path(parent_folder)
        self.chosen: Path | None = None
        # Several fixed folder names (one per label) made inside the destination instead of one named folder.
        self.fixed_names: list[str] | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.group = QButtonGroup(self)
        self.inside = QRadioButton(tr("現在のフォルダー内に新しいフォルダーを作る"))
        self.inside.setChecked(True)
        self.elsewhere = QRadioButton(tr("保存先を選ぶ"))
        self.group.addButton(self.inside)
        self.group.addButton(self.elsewhere)
        layout.addWidget(self.inside)
        row = QHBoxLayout()
        row.setContentsMargins(26, 0, 0, 0)
        row.addWidget(QLabel(tr("フォルダー名")))
        self.name = QLineEdit(default_name)
        self.name.setAccessibleName(tr("新しいフォルダーの名前"))
        row.addWidget(self.name, 1)
        layout.addLayout(row)
        self.inside_path = ElidedLabel()
        self.inside_path.setObjectName("faint")
        indented = QHBoxLayout()
        indented.addSpacing(26)
        indented.addWidget(self.inside_path, 1)
        layout.addLayout(indented)
        layout.addWidget(self.elsewhere)
        pick = QHBoxLayout()
        pick.setContentsMargins(26, 0, 0, 0)
        self.chosen_label = ElidedLabel(tr("未選択"))
        self.chosen_label.setObjectName("faint")
        pick.addWidget(self.chosen_label, 1)
        self.browse = QPushButton(tr("参照…"))
        self.browse.clicked.connect(self.pick_folder)
        pick.addWidget(self.browse)
        layout.addLayout(pick)
        self.name.textChanged.connect(self.refresh)
        self.group.buttonToggled.connect(self.refresh)
        self.refresh()

    def pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr("保存先のフォルダー"), str(self.chosen or self.parent_folder))
        if folder:
            self.chosen = Path(folder).resolve()
            self.elsewhere.setChecked(True)
        self.refresh()

    def set_fixed_names(self, names):
        """Make a folder per name inside the destination (``None``: one folder named in the field)."""
        self.fixed_names = list(names) if names else None
        self.inside.setText(tr("現在のフォルダー内に作る") if self.fixed_names else tr("現在のフォルダー内に新しいフォルダーを作る"))
        self.name.setVisible(self.fixed_names is None)
        self.refresh()

    def refresh(self, *_args):
        if self.fixed_names:
            text = tr("{folder} の中に {names}").format(folder=self.parent_folder, names=" · ".join(self.fixed_names))
        else:
            name = self.name.text().strip()
            problem = folder_name_problem(name)
            exists = (self.parent_folder / name).is_dir() if not problem else False
            text = problem or (tr("既にあるフォルダーに追加：") if exists else "") + str(self.parent_folder / name)
        self.inside_path.setText(text)
        self.inside_path.setToolTip(text)
        self.chosen_label.setText(str(self.chosen) if self.chosen else tr("未選択"))
        self.chosen_label.setToolTip(str(self.chosen) if self.chosen else "")
        self.name.setEnabled(self.inside.isChecked())

    def problem(self):
        if self.inside.isChecked():
            return "" if self.fixed_names else folder_name_problem(self.name.text().strip())
        return "" if self.chosen else tr("保存先のフォルダーを選んでください。")

    def destination(self) -> Path:
        """The folder to write into; with fixed names, the folder that will hold them."""
        problem = self.problem()
        if problem:
            raise ImageProblem(problem)
        if self.inside.isChecked():
            return self.parent_folder.resolve() if self.fixed_names else (self.parent_folder / self.name.text().strip()).resolve()
        assert self.chosen is not None  # problem() reports a folder not chosen yet
        return self.chosen


class LabelExportDialog(QDialog):
    """Move or copy the images of one label, or of every label into a folder per label.

    ``counts`` is {label: number of images}. Moving takes the image files as they
    are (no conversion); copying writes the edited images without metadata.
    """

    def __init__(self, counts, parent_folder, current_format="PNG", parent=None):
        super().__init__(parent)
        from .labels import REVIEW_LABELS
        self.labels = REVIEW_LABELS
        self.counts = counts
        self.setWindowTitle(tr("ラベルごとに書き出す"))
        self.setMinimumWidth(540)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("ラベル")))
        self.label_combo = QComboBox()
        for label, text in REVIEW_LABELS.items():
            self.label_combo.addItem(tr("{text}（{count}枚）").format(text=text, count=counts.get(label, 0)), label)
        self.label_combo.addItem(tr("すべてのラベル（採用・保留・不採用のフォルダーに分ける · {count}枚）").format(
            count=sum(counts.values())), "all")
        for index in range(self.label_combo.count()):
            label = self.label_combo.itemData(index)
            empty = sum(counts.values()) == 0 if label == "all" else not counts.get(label)
            self.label_combo.model().item(index).setEnabled(not empty)
        first = next((label for label in REVIEW_LABELS if counts.get(label)), "accepted")
        self.label_combo.setCurrentIndex(self.label_combo.findData(first))
        row.addWidget(self.label_combo, 1)
        layout.addLayout(row)
        self.move = QCheckBox(tr("元画像を移動する"))
        self.move.setChecked(True)
        layout.addWidget(self.move)
        self.move_note = faint("")
        self.move_note.setContentsMargins(26, 0, 0, 0)
        layout.addWidget(self.move_note)
        self.chooser = DestinationChooser(parent_folder, REVIEW_LABELS[first], self)
        self.named = REVIEW_LABELS[first]
        layout.addWidget(self.chooser)
        self.renumber = QCheckBox(tr("連番に振り直す（一覧の順）"))
        self.renumber.setChecked(True)
        layout.addWidget(self.renumber)
        self.names = faint("")
        self.names.setContentsMargins(26, 0, 0, 0)
        layout.addWidget(self.names)
        format_row = QHBoxLayout()
        self.format_label = QLabel(tr("形式"))
        format_row.addWidget(self.format_label)
        self.format_combo = QComboBox()
        for text, value in ((tr("元の形式のまま（PNG / JPEG / WebP。その他はPNG）"), "SOURCE"), ("PNG", "PNG"), ("JPEG", "JPEG"), (tr("WebP（可逆）"), "WEBP")):
            self.format_combo.addItem(text, value)
        format_row.addWidget(self.format_combo, 1)
        layout.addLayout(format_row)
        self.problem = QLabel()
        self.problem.setObjectName("danger")
        layout.addWidget(self.problem)
        buttons, self.ok = dialog_buttons(self, tr("移動する"))
        layout.addWidget(buttons)
        self.label_combo.currentIndexChanged.connect(self.label_changed)
        for signal in (self.renumber.toggled, self.move.toggled, self.chooser.name.textChanged, self.chooser.group.buttonToggled):
            signal.connect(self.refresh)
        self.chooser.browse.clicked.connect(self.refresh)
        self.label_changed()

    def label(self):
        return self.label_combo.currentData()

    def selected_labels(self):
        return [label for label in self.labels if self.counts.get(label)] if self.label() == "all" else [self.label()]

    def moving(self):
        return self.move.isChecked()

    def format(self):
        return self.format_combo.currentData()

    def label_changed(self, *_args):
        label = self.label()
        if label == "all":
            self.chooser.set_fixed_names([self.labels[name] for name in self.selected_labels()])
        else:
            # Follow the label in the folder name until the user types their own.
            if self.chooser.name.text().strip() in (self.named, *self.labels.values()):
                self.chooser.name.setText(self.labels[label])
            self.named = self.labels[label]
            self.chooser.set_fixed_names(None)
        self.refresh()

    def refresh(self, *_args):
        moving = self.moving()
        self.move_note.setText(tr("画像ファイルをそのまま移します（形式の変換・メタデータの削除はしません）。ラベルとメモも一緒に移り、「直前の整理操作を戻す」で戻せます。")
                               if moving else
                               tr("編集後の画像を、メタデータを削除して新しいファイルに書き出します。元画像は変わりません。"))
        for widget in (self.format_label, self.format_combo):
            widget.setEnabled(not moving)
        count = sum(self.counts.get(label, 0) for label in self.selected_labels())
        largest = max([self.counts.get(label, 0) for label in self.selected_labels()] or [0])
        if self.renumber.isChecked():
            stems = sequence_stems(max(1, largest))
            sample = stems[0] if len(stems) == 1 else f"{stems[0]}, {stems[1]}" + (f" … {stems[-1]}" if len(stems) > 2 else "")
            self.names.setText(tr("名前：{sample}（フォルダーごとに桁数をそろえます）").format(sample=sample))
        else:
            self.names.setText(tr("元の名前のまま（同名のファイルがあれば _2 などを付けます）"))
        self.ok.setText(tr("{count}枚を移動する").format(count=count) if moving else tr("{count}枚を書き出す").format(count=count))
        problem = self.chooser.problem() or ("" if count else tr("このラベルの画像がありません。"))
        self.problem.setText(problem)
        self.ok.setEnabled(not problem)

    def destinations(self):
        """{label: folder} for the chosen label(s)."""
        folder = self.chooser.destination()
        if self.label() == "all":
            return {label: folder / self.labels[label] for label in self.selected_labels()}
        return {self.label(): folder}


class MergeLabelFoldersDialog(QDialog):
    """Gather the images of the label folders (採用・保留・不採用) into one folder."""

    def __init__(self, root: Path, counts: dict, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self.setWindowTitle(tr("ラベルのフォルダーをまとめる"))
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        total = sum(counts.values())
        layout.addWidget(QLabel(tr("{folders}つのフォルダーの画像 {count} 枚を、1つのフォルダーにまとめます。").format(folders=len(counts), count=total)))
        layout.addWidget(faint("、".join(tr("{name}（{count}枚）").format(name=folder.name, count=count) for folder, count in counts.items())))
        self.group = QButtonGroup(self)
        self.back = QRadioButton(tr("「{name}」に戻す").format(name=self.root.name or str(self.root)))
        self.new = QRadioButton(tr("新しいフォルダーにまとめる"))
        self.back.setChecked(True)
        for button in (self.back, self.new):
            self.group.addButton(button)
            layout.addWidget(button)
        self.name = QLineEdit(tr("まとめ"))
        self.name.setContentsMargins(26, 0, 0, 0)
        layout.addWidget(self.name)
        self.remove_empty = QCheckBox(tr("空になったラベルのフォルダーを削除する"))
        self.remove_empty.setChecked(True)
        layout.addWidget(self.remove_empty)
        layout.addWidget(faint(tr("画像ファイルはそのまま移し、ラベル・メモ・タグも一緒に移ります。同じ名前の画像があれば _2 などを付けます。"
                                  "「直前の整理操作を戻す」で元のフォルダーに戻せます。ほかのファイルが残ったフォルダーは削除しません。")))
        self.problem = QLabel()
        self.problem.setObjectName("danger")
        layout.addWidget(self.problem)
        buttons, self.ok = dialog_buttons(self, tr("{count}枚をまとめる").format(count=total))
        layout.addWidget(buttons)
        self.group.buttonToggled.connect(self.refresh)
        self.name.textChanged.connect(self.refresh)
        self.refresh()

    def refresh(self, *_args):
        self.name.setEnabled(self.new.isChecked())
        problem = folder_name_problem(self.name.text().strip()) if self.new.isChecked() else ""
        if not problem and self.new.isChecked() and (self.root / self.name.text().strip()).exists():
            target = self.root / self.name.text().strip()
            problem = "" if target.is_dir() and not target.is_symlink() else tr("同じ名前のファイルがあります。別の名前にしてください。")
        self.problem.setText(problem)
        self.ok.setEnabled(not problem)

    def destination(self) -> Path:
        return self.root / self.name.text().strip() if self.new.isChecked() else self.root


COMPRESS_OPTIONS = (
    # key, title, note, encoding, lossy
    ("png", tr("PNGを最適化"), tr("画素はそのまま、圧縮をやり直します。256色以下ならパレット化します。"), Encoding("PNG"), False),
    ("webp_lossless", tr("WebP（可逆）"), tr("画素はそのまま。多くの場合PNGより小さくなります。"), Encoding("WEBP", lossless=True), False),
    ("jpeg", "JPEG", tr("写真向け。透過部分は白になります。"), Encoding("JPEG", quality=85), True),
    ("webp", tr("WebP（非可逆）"), tr("透過を保ったまま小さくします。"), Encoding("WEBP", quality=80), True),
    ("avif", "AVIF", tr("最も小さくなりやすい形式です。透過を保ちます。"), Encoding("AVIF", quality=60), True),
    ("png_colors", tr("PNGの色数を減らす"), tr("256色に減色します。イラスト向けです。"), Encoding("PNG", colors=256), True),
)

CONVERT_NOTES = {
    "PNG": tr("可逆 · 透過を保持"),
    "JPEG": tr("非可逆 · 透過は白背景"),
    "WEBP": tr("可逆または非可逆 · 透過を保持"),
    "AVIF": tr("非可逆 · 高圧縮 · 透過を保持"),
    "BMP": tr("可逆 · 無圧縮 · 透過は白背景"),
    "TIFF": tr("可逆（Deflate圧縮）· 透過を保持"),
    "GIF": tr("256色まで · 透過は1色のみ"),
    "HEIF": tr("非可逆 · 高圧縮"),
}


class ConvertDialog(QDialog):
    """Format conversion (``mode="convert"``) or size reduction (``mode="compress"``).

    ``sample`` is (name, original byte size, callable returning pixels) for the
    first image; its result is encoded in the background to show the real size.
    """

    def __init__(self, mode, count, parent_folder, sample, *, backup=True, source_format=None, keep_originals=True,
                 watermark: Watermark | None = None, watermark_on=False, size_limit_kb=2048, size_limit_on=False, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.count = count
        self.sample_name, self.sample_size, self.sample_pixels = sample
        self.pixels = None
        self.generation = 0
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.job = None
        compress = mode == "compress"
        self.setWindowTitle(tr("容量削減") if compress else tr("形式を変換"))
        self.setMinimumWidth(620)
        outer = QVBoxLayout(self)
        outer.setSpacing(8)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        intro = QLabel(tr("{count}枚を{value}ファイルとして書き出します。\n編集内容を含み、メタデータは含めません。元画像は変わりません。").format(count=count, value=tr('小さくした') if compress else tr('新しい形式の')))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.option_group = QButtonGroup(self)
        self.options = {}
        if compress:
            for lossy, heading in ((False, tr("画質を保つ（可逆）")), (True, tr("画質が変わる可能性あり（非可逆）"))):
                title = QLabel(heading)
                title.setObjectName("section")
                layout.addWidget(title)
                for key, text, note, encoding, is_lossy in COMPRESS_OPTIONS:
                    if is_lossy != lossy:
                        continue
                    button = QRadioButton(text)
                    button.setToolTip(note)
                    self.option_group.addButton(button)
                    self.options[key] = (button, encoding)
                    row = QHBoxLayout()
                    row.addWidget(button)
                    row.addWidget(faint(note), 1)
                    layout.addLayout(row)
            default = "png" if source_format == "PNG" else "jpeg"
            self.options[default][0].setChecked(True)
        else:
            row = QHBoxLayout()
            row.addWidget(QLabel(tr("変換後の形式")))
            self.format_combo = QComboBox()
            for format, (label, extension) in TARGETS.items():
                self.format_combo.addItem(tr("{label}（{extension}） · {CONVERT_NOTES}").format(label=label, extension=extension, CONVERT_NOTES=CONVERT_NOTES[format]), format)
                if not writable(format):
                    item = cast(QStandardItemModel, self.format_combo.model()).item(self.format_combo.count() - 1)
                    item.setEnabled(False)
                    item.setToolTip(tr("HEICは、ライセンスの都合で同梱していないため書き出せません。")
                                    if not HEIF_PLUGIN else tr("導入済みのHEIFモジュールは読み込み専用です。"))
            self.format_combo.setCurrentIndex(self.format_combo.findData("WEBP" if source_format != "WEBP" else "PNG"))
            row.addWidget(self.format_combo, 1)
            layout.addLayout(row)
            self.lossless = QCheckBox(tr("WebPを可逆で書き出す（画質を保つ）"))
            self.lossless.setChecked(True)
            layout.addWidget(self.lossless)
        quality_row = QHBoxLayout()
        self.quality_label = QLabel(tr("品質"))
        quality_row.addWidget(self.quality_label)
        self.quality = QSlider(Qt.Orientation.Horizontal)
        self.quality.setRange(1, 100)
        self.quality.setAccessibleName(tr("品質"))
        quality_row.addWidget(self.quality, 1)
        self.quality_value = QLabel()
        self.quality_value.setMinimumWidth(36)
        quality_row.addWidget(self.quality_value)
        layout.addLayout(quality_row)
        self.quality_note = faint(tr("数値が大きいほど画質が良く、ファイルは大きくなります。"))
        layout.addWidget(self.quality_note)
        resize_row = QHBoxLayout()
        self.shrink = QCheckBox(tr("長辺を次の大きさ以下に縮小（非可逆）"))
        resize_row.addWidget(self.shrink)
        self.max_side = QSpinBox()
        self.max_side.setRange(16, 32768)
        self.max_side.setValue(2048)
        self.max_side.setSuffix(" px")
        resize_row.addWidget(self.max_side)
        resize_row.addStretch(1)
        layout.addLayout(resize_row)
        # A cap on the file size (for sites with an upload limit).
        limit_row = QHBoxLayout()
        self.size_limit = QCheckBox(tr("ファイルサイズの上限"))
        limit_row.addWidget(self.size_limit)
        self.size_limit_value = QSpinBox()
        self.size_limit_value.setRange(10, 1024 * 1024)
        self.size_limit_value.setSingleStep(100)
        self.size_limit_value.setSuffix(" KB")
        self.size_limit_value.setValue(max(10, min(1024 * 1024, int(size_limit_kb))))
        self.size_limit_value.setAccessibleName(tr("ファイルサイズの上限（KB）"))
        limit_row.addWidget(self.size_limit_value)
        limit_row.addStretch(1)
        layout.addLayout(limit_row)
        self.size_limit_note = faint(tr("上限を超えるときは、非可逆の形式なら画質を下げ、それでも大きければ画像を縮小します。1MB = 1024KB。"))
        self.size_limit_note.setContentsMargins(26, 0, 0, 0)
        layout.addWidget(self.size_limit_note)
        self.size_limit.setChecked(size_limit_on)
        self.build_watermark(layout, watermark or Watermark(), watermark_on)
        layout.addWidget(QLabel(tr("保存先")))
        self.chooser = DestinationChooser(parent_folder, tr("圧縮済み") if compress else tr("変換済み"), self)
        layout.addWidget(self.chooser)
        # Size reduction can also replace the originals, for images whose format stays the same.
        self.replace = QCheckBox(tr("元画像に上書きする（形式が変わらない画像だけ）"))
        self.replace.setVisible(compress)
        layout.addWidget(self.replace)
        self.replace_note = faint("")
        self.replace_note.setContentsMargins(26, 0, 0, 0)
        self.keep_originals = keep_originals
        layout.addWidget(self.replace_note)
        layout.addWidget(faint(tr("元画像のメタデータは書き出したファイルに含めません。")
                               + (tr("復元用に、管理記録へ圧縮して保存します（暗号化なし）。") if backup
                                  else tr("復元用の退避はオフです（保存方法の設定）。"))))
        layout.addStretch(1)
        self.estimate = QLabel()
        self.estimate.setObjectName("estimate")
        self.estimate.setWordWrap(True)
        outer.addWidget(self.estimate)
        self.preview = QLabel()
        self.preview.setObjectName("editPreview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setAccessibleName(tr("透かしの見本"))
        self.preview.hide()
        outer.addWidget(self.preview)
        self.problem = QLabel()
        self.problem.setObjectName("danger")
        self.problem.setWordWrap(True)
        outer.addWidget(self.problem)
        buttons, self.ok = dialog_buttons(self, tr("容量を削減する") if compress else tr("変換する"))
        outer.addWidget(buttons)
        available = self.screen().availableGeometry()
        content.adjustSize()
        self.resize(max(620, content.sizeHint().width() + 40),
                    min(content.sizeHint().height() + 150, available.height() - 80))
        self.last_quality: dict[str, int] = {}
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.run_estimate)
        self.option_group.buttonToggled.connect(lambda *_args: self.option_changed())
        if not compress:
            self.format_combo.currentIndexChanged.connect(lambda *_args: self.option_changed())
            self.lossless.toggled.connect(lambda *_args: self.option_changed())
        self.quality.valueChanged.connect(self.quality_changed)
        self.shrink.toggled.connect(self.settings_changed)
        self.max_side.valueChanged.connect(self.settings_changed)
        self.size_limit.toggled.connect(self.settings_changed)
        self.size_limit_value.valueChanged.connect(self.settings_changed)
        for signal in (self.mark_on.toggled, self.mark_text.textChanged, self.mark_position.currentIndexChanged,
                       self.mark_size.valueChanged, self.mark_opacity.valueChanged, self.mark_color.currentIndexChanged,
                       self.mark_shadow.toggled):
            signal.connect(self.settings_changed)
        self.mark_on.toggled.connect(self.refresh_problem)
        self.chooser.name.textChanged.connect(self.refresh_problem)
        self.chooser.group.buttonToggled.connect(self.refresh_problem)
        self.chooser.browse.clicked.connect(self.refresh_problem)
        self.replace.toggled.connect(self.refresh_problem)
        self.option_group.buttonToggled.connect(lambda *_args: self.refresh_problem())
        self.option_changed()
        self.refresh_problem()

    def base_encoding(self) -> Encoding:
        if self.mode == "compress":
            return next(encoding for button, encoding in self.options.values() if button.isChecked())
        format = self.format_combo.currentData()
        if format == "WEBP" and self.lossless.isChecked():
            return Encoding("WEBP", lossless=True)
        return Encoding(format, quality={"JPEG": 90, "WEBP": 85, "AVIF": 65, "HEIF": 65}.get(format))

    def encoding(self) -> Encoding:
        base = self.base_encoding()
        quality = self.quality.value() if base.quality is not None else None
        return Encoding(base.format, quality=quality, lossless=base.lossless, colors=base.colors,
                        max_side=self.max_side.value() if self.shrink.isChecked() else None,
                        max_bytes=self.size_limit_value.value() * 1024 if self.size_limit.isChecked() else None,
                        watermark=self.watermark() if self.mark_on.isChecked() else None)

    # --- watermark and signature ---------------------------------------------------------------

    def build_watermark(self, layout, mark: Watermark, on: bool):
        self.mark_on = QCheckBox(tr("透かし・署名を入れる"))
        self.mark_on.setToolTip(tr("書き出す画像にだけ入れます。元画像と、Sumīreで開いている画像は変わりません。"))
        layout.addWidget(self.mark_on)
        self.mark_box = QWidget()
        form = QFormLayout(self.mark_box)
        form.setContentsMargins(26, 0, 0, 0)
        form.setSpacing(6)
        self.mark_text = QLineEdit(mark.text)
        self.mark_text.setMaxLength(200)
        self.mark_text.setPlaceholderText(tr("例：© 2026 名前"))
        form.addRow(tr("文字"), self.mark_text)
        image_row = QHBoxLayout()
        self.mark_image = mark.image
        self.mark_image_label = ElidedLabel()
        self.mark_image_label.setObjectName("muted")
        image_row.addWidget(self.mark_image_label, 1)
        choose = QPushButton(tr("選ぶ…"))
        choose.clicked.connect(self.choose_signature)
        image_row.addWidget(choose)
        self.mark_image_clear = QPushButton(tr("外す"))
        self.mark_image_clear.clicked.connect(lambda: self.set_signature(None))
        image_row.addWidget(self.mark_image_clear)
        form.addRow(tr("署名の画像"), image_row)
        self.mark_position = QComboBox()
        for key, text in POSITIONS.items():
            self.mark_position.addItem(text, key)
        self.mark_position.setCurrentIndex(max(0, self.mark_position.findData(mark.position)))
        form.addRow(tr("位置"), self.mark_position)
        self.mark_size = QSpinBox()
        self.mark_size.setRange(MARK_MIN, MARK_MAX)
        self.mark_size.setValue(mark.size)
        self.mark_size.setSuffix(" %")
        self.mark_size.setToolTip(tr("透かしの高さを、画像の長辺に対する割合で指定します。"))
        form.addRow(tr("大きさ（長辺に対して）"), self.mark_size)
        self.mark_opacity = QSpinBox()
        self.mark_opacity.setRange(5, 100)
        self.mark_opacity.setValue(mark.opacity)
        self.mark_opacity.setSuffix(" %")
        form.addRow(tr("不透明度"), self.mark_opacity)
        self.mark_color = QComboBox()
        for text, value in ((tr("白"), "#ffffff"), (tr("黒"), "#000000"), (tr("灰色"), "#808080")):
            self.mark_color.addItem(text, value)
        if self.mark_color.findData(mark.color) < 0:
            self.mark_color.addItem(mark.color, mark.color)
        self.mark_color.setCurrentIndex(self.mark_color.findData(mark.color))
        form.addRow(tr("文字の色"), self.mark_color)
        self.mark_shadow = QCheckBox(tr("影を付けて読みやすくする"))
        self.mark_shadow.setChecked(mark.shadow)
        form.addRow("", self.mark_shadow)
        layout.addWidget(self.mark_box)
        layout.addWidget(faint(tr("署名の画像があるときは、文字の代わりに画像を入れます。透明な背景のPNGがおすすめです。")))
        self.set_signature(mark.image, refresh=False)
        self.mark_on.setChecked(on)
        self.mark_box.setEnabled(on)
        self.mark_on.toggled.connect(self.mark_box.setEnabled)

    def choose_signature(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("署名の画像を選ぶ"), str(Path(self.mark_image).parent) if self.mark_image else "",
                                              tr("画像 (*.png *.webp *.jpg *.jpeg *.bmp *.tif *.tiff *.gif)"))
        if path:
            self.set_signature(path)

    def set_signature(self, path, refresh=True):
        self.mark_image = path or None
        self.mark_image_label.setText(Path(path).name if path else tr("なし（文字を入れます）"))
        self.mark_image_clear.setEnabled(bool(path))
        self.mark_text.setEnabled(not path)
        self.mark_color.setEnabled(not path)
        if refresh:
            self.settings_changed()

    def watermark(self) -> Watermark:
        return Watermark(text=self.mark_text.text(), image=self.mark_image, position=self.mark_position.currentData(),
                         size=self.mark_size.value(), opacity=self.mark_opacity.value(), color=self.mark_color.currentData(),
                         shadow=self.mark_shadow.isChecked())

    def watermark_settings(self):
        """(settings, on) to remember for the next export."""
        return self.watermark().to_settings(), self.mark_on.isChecked()

    def option_changed(self):
        base = self.base_encoding()
        uses_quality = base.quality is not None
        for widget in (self.quality_label, self.quality, self.quality_value, self.quality_note):
            widget.setVisible(uses_quality)
        if self.mode == "convert":
            self.lossless.setVisible(self.format_combo.currentData() == "WEBP")
        if uses_quality:
            self.quality.blockSignals(True)
            self.quality.setValue(self.last_quality.get(base.format, base.quality))
            self.quality.blockSignals(False)
            self.quality_value.setText(str(self.quality.value()))
        self.settings_changed()

    def quality_changed(self, value):
        self.quality_value.setText(str(value))
        self.last_quality[self.base_encoding().format] = value
        self.settings_changed()

    def settings_changed(self, *_args):
        encoding = self.encoding()
        kind = tr("非可逆（画質が変わる可能性があります）") if encoding.lossy else tr("可逆（画質は変わりません）")
        self.estimate.setText(tr("{kind}\n{value}試算中…").format(kind=kind, value=tr('1枚目の') if self.count > 1 else ''))
        self.generation += 1
        self.timer.start()

    def run_estimate(self):
        generation, encoding = self.generation, self.encoding()
        if self.job is not None:
            self.job.cancel.set()
        def work(cancel):
            if self.pixels is None:
                self.pixels = self.sample_pixels()
            size = len(encode(self.pixels, encoding))
            mark = encoding.watermark
            picture = watermark_preview(prepared_pixels(self.pixels, Encoding(max_side=encoding.max_side)), mark, 240) \
                if mark is not None and not mark.empty else None
            return size, picture
        job = self.job = Job(work)
        job.signals.done.connect(lambda result: self.show_estimate(generation, *result))
        job.signals.failed.connect(lambda message: self.show_estimate(generation, None, None, message))
        self.pool.start(job)

    def show_estimate(self, generation, size, picture=None, message=""):
        if generation != self.generation:
            return
        if size is not None:
            self.show_preview(picture)
        encoding = self.encoding()
        kind = tr("非可逆（画質が変わる可能性があります）") if encoding.lossy else tr("可逆（画質は変わりません）")
        if size is None:
            self.estimate.setText(tr("{kind}\n試算できません：{message}").format(kind=kind, message=message))
            return
        label = tr("圧縮後") if self.mode == "compress" else tr("変換後")
        prefix = tr("1枚目（{sample_name}）の試算：").format(sample_name=self.sample_name) if self.count > 1 else ""
        self.estimate.setText(f"{kind}\n{prefix}{size_summary(self.sample_size, size, label)}")

    def show_preview(self, picture):
        """The first image with the watermark, small, so its place and size can be judged."""
        if picture is None:
            self.preview.hide()
            return
        data = picture.convert("RGBA")
        image = QImage(data.tobytes(), data.width, data.height, data.width * 4, QImage.Format.Format_RGBA8888).copy()
        self.preview.setPixmap(QPixmap.fromImage(image))
        self.preview.setFixedHeight(data.height + 12)
        self.preview.show()

    def replace_originals(self) -> bool:
        return self.mode == "compress" and self.replace.isChecked()

    def refresh_problem(self, *_args):
        replace = self.replace_originals()
        self.chooser.setEnabled(not replace)
        if replace:
            name = TARGETS[self.base_encoding().format][0]
            self.replace_note.setText(tr("{name}の画像だけを、小さくした画像で置き換えます（ほかの形式の画像は変えません）。").format(name=name)
                                      + (tr("置き換える前の元画像は、アプリの終了まで残します。") if self.keep_originals
                                         else tr("置き換える前の元画像は残りません。")))
        self.replace_note.setVisible(replace)
        problem = "" if replace else self.chooser.problem()
        if replace and self.mark_on.isChecked():
            problem = tr("透かしを入れるときは、元画像に上書きできません。新しいフォルダーへ書き出してください。")
        self.problem.setText(problem)
        self.ok.setEnabled(not problem)

    def destination(self):
        return None if self.replace_originals() else self.chooser.destination()

    def done(self, result):
        self.generation += 1
        if self.job is not None:
            self.job.cancel.set()
        self.timer.stop()
        self.pool.waitForDone()
        super().done(result)


class CopyAreaDialog(QDialog):
    """「加工の範囲をほかの画像へ写す」: which images, which tool, and how the area is placed.

    ``targets`` is [(key, title, paths)] (the selected images, the images in the list…);
    ``picture`` and ``mask`` are the shown image and its processed area, for the preview.
    """

    def __init__(self, targets, picture, mask, mode, tools, save_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("加工の範囲をほかの画像へ写す"))
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        intro = QLabel(tr("表示中の画像で加工した範囲（マスクの範囲）を、ほかの画像の同じ場所に写して加工し、保存します。"))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        preview = QLabel()
        preview.setObjectName("editPreview")
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setPixmap(QPixmap.fromImage(area_picture(picture, mask)))
        preview.setAccessibleName(tr("写す範囲"))
        layout.addWidget(preview)
        form = QFormLayout()
        form.setSpacing(8)
        self.target_group = QButtonGroup(self)
        target_box = QVBoxLayout()
        self.targets = {}
        for key, title, paths in targets:
            button = QRadioButton(tr("{title}（{count}枚）").format(title=title, count=len(paths)))
            button.setEnabled(bool(paths))
            self.target_group.addButton(button)
            self.targets[key] = (button, paths)
            target_box.addWidget(button)
        first = next((button for button, paths in self.targets.values() if paths), None)
        if first is not None:
            first.setChecked(True)
        form.addRow(tr("写す先"), target_box)
        self.tool = QComboBox()
        for key, text in tools:
            self.tool.addItem(text, key)
        self.tool.setCurrentIndex(max(0, self.tool.findData(mode)))
        form.addRow(tr("加工"), self.tool)
        self.placement = QComboBox()
        self.placement.addItem(tr("画像の大きさに合わせる（同じ割合の位置）"), "relative")
        self.placement.addItem(tr("同じ画素の位置（左上をそろえる）"), "pixels")
        self.placement.setToolTip(tr("大きさの違う画像では、「画像の大きさに合わせる」で範囲も同じ割合で伸び縮みします。"))
        form.addRow(tr("位置"), self.placement)
        layout.addLayout(form)
        layout.addWidget(faint(save_text))
        buttons, self.ok = dialog_buttons(self, tr("写して保存する"))
        self.ok.setEnabled(first is not None)
        layout.addWidget(buttons)

    def chosen(self):
        """(paths, tool mode, placement)."""
        paths = next((paths for button, paths in self.targets.values() if button.isChecked()), [])
        return list(paths), self.tool.currentData(), self.placement.currentData()


def area_picture(picture, mask, longest=360):
    """The shown image, small, with its processed area tinted in the accent colour."""
    from PIL import Image as PILImage
    from .theme import TOKENS
    scale = min(1.0, longest / max(picture.size))
    size = (max(1, round(picture.width * scale)), max(1, round(picture.height * scale)))
    small = picture.convert("RGBA").resize(size, PILImage.Resampling.LANCZOS)
    area = mask.resize(size, PILImage.Resampling.NEAREST).point(lambda value: 150 if value else 0)
    tint = PILImage.new("RGBA", size, TOKENS["accent"])
    tint.putalpha(area)
    small.alpha_composite(tint)
    return QImage(small.tobytes(), small.width, small.height, small.width * 4, QImage.Format.Format_RGBA8888).copy()


class UpscaleDialog(QDialog):
    """Enlarge the displayed image in place with Lanczos3 (undoable; nothing is exported)."""

    def __init__(self, size, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("超解像を適用"))
        self.size = size
        layout = QFormLayout(self)
        note = QLabel(tr("表示中の画像を、編集内容を含めて拡大します。「元に戻す」で取り消せます。\n"
                      "モザイクなどで隠した部分が復元されることはありません。保存は現在の保存方法に従います。"))
        note.setWordWrap(True)
        layout.addRow(note)
        self.factor = QComboBox()
        for factor in UPSCALE_FACTORS:
            self.factor.addItem(tr("{factor:g}倍").format(factor=factor), factor)
        self.factor.setCurrentIndex(self.factor.findData(2))
        layout.addRow(tr("倍率"), self.factor)
        self.result = QLabel()
        self.result.setWordWrap(True)
        layout.addRow(tr("拡大後"), self.result)
        buttons, self.ok = dialog_buttons(self, tr("適用する"))
        layout.addRow(buttons)
        self.factor.currentIndexChanged.connect(self.update_result)
        self.update_result()

    def target_size(self):
        return upscaled_size(self.size, self.factor.currentData())

    def update_result(self, *_):
        try:
            width, height = self.target_size()
        except ImageProblem as error:
            self.result.setText(str(error))
            self.ok.setEnabled(False)
            return
        self.result.setText(f"{self.size[0]:,} × {self.size[1]:,}px → {width:,} × {height:,}px")
        self.ok.setEnabled(True)


class CollageDialog(QDialog):
    """Arrange the selected images in a grid or freely on a canvas.

    Crops are made on the canvas itself (double-click an image) and only apply
    to the collage; the image files never change.
    """

    def __init__(self, names, images, parent=None, loader=None):
        super().__init__(parent)
        self.setWindowTitle(tr("コラージュを作成"))
        self.names = list(names)
        self.sources = list(images)
        # ``loader(path)`` reads an added image file as metadata-free pixels.
        self.loader = loader
        self.free_started = False
        self.resize(1000, 680)
        self.main_layout = layout = QHBoxLayout(self)
        side = QVBoxLayout()
        self.count_label = QLabel()
        side.addWidget(self.count_label)
        self.form = form = QFormLayout()
        self.arrangement = QComboBox()
        self.arrangement.addItem(tr("格子に並べる"), "grid")
        self.arrangement.addItem(tr("自由に配置"), "free")
        self.arrangement.setToolTip(tr("自由に配置：画像をドラッグして動かし、角をドラッグして拡大・縮小します。クリックした画像が前面に来ます。"))
        form.addRow(tr("配置"), self.arrangement)
        self.layout_combo = QComboBox()
        form.addRow(tr("並べ方"), self.layout_combo)
        self.fit = QComboBox()
        self.fit.addItem(tr("全体を収める（余白あり）"), "contain")
        self.fit.addItem(tr("枠を埋める（はみ出しを切り取る）"), "cover")
        form.addRow(tr("画像の合わせ方"), self.fit)
        self.gap = QSpinBox()
        self.gap.setRange(0, 200)
        self.gap.setValue(0)
        self.gap.setSuffix(" px")
        form.addRow(tr("すき間"), self.gap)
        self.canvas_width, self.canvas_height = QSpinBox(), QSpinBox()
        for box in (self.canvas_width, self.canvas_height):
            box.setRange(1, MAX_DIMENSION)
            box.setSuffix(" px")
        size_row = QHBoxLayout()
        size_row.addWidget(self.canvas_width, 1)
        size_row.addWidget(QLabel("×"))
        size_row.addWidget(self.canvas_height, 1)
        self.canvas_size_row = QWidget()
        self.canvas_size_row.setLayout(size_row)
        size_row.setContentsMargins(0, 0, 0, 0)
        form.addRow(tr("キャンバス"), self.canvas_size_row)
        self.rearrange_button = QPushButton(tr("格子の位置に並べ直す"))
        self.rearrange_button.setToolTip(tr("画像の位置と大きさを、格子に並べたときの配置に戻します。"))
        form.addRow("", self.rearrange_button)
        self.background = QComboBox()
        for title, value in ((tr("白"), "#ffffff"), (tr("黒"), "#000000"), (tr("透明"), None)):
            self.background.addItem(title, value)
        form.addRow(tr("背景"), self.background)
        side.addLayout(form)
        self.size_label = faint("")
        side.addWidget(self.size_label)
        side.addSpacing(6)
        side.addWidget(QLabel(tr("画像")))
        self.image_list = QListWidget()
        self.image_list.setIconSize(QSize(40, 40))
        self.image_list.setAccessibleName(tr("コラージュにする画像"))
        side.addWidget(self.image_list, 1)
        images_row = QHBoxLayout()
        self.add_button = QPushButton(tr("画像を追加…"))
        self.add_button.setToolTip(tr("ほかの画像ファイルを加えます（{MAX_COLLAGE}枚まで）。").format(MAX_COLLAGE=MAX_COLLAGE))
        self.remove_button = QPushButton(tr("取り除く"))
        self.remove_button.setToolTip(tr("選んだ画像をコラージュから外します。画像ファイルは変わりません。"))
        images_row.addWidget(self.add_button)
        images_row.addWidget(self.remove_button)
        images_row.addStretch(1)
        side.addLayout(images_row)
        crop_row = QHBoxLayout()
        self.crop_button = QPushButton(tr("切り抜く"))
        self.crop_button.setToolTip(tr("選んだ画像の切り抜き枠を、右のキャンバスに表示します。"))
        self.uncrop_button = QPushButton(tr("切り抜きを解除"))
        crop_row.addWidget(self.crop_button)
        crop_row.addWidget(self.uncrop_button)
        crop_row.addStretch(1)
        side.addLayout(crop_row)
        self.hint = faint("")
        side.addWidget(self.hint)
        buttons, self.ok = dialog_buttons(self, tr("保存先を選ぶ…"))
        side.addWidget(buttons)
        layout.addLayout(side, 2)
        self.canvas = None
        self.set_images(self.names, self.sources)

        for combo in (self.arrangement, self.layout_combo, self.fit, self.background):
            combo.currentIndexChanged.connect(self.update_layout)
        for box in (self.gap, self.canvas_width, self.canvas_height):
            box.valueChanged.connect(self.update_layout)
        self.rearrange_button.clicked.connect(self.rearrange)
        self.image_list.currentRowChanged.connect(self.list_selected)
        self.image_list.itemDoubleClicked.connect(lambda item: self.canvas.start_crop(self.image_list.row(item)))
        self.crop_button.clicked.connect(lambda: self.canvas.start_crop(self.image_list.currentRow()))
        self.uncrop_button.clicked.connect(lambda: self.canvas.reset_crop(self.image_list.currentRow()))
        self.add_button.clicked.connect(self.choose_images)
        self.remove_button.clicked.connect(lambda: self.remove_image(self.image_list.currentRow()))
        self.update_layout()
        self.show_hint(False)

    def set_images(self, names, images, crops=None):
        """Use these images (crops kept by the caller where they still apply); the canvas starts afresh."""
        from .collage_canvas import CollageCanvas
        if self.canvas is not None:
            self.canvas.finish_crop()
        self.names, self.sources = list(names), list(images)
        canvas = CollageCanvas(self.sources)
        if crops:
            canvas.crops = list(crops)
        canvas.setAccessibleName(tr("コラージュのキャンバス"))
        canvas.changed.connect(self.canvas_changed)
        canvas.selectionChanged.connect(self.canvas_selected)
        canvas.croppingChanged.connect(self.show_hint)
        if self.canvas is None:
            self.main_layout.addWidget(canvas, 3)
        else:
            self.main_layout.replaceWidget(self.canvas, canvas)
            self.canvas.deleteLater()
        self.canvas = canvas
        self.free_started = False
        self.layout_combo.blockSignals(True)
        self.layout_combo.clear()
        for title, rows, columns in collage_layouts(len(self.sources)):
            self.layout_combo.addItem(title, (rows, columns))
        self.layout_combo.blockSignals(False)
        self.count_label.setText(tr("{count}枚を1枚にまとめます。").format(count=len(self.sources)))
        self.image_list.blockSignals(True)
        self.image_list.clear()
        for name in self.names:
            self.image_list.addItem(QListWidgetItem(name))
        self.image_list.blockSignals(False)
        for index in range(len(self.sources)):
            self._show_item(index)
        self.image_list.setCurrentRow(0)
        self.add_button.setEnabled(self.loader is not None and len(self.sources) < MAX_COLLAGE)
        self.remove_button.setEnabled(len(self.sources) > 1)

    def add_images(self, paths):
        """Add image files (up to the limit); returns the problems of files that could not be read."""
        problems = []
        names, images, crops = list(self.names), list(self.sources), list(self.canvas.crops)
        for path in paths:
            if len(images) >= MAX_COLLAGE:
                problems.append(tr("コラージュにできるのは{MAX_COLLAGE}枚までです。").format(MAX_COLLAGE=MAX_COLLAGE))
                break
            try:
                image = self.loader(Path(path))
            except ImageProblem as error:
                problems.append(f"{Path(path).name}: {error}")
                continue
            names.append(Path(path).name)
            images.append(image)
            crops.append((0, 0, image.width, image.height))
        if len(images) != len(self.sources):
            self.set_images(names, images, crops)
            self.update_layout()
        return problems

    def choose_images(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from .imaging import SUPPORTED
        pattern = " ".join("*" + suffix for suffix in sorted(SUPPORTED))
        raw, _ = QFileDialog.getOpenFileNames(self, tr("コラージュに加える画像"), "", tr("画像") + f" ({pattern})")
        if raw:
            problems = self.add_images(raw)
            if problems:
                QMessageBox.warning(self, tr("加えられなかった画像があります"), "\n".join(problems))

    def remove_image(self, row):
        if not 0 <= row < len(self.sources) or len(self.sources) <= 1:
            return
        self.canvas.finish_crop()
        keep = [index for index in range(len(self.sources)) if index != row]
        self.set_images([self.names[i] for i in keep], [self.sources[i] for i in keep], [self.canvas.crops[i] for i in keep])
        self.update_layout()

    # --- settings ----------------------------------------------------------------
    def free(self):
        return self.arrangement.currentData() == "free"

    def spec(self):
        rows, columns = self.layout_combo.currentData()
        return CollageSpec(rows, columns, self.fit.currentData(), self.gap.value(), self.background.currentData())

    def set_canvas_fields(self, size):
        for box, value in zip((self.canvas_width, self.canvas_height), size):
            box.blockSignals(True)
            box.setValue(value)
            box.blockSignals(False)

    def update_layout(self, *_args):
        free = self.free()
        for widget in (self.layout_combo, self.fit, self.gap):
            self.form.setRowVisible(widget, not free)
        for widget in (self.canvas_size_row, self.rearrange_button):
            self.form.setRowVisible(widget, free)
        background = self.background.currentData()
        try:
            # The grid is laid out first: the free layout starts from it.
            self.canvas.set_grid(self.spec(), background)
            if free:
                size = None if not self.free_started else (self.canvas_width.value(), self.canvas_height.value())
                size = self.canvas.set_free(size, background)
                self.free_started = True
                self.set_canvas_fields(size)
                check_canvas(size)
        except ImageProblem as error:
            self.size_label.setText(str(error))
            self.ok.setEnabled(False)
            return
        width, height = self.canvas.canvas_size
        self.size_label.setText(tr("仕上がり：{width:,} × {height:,}px").format(width=width, height=height))
        self.ok.setEnabled(True)
        self.show_hint(self.canvas.cropping is not None)

    def rearrange(self):
        self.set_canvas_fields(self.canvas.set_free(None, self.background.currentData(), rearrange=True))
        self.update_layout()

    # --- images ------------------------------------------------------------------
    def _show_item(self, index):
        from .canvas import qimage
        item = self.image_list.item(index)
        source = self.sources[index]
        crop = self.canvas.crops[index]
        cropped = crop != (0, 0, source.width, source.height)
        item.setText(self.names[index] + (tr("\n切り抜き：{crop:,} × {crop2:,}px").format(crop=crop[2], crop2=crop[3]) if cropped else ""))
        x, y, width, height = crop
        small = source.crop((x, y, x + width, y + height))
        small.thumbnail((80, 80))
        item.setIcon(QIcon(QPixmap.fromImage(qimage(small))))

    def update_crop_buttons(self):
        row = self.image_list.currentRow()
        valid = 0 <= row < len(self.sources)
        self.crop_button.setEnabled(valid)
        self.uncrop_button.setEnabled(valid and self.canvas.crops[row] != (0, 0, *self.sources[row].size))

    def list_selected(self, row):
        if 0 <= row < len(self.sources) and self.canvas.cropping is None:
            self.canvas.select(row)
        self.update_crop_buttons()

    def canvas_selected(self, index):
        self.image_list.blockSignals(True)
        self.image_list.setCurrentRow(index)
        self.image_list.blockSignals(False)
        self.update_crop_buttons()

    def canvas_changed(self):
        for index in range(len(self.sources)):
            self._show_item(index)
        if not self.free():
            self.update_layout()  # cropping changes the grid's cell size
        self.update_crop_buttons()

    def show_hint(self, cropping):
        if cropping:
            self.hint.setText(tr("枠の四隅や辺をドラッグして範囲を決めます。内側をドラッグすると移動します。"
                              "枠の外をクリックするか、Enterで確定します。"))
        elif self.free():
            self.hint.setText(tr("画像をドラッグして動かし、選んだ画像の角をドラッグして大きさを変えます。"
                              "ダブルクリックすると、その場で切り抜けます。元の画像は変わりません。"))
        else:
            self.hint.setText(tr("画像をダブルクリックすると、その場で切り抜けます。元の画像は変わりません。"))

    # --- result ------------------------------------------------------------------
    def accept(self):
        self.canvas.finish_crop()
        super().accept()

    def cropped_images(self):
        result = []
        for source, (x, y, width, height) in zip(self.sources, self.canvas.crops):
            result.append(source if (x, y, width, height) == (0, 0, *source.size) else source.crop((x, y, x + width, y + height)))
        return result

    def renderer(self):
        """A function that renders the full-size collage; safe to run off the UI thread."""
        self.canvas.finish_crop()
        sources, background = list(self.sources), self.background.currentData()
        if self.free():
            layout = FreeLayout((self.canvas_width.value(), self.canvas_height.value()), background, self.canvas.free_pieces())
            return lambda cancel=None: render_free_collage(sources, layout, cancel)
        images, spec = self.cropped_images(), self.spec()
        return lambda cancel=None: render_collage(images, spec)
