"""Lanczos3 enlargement: kernel correctness, transparency, limits and the in-place 超解像."""
import math
from pathlib import Path
import random

import pytest
from PIL import Image

import sumire.editing as editing
from sumire.editing import EditSpec, apply_edit, lanczos3_resize, upscale_lanczos3, upscaled_size
from sumire.output_dialogs import UpscaleDialog
from sumire.imaging import Document, ImageProblem

from test_gui import draw, window
from test_editor_gui import settled


def windowed_sinc(x, a):
    """Independent Lanczos kernel: sinc(x) * sinc(x / a) inside |x| < a."""
    if not -a <= x < a:
        return 0.0
    if x == 0:
        return 1.0
    return a * math.sin(math.pi * x) * math.sin(math.pi * x / a) / (math.pi * math.pi * x * x)


def reference_axis(values, out_size, a):
    """Separable pass using the same pixel-centre mapping and edge renormalisation as Pillow."""
    in_size = len(values)
    scale = in_size / out_size
    support = a * max(scale, 1.0)
    result = []
    for out in range(out_size):
        center = (out + 0.5) * scale
        first = max(int(center - support + 0.5), 0)
        last = min(int(center + support + 0.5), in_size)
        weights = [windowed_sinc((x - center + 0.5) / max(scale, 1.0), a) for x in range(first, last)]
        total = sum(weights)
        value = sum(values[x] * w for x, w in zip(range(first, last), weights)) / total
        result.append(min(255, max(0, round(value))))
    return result


def reference_resize(gray, size, a=3):
    width, height = gray.size
    rows = [values(gray.crop((0, y, width, y + 1))) for y in range(height)]
    horizontal = [reference_axis(row, size[0], a) for row in rows]
    columns = [reference_axis([horizontal[y][x] for y in range(height)], size[1], a) for x in range(size[0])]
    return [[columns[x][y] for x in range(size[0])] for y in range(size[1])]


def values(image):
    """Pixel tuples (or ints for one-band images) without the deprecated getdata()."""
    data, bands = image.tobytes(), len(image.getbands())
    return list(data) if bands == 1 else [tuple(data[i:i + bands]) for i in range(0, len(data), bands)]


def noise(size, seed=7):
    generator = random.Random(seed)
    image = Image.new("L", size)
    image.putdata([generator.randrange(256) for _ in range(size[0] * size[1])])
    return image


@pytest.mark.parametrize("factor", [2, 1.5, 3])
def test_matches_an_independent_lanczos3_reference(factor):
    gray = noise((13, 9))
    size = upscaled_size(gray.size, factor)
    output = upscale_lanczos3(Image.merge("RGBA", (gray, gray, gray, Image.new("L", gray.size, 255))), factor).getchannel("R")
    actual = [values(output.crop((0, y, size[0], y + 1))) for y in range(size[1])]
    expected = reference_resize(gray, size, a=3)
    differences = [abs(p - q) for row_a, row_e in zip(actual, expected) for p, q in zip(row_a, row_e)]
    # Pillow uses fixed-point weights and rounds after each pass.
    assert max(differences) <= 2 and sum(differences) / len(differences) < 0.25
    lanczos2 = reference_resize(gray, size, a=2)
    assert sum(abs(p - q) for row_a, row_2 in zip(actual, lanczos2) for p, q in zip(row_a, row_2)) > 20 * sum(differences) + 50


def test_transparent_colour_does_not_bleed_into_visible_edges():
    image = Image.new("RGBA", (16, 8), (255, 0, 0, 0))
    image.paste((0, 0, 255, 255), (8, 0, 16, 8))
    enlarged = upscale_lanczos3(image, 4)
    visible = [pixel for pixel in values(enlarged) if pixel[3] >= 16]
    assert visible and max(pixel[0] for pixel in visible) <= 2
    # Interpolating each channel on its own (no premultiplication) does bleed.
    red, alpha = (image.getchannel(band).resize(enlarged.size, Image.Resampling.LANCZOS) for band in ("R", "A"))
    assert max(r for r, a in zip(values(red), values(alpha)) if a >= 16) > 100


def test_opaque_pixels_and_metadata_free_result(patterned):
    patterned.info["parameters"] = "private prompt"
    enlarged = upscale_lanczos3(patterned, 2)
    assert enlarged.size == (320, 240) and enlarged.mode == "RGBA"
    assert not enlarged.info and set(values(enlarged.getchannel("A"))) == {255}


@pytest.mark.parametrize("factor", [1, 0.5, 9])
def test_factor_must_enlarge_within_range(factor):
    with pytest.raises(ImageProblem, match="倍率"):
        upscaled_size((100, 100), factor)


def test_result_must_stay_within_reopenable_limits():
    assert upscaled_size((3000, 2000), 1.5) == (4500, 3000)
    with pytest.raises(ImageProblem, match="上限"):
        upscaled_size((3000, 2000), 3)
    with pytest.raises(ImageProblem, match="上限"):
        upscaled_size((20000, 10), 2)


def test_document_resize_uses_lanczos3_on_premultiplied_alpha():
    image = Image.new("RGBA", (16, 8), (255, 0, 0, 0))
    image.paste((0, 0, 255, 255), (8, 0, 16, 8))
    document = Document(Path("resize.png"), image)
    assert apply_edit(document, EditSpec(size=(64, 32)))
    assert document.image.tobytes() == lanczos3_resize(image, (64, 32)).tobytes()
    assert max(pixel[0] for pixel in values(document.image) if pixel[3] >= 16) <= 2


def test_dialog_shows_result_size_and_blocks_oversized_images(qtbot):
    dialog = UpscaleDialog((160, 120))
    qtbot.addWidget(dialog)
    assert dialog.factor.currentData() == 2 and "320 × 240" in dialog.result.text() and dialog.ok.isEnabled()
    assert dialog.target_size() == (320, 240)
    large = UpscaleDialog((5000, 4000))
    qtbot.addWidget(large)
    assert "上限" in large.result.text() and not large.ok.isEnabled()
    large.factor.setCurrentIndex(large.factor.findData(1.5))
    assert not large.ok.isEnabled()


def choose_factor(factor, answers=None):
    def accept(self, dialog, accepted=None):
        if isinstance(dialog, UpscaleDialog):
            dialog.factor.setCurrentIndex(dialog.factor.findData(factor))
            return True
        answers.append(type(dialog).__name__) if answers is not None else None
        return False
    return accept


def test_in_place_upscale_keeps_edits_writes_nothing_and_can_be_undone(qtbot, window, tmp_path, monkeypatch):
    page = window
    page.auto.setChecked(False)
    page.overwrite.setChecked(False)
    draw(page)
    settled(qtbot, page)
    source = page.document.path
    original = source.read_bytes()
    files = set(source.parent.iterdir())
    expected = upscale_lanczos3(page.document.image, 2).tobytes()
    monkeypatch.setattr(type(page), "confirm_dialog", choose_factor(2))
    assert page.editor_actions["upscale"].isEnabled() and page.editor_actions["upscale"].text().startswith("超解像を適用")
    page.editor_actions["upscale"].trigger()
    settled(qtbot, page)
    assert page.document.image.size == (320, 240) and page.document.image.tobytes() == expected
    assert page.document.edit_mask.size == (320, 240) and page.document.dirty
    assert source.read_bytes() == original and set(source.parent.iterdir()) == files
    page.history(False)
    settled(qtbot, page)
    assert page.document.image.size == (160, 120)


def test_overwrite_mode_asks_before_changing_the_original_size(qtbot, window, monkeypatch):
    page = window
    page.auto.setChecked(False)
    page.overwrite.setChecked(True)
    asked = []
    monkeypatch.setattr(type(page), "confirm_dialog", choose_factor(1.5, asked))
    page.upscale_image()
    settled(qtbot, page)
    assert asked == ["QMessageBox"] and page.document.image.size == (160, 120)


def test_image_menu_offers_upscale_without_export(window):
    assert not hasattr(window, "upscale_button")
    menu_actions = window.image_menu.actions()
    other = next(action.menu() for action in menu_actions if action.menu() is not None)
    assert window.editor_actions["upscale"] in other.actions() and window.editor_actions["upscale"] not in menu_actions
    assert not any("書き出す" in action.text() for action in menu_actions)
    for key in ("export", "export_selected", "export_all", "upscale_selected", "upscale_all"):
        assert key not in window.editor_actions
