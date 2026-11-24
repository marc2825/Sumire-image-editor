"""Design tokens, the application stylesheet and a matching Qt palette.

Every colour used by the window, the stylesheet and custom painting comes from
TOKENS so that panels, lists and the canvas stay visually consistent. Spacing
follows 4 / 8 / 12 / 16 / 24 px and corners use 6 px (controls) or 8 px
(cards, popovers). One colour, one meaning: the violet accent marks the
selection, the primary action and keyboard focus; green, yellow and red are the
review labels (red also errors). Text is 12 / 13 / 15 / 20 px in the two bundled
weights, Regular and Bold.
"""
from importlib import resources
from pathlib import Path
from string import Template

from PySide6.QtCore import QPointF, QRectF, QTemporaryDir, Qt
from PySide6.QtGui import QColor, QFontDatabase, QImage, QPainter, QPainterPath, QPalette, QPen

from . import i18n

TOKENS = {
    # Surfaces, darkest to lightest. Neutral greys: a tinted ground would colour how the image looks.
    "canvas": "#1c1c1c",
    "chrome": "#212121",
    "panel": "#272727",
    "field": "#1f1f1f",
    "raised": "#303030",
    "control": "#333333",
    "control_hover": "#3d3d3d",
    "control_pressed": "#474747",
    "control_disabled": "#2c2c2c",
    # Lines: dividers between areas, and the edge of a control (at least 3:1 against the panel).
    "line": "#3a3a3a",
    "line_strong": "#757575",
    "line_hover": "#949494",
    # Text: body, secondary and hints all reach 4.5:1 on the panel.
    "text": "#ededed",
    "text_strong": "#f7f7f7",
    "text_muted": "#b4b4b4",
    "text_faint": "#9a9a9a",
    "text_disabled": "#6e6e6e",
    # Accent (violet, after the name): selection, the primary action and keyboard focus only.
    "accent": "#b8a6f5",
    "accent_hover": "#c9bbf8",
    "accent_pressed": "#a592ec",
    "accent_soft": "#3a3357",
    "accent_line": "#8f7fd6",
    "on_accent": "#1b1533",
    "accent_disabled": "#6f6890",
    "accent_disabled_soft": "#2f2b42",
    # Review labels: green 採用, yellow 保留, red 不採用. Red also marks errors and changes that cannot be undone.
    "ok": "#7ccf9b",
    "ok_soft": "#263a2d",
    "ok_line": "#4f8a64",
    "on_ok": "#10241a",
    "warn": "#e6c15c",
    "warn_soft": "#40371f",
    "warn_line": "#9c8440",
    "on_warn": "#2b220f",
    "danger": "#f08c7e",
    "danger_soft": "#45292a",
    "danger_line": "#a8645b",
    "danger_pressed": "#5a3530",
    "on_danger": "#2b1512",
    "info": "#9cc3f0",
    # Sort direction: ascending / descending.
    "sort_asc": "#93c3f2",
    "sort_desc": "#f1a49b",
    "neutral": "#8a8a8a",
    # Canvas checkerboard.
    "checker_a": "#222222",
    "checker_b": "#2a2a2a",
}

# The app mark: four squares on a dark violet ground (window icon, sumire.ico, start page).
BRAND = {"ground": "#29233d", "light": "#b8a6f5", "mid": "#8e7dd3", "deep": "#6b5ca9"}

# Noto Sans JP is bundled (sumire/fonts, SIL OFL 1.1) and registered by
# install_fonts(); if that fails, the next available font is used.
FONT_FAMILY = "'Noto Sans JP', 'Noto Sans CJK JP', 'Yu Gothic UI', 'Meiryo UI', 'Segoe UI', sans-serif"
# The bundled font is the Japanese subset and lacks many simplified Chinese
# characters. Mixing two fonts within a word looks broken, so Chinese starts
# with a Chinese font that Windows includes.
FONT_FAMILIES = {"zh_CN": "'Microsoft YaHei UI', 'Microsoft YaHei', 'Noto Sans CJK SC', 'Noto Sans SC', "
                          "'Noto Sans JP', 'Segoe UI', sans-serif"}
BUNDLED_FONTS = ("NotoSansJP-Regular.otf", "NotoSansJP-Bold.otf")


def font_family() -> str:
    return FONT_FAMILIES.get(i18n.language(), FONT_FAMILY)


def install_fonts() -> list[str]:
    """Register the bundled fonts for this process; the families that loaded.

    Nothing is installed into Windows. An empty list means the operating
    system's fonts are used.
    """
    families = set()
    for name in BUNDLED_FONTS:
        try:
            path = resources.files("sumire").joinpath("fonts", name)
            identifier = (QFontDatabase.addApplicationFont(str(path)) if isinstance(path, Path)
                          else QFontDatabase.addApplicationFontFromData(path.read_bytes()))
        except OSError:
            continue
        if identifier >= 0:
            families.update(QFontDatabase.applicationFontFamilies(identifier))
    return sorted(families)

_STYLE = Template("""
QWidget { color: $text; font-family: $font; font-size: 13px; }
QMainWindow, QDialog { background: $panel; }
/* Dialogs, popovers and menus carry an accent strip on top, so they read as
   separate from the main window. */
QDialog { border-top: 4px solid $accent; }
QFrame#topBar { background: $chrome; border-bottom: 1px solid $line; }
QWidget#panel { background: $panel; }
QFrame#panelFooter { background: $panel; border-top: 1px solid $line; }
QFrame#imageBar { background: $panel; border-bottom: 1px solid $line; }
QFrame#viewBar { background: $panel; border-top: 1px solid $line; }
QFrame#toast { background: $raised; border: 1px solid $line_strong; border-radius: 8px; }
QFrame#toast[tone="danger"] { border-color: $danger_line; background: $danger_soft; }
QLabel#toastText { background: transparent; }
QWidget#welcome { background: $canvas; }
QLabel#brand { font-size: 15px; font-weight: 700; color: $text_strong; }
QLabel#crumbSep { color: $text_faint; font-size: 15px; }
QLabel#section { color: $text_muted; font-size: 12px; font-weight: 700; }
QLabel#muted { color: $text_muted; font-size: 12px; }
QLabel#faint { color: $text_faint; font-size: 12px; }
QLabel#fileName { font-weight: 700; color: $text_strong; }
QLabel#status { color: $text; }
QLabel#danger { color: $danger; font-size: 12px; }
QLabel#keyHint { color: $text_faint; font-size: 12px; background: transparent; }
QLabel#estimate { color: $accent; font-weight: 700; }
QLabel#editPreview { background: $canvas; border: 1px solid $line; border-radius: 8px; }
QLabel#valueRow { color: $text; }
QLabel#heroTitle { font-size: 20px; font-weight: 700; color: $text_strong; }
QLabel#heroText { font-size: 13px; color: $text_muted; }
QLabel#saveState { font-size: 12px; color: $text_muted; padding: 0 2px; }

QPushButton, QToolButton {
    background: $control; border: 1px solid $line_strong; border-radius: 6px; padding: 6px 12px;
}
QPushButton:hover, QToolButton:hover { background: $control_hover; border-color: $line_hover; }
QPushButton:pressed, QToolButton:pressed { background: $control_pressed; }
QPushButton:disabled, QToolButton:disabled { color: $text_disabled; background: $control_disabled; border-color: $control_disabled; }
QPushButton::menu-indicator, QToolButton::menu-indicator { image: none; width: 0; }
QToolButton[popupMode="2"] { padding-right: 12px; }
QToolButton[variant="listAction"] { padding: 6px 6px; }
/* Keyboard focus: a 2 px accent ring. The padding shrinks by 1 px so the button keeps its size. */
QPushButton:focus, QToolButton:focus { border: 2px solid $accent; padding: 5px 11px; }
QToolButton[variant="listAction"]:focus { padding: 5px 5px; }

QPushButton#primary { color: $on_accent; background: $accent; border-color: $accent; font-weight: 700; padding: 6px 16px; }
QPushButton#primary:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton#primary:pressed { background: $accent_pressed; border-color: $accent_pressed; }
QPushButton#primary:disabled { color: $accent_disabled; background: $accent_disabled_soft; border-color: $accent_disabled_soft; }
QPushButton#primary:focus { border: 2px solid $text_strong; padding: 5px 15px; }

QPushButton[variant="ghost"], QToolButton[variant="ghost"] { background: transparent; border-color: transparent; }
QPushButton[variant="ghost"]:hover, QToolButton[variant="ghost"]:hover { background: $control; border-color: $control; }
QPushButton[variant="ghost"]:pressed, QToolButton[variant="ghost"]:pressed { background: $control_pressed; }
QPushButton[variant="ghost"]:disabled, QToolButton[variant="ghost"]:disabled { background: transparent; border-color: transparent; }
QToolButton[variant="ghost"]:checked { background: $accent_soft; border-color: $accent_soft; color: $accent; }
QPushButton[variant="ghost"]:focus, QToolButton[variant="ghost"]:focus { border: 2px solid $accent; padding: 5px 11px; }
QToolButton[variant="icon"] { background: transparent; border-color: transparent; padding: 5px; }
QToolButton[variant="icon"]:hover { background: $control; border-color: $control; }
QToolButton[variant="icon"]:pressed { background: $control_pressed; }
QToolButton[variant="icon"]:disabled { background: transparent; border-color: transparent; }
QToolButton[variant="icon"]:checked { background: $accent_soft; border-color: $accent_soft; }
QToolButton[variant="icon"]:focus { border: 2px solid $accent; padding: 4px; }
QToolButton[active="true"] { background: $accent_soft; border-color: $accent_soft; }
QPushButton[variant="link"] { background: transparent; border: none; color: $accent; padding: 2px 0; }
QPushButton[variant="link"]:hover { color: $accent_hover; text-decoration: underline; }
QPushButton[variant="link"]:focus { border: none; padding: 2px 0; text-decoration: underline; color: $accent_hover; }

/* The tools: icon above the name, all five the same size. */
QToolButton[variant="tool"] { background: transparent; border-color: transparent; padding: 6px 2px 4px 2px; font-size: 12px; }
QToolButton[variant="tool"]:hover { background: $control; border-color: $control; }
QToolButton[variant="tool"]:checked { background: $accent_soft; border-color: $accent_soft; color: $accent; font-weight: 700; }
QToolButton[variant="tool"]:disabled { background: transparent; border-color: transparent; }
QToolButton[variant="tool"]:focus { border: 2px solid $accent; padding: 5px 1px 3px 1px; }

QToolButton#fileMenu { padding: 5px 10px; }
QToolButton#fileMenu:focus { padding: 4px 9px; }
QLabel#workspaceTitle { color: $text_muted; font-weight: 700; }
QToolButton#saveMode { color: $text_muted; font-size: 12px; padding: 5px 10px; }
QToolButton#saveMode:hover { color: $text; }
QToolButton#saveMode:focus { padding: 4px 9px; }
QToolButton#restoreOriginal { color: $danger; background: $danger_soft; border: 1px solid $danger_line; padding: 5px 10px; }
QToolButton#restoreOriginal:hover { border-color: $danger; }
QToolButton#restoreOriginal:pressed { background: $danger_pressed; }
QToolButton#restoreOriginal:disabled { color: $text_disabled; background: $control_disabled; border-color: $line; }
QToolButton#restoreOriginal:focus { border: 2px solid $accent; padding: 4px 9px; }
QToolButton#disclosure { background: transparent; border: none; color: $text_muted; font-weight: 700; font-size: 12px; padding: 4px 0; }
QToolButton#disclosure:hover { color: $text; }
QToolButton#disclosure:focus { border: none; padding: 4px 0; color: $accent; text-decoration: underline; }
QToolButton#metadataState { background: transparent; border: 1px solid transparent; color: $text_muted; font-size: 12px; padding: 4px 6px; }
QToolButton#metadataState:hover { color: $text; border-color: $control; background: $control; }
QToolButton#metadataState:focus { border: 2px solid $accent; padding: 3px 5px; }
QListWidget#topicList { font-size: 15px; }
QListWidget#topicList::item { padding: 7px 10px; }
QListWidget#outlineList { background: transparent; border: none; font-size: 12px; color: $text_muted; }
QListWidget#outlineList::item { padding: 4px 8px; }
QListWidget#outlineList::item:hover { color: $text; }

QFrame#segmented { background: $field; border: 1px solid $line_strong; border-radius: 8px; }
QPushButton#segment, QToolButton#segment { background: transparent; border: none; border-radius: 6px; padding: 6px 4px; color: $text_muted; }
QPushButton#segment:hover, QToolButton#segment:hover { color: $text; background: $raised; }
QPushButton#segment:checked, QToolButton#segment:checked { background: $accent_soft; color: $accent; font-weight: 700; }
QPushButton#segment:disabled, QToolButton#segment:disabled { color: $text_disabled; background: transparent; }
QPushButton#segment:focus, QToolButton#segment:focus { border: 2px solid $accent; padding: 4px 2px; }
QPushButton#toggle { text-align: center; padding: 6px 10px; }
QPushButton#toggle:checked { background: $accent_soft; border-color: $accent_line; color: $accent; font-weight: 700; }
QPushButton#toggle:focus { border: 2px solid $accent; padding: 5px 9px; }

/* Review labels: outlined in their colour, filled when the shown image has that label. */
QPushButton#reviewLabel { padding: 6px 14px; font-weight: 700; color: $ok; background: transparent; border-color: $ok_line; }
QPushButton#reviewLabel:hover { border-color: $ok; background: $ok_soft; }
QPushButton#reviewLabel:checked { color: $on_ok; background: $ok; border-color: $ok; }
QPushButton#reviewLabel[label="rejected"] { color: $danger; border-color: $danger_line; }
QPushButton#reviewLabel[label="rejected"]:hover { border-color: $danger; background: $danger_soft; }
QPushButton#reviewLabel[label="rejected"]:checked { color: $on_danger; background: $danger; border-color: $danger; }
QPushButton#reviewLabel[label="pending"] { color: $warn; border-color: $warn_line; }
QPushButton#reviewLabel[label="pending"]:hover { border-color: $warn; background: $warn_soft; }
QPushButton#reviewLabel[label="pending"]:checked { color: $on_warn; background: $warn; border-color: $warn; }
QPushButton#reviewLabel:disabled { color: $text_disabled; background: transparent; border-color: $line; }
QPushButton#reviewLabel:focus { border: 2px solid $accent; padding: 5px 13px; }

QPushButton#recent { text-align: left; background: transparent; border: none; border-radius: 6px; padding: 8px 10px; }
QPushButton#recent:hover { background: $raised; }
QPushButton#recent:focus { border: 2px solid $accent; padding: 6px 8px; }
QToolButton#recentRemove { background: transparent; border: none; border-radius: 6px; color: $text_faint; padding: 4px 9px; }
QToolButton#recentRemove:hover { background: $raised; color: $text; }
QToolButton#recentRemove:focus { border: 2px solid $accent; padding: 2px 7px; }

QFrame#dropZone { border: 1px dashed $line_strong; border-radius: 12px; background: transparent; }
QFrame#dropZone[drag="true"] { border: 1px solid $accent; background: $accent_disabled_soft; }
QFrame#selectionBar { background: $accent_soft; border-radius: 6px; }
QFrame#popover { background: $raised; border: 1px solid $line_strong; border-top: 3px solid $accent; border-radius: 8px; }
QFrame#divider { background: $line; max-height: 1px; min-height: 1px; border: none; }
QFrame#vdivider { background: $line; max-width: 1px; min-width: 1px; border: none; }

QCheckBox, QRadioButton { spacing: 8px; padding: 1px 4px 1px 2px; border: 2px solid transparent; border-radius: 6px; }
QCheckBox:focus, QRadioButton:focus { border-color: $accent; }
QCheckBox::indicator { width: 16px; height: 16px; }
$checkbox

QListView { background: $panel; border: none; outline: none; }
QListView#library { padding: 0; }
QListView:focus { outline: none; }
QComboBox, QLineEdit { background: $field; border: 1px solid $line_strong; border-radius: 6px; padding: 5px 8px; }
QComboBox:hover, QLineEdit:hover { border-color: $line_hover; }
QComboBox:focus, QLineEdit:focus { border: 2px solid $accent; padding: 4px 7px; }
QComboBox:disabled, QLineEdit:disabled { color: $text_disabled; border-color: $line; }
QLineEdit#zoomField { background: transparent; border: 1px solid transparent; color: $text_muted; font-size: 12px; padding: 3px 6px; }
QLineEdit#zoomField:hover { border-color: $line_strong; }
QLineEdit#zoomField:focus { background: $field; border: 2px solid $accent; color: $text; padding: 2px 5px; }
QLineEdit#positionValue { background: transparent; border: 1px solid transparent; color: $text_muted; padding: 2px 4px; }
QLineEdit#positionValue:hover { border-color: $line_strong; }
QLineEdit#positionValue:focus { background: $field; border: 2px solid $accent; color: $text; padding: 1px 3px; }
QComboBox::drop-down { border: none; width: 22px; }
$combo_arrow
QComboBox QAbstractItemView { background: $raised; border: 1px solid $line_strong; selection-background-color: $accent_soft; selection-color: $text_strong; outline: none; }
QAbstractSpinBox:focus { border: 2px solid $accent; }

QSlider { min-height: 20px; }
QSlider::groove:horizontal { height: 4px; background: $line_strong; border-radius: 2px; }
QSlider::sub-page:horizontal { height: 4px; background: $accent; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; height: 14px; margin: -6px 0; background: $accent; border: 1px solid $accent; border-radius: 8px; }
QSlider::handle:horizontal:hover { background: $accent_hover; }
QSlider::handle:horizontal:focus { border: 2px solid $text_strong; }
QSlider::sub-page:horizontal:disabled { background: $control; }
QSlider::handle:horizontal:disabled { background: $line_strong; border-color: $line_strong; }

QSplitter::handle { background: $line; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget#panel { background: $panel; }
QScrollBar:vertical { width: 8px; background: transparent; margin: 2px; }
QScrollBar::handle:vertical { background: $line_strong; border-radius: 3px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: $line_hover; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { height: 8px; background: transparent; margin: 2px; }
QScrollBar::handle:horizontal { background: $line_strong; border-radius: 3px; min-width: 28px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QProgressBar { border: none; background: $control; border-radius: 3px; height: 5px; max-height: 5px; }
QProgressBar::chunk { background: $accent; border-radius: 3px; }
QProgressBar#batchProgress { min-height: 20px; max-height: 20px; text-align: center; color: $text; font-size: 12px; }
QProgressBar#batchProgress::chunk { background: $accent_soft; }

QMenu { background: $raised; border: 1px solid $line_strong; border-top: 2px solid $accent; padding: 6px 0; }
QMenu::item { padding: 6px 28px 6px 14px; background: transparent; }
QMenu::item:selected { background: $accent_soft; color: $text_strong; }
QMenu::item:disabled { color: $text_disabled; }
QMenu::separator { height: 1px; background: $line; margin: 5px 10px; }
QMenu::indicator { width: 14px; height: 14px; padding-left: 6px; }

QPlainTextEdit { background: $field; color: $text; border: 1px solid $line_strong; border-radius: 6px; }
QPlainTextEdit:focus { border: 2px solid $accent; }
QTabWidget::pane { border: 1px solid $line_strong; border-radius: 6px; top: -1px; }
QTabBar::tab { background: transparent; color: $text_muted; padding: 7px 14px; border: none; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: $text_strong; font-weight: 700; border-bottom-color: $accent; }
QTabBar::tab:hover { color: $text; }
$close_button
QTreeWidget, QTableView { background: $field; border: 1px solid $line_strong; border-radius: 6px; }
QHeaderView::section { background: $raised; color: $text_muted; border: none; padding: 5px 8px; }
QToolTip { background: $raised; color: $text_strong; border: 1px solid $line_strong; padding: 5px 7px; }
""")

_assets: QTemporaryDir | None = None
ASSETS = ("check", "box", "box_disabled", "arrow", "radio", "radio_on", "close", "close_hover")


def _paint_asset(path: Path, kind: str, scale: int):
    """Small stylesheet images (check mark, combo arrow) in a 16 px design grid.

    Qt loads ``name@2x.png`` automatically on high-density screens, so both
    files keep a 16 px logical size.
    """
    image = QImage(16 * scale, 16 * scale, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(scale, scale)
    if kind == "check":
        painter.setBrush(QColor(TOKENS["accent"]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(0.5, 0.5, 15, 15), 3.5, 3.5)
        painter.setPen(QPen(QColor(TOKENS["on_accent"]), 2.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        stroke = QPainterPath(QPointF(4.3, 8.3))
        stroke.lineTo(6.8, 10.8)
        stroke.lineTo(11.8, 5.3)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(stroke)
    elif kind in ("box", "box_disabled"):
        fill, line = ("field", "line_strong") if kind == "box" else ("control_disabled", "line")
        painter.setBrush(QColor(TOKENS[fill]))
        painter.setPen(QPen(QColor(TOKENS[line]), 1))
        painter.drawRoundedRect(QRectF(1, 1, 14, 14), 3, 3)
    elif kind in ("radio", "radio_on"):
        painter.setBrush(QColor(TOKENS["field"]))
        painter.setPen(QPen(QColor(TOKENS["accent" if kind == "radio_on" else "line_strong"]), 1.2))
        painter.drawEllipse(QRectF(1, 1, 14, 14))
        if kind == "radio_on":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(TOKENS["accent"]))
            painter.drawEllipse(QRectF(4.5, 4.5, 7, 7))
    elif kind in ("close", "close_hover"):
        # The tab's close mark: quiet until pointed at (Qt's own is a bright red-orange square).
        if kind == "close_hover":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(TOKENS["control_hover"]))
            painter.drawRoundedRect(QRectF(0, 0, 16, 16), 4, 4)
        painter.setPen(QPen(QColor(TOKENS["text" if kind == "close_hover" else "text_muted"]), 1.5,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(5, 5), QPointF(11, 11))
        painter.drawLine(QPointF(11, 5), QPointF(5, 11))
    elif kind == "arrow":
        painter.setPen(QPen(QColor(TOKENS["text_muted"]), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        stroke = QPainterPath(QPointF(4.5, 6.5))
        stroke.lineTo(8, 10)
        stroke.lineTo(11.5, 6.5)
        painter.drawPath(stroke)
    painter.end()
    # PySide6's stub types the format as bytes, but at run time only a str works (b"PNG" raises ValueError).
    if not image.save(str(path), "PNG"):  # type: ignore[call-overload]
        raise OSError(f"cannot write {path.name}")


def _asset_rules() -> dict[str, str]:
    """Stylesheet rules that need image files; empty when no temp folder is available.

    Fusion's own indicators remain as the fallback, so a missing or read-only
    temporary folder only changes the look of check boxes and combo arrows.
    """
    global _assets
    try:
        if _assets is None:
            _assets = QTemporaryDir()
            if not _assets.isValid():
                raise OSError("no temporary folder")
            folder = Path(_assets.path())
            for kind in ASSETS:
                _paint_asset(folder / f"{kind}.png", kind, 1)
                _paint_asset(folder / f"{kind}@2x.png", kind, 2)
        folder = Path(_assets.path())
        if not all((folder / f"{kind}.png").is_file() for kind in ASSETS):
            raise OSError("missing assets")
    except OSError:
        return {"checkbox": "", "combo_arrow": "", "close_button": ""}
    url = lambda kind: '"' + (folder / f"{kind}.png").as_posix() + '"'
    return {
        "checkbox": (f"QCheckBox::indicator:unchecked {{ image: url({url('box')}); }}\n"
                     f"QCheckBox::indicator:checked {{ image: url({url('check')}); }}\n"
                     f"QCheckBox::indicator:disabled {{ image: url({url('box_disabled')}); }}\n"
                     "QRadioButton { spacing: 8px; padding: 2px 0; }\nQRadioButton::indicator { width: 16px; height: 16px; }\n"
                     f"QRadioButton::indicator:unchecked {{ image: url({url('radio')}); }}\n"
                     f"QRadioButton::indicator:checked {{ image: url({url('radio_on')}); }}"),
        "combo_arrow": f"QComboBox::down-arrow {{ image: url({url('arrow')}); }}",
        "close_button": (f"QTabBar::close-button {{ image: url({url('close')}); subcontrol-position: right; width: 16px; height: 16px; padding: 4px; }}\n"
                         f"QTabBar::close-button:hover {{ image: url({url('close_hover')}); }}"),
    }


def stylesheet() -> str:
    return _STYLE.substitute(TOKENS, font=font_family(), **_asset_rules())


def color(name: str) -> QColor:
    return QColor(TOKENS[name])


def dark_palette() -> QPalette:
    # QFileDialog's tree, table headers and other Fusion controls use palette
    # brushes even when a parent stylesheet sets light QWidget text.
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: TOKENS["panel"],
        QPalette.ColorRole.WindowText: TOKENS["text"],
        QPalette.ColorRole.Base: TOKENS["field"],
        QPalette.ColorRole.AlternateBase: TOKENS["panel"],
        QPalette.ColorRole.Text: TOKENS["text"],
        QPalette.ColorRole.Button: TOKENS["control"],
        QPalette.ColorRole.ButtonText: TOKENS["text"],
        QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Highlight: TOKENS["accent_soft"],
        QPalette.ColorRole.HighlightedText: TOKENS["text_strong"],
        QPalette.ColorRole.ToolTipBase: TOKENS["raised"],
        QPalette.ColorRole.ToolTipText: TOKENS["text_strong"],
        QPalette.ColorRole.PlaceholderText: TOKENS["text_faint"],
        QPalette.ColorRole.Link: TOKENS["accent"],
        QPalette.ColorRole.LinkVisited: "#c6b7e6",
        QPalette.ColorRole.Accent: TOKENS["accent"],
        QPalette.ColorRole.Light: TOKENS["line_strong"],
        QPalette.ColorRole.Midlight: TOKENS["line"],
        QPalette.ColorRole.Mid: TOKENS["control_disabled"],
        QPalette.ColorRole.Dark: TOKENS["canvas"],
        QPalette.ColorRole.Shadow: "#101419",
    }
    for role, value in colors.items():
        palette.setColor(role, QColor(value))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(TOKENS["text_disabled"]))
    return palette


def tint_caption(widget) -> None:
    """Windows 11: give a dialog a tinted title bar, apart from the main window's.

    Uses DWMWA_BORDER_COLOR / CAPTION_COLOR / TEXT_COLOR (34–36). Older Windows
    ignores them, and other systems keep their own title bars.
    """
    import sys
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = wintypes.HWND(int(widget.winId()))
        for attribute, name in ((34, "accent_line"), (35, "accent_soft"), (36, "text_strong")):
            color = QColor(TOKENS[name])
            value = ctypes.c_uint(color.red() | color.green() << 8 | color.blue() << 16)  # COLORREF
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value))
    except (AttributeError, OSError, ValueError):
        pass
