"""List interface texts that a language catalog does not translate yet.

    python -m scripts.i18n_check            # every language
    python -m scripts.i18n_check --prune    # also drop entries no longer used in the code

Japanese text in tr("...") is the key; add the missing ones to sumire/locales/<code>.json,
keeping every {field} of the key in the translation.
"""
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELD = re.compile(r"\{[^{}]*\}")
# Shown through i18n.tr_state() or as preset names: not inside a tr() call.
EXTRA = ["未編集", "保存済み", "書出済み", "保存待ち", "未保存", "編集中", "変更なし", "変更あり", "保存失敗", "変更を保持",
         "読み込みエラー", "保存記録あり", "再検証待ち", "保存設定を変更", "保存先を変更", "再開可能",
         "メタデータ：無し", "メタデータ：有り", "とても細かいモザイク", "細かいモザイク", "強いモザイク", "黒塗り"]


def code_keys():
    keys = set(EXTRA)
    for path in (ROOT / "sumire").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr"
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                keys.add(node.args[0].value)
    return keys


def fields(text):
    return sorted(FIELD.findall(text.replace("{{", "").replace("}}", "")))


def main():
    keys, failed = code_keys(), False
    for path in sorted((ROOT / "sumire" / "locales").glob("*.json")):
        catalog = json.loads(path.read_text(encoding="utf-8"))
        missing = sorted(keys - set(catalog))
        wrong = [key for key, value in catalog.items() if fields(key) != fields(value)]
        unused = sorted(set(catalog) - keys)
        print(f"{path.name}: {len(missing)} missing, {len(wrong)} with different fields, {len(unused)} unused")
        for key in missing:
            print("  missing:", json.dumps(key, ensure_ascii=False))
        for key in wrong:
            print("  fields:", json.dumps(key, ensure_ascii=False))
        if "--prune" in sys.argv and unused:
            for key in unused:
                del catalog[key]
            path.write_text(json.dumps(catalog, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        failed |= bool(missing or wrong)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
