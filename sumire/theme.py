"""Design tokens, the application stylesheet and a matching Qt palette.

Every colour used by the window, the stylesheet and custom painting comes from
TOKENS so that panels, lists and the canvas stay visually consistent. Spacing
follows 4 / 8 / 12 / 16 / 24 px and corners use 6 px (controls) or 8 px
(cards, popovers). The accent colour is reserved for the primary action and
for the selected state.
"""
from importlib import resources
from pathlib import Path
from string import Template

from PySide6.QtCore import QPointF, QRectF, QTemporaryDir, Qt
from PySide6.QtGui import QColor, QFontDatabase, QImage, QPainter, QPainterPath, QPalette, QPen

from . import i18n

TOKENS = {
    # Surfaces, darkest to lightest.
    "canvas": "#171a1f",
    "chrome": "#1d2126",
    "panel": "#242930",
    "field": "#1c2026",
    "raised": "#2b313a",
    "control": "#343b45",
    "control_hover": "#3d4551",
    "control_pressed": "#47505e",
    "control_disabled": "#2a2f37",
    # Lines.
    "line": "#2f353e",
    "line_strong": "#434b57",
    # Text.
    "text": "#e5e9ef",
    "text_strong": "#f4f6f9",
    "text_muted": "#9aa4b2",
    "text_faint": "#6c7583",
    "text_disabled": "#5f6875",
    # Accent: primary action and selection only.
    "accent": "#a7dfc2",
    "accent_hover": "#bfe9d2",
    "accent_pressed": "#8fcfad",
    "accent_soft": "#2c3f37",
    "accent_line": "#6fae90",
    "on_accent": "#12261c",
    # Status tones.
    "ok": "#8fd3b0",
    "warn": "#e9c77b",
    "warn_soft": "#463e2b",
    "warn_line": "#a58c52",
    "danger": "#f1a49b",
    "danger_soft": "#4a3230",
    "danger_line": "#b9766e",
    "info": "#93c3f2",
    # Sort direction: ascending / descending.
    "sort_asc": "#93c3f2",
    "sort_desc": "#f1a49b",
    "neutral": "#7d8794",
    # Canvas checkerboard.
    "checker_a": "#202329",
    "checker_b": "#272b31",
}

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
QFrame#statusBar { background: $chrome; border-top: 1px solid $line; }
QWidget#panel { background: $panel; }
QFrame#panelFooter { background: $panel; border-top: 1px solid $line; }
QFrame#canvasHeader { background: $canvas; border-bottom: 1px solid $line; }
QWidget#welcome { background: $canvas; }
QLabel#brand { font-size: 16px; font-weight: 700; color: $text_strong; }
QLabel#crumbSep { color: $text_faint; font-size: 15px; }
QLabel#section { color: $text_muted; font-size: 11px; font-weight: 700; }
QLabel#muted { color: $text_muted; font-size: 12px; }
QLabel#faint { color: $text_faint; font-size: 12px; }
QLabel#fileName { font-weight: 700; color: $text_strong; }
QLabel#status { color: $text_muted; }
QLabel#danger { color: $danger; font-size: 12px; }
QLabel#keyHint { color: $text_faint; font-size: 10px; background: transparent; }
QLabel#estimate { color: $accent; font-weight: 600; }
QLabel#editPreview { background: $canvas; border: 1px solid $line; border-radius: 8px; }
QLabel#valueRow { color: $text; }
QLabel#heroTitle { font-size: 26px; font-weight: 700; color: $text_strong; }
QLabel#heroText { font-size: 13px; color: $text_muted; }
QLabel#saveState { font-size: 12px; color: $text_muted; padding: 0 2px; }

QPushButton, QToolButton {
    background: $control; border: 1px solid $line_strong; border-radius: 6px; padding: 6px 12px;
}
QPushButton:hover, QToolButton:hover { background: $control_hover; }
QPushButton:pressed, QToolButton:pressed { background: $control_pressed; }
QPushButton:disabled, QToolButton:disabled { color: $text_disabled; background: $control_disabled; border-color: $control_disabled; }
QPushButton::menu-indicator, QToolButton::menu-indicator { image: none; width: 0; }
QToolButton[popupMode="2"] { padding-right: 12px; }
QToolButton[variant="listAction"] { padding: 6px 6px; }

QPushButton#primary { color: $on_accent; background: $accent; border-color: $accent; font-weight: 700; padding: 6px 16px; }
QPushButton#primary:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton#primary:pressed { background: $accent_pressed; border-color: $accent_pressed; }
QPushButton#primary:disabled { color: #5d7568; background: #2b3933; border-color: #2b3933; }

QPushButton[variant="ghost"], QToolButton[variant="ghost"] { background: transparent; border-color: transparent; }
QPushButton[variant="ghost"]:hover, QToolButton[variant="ghost"]:hover { background: $control; border-color: $control; }
QPushButton[variant="ghost"]:pressed, QToolButton[variant="ghost"]:pressed { background: $control_pressed; }
QPushButton[variant="ghost"]:disabled, QToolButton[variant="ghost"]:disabled { background: transparent; border-color: transparent; }
QToolButton[variant="ghost"]:checked { background: $accent_soft; border-color: $accent_soft; color: $accent; }
QToolButton[variant="icon"] { background: transparent; border-color: transparent; padding: 5px; }
QToolButton[variant="icon"]:hover { background: $control; border-color: $control; }
QToolButton[variant="icon"]:pressed { background: $control_pressed; }
QToolButton[variant="icon"]:disabled { background: transparent; border-color: transparent; }
QToolButton[active="true"] { background: $accent_soft; border-color: $accent_soft; }
QPushButton[variant="link"] { background: transparent; border: none; color: $accent; padding: 2px 0; }
QPushButton[variant="link"]:hover { color: $accent_hover; text-decoration: underline; }

QToolButton#fileMenu { font-weight: 600; padding: 5px 10px; }
QLabel#workspaceTitle { color: $text_muted; font-weight: 600; }
QToolButton#saveMode { color: $text_muted; font-size: 12px; padding: 5px 10px; }
QToolButton#restoreOriginal { color: $danger; background: $danger_soft; border: 1px solid $danger_line; padding: 5px 10px; }
QToolButton#restoreOriginal:hover { border-color: $danger; }
QToolButton#restoreOriginal:pressed { background: #5a3a37; }
QToolButton#restoreOriginal:disabled { color: $text_disabled; background: $control_disabled; border-color: $line; }
QToolButton#saveMode:hover { color: $text; }
QToolButton#disclosure { background: transparent; border: none; color: $text_muted; font-weight: 700; font-size: 12px; padding: 4px 0; }
QToolButton#disclosure:hover { color: $text; }
QToolButton#metadataState { background: transparent; border: none; color: $text_muted; font-size: 12px; padding: 4px 6px; }
QToolButton#metadataState[found="true"] { color: $warn; }
QToolButton#metadataState:hover { color: $text; text-decoration: underline; }
QListWidget#topicList { font-size: 15px; }
QListWidget#topicList::item { padding: 7px 10px; }
QListWidget#outlineList { background: transparent; border: none; font-size: 12px; color: $text_muted; }
QListWidget#outlineList::item { padding: 4px 8px; }
QListWidget#outlineList::item:hover { color: $text; }

QFrame#segmented { background: $field; border: 1px solid $line; border-radius: 8px; }
QPushButton#segment { background: transparent; border: none; border-radius: 6px; padding: 6px 4px; color: $text_muted; }
QPushButton#segment:hover { color: $text; background: $raised; }
QPushButton#segment:checked { background: $control_hover; color: $accent; font-weight: 700; }
QPushButton#segment:disabled { color: $text_disabled; background: transparent; }
QPushButton#toggle { text-align: center; padding: 6px 10px; }
QPushButton#toggle:checked { background: $accent_soft; border-color: $accent_line; color: $accent; font-weight: 700; }

QPushButton#reviewLabel { padding: 7px 4px; font-weight: 600; color: $accent; background: $accent_soft; border-color: $accent_line; }
QPushButton#reviewLabel:hover { border-color: $accent; }
QPushButton#reviewLabel:checked { color: $on_accent; background: $accent; border-color: $accent; font-weight: 700; }
QPushButton#reviewLabel[label="rejected"] { color: $danger; background: $danger_soft; border-color: $danger_line; }
QPushButton#reviewLabel[label="rejected"]:hover { border-color: $danger; }
QPushButton#reviewLabel[label="rejected"]:checked { color: #2b1512; background: $danger; border-color: $danger; }
QPushButton#reviewLabel[label="pending"] { color: $warn; background: $warn_soft; border-color: $warn_line; }
QPushButton#reviewLabel[label="pending"]:hover { border-color: $warn; }
QPushButton#reviewLabel[label="pending"]:checked { color: #2b220f; background: $warn; border-color: $warn; }
QPushButton#reviewLabel:disabled { color: $text_disabled; background: $control_disabled; border-color: $line; }

QPushButton#recent { text-align: left; background: transparent; border: none; border-radius: 6px; padding: 8px 10px; }
QPushButton#recent:hover { background: $raised; }
QToolButton#recentRemove { background: transparent; border: none; border-radius: 6px; color: $text_faint; padding: 4px 9px; }
QToolButton#recentRemove:hover { background: $raised; color: $text; }

QFrame#dropZone { border: 1px dashed $line_strong; border-radius: 12px; background: transparent; }
QFrame#dropZone[drag="true"] { border: 1px solid $accent; background: #1b2420; }
QFrame#selectionBar { background: $accent_soft; border-radius: 6px; }
QFrame#popover { background: $raised; border: 1px solid $line_strong; border-top: 3px solid $accent; border-radius: 8px; }
QFrame#divider { background: $line; max-height: 1px; min-height: 1px; border: none; }

QCheckBox { spacing: 8px; padding: 2px 0; }
QCheckBox::indicator { width: 16px; height: 16px; }
$checkbox

QListView { background: $panel; border: none; outline: none; }
QListView#library { padding: 0; }
QComboBox, QLineEdit { background: $field; border: 1px solid $line_strong; border-radius: 6px; padding: 5px 8px; }
QComboBox:hover, QLineEdit:hover { border-color: #56606e; }
QComboBox:focus, QLineEdit:focus { border-color: $accent_line; }
QComboBox:disabled, QLineEdit:disabled { color: $text_disabled; border-color: $line; }
QLineEdit#zoomField { background: transparent; border: 1px solid transparent; color: $text_muted; font-size: 12px; padding: 3px 6px; }
QLineEdit#zoomField:hover { border-color: $line_strong; }
QLineEdit#zoomField:focus { background: $field; border-color: $accent_line; color: $text; }
QLineEdit#positionValue { background: transparent; border: 1px solid transparent; color: $text_muted; padding: 2px 4px; }
QLineEdit#positionValue:hover { border-color: $line_strong; }
QLineEdit#positionValue:focus { background: $field; border-color: $accent_line; color: $text; }
QComboBox::drop-down { border: none; width: 22px; }
$combo_arrow
QComboBox QAbstractItemView { background: $raised; border: 1px solid $line_strong; selection-background-color: $accent_soft; selection-color: $text_strong; outline: none; }

QSlider::groove:horizontal { height: 4px; background: $control; border-radius: 2px; }
QSlider::sub-page:horizontal { height: 4px; background: $accent_line; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; height: 14px; margin: -5px 0; background: $accent; border-radius: 7px; }
QSlider::handle:horizontal:hover { background: $accent_hover; }
QSlider::sub-page:horizontal:disabled { background: $control; }
QSlider::handle:horizontal:disabled { background: $line_strong; }

QSplitter::handle { background: $line; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget#panel { background: $panel; }
QScrollBar:vertical { width: 8px; background: transparent; margin: 2px; }
QScrollBar::handle:vertical { background: $line_strong; border-radius: 3px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: #56606e; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { height: 8px; background: transparent; margin: 2px; }
QScrollBar::handle:horizontal { background: $line_strong; border-radius: 3px; min-width: 28px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QProgressBar { border: none; background: $control; border-radius: 3px; height: 5px; max-height: 5px; }
QProgressBar::chunk { background: $accent; border-radius: 3px; }
QProgressBar#batchProgress { min-height: 20px; max-height: 20px; text-align: center; color: $text; font-size: 12px; }
QProgressBar#batchProgress::chunk { background: #3b6652; }

QMenu { background: $raised; border: 1px solid $line_strong; border-top: 2px solid $accent_line; padding: 6px 0; }
QMenu::item { padding: 6px 28px 6px 14px; background: transparent; }
QMenu::item:selected { background: $control_hover; color: $text_strong; }
QMenu::item:disabled { color: $text_disabled; }
QMenu::separator { height: 1px; background: $line; margin: 5px 10px; }
QMenu::indicator { width: 14px; height: 14px; padding-left: 6px; }

QPlainTextEdit { background: $field; color: $text; border: 1px solid $line_strong; border-radius: 6px; }
QTabWidget::pane { border: 1px solid $line_strong; border-radius: 6px; top: -1px; }
QTabBar::tab { background: transparent; color: $text_muted; padding: 7px 14px; border: none; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: $text_strong; border-bottom-color: $accent; }
QTabBar::tab:hover { color: $text; }
QTreeWidget, QTableView { background: $field; border: 1px solid $line_strong; border-radius: 6px; }
QHeaderView::section { background: $raised; color: $text_muted; border: none; padding: 5px 8px; }
QToolTip { background: $raised; color: $text_strong; border: 1px solid $line_strong; padding: 5px 7px; }
""")

_assets: QTemporaryDir | None = None
ASSETS = ("check", "box", "box_disabled", "arrow", "radio", "radio_on")


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
        return {"checkbox": "", "combo_arrow": ""}
    url = lambda kind: '"' + (folder / f"{kind}.png").as_posix() + '"'
    return {
        "checkbox": (f"QCheckBox::indicator:unchecked {{ image: url({url('box')}); }}\n"
                     f"QCheckBox::indicator:checked {{ image: url({url('check')}); }}\n"
                     f"QCheckBox::indicator:disabled {{ image: url({url('box_disabled')}); }}\n"
                     "QRadioButton { spacing: 8px; padding: 2px 0; }\nQRadioButton::indicator { width: 16px; height: 16px; }\n"
                     f"QRadioButton::indicator:unchecked {{ image: url({url('radio')}); }}\n"
                     f"QRadioButton::indicator:checked {{ image: url({url('radio_on')}); }}"),
        "combo_arrow": f"QComboBox::down-arrow {{ image: url({url('arrow')}); }}",
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
