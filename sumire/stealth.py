"""Remove recognized Stealth PNGInfo carriers without decoding their contents.

NovelAI's alpha carrier is documented by its reference reader/writer:
https://github.com/NovelAI/novelai-image-metadata
The related RGB variants use the same column-first pixel traversal:
https://github.com/neggles/sd-webui-stealth-pnginfo
"""
from __future__ import annotations

from typing import Any

from PIL import Image

SIGNATURES = {
    "alpha": {b"stealth_pngcomp", b"stealth_pnginfo"},
    "rgb": {b"stealth_rgbcomp", b"stealth_rgbinfo"},
}
SIGNATURE_BYTES = len(b"stealth_pngcomp")
# Collapse each pair of alpha values to one value. Keep fully transparent and
# opaque pixels exact; NovelAI's 254/255 carrier becomes opaque again.
ALPHA_WITHOUT_LSB = tuple(255 if value >= 254 else value & 0xFE for value in range(256))
RGB_WITHOUT_LSB = tuple(value & 0xFE for value in range(256))


def stealth_channels(image: Image.Image) -> tuple[str, ...]:
    """Inspect only the fixed-size signatures, never parse/decompress a payload."""
    if image.mode not in {"RGB", "RGBA", "LA", "P"}:
        return ()
    pixels_image = image if image.mode in {"RGB", "RGBA"} else image.convert("RGBA")
    pixels: Any = pixels_image.load()  # always loaded here; each pixel is a tuple of channels
    width, height = pixels_image.size
    found = []
    for name, channels in (("alpha", (3,)), ("rgb", (0, 1, 2))):
        if name == "alpha" and pixels_image.mode != "RGBA":
            continue
        count = SIGNATURE_BYTES * 8
        if width * height * len(channels) < count:
            continue
        signature = bytearray(SIGNATURE_BYTES)
        for bit in range(count):
            pixel_index, channel_index = divmod(bit, len(channels))
            x, y = divmod(pixel_index, height)
            signature[bit // 8] |= (pixels[x, y][channels[channel_index]] & 1) << (7 - bit % 8)
        if bytes(signature) in SIGNATURES[name]:
            found.append(name)
    return tuple(found)


def remove_stealth(image: Image.Image) -> Image.Image:
    """Erase the entire detected carrier, including payload and trailing FEC.

    Ordinary images are returned unchanged. Detected channels change by at most
    one level; the input image is never mutated.
    """
    carriers = stealth_channels(image)
    if not carriers:
        return image
    bands = list(image.convert("RGBA").split())
    if "alpha" in carriers:
        bands[3] = bands[3].point(ALPHA_WITHOUT_LSB)
    if "rgb" in carriers:
        for channel in range(3):
            bands[channel] = bands[channel].point(RGB_WITHOUT_LSB)
    result = Image.merge("RGBA", bands)
    # Loading still needs Orientation and ICC for the usual pixel transforms.
    result.info = image.info.copy()
    return result
