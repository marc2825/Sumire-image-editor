"""The public source export excludes local data and detects stale or edited copies."""
import json

import pytest

from scripts.export_public import export


def source(tmp_path):
    root = tmp_path / "private"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nversion = "0.4.0"\n', encoding="utf-8")
    (root / ".gitignore").write_text("dist/\n", encoding="utf-8")
    (root / "sumire").mkdir()
    (root / "sumire/ui.py").write_text("# current UI\n", encoding="utf-8")
    return root


def test_public_export_preserves_git_and_excludes_private_files(tmp_path):
    root = source(tmp_path)
    for name in (".env", "local.sqlite3", "screenshot.png", "dist/private.py",
                 "AGENTS.md", "RELEASE_STATUS.md", "PUBLISH_CHECKLIST.md",
                 ".git/config", "sumire/.private/data.py", "sumire/__pycache__/private.py"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("private content", encoding="utf-8")
    target = tmp_path / "public" / "Sumīre"
    (target / ".git").mkdir(parents=True)
    (target / ".git/config").write_text("public repository", encoding="utf-8")
    report = export(root, target, private_terms=["private content"])
    assert report["included"] == [".gitignore", "pyproject.toml", "sumire/ui.py"]
    assert (target / ".git/config").read_text(encoding="utf-8") == "public repository"
    assert "*.sqlite3" in (target / ".gitignore").read_text(encoding="utf-8")
    assert export(root, target, check=True)["sha256"] == report["sha256"]
    (root / "sumire/ui.py").write_text("# revised UI\n", encoding="utf-8")
    with pytest.raises(ValueError, match="out of date"):
        export(root, target, check=True)
    export(root, target)
    assert (target / "sumire/ui.py").read_bytes() == (root / "sumire/ui.py").read_bytes()
    assert json.loads((target.parent / "export-report.json").read_text(encoding="utf-8"))["version"] == "0.4.0"


def test_public_export_stops_before_copying_private_text(tmp_path):
    root = source(tmp_path)
    (root / "README.md").write_text("LocalOwnerIdentifier", encoding="utf-8")
    target = tmp_path / "public" / "Sumīre"
    with pytest.raises(ValueError, match="known_personal_identifiers"):
        export(root, target, private_terms=["LocalOwnerIdentifier"])
    assert not target.exists()


def test_public_export_does_not_overwrite_public_edits(tmp_path):
    root = source(tmp_path)
    target = tmp_path / "public" / "Sumīre"
    export(root, target)
    (target / "sumire/ui.py").write_text("# edited public copy\n", encoding="utf-8")
    with pytest.raises(ValueError, match="local changes"):
        export(root, target)
    assert (target / "sumire/ui.py").read_text(encoding="utf-8") == "# edited public copy\n"


def test_public_export_includes_docs_and_public_project_files(tmp_path):
    root = source(tmp_path)
    names = ("docs/USAGE.md", "docs/VALIDATION_SUMMARY.md", "docs/technical/UPSCALING.md",
             "SECURITY.md", "CONTRIBUTING.md", "README.en.md")
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {name}\n", encoding="utf-8")
    (root / "docs/draft.txt").write_text("not a document", encoding="utf-8")
    report = export(root, tmp_path / "public" / "Sumīre")
    for name in names:
        assert name in report["included"]
    assert "docs/draft.txt" not in report["included"]


def test_public_export_includes_bundled_user_help(tmp_path):
    root = source(tmp_path)
    path = root / "sumire/help_docs/USER_GUIDE.md"
    path.parent.mkdir()
    path.write_text("# Public user guide\n", encoding="utf-8")
    target = tmp_path / "public" / "Sumīre"
    report = export(root, target)
    assert report["included"].count("sumire/help_docs/USER_GUIDE.md") == 1
    assert (target / "sumire/help_docs/USER_GUIDE.md").read_bytes() == path.read_bytes()


def test_public_export_leaves_out_development_records_and_keeps_fonts(tmp_path):
    root = source(tmp_path)
    for name in ("AGENTS.md", "RELEASE_STATUS.md", "PUBLISH_CHECKLIST.md", "VALIDATION.md", "QT_REPLACEMENT.md",
                 "scripts/windows-build-requirements.txt", "licenses/NotoSansJP/OFL.txt", "sumire/fonts/OFL.txt"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{name}\n", encoding="utf-8")
    (root / "sumire/fonts/NotoSansJP-Regular.otf").write_bytes(b"OTTO\x00\xff binary font data")
    report = export(root, tmp_path / "public" / "Sumire-image-editor")
    assert {"QT_REPLACEMENT.md", "scripts/windows-build-requirements.txt", "licenses/NotoSansJP/OFL.txt",
            "sumire/fonts/OFL.txt", "sumire/fonts/NotoSansJP-Regular.otf"} <= set(report["included"])
    assert not {"AGENTS.md", "RELEASE_STATUS.md", "PUBLISH_CHECKLIST.md", "VALIDATION.md"} & set(report["included"])


# Built at run time so that this file itself passes the scan of the public export.
PERSONAL = ["C:" + "\\Users\\someone\\Pictures", "/ho" + "me/someone/project/", "/mnt/c/" + "Users/someone/x",
            "contact: someone" + "@mail.example.jp"]


@pytest.mark.parametrize("text", PERSONAL)
def test_public_export_stops_at_personal_paths_and_addresses(tmp_path, text):
    root = source(tmp_path)
    (root / "README.md").write_text(f"see {text}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Public export scan failed"):
        export(root, tmp_path / "public" / "Sumire-image-editor")


def test_placeholder_paths_and_high_dpi_names_are_not_personal(tmp_path):
    root = source(tmp_path)
    (root / "README.md").write_text(r"C:\Users\example\x, %USERPROFILE%, /home/user/, icon@2x.png, a@example.com",
                                    encoding="utf-8")
    export(root, tmp_path / "public" / "Sumire-image-editor")


def test_audit_reports_files_the_export_did_not_write(tmp_path):
    from scripts.export_public import audit
    root = source(tmp_path)
    target = tmp_path / "public" / "Sumire-image-editor"
    export(root, target)
    assert audit(target)["problems"] == []
    (target / "RELEASE_STATUS.md").write_text("internal", encoding="utf-8")
    (target / "notes.md").write_text(PERSONAL[0], encoding="utf-8")
    (target / "shot.png").write_bytes(b"\x89PNG")
    problems = audit(target)["problems"]
    assert "RELEASE_STATUS.md: private_file" in problems and "notes.md: windows_user_path" in problems
    assert "shot.png: image" in problems


def test_windows_package_names_and_pins_follow_the_release():
    from pathlib import Path
    from scripts import fetch_qt_sources, package_windows
    from sumire import DISPLAY_VERSION
    root = Path(__file__).resolve().parents[1]
    assert package_windows.NAME == f"Sumire-v{DISPLAY_VERSION}-win64"
    pins = package_windows.pinned_versions(root)
    assert pins["pyside6-essentials"] == pins["shiboken6"] == fetch_qt_sources.QT
    assert all(f"-{fetch_qt_sources.QT}.tar.xz" in name for name in fetch_qt_sources.ARCHIVES)
    assert not any(required.startswith(pruned) for required in package_windows.REQUIRED for pruned in package_windows.PRUNE)
    assert "QT_REPLACEMENT.md" in package_windows.DOCS and "THIRD_PARTY_NOTICES.md" in package_windows.DOCS
    assert all((root / name).is_file() for name in package_windows.DOCS)


def test_upstream_licence_texts_may_name_their_authors(tmp_path):
    root = source(tmp_path)
    (root / "licenses/Example").mkdir(parents=True)
    (root / "licenses/Example/LICENSE.txt").write_text("Copyright Jean-loup Gailly jloup" + "@gzip.org\n", encoding="utf-8")
    report = export(root, tmp_path / "public" / "Sumire-image-editor")
    assert "licenses/Example/LICENSE.txt" in report["included"]


def test_readme_pictures_are_published_only_without_metadata(tmp_path):
    from PIL import Image, PngImagePlugin
    from scripts.export_public import audit
    root = source(tmp_path)
    (root / "docs/images").mkdir(parents=True)
    Image.new("RGB", (8, 8), "#8877aa").save(root / "docs/images/teaser.png")
    target = tmp_path / "public" / "Sumire-image-editor"
    report = export(root, target)
    assert "docs/images/teaser.png" in report["included"]
    assert (target / "docs/images/teaser.png").read_bytes() == (root / "docs/images/teaser.png").read_bytes()
    assert not [problem for problem in audit(target)["problems"] if "teaser" in problem]
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", "synthetic prompt")
    Image.new("RGB", (8, 8)).save(root / "docs/images/teaser.png", pnginfo=info)
    with pytest.raises(ValueError, match="image_metadata"):
        export(root, target)
    Image.new("RGB", (8, 8)).save(root / "docs/other.png")
    assert "docs/other.png: image" in audit(root)["problems"]
