"""A watermark or signature drawn into exported images (never into the originals).

A text (drawn with the text tool's renderer, so any language's characters work) or a
signature image is placed in a corner, the centre, or repeated across the image. Its
size follows the image: the height is a percentage of the longer side, so the mark
looks the same on large and small images.
"""
from __future__ import annotations
from .i18n import tr

from dataclasses import dataclass
from functools import lru_cache
import math
from pathlib import Path

from PIL import Image, ImageFilter

from .imaging import ImageProblem, load_image

POSITIONS = {
    "bottom_right": tr("右下"),
    "bottom_left": tr("左下"),
    "top_right": tr("右上"),
    "top_left": tr("左上"),
    "center": tr("中央"),
    "tiled": tr("全体に繰り返す（斜め）"),
}
MIN_SIZE, MAX_SIZE = 1, 30          # percent of the longer side
MAX_TEXT = 200


@dataclass(frozen=True)
class Watermark:
    text: str = ""
    image: str | None = None        # a signature image (PNG with transparency works best)
    position: str = "bottom_right"
    size: int = 4                   # the mark's height, in percent of the image's longer side
    opacity: int = 60               # percent
    color: str = "#ffffff"
    shadow: bool = True             # a soft dark edge so a light mark stays readable on light areas

    @property
    def empty(self) -> bool:
        return not self.image and not self.text.strip()

    def to_settings(self) -> dict:
        return {"text": self.text, "image": self.image, "position": self.position, "size": self.size,
                "opacity": self.opacity, "color": self.color, "shadow": self.shadow}

    @classmethod
    def from_settings(cls, value) -> Watermark:
        """A watermark from saved settings; anything missing or invalid keeps its default."""
        mark = cls()
        if not isinstance(value, dict):
            return mark
        text = value.get("text")
        image = value.get("image")
        position = value.get("position")
        color = value.get("color")
        return cls(
            text=text[:MAX_TEXT] if isinstance(text, str) else mark.text,
            image=image if isinstance(image, str) and image else None,
            position=position if position in POSITIONS else mark.position,
            size=value["size"] if type(value.get("size")) is int and MIN_SIZE <= value["size"] <= MAX_SIZE else mark.size,
            opacity=value["opacity"] if type(value.get("opacity")) is int and 5 <= value["opacity"] <= 100 else mark.opacity,
            color=color.lower() if isinstance(color, str) and len(color) == 7 and color.startswith("#")
            and all(c in "0123456789abcdefABCDEF" for c in color[1:]) else mark.color,
            shadow=value["shadow"] if isinstance(value.get("shadow"), bool) else mark.shadow)


@lru_cache(maxsize=4)
def _signature(path: str, modified: float) -> Image.Image:
    del modified  # part of the cache key: a changed file is read again
    try:
        image = load_image(Path(path)).convert("RGBA")
    except ImageProblem:
        raise ImageProblem(tr("署名の画像を読み込めません：{name}").format(name=Path(path).name)) from None
    image = image.crop(image.getchannel("A").getbbox() or (0, 0, *image.size))
    if image.height > image.width * 20 or image.width > image.height * 20:
        raise ImageProblem(tr("署名の画像の縦横比が極端です。"))
    return image


def _mark_layer(mark: Watermark, height: int) -> Image.Image:
    """The mark itself (text or signature), ``height`` pixels tall, at full opacity."""
    if mark.image:
        path = Path(mark.image)
        try:
            modified = path.stat().st_mtime
        except OSError:
            raise ImageProblem(tr("署名の画像が見つかりません：{name}").format(name=path.name)) from None
        signature = _signature(str(path), modified)
        width = max(1, round(signature.width * height / signature.height))
        return signature.resize((width, height), Image.Resampling.LANCZOS)
    from .text_tool import TextStyle, placement_at, text_layer
    text = mark.text.strip()[:MAX_TEXT]
    style = TextStyle(size=max(4, height), color=mark.color, bold=True)
    placement = placement_at(text, style, (0, 0))
    text_width, text_height = placement.size()
    room = (math.ceil(text_width + height * 0.6), math.ceil(text_height + height * 0.6))
    rendered = text_layer(placement_at(text, style, (height * 0.3, height * 0.3)), room)
    if rendered is None:
        raise ImageProblem(tr("透かしの文字を描けません。"))
    layer, (left, top) = rendered
    canvas = Image.new("RGBA", room)
    canvas.paste(layer, (left, top))
    return canvas.crop(canvas.getchannel("A").getbbox() or (0, 0, *canvas.size))


def _with_shadow(layer: Image.Image, height: int) -> Image.Image:
    """The mark over a soft dark copy of itself, so it reads on light and dark areas alike."""
    offset = max(1, round(height * 0.05))
    radius = max(1, round(height * 0.06))
    pad = offset + radius * 2
    result = Image.new("RGBA", (layer.width + pad * 2, layer.height + pad * 2))
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 255))
    shadow.putalpha(layer.getchannel("A").point(lambda value: value * 0.55))
    result.paste(shadow, (pad + offset, pad + offset), shadow)
    result = result.filter(ImageFilter.GaussianBlur(radius))
    result.alpha_composite(layer, (pad, pad))
    return result


def _fade(layer: Image.Image, opacity: int) -> Image.Image:
    if opacity >= 100:
        return layer
    alpha = layer.getchannel("A").point(lambda value: round(value * opacity / 100))
    faded = layer.copy()
    faded.putalpha(alpha)
    return faded


def apply_watermark(pixels: Image.Image, mark: Watermark | None) -> Image.Image:
    """``pixels`` (RGBA) with the mark drawn in; the input is not changed."""
    if mark is None or mark.empty:
        return pixels
    longer = max(pixels.size)
    height = max(6, round(longer * max(MIN_SIZE, min(MAX_SIZE, mark.size)) / 100))
    layer = _mark_layer(mark, height)
    if mark.shadow:
        layer = _with_shadow(layer, height)
    layer = _fade(layer, max(5, min(100, mark.opacity)))
    result = pixels.convert("RGBA").copy()
    if mark.position == "tiled":
        tile = layer.rotate(30, resample=Image.Resampling.BICUBIC, expand=True)
        step_x, step_y = tile.width + height * 2, tile.height + height * 2
        overlay = Image.new("RGBA", result.size)
        for row, y in enumerate(range(-tile.height // 2, result.height, step_y)):
            shift = (step_x // 2) * (row % 2)
            for x in range(-tile.width - shift, result.width + tile.width, step_x):
                _composite_clipped(overlay, tile, x, y)
        return Image.alpha_composite(result, overlay)
    margin = max(4, round(longer * 0.02))
    if layer.width > result.width - margin * 2 or layer.height > result.height - margin * 2:
        scale = min((result.width - margin * 2) / layer.width, (result.height - margin * 2) / layer.height)
        if scale <= 0:
            return result
        layer = layer.resize((max(1, round(layer.width * scale)), max(1, round(layer.height * scale))),
                             Image.Resampling.LANCZOS)
    x = {"top_left": margin, "bottom_left": margin, "center": (result.width - layer.width) // 2}.get(
        mark.position, result.width - layer.width - margin)
    y = {"top_left": margin, "top_right": margin, "center": (result.height - layer.height) // 2}.get(
        mark.position, result.height - layer.height - margin)
    result.alpha_composite(layer, (x, y))
    return result


def _composite_clipped(target: Image.Image, layer: Image.Image, x: int, y: int) -> None:
    """``alpha_composite`` at a position that may lie partly outside ``target``."""
    left, top = max(0, x), max(0, y)
    right, bottom = min(target.width, x + layer.width), min(target.height, y + layer.height)
    if right <= left or bottom <= top:
        return
    part = layer.crop((left - x, top - y, right - x, bottom - y))
    target.alpha_composite(part, (left, top))


def preview(pixels: Image.Image, mark: Watermark | None, longest: int = 320) -> Image.Image:
    """A small picture of how the mark sits on ``pixels`` (for the export dialog)."""
    marked = apply_watermark(pixels, mark)
    scale = longest / max(marked.size)
    if scale < 1:
        marked = marked.resize((max(1, round(marked.width * scale)), max(1, round(marked.height * scale))),
                               Image.Resampling.LANCZOS)
    return marked
