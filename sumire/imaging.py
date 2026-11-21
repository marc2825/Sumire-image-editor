"""Qt-independent, original-resolution image operations and bounded undo history."""
from __future__ import annotations
from .i18n import tr

import io
import json
import math
import warnings
import zlib
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageCms, ImageDraw, ImageFilter, ImageOps, UnidentifiedImageError

from .stealth import remove_stealth

MAX_PIXELS = 24_000_000
MAX_DIMENSION = 32_768
MAX_INPUT_BYTES = 256 * 1024 * 1024
SUPPORTED = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".avif", ".tif", ".tiff", ".gif"}
FORMATS = {"PNG", "JPEG", "WEBP", "BMP", "AVIF", "TIFF", "GIF"}
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def _enable_heif():
    """Use a separately installed HEIF plugin; none is bundled (codec licences differ).

    pillow-heif reads and writes, pi-heif only reads.
    """
    import importlib
    for name in ("pillow_heif", "pi_heif"):
        try:
            module = importlib.import_module(name)
            module.register_heif_opener()
        except Exception:
            continue
        SUPPORTED.update({".heic", ".heif"})
        FORMATS.add("HEIF")
        return name
    return None


HEIF_PLUGIN = _enable_heif()
HEIF_WRITABLE = HEIF_PLUGIN == "pillow_heif"


def format_names():
    """User-facing list of readable formats."""
    return " / ".join(["PNG", "JPEG", "WebP", "AVIF", "BMP", "TIFF", "GIF"] + (["HEIC"] if HEIF_PLUGIN else []))


class ImageProblem(ValueError):
    """User-facing error. Never includes source metadata or decoder messages."""


# Formats without transparency (JPEG, BMP, …) show transparent parts on this colour.
FLAT_BACKGROUND = "#ffffff"


def flatten(pixels: Image.Image, background: str = FLAT_BACKGROUND) -> Image.Image:
    """RGBA pixels on an opaque background, for a format without transparency."""
    flat = Image.new("RGB", pixels.size, background)
    flat.paste(pixels, mask=pixels.getchannel("A"))
    return flat


def clean_pixels(image: Image.Image) -> Image.Image:
    """Create a new object using pixels alone, including no inherited info/EXIF."""
    rgba = image if image.mode == "RGBA" else image.convert("RGBA")
    result = Image.new("RGBA", rgba.size)
    result.paste(rgba)
    return result


def validate_opened(image):
    if image.format not in FORMATS:
        raise ImageProblem(tr("対応形式は {format_names} です。").format(format_names=format_names()))
    if getattr(image, "n_frames", 1) != 1:
        raise ImageProblem(tr("アニメーション画像には対応していません。"))
    if image.width * image.height > MAX_PIXELS or max(image.size) > MAX_DIMENSION:
        raise ImageProblem(tr("画像が大きすぎます。上限は2,400万画素・1辺32,768pxです。"))


def eight_bit(image):
    """16-bit greyscale scaled to 8 bits (a plain conversion would clip everything above 255 to white)."""
    if image.mode in {"I;16", "I;16L", "I;16B", "I;16N"}:
        image = image.convert("I")
    if image.mode == "I":
        return image.point(lambda value: value / 256).convert("L")
    return image


def srgb_pixels(image):
    profile = image.info.get("icc_profile")
    if not profile:
        return image
    try:
        alpha = image.convert("RGBA").getchannel("A")
        color = image if image.mode in {"RGB", "CMYK", "LAB", "L"} else image.convert("RGB")
        result = ImageCms.profileToProfile(color, ImageCms.ImageCmsProfile(io.BytesIO(profile)),
                                          ImageCms.createProfile("sRGB"), outputMode="RGB")
        result.putalpha(alpha)
        return result
    except (ImageCms.PyCMSError, OSError, ValueError):
        raise ImageProblem(tr("ICCプロファイルをsRGBへ変換できません。元画像を確認してください。")) from None


def _source(path):
    """What Image.open reads, and the bytes when they come from a ZIP (``archive.ArchiveEntry``)."""
    from .archive import ArchiveEntry, read_entry
    if isinstance(path, ArchiveEntry):
        raw = read_entry(path)
        return io.BytesIO(raw), raw
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ImageProblem(tr("ファイルが大きすぎます。入力の上限は256MiBです。"))
    return path, None


def load_image(path, found: list | None = None) -> Image.Image:
    """Clean pixels of ``path`` (a file or an image in a ZIP); ``found`` receives its metadata categories."""
    try:
        source, raw = _source(path)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source) as opened:
                validate_opened(opened)
                opened.load()
                if found is not None:
                    from .metadata import categories
                    found.extend(categories(opened, None if raw is not None else path, raw=raw))
                # Stealth data follows the encoded pixel order, so remove it
                # before Orientation/ICC transforms or any editing can hide its header.
                image = ImageOps.exif_transpose(remove_stealth(eight_bit(opened)))
                pixels = clean_pixels(srgb_pixels(image))
                pixels.format = opened.format
                return pixels
    except ImageProblem:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageProblem(tr("画像が大きすぎます。上限は2,400万画素です。")) from None
    except (OSError, ValueError, SyntaxError, UnidentifiedImageError):
        raise ImageProblem(tr("画像を読み込めません。形式・破損・アクセス権を確認してください。")) from None


def load_thumbnail(path, size=(256, 256)) -> Image.Image:
    """Display-only decode: reduce before RGBA allocation; never used for export."""
    try:
        source, _ = _source(path)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source) as opened:
                validate_opened(opened)
                # The JPEG decoder can produce a small preview directly. Orientation
                # is applied afterwards; request a square so rotated images fit too.
                if opened.format == "JPEG":
                    opened.draft("RGB", (max(size), max(size)))
                opened.load()
                image = remove_stealth(eight_bit(opened))
                image = ImageOps.exif_transpose(image)
                # Convert tagged colour before resampling to preserve appearance.
                image = srgb_pixels(image)
                if image.mode in {"P", "1"}:
                    image = image.convert("RGBA")
                image.thumbnail(size, Image.Resampling.LANCZOS)
                return clean_pixels(remove_stealth(image))
    except ImageProblem:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageProblem(tr("画像が大きすぎます。上限は2,400万画素です。")) from None
    except (OSError, ValueError, SyntaxError, UnidentifiedImageError):
        raise ImageProblem(tr("画像を読み込めません。形式・破損・アクセス権を確認してください。")) from None


@dataclass(frozen=True)
class Tool:
    mode: str = "mosaic"
    diameter: int = 90
    strength: int = 20
    color: str = "#000000"
    expansion: int = 1
    opacity: int = 100

    @property
    def effect_key(self):
        if self.mode == "fill":
            return self.mode, self.color, self.opacity
        if self.mode == "erase":
            return (self.mode,)
        return self.mode, self.strength


def make_effect(image: Image.Image, tool: Tool) -> Image.Image:
    if tool.mode == "fill":
        try:
            fill = Image.new("RGBA", image.size, tool.color)
        except ValueError:  # the colour picker never gives one; keep other callers on ImageProblem (issue #4)
            raise ImageProblem(tr("塗りつぶしの色が正しくありません。")) from None
        opacity = max(0, min(100, tool.opacity))
        if opacity == 100:
            return fill
        if opacity == 0:
            return image.copy()
        fill.putalpha(round(255 * opacity / 100))
        return Image.alpha_composite(image, fill)
    # Averaged with premultiplied alpha: a transparent pixel adds nothing (no dark fringes or black
    # blocks), its stored colour stays hidden, and the result keeps the image's transparency.
    source = image.convert("RGBA").convert("RGBa")
    if tool.mode == "blur":
        result = source.filter(ImageFilter.GaussianBlur(max(1, tool.strength)))
    elif tool.mode == "mosaic":
        block = max(2, tool.strength)
        width, height = image.size
        cols, rows = math.ceil(width / block), math.ceil(height / block)
        # Edge replication avoids dark pixels from padding and fixes the block grid.
        padded = Image.new("RGBa", (cols * block, rows * block))
        padded.paste(source, (0, 0))
        if padded.width > width:
            padded.paste(source.crop((width - 1, 0, width, height)).resize((padded.width - width, height)), (width, 0))
        if padded.height > height:
            padded.paste(padded.crop((0, height - 1, padded.width, height)).resize((padded.width, padded.height - height)), (0, height))
        result = padded.resize((cols, rows), Image.Resampling.BOX).resize(padded.size, Image.Resampling.NEAREST).crop((0, 0, width, height))
    else:
        raise ValueError("Unknown tool")
    return result.convert("RGBA")


def brush_segment(mask: Image.Image, start: tuple[float, float], end: tuple[float, float], diameter: int) -> None:
    """A capsule joins events without gaps, independent of display zoom."""
    draw = ImageDraw.Draw(mask)
    radius = max(1, diameter) / 2
    draw.line((start, end), fill=255, width=max(1, diameter))
    for x, y in (start, end):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)


def selection_mask(size: tuple[int, int], start: tuple[float, float], end: tuple[float, float], shape: str, expansion: int = 0) -> Image.Image:
    mask = Image.new("L", size)
    x0, x1 = sorted((start[0], end[0]))
    y0, y1 = sorted((start[1], end[1]))
    bounds = (x0 - expansion, y0 - expansion, x1 + expansion, y1 + expansion)
    draw = ImageDraw.Draw(mask)
    if shape == "rectangle":
        draw.rectangle(bounds, fill=255)
    elif shape == "ellipse":
        draw.ellipse(bounds, fill=255)
    else:
        raise ValueError("Unknown selection")
    return mask


def region_mask(size, points, shape, expansion=0, invert=False):
    """Hard selection shared by preview, edit masks and export."""
    if shape in {"rectangle", "ellipse"}:
        mask = selection_mask(size, points[0], points[-1], shape)
    elif shape in {"polygon", "lasso"}:
        mask = Image.new("L", size)
        if len(points) < 3:
            return mask
        ImageDraw.Draw(mask).polygon(points, fill=255)
    else:
        raise ValueError("Unknown selection")
    if invert:
        mask = ImageChops.invert(mask)
    return mask.filter(ImageFilter.MaxFilter(expansion * 2 + 1)) if expansion else mask


@dataclass
class Patch:
    box: tuple[int, int, int, int]
    before: bytes
    after: bytes
    before_revision: int
    after_revision: int
    before_mask: bytes = b""
    after_mask: bytes = b""
    edited_before: bool | None = None
    edited_after: bool | None = None

    @property
    def memory(self) -> int:
        return len(self.before) + len(self.after) + len(self.before_mask) + len(self.after_mask)


@dataclass
class FullPatch:
    before: tuple
    after: tuple
    before_revision: int
    after_revision: int

    @property
    def memory(self):
        return sum({id(data): len(data) for state in (self.before, self.after) for data in state[1:4]}.values())


class Document:
    """One image's pixels/history. Oldest patches are evicted, never mixed across files."""
    def __init__(self, path: Path, image: Image.Image, history_limit: int = 48 * 1024 * 1024):
        self.path = path
        self.source_format = image.format
        self.source_digest: bytes | None = None
        self.geometry_source_digest = None
        self.original = clean_pixels(image)
        self.initial_original = self.original
        self.geometry_edited = False
        self.geometry_steps: list = []
        self.image = clean_pixels(image)
        self.edit_mask = Image.new("L", image.size)
        self.history_limit = history_limit
        self.undo_stack: list[Patch] = []
        self.redo_stack: list[Patch] = []
        self.revision = 0
        self._sequence = 0
        self.saved_revision: int | None = None
        self.output: Path | None = None
        self.original_edited = False
        self.original_edit_status_known = True
        self.restored_edited: bool | None = None
        self.edited = False

    def update_edited(self, box=None) -> None:
        """Whether the image differs from the original. ``box``, the only area just changed, saves
        comparing the whole image: only an edited image that may have just returned to the original
        needs the full comparison. Called by image workers, never during a UI paint."""
        if self.revision == 0 and self.restored_edited is not None:
            self.edited = self.restored_edited
        elif self.original_edited or self.geometry_edited or self.original.size != self.image.size:
            self.edited = True
        elif box is not None and self._differs(box):
            self.edited = True
        elif box is not None and not self.edited:
            self.edited = False  # the rest was the original already, and the changed area is too
        else:
            self.edited = self._differs(None)

    def _differs(self, box) -> bool:
        # Include RGB changes even when alpha itself is unchanged (RGBA getbbox defaults to alpha).
        original, image = (self.original, self.image) if box is None else (self.original.crop(box), self.image.crop(box))
        return ImageChops.difference(original, image).getbbox(alpha_only=False) is not None

    def restore_edit_state(self, edited: bool | None, *, overwrite: bool):
        self.restored_edited = edited
        self.original_edited = overwrite and edited is True
        self.original_edit_status_known = not (overwrite and edited is None)
        self.update_edited()

    @property
    def edit_state(self) -> bool | None:
        return self.edited if self.edited or self.original_edit_status_known else None

    @property
    def dirty(self) -> bool:
        return self.saved_revision != self.revision and (self.revision != 0 or self.saved_revision is not None)

    @property
    def memory(self) -> int:
        return (self.image.width * self.image.height * 9
                + (self.initial_original.width * self.initial_original.height * 4 if self.initial_original is not self.original else 0)
                + sum(p.memory for p in self.undo_stack + self.redo_stack))

    def snapshot(self):
        return (self.image.size, zlib.compress(self.image.tobytes(), 1), zlib.compress(self.original.tobytes(), 1),
                zlib.compress(self.edit_mask.tobytes(), 1), self.geometry_edited, self.edited, json.dumps(self.geometry_steps))

    def replace(self, image, mask, original=None, *, geometry=None, steps=None):
        """Prepare the complete patch before publishing any new dimensions."""
        original = original if original is not None else self.original
        if image.size != mask.size or image.size != original.size:
            raise ImageProblem(tr("画像とマスクの寸法が一致しません。"))
        before = self.snapshot()
        geometry = self.geometry_edited if geometry is None else geometry
        steps = self.geometry_steps if steps is None else steps
        edited = self.original_edited or geometry or ImageChops.difference(original, image).getbbox(alpha_only=False) is not None
        original_data = before[2] if original is self.original else zlib.compress(original.tobytes(), 1)
        after = (image.size, zlib.compress(image.tobytes(), 1), original_data,
                 zlib.compress(mask.tobytes(), 1), geometry, edited, json.dumps(steps))
        if before[:5] == after[:5]:
            return False
        patch = FullPatch(before, after, self.revision, self._sequence + 1)
        self.image, self.original, self.edit_mask = image, original, mask
        self.geometry_edited, self.edited = geometry, edited
        self.geometry_steps = steps
        self.revision = self._sequence = patch.after_revision
        self.undo_stack.append(patch)
        self.redo_stack.clear()
        while len(self.undo_stack) > 80 or (len(self.undo_stack) > 1 and sum(p.memory for p in self.undo_stack) > self.history_limit):
            self.undo_stack.pop(0)
        return True

    def restore_full(self, state, revision):
        size, pixels, original, mask, geometry, edited, recipe = state
        image = Image.frombytes("RGBA", size, zlib.decompress(pixels))
        base = Image.frombytes("RGBA", size, zlib.decompress(original))
        mask = Image.frombytes("L", size, zlib.decompress(mask))
        self.image, self.original, self.edit_mask = image, base, mask
        self.geometry_edited, self.edited, self.revision = geometry, edited, revision
        self.geometry_steps = json.loads(recipe)

    def commit(self, before: Image.Image, box: tuple[int, int, int, int] | None, before_mask: Image.Image | None = None, *, cropped=False) -> bool:
        if box is None:
            return False
        old = (before if cropped else before.crop(box)).tobytes()
        new = self.image.crop(box).tobytes()
        old_mask = (before_mask if cropped else before_mask.crop(box)).tobytes() if before_mask is not None else b""
        new_mask = self.edit_mask.crop(box).tobytes() if before_mask is not None else b""
        if old == new and old_mask == new_mask:
            return False
        edited_before = self.edited
        self._sequence += 1
        previous_revision = self.revision
        self.revision = self._sequence
        if old != new:
            self.update_edited(box)
        self.undo_stack.append(Patch(box, zlib.compress(old, 1), zlib.compress(new, 1), previous_revision, self.revision,
                                     zlib.compress(old_mask, 1) if old_mask else b"", zlib.compress(new_mask, 1) if new_mask else b"",
                                     edited_before, self.edited))
        self.redo_stack.clear()
        while len(self.undo_stack) > 80 or (len(self.undo_stack) > 1 and sum(p.memory for p in self.undo_stack) > self.history_limit):
            self.undo_stack.pop(0)
        return True

    def _restore(self, patch: Patch, data: bytes, revision: int, mask: bytes, edited: bool | None) -> None:
        x0, y0, x1, y1 = patch.box
        region = Image.frombytes("RGBA", (x1 - x0, y1 - y0), zlib.decompress(data))
        self.image.paste(region, (x0, y0))
        if mask:
            self.edit_mask.paste(Image.frombytes("L", region.size, zlib.decompress(mask)), (x0, y0))
        self.revision = revision
        if edited is None:
            self.update_edited()
        else:
            self.edited = edited

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        patch = self.undo_stack.pop()
        if isinstance(patch, FullPatch):
            self.restore_full(patch.before, patch.before_revision)
        else:
            self._restore(patch, patch.before, patch.before_revision, patch.before_mask, patch.edited_before)
        self.redo_stack.append(patch)
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        patch = self.redo_stack.pop()
        if isinstance(patch, FullPatch):
            self.restore_full(patch.after, patch.after_revision)
        else:
            self._restore(patch, patch.after, patch.after_revision, patch.after_mask, patch.edited_after)
        self.undo_stack.append(patch)
        return True

    def reset_edits(self) -> bool:
        """Restore the held original and clear the mask as one undoable edit."""
        if self.geometry_edited or self.original.size != self.initial_original.size:
            return self.replace(clean_pixels(self.initial_original), Image.new("L", self.initial_original.size),
                                self.initial_original, geometry=False, steps=[])
        before, before_mask = self.image, self.edit_mask
        state = self.revision, self._sequence, self.edited, list(self.undo_stack), list(self.redo_stack)
        try:
            self.image = clean_pixels(self.original)
            self.edit_mask = Image.new("L", self.original.size)
            return self.commit(before, (0, 0, *self.original.size), before_mask)
        except Exception:
            self.image, self.edit_mask = before, before_mask
            self.revision, self._sequence, self.edited, self.undo_stack, self.redo_stack = state
            raise


class Stroke:
    """Full-resolution hard mask; preview and export share the exact same pixels."""
    def __init__(self, document: Document, tool: Tool, effect: Image.Image | None = None):
        self.document = document
        self.tool = tool
        self.tiles: dict = {}
        self.effect = document.original if tool.mode == "erase" else effect if effect is not None else make_effect(document.image, tool)
        self.mask = Image.new("L", document.image.size)
        self.last: tuple[float, float] | None = None
        self.box: tuple[int, int, int, int] | None = None

    def add(self, point: tuple[float, float]) -> tuple[int, int, int, int] | None:
        start = self.last or point
        diameter = self.tool.diameter + self.tool.expansion * 2
        brush_segment(self.mask, start, point, diameter)
        radius = diameter / 2 + 2
        w, h = self.document.image.size
        box = (min(w, max(0, math.floor(min(start[0], point[0]) - radius))), min(h, max(0, math.floor(min(start[1], point[1]) - radius))),
               max(0, min(w, math.ceil(max(start[0], point[0]) + radius))), max(0, min(h, math.ceil(max(start[1], point[1]) + radius))))
        self.last = point
        if box[2] <= box[0] or box[3] <= box[1]:
            return None
        self.apply(box)
        return box

    def apply(self, box: tuple[int, int, int, int] | None = None) -> None:
        box = box or self.mask.getbbox()
        if box is None or box[2] <= box[0] or box[3] <= box[1]:
            return
        # Save each touched tile once, before any overlapping segment mutates it.
        width, height = self.document.image.size
        for y in range(box[1] // 128, (box[3] - 1) // 128 + 1):
            for x in range(box[0] // 128, (box[2] - 1) // 128 + 1):
                key = (x * 128, y * 128, min(width, (x + 1) * 128), min(height, (y + 1) * 128))
                if key not in self.tiles:
                    self.tiles[key] = self.document.image.crop(key), self.document.edit_mask.crop(key)
        self.document.image.paste(self.effect.crop(box), box[:2], self.mask.crop(box))
        if self.tool.mode == "erase":
            self.document.edit_mask.paste(0, box, self.mask.crop(box))
        elif self.tool.mode != "fill" or self.tool.opacity > 0:
            self.document.edit_mask.paste(255, box, self.mask.crop(box))
        if self.box is None:
            self.box = box
        else:
            a, b, c, d = self.box
            self.box = min(a, box[0]), min(b, box[1]), max(c, box[2]), max(d, box[3])

    def finish(self) -> bool:
        if self.box is None:
            return False
        before = self.document.image.crop(self.box)
        before_mask = self.document.edit_mask.crop(self.box)
        for tile, (pixels, mask) in self.tiles.items():
            before.paste(pixels, (tile[0] - self.box[0], tile[1] - self.box[1]))
            before_mask.paste(mask, (tile[0] - self.box[0], tile[1] - self.box[1]))
        changed = self.document.commit(before, self.box, before_mask, cropped=True)
        self.tiles.clear()
        return changed

    def cancel(self) -> None:
        for box, (pixels, mask) in self.tiles.items():
            self.document.image.paste(pixels, box[:2])
            self.document.edit_mask.paste(mask, box[:2])
        self.tiles.clear()

