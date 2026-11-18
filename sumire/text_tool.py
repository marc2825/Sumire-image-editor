"""Text written into the image: rendering with Qt, the undoable edit, and the dialog that sets it.

The text becomes part of the pixels, like the other tools: it is applied as a stroke whose
mask covers the glyphs, so Undo, the eraser, the edit mask and saving treat it like any edit.
The point clicked on the image is the top left of the first line.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import cast

from PIL import Image
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QImage, QPainter
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QDialog, QDialogButtonBox, QFontComboBox, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout,
)

from .i18n import tr
from .icons import swatch
from .imaging import Document, ImageProblem, Stroke, Tool

MIN_SIZE, MAX_SIZE = 4, 2000
MAX_TEXT = 2000
MAX_LAYER_PIXELS = 64_000_000


@dataclass(frozen=True)
class TextStyle:
    family: str = ""
    size: int = 48
    color: str = "#ffffff"
    bold: bool = False

    def to_settings(self) -> dict:
        return {"family": self.family, "size": self.size, "color": self.color, "bold": self.bold}

    @classmethod
    def from_settings(cls, value) -> TextStyle:
        """A style from saved settings; anything missing or invalid keeps its default."""
        style = cls()
        if not isinstance(value, dict):
            return style
        if isinstance(value.get("family"), str) and len(value["family"]) <= 200:
            style = replace(style, family=value["family"])
        if type(value.get("size")) is int and MIN_SIZE <= value["size"] <= MAX_SIZE:
            style = replace(style, size=value["size"])
        color = value.get("color")
        if isinstance(color, str) and len(color) == 7 and color.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in color[1:]):
            style = replace(style, color=color.lower())
        if isinstance(value.get("bold"), bool):
            style = replace(style, bold=value["bold"])
        return style


def default_family() -> str:
    """The bundled Noto Sans JP when it is loaded (it has Japanese), else the system's font."""
    families = QFontDatabase.families()
    return next((name for name in ("Noto Sans JP", "Noto Sans CJK JP") if name in families), QApplication.font().family())


def text_font(style: TextStyle) -> QFont:
    font = QFont(style.family or default_family())
    font.setPixelSize(max(MIN_SIZE, min(MAX_SIZE, style.size)))
    font.setBold(style.bold)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def render_text(text: str, style: TextStyle) -> tuple[QImage, int]:
    """The text drawn on a transparent image, and the margin around it.

    The first line's top left is at (margin, margin), so the image goes at the clicked point
    minus the margin; the margin leaves room for glyphs that reach past their advance.
    """
    font = text_font(style)
    metrics = QFontMetricsF(font)
    lines = text.split("\n")
    margin = math.ceil(font.pixelSize() * 0.25) + 2
    width = math.ceil(max(metrics.horizontalAdvance(line) for line in lines)) + 2 * margin
    height = math.ceil(metrics.lineSpacing() * len(lines)) + 2 * margin
    if width * height > MAX_LAYER_PIXELS:
        raise ImageProblem(tr("文字が大きすぎます。文字の大きさか文字数を減らしてください。"))
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    painter.setFont(font)
    painter.setPen(QColor(style.color))
    for number, line in enumerate(lines):
        painter.drawText(QPointF(margin, margin + metrics.ascent() + number * metrics.lineSpacing()), line)
    painter.end()
    return image, margin


def to_pil(image: QImage) -> Image.Image:
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombuffer("RGBA", (image.width(), image.height()), bytes(image.constBits()), "raw", "RGBA",
                            image.bytesPerLine(), 1).copy()


class _Placed:
    """The text composited over its part of the image; ``crop`` takes image coordinates (Stroke's effect)."""

    def __init__(self, image: Image.Image, origin: tuple[int, int]):
        self.image = image
        self.origin = origin

    def crop(self, box):
        x, y = self.origin
        return self.image.crop((box[0] - x, box[1] - y, box[2] - x, box[3] - y))


def text_stroke(document: Document, text: str, style: TextStyle, point: tuple[float, float]) -> Stroke | None:
    """A stroke that writes ``text`` with its first line's top left at ``point``; None if nothing lands on the image."""
    if not text.strip():
        return None
    if len(text) > MAX_TEXT:
        raise ImageProblem(tr("文字が多すぎます（{count}文字まで）。").format(count=MAX_TEXT))
    rendered, margin = render_text(text, style)
    layer = to_pil(rendered)
    x, y = round(point[0]) - margin, round(point[1]) - margin
    width, height = document.image.size
    box = (max(0, x), max(0, y), min(width, x + layer.width), min(height, y + layer.height))
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    part = layer.crop((box[0] - x, box[1] - y, box[2] - x, box[3] - y))
    coverage = part.getchannel("A").point(lambda value: 255 if value else 0)
    if coverage.getbbox() is None:
        return None
    base = document.image.crop(box)
    placed = _Placed(Image.alpha_composite(base, part), box[:2])
    stroke = Stroke(document, Tool("text"), cast(Image.Image, placed))
    stroke.mask.paste(coverage, box[:2])
    return stroke


class TextDialog(QDialog):
    """Text, font, size, colour and bold; ``changed`` fires on every edit (for the preview on the image)."""

    changed = Signal()

    def __init__(self, style: TextStyle, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("テキストを入れる"))
        self.setMinimumWidth(420)
        self.color = style.color
        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText(tr("入れる文字（改行もできます）"))
        self.text.setMinimumHeight(90)
        self.text.textChanged.connect(self.changed)
        layout.addWidget(self.text)
        row = QHBoxLayout()
        self.font_box = QFontComboBox()
        self.font_box.setAccessibleName(tr("フォント"))
        self.font_box.setCurrentFont(text_font(style))
        self.font_box.currentFontChanged.connect(self.changed)
        row.addWidget(self.font_box, 1)
        self.size_box = QSpinBox()
        self.size_box.setRange(MIN_SIZE, MAX_SIZE)
        self.size_box.setSuffix(" px")
        self.size_box.setValue(style.size)
        self.size_box.setAccessibleName(tr("文字の大きさ"))
        self.size_box.setToolTip(tr("文字の大きさ（元画像のpx）"))
        self.size_box.valueChanged.connect(self.changed)
        row.addWidget(self.size_box)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.color_button = QPushButton()
        self.color_button.setAccessibleName(tr("文字の色"))
        self.color_button.clicked.connect(self.choose_color)
        row.addWidget(self.color_button)
        self.bold = QCheckBox(tr("太字"))
        self.bold.setChecked(style.bold)
        self.bold.toggled.connect(self.changed)
        row.addWidget(self.bold)
        row.addStretch(1)
        layout.addLayout(row)
        note = QLabel(tr("クリックした位置が文字の左上になります。入れた文字は画像の一部になり、「元に戻す」や消しゴムで消せます。"))
        note.setObjectName("faint")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText(tr("入れる"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("キャンセル"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.changed.connect(self.update_buttons)
        self.update_color()
        self.update_buttons()
        self.text.setFocus()

    def choose_color(self):
        color = QColorDialog.getColor(QColor(self.color), self, tr("文字の色"))
        if color.isValid():
            self.color = color.name()
            self.update_color()
            self.changed.emit()

    def update_color(self):
        self.color_button.setIcon(swatch(self.color))
        self.color_button.setText(self.color.upper())

    def update_buttons(self):
        self.ok_button.setEnabled(bool(self.text.toPlainText().strip()))

    def value(self) -> str:
        return self.text.toPlainText()[:MAX_TEXT]

    def text_style(self) -> TextStyle:
        return TextStyle(self.font_box.currentFont().family(), self.size_box.value(), self.color, self.bold.isChecked())
