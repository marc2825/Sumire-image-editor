r"""Native Windows smoke test of the distribution folder, using only synthetic images.

    python -m scripts.smoke_windows_exe dist\Sumire-v1.1.0-win64 --artifacts test-artifacts\windows-exe [--shell-verbs]

Run from a Windows test environment with Pillow, pywinauto, psutil and pywin32.
It moves the real mouse and keyboard: do not use the PC until it finishes.
The distribution folder is copied to a Japanese path; the application child gets
no Python on PATH and its own new settings profile, so the first-start dialog,
the first-overwrite notice and the quit confirmation all appear and are answered.
This is not a clean-PC test. --shell-verbs temporarily registers Sumīre's Explorer
verbs (including the "open where?" dialog of a running instance) and restores them.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time
import zlib


def wait_for(check, description, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (OSError, RuntimeError):
            pass
        time.sleep(0.15)
    raise AssertionError(f"Timed out: {description}")


def capture_client(window, path):
    """Ask the owned app to paint itself; never capture overlapping desktop windows."""
    from PIL import Image
    import win32gui
    import win32ui
    left, top, right, bottom = win32gui.GetClientRect(window.handle)
    width, height = right - left, bottom - top
    handle = win32gui.GetDC(window.handle)
    source = win32ui.CreateDCFromHandle(handle)
    target = source.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    try:
        bitmap.CreateCompatibleBitmap(source, width, height)
        target.SelectObject(bitmap)
        paint = ctypes.windll.user32.PrintWindow
        paint.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
        paint.restype = ctypes.c_bool
        if not paint(window.handle, target.GetSafeHdc(), 3):  # PW_CLIENTONLY | PW_RENDERFULLCONTENT
            raise RuntimeError("The application did not render its client area; no desktop fallback is used.")
        Image.frombuffer("RGB", (width, height), bitmap.GetBitmapBits(True), "raw", "BGRX", 0, 1).save(path)
    finally:
        win32gui.DeleteObject(bitmap.GetHandle())
        target.DeleteDC()
        source.DeleteDC()
        win32gui.ReleaseDC(window.handle, handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("distribution", type=Path, help="the extracted folder that contains sumire.exe and _internal")
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--shell-verbs", action="store_true")
    parser.add_argument("--scales", type=float, nargs="+", default=[1.5, 2])
    parser.add_argument("--expect-os-dpi", type=int)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Run this test on Windows.")
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    import psutil
    import win32api
    from PIL import Image, PngImagePlugin
    from pywinauto import Desktop, keyboard, mouse

    output = args.artifacts.resolve()
    output.mkdir(parents=True, exist_ok=False)
    distribution = output / "Sumīre 日本語の配布 フォルダー"
    source_folder = args.distribution.resolve()
    if source_folder.is_file():
        source_folder = source_folder.parent
    if not (source_folder / "sumire.exe").is_file() or not (source_folder / "_internal").is_dir():
        parser.error("Pass the extracted distribution folder (sumire.exe and _internal).")
    shutil.copytree(source_folder, distribution)
    executable = distribution / "sumire.exe"
    system32 = str(Path(os.environ["SystemRoot"]) / "System32")
    report = {"exe_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(), "scales": [],
              "clean_pc_test": "NOT RUN: PATH isolation is not an uninstalled-Python PC", "dialogs": []}

    def windows():
        found = []
        for window in Desktop(backend="win32").windows(title_re=".*Sumīre.*"):
            try:
                if Path(psutil.Process(window.process_id()).exe()) == executable:
                    found.append(window)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return found

    def dialog(title):
        """A dialog of the app: owned windows may appear under the main window or on the desktop."""
        for window in windows():
            for candidate in (Desktop(backend="uia").window(handle=window.handle).child_window(title=title, control_type="Window"),
                              Desktop(backend="uia").window(process=window.process_id(), title=title, control_type="Window")):
                if candidate.exists(timeout=0):
                    return candidate
        return None

    def press(window, title):
        window.child_window(title=title, control_type="Button").invoke()

    def answer_dialogs(choices):
        """Answer the app's own dialogs; ``choices`` records what was seen."""
        first_run = dialog("保存方法を選んでください")
        if first_run is not None:
            first_run.child_window(title="元画像に上書き保存する", control_type="RadioButton").select()
            for title in ("保存するときにメタデータを削除する", "削除前のメタデータを復元用に残す"):
                box = first_run.child_window(title=title, control_type="CheckBox")
                if box.get_toggle_state() == 0:
                    box.toggle()
            press(first_run, "この設定で始める")
            choices.append("first-run: overwrite, strip, keep for restoring")
            return True
        notice = dialog("元画像に上書きします")
        if notice is not None:
            press(notice, "上書きする")
            choices.append("first overwrite: overwrite")
            return True
        where = dialog("画像・フォルダーの開き方")
        if where is not None:
            press(where, "新しいタブで開く")
            choices.append("open where: new tab")
            return True
        return False

    def window_for(name, choices=None):
        answer_dialogs(choices if choices is not None else [])
        return next((w for w in windows() if w.window_text() == f"{name} — Sumīre"), None)

    def close_windows():
        for window in windows():
            ui = Desktop(backend="uia").window(handle=window.handle)
            file_dialog = ui.child_window(title="メタデータを復元して別名保存", control_type="Window")
            if file_dialog.exists(timeout=0):
                file_dialog.child_window(auto_id="2", control_type="Button").invoke()
            window.close()

        def closed():
            quit_box = dialog("Sumīreを終了")
            if quit_box is not None:
                press(quit_box, "終了する")
            return not windows()
        wait_for(closed, "application close")

    def pixels(path):
        with Image.open(path) as image:
            return hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest()

    def sample(path):
        image = Image.new("RGB", (640, 480))
        image.putdata([((x * 19 + y * 3) % 256, (y * 29) % 256, (x * 7 + y * 11) % 256)
                       for y in range(480) for x in range(640)])
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("parameters", "synthetic test metadata")
        image.save(path, pnginfo=metadata)

    def clean_environment(folder, scale):
        env = dict(os.environ)
        env.update(PATH=system32, PYTHONHOME=str(folder / "missing-python"),
                   PYTHONPATH=str(folder / "missing-modules"), QT_QPA_PLATFORM="windows",
                   QT_SCALE_FACTOR=str(scale), SUMIRE_SETTINGS_FILE=str(folder / "settings.json"))
        temp = folder / "日本語の一時領域"
        temp.mkdir()
        env.update(TEMP=str(temp), TMP=str(temp))
        assert subprocess.run([str(Path(system32) / "where.exe"), "python"], env=env,
                              capture_output=True).returncode != 0
        return env

    try:
        for scale in args.scales:
            welcome_folder = output / f"welcome-{scale}"
            welcome_folder.mkdir()
            welcome_process = subprocess.Popen([str(executable)], env=clean_environment(welcome_folder, scale))
            try:
                # A new profile asks for the save method first.
                wait_for(lambda: answer_dialogs(report["dialogs"]), "first-start dialog")
                welcome = wait_for(lambda: next(iter(windows()), None), "empty-state launch")
                welcome.set_focus()
                welcome_ui = Desktop(backend="uia").window(handle=welcome.handle)
                wait_for(lambda: welcome_ui.child_window(title="フォルダーを開く", control_type="Button").exists()
                         and welcome_ui.child_window(title="画像を開く", control_type="Button").exists(), "empty-state open controls")
                capture_client(welcome, welcome_folder / "welcome-preview.png")
                print(f"PASS: empty-state controls at Qt factor {scale:g}", flush=True)
            finally:
                close_windows()
                welcome_process.wait(timeout=20)
            folder = output / f"scale-{scale}"
            folder.mkdir()
            source = folder / "画像 01 & テスト.png"
            sample(source)
            sibling = folder / "選択していない画像.png"
            sample(sibling)
            sibling_before = sibling.read_bytes()
            original = pixels(source)
            env = clean_environment(folder, scale)
            process = subprocess.Popen([str(executable), "--open", str(source)], env=env)
            try:
                window = wait_for(lambda: window_for(source.name, report["dialogs"]), "Japanese image launch")
                os_dpi = ctypes.windll.user32.GetDpiForWindow(window.handle)
                if args.expect_os_dpi is not None:
                    assert os_dpi == args.expect_os_dpi, (os_dpi, args.expect_os_dpi)
                frame = window.rectangle()
                work = win32api.GetMonitorInfo(win32api.MonitorFromWindow(window.handle))["Work"]
                assert frame.left >= work[0] and frame.top >= work[1], (frame, work)
                assert frame.right <= work[2] and frame.bottom <= work[3], (frame, work)
                window.set_focus()
                ui = Desktop(backend="uia").window(handle=window.handle)
                canvas = ui.child_window(class_name="Canvas").wrapper_object()
                wait_for(lambda: ui.child_window(title="上書きして次へ →", control_type="Button").is_enabled(), "image ready")
                # Give the folder monitor time to poll twice. Opening one file
                # must not import its siblings after the initial scan.
                time.sleep(3)
                assert ui.child_window(title="画像  1 枚", control_type="Text").exists()
                keyboard.send_keys("^f")
                # Qt's Windows UIA provider exposes this edit by class, with an empty Name.
                search = ui.child_window(class_name="QLineEdit", control_type="Edit")
                search.set_edit_text("unmatched-name")
                wait_for(lambda: ui.child_window(title_re="(?s).*表示 0 / 1.*", control_type="Text").exists(), "name search hides unmatched image")
                search.set_edit_text("")
                wait_for(lambda: not ui.child_window(title_re="(?s).*表示 0 / 1.*", control_type="Text").exists(), "name search reset")
                wait_for(lambda: ui.child_window(title="上書きして次へ →", control_type="Button").is_enabled(), "image ready after search")
                window.set_focus()
                keyboard.send_keys("{ENTER}")  # Finish search and return keyboard focus to the canvas.
                time.sleep(0.3)  # Let the reload and layout finish before resolving its screen rectangle.
                canvas = ui.child_window(class_name="Canvas").wrapper_object()
                print(f"PASS: native name search and reset at Qt factor {scale:g}", flush=True)
                rect = canvas.rectangle()
                capture_client(window, folder / "before-draw.png")
                center = rect.left + rect.width() // 2
                delta = min(30, rect.width() // 8)
                start = (center - delta, rect.top + rect.height() // 2)
                end = (center + delta, start[1])
                mouse.press(coords=start)
                for step in range(1, 11):
                    mouse.move(coords=(start[0] + (end[0] - start[0]) * step // 10, start[1]))
                mouse.release(coords=end)
                # The first overwrite of a run explains itself; answer_dialogs accepts it.
                wait_for(lambda: answer_dialogs(report["dialogs"]) or pixels(source) != original, "first-overwrite notice")
                wait_for(lambda: pixels(source) != original, "brush autosave")
                edited = pixels(source)
                keyboard.send_keys("^z")
                wait_for(lambda: pixels(source) == original, "Undo autosave")
                keyboard.send_keys("^y")
                wait_for(lambda: pixels(source) == edited, "Redo autosave")
                with Image.open(source) as saved:
                    assert saved.size == (640, 480) and not saved.info
                assert ui.child_window(title_re=".*メタデータ：無し.*", control_type="Text").exists()
                # New profiles keep records in the app's folder, keyed by the image folder.
                key = hashlib.sha256(os.path.normcase(str(source.parent.resolve())).encode()).hexdigest()
                records = folder / "records" / key / ".sumire-index.sqlite3"
                assert not (source.parent / ".sumire-index.sqlite3").exists()
                connection = sqlite3.connect(records)
                try:
                    rows = connection.execute("SELECT digest,payload FROM metadata_backups").fetchall()
                finally:
                    connection.close()
                assert len(rows) == 1 and rows[0][0] == hashlib.sha256(source.read_bytes()).hexdigest()
                assert json.loads(zlib.decompress(rows[0][1]))["format"] == "PNG"
                # The restore command is in the image menu (the "⋯" next to the file name) → その他.
                image_menu = ui.child_window(title="この画像の操作")
                wait_for(image_menu.is_enabled, "image menu ready")
                image_menu.click_input()
                # Qt exposes the popup as a Window with class QMenu, not UIA's Menu type.
                other_item = Desktop(backend="uia").window(process=window.process_id(), class_name="QMenu").child_window(
                    title_re="^その他", control_type="MenuItem")
                other_item.wait("ready", timeout=15)
                other_item.click_input()
                restore_item = Desktop(backend="uia").window(process=window.process_id(), class_name="QMenu", found_index=1).child_window(
                    title_re="^メタデータを復元して別名保存", control_type="MenuItem")
                restore_item.wait("ready", timeout=15)
                restore_item.click_input()
                dialog = ui.child_window(title="メタデータを復元して別名保存", control_type="Window")
                dialog.wait("ready", timeout=15)
                restored = folder / "復元した画像.png"
                filename = dialog.child_window(auto_id="1001", control_type="Edit")
                filename.set_edit_text(str(restored))
                dialog.child_window(auto_id="1", control_type="Button").invoke()
                wait_for(restored.exists, "restored copy saved")
                with Image.open(restored) as saved:
                    assert saved.info["parameters"] == "synthetic test metadata"
                assert pixels(restored) == edited and pixels(source) == edited
                with Image.open(source) as saved:
                    assert not saved.info
                assert sibling.read_bytes() == sibling_before
                modules = [m.path for m in psutil.Process(window.process_id()).memory_maps()]
                internal = str(distribution / "_internal").lower()
                python_dlls = [p for p in modules if Path(p).name.lower() in ("python3.dll", "python312.dll")]
                assert python_dlls and all(p.lower().startswith(internal) for p in python_dlls), python_dlls
                qt_dlls = [p for p in modules if Path(p).name.lower().startswith("qt6")]
                assert qt_dlls and all(p.lower().startswith(internal) for p in qt_dlls), qt_dlls
                assert not any("site-packages" in p.lower() or "\\programs\\python\\" in p.lower() for p in modules)
                capture_client(window, folder / "exe-preview.png")
                report["scales"].append({"QT_SCALE_FACTOR": scale, "os_dpi": os_dpi,
                    "frame": [frame.left, frame.top, frame.right, frame.bottom], "work_area": list(work),
                    "fits": True, "Japanese_exe_image_temp_paths": "PASS", "brush_autosave_undo_redo": "PASS",
                    "selected_image_only_after_monitor_polls": True,
                    "redesigned_empty_state_and_name_search": "PASS",
                    "first_run_dialog_and_overwrite_notice": "PASS", "records_in_app_folder": "PASS",
                    "compressed_sqlite_backup_and_restore_button": "PASS",
                    "metadata_removed": True, "python_on_PATH": False, "python_and_qt_from_internal": True})
                print(f"PASS: EXE at Qt factor {scale:g}, OS DPI {os_dpi}, Japanese paths, edit/save/Undo/Redo, bundled Python", flush=True)
            finally:
                close_windows()
                process.wait(timeout=20)

        if args.shell_verbs:
            # Same named shell verb that Explorer's context menu invokes.
            import winreg
            from win32com.shell import shell, shellcon
            from sumire.explorer import BASE, LEGACY_VERBS, context_entries, apply_context_menu, _read_values, _write_values, _delete_verb, _notify_shell
            entries = context_entries([str(executable), "--open"])
            previous = {path: _read_values(winreg, path) for path in entries}
            previous_legacy = {}
            for verb in LEGACY_VERBS:
                path = BASE + verb
                try:
                    values = _read_values(winreg, path, legacy=True)
                except ValueError:
                    continue
                if values is not None:
                    previous_legacy[path] = values
            folder = output / "右クリックの検証"
            folder.mkdir()
            source = folder / "画像 01 & テスト.png"
            other = folder / "画像 02.png"
            sample(source)
            sample(other)
            saved_environment = dict(os.environ)
            os.environ.update(clean_environment(folder, 1))
            try:
                apply_context_menu(entries)
                _notify_shell()
                for path, values in entries.items():
                    assert _read_values(winreg, path) == values
                def invoke(path):
                    # SEE_MASK_NOASYNC (0x100) is absent in some pywin32 releases.
                    result = shell.ShellExecuteEx(fMask=shellcon.SEE_MASK_NOCLOSEPROCESS | 0x100,
                                                  lpVerb="sumire.Open", lpFile=str(path), nShow=1)
                    if result.get("hProcess"):
                        result["hProcess"].Close()
                invoke(source)
                window = wait_for(lambda: window_for(source.name, report["dialogs"]), "image context verb")
                pid = window.process_id()
                seen = len(report["dialogs"])
                invoke(other)
                # The running instance asks whether to add to the current tab or open a new one.
                wait_for(lambda: window_for(other.name, report["dialogs"]), "forward context verb to existing instance")
                assert "open where: new tab" in report["dialogs"][seen:], report["dialogs"]
                assert len(windows()) == 1 and windows()[0].process_id() == pid
                close_windows()
                invoke(folder)
                window = wait_for(lambda: window_for(source.name, report["dialogs"]), "folder context verb")
                assert len(windows()) == 1
                window.set_focus()
                capture_client(window, folder / "shell-verb-preview.png")
                report["shell_verbs"] = {"registered_entries": len(entries), "image": "PASS", "folder": "PASS",
                                         "existing_instance_new_tab_choice": "PASS"}
                print("PASS: native Shell sumire.Open image/folder verbs and existing-instance handoff", flush=True)
            finally:
                close_windows()
                os.environ.clear()
                os.environ.update(saved_environment)
                for path, values in previous.items():
                    if values is None:
                        _delete_verb(winreg, path)
                    else:
                        _write_values(winreg, path, values)
                for path, values in previous_legacy.items():
                    _write_values(winreg, path, values, legacy=True)
                _notify_shell()
                assert {path: _read_values(winreg, path) for path in entries} == previous
                assert {path: _read_values(winreg, path, legacy=True) for path in previous_legacy} == previous_legacy
                report["shell_registry_restored"] = True
    finally:
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
