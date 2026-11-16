"""Pack the onedir Windows build, documents and licences into Sumire-v<version>-win64.zip.

Run on Windows with the Python environment that made the build (build_windows.ps1
does both). The result:

    dist/Sumire-v1.2.0-win64/            the folder users get
        sumire.exe, _internal/            program, Python, Qt (replaceable DLLs), fonts
        README-Windows*.txt, LICENSE, THIRD_PARTY_NOTICES.md, QT_REPLACEMENT.md, ...
        licenses/                         licence texts of everything bundled
        SHA256SUMS.txt                    checksums of the files above (not of the ZIP)
    dist/Sumire-v1.2.0-win64.zip
    dist/Sumire-v1.2.0-win64.zip.sha256  checksum of the ZIP, kept outside it
"""
from __future__ import annotations

import ctypes
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import tomllib
import zipfile

from sumire import DISPLAY_VERSION, __version__

ROOT = Path(__file__).resolve().parents[1]
NAME = f"Sumire-v{DISPLAY_VERSION}-win64"
# The full VALIDATION.md log stays in the source repository; users get docs/VALIDATION_SUMMARY.md.
DOCS = ("LICENSE", "THIRD_PARTY_NOTICES.md", "QT_REPLACEMENT.md", "README.md", "README.en.md", "README.zh-CN.md",
        "README-Windows.txt", "README-Windows.en.txt", "README-Windows.zh-CN.txt", "CHANGELOG.md", "SECURITY.md")
PACKAGES = ("PySide6-Essentials", "shiboken6", "Pillow", "PyInstaller")
# Files the distribution cannot work without, relative to the onedir folder.
REQUIRED = ("sumire.exe", "_internal/base_library.zip", "_internal/PySide6/Qt6Core.dll", "_internal/PySide6/Qt6Gui.dll",
            "_internal/PySide6/Qt6Widgets.dll", "_internal/PySide6/plugins/platforms/qwindows.dll",
            "_internal/PySide6/translations/qtbase_ja.qm", "_internal/PySide6/translations/qtbase_zh_CN.qm",
            "_internal/sumire/fonts/NotoSansJP-Regular.otf", "_internal/sumire/fonts/NotoSansJP-Bold.otf",
            "_internal/sumire/fonts/OFL.txt", "_internal/sumire/locales/en.json", "_internal/sumire/locales/zh_CN.json",
            "_internal/sumire/help_docs/FAQ.md")
UNREGISTER_CMD = ('@echo off\r\n'
                  'rem Removes "Open with Sumire" from the right-click menu. Run it before deleting this folder.\r\n'
                  '"%~dp0sumire.exe" --unregister\r\n')
# Collected by PyInstaller's Qt hooks but never used: Sumīre makes no network connections and
# draws without OpenGL. Leaving them out keeps network code (TLS backends, TUIO input over UDP)
# and the 20 MB software OpenGL (Mesa) out of the distribution.
PRUNE = ("_internal/PySide6/plugins/tls", "_internal/PySide6/plugins/networkinformation",
         "_internal/PySide6/plugins/generic", "_internal/PySide6/opengl32sw.dll")
# HEIC is not distributed (licensing); a build environment that has a HEIF plugin must not leak it.
FORBIDDEN = re.compile(r"(?i)(pillow_heif|pi_heif|libheif|QtWebEngine|Qt6WebEngine)")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def executable_version(path):
    api = ctypes.windll.version
    api.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
    api.GetFileVersionInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    api.VerQueryValueW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                  ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint)]
    size = api.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        raise ValueError("The executable has no Windows version resource.")
    data = ctypes.create_string_buffer(size)
    pointer, length = ctypes.c_void_p(), ctypes.c_uint()
    if not api.GetFileVersionInfoW(str(path), 0, size, data) or not api.VerQueryValueW(
            data, "\\", ctypes.byref(pointer), ctypes.byref(length)) or length.value < 52:
        raise ValueError("The executable version resource is invalid.")
    fields = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32))
    ms, ls = fields[2], fields[3]
    text = ctypes.c_void_p()
    if not api.VerQueryValueW(data, "\\StringFileInfo\\040904B0\\ProductVersion", ctypes.byref(text), ctypes.byref(length)):
        raise ValueError("The executable has no product version text.")
    return (ms >> 16, ms & 0xffff, ls >> 16, ls & 0xffff), ctypes.wstring_at(text.value).rstrip("\0")


def pinned_versions(root):
    pins = {}
    for line in (root / "scripts/windows-build-requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            name, version = line.split("==")
            pins[name.strip().lower()] = version.strip()
    return pins


def copy_licenses(target):
    """Licence texts shipped with Python, Pillow and PyInstaller.

    Qt's, PySide6's and shiboken6's come from licenses/Qt: their wheels only carry a
    reference to the commercial licence, which this distribution does not use.
    """
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise ValueError("Python LICENSE.txt was not found in the build runtime.")
    folder = target / "Python"
    folder.mkdir(parents=True)
    shutil.copyfile(python_license, folder / "LICENSE.txt")
    for package in ("Pillow", "PyInstaller"):
        distribution = importlib.metadata.distribution(package)
        files = [path for path in distribution.files or () if any(
            part.lower() in ("licenses", "license", "copying", "copyright", "notice")
            or part.lower().startswith(("license.", "copying.", "copyright.", "notice."))
            for part in path.parts)]
        for relative in files:
            source = Path(distribution.locate_file(relative))
            if not source.is_file() or ".." in relative.parts:
                raise ValueError(f"Invalid license file for {package}.")
            destination = target / package / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)


def check_build(root, build):
    source_version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if source_version != __version__:
        raise ValueError("pyproject.toml and sumire/__init__.py versions differ.")
    inventory = json.loads((root / "build/build-info.json").read_text(encoding="utf-8"))
    if inventory.get("Sumīre") != DISPLAY_VERSION:
        raise ValueError("Source and build versions differ; rebuild the executable before packaging.")
    for name in ("README-Windows.txt", "README-Windows.en.txt", "README-Windows.zh-CN.txt"):
        first = (root / name).read_text(encoding="utf-8-sig").splitlines()[0]
        if first != f"Sumīre {DISPLAY_VERSION} / Windows 11 x64":
            raise ValueError(f"The first line of {name} does not show {DISPLAY_VERSION}.")
    pins = pinned_versions(root)
    for name in PACKAGES:
        installed = importlib.metadata.version(name)
        if inventory.get(name) != installed:
            raise ValueError(f"Build and packaging environments differ: {name}")
        if pins.get(name.lower()) != installed:
            raise ValueError(f"{name} {installed} is not the pinned version {pins.get(name.lower())}.")
    if inventory.get("Python") != sys.version.split()[0]:
        raise ValueError("Build and packaging Python versions differ.")
    missing = [name for name in REQUIRED if not (build / name).is_file()]
    if missing:
        raise ValueError("The build lacks: " + ", ".join(missing))
    leaked = sorted(str(path.relative_to(build)) for path in build.rglob("*") if FORBIDDEN.search(path.name))
    if leaked:
        raise ValueError("The build contains files that are not distributed: " + ", ".join(leaked[:10]))
    if not list((build / "_internal/PIL").glob("_avif*.pyd")):
        raise ValueError("Pillow's AVIF module is missing from the build.")
    # Check the actual PE version too; a current JSON file must not disguise an old executable.
    numbers, text = executable_version(build / "sumire.exe")
    if numbers != tuple(map(int, __version__.split("."))) + (0,) or text != DISPLAY_VERSION:
        raise ValueError("Executable version differs from source; rebuild before packaging.")
    return inventory


def package(root=ROOT):
    if os.name != "nt":
        raise ValueError("Package on Windows using the same Python environment as the executable build.")
    root = root.resolve()
    dist = root / "dist"
    build = dist / "sumire"
    inventory = check_build(root, build)
    with tempfile.TemporaryDirectory(prefix="sumire-package-", dir=dist) as temporary:
        folder = Path(temporary) / NAME
        shutil.copytree(build, folder)
        for name in PRUNE:
            path = folder / name
            shutil.rmtree(path) if path.is_dir() else path.unlink()
        for filename in DOCS:
            shutil.copyfile(root / filename, folder / filename)
        shutil.copyfile(root / "build/build-info.json", folder / "build-info.json")
        # Double-click before deleting the folder: removes the right-click entry (README-Windows, "アンインストール").
        (folder / "unregister-context-menu.cmd").write_bytes(UNREGISTER_CMD.encode("ascii"))
        # README.md links to the help pages; the app reads its own copy inside _internal.
        shutil.copytree(root / "sumire/help_docs", folder / "sumire/help_docs")
        shutil.copytree(root / "docs", folder / "docs")
        copy_licenses(folder / "licenses")
        shutil.copytree(root / "licenses", folder / "licenses", dirs_exist_ok=True)
        files = sorted((path for path in folder.rglob("*") if path.is_file()), key=lambda p: p.relative_to(folder).as_posix())
        checksums = "".join(f"{sha256(path)}  {path.relative_to(folder).as_posix()}\n" for path in files)
        (folder / "SHA256SUMS.txt").write_text(checksums, encoding="utf-8")
        archive = Path(temporary) / (NAME + ".zip")
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for path in sorted(folder.rglob("*"), key=lambda p: p.relative_to(folder).as_posix()):
                if path.is_file():
                    bundle.write(path, path.relative_to(folder.parent).as_posix())
        target = dist / NAME
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(folder), target)
        os.replace(archive, dist / archive.name)
    archive = dist / (NAME + ".zip")
    (dist / (NAME + ".zip.sha256")).write_text(f"{sha256(archive)}  {archive.name}\n", encoding="utf-8")
    return archive, inventory


if __name__ == "__main__":
    archive, inventory = package()
    print(f"Packaged: {archive.name} ({archive.stat().st_size:,} bytes)")
