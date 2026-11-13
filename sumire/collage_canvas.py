"""The interactive collage canvas: shows the collage, crops images in place and,
in the free layout, moves and resizes them.

Coordinates are output pixels of the collage. Double-clicking an image shows its
crop frame over the whole image, with the cut-off parts faded; clicking outside
the frame (or Esc / Enter) finishes cropping. Image files are never changed.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from .canvas import qimage
from .collage import CollageSpec, Piece, grid_pieces
from .imaging import MAX_DIMENSION, MAX_PIXELS
from .theme import TOKENS

PREVIEW_SIDE = 1600
MARGIN = 14
GRIP = 9
MIN_SHOWN = 8
CURSORS = {"tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
           "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
           "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
           "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
           "move": Qt.CursorShape.SizeAllCursor}


def _checker():
    tile = QPixmap(16, 16)
    tile.fill(QColor("#cfd3d8"))
    painter = QPainter(tile)
    painter.fillRect(0, 0, 8, 8, QColor("#f2f3f5"))
    painter.fillRect(8, 8, 8, 8, QColor("#f2f3f5"))
    painter.end()
    return tile


class CollageCanvas(QWidget):
    changed = Signal()             # a crop or a placement changed
    selectionChanged = Signal(int)
    croppingChanged = Signal(bool)

    def __init__(self, images, parent=None):
        super().__init__(parent)
        self.sources = list(images)
        self.previews, self.preview_scales = [], []
        for image in self.sources:
            small = image.copy()
            small.thumbnail((PREVIEW_SIDE, PREVIEW_SIDE))
            self.previews.append(QPixmap.fromImage(qimage(small)))
            self.preview_scales.append(small.width / image.width)
        self.crops = [(0, 0, image.width, image.height) for image in self.sources]
        self.free = False
        self.spec = CollageSpec(1, max(1, len(images)))
        self.pieces: list[Piece] = []      # free layout, by source index
        self.order = list(range(len(images)))
        self.canvas_size = (1, 1)
        self.background = "#ffffff"
        self.selected = None
        self.cropping = None               # index being cropped
        self.live_crop = None
        self.anchor = None                 # (x, y, scale) of the whole image while cropping
        self.drag = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(380, 380)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.checker = _checker()

    # --- layout ----------------------------------------------------------------
    def crop_sizes(self):
        return [(crop[2], crop[3]) for crop in self.crops]

    def set_grid(self, spec, background):
        """Lay the images out like ``render_collage``; raises ImageProblem for an impossible layout."""
        self.finish_crop()
        _, size = grid_pieces(self.crop_sizes(), spec)
        self.spec, self.free, self.background, self.canvas_size = spec, False, background, size
        self.update()

    def set_free(self, size, background, *, rearrange=False):
        """Switch to the free layout and return the canvas size.

        The first time (or on ``rearrange``) the images start where the grid
        put them, whole, on a canvas of the grid's size unless ``size`` is given.
        """
        self.finish_crop()
        if rearrange or not self.pieces:
            spec = CollageSpec(self.spec.rows, self.spec.columns, "contain", self.spec.gap, background)
            placed, grid_size = grid_pieces(self.crop_sizes(), spec)
            self.pieces = [Piece(crop, x, y, scale) for crop, (x, y, scale, _) in zip(self.crops, placed)]
            self.order = list(range(len(self.sources)))
            if rearrange or size is None:
                size = grid_size
        self.free, self.background = True, background
        self.canvas_size = size or self.canvas_size
        self.update()
        return self.canvas_size

    def placements(self):
        """[(index, x, y, scale, clip)] back to front, using the committed crops."""
        if self.free:
            return [(index, self.pieces[index].x, self.pieces[index].y, self.pieces[index].scale, None)
                    for index in self.order]
        placed, _ = grid_pieces(self.crop_sizes(), self.spec)
        return [(index, x, y, scale, cell) for index, (x, y, scale, cell) in enumerate(placed)]

    def placement(self, index):
        return next(item for item in self.placements() if item[0] == index)

    def free_pieces(self):
        return tuple((index, self.pieces[index]) for index in self.order)

    # --- view transform ----------------------------------------------------------
    def view_scale(self):
        width, height = self.canvas_size
        return max(1e-6, min((self.width() - 2 * MARGIN) / width, (self.height() - 2 * MARGIN) / height))

    def origin(self):
        scale = self.view_scale()
        return ((self.width() - self.canvas_size[0] * scale) / 2, (self.height() - self.canvas_size[1] * scale) / 2)

    def to_view(self, x, y, width=0, height=0):
        scale, (ox, oy) = self.view_scale(), self.origin()
        return QRectF(ox + x * scale, oy + y * scale, width * scale, height * scale)

    def to_canvas(self, point):
        scale, (ox, oy) = self.view_scale(), self.origin()
        return (point.x() - ox) / scale, (point.y() - oy) / scale

    # --- hit tests --------------------------------------------------------------
    def shown_rect(self, index, x, y, scale, clip=None):
        crop = self.crops[index]
        rect = QRectF(x, y, crop[2] * scale, crop[3] * scale)
        return rect.intersected(QRectF(*clip)) if clip else rect

    def item_at(self, point):
        x, y = self.to_canvas(point)
        for index, px, py, scale, clip in reversed(self.placements()):
            if self.shown_rect(index, px, py, scale, clip).contains(QPointF(x, y)):
                return index
        return None

    def frame_rect(self):
        """The crop frame in view coordinates while cropping."""
        ax, ay, scale = self.anchor
        x, y, width, height = self.live_crop
        return self.to_view(ax + x * scale, ay + y * scale, width * scale, height * scale)

    def selected_rect(self):
        if not self.free or self.selected is None:
            return None
        piece = self.pieces[self.selected]
        width, height = piece.shown_size()
        return self.to_view(piece.x, piece.y, width, height)

    @staticmethod
    def edge_hit(rect, point, *, edges=True):
        px, py = point.x(), point.y()
        near_x = "l" if abs(px - rect.left()) <= GRIP else "r" if abs(px - rect.right()) <= GRIP else ""
        near_y = "t" if abs(py - rect.top()) <= GRIP else "b" if abs(py - rect.bottom()) <= GRIP else ""
        inside_x = rect.left() - GRIP <= px <= rect.right() + GRIP
        inside_y = rect.top() - GRIP <= py <= rect.bottom() + GRIP
        if near_x and near_y:
            return near_y + near_x
        if edges and near_x and inside_y:
            return near_x
        if edges and near_y and inside_x:
            return near_y
        if rect.contains(point):
            return "move"
        return None

    # --- selection and cropping --------------------------------------------------
    def select(self, index):
        if index == self.selected:
            return
        self.selected = index
        if self.free and index is not None and index in self.order:
            self.order.remove(index)
            self.order.append(index)  # the chosen image comes to the front
        self.update()
        if index is not None:
            self.selectionChanged.emit(index)

    def start_crop(self, index):
        if index is None or not 0 <= index < len(self.sources):
            return
        self.finish_crop()
        self.select(index)
        _, x, y, scale, _ = self.placement(index)
        crop = self.crops[index]
        self.cropping, self.live_crop = index, crop
        self.anchor = (x - crop[0] * scale, y - crop[1] * scale, scale)
        self.setFocus()
        self.update()
        self.croppingChanged.emit(True)

    def finish_crop(self):
        if self.cropping is None:
            return
        index, crop = self.cropping, self.live_crop
        self.cropping = self.live_crop = self.anchor = None
        self.drag = None
        changed = crop != self.crops[index]
        self.recrop(index, crop)
        self.update()
        self.croppingChanged.emit(False)
        if changed:
            self.changed.emit()

    def reset_crop(self, index):
        if index is None or not 0 <= index < len(self.sources):
            return
        self.finish_crop()
        source = self.sources[index]
        if self.crops[index] == (0, 0, source.width, source.height):
            return
        self.recrop(index, (0, 0, source.width, source.height))
        self.update()
        self.changed.emit()

    def recrop(self, index, crop):
        """Use ``crop`` of image ``index``; a free piece keeps the whole image where it was."""
        if self.pieces:
            piece, old = self.pieces[index], self.crops[index]
            self.pieces[index] = Piece(crop, piece.x + (crop[0] - old[0]) * piece.scale,
                                       piece.y + (crop[1] - old[1]) * piece.scale, piece.scale)
        self.crops[index] = crop

    # --- mouse -------------------------------------------------------------------
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.item_at(event.position())
            if index is not None and index != self.cropping:
                self.start_crop(index)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position()
        if self.cropping is not None:
            part = self.edge_hit(self.frame_rect(), point)
            if part:
                self.drag = ("crop", part, point, self.live_crop)
            else:
                self.finish_crop()
            return
        rect = self.selected_rect()
        corner = self.edge_hit(rect, point, edges=False) if rect is not None else None
        if corner and corner != "move":
            self.drag = ("resize", corner, point, self.pieces[self.selected])
            return
        index = self.item_at(point)
        self.select(index)
        if self.free and index is not None:
            self.drag = ("move", None, point, self.pieces[index])

    def mouseMoveEvent(self, event):
        point = event.position()
        if self.drag is None or not event.buttons() & Qt.MouseButton.LeftButton:
            self.setCursor(self.hover_cursor(point))
            return
        kind, part, start, before = self.drag
        scale = self.view_scale()
        dx, dy = (point.x() - start.x()) / scale, (point.y() - start.y()) / scale
        if kind == "crop":
            self.live_crop = self.dragged_crop(part, before, dx / self.anchor[2], dy / self.anchor[2])
        elif kind == "move":
            self.pieces[self.selected] = Piece(before.crop, before.x + dx, before.y + dy, before.scale)
        else:
            self.pieces[self.selected] = self.resized(part, before, dx, dy)
        self.update()

    def mouseReleaseEvent(self, event):
        if self.drag is not None and self.drag[0] in ("move", "resize"):
            self.changed.emit()
        self.drag = None

    def hover_cursor(self, point):
        if self.cropping is not None:
            return CURSORS.get(self.edge_hit(self.frame_rect(), point), Qt.CursorShape.ArrowCursor)
        rect = self.selected_rect()
        corner = self.edge_hit(rect, point, edges=False) if rect is not None else None
        if corner and corner != "move":
            return CURSORS[corner]
        if self.free and self.item_at(point) is not None:
            return Qt.CursorShape.SizeAllCursor
        return Qt.CursorShape.ArrowCursor

    def keyPressEvent(self, event):
        if self.cropping is not None and event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.finish_crop()
            return
        super().keyPressEvent(event)

    def dragged_crop(self, part, before, dx, dy):
        x, y, width, height = before
        limit_w, limit_h = self.sources[self.cropping].size
        dx, dy = round(dx), round(dy)
        if part == "move":
            return (max(0, min(limit_w - width, x + dx)), max(0, min(limit_h - height, y + dy)), width, height)
        left, top, right, bottom = x, y, x + width, y + height
        if "l" in part:
            left = max(0, min(right - 1, left + dx))
        if "r" in part:
            right = min(limit_w, max(left + 1, right + dx))
        if "t" in part:
            top = max(0, min(bottom - 1, top + dy))
        if "b" in part:
            bottom = min(limit_h, max(top + 1, bottom + dy))
        return (left, top, right - left, bottom - top)

    def resized(self, corner, before, dx, dy):
        """Resize from a corner, keeping the proportions and the opposite corner in place."""
        width, height = before.crop[2] * before.scale, before.crop[3] * before.scale
        grow_w = width + (dx if "r" in corner else -dx)
        grow_h = height + (dy if "b" in corner else -dy)
        scale = max(grow_w / before.crop[2], grow_h / before.crop[3])
        largest = min(MAX_DIMENSION / max(before.crop[2], before.crop[3]),
                      (MAX_PIXELS / (before.crop[2] * before.crop[3])) ** 0.5)
        scale = max(MIN_SHOWN / min(before.crop[2], before.crop[3]), min(largest, scale))
        new_w, new_h = before.crop[2] * scale, before.crop[3] * scale
        x = before.x + width - new_w if "l" in corner else before.x
        y = before.y + height - new_h if "t" in corner else before.y
        return Piece(before.crop, x, y, scale)

    # --- painting --------------------------------------------------------------
    def draw_image(self, painter, index, full_x, full_y, scale, part=None):
        """Draw ``part`` (a crop, default all) of source ``index`` whose top-left is at full_x, full_y."""
        source = self.sources[index]
        x, y, width, height = part or (0, 0, source.width, source.height)
        ratio = self.preview_scales[index]
        target = self.to_view(full_x + x * scale, full_y + y * scale, width * scale, height * scale)
        painter.drawPixmap(target, self.previews[index], QRectF(x * ratio, y * ratio, width * ratio, height * ratio))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(TOKENS["field"]))
        page = self.to_view(0, 0, *self.canvas_size)
        if self.background:
            painter.fillRect(page, QColor(self.background))
        else:
            painter.fillRect(page, QBrush(self.checker))
        for index, x, y, scale, clip in self.placements():
            if index == self.cropping:
                continue
            crop = self.crops[index]
            painter.save()
            if clip is None:
                # Parts outside the canvas stay visible, faded: they won't be in the collage.
                painter.setOpacity(0.25)
                self.draw_image(painter, index, x - crop[0] * scale, y - crop[1] * scale, scale, crop)
                painter.setOpacity(1.0)
            area = page if clip is None else self.to_view(*clip).intersected(page)
            painter.setClipRect(area)
            self.draw_image(painter, index, x - crop[0] * scale, y - crop[1] * scale, scale, crop)
            painter.restore()
        rect = self.selected_rect()
        if rect is not None and self.cropping is None:
            painter.setPen(QPen(QColor(TOKENS["accent"]), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            painter.setBrush(QColor(TOKENS["accent"]))
            for corner in (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()):
                painter.drawRect(QRectF(corner.x() - 4, corner.y() - 4, 8, 8))
        if self.cropping is not None:
            self.paint_crop(painter)
        painter.end()

    def paint_crop(self, painter):
        index = self.cropping
        ax, ay, scale = self.anchor
        painter.setOpacity(0.35)  # the parts that will be cut off
        self.draw_image(painter, index, ax, ay, scale)
        painter.setOpacity(1.0)
        self.draw_image(painter, index, ax, ay, scale, self.live_crop)
        frame = self.frame_rect()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 90), 1))
        for third in (1, 2):
            x = frame.left() + frame.width() * third / 3
            y = frame.top() + frame.height() * third / 3
            painter.drawLine(QPointF(x, frame.top()), QPointF(x, frame.bottom()))
            painter.drawLine(QPointF(frame.left(), y), QPointF(frame.right(), y))
        painter.setPen(QPen(QColor(TOKENS["accent"]), 1.5))
        painter.drawRect(frame)
        painter.setPen(QPen(QColor("#ffffff"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap))
        arm = min(16.0, frame.width() / 2, frame.height() / 2)
        for cx, cy, hx, hy in ((frame.left(), frame.top(), 1, 1), (frame.right(), frame.top(), -1, 1),
                               (frame.left(), frame.bottom(), 1, -1), (frame.right(), frame.bottom(), -1, -1)):
            cx, cy = cx + hx * 2, cy + hy * 2
            painter.drawLine(QPointF(cx, cy), QPointF(cx + hx * arm, cy))
            painter.drawLine(QPointF(cx, cy), QPointF(cx, cy + hy * arm))
