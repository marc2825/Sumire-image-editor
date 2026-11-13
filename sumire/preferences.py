"""Atomic application settings; image pixels and prompts are never persisted."""
import json
import os
from pathlib import Path
import tempfile

from PySide6.QtCore import QStandardPaths

from . import legacy


def settings_path():
    override = os.environ.get("SUMIRE_SETTINGS_FILE") or os.environ.get(legacy.SETTINGS_ENV)
    if override:
        return Path(override)
    folder = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation))
    current = folder / "sumire-workspace.json"
    if current.exists():
        return current
    # Reuse the old profile in place so its record databases and instance lock
    # remain together. Prefer the new profile whenever it already exists.
    candidates = [folder / legacy.SETTINGS_FILENAME,
                  folder.parent / legacy.APP_NAME / legacy.SETTINGS_FILENAME,
                  folder.parent.parent / legacy.APP_NAME / legacy.APP_NAME / legacy.SETTINGS_FILENAME]
    return next((path for path in candidates if path.is_file()), current)


class Preferences:
    def __init__(self, path=None):
        self.path = Path(path) if path else settings_path()
        self.data = {}
        try:
            if self.path.stat().st_size < 8 * 1024 * 1024:
                value = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(value, dict):
                    self.data = value
        except (OSError, ValueError):
            pass

    def save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".sumire-settings-", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            self.data = data
        finally:
            Path(name).unlink(missing_ok=True)
