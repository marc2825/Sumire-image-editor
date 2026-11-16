"""Per-user Windows Explorer verbs, including a WSL source installation.

Keep this module free of Qt and Python 3.12-only syntax: Windows Python can run
the registry helper even when the actual application runs inside WSL.
"""
from __future__ import annotations
from .i18n import tr

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

OWNER = "sumire.ImageFinishing.ContextMenu.v1"
LEGACY_OWNER = "Sumi.ImageFinishing.ContextMenu.v1"
BASE = "Software\\Classes\\"
EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
VERBS = {f"SystemFileAssociations\\{extension}\\shell\\sumire.Open": "%1" for extension in EXTENSIONS}
VERBS.update({"Directory\\shell\\sumire.Open": "%1\\.", "Directory\\Background\\shell\\sumire.Open": "%V\\."})
LEGACY_VERBS = {verb.replace("\\sumire.Open", "\\Sumi.Open"): value for verb, value in VERBS.items()}


def context_entries(launcher):
    command = subprocess.list2cmdline([str(arg) for arg in launcher])
    return {BASE + verb: {"": tr("Sumīreで開く"), "SumireOwner": OWNER, "MultiSelectModel": "Single",
                          "command": command + ' "' + placeholder + '"'} for verb, placeholder in VERBS.items()}


def _read_values(registry, path, *, legacy=False):
    field, expected_owner = ("SumiOwner", LEGACY_OWNER) if legacy else ("SumireOwner", OWNER)
    try:
        with registry.OpenKey(registry.HKEY_CURRENT_USER, path) as key:
            owner = registry.QueryValueEx(key, field)[0]
            if owner != expected_owner:
                raise ValueError(tr("同名の別の右クリック項目があります。登録を中止しました。"))
            values = {name: registry.QueryValueEx(key, name)[0] for name in ("", field, "MultiSelectModel")}
        with registry.OpenKey(registry.HKEY_CURRENT_USER, path + "\\command") as key:
            values["command"] = registry.QueryValueEx(key, "")[0]
        return values
    except FileNotFoundError:
        # Distinguish a missing verb from a foreign/partially written verb.
        try:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, path):
                pass
        except FileNotFoundError:
            return None
        raise ValueError(tr("右クリック項目の登録情報を確認できません。")) from None


def _write_values(registry, path, values, *, legacy=False):
    field = "SumiOwner" if legacy else "SumireOwner"
    with registry.CreateKey(registry.HKEY_CURRENT_USER, path) as key:
        for name in ("", field, "MultiSelectModel"):
            registry.SetValueEx(key, name, 0, registry.REG_SZ, values[name])
    with registry.CreateKey(registry.HKEY_CURRENT_USER, path + "\\command") as key:
        registry.SetValueEx(key, "", 0, registry.REG_SZ, values["command"])


def _delete_verb(registry, path):
    for suffix in ("\\command", ""):
        try:
            registry.DeleteKey(registry.HKEY_CURRENT_USER, path + suffix)
        except FileNotFoundError:
            pass


def apply_context_menu(entries, *, remove=False, registry=None):
    if registry is None:
        import winreg as registry
    expected = {BASE + verb for verb in VERBS}
    if not isinstance(entries, dict) or set(entries) != expected or any(not isinstance(value, dict) or value.get("SumireOwner") != OWNER
                                      or any(not isinstance(value.get(name), str) for name in ("", "MultiSelectModel", "command"))
                                      for value in entries.values()):
        raise ValueError(tr("右クリックメニューの登録内容が不正です。"))
    previous = {path: _read_values(registry, path) for path in entries}
    legacy_entries = {}
    for verb in LEGACY_VERBS:
        path = BASE + verb
        try:
            values = _read_values(registry, path, legacy=True)
        except ValueError:
            continue  # A foreign legacy-named verb must never be touched.
        if values is not None:
            legacy_entries[path] = values
    changed = []
    try:
        for path, values in entries.items():
            changed.append(path)
            if remove:
                if previous[path] is not None:
                    _delete_verb(registry, path)
            else:
                _write_values(registry, path, values)
        for path in legacy_entries:
            changed.append(path)
            _delete_verb(registry, path)
    except OSError:
        for path in reversed(changed):
            if path in legacy_entries:
                _write_values(registry, path, legacy_entries[path], legacy=True)
            elif previous[path] is None:
                _delete_verb(registry, path)
            else:
                _write_values(registry, path, previous[path])
        raise


def _wslpath(path, direction):
    result = subprocess.run(["wslpath", direction, str(path)], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def normalize_inputs(paths):
    result = []
    for raw in paths:
        if os.name != "nt" and (re.match(r"^[A-Za-z]:[\\/]", raw) or raw.startswith("\\\\")):
            raw = _wslpath(raw, "-u")
        result.append(raw)
    return result


def newest_python(candidates):
    """The pythonw.exe of the newest Windows Python ("Python312" over "Python39"), 64-bit first."""
    def version(path):
        match = re.fullmatch(r"Python(\d)(\d+)(.*)", path.parent.name)
        if not match:
            return (0, 0, False, path.parent.name)
        return (int(match.group(1)), int(match.group(2)), not match.group(3).endswith("-32"), path.parent.name)
    candidates = list(candidates)
    return max(candidates, key=version) if candidates else None


def windows_launcher():
    if os.name == "nt":
        executable = Path(sys.executable).resolve()
        if getattr(sys, "frozen", False):
            return [str(executable), "--open"], None
        pythonw = executable.with_name("pythonw.exe")
        if not pythonw.is_file():
            raise ValueError(tr("Pythonのpythonw.exeを確認できません。sumire.exeかWindowsのPython環境を使ってください。"))
        return [str(pythonw), str(Path(__file__).resolve().parent.parent / "run_sumire.py"), "--open"], None
    distribution = os.environ.get("WSL_DISTRO_NAME")
    if not distribution:
        raise ValueError(tr("この連携はWindowsまたはWSLから登録してください。"))
    # A Windows Python is only a console-free launcher; Qt stays inside WSL.
    pythonw = newest_python(Path("/mnt/c/Users").glob("*/AppData/Local/Programs/Python/Python*/pythonw.exe"))
    if pythonw is None:
        raise ValueError(tr("Windowsのpythonw.exeが見つかりません。Windows版Pythonを導入するか、Windows版Sumīreから登録してください。"))
    project = Path(__file__).resolve().parent.parent
    launcher = [_wslpath(pythonw, "-w"), _wslpath(project / "scripts" / "launch_windows.pyw", "-w"),
                distribution, sys.executable, str(project)]
    return launcher, pythonw.with_name("python.exe")


def configure_context_menu(*, remove=False):
    launcher, bridge = windows_launcher()
    entries = context_entries(launcher)
    if bridge is None:
        apply_context_menu(entries, remove=remove)
        _notify_shell()
        return
    module = _wslpath(Path(__file__).resolve(), "-w")
    completed = subprocess.run([str(bridge), module, "--remove" if remove else "--install"],
                               input=json.dumps(entries, ensure_ascii=False).encode("utf-8"), capture_output=True)
    if completed.returncode:
        raise ValueError(tr("Windowsの右クリックメニューを更新できませんでした。Windowsとの接続・アクセス権を確認してください。"))


def _notify_shell():
    if os.name == "nt":
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)


def main():
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--install", action="store_true")
    action.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    try:
        entries = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        apply_context_menu(entries, remove=args.remove)
        _notify_shell()
    except (OSError, ValueError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
