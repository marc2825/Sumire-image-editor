"""Copying the processed area of one image onto others (the same signature corner, the same face…).

The area is the shown image's edit mask (what the mask view shows). On each other image it is
placed either at the same relative position and size (images of other sizes stay aligned), or at
the same pixels. There it is processed with one tool: mosaic, blur or fill.
"""
from __future__ import annotations

from PIL import Image, ImageChops

from .imaging import Tool, make_effect

MODES = ("relative", "pixels")


def placed_mask(mask: Image.Image, size: tuple[int, int], how: str = "relative") -> Image.Image:
    """``mask`` on an image of ``size``: stretched to it ("relative") or at the same pixels ("pixels")."""
    if mask.size == size:
        return mask.copy()
    if how == "pixels":
        result = Image.new("L", size)
        result.paste(mask.crop((0, 0, min(mask.width, size[0]), min(mask.height, size[1]))), (0, 0))
        return result
    # Hard edges, like a drawn mask: no grey pixels at the border.
    return mask.resize(size, Image.Resampling.NEAREST)


def apply_area(image: Image.Image, mask: Image.Image | None, area: Image.Image, tool: Tool):
    """``image`` with ``area`` processed by ``tool``; returns (image, mask, changed).

    ``mask`` is the image's own edit mask (None when it has none yet); the area is added to it.
    """
    base = mask if mask is not None and mask.size == image.size else Image.new("L", image.size)
    if area.getbbox() is None:
        return image, base, False
    result = image.copy()
    result.paste(make_effect(image, tool), (0, 0), area)
    new_mask = ImageChops.lighter(base, area) if tool.mode != "fill" or tool.opacity > 0 else base
    changed = ImageChops.difference(result, image).getbbox(alpha_only=False) is not None
    return result, new_mask, changed or new_mask.tobytes() != base.tobytes()
