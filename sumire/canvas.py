from __future__ import annotations
from typing import cast
from .i18n import tr

import math
from dataclasses import replace

from PIL import Image
from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QPen, QPixmap, QPolygonF, QWheelEvent
from PySide6.QtWidgets import QWidget

from .imaging import Document, Stroke, Tool, region_mask
from .theme import TOKENS
from .shortcuts import CANVAS_COMMANDS, defaults, matches


def qimage(image: Image.Image) -> QImage:
    rgba = image if image.mode == "RGBA" else image.convert("RGBA")
    return QImage(rgba.tobytes(), rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888).copy()


LASSO_FLASH_MS = 280


def _crossing(p1, p2, q1, q2):
    """Where segment p1→p2 crosses q1→q2, as the fraction along p1→p2; None if it doesn't."""
    rx, ry = p2[0] - p1[0], p2[1] - p1[1]
    sx, sy = q2[0] - q1[0], q2[1] - q1[1]
    denominator = rx * sy - ry * sx
    if abs(denominator) < 1e-12:
        return None  # parallel (or overlapping) segments close nothing
    qx, qy = q1[0] - p1[0], q1[1] - p1[1]
    t = (qx * sy - qy * sx) / denominator
    u = (qx * ry - qy * rx) / denominator
    return t if 0 <= t <= 1 and 0 <= u <= 1 else None


def loop_closed_by_last_segment(points):
    """The closed region made when the newest segment of a lasso crosses an earlier one.

    Returns the region's polygon (the crossing point, then the points drawn
    since), or None. Of several crossings, the first one along the new segment
    closes the region first.
    """
    if len(points) < 4:
        return None
    last = len(points) - 2
    p1, p2 = points[last], points[last + 1]
    best = None
    for index in range(last - 1):  # the segment just before shares a point and is skipped
        t = _crossing(p1, p2, points[index], points[index + 1])
        if t is not None and (best is None or t < best[0]):
            best = (t, index)
    if best is None:
        return None
    t, index = best
    crossing = (p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t)
    loop = [crossing, *points[index + 1:last + 1]]
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(loop, loop[1:] + loop[:1])) / 2
    return loop if abs(area) >= 1 else None


class Canvas(QWidget):
    strokeStarted = Signal()
    strokeCancelled = Signal()
    lassoNotClosed = Signal()
    strokeFinished = Signal(object)
    zoomChanged = Signal(float)
    filesDropped = Signal(list)
    eraserRequested = Signal()
    textToolRequested = Signal()
    textRequested = Signal(QPointF)
    textTransformed = Signal(object)  # the new TextPlacement after a drag on the box
    textEditRequested = Signal()
    textDeleteRequested = Signal()
    textDeselected = Signal()
    maskToggleRequested = Signal()
    colorPicked = Signal(str)

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(True)
        self.setMinimumSize(280, 280)
        self.document: Document | None = None
        self.tool = Tool()
        self.shape = "brush"
        self.effect: Image.Image | None = None
        self.ready = False
        self.locked = False
        self.message = ""
        self.scale = 1.0
        self.offset = QPointF()
        self.fitted = True
        self.compare = False
        self.image = QImage()
        self.original = QImage()
        self.original_source = None
        self.mask_overlay = QImage()
        self.show_mask = False
        self.stroke: Stroke | None = None
        self.cursor_point: QPointF | None = None
        self.selection_start: QPointF | None = None
        self.pan_start: QPointF | None = None
        self.selection_points = []
        self.lasso_loop = self.flash_points = self.flash_token = None
        self.invert_selection = False
        self.last_brush_point = None
        # (image, top left in image pixels) of the text being typed, drawn over the image.
        self.text_preview: tuple[QImage, QRectF] | None = None
        # Pixels without the text being edited (image, top left), drawn under its preview.
        self.text_under: tuple[QImage, QPointF] | None = None
        # The text that can be edited (a TextState): its box and handles are drawn and dragged.
        self.text_box = None
        self.text_drag: dict | None = None
        self.space_down = False
        self.pan_key = None
        self.bindings = defaults()
        tile = QPixmap(20, 20)
        tile.fill(QColor(TOKENS["checker_a"]))
        painter = QPainter(tile)
        painter.fillRect(0, 0, 10, 10, QColor(TOKENS["checker_b"]))
        painter.fillRect(10, 10, 10, 10, QColor(TOKENS["checker_b"]))
        painter.end()
        self.checker = tile
        self.navigator = Navigator(self)
        self.navigator.hide()

    def set_document(self, document: Document | None, *, render=True):
        self.document = document
        self.selection_points = []
        self.lasso_loop = self.flash_points = self.flash_token = None
        self.last_brush_point = None
        self.text_preview = None
        self.text_under = None
        self.text_box = None
        self.text_drag = None
        self.effect = None
        self.ready = False
        self.compare = False
        self.needs_fit = bool(document)
        if document and render:
            self.image = qimage(document.image)
            self.original = qimage(document.original)
            self.original_source = document.original
            self.refresh_mask()
            self.fit()
            self.needs_fit = False
        else:
            self.image = self.original = QImage()
            self.mask_overlay = QImage()
        self.update()

    def release_display(self):
        self.image = self.original = self.mask_overlay = QImage()
        self.effect = None
        self.original_source = None
        self.ready = False

    def restore_display(self):
        if self.document and self.image.isNull():
            self.image = qimage(self.document.image)
            self.original = qimage(self.document.original)
            self.original_source = self.document.original
            self.refresh_mask()
            if self.needs_fit:
                self.fit()
                self.needs_fit = False
            self.update()

    @property
    def memory(self):
        display = sum(image.sizeInBytes() for image in (self.image, self.original, self.mask_overlay))
        return display + (self.effect.width * self.effect.height * 4 if self.effect is not None else 0)

    def refresh(self, box=None):
        if self.document:
            if self.image.isNull():
                return
            if self.image.size().width() != self.document.image.width or self.image.size().height() != self.document.image.height:
                self.set_document(self.document)
                return
            if box:
                painter = QPainter(self.image)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                painter.drawImage(box[0], box[1], qimage(self.document.image.crop(box)))
                painter.end()
            else:
                self.image = qimage(self.document.image)
            self.refresh_mask(box)
            if self.original_source is not self.document.original:
                self.original = qimage(self.document.original)
                self.original_source = self.document.original
            self.navigator.update()
        self.update()

    def refresh_mask(self, box=None):
        if not self.document or not self.show_mask:
            self.mask_overlay = QImage()
            return
        mask = self.document.edit_mask.crop(box) if box else self.document.edit_mask
        overlay = Image.new("RGBA", mask.size, (65, 200, 255, 0))
        overlay.putalpha(mask.point(lambda value: round(value * 0.42)))
        region = qimage(overlay)
        if box and not self.mask_overlay.isNull():
            painter = QPainter(self.mask_overlay)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.drawImage(box[0], box[1], region)
            painter.end()
        else:
            self.mask_overlay = region

    # --- the text box: handles, hit test, dragging -----------------------------------------------

    HANDLE = 5  # half the size of a corner handle, in screen pixels
    ROTATE_OFFSET = 26  # the rotation handle's distance above the top edge, in screen pixels

    def to_screen(self, point: QPointF) -> QPointF:
        return point * self.scale + self.offset

    def text_handles(self, placement=None):
        """Screen positions: the four corners, the middle of the top edge and the rotation handle."""
        corners = [self.to_screen(point) for point in (placement or self.text_box.placement).corners()]
        top = (corners[0] + corners[1]) / 2
        edge = corners[1] - corners[0]
        length = math.hypot(edge.x(), edge.y()) or 1.0
        normal = QPointF(edge.y() / length, -edge.x() / length)  # pointing away from the block, above it
        return corners, top, top + normal * self.ROTATE_OFFSET

    def text_hit(self, position: QPointF):
        """What a screen point is on: "rotate", "corner0"…"corner3", "move" (inside) or None."""
        if self.text_box is None:
            return None
        corners, _, rotate = self.text_handles()
        reach = self.HANDLE + 4
        if math.hypot(position.x() - rotate.x(), position.y() - rotate.y()) <= reach + 2:
            return "rotate"
        for number, corner in enumerate(corners):
            if abs(position.x() - corner.x()) <= reach and abs(position.y() - corner.y()) <= reach:
                return f"corner{number}"
        placement = self.text_box.placement
        local = placement.to_block(self.to_image(position))
        width, height = placement.size()
        slack = 4 / self.scale
        return "move" if -slack <= local.x() <= width + slack and -slack <= local.y() <= height + slack else None

    def start_text_drag(self, hit, point: QPointF):
        state = self.text_box
        self.text_drag = {"hit": hit, "start": point, "placement": None, "origin": state.placement}
        under = qimage(state.under)
        self.text_under = under, QPointF(state.box[0], state.box[1])
        self.drag_text(point, False)

    def drag_text(self, point: QPointF, snap: bool):
        """The placement for the pointer at ``point`` (image coordinates), shown as a preview."""
        from .text_tool import MAX_SIZE, MIN_SIZE
        drag = self.text_drag
        if drag is None:
            return
        origin = drag["origin"]
        hit, start = drag["hit"], drag["start"]
        cx, cy = origin.center
        if hit == "move":
            placement = replace(origin, center=(cx + point.x() - start.x(), cy + point.y() - start.y()))
        elif hit == "rotate":
            turned = math.degrees(math.atan2(point.y() - cy, point.x() - cx) - math.atan2(start.y() - cy, start.x() - cx))
            angle = (origin.angle + turned) % 360
            if snap:
                angle = round(angle / 15) * 15 % 360
            placement = replace(origin, angle=angle)
        else:
            # A corner: scale about the opposite corner, which stays where it is.
            number = int(hit[-1])
            corners = origin.corners()
            fixed, grabbed = corners[(number + 2) % 4], corners[number]
            diagonal = grabbed - fixed
            length = math.hypot(diagonal.x(), diagonal.y()) or 1.0
            reach = ((point.x() - fixed.x()) * diagonal.x() + (point.y() - fixed.y()) * diagonal.y()) / length
            size = max(MIN_SIZE, min(MAX_SIZE, round(origin.style.size * max(0.01, reach / length))))
            style = replace(origin.style, size=size)
            resized = replace(origin, style=style)
            # Put the new block so that its fixed corner is where the old one was.
            moved = resized.corners()[(number + 2) % 4]
            placement = replace(resized, center=(resized.center[0] + fixed.x() - moved.x(), resized.center[1] + fixed.y() - moved.y()))
        drag["placement"] = placement
        self.show_text_preview(placement)

    def show_text_preview(self, placement):
        """Draw ``placement`` over the image at about the screen's resolution (cheap while dragging or typing)."""
        from .imaging import ImageProblem
        from .text_tool import render_placed
        if self.document is None:
            return
        resolution = min(1.0, self.scale * max(1.0, self.devicePixelRatioF()))
        try:
            self.text_preview = render_placed(placement, self.document.image.size, resolution)
        except ImageProblem:
            self.text_preview = None
        self.update()

    def clear_text_preview(self):
        self.text_preview = None
        self.text_under = None
        self.update()

    def paint_text_box(self, painter: QPainter):
        if self.text_box is None or self.tool.mode != "text":
            return
        dragged = self.text_drag.get("placement") if self.text_drag is not None else None
        corners, top, rotate = self.text_handles(dragged or self.text_box.placement)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = QColor(TOKENS["accent"])
        for color, width in ((QColor(0, 0, 0, 150), 3), (accent, 1.4)):
            painter.setPen(QPen(color, width))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(QPolygonF(corners))
            painter.drawLine(top, rotate)
        painter.setPen(QPen(accent, 1.4))
        painter.setBrush(QColor("#ffffff"))
        for corner in corners:
            painter.drawRect(QRectF(corner.x() - self.HANDLE, corner.y() - self.HANDLE, 2 * self.HANDLE, 2 * self.HANDLE))
        painter.drawEllipse(rotate, self.HANDLE + 1, self.HANDLE + 1)
        painter.restore()

    def tool_cursor(self):
        return Qt.CursorShape.IBeamCursor if self.tool.mode == "text" else Qt.CursorShape.CrossCursor

    def to_image(self, position: QPointF) -> QPointF:
        return (position - self.offset) / self.scale

    def in_image(self, point: QPointF) -> bool:
        return bool(self.document and 0 <= point.x() < self.image.width() and 0 <= point.y() < self.image.height())

    def fit(self):
        if self.image.isNull():
            return
        self.scale = max(0.01, min((self.width() - 64) / self.image.width(), (self.height() - 64) / self.image.height(), 1.0))
        self.offset = QPointF((self.width() - self.image.width() * self.scale) / 2, (self.height() - self.image.height() * self.scale) / 2)
        self.fitted = True
        self.zoomChanged.emit(self.scale)
        self.update()

    def zoom(self, factor: float, anchor: QPointF | None = None):
        if not self.document or self.stroke:
            return
        anchor = anchor or QPointF(self.width() / 2, self.height() / 2)
        point = self.to_image(anchor)
        self.scale = min(16.0, max(0.01, self.scale * factor))
        self.offset = anchor - point * self.scale
        self.fitted = False
        self.zoomChanged.emit(self.scale)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(TOKENS["canvas"]))
        if not self.document:
            # The welcome page handles the first launch; this is an open list
            # whose filter, or folder, currently has nothing to show.
            font = painter.font()
            font.setPixelSize(15)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor(TOKENS["text"]))
            painter.drawText(self.rect().adjusted(20, -40, -20, 0), Qt.AlignmentFlag.AlignCenter, tr("表示する画像がありません"))
            font.setPixelSize(12)
            font.setBold(False)
            painter.setFont(font)
            painter.setPen(QColor(TOKENS["text_muted"]))
            painter.drawText(self.rect().adjusted(20, 30, -20, 0), Qt.AlignmentFlag.AlignCenter,
                             self.message or tr("絞り込みを解除するか、画像・フォルダーをドロップしてください。\nフォルダーに追加された画像は自動で取り込みます。"))
            return
        painter.save()
        painter.translate(self.offset)
        painter.scale(self.scale, self.scale)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.scale < 1)
        rect = QRectF(0, 0, self.image.width(), self.image.height())
        painter.drawTiledPixmap(rect, self.checker)
        painter.drawImage(QPointF(), self.original if self.compare else self.image)
        if self.show_mask and not self.compare:
            painter.drawImage(QPointF(), self.mask_overlay)
        if not self.compare:
            if self.text_under is not None:
                under, origin = self.text_under
                painter.drawImage(origin, under)
            if self.text_preview is not None:
                preview, target = self.text_preview
                painter.drawImage(target, preview)
        painter.restore()
        if not self.compare:
            self.paint_text_box(painter)
        if self.flash_points:
            # The region the lasso closed, shown for a moment before it is applied.
            painter.setPen(QPen(QColor("#ffd166"), 2.5))
            painter.setBrush(QColor(255, 209, 102, 110))
            painter.drawPolygon(QPolygonF([QPointF(x, y) * self.scale + self.offset for x, y in self.flash_points]))
        elif self.selection_points:
            points = [QPointF(x, y) * self.scale + self.offset for x, y in self.selection_points]
            if self.cursor_point is not None:
                points.append(self.cursor_point)
            painter.setPen(QPen(QColor("#8bc7ff"), 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(100, 180, 255, 35))
            if self.shape == "lasso":
                # Open line: the end is not joined to the start. Once the line
                # crosses itself, the region it closed is tinted.
                if self.lasso_loop:
                    painter.save()
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawPolygon(QPolygonF([QPointF(x, y) * self.scale + self.offset for x, y in self.lasso_loop]))
                    painter.restore()
                painter.drawPolyline(QPolygonF(points))
            else:
                painter.drawPolygon(QPolygonF(points))
        elif self.selection_start is not None and self.cursor_point is not None:
            rect = QRectF(self.selection_start * self.scale + self.offset, self.cursor_point).normalized()
            painter.setPen(QPen(QColor("#8bc7ff"), 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(100, 180, 255, 35))
            if self.shape == "ellipse":
                painter.drawEllipse(rect)
            else:
                painter.drawRect(rect)
        elif self.cursor_point and self.shape == "brush" and self.tool.mode != "text" and not self.compare and not self.space_down:
            radius = (self.tool.diameter / 2 + self.tool.expansion) * self.scale
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor(0, 0, 0, 180), 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(self.cursor_point, radius, radius)
            painter.setPen(QPen(QColor("#ffffff"), 1))
            painter.drawEllipse(self.cursor_point, radius, radius)
        if self.compare or self.message:
            label = tr("元画像を表示中 · キーやボタンを離して戻る") if self.compare else self.message
            painter.setPen(QColor("#edf2f8"))
            painter.fillRect(12, 12, min(self.width() - 24, 420), 34, QColor(20, 23, 28, 225))
            painter.drawText(24, 34, label)
        if self.navigator.isVisible():
            self.navigator.update()

    def mousePressEvent(self, event: QMouseEvent):
        self.setFocus()
        pos = event.position()
        if event.button() == Qt.MouseButton.MiddleButton or (event.button() == Qt.MouseButton.LeftButton and self.space_down):
            self.pan_start = pos
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        point = self.to_image(pos)
        if self.document is None:
            return
        if (event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.AltModifier
                and self.in_image(point) and self.ready and not self.locked and not self.compare):
            r, g, b, _ = cast(tuple[int, int, int, int], self.document.image.getpixel((int(point.x()), int(point.y()))))
            self.colorPicked.emit(f"#{r:02x}{g:02x}{b:02x}")
            return
        if self.tool.mode == "text":
            if event.button() != Qt.MouseButton.LeftButton or self.locked or self.compare or self.stroke:
                return
            if self.text_box is not None:
                hit = self.text_hit(pos)
                if hit is not None:
                    self.start_text_drag(hit, point)
                else:  # a click beside the text finishes editing it; the next click adds a new text
                    self.text_box = None
                    self.textDeselected.emit()
                    self.update()
                return
            if self.in_image(point):
                self.textRequested.emit(point)
            return
        if self.shape == "polygon" and self.stroke:
            if event.button() == Qt.MouseButton.LeftButton:
                self.selection_points.append(self.clipped_point(point))
                self.update()
            return
        if event.button() != Qt.MouseButton.LeftButton or not self.in_image(point) or not self.ready or self.locked or self.compare:
            return
        self.stroke = Stroke(self.document, self.tool, self.effect)
        self.ready = False
        self.strokeStarted.emit()
        if self.shape == "brush":
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier and self.last_brush_point is not None:
                self.stroke.add(self.last_brush_point)
            self.refresh(self.stroke.add((point.x(), point.y())))
        elif self.shape in {"polygon", "lasso"}:
            self.selection_points = [self.clipped_point(point)]
            self.lasso_loop = None
        else:
            self.selection_start = point

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position()
        self.cursor_point = pos
        if self.pan_start is not None:
            self.offset += pos - self.pan_start
            self.pan_start = pos
            self.fitted = False
        elif self.text_drag is not None:
            self.drag_text(self.to_image(pos), bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
        elif self.tool.mode == "text" and self.text_box is not None and not self.space_down:
            hit = self.text_hit(pos)
            self.setCursor({"move": Qt.CursorShape.SizeAllCursor, "rotate": Qt.CursorShape.PointingHandCursor,
                            None: self.tool_cursor()}.get(hit, Qt.CursorShape.SizeFDiagCursor if hit in ("corner0", "corner2")
                                                          else Qt.CursorShape.SizeBDiagCursor))
        elif self.stroke and self.shape == "lasso" and self.flash_points is None:
            point = self.clipped_point(self.to_image(pos))
            if point != self.selection_points[-1]:
                self.add_lasso_point(point)
        elif self.stroke and self.shape == "brush":
            point = self.to_image(pos)
            # Clip huge off-canvas coordinates to avoid pathological drawing work.
            x = max(-self.tool.diameter, min(self.image.width() + self.tool.diameter, point.x()))
            y = max(-self.tool.diameter, min(self.image.height() + self.tool.diameter, point.y()))
            box = self.stroke.add((x, y))
            if box:
                self.refresh(box)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self.pan_start is not None:
            self.pan_start = None
            self.setCursor(Qt.CursorShape.OpenHandCursor if self.space_down else self.tool_cursor())
            return
        if self.text_drag is not None and event.button() == Qt.MouseButton.LeftButton:
            drag, self.text_drag = self.text_drag, None
            placement = drag.get("placement")
            if placement is not None and placement != self.text_box.placement:
                self.textTransformed.emit(placement)  # the window writes it, then clears the preview
            else:
                self.clear_text_preview()
            return
        if event.button() != Qt.MouseButton.LeftButton or not self.stroke or self.document is None:
            return
        stroke = self.stroke
        point = self.to_image(event.position())
        if self.shape == "polygon":
            return
        if self.shape == "lasso":
            if self.flash_points is None:
                point = self.clipped_point(point)
                if point != self.selection_points[-1]:
                    self.add_lasso_point(point)
                self.finish_lasso()
            return
        if self.selection_start is not None:
            point = QPointF(max(0, min(self.image.width() - 1, point.x())), max(0, min(self.image.height() - 1, point.y())))
            stroke.mask = region_mask(self.document.image.size, [(self.selection_start.x(), self.selection_start.y()),
                                      (point.x(), point.y())], self.shape, self.tool.expansion, self.invert_selection)
            stroke.apply()
            self.refresh(stroke.box)
        else:
            x = max(-self.tool.diameter, min(self.image.width() + self.tool.diameter, point.x()))
            y = max(-self.tool.diameter, min(self.image.height() + self.tool.diameter, point.y()))
            box = stroke.add((x, y))
            if box:
                self.refresh(box)
            self.last_brush_point = (x, y)
        self.stroke = None
        self.selection_start = None
        self.strokeFinished.emit(stroke)

    def clipped_point(self, point):
        return (max(0, min(self.document.image.width - 1, point.x())),
                max(0, min(self.document.image.height - 1, point.y())))

    def finish_selection(self):
        if not self.stroke or len(set(self.selection_points)) < 3:
            self.cancel_stroke()
            return
        stroke = self.stroke
        stroke.mask = region_mask(self.document.image.size, self.selection_points, self.shape,
                                  self.tool.expansion, self.invert_selection)
        stroke.apply()
        self.refresh(stroke.box)
        self.stroke = None
        self.selection_points = []
        self.strokeFinished.emit(stroke)

    def add_lasso_point(self, point):
        self.selection_points.append(point)
        if self.lasso_loop is None:
            self.lasso_loop = loop_closed_by_last_segment(self.selection_points)

    def finish_lasso(self):
        """Apply to the first closed region the lasso made, after showing it for a moment.

        The end is never joined to the start: a path that never crosses itself
        encloses nothing and changes nothing.
        """
        if not self.stroke:
            return
        loop = self.lasso_loop
        if loop is None:
            self.cancel_stroke()
            self.lassoNotClosed.emit()
            return
        stroke, token = self.stroke, object()
        self.selection_points = []
        self.flash_points, self.flash_token = loop, token
        self.update()
        QTimer.singleShot(LASSO_FLASH_MS, lambda: self.apply_lasso(stroke, loop, token))

    def apply_lasso(self, stroke, loop, token):
        if self.flash_token is not token or self.stroke is not stroke:
            return  # cancelled or replaced meanwhile
        self.flash_points = self.flash_token = None
        self.lasso_loop = None
        stroke.mask = region_mask(self.document.image.size, loop, "lasso", self.tool.expansion, self.invert_selection)
        stroke.apply()
        self.refresh(stroke.box)
        self.stroke = None
        self.strokeFinished.emit(stroke)

    def mouseDoubleClickEvent(self, event):
        if (self.tool.mode == "text" and self.text_box is not None and event.button() == Qt.MouseButton.LeftButton
                and not self.locked and self.text_hit(event.position()) == "move"):
            self.text_drag = None
            self.textEditRequested.emit()
            return
        if self.shape == "polygon" and self.stroke and event.button() == Qt.MouseButton.LeftButton:
            self.selection_points.append(self.clipped_point(self.to_image(event.position())))
            self.finish_selection()
        else:
            super().mouseDoubleClickEvent(event)

    def cancel_stroke(self):
        if self.text_drag is not None:
            self.text_drag = None
            self.clear_text_preview()
            return
        if self.text_box is not None and not self.stroke:
            self.text_box = None
            self.textDeselected.emit()
            self.update()
            return
        if self.stroke:
            self.stroke.cancel()
            self.stroke = None
            self.selection_start = None
            self.selection_points = []
            self.lasso_loop = self.flash_points = self.flash_token = None
            self.ready = self.effect is not None
            self.refresh()
            # The window re-enables controls after an Escape cancellation.
            self.strokeCancelled.emit()

    def wheelEvent(self, event: QWheelEvent):
        self.zoom(math.pow(1.0015, event.angleDelta().y()), event.position())
        event.accept()

    def event(self, event):
        if (event.type() in {QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress} and self.shape == "polygon" and self.stroke
                and event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Backspace}):
            if event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Backspace:
                    if len(self.selection_points) > 1:
                        self.selection_points.pop()
                    self.update()
                else:
                    self.finish_selection()
            event.accept()
            return True
        if event.type() in {QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress} and any(
                matches(event, self.bindings[name]) for name in CANVAS_COMMANDS):
            if event.type() == QEvent.Type.KeyPress:
                self.keyPressEvent(event)
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event: QKeyEvent):
        if matches(event, self.bindings["eraser"]):
            self.eraserRequested.emit()
        elif matches(event, self.bindings["text"]):
            self.textToolRequested.emit()
        elif matches(event, self.bindings["mask"]):
            self.maskToggleRequested.emit()
        elif matches(event, self.bindings["pan"]):
            if not event.isAutoRepeat():
                self.space_down = True
                self.pan_key = event.key()
                self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif matches(event, self.bindings["cancel_stroke"]):
            self.cancel_stroke()
        elif (event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.tool.mode == "text"
              and self.text_box is not None and self.text_drag is None and not self.locked):
            self.textDeleteRequested.emit()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent):
        if event.key() == self.pan_key and not event.isAutoRepeat():
            self.space_down = False
            self.pan_key = None
            self.setCursor(self.tool_cursor())
        else:
            super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self.space_down = False
        self.pan_key = None
        self.setCursor(self.tool_cursor())
        super().focusOutEvent(event)

    def leaveEvent(self, event):
        self.cursor_point = None
        self.update()

    def resizeEvent(self, event):
        if self.fitted:
            self.fit()
        super().resizeEvent(event)
        self.navigator.move(max(8, self.width() - self.navigator.width() - 12), max(8, self.height() - self.navigator.height() - 12))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.filesDropped.emit([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
        event.acceptProposedAction()


class Navigator(QWidget):
    def __init__(self, canvas):
        super().__init__(canvas)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.canvas = canvas
        self.setFixedSize(170, 130)
        self.setToolTip(tr("クリック・ドラッグで表示位置を移動"))
        self.setAccessibleName(tr("ナビゲーター"))

    def image_rect(self):
        if self.canvas.image.isNull():
            return QRectF()
        size = self.canvas.image.size().scaled(QSize(self.width() - 8, self.height() - 8), Qt.AspectRatioMode.KeepAspectRatio)
        return QRectF((self.width() - size.width()) / 2, (self.height() - size.height()) / 2, size.width(), size.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(TOKENS["canvas"]))
        rect = self.image_rect()
        if rect.isEmpty():
            return
        painter.drawImage(rect, self.canvas.image)
        c = self.canvas
        ratio = rect.width() / c.image.width()
        viewport = QRectF(-c.offset.x() / c.scale, -c.offset.y() / c.scale, c.width() / c.scale, c.height() / c.scale)
        viewport = QRectF(rect.left() + viewport.left() * ratio, rect.top() + viewport.top() * ratio,
                          viewport.width() * ratio, viewport.height() * ratio).intersected(rect)
        painter.setPen(QPen(QColor(TOKENS["accent"]), 2))
        painter.drawRect(viewport)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.center_on(event.position())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.center_on(event.position())

    def center_on(self, point):
        rect, c = self.image_rect(), self.canvas
        if rect.isEmpty():
            return
        x = max(0, min(c.image.width(), (point.x() - rect.left()) * c.image.width() / rect.width()))
        y = max(0, min(c.image.height(), (point.y() - rect.top()) * c.image.height() / rect.height()))
        c.offset = QPointF(c.width() / 2 - x * c.scale, c.height() / 2 - y * c.scale)
        c.fitted = False
        c.update()

