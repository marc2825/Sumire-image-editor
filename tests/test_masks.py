from pathlib import Path

import pytest
from PIL import Image, ImageChops

from sumire.imaging import Document, Stroke, Tool, selection_mask


def apply(document, mode, start, end, shape="rectangle", **options):
    stroke = Stroke(document, Tool(mode, diameter=14, expansion=0, **options))
    if shape == "brush":
        stroke.add(start)
        stroke.add(end)
    else:
        stroke.mask = selection_mask(document.image.size, start, end, shape)
        stroke.apply()
    return stroke, stroke.finish()


@pytest.mark.parametrize("mode", ["mosaic", "blur", "fill"])
def test_eraser_restores_original_pixels_alpha_and_only_selected_mask(mode, patterned):
    image = patterned.copy()
    image.putalpha(120)
    document = Document(Path("image.png"), image)
    apply(document, mode, (10, 10), (120, 100))
    processed = document.image.copy()
    assert document.edit_mask.getpixel((20, 20)) == 255
    assert document.edit_mask.getpixel((0, 0)) == 0
    apply(document, "erase", (30, 30), (60, 60))
    assert document.image.crop((30, 30, 61, 61)).tobytes() == image.crop((30, 30, 61, 61)).tobytes()
    assert document.image.getpixel((20, 20)) == processed.getpixel((20, 20))
    assert document.edit_mask.getpixel((40, 40)) == 0
    assert document.edit_mask.getpixel((20, 20)) == 255
    assert document.image.getpixel((40, 40))[3] == 120


def test_overlapping_effects_erase_to_original_and_mask_history_is_reversible(patterned):
    document = Document(Path("image.png"), patterned)
    apply(document, "mosaic", (10, 10), (90, 90))
    apply(document, "fill", (50, 50), (120, 100))
    pixels, mask = document.image.tobytes(), document.edit_mask.tobytes()
    apply(document, "erase", (30, 30), (100, 100))
    erased_pixels, erased_mask = document.image.tobytes(), document.edit_mask.tobytes()
    assert document.image.getpixel((60, 60)) == patterned.getpixel((60, 60))
    assert document.undo()
    assert document.image.tobytes() == pixels and document.edit_mask.tobytes() == mask
    assert document.redo()
    assert document.image.tobytes() == erased_pixels and document.edit_mask.tobytes() == erased_mask
    assert document.undo() and document.undo() and document.undo()
    assert document.image.tobytes() == patterned.tobytes()
    assert document.edit_mask.getbbox() is None


@pytest.mark.parametrize("shape", ["rectangle", "ellipse", "brush"])
def test_mask_and_eraser_support_all_shapes(shape, patterned):
    document = Document(Path("image.png"), patterned)
    apply(document, "fill", (10, 10), (120, 100))
    stroke, changed = apply(document, "erase", (30, 30), (75, 70), shape)
    assert changed
    expected = Image.new("L", patterned.size)
    expected.paste(255, (10, 10, 121, 101))
    expected.paste(0, (0, 0), stroke.mask)
    assert ImageChops.difference(document.edit_mask, expected).getbbox() is None


@pytest.mark.parametrize("erase", [False, True])
def test_cancel_restores_both_pixels_and_mask(erase, patterned):
    document = Document(Path("image.png"), patterned)
    apply(document, "fill", (20, 20), (80, 80))
    pixels, mask, revision = document.image.tobytes(), document.edit_mask.tobytes(), document.revision
    stroke = Stroke(document, Tool("erase" if erase else "blur", diameter=30))
    stroke.add((40, 40))
    stroke.cancel()
    assert document.image.tobytes() == pixels
    assert document.edit_mask.tobytes() == mask and document.revision == revision


def test_transparent_fill_does_not_create_mask_but_applied_uniform_effect_does():
    document = Document(Path("image.png"), Image.new("RGBA", (80, 80), "white"))
    _, changed = apply(document, "fill", (20, 20), (50, 50), opacity=0)
    assert not changed and document.edit_mask.getbbox() is None
    _, changed = apply(document, "mosaic", (20, 20), (50, 50))
    assert changed and document.edit_mask.getpixel((30, 30)) == 255
    assert not document.edited
    assert document.undo() and document.edit_mask.getbbox() is None


def test_mask_only_changes_keep_restored_unedited_state_when_pixels_differ():
    document = Document(Path("image.jpg"), Image.new("RGBA", (80, 80), "white"))
    document.image = Image.new("RGBA", (80, 80), "black")
    document.restore_edit_state(False, overwrite=False)
    _, changed = apply(document, "mosaic", (20, 20), (50, 50))
    assert changed and document.edit_state is False
    assert document.undo() and document.edit_state is False
    assert document.redo() and document.edit_state is False
