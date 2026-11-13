"""The release number agrees everywhere, and the bundled font loads with a fallback."""
import json
import re
import tomllib
from pathlib import Path

from PySide6.QtGui import QRawFont

from sumire import DISPLAY_VERSION, __version__, i18n, theme

ROOT = Path(__file__).resolve().parents[1]


def test_display_and_package_versions_are_the_same_number():
    assert tuple(map(int, DISPLAY_VERSION.split("."))) == tuple(map(int, __version__.split(".")))
    assert tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"] == __version__
    assert re.fullmatch(r"\d+\.\d{2}\.\d+", DISPLAY_VERSION)


def test_readmes_and_changelog_show_the_display_version():
    for name in ("README.md", "README.en.md", "README.zh-CN.md"):
        assert f"badge/version-{DISPLAY_VERSION}-" in (ROOT / name).read_text(encoding="utf-8"), name
    for name in ("README-Windows.txt", "README-Windows.en.txt", "README-Windows.zh-CN.txt"):
        first = (ROOT / name).read_text(encoding="utf-8-sig").splitlines()[0]
        assert first == f"Sumīre {DISPLAY_VERSION} / Windows 11 x64", name
    assert f"\n## {DISPLAY_VERSION} " in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_bundled_font_and_its_licence_are_present():
    folder = ROOT / "sumire" / "fonts"
    assert sorted(path.name for path in folder.iterdir()) == ["NotoSansJP-Bold.otf", "NotoSansJP-Regular.otf", "OFL.txt"]
    assert "SIL OPEN FONT LICENSE Version 1.1" in (folder / "OFL.txt").read_text(encoding="utf-8")
    assert (ROOT / "licenses" / "NotoSansJP" / "OFL.txt").read_bytes() == (folder / "OFL.txt").read_bytes()


def test_bundled_font_is_registered(qapp):
    from PySide6.QtGui import QFontDatabase
    assert theme.install_fonts() == ["Noto Sans JP"]
    assert {"Regular", "Bold"} <= set(QFontDatabase.styles("Noto Sans JP"))


def test_missing_font_files_fall_back_to_the_system_fonts(qapp, monkeypatch):
    monkeypatch.setattr(theme, "BUNDLED_FONTS", ("missing.otf",))
    assert theme.install_fonts() == []
    assert "'Yu Gothic UI'" in theme.font_family()  # the style sheet still names the Windows fonts


def interface_characters(code):
    from scripts.i18n_check import code_keys
    texts = code_keys() if code == "ja" else json.loads(
        (ROOT / "sumire" / "locales" / f"{code}.json").read_text(encoding="utf-8")).values()
    return {character for text in texts for character in text if not character.isspace()}


def test_japanese_and_english_texts_are_covered_by_the_bundled_font(qapp):
    font = QRawFont(str(ROOT / "sumire" / "fonts" / "NotoSansJP-Regular.otf"), 13)
    for code in ("ja", "en"):
        missing = {c for c in interface_characters(code) if font.glyphIndexesForString(c) == [0]}
        assert missing <= {"▾"}, (code, sorted(missing))  # ▾ comes from a system font


def test_chinese_starts_with_a_chinese_font():
    """The Japanese subset lacks many simplified characters (e.g. 这, 设, 删)."""
    font = QRawFont(str(ROOT / "sumire" / "fonts" / "NotoSansJP-Regular.otf"), 13)
    assert any(font.glyphIndexesForString(c) == [0] for c in interface_characters("zh_CN"))
    assert theme.font_family().startswith("'Noto Sans JP'")
    i18n.set_language("zh_CN")
    try:
        assert theme.font_family().startswith("'Microsoft YaHei UI'")
        assert "font-family: 'Microsoft YaHei UI'" in theme.stylesheet()
    finally:
        i18n.set_language("ja")
    i18n.set_language("en")
    try:
        assert theme.font_family().startswith("'Noto Sans JP'")
    finally:
        i18n.set_language("ja")
