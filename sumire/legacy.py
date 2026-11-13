"""Legacy identifiers retained only to read existing data and share old locks."""
from pathlib import Path

APP_NAME = "Sumi"
SLUG = "sumi"
SETTINGS_ENV = "SUMI_SETTINGS_FILE"
SETTINGS_FILENAME = "sumi-workspace.json"
DATABASE_FILENAME = ".sumi-index.sqlite3"
PROJECT_EXTENSION = ".sumi"


def default_output_folder(folder):
    """Continue existing separate exports rather than losing their edit records."""
    folder = Path(folder)
    current, previous = folder / "Sumīre", folder / APP_NAME
    return previous if not current.exists() and previous.is_dir() else current
