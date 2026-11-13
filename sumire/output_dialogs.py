"""Dialogs for writing new files: accepted export, conversion, compression and collages."""
from __future__ import annotations
from .i18n import tr

from pathlib import Path

from PySide6.QtCore import QSize, QThreadPool, QTimer, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QRadioButton, QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from .collage import CollageSpec, FreeLayout, check_canvas, collage_layouts, render_collage, render_free_collage
from .convert import Encoding, TARGETS, encode, size_summary, writable
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

    def refresh(self, *_args):
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
            return folder_name_problem(self.name.text().strip())
        return "" if self.chosen else tr("保存先のフォルダーを選んでください。")

    def destination(self) -> Path:
        problem = self.problem()
        if problem:
            raise ImageProblem(problem)
        return (self.parent_folder / self.name.text().strip()).resolve() if self.inside.isChecked() else self.chosen


class AcceptedExportDialog(QDialog):
    def __init__(self, paths, parent_folder, current_format="PNG", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("採用画像を書き出す"))
        self.setMinimumWidth(520)
        self.count = len(paths)
        self.first_suffix = paths[0].suffix.lower() if paths else ".png"
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        intro = QLabel(tr("「採用」の画像 {count} 枚を、メタデータを削除して書き出します。元画像は変わりません。").format(count=len(paths)))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.chooser = DestinationChooser(parent_folder, tr("採用"), self)
        layout.addWidget(self.chooser)
        self.renumber = QCheckBox(tr("連番に振り直す（一覧の順）"))
        self.renumber.setChecked(True)
        layout.addWidget(self.renumber)
        self.names = faint("")
        self.names.setContentsMargins(26, 0, 0, 0)
        layout.addWidget(self.names)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("形式")))
        self.format_combo = QComboBox()
        for text, value in ((tr("元の形式のまま（PNG / JPEG / WebP。その他はPNG）"), "SOURCE"), ("PNG", "PNG"), ("JPEG", "JPEG"), (tr("WebP（可逆）"), "WEBP")):
            self.format_combo.addItem(text, value)
        row.addWidget(self.format_combo, 1)
        layout.addLayout(row)
        self.problem = QLabel()
        self.problem.setObjectName("danger")
        layout.addWidget(self.problem)
        buttons, self.ok = dialog_buttons(self, tr("書き出す"))
        layout.addWidget(buttons)
        for signal in (self.renumber.toggled, self.chooser.name.textChanged, self.chooser.group.buttonToggled):
            signal.connect(self.refresh)
        self.chooser.browse.clicked.connect(self.refresh)
        self.refresh()

    def format(self):
        return self.format_combo.currentData()

    def refresh(self, *_args):
        if self.renumber.isChecked():
            stems = sequence_stems(self.count)
            sample = stems[0] if len(stems) == 1 else f"{stems[0]}, {stems[1]}" + (f" … {stems[-1]}" if len(stems) > 2 else "")
            self.names.setText(tr("名前：{sample}（桁数をそろえます。拡張子は形式に合わせます）").format(sample=sample))
        else:
            self.names.setText(tr("元の名前のまま（同名のファイルがあれば _2 などを付けます）"))
        problem = self.chooser.problem()
        self.problem.setText(problem)
        self.ok.setEnabled(not problem)

    def destination(self):
        return self.chooser.destination()


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

    def __init__(self, mode, count, parent_folder, sample, *, backup=True, source_format=None, parent=None):
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
                    item = self.format_combo.model().item(self.format_combo.count() - 1)
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
        layout.addWidget(QLabel(tr("保存先")))
        self.chooser = DestinationChooser(parent_folder, tr("圧縮済み") if compress else tr("変換済み"), self)
        layout.addWidget(self.chooser)
        layout.addWidget(faint(tr("元画像のメタデータは書き出したファイルに含めません。")
                               + (tr("復元用に、管理記録へ圧縮して保存します（暗号化なし）。") if backup
                                  else tr("復元用の退避はオフです（保存方法の設定）。"))))
        layout.addStretch(1)
        self.estimate = QLabel()
        self.estimate.setObjectName("estimate")
        self.estimate.setWordWrap(True)
        outer.addWidget(self.estimate)
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
        self.last_quality = {}
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
        self.chooser.name.textChanged.connect(self.refresh_problem)
        self.chooser.group.buttonToggled.connect(self.refresh_problem)
        self.chooser.browse.clicked.connect(self.refresh_problem)
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
                        max_side=self.max_side.value() if self.shrink.isChecked() else None)

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
            return len(encode(self.pixels, encoding))
        job = self.job = Job(work)
        job.signals.done.connect(lambda size: self.show_estimate(generation, size))
        job.signals.failed.connect(lambda message: self.show_estimate(generation, None, message))
        self.pool.start(job)

    def show_estimate(self, generation, size, message=""):
        if generation != self.generation:
            return
        encoding = self.encoding()
        kind = tr("非可逆（画質が変わる可能性があります）") if encoding.lossy else tr("可逆（画質は変わりません）")
        if size is None:
            self.estimate.setText(tr("{kind}\n試算できません：{message}").format(kind=kind, message=message))
            return
        label = tr("圧縮後") if self.mode == "compress" else tr("変換後")
        prefix = tr("1枚目（{sample_name}）の試算：").format(sample_name=self.sample_name) if self.count > 1 else ""
        self.estimate.setText(f"{kind}\n{prefix}{size_summary(self.sample_size, size, label)}")

    def refresh_problem(self, *_args):
        problem = self.chooser.problem()
        self.problem.setText(problem)
        self.ok.setEnabled(not problem)

    def destination(self):
        return self.chooser.destination()

    def done(self, result):
        self.generation += 1
        if self.job is not None:
            self.job.cancel.set()
        self.timer.stop()
        self.pool.waitForDone()
        super().done(result)


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

    def __init__(self, names, images, parent=None):
        super().__init__(parent)
        from .collage_canvas import CollageCanvas
        self.setWindowTitle(tr("コラージュを作成"))
        self.names = list(names)
        self.sources = list(images)
        self.free_started = False
        self.resize(1000, 680)
        layout = QHBoxLayout(self)
        side = QVBoxLayout()
        side.addWidget(QLabel(tr("{count}枚を1枚にまとめます。").format(count=len(images))))
        self.form = form = QFormLayout()
        self.arrangement = QComboBox()
        self.arrangement.addItem(tr("格子に並べる"), "grid")
        self.arrangement.addItem(tr("自由に配置"), "free")
        self.arrangement.setToolTip(tr("自由に配置：画像をドラッグして動かし、角をドラッグして拡大・縮小します。クリックした画像が前面に来ます。"))
        form.addRow(tr("配置"), self.arrangement)
        self.layout_combo = QComboBox()
        for title, rows, columns in collage_layouts(len(images)):
            self.layout_combo.addItem(title, (rows, columns))
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
        for name in self.names:
            self.image_list.addItem(QListWidgetItem(name))
        side.addWidget(self.image_list, 1)
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
        self.canvas = CollageCanvas(images)
        self.canvas.setAccessibleName(tr("コラージュのキャンバス"))
        layout.addWidget(self.canvas, 3)
        for index in range(len(images)):
            self._show_item(index)
        self.image_list.setCurrentRow(0)

        for combo in (self.arrangement, self.layout_combo, self.fit, self.background):
            combo.currentIndexChanged.connect(self.update_layout)
        for box in (self.gap, self.canvas_width, self.canvas_height):
            box.valueChanged.connect(self.update_layout)
        self.rearrange_button.clicked.connect(self.rearrange)
        self.image_list.currentRowChanged.connect(self.list_selected)
        self.image_list.itemDoubleClicked.connect(lambda item: self.canvas.start_crop(self.image_list.row(item)))
        self.crop_button.clicked.connect(lambda: self.canvas.start_crop(self.image_list.currentRow()))
        self.uncrop_button.clicked.connect(lambda: self.canvas.reset_crop(self.image_list.currentRow()))
        self.canvas.changed.connect(self.canvas_changed)
        self.canvas.selectionChanged.connect(self.canvas_selected)
        self.canvas.croppingChanged.connect(self.show_hint)
        self.update_layout()
        self.show_hint(False)

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
