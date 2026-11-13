"""Console-free Explorer -> WSL launcher. Uses only Windows Python's stdlib."""
import ctypes
from pathlib import Path
import subprocess
import sys
import os


def main():
    if len(sys.argv) != 5:
        return 1
    distribution, python, project, target = sys.argv[1:]
    wsl = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "wsl.exe"
    command = [str(wsl), "--distribution", distribution, "--cd", project,
               "--exec", python, "-m", "sumire", "--open", target]
    try:
        result = subprocess.run(command, creationflags=subprocess.CREATE_NO_WINDOW,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            return 0
    except OSError:
        pass
    ctypes.windll.user32.MessageBoxW(None, "Sumīreを起動できませんでした。WSLとSumīreの実行環境を確認してください。", "Sumīre", 0x10)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
