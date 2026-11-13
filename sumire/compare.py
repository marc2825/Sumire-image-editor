"""Two to six image views side by side; each zooms on its own unless linking is turned on."""
from .i18n import tr
from PySide6.QtCore import QPointF, Signal, QTimer
from PySide6.QtWidgets import QCheckBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .canvas import Canvas
from .imaging import Document


class CompareCanvas(Canvas):
    viewChanged = Signal()

    def zoom(self, factor, anchor=None):
        super().zoom(factor, anchor)
        self.viewChanged.emit()

    def mouseMoveEvent(self, event):
        panning = self.pan_start is not None
        super().mouseMoveEvent(event)
        if panning:
            self.viewChanged.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.document:
            self.viewChanged.emit()


def grid_columns(count):
    return count if count <= 3 else 2 if count == 4 else 3


class ComparisonDialog(QDialog):
    def __init__(self, paths, images, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("{count}枚を比較 · ホイールで拡大 / Spaceまたは中ボタンで移動").format(count=len(paths)))
        self.resize(1180, 760)
        layout = QVBoxLayout(self)
        self.views = []
        grid = QGridLayout()
        grid.setSpacing(8)
        columns = grid_columns(len(paths))
        for number, (path, image) in enumerate(zip(paths, images)):
            panel = QWidget()
            column = QVBoxLayout(panel)
            column.setContentsMargins(0, 0, 0, 0)
            name = QLabel(path.name)
            name.setToolTip(str(path))
            column.addWidget(name)
            view = CompareCanvas()
            view.set_document(Document(path, image))
            view.locked = True
            view.setAcceptDrops(False)
            column.addWidget(view, 1)
            self.views.append(view)
            grid.addWidget(panel, *divmod(number, columns))
        layout.addLayout(grid, 1)
        for view in self.views:
            view.viewChanged.connect(lambda source=view: self.synchronize(source) if self.linked.isChecked() else None)
        row = QHBoxLayout()
        self.linked = QCheckBox(tr("拡大・移動を連動"))
        self.linked.setToolTip(tr("オンにすると、1枚の拡大・移動をほかの画像にも同じ位置で反映します。"))
        self.linked.toggled.connect(lambda checked: self.synchronize(self.views[0]) if checked else None)
        row.addWidget(self.linked)
        row.addStretch(1)
        fit = QPushButton(tr("すべて全体表示"))
        fit.clicked.connect(self.fit)
        row.addWidget(fit)
        actual = QPushButton(tr("すべて原寸表示"))
        actual.clicked.connect(self.actual_size)
        row.addWidget(actual)
        close = QPushButton(tr("閉じる"))
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)
        QTimer.singleShot(0, self.fit)

    def fit(self):
        for view in self.views:
            view.fit()

    def actual_size(self):
        for view in self.views:
            view.zoom(1 / view.scale)

    def synchronize(self, source):
        if self.syncing:
            return
        self.syncing = True
        try:
            center = source.to_image(QPointF(source.width() / 2, source.height() / 2))
            for target in self.views:
                if target is source:
                    continue
                target.scale = source.scale
                point = QPointF(center.x() / source.image.width() * target.image.width(),
                                center.y() / source.image.height() * target.image.height())
                target.offset = QPointF(target.width() / 2, target.height() / 2) - point * target.scale
                target.fitted = False
                target.update()
        finally:
            self.syncing = False

    syncing = False
