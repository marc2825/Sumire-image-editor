"""Collect the source code of the Qt and PySide6 libraries in the Windows distribution.

    python -m scripts.fetch_qt_sources                       # download, check, pack
    python -m scripts.fetch_qt_sources --notices-only        # only rewrite licenses/Qt/THIRD_PARTY.md

Downloads the official source archives of the versions in
scripts/windows-build-requirements.txt from download.qt.io, checks each SHA-256
against the value Qt publishes (pinned below), and writes
dist/Sumire-v<version>-qt-pyside6-source.zip. Offer that file
from the same place as the distribution ZIP (see QT_REPLACEMENT.md).

It also reads the qt_attribution.json files in those archives and writes
licenses/Qt/THIRD_PARTY.md and the licence texts they refer to
(licenses/Qt/third-party/), which go into the distribution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import urllib.request
import zipfile

from sumire import DISPLAY_VERSION

ROOT = Path(__file__).resolve().parents[1]
QT = "6.12.0"
QT_URL = "https://download.qt.io/official_releases/qt/6.12/6.12.0/submodules/"
PYSIDE_URL = "https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/"
# SHA-256 values as published on download.qt.io (the .mirrorlist pages), 2026-11-13.
ARCHIVES = {
    "qtbase-everywhere-src-6.12.0.tar.xz": (
        QT_URL, "a951bd163c7b80fc6b8c88d7668fb56abf91c152373e13c10666763238131307",
        "Qt6Core.dll, Qt6Gui.dll, Qt6Widgets.dll, Qt6Network.dll; platforms, styles, gif/ico/jpeg image format plugins"),
    "qtsvg-everywhere-src-6.12.0.tar.xz": (
        QT_URL, "e4ab39534ec97987b1b9b60ef7f4d3253d5912a69f8c713a01753174a4029331",
        "Qt6Svg.dll; qsvg and qsvgicon plugins"),
    "qtimageformats-everywhere-src-6.12.0.tar.xz": (
        QT_URL, "0943132b5db8de6b6a7f1d162682173e8763c7ed94e80fd39113292845f67762",
        "icns, tga, tiff, wbmp and webp image format plugins"),
    "qttranslations-everywhere-src-6.12.0.tar.xz": (
        QT_URL, "85929c0c30d6f273f23bd879bb69803ea17b010ab73cab2f8abf95357f6f6bbb",
        "translations/*.qm"),
    "pyside-setup-everywhere-src-6.12.0.tar.xz": (
        PYSIDE_URL, "099c1a597cf33c1b000e11cf68a0b82d216fb802bf81726efc720394f10c7751",
        "PySide6 (QtCore.pyd, QtGui.pyd, QtWidgets.pyd, QtNetwork.pyd, pyside6.abi3.dll, Python modules) and shiboken6"),
}
NAME = f"Sumire-v{DISPLAY_VERSION}-qt-pyside6-source"


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    for name, (base, expected, _) in ARCHIVES.items():
        path = folder / name
        if not path.is_file() or sha256(path) != expected:
            partial = path.with_suffix(path.suffix + ".part")
            with urllib.request.urlopen(base + name, timeout=120) as response, open(partial, "wb") as stream:
                shutil.copyfileobj(response, stream, 1 << 20)
            if sha256(partial) != expected:
                partial.unlink()
                raise ValueError(f"{name}: SHA-256 differs from the value Qt publishes.")
            partial.replace(path)
    return folder


def attributions(folder: Path):
    """Every qt_attribution.json entry and the SPDX licence texts they name."""
    entries, texts = [], {}
    for name in ARCHIVES:
        with tarfile.open(folder / name, "r:xz") as archive:
            members = {member.name: member for member in archive if member.isfile()}
            top = name.removesuffix(".tar.xz")
            for path, member in sorted(members.items()):
                if not path.endswith("qt_attribution.json"):
                    continue
                try:
                    data = json.loads(archive.extractfile(member).read().decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    continue
                for item in data if isinstance(data, list) else [data]:
                    if isinstance(item, dict) and item.get("Name"):
                        entries.append({"module": top.split("-everywhere")[0], "path": path.split("/", 1)[1].rsplit("/", 1)[0],
                                        **{key: item.get(key) for key in ("Name", "Version", "License", "LicenseId",
                                                                          "Copyright", "QtUsage", "Homepage")}})
            for path, member in members.items():
                parts = path.split("/")
                if len(parts) == 3 and parts[1] == "LICENSES" and parts[2].endswith(".txt"):
                    texts.setdefault(parts[2], archive.extractfile(member).read())
    return entries, texts


def write_notices(entries, texts, target: Path):
    target.mkdir(parents=True, exist_ok=True)
    folder = target / "third-party"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir()
    used = set()
    lines = [
        "# Third-party components in Qt and PySide6 6.12.0",
        "",
        "Generated by `python -m scripts.fetch_qt_sources --notices-only` from the `qt_attribution.json` files in",
        "the official source archives of Qt 6.12.0 (qtbase, qtsvg, qtimageformats, qttranslations) and",
        "pyside-setup 6.12.0. It lists every component those sources declare; not all of them are compiled",
        "into the Windows libraries in this distribution (some are for other platforms or modules).",
        "The licence texts are in `third-party/`.",
        "",
    ]
    for entry in sorted(entries, key=lambda item: (item["module"], item["Name"].casefold(), item["path"])):
        identifiers = [part.strip("() ") for part in str(entry.get("LicenseId") or "").replace(" OR ", " ").replace(" AND ", " ").replace(" WITH ", " ").split()]
        for identifier in identifiers:
            if f"{identifier}.txt" in texts:
                used.add(f"{identifier}.txt")
        copyright = entry.get("Copyright") or ""
        if isinstance(copyright, list):
            copyright = "\n".join(copyright)
        lines += [f"## {entry['Name']}" + (f" {entry['Version']}" if entry.get("Version") else ""),
                  "",
                  f"- Qt module: {entry['module']} (`{entry['path']}`)",
                  f"- License: {entry.get('License') or '-'} (`{entry.get('LicenseId') or '-'}`)"]
        if entry.get("Homepage"):
            lines.append(f"- Homepage: {entry['Homepage']}")
        if copyright.strip():
            lines += ["", "```text", copyright.strip(), "```"]
        lines.append("")
    for name in sorted(used):
        (folder / name).write_bytes(texts[name])
    (target / "THIRD_PARTY.md").write_text("\n".join(lines), encoding="utf-8")
    return len(entries), sorted(used)


def pack(folder: Path, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    readme = [
        f"Source code of the Qt and PySide6 libraries in Sumire {DISPLAY_VERSION} for Windows",
        "",
        "The Windows distribution (Sumire-v{0}-win64.zip) contains unmodified binaries of".format(DISPLAY_VERSION),
        f"Qt {QT} and PySide6/shiboken6 {QT} from the PySide6-Essentials and shiboken6 wheels on PyPI.",
        "These are the official source archives of the same versions, as published at download.qt.io,",
        "under the GNU LGPL version 3 (with other licences for some parts; see each archive).",
        "",
        "Archive | used for | SHA-256",
    ]
    for name, (base, expected, usage) in ARCHIVES.items():
        readme.append(f"{name} | {usage} | {expected}")
    readme += ["", "Downloaded from:", *[base + name for name, (base, _, _) in ARCHIVES.items()],
               "", "How to replace the libraries in the distribution: QT_REPLACEMENT.md in the distribution or the source."]
    archive = output / f"{NAME}.zip"
    partial = archive.with_suffix(".zip.part")
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_STORED) as bundle:
        bundle.writestr(f"{NAME}/README.txt", "\n".join(readme) + "\n")
        bundle.writestr(f"{NAME}/SHA256SUMS.txt", "".join(f"{expected}  {name}\n" for name, (_, expected, _) in ARCHIVES.items()))
        for name in ARCHIVES:
            bundle.write(folder / name, f"{NAME}/{name}")
    partial.replace(archive)
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--downloads", type=Path, default=ROOT / "build" / "qt-sources")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--notices-only", action="store_true")
    args = parser.parse_args()
    folder = download(args.downloads)
    count, used = write_notices(*attributions(folder), ROOT / "licenses" / "Qt")
    print(f"licenses/Qt/THIRD_PARTY.md: {count} components, {len(used)} licence texts")
    if not args.notices_only:
        archive = pack(folder, args.output)
        print(f"{archive.relative_to(ROOT)}: {archive.stat().st_size:,} bytes, SHA-256 {sha256(archive)}")


if __name__ == "__main__":
    main()
