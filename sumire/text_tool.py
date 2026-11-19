"""Text written into the image: placement, rendering with Qt, the undoable edit, and the dialog.

A text is a placement (the text, its style, the centre of its block and its angle). Writing it
replaces the pixels under its box as one undoable edit and remembers those pixels (``TextState``),
so a later move, rotation, resize or rewrite takes the old text out and writes the new one as one
more edit. The pixels always hold the text, so saving and switching images need nothing special;
Undo goes back to the previous placement. The text also counts as an edited area (the mask).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QImage, QPainter, QTransform
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QDialog, QDialogButtonBox, QFontComboBox, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout,
)

from .i18n import tr
from .icons import swatch
from .imaging import Document, ImageProblem

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


def margin(style: TextStyle) -> int:
    """Room around the block for glyphs that reach past their advance (italic ends, accents)."""
    return math.ceil(max(MIN_SIZE, min(MAX_SIZE, style.size)) * 0.25) + 2


def block_size(text: str, style: TextStyle) -> tuple[float, float]:
    """Width (the longest line) and height (the lines) of the text block, in image pixels."""
    metrics = QFontMetricsF(text_font(style))
    lines = text.split("\n")
    return max(metrics.horizontalAdvance(line) for line in lines), metrics.lineSpacing() * len(lines)


@dataclass(frozen=True)
class TextPlacement:
    text: str
    style: TextStyle
    center: tuple[float, float]
    angle: float = 0.0  # degrees, clockwise on the screen

    def size(self) -> tuple[float, float]:
        return block_size(self.text, self.style)

    def transform(self) -> QTransform:
        """Block coordinates (0, 0)–(width, height) to image coordinates."""
        width, height = self.size()
        transform = QTransform()
        transform.translate(*self.center)
        transform.rotate(self.angle)
        transform.translate(-width / 2, -height / 2)
        return transform

    def corners(self) -> list[QPointF]:
        """Top left, top right, bottom right and bottom left of the block, in image coordinates."""
        width, height = self.size()
        transform = self.transform()
        return [transform.map(QPointF(x, y)) for x, y in ((0, 0), (width, 0), (width, height), (0, height))]

    def to_block(self, point: QPointF) -> QPointF:
        """An image point in block coordinates (to test what it hits)."""
        inverse, _ = self.transform().inverted()
        return inverse.map(point)


def placement_at(text: str, style: TextStyle, top_left: tuple[float, float], angle: float = 0.0) -> TextPlacement:
    """The placement whose block has its top left corner at ``top_left`` (so new text grows right and down)."""
    width, height = block_size(text, style)
    radians = math.radians(angle)
    dx, dy = width / 2, height / 2
    return TextPlacement(text, style, (top_left[0] + dx * math.cos(radians) - dy * math.sin(radians),
                                       top_left[1] + dx * math.sin(radians) + dy * math.cos(radians)), angle)


def render_placed(placement: TextPlacement, bounds: tuple[int, int] | None = None,
                  resolution: float = 1.0) -> tuple[QImage, QRectF] | None:
    """The text drawn as placed, and the rectangle it covers in image coordinates.

    Only the part inside ``bounds`` (the image's size) is drawn, so a huge text costs no more than
    the image. ``resolution`` below 1 draws a smaller image for previews at the screen's scale.
    None when nothing of it is inside.
    """
    if not placement.text.strip():
        return None
    room = margin(placement.style)
    width, height = placement.size()
    transform = placement.transform()
    rect = transform.mapRect(QRectF(-room, -room, width + 2 * room, height + 2 * room))
    if bounds is not None:
        rect = rect.intersected(QRectF(0, 0, *bounds))
    if rect.isEmpty():
        return None
    left, top = math.floor(rect.left()), math.floor(rect.top())
    right, bottom = math.ceil(rect.right()), math.ceil(rect.bottom())
    pixels_x, pixels_y = max(1, math.ceil((right - left) * resolution)), max(1, math.ceil((bottom - top) * resolution))
    if pixels_x * pixels_y > MAX_LAYER_PIXELS:
        raise ImageProblem(tr("文字が大きすぎます。文字の大きさか文字数を減らしてください。"))
    image = QImage(pixels_x, pixels_y, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    font = text_font(placement.style)
    metrics = QFontMetricsF(font)
    painter = QPainter(image)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
                           | QPainter.RenderHint.SmoothPixmapTransform)
    painter.scale(resolution, resolution)
    painter.translate(-left, -top)
    painter.setTransform(transform, True)
    painter.setFont(font)
    painter.setPen(QColor(placement.style.color))
    for number, line in enumerate(placement.text.split("\n")):
        painter.drawText(QPointF(0, metrics.ascent() + number * metrics.lineSpacing()), line)
    painter.end()
    return image, QRectF(left, top, right - left, bottom - top)


def to_pil(image: QImage) -> Image.Image:
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombuffer("RGBA", (image.width(), image.height()), bytes(image.constBits()), "raw", "RGBA",
                            image.bytesPerLine(), 1).copy()


def text_layer(placement: TextPlacement, size: tuple[int, int]) -> tuple[Image.Image, tuple[int, int]] | None:
    """The text's pixels inside an image of ``size``, and where they go; None if nothing shows."""
    if len(placement.text) > MAX_TEXT:
        raise ImageProblem(tr("文字が多すぎます（{count}文字まで）。").format(count=MAX_TEXT))
    rendered = render_placed(placement, size)
    if rendered is None:
        return None
    image, rect = rendered
    layer = to_pil(image)
    if layer.getchannel("A").getbbox() is None:
        return None
    return layer, (round(rect.left()), round(rect.top()))


@dataclass(frozen=True)
class TextState:
    """A text as written: its placement, the box it changed and the pixels and mask it replaced there."""
    placement: TextPlacement
    box: tuple[int, int, int, int]
    under: Image.Image
    under_mask: Image.Image


def write_text(document: Document, placement: TextPlacement | None, layer, old: TextState | None):
    """Take ``old`` out (if any) and write ``layer`` (if any) as one undoable edit.

    ``layer`` is ``text_layer(placement, …)``. Returns (the new TextState or None, whether the image changed).
    """
    boxes = [old.box] if old is not None else []
    if layer is not None:
        pixels, (x, y) = layer
        boxes.append((x, y, x + pixels.width, y + pixels.height))
    if not boxes:
        return None, False
    union = (min(box[0] for box in boxes), min(box[1] for box in boxes), max(box[2] for box in boxes), max(box[3] for box in boxes))
    before = document.image.crop(union)
    before_mask = document.edit_mask.crop(union)
    after, after_mask = before.copy(), before_mask.copy()
    left, top = union[:2]
    if old is not None:
        after.paste(old.under, (old.box[0] - left, old.box[1] - top))
        after_mask.paste(old.under_mask, (old.box[0] - left, old.box[1] - top))
    state = None
    if layer is not None and placement is not None:
        pixels, (x, y) = layer
        spot = (x - left, y - top, x - left + pixels.width, y - top + pixels.height)
        state = TextState(placement, (x, y, x + pixels.width, y + pixels.height), after.crop(spot), after_mask.crop(spot))
        after.alpha_composite(pixels, dest=spot[:2])
        after_mask.paste(255, spot, pixels.getchannel("A").point(lambda value: 255 if value else 0))
    document.image.paste(after, union[:2])
    document.edit_mask.paste(after_mask, union[:2])
    try:
        changed = document.commit(before, union, before_mask, cropped=True)
    except Exception:
        document.image.paste(before, union[:2])
        document.edit_mask.paste(before_mask, union[:2])
        raise
    return state, changed


class TextDialog(QDialog):
    """Text, font, size, colour and bold. ``changed`` fires shortly after edits (the preview on the image)."""

    changed = Signal()

    def __init__(self, style: TextStyle, parent=None, text: str = "", editing: bool = False):
        super().__init__(parent)
        self.setWindowTitle(tr("テキストを編集") if editing else tr("テキストを入れる"))
        self.setMinimumWidth(420)
        self.color = style.color
        # Typing fast with a large size must not redraw the preview on every key (issue #3).
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(120)
        self.debounce.timeout.connect(self.changed)
        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText(tr("入れる文字（改行もできます）"))
        self.text.setMinimumHeight(90)
        self.text.setPlainText(text)
        self.text.textChanged.connect(self.edited)
        layout.addWidget(self.text)
        row = QHBoxLayout()
        self.font_box = QFontComboBox()
        self.font_box.setAccessibleName(tr("フォント"))
        self.font_box.setCurrentFont(text_font(style))
        self.font_box.currentFontChanged.connect(self.edited)
        row.addWidget(self.font_box, 1)
        self.size_box = QSpinBox()
        self.size_box.setRange(MIN_SIZE, MAX_SIZE)
        self.size_box.setSuffix(" px")
        self.size_box.setValue(style.size)
        self.size_box.setAccessibleName(tr("文字の大きさ"))
        self.size_box.setToolTip(tr("文字の大きさ（元画像のpx）"))
        self.size_box.valueChanged.connect(self.edited)
        row.addWidget(self.size_box)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.color_button = QPushButton()
        self.color_button.setAccessibleName(tr("文字の色"))
        self.color_button.clicked.connect(self.choose_color)
        row.addWidget(self.color_button)
        self.bold = QCheckBox(tr("太字"))
        self.bold.setChecked(style.bold)
        self.bold.toggled.connect(self.edited)
        row.addWidget(self.bold)
        row.addStretch(1)
        layout.addLayout(row)
        note = QLabel(tr("入れた後も、枠をドラッグして移動、角で拡大・縮小、上の丸で回転、ダブルクリックで書き直しができます。"
                         "「元に戻す」で1つ前に戻ります。"))
        note.setObjectName("faint")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText(tr("適用") if editing else tr("入れる"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("キャンセル"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.update_color()
        self.update_buttons()
        self.text.setFocus()
        self.text.moveCursor(self.text.textCursor().MoveOperation.End)

    def edited(self, *args):
        self.update_buttons()
        self.debounce.start()

    def choose_color(self):
        color = QColorDialog.getColor(QColor(self.color), self, tr("文字の色"))
        if color.isValid():
            self.color = color.name()
            self.update_color()
            self.edited()

    def update_color(self):
        self.color_button.setIcon(swatch(self.color))
        self.color_button.setText(self.color.upper())

    def update_buttons(self):
        self.ok_button.setEnabled(bool(self.text.toPlainText().strip()))

    def value(self) -> str:
        return self.text.toPlainText()[:MAX_TEXT]

    def text_style(self) -> TextStyle:
        return TextStyle(self.font_box.currentFont().family(), self.size_box.value(), self.color, self.bold.isChecked())
