"""Interface language: Japanese (the source), English and Simplified Chinese.

The Japanese text in the code is the key. Each other language has a catalog,
``locales/<code>.json``, mapping that text to its translation; text without an
entry stays Japanese. Text built from values is translated as a template with
named fields, e.g. ``tr("保存 {saved}枚").format(saved=count)``.

Japanese is the default. The language is chosen on the start page or in the
settings and takes effect at the next start, so nothing has to be re-translated
while the windows are open.
"""
from __future__ import annotations

import json
from importlib import resources

LANGUAGES = {"ja": "日本語", "en": "English", "zh_CN": "简体中文"}
DEFAULT = "ja"

_language = DEFAULT
_catalog: dict[str, str] = {}


def load_catalog(code: str) -> dict[str, str]:
    if code == DEFAULT or code not in LANGUAGES:
        return {}
    try:
        data = json.loads(resources.files("sumire").joinpath("locales", f"{code}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {key: value for key, value in data.items() if isinstance(key, str) and isinstance(value, str) and value}


def set_language(code: str | None) -> str:
    """Use ``code`` for every text translated from now on; unknown codes mean Japanese."""
    global _language, _catalog
    _language = code if code in LANGUAGES else DEFAULT
    _catalog = load_catalog(_language)
    return _language


def language() -> str:
    return _language


def tr(text: str) -> str:
    return _catalog.get(text, text)


def tr_state(text: str) -> str:
    """A save state such as "未編集 · 保存済み · メタデータ：無し", translated part by part.

    States stay Japanese inside the app (their parts are matched to pick a colour)
    and are only translated where they are shown.
    """
    return " · ".join(tr(part) for part in text.split(" · ")) if _catalog else text


def saved_language(preferences) -> str | None:
    value = preferences.data.get("language") if preferences is not None else None
    return value if value in LANGUAGES else None


def save_language(preferences, code: str) -> bool:
    try:
        preferences.save({**preferences.data, "language": code})
    except OSError:
        return False
    return True


RESTART_NOTE = "次に起動したときから切り替わります。"


def switch_note(code: str) -> str:
    """"Applies from the next start", also in the chosen language so it can be read after switching."""
    current = tr(RESTART_NOTE)
    chosen = load_catalog(code).get(RESTART_NOTE, RESTART_NOTE)
    return current if chosen == current else f"{current}\n{chosen}"
