"""Check a packaged Windows ZIP the way a user would get it.

    python -m scripts.verify_distribution dist\\Sumire-v1.01.0-win64.zip --report test-artifacts\\distribution.json
    python -m scripts.verify_distribution dist\\Sumire-v1.01.0-win64.zip --replace-qt C:\\qt\\6.12.0\\msvc2022_64

Run on Windows with the environment that built the ZIP. It
- compares the ZIP with its external .sha256 file and every file with SHA256SUMS.txt inside,
- checks the required documents and licences, and that nothing private is inside,
- checks that the Qt and PySide6 files are byte-identical to the installed wheels,
- extracts the ZIP to a new folder whose path has Japanese characters and spaces
  and runs ``sumire.exe --self-test`` there,
- with --replace-qt, copies Qt6Core/Gui/Widgets/Network.dll (from ``bin``) and
  qwindows.dll (from ``plugins/platforms``) of another Qt 6.12 build over the
  extracted copy, runs the self-test again and checks that the replaced files
  were the ones loaded.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import zipfile

from sumire import DISPLAY_VERSION

NAME = f"Sumire-v{DISPLAY_VERSION}-win64"
DOCUMENTS = ("sumire.exe", "unregister-context-menu.cmd", "LICENSE", "THIRD_PARTY_NOTICES.md", "QT_REPLACEMENT.md", "README-Windows.txt",
             "README-Windows.en.txt", "README-Windows.zh-CN.txt", "CHANGELOG.md", "SHA256SUMS.txt",
             "docs/VALIDATION_SUMMARY.md", "licenses/Python/LICENSE.txt", "licenses/Qt/LGPL-3.0-only.txt",
             "licenses/Qt/GPL-3.0-only.txt", "licenses/Qt/THIRD_PARTY.md", "licenses/NotoSansJP/OFL.txt",
             "licenses/PyInstaller/pyinstaller-6.22.3.dist-info/licenses/COPYING.txt",
             "licenses/Pillow/pillow-12.3.0.dist-info/licenses/LICENSE", "_internal/sumire/fonts/OFL.txt")
PRIVATE = re.compile(r"(?i)(^|/)(AGENTS\.md|RELEASE_STATUS\.md|PUBLISH_CHECKLIST\.md|VALIDATION\.md|\.env|"
                     r"[^/]*\.sqlite3?(-.*)?|[^/]*\.log|__pycache__|[^/]*\.sumire|settings\.json)$")
QT_REPLACEMENTS = {"bin/Qt6Core.dll": "PySide6/Qt6Core.dll", "bin/Qt6Gui.dll": "PySide6/Qt6Gui.dll",
                   "bin/Qt6Widgets.dll": "PySide6/Qt6Widgets.dll", "bin/Qt6Network.dll": "PySide6/Qt6Network.dll",
                   "plugins/platforms/qwindows.dll": "PySide6/plugins/platforms/qwindows.dll"}


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def check_archive(archive: Path):
    external = archive.with_name(archive.name + ".sha256").read_text(encoding="utf-8").split()
    require(external == [sha256(archive), archive.name], "the ZIP differs from its .sha256 file")
    with zipfile.ZipFile(archive) as bundle:
        require(bundle.testzip() is None, "a file in the ZIP is damaged")
        names = [info.filename for info in bundle.infolist() if not info.is_dir()]
        require(all(PurePosixPath(name).parts[0] == NAME for name in names), f"everything must be inside {NAME}/")
        require(not any(".." in PurePosixPath(name).parts or name.startswith("/") for name in names), "unsafe path")
        relative = [name.split("/", 1)[1] for name in names]
        missing = [name for name in DOCUMENTS if name not in relative]
        require(not missing, f"missing: {missing}")
        private = [name for name in relative if PRIVATE.search(name)]
        require(not private, f"private or generated files: {private}")
        sums = dict(reversed(line.split("  ", 1)) for line in
                    bundle.read(f"{NAME}/SHA256SUMS.txt").decode("utf-8").splitlines())
        require(set(sums) == set(relative) - {"SHA256SUMS.txt"}, "SHA256SUMS.txt does not list exactly the files")
        for name in sums:
            require(hashlib.sha256(bundle.read(f"{NAME}/{name}")).hexdigest() == sums[name], f"checksum differs: {name}")
        sizes = sum(info.file_size for info in bundle.infolist())
    return {"zip": archive.name, "zip_bytes": archive.stat().st_size, "zip_sha256": external[0], "files": len(names),
            "extracted_bytes": sizes, "checked_files": len(sums)}


def check_qt_matches_wheels(folder: Path):
    """The Qt and PySide6 files in the distribution are the wheels' files, unchanged."""
    compared = {}
    for package in ("PySide6-Essentials", "shiboken6"):
        distribution = importlib.metadata.distribution(package)
        for relative in distribution.files or ():
            if relative.suffix.lower() not in {".dll", ".pyd", ".qm"}:
                continue
            target = folder / "_internal" / Path(*relative.parts)
            if target.is_file():
                source = Path(distribution.locate_file(relative))
                require(sha256(source) == sha256(target), f"{relative} differs from the wheel")
                compared[str(relative).replace("\\", "/")] = sha256(target)
    require(any(name.endswith("Qt6Core.dll") for name in compared), "Qt6Core.dll was not compared")
    return {"identical_to_wheels": len(compared), "examples": {name: compared[name] for name in sorted(compared)
                                                                 if re.search(r"Qt6(Core|Gui|Widgets)\.dll$", name)}}


def self_test(folder: Path, report: Path):
    result = subprocess.run([str(folder / "sumire.exe"), "--self-test", str(report)], timeout=900)
    data = json.loads((report / "self-test.json").read_text(encoding="utf-8"))
    failed = {name: check["detail"] for name, check in data["checks"].items() if not check["ok"]}
    require(result.returncode == 0 and data["passed"], f"self-test failed: {failed}")
    return data


def loaded(data):
    return {Path(item["file"].replace("\\", "/")).name: item["sha256"]
            for item in data["checks"]["loaded_libraries"]["detail"]["modules"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--replace-qt", type=Path, help="a Qt 6.12 MSVC 2022 x64 folder with bin/ and plugins/")
    args = parser.parse_args()
    archive = args.archive.resolve()
    results = {"archive": check_archive(archive)}
    with tempfile.TemporaryDirectory(prefix="sumire-verify-") as temporary:
        target = Path(temporary) / "展開 テスト フォルダー"
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(target)
        folder = target / NAME
        results["qt_files"] = check_qt_matches_wheels(folder)
        data = self_test(folder, Path(temporary) / "self-test")
        results["self_test"] = {name: check["ok"] for name, check in data["checks"].items()}
        results["loaded_qt"] = {name: digest for name, digest in loaded(data).items() if name.lower().startswith("qt6")}
        results["environment"] = data["checks"]["environment"]["detail"]
        results["interfaces"] = {name: {key: value for key, value in detail.items()
                                        if key in ("ok", "font_in_use", "device_pixel_ratio", "kana_left",
                                                   "buttons_narrower_than_text", "qt_translation", "style")}
                                 for name, detail in data["checks"]["interfaces"]["detail"].items()}
        shutil.copytree(Path(temporary) / "self-test", args.report.parent / "self-test-extracted", dirs_exist_ok=True)
        if args.replace_qt:
            replaced = {}
            for source, destination in QT_REPLACEMENTS.items():
                path = args.replace_qt / source
                require(path.is_file(), f"{path} is missing")
                before = sha256(folder / "_internal" / destination)
                shutil.copyfile(path, folder / "_internal" / destination)
                replaced[Path(destination).name] = {"before": before, "after": sha256(path)}
                require(before != replaced[Path(destination).name]["after"], f"{destination}: the replacement is the same file")
            data = self_test(folder, Path(temporary) / "self-test-replaced")
            now = loaded(data)
            for name, digests in replaced.items():
                require(now.get(name) == digests["after"], f"{name}: the replaced file was not the one loaded")
            results["qt_replacement"] = {"replaced": replaced, "self_test_passed": data["passed"],
                                         "loaded_after": {name: now[name] for name in now if name.lower().startswith(("qt6", "qwindows"))}}
            shutil.copytree(Path(temporary) / "self-test-replaced", args.report.parent / "self-test-replaced-qt", dirs_exist_ok=True)
    results["passed"] = True
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: {archive.name}")


if __name__ == "__main__":
    main()
