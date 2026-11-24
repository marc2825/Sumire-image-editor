"""Generate the established Sumīre icon, Windows version resource and build inventory."""
import importlib.metadata
import json
from pathlib import Path
import platform

from PIL import Image, ImageDraw
from sumire import DISPLAY_VERSION, __version__

ROOT = Path(__file__).resolve().parents[1]


# The mark's colours (sumire.theme.BRAND) and squares (sumire.icons.MARK_SQUARES, in 64 units),
# repeated here so the icon can be made without starting Qt.
BRAND = {"ground": "#29233d", "light": "#b8a6f5", "mid": "#8e7dd3", "deep": "#6b5ca9"}
MARK_SQUARES = ((14, 14, "light"), (34, 14, "mid"), (14, 34, "deep"), (34, 34, "light"))


def write_icon(path):
    icon = Image.new("RGBA", (256, 256), BRAND["ground"])
    draw = ImageDraw.Draw(icon)
    for x, y, color in MARK_SQUARES:
        draw.rectangle((x * 4, y * 4, x * 4 + 63, y * 4 + 63), fill=BRAND[color])
    icon.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def prepare(root=ROOT):
    assets, build = root / "assets", root / "build"
    assets.mkdir(exist_ok=True)
    build.mkdir(exist_ok=True)
    write_icon(assets / "sumire.ico")
    version = tuple(int(n) for n in __version__.split(".")) + (0,)
    (build / "sumire-version.txt").write_text(
        "VSVersionInfo(\n"
        f" ffi=FixedFileInfo(filevers={version!r}, prodvers={version!r}, mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)),\n"
        " kids=[StringFileInfo([StringTable('040904B0', [\n"
        " StringStruct('CompanyName', 'Sumīre'), StringStruct('FileDescription', 'Sumīre image finishing'),\n"
        f" StringStruct('FileVersion', '{DISPLAY_VERSION}'), StringStruct('ProductVersion', '{DISPLAY_VERSION}'),\n"
        " StringStruct('ProductName', 'Sumīre'), StringStruct('OriginalFilename', 'sumire.exe'),\n"
        " StringStruct('LegalCopyright', 'Copyright (c) 2026 marc2825; MIT License')])]), VarFileInfo([VarStruct('Translation', [1033,1200])])])\n",
        encoding="utf-8")
    inventory = {"Sumīre": DISPLAY_VERSION, "package_version": __version__, "Python": platform.python_version(),
                 "platform": platform.platform()}
    for package in ("PySide6-Essentials", "shiboken6", "Pillow", "PyInstaller", "pyinstaller-hooks-contrib"):
        inventory[package] = importlib.metadata.version(package)
    (build / "build-info.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    return inventory


if __name__ == "__main__":
    prepare()
    print("Prepared Sumīre icon, executable version and build-info.json")
