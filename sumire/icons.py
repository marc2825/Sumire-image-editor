"""Code-drawn line icons, so the distribution needs no image resources.

Each icon is drawn once in a 16-unit design grid at 64 px and Qt scales it to
the requested size and screen density. Normal, disabled and checked ("on")
variants use the theme's text, disabled and accent colours.
"""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from .theme import BRAND, TOKENS

_SIZE = 64


def _line(painter: QPainter, *points):
    path = QPainterPath(QPointF(*points[0]))
    for point in points[1:]:
        path.lineTo(QPointF(*point))
    painter.drawPath(path)


def _draw(painter: QPainter, name: str, color: QColor):
    pen = QPen(color, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if name in ("undo", "redo"):
        if name == "redo":
            painter.translate(16, 0)
            painter.scale(-1, 1)
        _line(painter, (5.5, 3.5), (2.5, 6.5), (5.5, 9.5))
        path = QPainterPath(QPointF(3, 6.5))
        path.lineTo(9.5, 6.5)
        path.cubicTo(12, 6.5, 13.5, 8.2, 13.5, 10)
        path.cubicTo(13.5, 11.8, 12, 13, 9.5, 13)
        path.lineTo(7, 13)
        painter.drawPath(path)
    elif name == "settings":
        # A gear: eight teeth around a ring, with a hollow hub.
        import math
        path = QPainterPath()
        for tooth in range(8):
            base = math.radians(tooth * 45)
            for offset, radius in ((-15, 4.7), (-8, 6.6), (8, 6.6), (15, 4.7)):
                angle = base + math.radians(offset)
                point = QPointF(8 + radius * math.cos(angle), 8 + radius * math.sin(angle))
                path.moveTo(point) if tooth == 0 and offset == -15 else path.lineTo(point)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawEllipse(QPointF(8, 8), 2, 2)
    elif name in ("rotate_right", "rotate_left"):
        # A three-quarter arc with an arrowhead: ↻ clockwise, mirrored for ↺.
        if name == "rotate_left":
            painter.translate(16, 0)
            painter.scale(-1, 1)
        path = QPainterPath()
        path.arcMoveTo(QRectF(2.5, 2.5, 11, 11), 90)
        path.arcTo(QRectF(2.5, 2.5, 11, 11), 90, 270)
        painter.drawPath(path)
        _line(painter, (5.5, 0.8), (8, 2.5), (6, 5))
    elif name in ("flip_horizontal", "flip_vertical"):
        # Two mirrored triangles about a dashed axis: ◁┆▷, or rotated for top/bottom.
        if name == "flip_vertical":
            painter.translate(16, 0)
            painter.rotate(90)
        dashed = QPen(painter.pen())
        dashed.setDashPattern([1.5, 1.5])
        painter.save()
        painter.setPen(dashed)
        _line(painter, (8, 1.5), (8, 14.5))
        painter.restore()
        painter.setBrush(color)
        triangle = QPainterPath(QPointF(6, 4))
        triangle.lineTo(1.5, 12)
        triangle.lineTo(6, 12)
        triangle.closeSubpath()
        painter.drawPath(triangle)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        outline = QPainterPath(QPointF(10, 4))
        outline.lineTo(14.5, 12)
        outline.lineTo(10, 12)
        outline.closeSubpath()
        painter.drawPath(outline)
    elif name == "crop":
        _line(painter, (4.5, 1.5), (4.5, 11.5), (14.5, 11.5))
        _line(painter, (1.5, 4.5), (11.5, 4.5), (11.5, 14.5))
    elif name == "menu":
        for y in (4.5, 8, 11.5):
            _line(painter, (2.5, y), (13.5, y))
    elif name == "more":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        for x in (3.5, 8, 12.5):
            painter.drawEllipse(QPointF(x, 8), 1.25, 1.25)
    elif name == "chevron_left":
        _line(painter, (10, 3.5), (5.5, 8), (10, 12.5))
    elif name == "chevron_right":
        _line(painter, (6, 3.5), (10.5, 8), (6, 12.5))
    elif name == "chevron_down":
        _line(painter, (4, 6), (8, 10), (12, 6))
    elif name == "search":
        painter.drawEllipse(QPointF(7, 7), 4.3, 4.3)
        _line(painter, (10.3, 10.3), (13.5, 13.5))
    elif name == "filter":
        _line(painter, (2.5, 4.5), (13.5, 4.5))
        _line(painter, (4.5, 8), (11.5, 8))
        _line(painter, (6.5, 11.5), (9.5, 11.5))
    elif name == "compare":
        painter.drawRoundedRect(QRectF(2.5, 3.5, 11, 9), 1.5, 1.5)
        _line(painter, (8, 2), (8, 14))
        painter.setPen(Qt.PenStyle.NoPen)
        fill = QColor(color)
        fill.setAlphaF(0.45)
        painter.setBrush(fill)
        painter.drawRect(QRectF(3.2, 4.2, 4.1, 7.6))
    elif name == "mask":
        painter.drawRoundedRect(QRectF(2.5, 2.5, 11, 11), 1.5, 1.5)
        painter.setPen(Qt.PenStyle.NoPen)
        fill = QColor(color)
        fill.setAlphaF(0.6)
        painter.setBrush(fill)
        painter.drawEllipse(QPointF(8, 8), 3, 3)
    elif name == "fit":
        for (x, y), (dx, dy) in (((2.5, 2.5), (1, 1)), ((13.5, 2.5), (-1, 1)), ((2.5, 13.5), (1, -1)), ((13.5, 13.5), (-1, -1))):
            _line(painter, (x, y + 3.5 * dy), (x, y), (x + 3.5 * dx, y))
    elif name == "close":
        _line(painter, (4, 4), (12, 12))
        _line(painter, (12, 4), (4, 12))
    elif name == "folder":
        path = QPainterPath(QPointF(2, 4.5))
        path.lineTo(6, 4.5)
        path.lineTo(7.5, 6)
        path.lineTo(14, 6)
        path.lineTo(14, 12.5)
        path.lineTo(2, 12.5)
        path.closeSubpath()
        painter.drawPath(path)
    elif name in ("folder_up", "folder_plus"):
        path = QPainterPath(QPointF(1.5, 4))
        path.lineTo(5.5, 4)
        path.lineTo(7, 5.5)
        path.lineTo(14.5, 5.5)
        path.lineTo(14.5, 13)
        path.lineTo(1.5, 13)
        path.closeSubpath()
        painter.drawPath(path)
        if name == "folder_up":
            _line(painter, (8, 11.5), (8, 7.5))
            _line(painter, (6, 9.5), (8, 7.5), (10, 9.5))
        else:
            _line(painter, (8, 7.5), (8, 11.5))
            _line(painter, (6, 9.5), (10, 9.5))
    elif name == "image":
        painter.drawRoundedRect(QRectF(2, 3, 12, 10), 1.5, 1.5)
        _line(painter, (2.5, 11.5), (6, 8), (8.5, 10.5), (10.5, 8.5), (13.5, 11.5))
        painter.drawEllipse(QPointF(10.5, 5.8), 1, 1)
    elif name == "eraser":
        painter.translate(8, 8)
        painter.rotate(-45)
        painter.drawRoundedRect(QRectF(-6, -3, 12, 6), 1.2, 1.2)
        _line(painter, (-1, -3), (-1, 3))
        painter.resetTransform()
        painter.scale(_SIZE / 16, _SIZE / 16)
        _line(painter, (7.5, 13.5), (13.5, 13.5))
    elif name == "text":
        # A "T": the bar with small serifs, the stem with a foot.
        _line(painter, (3, 4.5), (3, 3), (13, 3), (13, 4.5))
        _line(painter, (8, 3), (8, 13))
        _line(painter, (6, 13), (10, 13))
    elif name == "tag":
        path = QPainterPath(QPointF(2.5, 2.5))
        for x, y in ((8.5, 2.5), (13.5, 7.5), (8, 13), (2.5, 7.5), (2.5, 2.5)):
            path.lineTo(QPointF(x, y))
        painter.drawPath(path)
        painter.drawEllipse(QPointF(5.5, 5.5), 1, 1)
    elif name == "check":
        _line(painter, (3.5, 8.5), (6.5, 11.5), (12.5, 4.5))
    elif name == "note":
        _line(painter, (3, 13), (3.6, 10.4), (10.6, 3.4), (12.6, 5.4), (5.6, 12.4), (3, 13))
    elif name == "help":
        painter.drawEllipse(QRectF(1.5, 1.5, 13, 13))
        path = QPainterPath(QPointF(5.8, 5.8))
        path.cubicTo(5.8, 2.9, 10.5, 3.5, 10.5, 5.7)
        path.cubicTo(10.5, 7.4, 8, 7.1, 8, 9.5)
        painter.drawPath(path)
        painter.drawPoint(QPointF(8, 11.7))
    elif name == "reload":
        # Reload: an almost closed circle, the arrow at the top pointing into the gap (⟳).
        path = QPainterPath()
        path.arcMoveTo(QRectF(2.5, 2.5, 11, 11), 80)
        path.arcTo(QRectF(2.5, 2.5, 11, 11), 80, 305)
        painter.drawPath(path)
        _line(painter, (7.4, 0.6), (10, 2.6), (7.6, 4.8))
    elif name == "plus":
        _line(painter, (8, 3), (8, 13))
        _line(painter, (3, 8), (13, 8))
    elif name == "share":
        painter.drawRoundedRect(QRectF(2.5, 6.5, 11, 7), 1.5, 1.5)
        _line(painter, (8, 10), (8, 2.5))
        _line(painter, (5.5, 5), (8, 2.5), (10.5, 5))
    # The tools: mosaic, blur and fill, and the shapes they are applied with.
    elif name == "mosaic":
        painter.drawRect(QRectF(2.5, 2.5, 11, 11))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRect(QRectF(2.5, 2.5, 5.5, 5.5))
        painter.drawRect(QRectF(8, 8, 5.5, 5.5))
    elif name == "blur":
        path = QPainterPath(QPointF(8, 2))
        path.cubicTo(10.5, 5, 12.5, 7.5, 12.5, 9.7)
        path.cubicTo(12.5, 12.2, 10.5, 14, 8, 14)
        path.cubicTo(5.5, 14, 3.5, 12.2, 3.5, 9.7)
        path.cubicTo(3.5, 7.5, 5.5, 5, 8, 2)
        painter.drawPath(path)
        _line(painter, (6, 10.5), (6.5, 11.8), (7.8, 12.3))
    elif name == "fill":
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(2.5, 2.5, 11, 11), 1.5, 1.5)
    elif name == "brush":
        path = QPainterPath(QPointF(2, 12))
        path.cubicTo(4.5, 4, 6.5, 13.5, 9, 8)
        path.cubicTo(10.5, 4.5, 12, 4.5, 14, 5)
        painter.drawPath(path)
    elif name == "rectangle":
        painter.drawRect(QRectF(2.5, 4, 11, 8))
    elif name == "ellipse":
        painter.drawEllipse(QRectF(2, 3.5, 12, 9))
    elif name == "polygon":
        _line(painter, (8, 2.5), (13.5, 6.5), (11.5, 13), (4.5, 13), (2.5, 6.5), (8, 2.5))
    elif name == "lasso":
        path = QPainterPath(QPointF(6.5, 11))
        path.cubicTo(3.5, 10.5, 2, 8.8, 2, 7)
        path.cubicTo(2, 4.5, 4.7, 2.5, 8, 2.5)
        path.cubicTo(11.3, 2.5, 14, 4.5, 14, 7)
        path.cubicTo(14, 9.5, 11.3, 11.3, 8, 11.3)
        painter.drawPath(path)
        _line(painter, (6.5, 11), (5.6, 12.6), (7, 14))
    # The side panels, shown or folded.
    elif name in ("sidebar_left", "sidebar_right"):
        if name == "sidebar_right":
            painter.translate(16, 0)
            painter.scale(-1, 1)
        painter.drawRoundedRect(QRectF(1.5, 2.5, 13, 11), 1.5, 1.5)
        _line(painter, (6, 2.5), (6, 13.5))
        painter.setPen(Qt.PenStyle.NoPen)
        fill = QColor(color)
        fill.setAlphaF(0.45)
        painter.setBrush(fill)
        painter.drawRect(QRectF(2.2, 3.2, 3.2, 9.6))
    elif name == "adjust":
        _line(painter, (2, 5), (9, 5))
        _line(painter, (13, 5), (14, 5))
        _line(painter, (2, 11), (3, 11))
        _line(painter, (7, 11), (14, 11))
        painter.drawEllipse(QPointF(11, 5), 2, 2)
        painter.drawEllipse(QPointF(5, 11), 2, 2)
    elif name == "stack":
        # Several images at once: the whole-list work.
        painter.drawRoundedRect(QRectF(2.5, 6, 9, 7.5), 1.2, 1.2)
        _line(painter, (4.5, 4), (13.5, 4), (13.5, 11))


def _pixmap(name: str, color: str) -> QPixmap:
    pixmap = QPixmap(_SIZE, _SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(_SIZE / 16, _SIZE / 16)
    _draw(painter, name, QColor(color))
    painter.end()
    return pixmap


@lru_cache(maxsize=None)
def icon(name: str, tone: str = "text") -> QIcon:
    result = QIcon()
    result.addPixmap(_pixmap(name, TOKENS[tone]), QIcon.Mode.Normal, QIcon.State.Off)
    result.addPixmap(_pixmap(name, TOKENS["accent"]), QIcon.Mode.Normal, QIcon.State.On)
    result.addPixmap(_pixmap(name, TOKENS["text_disabled"]), QIcon.Mode.Disabled, QIcon.State.Off)
    result.addPixmap(_pixmap(name, TOKENS["text_disabled"]), QIcon.Mode.Disabled, QIcon.State.On)
    return result


def swatch(color: str, size: int = 14) -> QIcon:
    """A rounded colour chip for the fill colour button."""
    scale = 4
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(TOKENS["line_strong"]), scale))
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(QRectF(scale / 2, scale / 2, size * scale - scale, size * scale - scale), 3 * scale, 3 * scale)
    painter.end()
    return QIcon(pixmap)


# The four squares of the mark in a 64-unit square: (x, y, BRAND colour).
MARK_SQUARES = ((14, 14, "light"), (34, 14, "mid"), (14, 34, "deep"), (34, 34, "light"))


def app_mark(size: int = 64) -> QPixmap:
    """The established four-square Sumīre mark (matches assets/sumire.ico)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    unit = size / 64
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(BRAND["ground"]))
    painter.drawRoundedRect(QRectF(0, 0, size, size), 12 * unit, 12 * unit)
    for x, y, value in MARK_SQUARES:
        painter.setBrush(QColor(BRAND[value]))
        painter.drawRect(QRectF(x * unit, y * unit, 16 * unit, 16 * unit))
    painter.end()
    return pixmap


def grab_hand(ratio: float = 1.0, size: int = 28) -> QPixmap:
    """A closed hand, shown while images are dragged to reorder or move them.

    Drawn as a picture rather than a cursor shape: on Windows a drag shows
    only pixmaps, so the system's own hand cursor can't be used there.
    """
    pixmap = QPixmap(round(size * ratio), round(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 24, size / 24)
    shape = QPainterPath()
    shape.addRoundedRect(QRectF(5, 10, 16, 11.5), 4, 4)  # palm
    for x in (6, 10, 14, 18):  # curled fingers
        finger = QPainterPath()
        finger.addRoundedRect(QRectF(x, 6, 4, 8), 2, 2)
        shape = shape.united(finger)
    thumb = QPainterPath()
    thumb.addRoundedRect(QRectF(2, 11, 6.5, 5), 2.5, 2.5)
    shape = shape.united(thumb)
    painter.setPen(QPen(QColor("#111111"), 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(QColor("#ffffff"))
    painter.drawPath(shape)
    painter.setPen(QPen(QColor("#111111"), 1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for x in (10, 14, 18):
        _line(painter, (x, 8), (x, 12))
    painter.end()
    return pixmap
