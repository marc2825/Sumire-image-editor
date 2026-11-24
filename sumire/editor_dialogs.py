"""Occasional image editing and output controls kept out of the main panels."""
from .i18n import tr
from dataclasses import replace

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from .canvas import qimage
from .editing import COLOR_FIELDS, NEUTRAL_COLORS, EditSpec, adjust_colors, checked_size, geometry
from .icons import icon
from .imaging import ImageProblem
from .novelai import CropPreview
from .theme import TOKENS
from .ui import section_label


def _signed(value):
    return f"{value:+d}" if value else "0"


# name: (label, slider range, slider value per 1.0 of the spec value, display, tooltip)
COLOR_CONTROLS = {
    "exposure": (tr("露出"), (-300, 300), 100, lambda v: f"{v / 100:+.2f} EV" if v else "0 EV", tr("画像全体の光の量。+1 EVで2倍の明るさ")),
    "brightness": (tr("明るさ"), (0, 300), 100, lambda v: f"{v}%", tr("画像全体を明るく・暗く")),
    "contrast": (tr("コントラスト"), (0, 300), 100, lambda v: f"{v}%", tr("明るい部分と暗い部分の差")),
    "highlights": (tr("ハイライト"), (-100, 100), 1, _signed, tr("明るい部分だけを明るく・暗く")),
    "shadows": (tr("シャドウ"), (-100, 100), 1, _signed, tr("暗い部分だけを明るく・暗く")),
    "white": (tr("白レベル"), (1, 255), 1, str, tr("この明るさ以上を真っ白にする")),
    "black": (tr("黒レベル"), (0, 254), 1, str, tr("この明るさ以下を真っ黒にする")),
    "gamma": (tr("ガンマ"), (20, 500), 100, lambda v: f"{v / 100:.2f}", tr("中間の明るさ。1より大きいと明るく")),
    "saturation": (tr("彩度"), (0, 300), 100, lambda v: f"{v}%", tr("色の鮮やかさ。0%で白黒")),
    "hue": (tr("色相"), (-180, 180), 1, lambda v: f"{v:+d}°" if v else "0°", tr("色合いを回す")),
    "temperature": (tr("色温度"), (-100, 100), 1, _signed, tr("マイナスで青み、プラスで黄み")),
    "red": (tr("赤"), (0, 200), 100, lambda v: f"{v}%", tr("赤の強さ")),
    "green": (tr("緑"), (0, 200), 100, lambda v: f"{v}%", tr("緑の強さ")),
    "blue": (tr("青"), (0, 200), 100, lambda v: f"{v}%", tr("青の強さ")),
    "sharpness": (tr("シャープネス"), (0, 300), 100, lambda v: f"{v}%", tr("輪郭のくっきりさ。100%で変化なし")),
}
BASIC_COLORS = ("brightness", "contrast", "saturation", "hue", "exposure", "temperature", "gamma")
DETAIL_GROUPS = ((tr("明暗"), ("highlights", "shadows", "white", "black")),
                 (tr("RGBバランス"), ("red", "green", "blue")),
                 (tr("細部"), ("sharpness",)))


def spin(value, maximum=32768, minimum=1):
    field = QSpinBox()
    field.setRange(minimum, maximum)
    field.setValue(value)
    return field


class ImageEditDialog(QDialog):
    """Crop and resize (``mode="crop"``) or adjust the colours (``mode="color"``).

    Rotation and flipping are immediate panel buttons, so they are not part of this dialog.
    """

    TITLES = {"crop": tr("画像を切り抜く"), "color": tr("色調の調整")}

    def __init__(self, image, parent=None, mode="crop"):
        super().__init__(parent)
        if mode not in self.TITLES:
            raise ValueError(mode)
        self.mode = mode
        self.source_size = image.size
        self.setWindowTitle(self.TITLES[mode])
        available = self.screen().availableGeometry()
        self.resize(min(1180 if mode == "crop" else 1040, available.width() - 40),
                    min(800 if mode == "crop" else 720, available.height() - 64))
        self.setSizeGripEnabled(True)
        layout = QVBoxLayout(self)
        body = QHBoxLayout()
        body.setSpacing(16)
        layout.addLayout(body, 1)
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        body.addWidget(scroll, 3)
        self.crop_fields = [spin(0, image.width - 1, 0), spin(0, image.height - 1, 0), spin(image.width, image.width), spin(image.height, image.height)]
        self.resize_enabled = QCheckBox(tr("出力の寸法を指定する（拡大・縮小）"))
        self.resize_width, self.resize_height = spin(image.width), spin(image.height)
        self.keep_aspect = QCheckBox(tr("幅と高さの比率を保つ"))
        self.keep_aspect.setToolTip(tr("幅を変えると、高さも同じ割合で変わります（逆も同じ）。"))
        self.keep_aspect.setChecked(True)
        self.color_fields = []
        if mode == "crop":
            self.build_crop_page(page, image)
        else:
            self.build_color_page(page)
        self.preview_source = image.copy()
        self.preview_source.thumbnail((1000, 800))
        side = QVBoxLayout()
        side.setSpacing(8)
        side.addWidget(QLabel(tr("適用後のプレビュー")))
        self.preview_box = (max(260, min(420 if mode == "crop" else 560, self.width() - 760 if mode == "crop" else self.width() - 440)),
                            max(220, min(520, self.height() - 280)))
        self.result_preview = QLabel()
        self.result_preview.setObjectName("editPreview")
        self.result_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # The pixmap follows the label, never the other way round, so short screens still fit.
        self.result_preview.setMinimumSize(200, 150)
        self.result_preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        side.addWidget(self.result_preview, 1)
        self.dimensions = QLabel()
        self.dimensions.setWordWrap(True)
        side.addWidget(self.dimensions)
        body.addLayout(side, 2 if mode == "crop" else 3)
        note = QLabel(tr("※ 適用後も「元に戻す」で取り消せます。上書き保存すると、切り落とした部分は元画像からも失われます。")
                      if mode == "crop" else tr("※ 適用後も「元に戻す」で取り消せます。透明度と加工した範囲はそのまま保ちます。"))
        note.setWordWrap(True)
        layout.addWidget(note)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.update_preview)
        for widget in (self.resize_enabled, self.keep_aspect):
            widget.toggled.connect(self.schedule_preview)
        self.resize_enabled.toggled.connect(self.resize_toggled)
        for field in self.color_fields:
            field.valueChanged.connect(self.schedule_preview)
        self.resize_width.valueChanged.connect(lambda: self.resize_changed(True))
        self.resize_height.valueChanged.connect(lambda: self.resize_changed(False))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("切り抜きを適用") if mode == "crop" else tr("色調を適用"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("キャンセル"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize_toggled(False)
        self.update_preview()

    def build_crop_page(self, page, image):
        crop_layout = QVBoxLayout(page)
        crop_layout.setSpacing(10)
        hint = QLabel(tr("四隅や辺をドラッグして範囲を調整し、「切り抜きを適用」で確定します。枠の内側をドラッグすると移動します。"))
        hint.setWordWrap(True)
        crop_layout.addWidget(hint)
        # Large enough to aim a crop precisely; capped so the dialog fits a 1366×768 screen.
        self.crop_preview = CropPreview(image, (max(320, min(680, self.width() - 520)), max(220, min(460, self.height() - 360))))
        crop_layout.addWidget(self.crop_preview, alignment=Qt.AlignmentFlag.AlignCenter)
        crop_layout.addWidget(section_label(tr("切り抜く範囲")))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        for index, (name, field) in enumerate(zip((tr("左端 X"), tr("上端 Y"), tr("幅"), tr("高さ")), self.crop_fields)):
            field.setAccessibleName(tr("切り抜き ") + name)
            field.setSuffix(" px")
            row, column = divmod(index, 2)
            grid.addWidget(QLabel(name), row, column * 2)
            grid.addWidget(field, row, column * 2 + 1)
            field.valueChanged.connect(self.sync_crop)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        crop_layout.addLayout(grid)
        reset_crop = QPushButton(tr("範囲を画像全体に戻す"))
        reset_crop.clicked.connect(lambda: self.set_crop((0, 0, *image.size)))
        crop_layout.addWidget(reset_crop, alignment=Qt.AlignmentFlag.AlignLeft)
        crop_layout.addSpacing(4)
        crop_layout.addWidget(section_label(tr("拡大・縮小")))
        crop_layout.addWidget(self.resize_enabled)
        size_row = QHBoxLayout()
        for field, name in ((self.resize_width, tr("幅")), (self.resize_height, tr("高さ"))):
            field.setSuffix(" px")
            field.setAccessibleName(tr("出力の") + name)
        size_row.addWidget(QLabel(tr("幅")))
        size_row.addWidget(self.resize_width, 1)
        size_row.addWidget(QLabel(tr("×  高さ")))
        size_row.addWidget(self.resize_height, 1)
        crop_layout.addLayout(size_row)
        scale_row = QHBoxLayout()
        scale_row.addWidget(self.keep_aspect)
        scale_row.addStretch(1)
        self.scale_buttons = []
        for percent in (50, 200):
            button = QPushButton(f"{percent}%")
            button.setToolTip(tr("切り抜いた範囲の{percent}%の寸法にします").format(percent=percent))
            button.clicked.connect(lambda checked=False, value=percent: self.scale_to(value))
            scale_row.addWidget(button)
            self.scale_buttons.append(button)
        crop_layout.addLayout(scale_row)
        crop_layout.addStretch(1)
        self.crop_preview.cropChanged.connect(self.set_crop)

    def build_color_page(self, page):
        outer = QVBoxLayout(page)
        outer.addStretch(1)
        history = QHBoxLayout()
        history.setSpacing(6)
        self.color_undo = QPushButton(tr("元に戻す"))
        self.color_undo.setIcon(icon("undo"))
        self.color_undo.setToolTip(tr("一つ前の調整に戻す · Ctrl+Z"))
        self.color_redo = QPushButton(tr("やり直す"))
        self.color_redo.setIcon(icon("redo"))
        self.color_redo.setToolTip(tr("戻した調整をやり直す · Ctrl+Shift+Z / Ctrl+Y"))
        self.color_undo.clicked.connect(lambda: self.step_colors(-1))
        self.color_redo.clicked.connect(lambda: self.step_colors(1))
        reset_color = QPushButton(tr("すべて初期値に戻す"))
        reset_color.clicked.connect(self.reset_colors)
        history.addWidget(self.color_undo)
        history.addWidget(self.color_redo)
        history.addStretch(1)
        history.addWidget(reset_color)
        outer.addLayout(history)
        outer.addSpacing(6)
        self.color_controls = {}
        basic = self.color_grid(((None, BASIC_COLORS),))
        outer.addLayout(basic)
        outer.addSpacing(10)
        self.detail_toggle = QToolButton()
        self.detail_toggle.setObjectName("disclosure")
        self.detail_toggle.setText(tr("詳細調整"))
        self.detail_toggle.setCheckable(True)
        self.detail_toggle.setIcon(icon("chevron_right", "text_muted"))
        self.detail_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.detail_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        outer.addWidget(self.detail_toggle)
        self.color_details = QWidget()
        details = self.color_grid(DETAIL_GROUPS)
        details.setContentsMargins(0, 4, 0, 0)
        self.color_details.setLayout(details)
        self.color_details.hide()
        self.detail_toggle.toggled.connect(self.show_color_details)
        outer.addWidget(self.color_details)
        outer.addStretch(1)
        # Ordered like EditSpec so tests and callers can rely on the first field being brightness.
        self.color_fields = [self.color_controls[name][0] for name in COLOR_FIELDS]
        self.color_history = [self.color_state()]
        self.color_index = 0
        self.restoring = False
        self.history_timer = QTimer(self)
        self.history_timer.setSingleShot(True)
        self.history_timer.timeout.connect(self.record_colors)
        for slider in self.color_fields:
            slider.valueChanged.connect(self.colors_changed)
        for keys, step in ((QKeySequence.StandardKey.Undo, -1), (QKeySequence.StandardKey.Redo, 1), ("Ctrl+Y", 1)):
            QShortcut(QKeySequence(keys), self, activated=lambda value=step: self.step_colors(value))
        self.update_history_buttons()

    def color_grid(self, groups):
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(0, 96)
        row = 0
        for title, names in groups:
            if title:
                if row:
                    grid.setRowMinimumHeight(row, 6)
                    row += 1
                grid.addWidget(section_label(title), row, 0, 1, 3)
                row += 1
            for name in names:
                label, (low, high), scale, show, tip = COLOR_CONTROLS[name]
                slider = QSlider(Qt.Orientation.Horizontal)
                slider.setRange(low, high)
                slider.setValue(round(NEUTRAL_COLORS[name] * scale))
                slider.setAccessibleName(label)
                slider.setToolTip(tip + tr("。ダブルクリックで初期値"))
                value = QLabel(show(slider.value()))
                value.setMinimumWidth(64)
                value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                slider.valueChanged.connect(lambda number, text=value, show=show: text.setText(show(number)))
                slider.mouseDoubleClickEvent = lambda event, field=slider, home=slider.value(): field.setValue(home)
                name_label = QLabel(label)
                name_label.setToolTip(tip)
                grid.addWidget(name_label, row, 0)
                grid.addWidget(slider, row, 1)
                grid.addWidget(value, row, 2)
                self.color_controls[name] = (slider, scale)
                row += 1
        return grid

    def show_color_details(self, show):
        self.color_details.setVisible(show)
        self.detail_toggle.setIcon(icon("chevron_down" if show else "chevron_right", "text_muted"))

    def color_state(self):
        return tuple(slider.value() for slider in self.color_fields)

    def colors_changed(self, *_):
        if not self.restoring:
            self.history_timer.start(350)

    def record_colors(self):
        state = self.color_state()
        if state != self.color_history[self.color_index]:
            del self.color_history[self.color_index + 1:]
            self.color_history.append(state)
            self.color_index += 1
        self.update_history_buttons()

    def step_colors(self, direction):
        if self.history_timer.isActive():
            self.history_timer.stop()
            self.record_colors()
        index = self.color_index + direction
        if not 0 <= index < len(self.color_history):
            return
        self.color_index = index
        self.restoring = True
        for slider, value in zip(self.color_fields, self.color_history[index]):
            slider.setValue(value)
        self.restoring = False
        self.update_history_buttons()
        self.schedule_preview()

    def update_history_buttons(self):
        self.color_undo.setEnabled(self.color_index > 0 or self.history_timer.isActive())
        self.color_redo.setEnabled(self.color_index < len(self.color_history) - 1)

    def reset_colors(self):
        for name, (slider, scale) in self.color_controls.items():
            slider.setValue(round(NEUTRAL_COLORS[name] * scale))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "preview_timer"):
            self.schedule_preview()

    def set_crop(self, values):
        for field, value in zip(self.crop_fields, values):
            field.blockSignals(True)
            field.setValue(value)
            field.blockSignals(False)
        self.sync_crop()

    def sync_crop(self):
        x, y, w, h = [field.value() for field in self.crop_fields]
        w, h = min(w, self.source_size[0] - x), min(h, self.source_size[1] - y)
        for field, value in zip(self.crop_fields[2:], (w, h)):
            field.blockSignals(True)
            field.setValue(value)
            field.blockSignals(False)
        if hasattr(self, "crop_preview"):
            self.crop_preview.crop = (x, y, w, h)
            self.crop_preview.update()
        if not self.resize_enabled.isChecked():
            self.follow_crop()
        if hasattr(self, "preview_timer"):
            self.schedule_preview()

    def resize_toggled(self, enabled):
        for widget in (self.resize_width, self.resize_height, self.keep_aspect, *getattr(self, "scale_buttons", [])):
            widget.setEnabled(enabled)
        if not enabled:
            self.follow_crop()

    def follow_crop(self):
        """While no output size is chosen, the size fields show the cropped size."""
        for field, value in zip((self.resize_width, self.resize_height), (field.value() for field in self.crop_fields[2:])):
            field.blockSignals(True)
            field.setValue(value)
            field.blockSignals(False)

    def scale_to(self, percent):
        w, h = [field.value() for field in self.crop_fields[2:]]
        for field, value in zip((self.resize_width, self.resize_height), (w, h)):
            field.blockSignals(True)
            field.setValue(max(1, min(field.maximum(), round(value * percent / 100))))
            field.blockSignals(False)
        self.schedule_preview()

    def resize_changed(self, from_width):
        if self.keep_aspect.isChecked():
            w, h = [field.value() for field in self.crop_fields[2:]]
            other = self.resize_height if from_width else self.resize_width
            other.blockSignals(True)
            other.setValue(max(1, round(self.resize_width.value() * h / w if from_width else self.resize_height.value() * w / h)))
            other.blockSignals(False)
        self.schedule_preview()

    def spec(self):
        colors = {}
        for name, (slider, scale) in getattr(self, "color_controls", {}).items():
            colors[name] = slider.value() if scale == 1 else slider.value() / scale
        return EditSpec(tuple(field.value() for field in self.crop_fields),
                        (self.resize_width.value(), self.resize_height.value()) if self.resize_enabled.isChecked() else None,
                        0, False, False, **colors)

    def schedule_preview(self, *_):
        self.preview_timer.start(80)

    def update_preview(self):
        spec = self.spec()
        x, y, w, h = spec.crop
        sx, sy = self.preview_source.width / self.source_size[0], self.preview_source.height / self.source_size[1]
        crop = (min(self.preview_source.width - 1, round(x * sx)), min(self.preview_source.height - 1, round(y * sy)),
                max(1, round(w * sx)), max(1, round(h * sy)))
        crop = (crop[0], crop[1], min(crop[2], self.preview_source.width - crop[0]), min(crop[3], self.preview_source.height - crop[1]))
        output_size = spec.size or ((h, w) if spec.rotation in {90, 270} else (w, h))
        box = self.preview_box
        if self.result_preview.isVisible():
            box = (max(200, self.result_preview.width() - 8), max(150, self.result_preview.height() - 8))
        factor = min(1, box[0] / output_size[0], box[1] / output_size[1])
        small_spec = replace(spec, crop=crop, size=(max(1, round(output_size[0] * factor)), max(1, round(output_size[1] * factor))))
        result = adjust_colors(geometry(self.preview_source, small_spec), spec)
        self.result_preview.setPixmap(QPixmap.fromImage(qimage(result)))
        if self.mode == "crop":
            text = tr("切り抜き後：{w:,} × {h:,} px").format(w=w, h=h)
            if spec.size is not None:
                text += tr("\n出力：{output_size:,} × {output_size2:,} px").format(output_size=output_size[0], output_size2=output_size[1])
            self.dimensions.setText(text + tr("\n（元画像：{source_size:,} × {source_size2:,} px）").format(source_size=self.source_size[0], source_size2=self.source_size[1]))
        else:
            self.dimensions.setText(f"{output_size[0]:,} × {output_size[1]:,} px")

    def accept(self):
        if self.spec().size is not None:
            try:
                checked_size(self.spec().size)
            except ImageProblem as error:
                self.error.setText(str(error))
                return
        super().accept()


class MetadataDialog(QDialog):
    """Metadata of one file as [種類] blocks of 項目：内容, with a copy button."""

    def __init__(self, title, entries, note="", parent=None):
        super().__init__(parent)
        from html import escape
        from PySide6.QtWidgets import QApplication, QTextBrowser
        self.setWindowTitle(tr("メタデータの内容"))
        available = self.screen().availableGeometry()
        self.resize(min(760, available.width() - 40), min(640, available.height() - 64))
        self.setSizeGripEnabled(True)
        layout = QVBoxLayout(self)
        heading = QLabel(title)
        heading.setWordWrap(True)
        heading.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(heading)
        groups = {}
        for category, item, content in entries:
            groups.setdefault(category, []).append((item, content))
        html, plain = [], []
        if not groups:
            html.append(tr("<p>メタデータは見つかりませんでした。</p>"))
            plain.append(tr("メタデータは見つかりませんでした。"))
        # One table for every section, so the values start at the same place throughout.
        if groups:
            html.append('<table cellspacing="0" cellpadding="3" width="100%">')
        for number, (category, items) in enumerate(groups.items()):
            top = 4 if number == 0 else 16
            html.append(f'<tr><td colspan="2" style="padding-top:{top}px; padding-bottom:4px; font-weight:700; '
                        f'color:{TOKENS["text_strong"]}">{escape(category)}</td></tr>')
            plain.append(f"[{category}]")
            for item, content in items:
                body = escape(content).replace("\n", "<br>")
                html.append(f'<tr><td valign="top" width="36%" style="color:{TOKENS["text_muted"]}; padding-right:12px">{escape(item)}</td>'
                            f'<td valign="top">{body}</td></tr>')
                plain.append(tr("{item}：{content}").format(item=item, content=content))
            plain.append("")
        if groups:
            html.append("</table>")
        self.text = "\n".join(plain).strip()
        view = QTextBrowser()
        view.setOpenLinks(False)
        view.setHtml("".join(html))
        layout.addWidget(view, 1)
        if note:
            label = QLabel(note)
            label.setObjectName("faint")
            label.setWordWrap(True)
            layout.addWidget(label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr("閉じる"))
        copy = buttons.addButton(tr("テキストをコピー"), QDialogButtonBox.ButtonRole.ActionRole)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.text))
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
