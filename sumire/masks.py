"""Binary edit masks bound to the exact saved image; never contain photo pixels."""
from .i18n import tr
from contextlib import closing
import io
import json
import sqlite3

from PIL import Image

from .labels import label_key
from .storage import connect_owned, record_path, SCHEMAS


class MaskStore:
    def __init__(self, folder):
        self.path = record_path(folder)

    def get(self, source, digest, size):
        if not self.path.is_file() or self.path.is_symlink():
            return None
        try:
            with closing(connect_owned(self.path)) as connection:
                row = connection.execute("SELECT digest,width,height,png FROM edit_masks WHERE source=?", (label_key(source),)).fetchone()
            if not row or row[0] != digest.hex() or tuple(row[1:3]) != tuple(size) or len(row[3]) > 32 * 1024 * 1024:
                return None
            with Image.open(io.BytesIO(row[3])) as mask:
                if mask.format != "PNG" or mask.mode != "L" or mask.size != size:
                    return None
                mask.load()
                if any(mask.histogram()[1:255]):
                    return None
                return mask.copy()
        except (OSError, ValueError, sqlite3.Error):
            return None

    def store(self, source, digest, mask):
        image = mask.point(lambda value: 255 if value else 0).convert("L")
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        try:
            with closing(connect_owned(self.path)) as connection:
                with connection:
                    connection.execute(f"CREATE TABLE IF NOT EXISTS edit_masks ({SCHEMAS['edit_masks']})")
                    connection.execute("INSERT OR REPLACE INTO edit_masks VALUES (?,?,?,?,?)", (label_key(source), digest.hex(), *image.size, stream.getvalue()))
        except sqlite3.Error:
            raise OSError(tr("加工マスクの記録を保存できません。")) from None

    def store_geometry(self, source, digest, steps, source_digest=None):
        try:
            with closing(connect_owned(self.path)) as connection:
                with connection:
                    connection.execute(f"CREATE TABLE IF NOT EXISTS geometry_edits ({SCHEMAS['geometry_edits']})")
                    connection.execute("INSERT OR REPLACE INTO geometry_edits VALUES (?,?,?)",
                                       (label_key(source), digest.hex(), json.dumps({"source_digest": source_digest.hex() if source_digest else None, "steps": steps})))
        except sqlite3.Error:
            raise OSError(tr("画像の変換手順を記録できません。")) from None

    def get_geometry(self, source, digest, source_digest=None):
        if not self.path.is_file() or self.path.is_symlink():
            return None
        try:
            with closing(connect_owned(self.path)) as connection:
                row = connection.execute("SELECT digest,recipe FROM geometry_edits WHERE source=?", (label_key(source),)).fetchone()
            if not row or row[0] != digest.hex() or len(row[1]) > 1024 * 1024:
                return None
            recipe = json.loads(row[1])
            if not isinstance(recipe, dict) or (source_digest is not None and recipe.get("source_digest") != source_digest.hex()):
                return None
            steps = recipe.get("steps")
            return steps if isinstance(steps, list) and len(steps) <= 4096 and all(isinstance(step, dict) for step in steps) else None
        except (OSError, ValueError, TypeError, sqlite3.Error):
            return None
