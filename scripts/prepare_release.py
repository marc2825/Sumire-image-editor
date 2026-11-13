"""Generate the established Sumīre icon, Windows version resource and build inventory."""
import importlib.metadata
import json
from pathlib import Path
import platform

from PIL import Image, ImageDraw
from sumire import DISPLAY_VERSION, __version__

ROOT = Path(__file__).resolve().parents[1]


def prepare(root=ROOT):
    assets, build = root / "assets", root / "build"
    assets.mkdir(exist_ok=True)
    build.mkdir(exist_ok=True)
    icon = Image.new("RGBA", (256, 256), "#25362e")
    draw = ImageDraw.Draw(icon)
    for x, y, color in ((56, 56, "#a8dfc2"), (136, 56, "#7da78f"), (56, 136, "#648873"), (136, 136, "#a8dfc2")):
        draw.rectangle((x, y, x + 63, y + 63), fill=color)
    icon.save(assets / "sumire.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
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
