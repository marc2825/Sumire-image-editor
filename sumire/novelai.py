"""Prepare a clean image for NovelAI's browser import, without an API account."""
from __future__ import annotations
from .i18n import tr

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image
from PySide6.QtCore import QMimeData, QPointF, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QDrag, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout

from .export import check_cancel, save_image
from .theme import TOKENS
from .imaging import ImageProblem
from .canvas import qimage
from .stealth import remove_stealth

NOVELAI_URL = "https://novelai.net/image"


@dataclass
class PreparedImage:
    directory: TemporaryDirectory
    path: Path
    metadata: bool = False  # the original's generation information (metadata) was attached

    def cleanup(self):
        self.directory.cleanup()


def transform_image(pixels, crop=None, max_size=None):
    if crop is not None:
        x, y, width, height = crop
        if x < 0 or y < 0 or width < 1 or height < 1 or x + width > pixels.width or y + height > pixels.height:
            raise ImageProblem(tr("切り抜き範囲が画像の外にあります。"))
        pixels = pixels.crop((x, y, x + width, y + height))
    else:
        pixels = pixels.copy()
    if max_size:
        if min(max_size) < 1:
            raise ImageProblem(tr("出力サイズは1px以上にしてください。"))
        pixels.thumbnail(max_size, Image.Resampling.LANCZOS)
    return pixels


def with_metadata(pixels, source: Path, cancel=None):
    """PNG bytes of ``pixels`` carrying the generation information of ``source`` (a PNG), or None.

    NovelAI reads it back (text chunks and Stealth PNGInfo). Pictures inside the metadata
    (thumbnails) are never copied. When the hidden pixel data no longer fits (a smaller,
    cropped image), the text is kept without it.
    """
    from .metadata import _compress, capture_metadata, restored_bytes, unpack_backup
    try:
        payload = capture_metadata(source.read_bytes(), cancel)
    except (OSError, ImageProblem):
        return None
    if payload is None:
        return None
    format, parts, stealth = unpack_backup(payload)
    if format != "PNG":
        return None
    try:
        return restored_bytes(pixels, payload, cancel)
    except ImageProblem:
        if not stealth or not parts:
            return None
        return restored_bytes(pixels, _compress("PNG", parts, []), cancel)


def prepare_image(pixels, source: Path, cancel=None, *, crop=None, max_size=None, keep_metadata=False) -> PreparedImage:
    """A PNG of the edited image to hand over: without metadata, or (``keep_metadata``, for NovelAI)
    with the original's generation information so NovelAI can read the settings back."""
    directory = TemporaryDirectory(prefix="sumire-novelai-", ignore_cleanup_errors=True)
    try:
        target = Path(directory.name) / "sumire-i2i.png"
        # Remove carriers before cropping/resampling can destroy their header.
        pixels = transform_image(remove_stealth(pixels), crop, max_size)
        data = with_metadata(pixels, source, cancel) if keep_metadata and source.is_file() else None
        if data is not None:
            target.write_bytes(data)
        else:
            save_image(pixels, target, source=source, format="PNG", cancel=cancel)
        check_cancel(cancel)
        return PreparedImage(directory, target, metadata=data is not None)
    except BaseException:
        directory.cleanup()
        raise


class CropPreview(QLabel):
    """Adjusts a crop frame that starts on the whole image.

    The four corners and the edges resize the frame and its inside moves it;
    a new frame is never drawn from scratch, so the image can't be lost by a stray click.
    """

    cropChanged = Signal(tuple)
    GRIP = 10

    def __init__(self, image, maximum=(500, 300)):
        super().__init__()
        self.source_size = image.size
        small = image.copy()
        small.thumbnail(maximum)
        self.setPixmap(QPixmap.fromImage(qimage(small)).scaled(*maximum, Qt.AspectRatioMode.KeepAspectRatio,
                                                             Qt.TransformationMode.SmoothTransformation))
        self.setFixedSize(self.pixmap().size())
        self.setMouseTracking(True)
        self.crop = (0, 0, image.width, image.height)
        self.drag = None

    def _scale(self):
        return self.width() / self.source_size[0], self.height() / self.source_size[1]

    def _frame(self):
        x, y, width, height = self.crop
        sx, sy = self._scale()
        return x * sx, y * sy, (x + width) * sx, (y + height) * sy

    def hit(self, point):
        """Which part of the frame a widget point grabs: corner/edge letters, "move" or None."""
        left, top, right, bottom = self._frame()
        px, py, grip = point.x(), point.y(), self.GRIP
        near_x = "l" if abs(px - left) <= grip else "r" if abs(px - right) <= grip else ""
        near_y = "t" if abs(py - top) <= grip else "b" if abs(py - bottom) <= grip else ""
        inside_x, inside_y = left - grip <= px <= right + grip, top - grip <= py <= bottom + grip
        if near_x and near_y:
            return near_y + near_x
        if near_x and inside_y:
            return near_x
        if near_y and inside_x:
            return near_y
        if left < px < right and top < py < bottom:
            return "move"
        return None

    CURSORS = {"tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
               "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
               "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
               "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
               "move": Qt.CursorShape.SizeAllCursor}

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            part = self.hit(event.position())
            self.drag = (part, event.position(), self.crop) if part else None

    def mouseMoveEvent(self, event):
        if self.drag is None or not event.buttons() & Qt.MouseButton.LeftButton:
            part = self.hit(event.position())
            self.setCursor(self.CURSORS.get(part, Qt.CursorShape.ArrowCursor))
            return
        part, start, (x, y, width, height) = self.drag
        sx, sy = self._scale()
        dx = round((event.position().x() - start.x()) / sx)
        dy = round((event.position().y() - start.y()) / sy)
        limit_w, limit_h = self.source_size
        if part == "move":
            x = max(0, min(limit_w - width, x + dx))
            y = max(0, min(limit_h - height, y + dy))
            self.set_crop((x, y, width, height))
            return
        left, top, right, bottom = x, y, x + width, y + height
        if "l" in part:
            left = max(0, min(right - 1, left + dx))
        if "r" in part:
            right = min(limit_w, max(left + 1, right + dx))
        if "t" in part:
            top = max(0, min(bottom - 1, top + dy))
        if "b" in part:
            bottom = min(limit_h, max(top + 1, bottom + dy))
        self.set_crop((left, top, right - left, bottom - top))

    def set_crop(self, crop):
        if crop != self.crop:
            self.crop = crop
            self.cropChanged.emit(crop)
            self.update()

    def mouseReleaseEvent(self, event):
        self.drag = None

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, top, right, bottom = self._frame()
        frame = QRectF(left, top, max(1.0, right - left), max(1.0, bottom - top))
        outside = QPainterPath()
        outside.addRect(QRectF(self.rect()))
        inside = QPainterPath()
        inside.addRect(frame)
        painter.fillPath(outside.subtracted(inside), QColor(0, 0, 0, 140))
        painter.setPen(QPen(QColor(255, 255, 255, 90), 1))
        for third in (1, 2):
            painter.drawLine(QPointF(left + (right - left) * third / 3, top), QPointF(left + (right - left) * third / 3, bottom))
            painter.drawLine(QPointF(left, top + (bottom - top) * third / 3), QPointF(right, top + (bottom - top) * third / 3))
        painter.setPen(QPen(QColor(TOKENS["accent"]), 1.5))
        painter.drawRect(frame.adjusted(0.75, 0.75, -0.75, -0.75))
        # L-shaped corner grips: the parts to drag.
        painter.setPen(QPen(QColor("#ffffff"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap))
        arm = min(18.0, (right - left) / 2, (bottom - top) / 2)
        for cx, cy, hx, hy in ((left, top, 1, 1), (right, top, -1, 1), (left, bottom, 1, -1), (right, bottom, -1, -1)):
            cx, cy = cx + hx * 2, cy + hy * 2
            painter.drawLine(QPointF(cx, cy), QPointF(cx + hx * arm, cy))
            painter.drawLine(QPointF(cx, cy), QPointF(cx, cy + hy * arm))


class ImageAdjustmentDialog(QDialog):
    def __init__(self, image, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("NovelAI用の切り抜き・縮小"))
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("四隅や辺をドラッグして範囲を調整します。枠の内側をドラッグすると移動します。\n出力は縦横の比率を保ったまま、指定した大きさに収めます。")))
        self.preview = CropPreview(image)
        layout.addWidget(self.preview, alignment=Qt.AlignmentFlag.AlignCenter)
        form = QFormLayout()
        self.fields = []
        for name, maximum, value in [(tr("左 X"), image.width - 1, 0), (tr("上 Y"), image.height - 1, 0),
                                      (tr("幅"), image.width, image.width), (tr("高さ"), image.height, image.height),
                                      (tr("出力の最大幅"), 32768, image.width), (tr("出力の最大高さ"), 32768, image.height)]:
            field = QSpinBox()
            field.setRange(0 if len(self.fields) < 2 else 1, maximum)
            field.setValue(value)
            self.fields.append(field)
            form.addRow(name, field)
        layout.addLayout(form)
        self.preview.cropChanged.connect(self.set_crop)
        for field in self.fields[:4]:
            field.valueChanged.connect(self.sync_crop)
        reset = QPushButton(tr("切り抜きを解除"))
        reset.clicked.connect(lambda: self.set_crop((0, 0, image.width, image.height)))
        layout.addWidget(reset)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("この範囲で取り込む"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def set_crop(self, crop):
        for field, value in zip(self.fields, crop):
            field.blockSignals(True)
            field.setValue(value)
            field.blockSignals(False)
        self.sync_crop()

    def sync_crop(self):
        x, y, width, height = (field.value() for field in self.fields[:4])
        width = min(width, self.preview.source_size[0] - x)
        height = min(height, self.preview.source_size[1] - y)
        for field, value in zip(self.fields[2:4], (width, height)):
            field.blockSignals(True)
            field.setValue(value)
            field.blockSignals(False)
        self.preview.crop = (x, y, width, height)
        self.preview.update()

    def options(self):
        return tuple(field.value() for field in self.fields[:4]), tuple(field.value() for field in self.fields[4:])


class ImageDragLabel(QLabel):
    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = path
        self.start = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setPixmap(QPixmap(str(path)).scaled(360, 200, Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation))
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(tr("この画像をNovelAIの生成画面へドラッグしてください。"))
        self.setAccessibleName(tr("NovelAIへドラッグする画像"))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self.start is not None and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self.start).manhattanLength() >= QApplication.startDragDistance()):
            self.start = None
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(self.path))])
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.setPixmap(self.pixmap().scaled(120, 80, Qt.AspectRatioMode.KeepAspectRatio))
            drag.exec(Qt.DropAction.CopyAction)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.start = None
        super().mouseReleaseEvent(event)


class NovelAIImportDialog(QDialog):
    """Shows a prepared, metadata-free PNG to drag or copy into NovelAI (``target``
    "novelai") or into any other app, such as a browser or a chat app ("drag")."""

    def __init__(self, prepared: PreparedImage, parent=None, target="novelai"):
        super().__init__(parent)
        self.prepared = prepared
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        novelai = target == "novelai"
        self.setWindowTitle(tr("NovelAIへ画像を取り込む") if novelai else tr("画像を渡す"))
        self.resize(480, 440)
        layout = QVBoxLayout(self)
        instructions = QLabel(tr("1. NovelAIの画像生成画面を開き、ログインします。\n"
                              "2. 下の画像を生成画面へドラッグします。\n"
                              "3. NovelAIで「Image2Image」を選びます。") if novelai else
                              tr("下の画像を、ブラウザーの投稿欄やチャットアプリへドラッグします。\n"
                              "貼り付けで渡すときは「画像をコピー」を押します。"))
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        self.preview = ImageDragLabel(prepared.path)
        layout.addWidget(self.preview)
        note = QLabel((tr("表示中の編集結果に、元の画像の生成情報（メタデータ）を付けたPNGで渡します。\n")
                       if prepared.metadata else tr("表示中の編集結果を、メタデータのないPNGで渡します。\n"))
                      + tr("※ 渡し終わるまで、この画面は閉じないでください。"))
        note.setWordWrap(True)
        layout.addWidget(note)
        self.path_field = QLineEdit(str(prepared.path))
        self.path_field.setReadOnly(True)
        self.path_field.setToolTip(tr("ドラッグできない場合は、アップロードの画面でこのファイルを選んでください。"))
        layout.addWidget(self.path_field)
        row = QHBoxLayout()
        self.open_button = QPushButton(tr("NovelAIを開く"))
        self.open_button.clicked.connect(self.open_browser)
        self.open_button.setVisible(novelai)
        row.addWidget(self.open_button)
        self.copy_button = QPushButton(tr("画像をコピー"))
        self.copy_button.clicked.connect(self.copy_image)
        row.addWidget(self.copy_button)
        close = QPushButton(tr("閉じる"))
        close.clicked.connect(self.close)
        row.addWidget(close)
        layout.addLayout(row)
        self.message = QLabel(tr("画像の取り込みと生成はNovelAI側で操作します。") if novelai else tr("閉じると、渡すために作ったPNGは削除します。"))
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.finished.connect(lambda _result: self.prepared.cleanup())

    def open_browser(self):
        if not QDesktopServices.openUrl(QUrl(NOVELAI_URL)):
            self.message.setText(tr("ブラウザーを開けませんでした。{NOVELAI_URL} を開いてください。").format(NOVELAI_URL=NOVELAI_URL))

    def copy_image(self):
        try:
            data = self.prepared.path.read_bytes()
        except OSError:
            self.message.setText(tr("取り込み用画像を読み込めません。Sumīreからもう一度開いてください。"))
            return
        mime = QMimeData()
        mime.setData("image/png", data)
        # "image/png" carries these exact bytes (with the metadata, when it was attached). No file link:
        # the file is removed when this window closes.
        mime.setImageData(QImage.fromData(data, "PNG"))
        QApplication.clipboard().setMimeData(mime)
        self.message.setText(tr("画像をコピーしました。NovelAIへCtrl+Vで貼り付けることも可能です。"))
