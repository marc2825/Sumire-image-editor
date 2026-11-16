"""Documents that describe the current release agree with its version and the pinned packages.

Validation records (VALIDATION_SUMMARY.md, the 「確かめたこと」 of QT_REPLACEMENT.md) and CHANGELOG.md
keep the versions they were written for and are not checked here.
"""
import re
from pathlib import Path

from sumire import DISPLAY_VERSION

ROOT = Path(__file__).resolve().parents[1]
# Every file that names the distribution of this source: they must all name this version.
CURRENT = ("QT_REPLACEMENT.md", "THIRD_PARTY_NOTICES.md", "docs/DEVELOPMENT.md", "scripts/package_windows.py",
           "scripts/verify_distribution.py", "scripts/smoke_windows_exe.py")
ZIP = re.compile(r"Sumire-v(\d+\.\d+\.\d+)-(?:win64|qt-pyside6-source)")


def pins():
    found = {}
    for line in (ROOT / "scripts/windows-build-requirements.txt").read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s#]+)", line.strip())
        if match:
            found[match.group(1).lower()] = match.group(2)
    return found


def text(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_release_documents_name_this_version():
    for name in CURRENT:
        versions = set(ZIP.findall(text(name)))
        assert versions <= {DISPLAY_VERSION}, (name, versions)
    assert ZIP.search(text("QT_REPLACEMENT.md")) and ZIP.search(text("THIRD_PARTY_NOTICES.md"))
    assert f"## Windows版に入っているもの（{DISPLAY_VERSION}）" in text("THIRD_PARTY_NOTICES.md")
    assert f"同じ `{DISPLAY_VERSION}`" in text("docs/DEVELOPMENT.md")
    assert f"数値が {DISPLAY_VERSION}.0、文字列が `{DISPLAY_VERSION}`" in text("docs/DEVELOPMENT.md")


def test_licence_notices_name_the_pinned_packages():
    pinned = pins()
    notices = text("THIRD_PARTY_NOTICES.md")
    qt = pinned["pyside6-essentials"]
    assert pinned["shiboken6"] == qt
    assert re.search(rf"\| Qt（[^|]*\| {re.escape(qt)} \| GNU LGPL v3", notices)
    assert re.search(rf"\| PySide6・shiboken6 \| {re.escape(qt)} \| GNU LGPL v3", notices)
    assert re.search(rf"\| Pillow \| {re.escape(pinned['pillow'])} \|", notices)
    assert re.search(rf"\| PyInstaller のブートローダー \| {re.escape(pinned['pyinstaller'])} \|", notices)
    replacement = text("QT_REPLACEMENT.md")
    assert f"PySide6-Essentials {qt}・shiboken6 {qt}" in replacement and f"Qt {qt}" in replacement


def test_qt_source_archives_are_the_pinned_qt():
    """The LGPL source offer (fetch_qt_sources) is for exactly the Qt in the distribution."""
    from scripts import fetch_qt_sources
    qt = pins()["pyside6-essentials"]
    assert fetch_qt_sources.QT == qt
    assert all(qt in name for name in fetch_qt_sources.ARCHIVES)
    for name in ("LGPL-3.0-only.txt", "GPL-3.0-only.txt", "THIRD_PARTY.md"):
        assert (ROOT / "licenses" / "Qt" / name).is_file(), name
