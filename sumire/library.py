"""Lazy visible-item thumbnails, one decoding worker and bounded in-memory cache."""
from __future__ import annotations
from .i18n import tr, tr_state

import re
import json
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import (QAbstractListModel, QEvent, QItemSelectionModel, QModelIndex, QPoint, QRectF, QSize, Qt, QThreadPool,
                            QSortFilterProxyModel, QMimeData, QTimer, Signal)
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QIcon, QPainter, QPen, QPixmap, QDrag
from PySide6.QtWidgets import QApplication, QListView, QAbstractItemView, QStyle, QStyledItemDelegate

from .canvas import qimage
from .export import check_cancel
from .icons import grab_hand
from .imaging import SUPPORTED, load_thumbnail
from .labels import REVIEW_LABELS
from .theme import TOKENS
from .workers import Job

STATE_ROLE = Qt.ItemDataRole.UserRole + 1
LABEL_ROLE = Qt.ItemDataRole.UserRole + 2
NOTE_ROLE = Qt.ItemDataRole.UserRole + 3
TAGS_ROLE = Qt.ItemDataRole.UserRole + 4
LIST_ICON = QSize(64, 48)
LABEL_TONES = {"accepted": ("ok", "accent_soft"), "pending": ("warn", "warn_soft"), "rejected": ("danger", "danger_soft")}


def filename_key(path: Path):
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold()) for part in re.split(r"(\d+)", path.name))


def state_summary(state: str | None) -> tuple[str, str]:
    """Short list text and colour tone for a detailed save state."""
    state = state or "未編集"
    first = state.split(" · ")[0]
    if "失敗" in state or "エラー" in state:
        return first, "danger"
    if "保存済み" in state or "書出済み" in state:
        return ("保存済み · 未編集" if first == "未編集" else first), "ok"
    if any(word in state for word in ("保存待ち", "未保存", "変更", "再検証")):
        return first, "warn"
    return first, "neutral"


def scan_paths(inputs: list[str]) -> list[Path]:
    paths: set[Path] = set()
    for raw in inputs:
        path = Path(raw).resolve()
        if path.is_dir():
            paths.update(p.resolve() for p in path.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED)
        elif path.is_file():
            paths.add(path)
    return sorted(paths, key=lambda p: (filename_key(p), str(p)))


class LibraryModel(QAbstractListModel):
    renameRequested = Signal(str, str)
    cacheChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.paths: list[Path] = []
        self.rows: dict[Path, int] = {}
        self.states: dict[Path, str] = {}
        self.labels: dict[Path, str] = {}
        self.notes: dict[Path, str] = {}
        self.tags: dict[Path, tuple[str, ...]] = {}
        self.grid_size = 0
        self.cache: OrderedDict[Path, QIcon] = OrderedDict()
        self.pending: set[Path] = set()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.jobs: set[Job] = set()
        self.generation = 0
        self.active = True
        placeholder = QPixmap(88, 64)
        placeholder.fill(QColor(TOKENS["raised"]))
        self.placeholder = QIcon(placeholder)

    def set_paths(self, paths: list[Path], *, preserve_cache=False, mapping=None):
        self.generation += 1
        for job in self.jobs:
            job.cancel.set()
        self.beginResetModel()
        self.paths = paths
        self.rows = {path: row for row, path in enumerate(paths)}
        self.states.clear()
        self.labels.clear()
        self.notes.clear()
        self.tags.clear()
        if preserve_cache:
            mapping = mapping or {}
            self.cache = OrderedDict((mapping.get(path, path), icon) for path, icon in self.cache.items()
                                     if mapping.get(path, path) in self.rows)
        else:
            self.cache.clear()
        self.pending.clear()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.paths)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.paths):
            return None
        path = self.paths[index.row()]
        if role == Qt.ItemDataRole.EditRole:
            return path.stem
        label = REVIEW_LABELS.get(self.labels.get(path), "")
        if role == Qt.ItemDataRole.DisplayRole:
            state = tr_state(self.states.get(path, "未編集").split(" · ")[0])
            return f"{path.name}\n{state}" + (f"\n{label}" if label else "")
        if role == Qt.ItemDataRole.ToolTipRole:
            state = tr_state(self.states.get(path, "未編集"))
            tags = " ".join("#" + tag for tag in self.tags.get(path, ()))
            return f"{path}\n{label or tr('ラベルなし')} · {state}" + (f"\n{tags}" if tags else "") + f"\n{self.notes.get(path, '')}"
        if role == Qt.ItemDataRole.UserRole:
            return str(path)
        if role == STATE_ROLE:
            return self.states.get(path, "未編集")
        if role == LABEL_ROLE:
            return self.labels.get(path)
        if role == NOTE_ROLE:
            return bool(self.notes.get(path))
        if role == TAGS_ROLE:
            return self.tags.get(path, ())
        if role == Qt.ItemDataRole.AccessibleTextRole:
            state = tr_state(self.states.get(path, "未編集"))
            return tr("{name}、{state}").format(name=path.name, state=state) + (tr("、{label}").format(label=label) if label else "")
        if role == Qt.ItemDataRole.SizeHintRole:
            return QSize(self.grid_size + 16, self.grid_size + 58) if self.grid_size else QSize(200, LIST_ICON.height() + 16)
        if role == Qt.ItemDataRole.DecorationRole:
            if path in self.cache:
                self.cache.move_to_end(path)
                return self.cache[path]
            if self.active and path not in self.pending and len(self.pending) < 32:
                self._thumbnail(path, index.row())
            return self.placeholder
        return None

    def state(self, path: Path, text: str):
        self.states[path] = text
        row = self.rows.get(path)
        if row is not None:
            index = self.index(row)
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])

    def set_label(self, path: Path, label: str | None):
        if label is None:
            self.labels.pop(path, None)
        else:
            self.labels[path] = label
        row = self.rows.get(path)
        if row is not None:
            index = self.index(row)
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole])

    def set_tags(self, path: Path, tags):
        if tags:
            self.tags[path] = tuple(tags)
        else:
            self.tags.pop(path, None)
        row = self.rows.get(path)
        if row is not None:
            index = self.index(row)
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole])

    def known_tags(self):
        """Every tag used in this list, in name order."""
        found = {tag.casefold(): tag for tags in self.tags.values() for tag in tags}
        return sorted(found.values(), key=str.casefold)

    def set_note(self, path: Path, text: str):
        self.notes[path] = text
        row = self.rows.get(path)
        if row is not None:
            index = self.index(row)
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.ToolTipRole])

    def _thumbnail(self, path: Path, row: int):
        self.pending.add(path)
        generation = self.generation

        def decode(cancel):
            check_cancel(cancel)
            image = load_thumbnail(path)
            check_cancel(cancel)
            return image

        job = Job(decode)
        self.jobs.add(job)

        def completed(image):
            if generation != self.generation:
                return
            self.cache[path] = QIcon(QPixmap.fromImage(qimage(image)))
            while len(self.cache) > 160:
                self.cache.popitem(last=False)
            self.pending.discard(path)
            index = self.index(row)
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DecorationRole])
            self.cacheChanged.emit()

        def failed(_message):
            if generation == self.generation:
                self.cache[path] = self.placeholder
                self.pending.discard(path)

        job.signals.done.connect(completed)
        job.signals.failed.connect(failed)
        job.signals.finished.connect(lambda: self.jobs.discard(job))
        self.pool.start(job)

    @property
    def cache_memory(self):
        return sum(max((size.width() * size.height() * 4 for size in icon.availableSizes()), default=0)
                   for icon in self.cache.values())

    def suspend(self):
        self.active = False
        self.generation += 1
        for job in self.jobs:
            job.cancel.set()
        self.pending.clear()

    def resume(self):
        self.active = True
        if self.paths:
            self.dataChanged.emit(self.index(0), self.index(len(self.paths) - 1), [Qt.ItemDataRole.DecorationRole])

    def flags(self, index):
        return super().flags(index) | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled | Qt.ItemFlag.ItemIsEditable

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role == Qt.ItemDataRole.EditRole and index.isValid() and isinstance(value, str):
            self.renameRequested.emit(str(self.paths[index.row()]), value)
            return True
        return False


class LibraryFilter(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.label = "all"
        self.tag = None  # show only images with this tag (compared ignoring case)
        self.text = ""
        self.allowed = None

    def filterAcceptsRow(self, row, parent):
        model = self.sourceModel()
        path = model.paths[row]
        tags = model.tags.get(path, ())
        text = self.text.casefold()
        return ((self.label == "all" or model.labels.get(path, "unlabelled") == self.label)
                and (self.tag is None or self.tag.casefold() in {tag.casefold() for tag in tags})
                and (not text or text in path.name.casefold() or text in model.notes.get(path, "").casefold()
                     or any(text in tag.casefold() for tag in tags))
                and (self.allowed is None or path in self.allowed))

    @property
    def active(self):
        return self.label != "all" or self.tag is not None or bool(self.text)

    def refresh(self):
        self.invalidate()


class LibraryView(QListView):
    reordered = Signal(list, str)
    filesDropped = Signal(list)
    MIME = "application/x-sumire-paths"
    # Dragging near (or past) the top or bottom scrolls: faster the further in, up to MAX_STEP px a tick.
    EDGE = 56
    MAX_STEP = 48
    TICK_MS = 16

    def __init__(self):
        super().__init__()
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.drop_line = None
        self.enable_dragging()
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        # Qt's own auto-scroll only works inside a thin margin and starts slowly; edge_scroll replaces it.
        self.setAutoScroll(False)
        self.dragging = False
        self.scroll_timer = QTimer(self)
        self.scroll_timer.setInterval(self.TICK_MS)
        self.scroll_timer.timeout.connect(self.edge_scroll)

    def mousePressEvent(self, event):
        # Ctrl+click on a selected image takes just that one out of a multiple selection; Qt would
        # make it current, and opening it would select it alone.
        index = self.indexAt(event.position().toPoint())
        if (event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ControlModifier
                and index.isValid() and self.selectionModel().isSelected(index)
                and len(self.selectionModel().selectedIndexes()) > 1):
            self.selectionModel().select(index, QItemSelectionModel.SelectionFlag.Deselect)
            event.accept()
            return
        super().mousePressEvent(event)

    def edge_step(self, y: int) -> int:
        """Pixels to scroll for the pointer at viewport height ``y`` (negative is up); 0 away from the edges."""
        height = self.viewport().height()
        depth = self.EDGE - y if y < self.EDGE else y - (height - self.EDGE) if y > height - self.EDGE else 0
        if depth <= 0:
            return 0
        step = min(self.MAX_STEP, 4 + depth * self.MAX_STEP // (self.EDGE * 2))
        return -step if y < self.EDGE else step

    def edge_scroll(self):
        """While dragging: scroll when the pointer is near the top or bottom, or above or below the list."""
        position = QCursor.pos()
        local = self.viewport().mapFromGlobal(position)
        under = QApplication.widgetAt(position)
        if under is not None and under is not self.viewport() and not self.isAncestorOf(under) and under.acceptDrops():
            return  # over another drop target (a folder to move into): leave the list where it is
        if not -self.EDGE * 2 <= local.x() <= self.viewport().width() + self.EDGE * 2:
            return  # well to the side: the pointer is somewhere else
        step = self.edge_step(local.y())
        if step:
            bar = self.verticalScrollBar()
            bar.setValue(bar.value() + step)

    def eventFilter(self, watched, event):
        # The wheel scrolls the list while an image is being dragged.
        if self.dragging and event.type() == QEvent.Type.Wheel:
            bar = self.verticalScrollBar()
            bar.setValue(bar.value() - event.angleDelta().y())
            return True
        return super().eventFilter(watched, event)

    def enable_dragging(self):
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)

    def setMovement(self, movement):
        # QListView turns drag and drop off for Static movement; reordering is
        # handled here instead of by free item placement, so keep it on.
        super().setMovement(movement)
        self.enable_dragging()

    def insertion_point(self, position):
        """(path to insert before or "" for the end, y/x of the indicator line)."""
        index = self.indexAt(position)
        if not index.isValid():
            rows = self.model().rowCount() if self.model() else 0
            last = self.visualRect(self.model().index(rows - 1, 0)) if rows else None
            return "", (last.bottom() + 1 if last is not None else 0)
        rect = self.visualRect(index)
        grid = self.viewMode() == QListView.ViewMode.IconMode
        after = position.x() > rect.center().x() if grid else position.y() > rect.center().y()
        if after:
            following = index.sibling(index.row() + 1, 0)
            return (following.data(Qt.ItemDataRole.UserRole) or "" if following.isValid() else ""), (rect.right() if grid else rect.bottom()) + 1
        return index.data(Qt.ItemDataRole.UserRole) or "", rect.left() if grid else rect.top()

    def startDrag(self, actions):
        paths = [index.data(Qt.ItemDataRole.UserRole) for index in self.selectedIndexes()]
        mime = QMimeData()
        mime.setData(self.MIME, json.dumps(paths).encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        # The hand follows the pointer as the drag picture; a blank cursor keeps
        # the default arrow-and-box from being drawn over it. Where nothing can be
        # dropped, the platform's "not allowed" sign still appears.
        hand = grab_hand(self.devicePixelRatioF())
        drag.setPixmap(hand)
        drag.setHotSpot(QPoint(round(hand.width() / hand.devicePixelRatio() / 2),
                               round(hand.height() / hand.devicePixelRatio() / 2)))
        blank = QPixmap(1, 1)
        blank.fill(Qt.GlobalColor.transparent)
        drag.setDragCursor(blank, Qt.DropAction.MoveAction)
        self.dragging = True
        application = QApplication.instance()
        application.installEventFilter(self)
        self.scroll_timer.start()
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self.scroll_timer.stop()
            application.removeEventFilter(self)
            self.dragging = False

    def dragEnterEvent(self, event):
        if event.source() is self and event.mimeData().hasFormat(self.MIME):
            event.acceptProposedAction()
        elif event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        internal = event.source() is self and event.mimeData().hasFormat(self.MIME)
        super().dragMoveEvent(event)
        self.dragEnterEvent(event)
        line = None
        if internal:
            position = event.position().toPoint()
            _, offset = self.insertion_point(position)
            index = self.indexAt(position)
            rect = self.visualRect(index) if index.isValid() else None
            line = (self.viewMode() == QListView.ViewMode.IconMode, offset, rect)
        if line != self.drop_line:
            self.drop_line = line
            self.viewport().update()

    def dragLeaveEvent(self, event):
        super().dragLeaveEvent(event)
        self.drop_line = None
        self.viewport().update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.drop_line is None:
            return
        grid, offset, rect = self.drop_line
        painter = QPainter(self.viewport())
        painter.setPen(QPen(QColor(TOKENS["accent"]), 2))
        if grid and rect is not None:
            painter.drawLine(offset, rect.top() + 4, offset, rect.bottom() - 4)
        elif not grid:
            painter.drawLine(4, offset, self.viewport().width() - 4, offset)
        painter.end()

    def dropEvent(self, event):
        self.drop_line = None
        self.viewport().update()
        if event.source() is self and event.mimeData().hasFormat(self.MIME):
            paths = json.loads(bytes(event.mimeData().data(self.MIME)))
            before, _ = self.insertion_point(event.position().toPoint())
            self.reordered.emit(paths, before)
            event.acceptProposedAction()
        elif event.mimeData().hasUrls():
            self.filesDropped.emit([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
            event.acceptProposedAction()
        else:
            event.ignore()


# Grid thumbnails smaller than this drop the name and state text.
COMPACT_GRID = 80


class LibraryDelegate(QStyledItemDelegate):
    """Thumbnail rows (list) and tiles (grid) with a save-state dot and label pill."""

    def __init__(self, view: QListView):
        super().__init__(view)
        self.view = view
        self.grid = False

    def sizeHint(self, option, index):
        hint = index.data(Qt.ItemDataRole.SizeHintRole)
        return hint if isinstance(hint, QSize) else super().sizeHint(option, index)

    def updateEditorGeometry(self, editor, option, index):
        # Leave the thumbnail and save-state line visible while editing the name.
        rect = option.rect.adjusted(8, 4, -8, -4)
        if self.grid:
            rect.setTop(rect.top() + self.view.iconSize().height() + 8)
        else:
            rect.setLeft(rect.left() + self.view.iconSize().width() + 12)
        rect.setHeight(min(28, rect.height()))
        editor.setGeometry(rect)

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(1, 2, -1, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(TOKENS["accent_soft"]))
            painter.drawRoundedRect(QRectF(rect), 6, 6)
            if not self.grid:
                painter.setBrush(QColor(TOKENS["accent"]))
                painter.drawRoundedRect(QRectF(rect.left(), rect.top() + 8, 3, rect.height() - 16), 1.5, 1.5)
        elif hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(TOKENS["raised"]))
            painter.drawRoundedRect(QRectF(rect), 6, 6)
        name = (index.data(Qt.ItemDataRole.DisplayRole) or "").split("\n")[0]  # the file name (also for an image in a ZIP)
        state, tone = state_summary(index.data(STATE_ROLE))
        state = tr_state(state)
        label = index.data(LABEL_ROLE)
        note = index.data(NOTE_ROLE)
        tags = index.data(TAGS_ROLE) or ()
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        size = self.view.iconSize()
        if self.grid and size.width() < COMPACT_GRID:
            # Small tiles: the thumbnail with a state dot and a label dot; the name is in the tooltip.
            thumb = QRectF(rect.left() + (rect.width() - size.width()) / 2, rect.top() + (rect.height() - size.height()) / 2,
                           size.width(), size.height())
            self._thumbnail(painter, thumb, icon)
            painter.setPen(QPen(QColor(TOKENS["canvas"]), 1.5))
            painter.setBrush(QColor(TOKENS[tone]))
            painter.drawEllipse(QRectF(thumb.left() + 3, thumb.bottom() - 11, 8, 8))
            if label in REVIEW_LABELS:
                painter.setBrush(QColor(TOKENS[LABEL_TONES[label][0]]))
                painter.drawEllipse(QRectF(thumb.right() - 12, thumb.top() + 3, 9, 9))
            painter.restore()
            return
        if self.grid:
            thumb = QRectF(rect.left() + (rect.width() - size.width()) / 2, rect.top() + 6, size.width(), size.height())
            text_left, text_right = rect.left() + 8, rect.right() - 8
            name_top = thumb.bottom() + 6
        else:
            thumb = QRectF(rect.left() + 10, rect.top() + (rect.height() - size.height()) / 2, size.width(), size.height())
            text_left, text_right = thumb.right() + 10, rect.right() - 8
            name_top = rect.top() + rect.height() / 2 - 19
        self._thumbnail(painter, thumb, icon)
        font = QFont(option.font)
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.DemiBold if selected else QFont.Weight.Normal)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        width = int(text_right - text_left)
        note_width = 14 if note else 0
        painter.setPen(QColor(TOKENS["text_strong"] if selected else TOKENS["text"]))
        painter.drawText(QRectF(text_left, name_top, width - note_width, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         metrics.elidedText(name, Qt.TextElideMode.ElideMiddle, width - note_width))
        if note:
            painter.setPen(QColor(TOKENS["text_muted"]))
            painter.drawText(QRectF(text_right - 12, name_top, 12, 18), Qt.AlignmentFlag.AlignCenter, "✎")
        small = QFont(option.font)
        small.setPixelSize(11)
        painter.setFont(small)
        small_metrics = QFontMetrics(small)
        line_top = name_top + 20
        pill_width = 0
        if label in REVIEW_LABELS:
            text = REVIEW_LABELS[label]
            pill_width = small_metrics.horizontalAdvance(text) + 14
            foreground, background = LABEL_TONES[label]
            pill = QRectF(text_right - pill_width, line_top, pill_width, 17)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(TOKENS[background]))
            painter.drawRoundedRect(pill, 8.5, 8.5)
            painter.setPen(QColor(TOKENS[foreground]))
            painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(TOKENS[tone]))
        painter.drawEllipse(QRectF(text_left, line_top + 5.5, 6, 6))
        painter.setPen(QColor(TOKENS["text_muted"]))
        available = int(width - pill_width - 16)
        line = state + ("  " + " ".join("#" + tag for tag in tags) if tags else "")
        painter.drawText(QRectF(text_left + 11, line_top, max(0, available), 17), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         small_metrics.elidedText(line, Qt.TextElideMode.ElideRight, max(0, available)))
        painter.restore()

    @staticmethod
    def _thumbnail(painter: QPainter, area: QRectF, icon):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(TOKENS["field"]))
        painter.drawRoundedRect(area, 4, 4)
        if not isinstance(icon, QIcon) or icon.isNull():
            return
        ratio = painter.device().devicePixelRatioF() if painter.device() else 1.0
        pixmap = icon.pixmap(QSize(int(area.width()), int(area.height())), ratio)
        if pixmap.isNull():
            return
        logical = pixmap.deviceIndependentSize()
        target = QRectF(area.left() + (area.width() - logical.width()) / 2, area.top() + (area.height() - logical.height()) / 2,
                        logical.width(), logical.height())
        painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
