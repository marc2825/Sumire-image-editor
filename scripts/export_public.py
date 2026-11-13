"""Export an allowlisted source snapshot without Git history or local user data.

    python -m scripts.export_public                 # build/source/Sumire-image-editor (a clean copy)
    python -m scripts.export_public --check         # the export still matches the source
    python -m scripts.export_public --audit         # scan the exported tree, print a report

Development records (AGENTS.md, RELEASE_STATUS.md, PUBLISH_CHECKLIST.md, the full
VALIDATION.md log) are never exported; users get docs/VALIDATION_SUMMARY.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_NAME = "Sumire-image-editor"
TOP_LEVEL = (".gitignore", "LICENSE", "README.md", "README.en.md", "README.zh-CN.md", "README-Windows.txt",
             "README-Windows.en.txt", "README-Windows.zh-CN.txt", "CHANGELOG.md", "ROADMAP.md",
             "THIRD_PARTY_NOTICES.md", "QT_REPLACEMENT.md", "SECURITY.md", "CONTRIBUTING.md", "pyproject.toml",
             "run_sumire.py")
SOURCE_TYPES = {"sumire": {".py"}, "scripts": {".py", ".pyw", ".ps1", ".txt"},
                "tests": {".py"}, "assets": {".ico"}, "licenses": {".txt", ".md"},
                "sumire/help_docs": {".md"}, "sumire/locales": {".json"}, "sumire/fonts": {".otf", ".txt"},
                "docs": {".md"}}
BINARY = {".ico", ".otf"}
# Upstream licence texts name their authors' addresses; those notices must stay as they are.
UPSTREAM_NOTICES = ("licenses/",)
# Development records stay in the private repository.
PRIVATE_FILES = {"AGENTS.md", "RELEASE_STATUS.md", "PUBLISH_CHECKLIST.md", "VALIDATION.md", "CLAUDE.md"}
PUBLIC_IGNORES = """
# Local settings and credentials
.env
.env.*
!.env.example
.venv*/
.vscode/
.idea/
.agents/
.codex/
.aws/

# User data and metadata recovery records
*.sqlite
*.sqlite3
*.sqlite-*
*.sqlite3-*
*.db
*.db-*
*.sumire
*.sumi
.sumire-rename-*.json
.sumi-rename-*.json
*.log
"""
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github_token": re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})"),
    "cloud_key": re.compile(r"(?:AKIA|ASIA)[A-Z0-9]{16}"),
    "openai_key": re.compile(r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}"),
}
# Personal paths and addresses; placeholders such as C:\Users\example are allowed.
PLACEHOLDERS = r"(?:example|name|user|username|public|default|<[^>]*>|%[a-z]+%|\*)"
PRIVATE_PATTERNS = {
    "windows_user_path": re.compile(r"(?i)[a-z]:[\\/]+users[\\/]+(?!" + PLACEHOLDERS + r"(?:[\\/\s\"']|$))[^\\/\s\"'*]+"),
    "linux_home_path": re.compile(r"/home/(?!" + PLACEHOLDERS + r"/)[a-z0-9_.-]+/"),
    "wsl_user_path": re.compile(r"(?i)/mnt/[a-z]/users/(?!" + PLACEHOLDERS + r"/)[^/\s\"'*]+"),
    # Not "name@2x.png" (Qt's high-DPI image names).
    "email_address": re.compile(r"(?i)\b[a-z0-9._%+-]+@(?!example\.(?:com|org|net)\b|\d+x\.)[a-z0-9.-]+\.[a-z]{2,}\b"),
}

def scanned_patterns(name):
    patterns = {**SECRET_PATTERNS, **PRIVATE_PATTERNS}
    if name.startswith(UPSTREAM_NOTICES):
        del patterns["email_address"]
    return patterns


def digest(data):
    return hashlib.sha256(data).hexdigest()


def source_files(root):
    files = [Path(name) for name in TOP_LEVEL if (root / name).is_file()]
    for directory, suffixes in SOURCE_TYPES.items():
        for path in (root / directory).rglob("*"):
            relative = path.relative_to(root)
            if path.is_file() and path.suffix in suffixes and not any(
                    part.startswith(".") or part == "__pycache__" for part in relative.parts):
                if path.is_symlink():
                    raise ValueError(f"Symlink is not a public source file: {relative}")
                files.append(relative)
    return sorted(files, key=lambda path: path.as_posix())


def export(root, destination, *, check=False, private_terms=()):
    root, destination = root.resolve(), destination.resolve()
    if destination == root or root.is_relative_to(destination):
        raise ValueError("The export destination must not contain the source repository.")
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    files = source_files(root)
    content = {path.as_posix(): (root / path).read_bytes() for path in files}
    ignore = destination / ".gitignore"
    content[".gitignore"] = (ignore.read_bytes() if ignore.exists() else
                             content[".gitignore"] + PUBLIC_IGNORES.encode("utf-8"))
    findings = []
    for name, data in content.items():
        if Path(name).suffix in BINARY:
            continue
        text = data.decode("utf-8-sig")
        if any(term.casefold() in text.casefold() for term in private_terms if term):
            findings.append(f"{name}: known_personal_identifiers")
        findings.extend(f"{name}: {kind}" for kind, pattern in scanned_patterns(name).items() if pattern.search(text))
    if findings:
        raise ValueError("Public export scan failed (values omitted):\n" + "\n".join(findings))
    report_path = destination.parent / "export-report.json"
    previous = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    stale = set(previous.get("included", ())) - set(content)
    changed = [name for name, data in content.items()
               if not (destination / name).is_file() or (destination / name).read_bytes() != data]
    report = {
        "project": "Sumīre", "identifier": "sumire", "version": version,
        "source_files": len(content), "included": sorted(content),
        "sha256": {name: digest(data) for name, data in sorted(content.items())},
        "modified_files": [".gitignore"],
        "excluded": ["original Git history and remotes", "virtual environments", "build outputs",
                     "test artifacts", "user data", "local settings"],
        "scan": {"known_personal_identifiers": "no matches" if private_terms else "not supplied",
                 **{name: "no matches" for name in {**SECRET_PATTERNS, **PRIVATE_PATTERNS}}},
    }
    if check:
        # A check may omit the private terms used during the original export.
        comparable = {**previous, "scan": report["scan"]}
        if changed or any((destination / name).exists() for name in stale) or comparable != report:
            raise ValueError("Public export is out of date: " + ", ".join(changed or ["export-report.json"]))
        return report
    # Do not overwrite changes made directly in the public tree since its last export.
    for name in set(changed) | stale:
        path = destination / name
        if name == ".gitignore" or not path.exists():
            continue
        old_hash = previous.get("sha256", {}).get(name)
        if old_hash is None or not path.is_file() or digest(path.read_bytes()) != old_hash:
            raise ValueError(f"Public file has local changes; export stopped: {name}")
    for name in stale:
        path = destination / name
        if path.is_file():
            path.unlink()
    for name, data in content.items():
        path = destination / name
        if path.is_symlink():
            raise ValueError(f"Public destination is a symlink: {name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def published_files(destination):
    """In a Git repository, the files Git would publish (tracked, or new and not ignored); else every file."""
    if (destination / ".git").exists():
        import subprocess
        listed = subprocess.run(["git", "-C", str(destination), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                                capture_output=True, check=True).stdout.decode("utf-8").split("\0")
        return sorted(destination / name for name in listed if name)
    return sorted(path for path in destination.rglob("*") if path.relative_to(destination).parts[0] != ".git")


def audit(destination, private_terms=()):
    """Scan an exported tree or the repository: everything that would be published."""
    destination = destination.resolve()
    files, problems = [], []
    for path in published_files(destination):
        relative = path.relative_to(destination).as_posix()
        if path.is_symlink():
            problems.append(f"{relative}: symlink")
            continue
        if not path.is_file():
            continue
        files.append(path)
        name = path.name
        if name in PRIVATE_FILES or re.search(r"(?i)\.(sqlite3?|db|log|env|sumire|sumi)(-.*)?$", name) or name == ".env":
            problems.append(f"{relative}: private_file")
        if "__pycache__" in path.parts or name.endswith((".pyc", ".pyo")):
            problems.append(f"{relative}: cache")
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".bmp", ".tif", ".tiff", ".heic"}:
            problems.append(f"{relative}: image")
        if path.suffix in BINARY:
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            problems.append(f"{relative}: unexpected_binary")
            continue
        if any(term.casefold() in text.casefold() for term in private_terms if term):
            problems.append(f"{relative}: known_personal_identifiers")
        problems.extend(f"{relative}: {kind}" for kind, pattern in scanned_patterns(relative).items() if pattern.search(text))
    git = destination / ".git"
    return {
        "tree": destination.name, "files": len(files), "bytes": sum(path.stat().st_size for path in files),
        "binary_files": {path.relative_to(destination).as_posix(): digest(path.read_bytes())
                         for path in files if path.suffix in BINARY},
        "git": "present (check author, e-mail and remotes before pushing)" if git.exists() else "none (initialise a new repository)",
        "required_present": {name: (destination / name).is_file() for name in
                             ("LICENSE", "README.md", "CHANGELOG.md", "THIRD_PARTY_NOTICES.md", "QT_REPLACEMENT.md",
                              "pyproject.toml", "scripts/build_windows.ps1", "scripts/windows-build-requirements.txt",
                              "licenses/NotoSansJP/OFL.txt", "licenses/Qt/LGPL-3.0-only.txt", "sumire/fonts/OFL.txt")},
        "problems": problems,
        "checked": ["private development records", "SQLite/log/env files", "caches", "images", "symlinks",
                    *SECRET_PATTERNS, *PRIVATE_PATTERNS, "known personal identifiers (when supplied)"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--destination", type=Path, default=ROOT / "build" / "source" / PUBLIC_NAME)
    parser.add_argument("--check", action="store_true", help="Only verify the source, export and manifest agree")
    parser.add_argument("--audit", action="store_true", help="Scan the exported tree and print a JSON report")
    parser.add_argument("--private-term", action="append", default=[], help="Additional private text to reject (not recorded)")
    args = parser.parse_args()
    try:
        if args.audit:
            report = audit(args.destination, args.private_term)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            if report["problems"] or not all(report["required_present"].values()):
                parser.exit(1, "Audit found problems.\n")
            return
        report = export(ROOT, args.destination, check=args.check, private_terms=args.private_term)
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")
    print(f"{'Verified' if args.check else 'Exported'} Sumīre {report['version']}: {report['source_files']} files (no Git history copied)")


if __name__ == "__main__":
    main()
