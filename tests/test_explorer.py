from pathlib import Path
from types import SimpleNamespace
import json
import runpy
import subprocess
import sys

import pytest

from sumire.explorer import BASE, OWNER, VERBS, apply_context_menu, context_entries, normalize_inputs


class Key:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class Registry:
    HKEY_CURRENT_USER = "HKCU"
    REG_SZ = 1

    def __init__(self):
        self.values = {}
        self.calls = 0
        self.fail_at = None

    def OpenKey(self, root, path):
        assert root == self.HKEY_CURRENT_USER
        if path not in self.values:
            raise FileNotFoundError()
        return Key(path)

    def CreateKey(self, root, path):
        assert root == self.HKEY_CURRENT_USER
        self.values.setdefault(path, {})
        return Key(path)

    def QueryValueEx(self, key, name):
        if name not in self.values[key.path]:
            raise FileNotFoundError()
        return self.values[key.path][name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, kind, value):
        self.calls += 1
        if self.calls == self.fail_at:
            raise OSError("synthetic failure")
        assert kind == self.REG_SZ
        self.values[key.path][name] = value

    def DeleteKey(self, root, path):
        if path not in self.values:
            raise FileNotFoundError()
        if any(key.startswith(path + "\\") for key in self.values):
            raise OSError("key has children")
        del self.values[path]


def test_context_commands_quote_paths_and_only_target_supported_images_and_folders():
    entries = context_entries([r"C:\Program Files\日本語\sumire.exe", "--open"])
    assert len(entries) == 7
    for path, values in entries.items():
        assert path.startswith(BASE) and path.endswith("\\shell\\sumire.Open")
        assert values["SumireOwner"] == OWNER and values["MultiSelectModel"] == "Single"
        assert values["command"].startswith('"C:\\Program Files\\日本語\\sumire.exe" --open ')
        assert values["command"].endswith('"%V\\."' if "Background" in path else '"%1\\."' if "Directory" in path else '"%1"')


def test_install_update_and_remove_leave_unrelated_registry_entries():
    registry = Registry()
    unrelated = BASE + r"Directory\shell\OtherApplication"
    registry.values[unrelated] = {"": "keep"}
    first = context_entries([r"C:\Sumīre\sumire.exe", "--open"])
    second = context_entries([r"D:\日本語 Sumīre\sumire.exe", "--open"])
    apply_context_menu(first, registry=registry)
    apply_context_menu(second, registry=registry)
    for path in second:
        assert registry.values[path + "\\command"][""] == second[path]["command"]
    apply_context_menu(second, remove=True, registry=registry)
    assert registry.values == {unrelated: {"": "keep"}}


def test_foreign_or_invalid_registration_is_not_overwritten():
    registry = Registry()
    entries = context_entries(["sumire.exe"])
    first = next(iter(entries))
    registry.values[first] = {"": "foreign"}
    with pytest.raises(ValueError):
        apply_context_menu(entries, registry=registry)
    assert registry.values == {first: {"": "foreign"}}
    with pytest.raises(ValueError):
        apply_context_menu({"Software\\Other": {"SumireOwner": OWNER}}, registry=registry)


@pytest.mark.parametrize("existing", [False, True])
def test_registry_write_failure_rolls_back_install_and_update(existing):
    registry = Registry()
    entries = context_entries(["sumire.exe"])
    if existing:
        apply_context_menu(entries, registry=registry)
    before = {key: dict(value) for key, value in registry.values.items()}
    registry.fail_at = registry.calls + 7
    with pytest.raises(OSError):
        apply_context_menu(context_entries(["new sumire.exe"]), registry=registry)
    assert registry.values == before


@pytest.mark.parametrize("platform", ["posix", "nt"])
def test_windows_paths_are_converted_without_shell_execution(monkeypatch, platform):
    import sumire.explorer as module
    calls = []
    def convert(path, direction):
        calls.append((path, direction))
        return "/mnt/c/converted"
    monkeypatch.setattr(module, "_wslpath", convert)
    monkeypatch.setattr(module, "os", SimpleNamespace(name=platform))
    paths = [r"C:\Users\example\日本語 & pictures\image.png", r"\\server\share\folder", "/tmp/local.png"]
    assert normalize_inputs(paths) == (["/mnt/c/converted", "/mnt/c/converted", "/tmp/local.png"] if platform == "posix" else paths)
    assert calls == ([(paths[0], "-u"), (paths[1], "-u")] if platform == "posix" else [])


def test_wsl_registry_bridge_passes_unicode_plan_as_utf8(monkeypatch):
    import sumire.explorer as module
    commands = []
    monkeypatch.setattr(module, "windows_launcher", lambda: (["pythonw.exe", "launch.pyw", "Ubuntu", "/python", "/日本語"], Path("/bridge/python.exe")))
    monkeypatch.setattr(module, "_wslpath", lambda path, direction: "windows-helper.py")
    def run(command, **options):
        commands.append((command, json.loads(options["input"].decode("utf-8"))))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module.subprocess, "run", run)
    module.configure_context_menu()
    assert commands[0][0] == [str(Path("/bridge/python.exe")), "windows-helper.py", "--install"]
    assert all("/日本語" in values["command"] for values in commands[0][1].values())


def test_console_free_launcher_forwards_selected_path_literally(monkeypatch):
    main = runpy.run_path(str(Path(__file__).parents[1] / "scripts" / "launch_windows.pyw"))["main"]
    target = r"C:\日本語 & folders\image.png"
    monkeypatch.setattr(sys, "argv", ["launch_windows.pyw", "Ubuntu-24.04", "/venv/python", "/project path", target])
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda command, **options: calls.append((command, options)) or SimpleNamespace(returncode=0))
    assert main() == 0
    command, options = calls[0]
    assert command[-4:] == ["-m", "sumire", "--open", target]
    assert options["creationflags"] == 0x08000000
    assert "shell" not in options


@pytest.mark.parametrize("arguments,expected", [(["--open", r"C:\selected"], ["setup", [str(Path("/mnt/c/selected").resolve())]]),
                                                ([], ["setup", "resume"])])
def test_entrypoint_resumes_tabs_or_opens_requested_target(qapp, monkeypatch, arguments, expected):
    import sumire.__main__ as entry
    calls = []
    class App:
        def __getattr__(self, name):
            return lambda *args: 0
    class Window:
        def show(self):
            pass
        def open_inputs(self, paths):
            calls.append(paths)
        def resume_session(self):
            calls.append("resume")
        def first_run_setup(self):
            # The save method is chosen before anything is opened or resumed.
            calls.append("setup")
    monkeypatch.setattr(entry, "QApplication", lambda args: App())
    monkeypatch.setattr(entry, "install_translations", lambda app: None)
    monkeypatch.setattr(entry, "window_class", lambda: Window)
    monkeypatch.setattr(entry, "choose_language", lambda: "ja")
    monkeypatch.setattr(entry, "InstanceBroker", lambda: SimpleNamespace(start_or_forward=lambda paths: "primary", requested=SimpleNamespace(connect=lambda callback: None), close=lambda: None))
    monkeypatch.setattr(entry, "QTimer", SimpleNamespace(singleShot=lambda delay, callback: callback()))
    monkeypatch.setattr(entry, "normalize_inputs", lambda paths: ["/mnt/c/selected"] if paths == [r"C:\selected"] else [])
    monkeypatch.setattr(sys, "argv", ["sumire", *arguments])
    assert entry.main() == 0
    assert calls == expected


def test_qt_standard_texts_are_japanese(qapp):
    """Standard buttons and Qt dialogs must not appear in English in the Japanese UI."""
    import sumire.__main__ as entry
    from PySide6.QtCore import QCoreApplication
    translator = entry.install_translations(qapp)
    try:
        assert translator is not None
        assert QCoreApplication.translate("QPlatformTheme", "Cancel") == "キャンセル"
        assert QCoreApplication.translate("QPlatformTheme", "Close") == "閉じる"
        assert QCoreApplication.translate("QPlatformTheme", "Discard") != "Discard"
    finally:
        if translator is not None:
            qapp.removeTranslator(translator)


def test_wsl_picks_the_newest_windows_python_by_version_not_by_name():
    """Issue #1: a text sort put Python39 before Python312."""
    from sumire.explorer import newest_python
    base = Path("/mnt/c/Users/user/AppData/Local/Programs/Python")
    found = [base / name / "pythonw.exe" for name in ("Python39", "Python312", "Python311", "Python313-32")]
    assert newest_python(found) == base / "Python313-32" / "pythonw.exe"
    assert newest_python(found[:3]) == base / "Python312" / "pythonw.exe"
    assert newest_python([base / "Python312-32" / "pythonw.exe", base / "Python312" / "pythonw.exe"]) == base / "Python312" / "pythonw.exe"
    assert newest_python([]) is None
