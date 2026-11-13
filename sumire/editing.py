"""Non-destructive editor operations; output scaling never mutates a document."""
from .i18n import tr
from dataclasses import asdict, dataclass, fields

from PIL import Image, ImageEnhance

from .imaging import ImageProblem, MAX_DIMENSION, MAX_PIXELS, clean_pixels


@dataclass(frozen=True)
class EditSpec:
    crop: tuple | None = None  # x, y, width, height
    size: tuple | None = None
    rotation: int = 0  # clockwise
    horizontal: bool = False
    vertical: bool = False
    brightness: float = 1  # 0–3, multiplier
    contrast: float = 1  # 0–3
    saturation: float = 1  # 0–3
    hue: int = 0  # −180〜180°
    exposure: float = 0  # −3〜3 EV
    temperature: int = 0  # −100（青み）〜100（黄み）
    gamma: float = 1  # 0.2〜5
    highlights: int = 0  # −100〜100
    shadows: int = 0  # −100〜100
    white: int = 255  # white level, input value mapped to 255
    black: int = 0  # black level, input value mapped to 0
    red: float = 1  # RGB balance, 0–2
    green: float = 1
    blue: float = 1
    sharpness: float = 1  # 0–3; 1 keeps the image as is


GEOMETRY_FIELDS = ("crop", "size", "rotation", "horizontal", "vertical")
COLOR_FIELDS = tuple(field.name for field in fields(EditSpec) if field.name not in GEOMETRY_FIELDS)
NEUTRAL_COLORS = {field.name: field.default for field in fields(EditSpec) if field.name in COLOR_FIELDS}
COLOR_LIMITS = {"brightness": (0, 3), "contrast": (0, 3), "saturation": (0, 3), "hue": (-180, 180),
                "exposure": (-3, 3), "temperature": (-100, 100), "gamma": (0.2, 5), "highlights": (-100, 100),
                "shadows": (-100, 100), "white": (1, 255), "black": (0, 254), "red": (0, 2), "green": (0, 2),
                "blue": (0, 2), "sharpness": (0, 3)}


def color_values(spec):
    return {name: getattr(spec, name) for name in COLOR_FIELDS}


def has_color(spec):
    return color_values(spec) != NEUTRAL_COLORS


def _tone_lut(spec):
    """One 768-entry table for every per-channel adjustment, applied in a fixed order."""
    gains = (spec.red, spec.green, spec.blue)
    warm = spec.temperature / 100 * 0.25
    temperature = (1 + warm, 1, 1 - warm)
    exposure = 2 ** spec.exposure
    black, white = spec.black, max(spec.black + 1, spec.white)
    table = []
    for channel in range(3):
        for value in range(256):
            v = value / 255 * exposure
            v = (v * 255 - black) / (white - black)
            v = min(1.0, max(0.0, v)) ** (1 / spec.gamma)
            # Shadows lift or deepen the dark half, highlights the bright half, smoothly.
            v += spec.shadows / 100 * 0.5 * v * (1 - v) ** 2 * 4
            v += spec.highlights / 100 * 0.5 * v ** 2 * (1 - v) * 4
            v *= spec.brightness * gains[channel] * temperature[channel]
            table.append(round(min(1.0, max(0.0, v)) * 255))
    return table


def adjust_colors(pixels, spec):
    """Colour adjustments on RGBA pixels; alpha is kept unchanged."""
    if not has_color(spec):
        return pixels
    alpha = pixels.getchannel("A")
    rgb = pixels.convert("RGB")
    lut = _tone_lut(spec)
    if lut != list(range(256)) * 3:
        rgb = rgb.point(lut)
    if spec.contrast != 1:
        rgb = ImageEnhance.Contrast(rgb).enhance(spec.contrast)
    if spec.saturation != 1:
        rgb = ImageEnhance.Color(rgb).enhance(spec.saturation)
    if spec.hue:
        hue, sat, value = rgb.convert("HSV").split()
        shift = round(spec.hue / 360 * 256) % 256
        hue = hue.point([(value + shift) % 256 for value in range(256)])
        rgb = Image.merge("HSV", (hue, sat, value)).convert("RGB")
    if spec.sharpness != 1:
        rgb = ImageEnhance.Sharpness(rgb).enhance(spec.sharpness)
    rgb.putalpha(alpha)
    return rgb


# Pillow's LANCZOS filter is the windowed sinc with a = 3 (support 3.0 in
# libImaging/Resample.c), i.e. Lanczos3. It interpolates; unlike machine-learning
# super-resolution it does not invent detail, so redacted areas stay redacted.
LANCZOS3 = Image.Resampling.LANCZOS
UPSCALE_FACTORS = (1.5, 2, 3, 4)
MAX_UPSCALE = 8


def checked_size(size):
    if (len(size) != 2 or any(type(value) is not int or not 1 <= value <= MAX_DIMENSION for value in size)
            or size[0] * size[1] > MAX_PIXELS):
        raise ImageProblem(tr("寸法は1辺1〜32,768px、合計2,400万画素以内で指定してください。"))
    return size


def lanczos3_resize(image, size):
    """Resample with Lanczos3 on premultiplied alpha.

    Interpolating straight RGBA would let the colour of fully transparent pixels
    bleed into visible edges. Pillow premultiplies RGBA internally as well; doing
    it explicitly keeps that guarantee independent of the library version.
    """
    checked_size(size)
    rgba = image if image.mode == "RGBA" else image.convert("RGBA")
    return rgba.convert("RGBa").resize(size, LANCZOS3).convert("RGBA")


def upscaled_size(size, factor):
    if not 1 < factor <= MAX_UPSCALE:
        raise ImageProblem(tr("拡大の倍率は1倍より大きく、{MAX_UPSCALE}倍以下で指定してください。").format(MAX_UPSCALE=MAX_UPSCALE))
    target = (max(1, round(size[0] * factor)), max(1, round(size[1] * factor)))
    try:
        return checked_size(target)
    except ImageProblem:
        raise ImageProblem(tr("{factor:g}倍では{target:,} × {target2:,}pxになり、上限（1辺32,768px・2,400万画素）を超えます。").format(factor=factor, target=target[0], target2=target[1])) from None


def upscale_lanczos3(image, factor):
    """A new, metadata-free image enlarged by ``factor`` with Lanczos3."""
    return lanczos3_resize(clean_pixels(image), upscaled_size(image.size, factor))


def geometry(image, spec, *, mask=False):
    result = image
    if spec.crop is not None:
        x, y, width, height = spec.crop
        if (any(type(value) is not int for value in spec.crop) or x < 0 or y < 0 or width < 1 or height < 1
                or x + width > image.width or y + height > image.height):
            raise ImageProblem(tr("切り抜き範囲が画像の外にあります。"))
        result = result.crop((x, y, x + width, y + height))
    if spec.rotation not in {0, 90, 180, 270}:
        raise ImageProblem(tr("回転は90°単位で指定してください。"))
    if spec.rotation:
        result = result.transpose({90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180,
                                   270: Image.Transpose.ROTATE_90}[spec.rotation])
    if spec.horizontal:
        result = result.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if spec.vertical:
        result = result.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    if spec.size is not None:
        checked_size(spec.size)
        result = result.resize(spec.size, Image.Resampling.NEAREST) if mask else lanczos3_resize(result, spec.size)
    return result.copy() if result is image else result


def check_colors(spec):
    for name, (low, high) in COLOR_LIMITS.items():
        if not low <= getattr(spec, name) <= high:
            raise ImageProblem(tr("色調の値が範囲外です。"))
    if spec.black >= spec.white:
        raise ImageProblem(tr("黒レベルは白レベルより小さくしてください。"))


def apply_edit(document, spec):
    check_colors(spec)
    pixels = adjust_colors(geometry(document.image, spec), spec)
    has_geometry = (spec.crop not in (None, (0, 0, *document.image.size)) or spec.rotation != 0
                    or spec.horizontal or spec.vertical or spec.size not in (None, document.image.size))
    mask = geometry(document.edit_mask, spec, mask=True) if has_geometry else document.edit_mask
    base = geometry(document.original, spec) if has_geometry else document.original
    step = {key: value for key, value in asdict(spec).items() if key in GEOMETRY_FIELDS}
    steps = [*document.geometry_steps, step] if has_geometry else document.geometry_steps
    return document.replace(clean_pixels(pixels), mask, base, geometry=document.geometry_edited or has_geometry, steps=steps)


def resized_output(image, maximum):
    if any(type(value) is not int or not 1 <= value <= MAX_DIMENSION for value in maximum):
        raise ImageProblem(tr("出力の上限は1辺1〜32,768pxで指定してください。"))
    result = clean_pixels(image)
    result.thumbnail(maximum, Image.Resampling.LANCZOS)
    return result
