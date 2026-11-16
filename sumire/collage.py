"""Arrange several images into one picture (side by side, stacked or in a grid)."""
from __future__ import annotations
from .i18n import tr

from dataclasses import dataclass
import math
from statistics import median

from PIL import Image

from .editing import lanczos3_resize
from .imaging import MAX_DIMENSION, MAX_PIXELS, ImageProblem, clean_pixels

MAX_COLLAGE = 16


@dataclass(frozen=True)
class CollageSpec:
    rows: int
    columns: int
    fit: str = "contain"          # contain: whole image with margins / cover: fill and crop
    gap: int = 0                  # pixels between cells and around the edge
    background: str | None = "#ffffff"   # None = transparent


def collage_layouts(count):
    """(title, rows, columns) choices for ``count`` images, the most natural first."""
    if count < 1:
        return []
    if count == 1:
        return [(tr("1枚（余白・背景を付ける、切り抜く）"), 1, 1)]
    grids = []
    for columns in range(2, 5):
        rows = math.ceil(count / columns)
        empty = rows * columns - count
        if rows >= 2 and columns < count and empty < min(rows, columns):
            title = tr("{value}分割（{columns}×{rows}）").format(value=rows * columns, columns=columns, rows=rows) + (tr(" · 空き{empty}枠").format(empty=empty) if empty else "")
            grids.append((title, rows, columns))
    lines = [(tr("左右に並べる（横{count}分割）").format(count=count), 1, count), (tr("上下に並べる（縦{count}分割）").format(count=count), count, 1)]
    # Four or more images read best as a near-square grid.
    grids.sort(key=lambda item: (abs(item[1] - item[2]), item[1] * item[2] - count))
    return grids + lines if count >= 4 and grids else lines + grids


def _cell_and_canvas(sizes, spec):
    if not 1 <= len(sizes) <= MAX_COLLAGE:
        raise ImageProblem(tr("コラージュにできるのは1〜{MAX_COLLAGE}枚です。").format(MAX_COLLAGE=MAX_COLLAGE))
    if spec.rows * spec.columns < len(sizes) or spec.fit not in {"contain", "cover"} or not 0 <= spec.gap <= 1000:
        raise ImageProblem(tr("コラージュの並べ方を確認してください。"))
    cell_w = max(1, round(median(width for width, _ in sizes)))
    cell_h = max(1, round(median(height for _, height in sizes)))
    gap = spec.gap
    width = spec.columns * cell_w + (spec.columns + 1) * gap
    height = spec.rows * cell_h + (spec.rows + 1) * gap
    scale = min(1.0, MAX_DIMENSION / width, MAX_DIMENSION / height, math.sqrt(MAX_PIXELS / (width * height)))
    if scale < 1:
        cell_w, cell_h, gap = max(1, int(cell_w * scale)), max(1, int(cell_h * scale)), int(gap * scale)
        width = spec.columns * cell_w + (spec.columns + 1) * gap
        height = spec.rows * cell_h + (spec.rows + 1) * gap
    return (cell_w, cell_h, gap), (width, height)


def cell_layout(sizes, spec, cell_scale=1.0):
    """(cell width, cell height, gap) exactly as ``render_collage`` lays the cells out."""
    (cell_w, cell_h, gap), _ = _cell_and_canvas(sizes, spec)
    if cell_scale != 1:
        cell_w, cell_h = max(1, round(cell_w * cell_scale)), max(1, round(cell_h * cell_scale))
        gap = round(gap * cell_scale)
    return cell_w, cell_h, gap


def render_collage(images, spec: CollageSpec, *, measure_only=False, cell_scale=1.0, sizes=None):
    """Return the collage (RGBA), or only its size with ``measure_only``.

    ``sizes`` lets a preview lay out small thumbnails exactly like the originals.
    """
    sizes = sizes or [image.size for image in images]
    (cell_w, cell_h, gap), size = _cell_and_canvas(sizes, spec)
    if measure_only:
        return size
    if cell_scale != 1:
        cell_w, cell_h, gap = cell_layout(sizes, spec, cell_scale)
        size = (spec.columns * cell_w + (spec.columns + 1) * gap, spec.rows * cell_h + (spec.rows + 1) * gap)
    canvas = Image.new("RGBA", size, spec.background or (0, 0, 0, 0))
    for number, image in enumerate(images):
        row, column = divmod(number, spec.columns)
        left, top = gap + column * (cell_w + gap), gap + row * (cell_h + gap)
        pixels = clean_pixels(image)
        if spec.fit == "contain":
            scale = min(cell_w / pixels.width, cell_h / pixels.height)
        else:
            scale = max(cell_w / pixels.width, cell_h / pixels.height)
        target = (max(1, round(pixels.width * scale)), max(1, round(pixels.height * scale)))
        resized = lanczos3_resize(pixels, target) if target != pixels.size else pixels
        if spec.fit == "cover":
            x, y = (resized.width - cell_w) // 2, (resized.height - cell_h) // 2
            resized = resized.crop((x, y, x + cell_w, y + cell_h))
            canvas.alpha_composite(resized, (left, top))
        else:
            canvas.alpha_composite(resized, (left + (cell_w - resized.width) // 2, top + (cell_h - resized.height) // 2))
    return canvas


def grid_pieces(sizes, spec):
    """Where ``render_collage`` puts each image, for showing and editing it on a canvas.

    Returns ([(x, y, scale, cell)], canvas size): the top-left of each image and
    its scale in output pixels, and the cell it is clipped to ("cover" overflows it).
    """
    (cell_w, cell_h, gap), size = _cell_and_canvas(sizes, spec)
    pieces = []
    for number, (width, height) in enumerate(sizes):
        row, column = divmod(number, spec.columns)
        left, top = gap + column * (cell_w + gap), gap + row * (cell_h + gap)
        scale = (min if spec.fit == "contain" else max)(cell_w / width, cell_h / height)
        shown_w, shown_h = max(1, round(width * scale)), max(1, round(height * scale))
        if spec.fit == "contain":
            x, y = left + (cell_w - shown_w) // 2, top + (cell_h - shown_h) // 2
        else:
            x, y = left - (shown_w - cell_w) // 2, top - (shown_h - cell_h) // 2
        pieces.append((x, y, scale, (left, top, cell_w, cell_h)))
    return pieces, size


@dataclass(frozen=True)
class Piece:
    """One image placed freely: the part used and where it goes, in output pixels."""
    crop: tuple            # x, y, width, height in the source image
    x: float               # canvas position of the crop's top-left corner
    y: float
    scale: float           # output pixels per source pixel

    def shown_size(self):
        return max(1, round(self.crop[2] * self.scale)), max(1, round(self.crop[3] * self.scale))


@dataclass(frozen=True)
class FreeLayout:
    size: tuple                       # canvas width, height
    background: str | None            # None = transparent
    pieces: tuple                     # (source index, Piece), back to front


def check_canvas(size):
    width, height = size
    if not (1 <= width <= MAX_DIMENSION and 1 <= height <= MAX_DIMENSION) or width * height > MAX_PIXELS:
        raise ImageProblem(tr("キャンバスは1辺32,768px・合計2,400万画素以内にしてください。"))
    return size


def render_free_collage(images, layout: FreeLayout, cancel=None):
    """The free collage at full size: each piece cropped, scaled with Lanczos3 and
    drawn in order; parts outside the canvas are cut off."""
    from .export import check_cancel
    width, height = check_canvas(layout.size)
    canvas = Image.new("RGBA", (width, height), layout.background or (0, 0, 0, 0))
    for index, piece in layout.pieces:
        check_cancel(cancel)
        x, y, crop_w, crop_h = piece.crop
        source = images[index]
        if crop_w < 1 or crop_h < 1 or x < 0 or y < 0 or x + crop_w > source.width or y + crop_h > source.height:
            raise ImageProblem(tr("切り抜き範囲が画像の外にあります。"))
        shown_w, shown_h = piece.shown_size()
        left, top = round(piece.x), round(piece.y)
        visible = (max(0, left), max(0, top), min(width, left + shown_w), min(height, top + shown_h))
        if visible[0] >= visible[2] or visible[1] >= visible[3]:
            continue
        part = clean_pixels(source).crop((x, y, x + crop_w, y + crop_h))
        if (shown_w, shown_h) != part.size:
            part = lanczos3_resize(part, (shown_w, shown_h))
        part = part.crop((visible[0] - left, visible[1] - top, visible[2] - left, visible[3] - top))
        canvas.alpha_composite(part, visible[:2])
    return canvas
