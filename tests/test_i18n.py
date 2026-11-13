"""Interface languages: every translatable text has a translation, and the app runs in each language."""
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from sumire import i18n

ROOT = Path(__file__).resolve().parents[1]
FIELD = re.compile(r"\{[^{}]*\}")


def code_keys():
    keys = set()
    for path in (ROOT / "sumire").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr"
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                keys.add(node.args[0].value)
    return keys


@pytest.mark.parametrize("code", ["en", "zh_CN"])
def test_every_text_has_a_translation_with_the_same_fields(code):
    catalog = json.loads((ROOT / "sumire" / "locales" / f"{code}.json").read_text(encoding="utf-8"))
    missing = sorted(code_keys() - set(catalog))
    assert not missing, missing[:10]
    for key, value in catalog.items():
        assert sorted(FIELD.findall(value.replace("{{", "").replace("}}", ""))) == \
               sorted(FIELD.findall(key.replace("{{", "").replace("}}", ""))), key
        if code == "zh_CN":
            assert not re.search(r"[぀-ヿ]", value), value  # no kana (or ・) in Chinese


def test_languages_load_and_states_translate_part_by_part():
    assert i18n.tr("保存") == "保存"  # Japanese is the source
    i18n.set_language("en")
    try:
        assert i18n.tr("保存") == "Save"
        assert i18n.tr_state("未編集 · 保存済み · メタデータ：無し") == "Unedited · Saved · Metadata: none"
        assert i18n.tr("{count}枚を選択中").format(count=3) == "3 selected"
    finally:
        i18n.set_language("ja")
    assert i18n.set_language("fr") == "ja"


def test_japanese_until_a_language_is_chosen_on_the_start_page(qtbot, monkeypatch):
    import sumire.__main__ as entry
    from sumire.preferences import Preferences
    from sumire.window import Window
    assert entry.choose_language() == "ja"  # whatever the system's language
    window = Window()
    qtbot.addWidget(window)
    window.show()
    combo = window.welcome.language
    assert [combo.itemText(index) for index in range(combo.count())] == ["日本語", "English", "简体中文"]
    assert combo.currentData() == "ja" and window.welcome.language_note.isHidden()
    combo.setCurrentIndex(combo.findData("zh_CN"))
    combo.activated.emit(combo.currentIndex())
    assert Preferences().data["language"] == "zh_CN" and entry.choose_language() == "zh_CN"
    assert "下次启动时生效" in window.welcome.language_note.text() and not window.welcome.language_note.isHidden()
    assert i18n.language() == "ja"  # applies from the next start


def test_language_setting_is_saved_for_the_next_start(qtbot, tmp_path, patterned):
    from sumire.preferences import Preferences
    from sumire.settings_dialog import SettingsDialog
    from sumire.window import Window
    window = Window()
    qtbot.addWidget(window)
    dialog = SettingsDialog(window)
    qtbot.addWidget(dialog)
    assert [dialog.language.itemText(index) for index in range(dialog.language.count())] == ["日本語", "English", "简体中文"]
    dialog.language.setCurrentIndex(dialog.language.findData("en"))
    assert Preferences().data["language"] == "en"
    assert "Applies from the next start." in dialog.language_note.text()  # also shown in the chosen language
    assert i18n.language() == "ja"  # the running app keeps its language


@pytest.mark.parametrize("code", ["en", "zh_CN"])
def test_the_window_runs_in_each_language_without_japanese(tmp_path, patterned, code):
    """In a fresh interpreter: some texts are made when the interface modules load."""
    folder = tmp_path / "images"
    folder.mkdir()
    patterned.save(folder / "a.png")
    script = f"""
import re, sys, time
from PySide6.QtWidgets import QApplication, QAbstractButton, QLabel, QWidget
app = QApplication([])
from sumire import i18n
i18n.set_language({code!r})
from sumire.theme import install_fonts
assert install_fonts() == ["Noto Sans JP"]
from sumire.workspace_tabs import WorkspaceWindow
window = WorkspaceWindow(); window.show()
window.open_inputs([{str(folder)!r}])
page = window.current_workspace()
for _ in range(500):
    app.processEvents(); time.sleep(0.01)
    if page.document is not None and page.canvas.ready:
        break
kana = re.compile(r"[\\u3040-\\u30ff]")
left = [w.text() for w in window.findChildren(QWidget) if isinstance(w, (QAbstractButton, QLabel)) and kana.search(w.text())]
print("LEFT", left)
sys.exit(1 if left or page.document is None else 0)
"""
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "SUMIRE_SETTINGS_FILE": str(tmp_path / "settings.json")}
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=environment, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]


def test_help_follows_the_language_and_falls_back_to_japanese(monkeypatch):
    from sumire import help as help_module
    i18n.set_language("en")
    try:
        assert help_module.help_folder() == ("help_docs", "en")
        text = help_module.read_help_document("FAQ.md")
        assert text.startswith("#")
    finally:
        i18n.set_language("ja")
    assert help_module.help_folder() == ("help_docs",)
