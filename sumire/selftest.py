"""Check a built copy of Sumīre without showing a window or touching the user's data.

    sumire.exe --self-test FOLDER

Writes FOLDER/self-test.json and one screenshot per interface language, and
exits with 0 when every check passed. Settings, records and temporary files
stay inside FOLDER; the Explorer menu is only computed, never registered.
Used to verify the Windows distribution. Nothing is sent anywhere.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import time
import traceback

LANGUAGE_CODES = ("ja", "en", "zh_CN")
SCALES = (1.25, 1.5)
KANA = re.compile("[぀-ヿ]")
SECRET_TEXT = "synthetic self-test prompt"


def redact(value):
    """Reports may be shared: the user's home folder and name are replaced."""
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if not isinstance(value, str):
        return value
    home = str(Path.home())
    for text in {home, home.replace("\\", "/")}:
        if len(text) > 3:
            value = value.replace(text, "%USERPROFILE%")
    user = os.environ.get("USERNAME") or os.environ.get("USER")
    return value.replace(user, "<user>") if user and len(user) > 2 else value


def isolate(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    os.environ["SUMIRE_SETTINGS_FILE"] = str(folder / "profile" / "settings.json")
    temp = folder / "temp"
    temp.mkdir(exist_ok=True)
    for name in ("TEMP", "TMP", "TMPDIR"):
        os.environ[name] = str(temp)
    tempfile.tempdir = str(temp)


class Checks:
    def __init__(self):
        self.results = {}

    def run(self, name, function):
        try:
            self.results[name] = {"ok": True, "detail": function()}
        except Exception as error:  # every failure is reported, not raised
            self.results[name] = {"ok": False, "detail": f"{type(error).__name__}: {error}",
                                  "trace": traceback.format_exc(limit=8)}

    def passed(self):
        return all(result["ok"] for result in self.results.values())


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sample_image(size=(96, 64)):
    from PIL import Image
    image = Image.new("RGBA", size)
    image.putdata([((x * 19 + y * 3) % 256, (y * 29) % 256, (x * 7 + y * 11) % 256, 255)
                   for y in range(size[1]) for x in range(size[0])])
    return image


def with_stealth(image):
    """NovelAI's alpha carrier (column-first least significant bits), as in the tests."""
    payload = gzip.compress(json.dumps({"Comment": SECRET_TEXT}).encode(), mtime=0)
    data = b"stealth_pngcomp" + (len(payload) * 8).to_bytes(4, "big") + payload
    pixels = image.load()
    for index, bit in enumerate(int(bit) for byte in data for bit in f"{byte:08b}"):
        x, y = divmod(index, image.height)
        red, green, blue, alpha = pixels[x, y]
        pixels[x, y] = (red, green, blue, (alpha & 254) | bit)
    return image


# --- checks in the main process ---------------------------------------------------

def environment():
    import PIL
    import PySide6
    from PySide6.QtCore import qVersion
    from PySide6.QtWidgets import QApplication
    from . import DISPLAY_VERSION, __version__
    return {"sumire": DISPLAY_VERSION, "package_version": __version__, "frozen": bool(getattr(sys, "frozen", False)),
            "executable": sys.executable, "python": platform.python_version(), "qt": qVersion(),
            "pyside6": PySide6.__version__, "pillow": PIL.__version__, "qt_platform": QApplication.platformName(),
            "os": platform.platform()}


def fonts():
    from PySide6.QtGui import QFontDatabase
    from .theme import install_fonts
    families = install_fonts()
    require(families == ["Noto Sans JP"], f"bundled font not registered: {families}")
    styles = QFontDatabase.styles("Noto Sans JP")
    require({"Regular", "Bold"} <= set(styles), f"styles: {styles}")
    return {"families": families, "styles": styles}


def image_formats():
    import importlib.util
    from PIL import Image, features
    from . import convert
    results = {}
    for format in ("PNG", "JPEG", "WEBP", "AVIF", "BMP", "TIFF", "GIF"):
        encoding = convert.Encoding(format=format, quality=90 if format in {"JPEG", "WEBP", "AVIF"} else None)
        raw = convert.encode(sample_image(), encoding)  # also decodes and checks the file
        with Image.open(io.BytesIO(raw)) as decoded:
            decoded.load()
            results[format] = {"bytes": len(raw), "decoded_as": decoded.format, "size": list(decoded.size)}
    require(features.check("avif"), "AVIF support is missing")
    results["libavif"] = features.version("avif")
    results["webp"] = features.version("webp")
    results["jpeg"] = features.version("jpg")
    results["heif_writable"] = convert.writable("HEIF")
    require(importlib.util.find_spec("pillow_heif") is None and importlib.util.find_spec("pi_heif") is None,
            "a HEIF plugin is bundled although HEIC is not distributed")
    return results


def metadata_removal(folder: Path):
    from PIL import Image, PngImagePlugin
    from . import export, metadata, stealth
    source = folder / "metadata-source.png"
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", SECRET_TEXT)
    with_stealth(sample_image((120, 80))).save(source, pnginfo=info)
    found = metadata.inspect_metadata(source)
    with Image.open(source) as image:
        image.load()
        require(stealth.stealth_channels(image) == ("alpha",), "the synthetic Stealth PNGInfo was not detected")
        pixels = image.convert("RGBA")
    target = folder / "metadata-removed.png"
    export.save_image(stealth.remove_stealth(pixels), target, source=source, format="PNG")
    export.verify_export(target, (120, 80), "PNG")
    with Image.open(target) as saved:
        saved.load()
        require(not saved.info.get("parameters") and not stealth.stealth_channels(saved), "metadata left after saving")
    require(SECRET_TEXT.encode() not in target.read_bytes(), "the prompt text is still in the file")
    return {"found_before": sorted(found) if not isinstance(found, dict) else found, "after": "none"}


def qt_translations():
    from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QTranslator
    folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    results = {"folder": folder}
    for code, locale in (("ja", QLocale(QLocale.Language.Japanese, QLocale.Country.Japan)),
                         ("zh_CN", QLocale(QLocale.Language.Chinese, QLocale.Country.China))):
        translator = QTranslator()
        require(translator.load(locale, "qtbase", "_", folder), f"qtbase_{code}.qm is missing")
        QCoreApplication.installTranslator(translator)
        cancel = QCoreApplication.translate("QPlatformTheme", "Cancel")
        QCoreApplication.removeTranslator(translator)
        require(cancel != "Cancel", f"{code}: standard buttons are not translated")
        results[code] = cancel
    return results


def texts_and_help():
    from importlib import resources
    from . import help as help_module
    from . import i18n
    results = {}
    for code in LANGUAGE_CODES:
        catalog = i18n.load_catalog(code)
        require(code == "ja" or len(catalog) > 1000, f"{code}: interface catalog is missing")
        documents = {}
        for topic in help_module.TOPICS:
            path = help_module.help_folder(code)
            text = resources.files("sumire").joinpath(*path, topic.filename).read_text(encoding="utf-8")
            require(text.startswith("#"), f"{code}/{topic.filename} is not a help page")
            documents[topic.filename] = len(text)
        results[code] = {"catalog_entries": len(catalog), "help_pages": documents}
    return results


def explorer_menu():
    from . import explorer
    if os.name != "nt":
        return "not Windows: skipped"
    launcher, bridge = explorer.windows_launcher()
    require(bridge is None, "a frozen build registers itself directly")
    if getattr(sys, "frozen", False):
        require(Path(launcher[0]) == Path(sys.executable).resolve() and launcher[1:] == ["--open"], launcher)
    entries = explorer.context_entries(launcher)
    commands = sorted({values["command"] for values in entries.values()})
    require(all(launcher[0] in command for command in commands), commands)
    return {"launcher": launcher, "verbs": len(entries), "commands": commands, "registered": False}


def loaded_libraries():
    """Which Qt and image libraries this process loaded, and from where (Windows only)."""
    if os.name != "nt":
        return "not Windows: skipped"
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    process = kernel32.GetCurrentProcess()
    psapi = ctypes.WinDLL("psapi")
    psapi.EnumProcessModules.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD,
                                         ctypes.POINTER(wintypes.DWORD)]
    psapi.GetModuleFileNameExW.argtypes = [wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    modules = (wintypes.HMODULE * 2048)()
    needed = wintypes.DWORD()
    require(psapi.EnumProcessModules(process, modules, ctypes.sizeof(modules), ctypes.byref(needed)), "EnumProcessModules")
    paths = []
    buffer = ctypes.create_unicode_buffer(32768)
    for handle in modules[:needed.value // ctypes.sizeof(wintypes.HMODULE)]:
        if psapi.GetModuleFileNameExW(process, handle, buffer, len(buffer)):
            paths.append(Path(buffer.value))
    base = Path(sys.executable).resolve().parent
    interesting = [path for path in paths if re.match(r"(?i)(qt6|pyside6|shiboken6|q\w+\.dll$|python3|_avif|_webp|_imaging|lib)", path.name)]
    qt = [path for path in interesting if path.name.lower().startswith(("qt6", "pyside6", "shiboken6"))]
    require(qt, "no Qt library is loaded")
    outside = [str(path) for path in qt if getattr(sys, "frozen", False) and not path.resolve().is_relative_to(base)]
    require(not outside, f"Qt loaded from outside the distribution: {outside}")

    def describe(path):
        try:
            name = str(path.resolve().relative_to(base))
        except ValueError:
            name = str(path)
        return {"file": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return {"base": str(base), "modules": [describe(path) for path in sorted(interesting, key=lambda p: str(p).lower())]}


def interfaces(folder: Path):
    results, failed = {}, []
    runs = [(code, None) for code in LANGUAGE_CODES] + [("ja", scale) for scale in SCALES]
    for code, scale in runs:
        name = code if scale is None else f"{code}-{scale:g}x"
        command = ([sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "sumire"])
        command += ["--self-test-ui", code, str(folder / f"ui-{name}")]
        environment = dict(os.environ)
        if scale is not None:
            environment["QT_SCALE_FACTOR"] = str(scale)
        try:
            subprocess.run(command, env=environment, timeout=180, check=False)
            report = json.loads((folder / f"ui-{name}" / "interface.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            report = {"ok": False, "error": f"{type(error).__name__}: {error}"}
        results[name] = report
        if not report.get("ok"):
            failed.append(name)
    require(not failed, f"interface checks failed: {failed}")
    return results


def run(folder: Path) -> int:
    folder = folder.resolve()
    isolate(folder)
    from PySide6.QtWidgets import QApplication
    app = QApplication([sys.argv[0]])
    checks = Checks()
    checks.run("environment", environment)
    checks.run("fonts", fonts)
    checks.run("image_formats", image_formats)
    checks.run("metadata_removal", lambda: metadata_removal(folder / "temp"))
    checks.run("qt_translations", qt_translations)
    checks.run("texts_and_help", texts_and_help)
    checks.run("explorer_menu", explorer_menu)
    checks.run("loaded_libraries", loaded_libraries)
    checks.run("interfaces", lambda: interfaces(folder))
    report = {"passed": checks.passed(), "finished": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "checks": checks.results}
    (folder / "self-test.json").write_text(json.dumps(redact(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    del app
    return 0 if report["passed"] else 1


# --- one interface language, in its own process --------------------------------------

def run_interface(code: str, folder: Path) -> int:
    """Texts are made when the interface modules load, so each language needs a fresh process."""
    folder = folder.resolve()
    isolate(folder)
    report = {"language": code, "ok": False}
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QFontInfo
        from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QWidget
        app = QApplication([sys.argv[0]])
        from . import i18n
        i18n.set_language(code)
        from .__main__ import configure  # the same set-up as a normal start
        translator, report["bundled_fonts"] = configure(app)
        report["qt_translation"] = translator is not None
        report["style"] = app.style().name()
        from . import workspace_tabs
        workspace_tabs.QUIT_CONFIRMATION["enabled"] = False
        images = folder / "images"
        images.mkdir(exist_ok=True)
        sample_image((640, 420)).save(images / "画像 01.png")  # not kana: those are counted below
        window = workspace_tabs.WorkspaceWindow()
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.resize(1280, 800)
        window.show()
        window.open_inputs([str(images)])
        page = window.current_workspace()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
            if page is not None and page.document is not None and page.canvas.ready:
                break
        for _ in range(30):
            app.processEvents()
            time.sleep(0.01)
        widgets = [widget for widget in window.findChildren(QWidget)
                   if isinstance(widget, (QAbstractButton, QLabel)) and widget.isVisible() and widget.text()]
        kana = sorted({widget.text() for widget in widgets if KANA.search(widget.text())}) if code != "ja" else []
        clipped = []
        for widget in widgets:
            text = widget.text().replace("&&", "\0").replace("&", "").replace("\0", "&")
            if isinstance(widget, QAbstractButton) and "\n" not in text:
                needed = widget.fontMetrics().horizontalAdvance(text) + (widget.iconSize().width() if not widget.icon().isNull() else 0)
                if needed > widget.contentsRect().width():
                    clipped.append({"text": text, "needed": needed, "width": widget.contentsRect().width()})
        label = next((widget for widget in widgets if isinstance(widget, QLabel)), None)
        report.update({
            "image_loaded": page is not None and page.document is not None,
            "font_in_use": QFontInfo(label.font()).family() if label else None,
            "device_pixel_ratio": window.devicePixelRatioF(),
            "visible_texts": len(widgets), "kana_left": kana[:20], "buttons_narrower_than_text": clipped[:30],
        })
        window.grab().save(str(folder / f"interface-{code}.png"))
        report["ok"] = bool(report["image_loaded"] and not kana and report["bundled_fonts"] == ["Noto Sans JP"]
                            and (code == "en" or report["qt_translation"]))
        window.close()
    except Exception as error:  # reported to the parent
        report["error"] = f"{type(error).__name__}: {error}"
        report["trace"] = traceback.format_exc(limit=8)
    (folder / "interface.json").write_text(json.dumps(redact(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


def main(arguments) -> int:
    if arguments[:1] == ["--self-test"] and len(arguments) == 2:
        return run(Path(arguments[1]))
    if arguments[:1] == ["--self-test-ui"] and len(arguments) == 3:
        return run_interface(arguments[1], Path(arguments[2]))
    print("usage: sumire --self-test FOLDER", file=sys.stderr)
    return 2
