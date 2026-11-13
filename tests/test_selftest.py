"""The built app's --self-test, run here from the source in a fresh interpreter."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_self_test_passes_and_stays_inside_its_folder(tmp_path):
    folder = tmp_path / "self-test"
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "SUMIRE_SETTINGS_FILE": str(tmp_path / "user-settings.json")}
    result = subprocess.run([sys.executable, "-m", "sumire", "--self-test", str(folder)], cwd=ROOT, env=environment,
                            capture_output=True, text=True, timeout=600)
    report = json.loads((folder / "self-test.json").read_text(encoding="utf-8"))
    failed = {name: check["detail"] for name, check in report["checks"].items() if not check["ok"]}
    assert result.returncode == 0 and report["passed"], failed
    assert set(report["checks"]["interfaces"]["detail"]) == {"ja", "en", "zh_CN", "ja-1.25x", "ja-1.5x"}
    assert all((folder / f"ui-{code}" / f"interface-{code}.png").is_file() for code in ("ja", "en", "zh_CN"))
    assert not (tmp_path / "user-settings.json").exists()  # the user's profile is never touched
    assert str(Path.home()) not in (folder / "self-test.json").read_text(encoding="utf-8")


def test_unknown_self_test_arguments_are_refused():
    from sumire.selftest import main
    assert main(["--self-test"]) == 2
