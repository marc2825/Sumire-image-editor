from pathlib import Path

import pytest
from PIL import Image, ImageChops

from sumire.imaging import Document, ImageProblem, Stroke, Tool, load_image, make_effect, selection_mask


def test_brush_interpolates_fast_motion_and_preserves_outside(patterned):
    doc = Document(Path("test.png"), patterned)
    stroke = Stroke(doc, Tool("fill", 8, color="#000000", expansion=0))
    stroke.add((10, 60))
    stroke.add((150, 60))
    assert stroke.finish()
    assert all(doc.image.getpixel((x, 60)) == (0, 0, 0, 255) for x in range(10, 151))
    assert doc.image.crop((0, 0, 160, 50)).tobytes() == patterned.crop((0, 0, 160, 50)).tobytes()
    assert doc.image.getpixel((80, 53)) == patterned.getpixel((80, 53))


def test_strength_changes_mosaic_and_fixed_blocks(patterned):
    weak = make_effect(patterned, Tool(strength=4))
    strong = make_effect(patterned, Tool(strength=20))
    assert weak.tobytes() != strong.tobytes()
    assert strong.getpixel((1, 1)) == strong.getpixel((19, 19))
    assert weak.getpixel((1, 1)) != weak.getpixel((5, 1))


def test_partial_edge_block_does_not_add_black():
    image = Image.new("RGBA", (23, 13), "white")
    result = make_effect(image, Tool(strength=20))
    assert result.size == image.size
    assert result.tobytes() == Image.new("RGBA", image.size, "white").tobytes()


@pytest.mark.parametrize("mode,strength", [("mosaic", 4), ("blur", 3)])
def test_effects_keep_transparency_and_add_no_black(mode, strength):
    """Issue #1: blur and mosaic made semi-transparent areas opaque and transparent ones black."""
    image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    image.paste((255, 0, 0, 255), (16, 0, 32, 32))  # right half opaque red
    image.paste((0, 0, 255, 128), (0, 24, 32, 32))  # bottom strip half-transparent blue
    result = make_effect(image, Tool(mode, strength=strength))
    assert result.getpixel((0, 0))[3] == 0  # far inside the transparent area: still transparent
    assert result.getpixel((31, 0)) == (255, 0, 0, 255)  # inside the red: unchanged
    assert 0 < result.getpixel((0, 31))[3] < 255  # the half-transparent strip stays half-transparent
    for x in range(32):
        red, green, blue, alpha = result.getpixel((x, 4))
        if alpha:
            assert (red, green, blue) != (0, 0, 0) and red >= 200  # no dark fringe from transparent pixels


def test_mosaic_does_not_reveal_colour_stored_in_transparent_pixels():
    image = Image.new("RGBA", (8, 8), (0, 255, 0, 0))  # fully transparent, with a colour stored in it
    result = make_effect(image, Tool("mosaic", strength=4))
    assert all(pixel[3] == 0 for pixel in result.getdata())


def test_blur_matches_pillow(patterned):
    from PIL import ImageFilter
    result = make_effect(patterned, Tool("blur", strength=8))
    assert result.tobytes() == patterned.filter(ImageFilter.GaussianBlur(8)).tobytes()


@pytest.mark.parametrize("shape", ["rectangle", "ellipse"])
def test_selection_reversed_and_expanded(shape):
    forward = selection_mask((100, 100), (20, 30), (60, 70), shape, 2)
    reverse = selection_mask((100, 100), (60, 70), (20, 30), shape, 2)
    assert forward.tobytes() == reverse.tobytes()
    assert forward.getpixel((40, 30)) == 255
    assert forward.getpixel((40, 27)) == 0
    assert forward.getpixel((40, 28)) == 255


def test_undo_redo_branching_and_multiple_strokes(patterned):
    doc = Document(Path("test.png"), patterned)
    for point in [(20, 20), (100, 80)]:
        stroke = Stroke(doc, Tool("fill", 15, color="#ffffff"))
        stroke.add(point)
        stroke.finish()
    final = doc.image.tobytes()
    assert doc.undo() and doc.undo()
    assert doc.image.tobytes() == patterned.tobytes()
    assert doc.redo() and doc.redo()
    assert doc.image.tobytes() == final
    assert doc.undo()
    stroke = Stroke(doc, Tool("fill", 12))
    stroke.add((80, 20))
    stroke.finish()
    assert not doc.redo()
    assert doc.revision == 3


def test_transparent_area_stays_transparent_and_its_stored_colour_is_wiped_within_mask():
    """A colour stored in fully transparent pixels must not appear (it used to, made opaque), and
    within the mask it is wiped, so it cannot be read even by a viewer that ignores transparency."""
    doc = Document(Path("test.png"), Image.new("RGBA", (100, 100), (120, 10, 60, 0)))
    stroke = Stroke(doc, Tool("mosaic", 12))
    stroke.add((50, 50))
    stroke.finish()
    assert doc.image.getpixel((50, 50)) == (0, 0, 0, 0)
    assert doc.image.getpixel((0, 0)) == (120, 10, 60, 0)  # outside the mask nothing changes


def test_fill_and_cancel(patterned):
    doc = Document(Path("test.png"), patterned)
    stroke = Stroke(doc, Tool("fill", 12, color="#fefefe"))
    stroke.add((60, 60))
    assert doc.image.getpixel((60, 60)) == (254, 254, 254, 255)
    stroke.cancel()
    assert doc.image.tobytes() == patterned.tobytes()
    assert not doc.undo_stack


def test_history_is_bounded(patterned):
    doc = Document(Path("test.png"), patterned, history_limit=1)
    for point in [(20, 20), (60, 60), (100, 90)]:
        stroke = Stroke(doc, Tool("fill", 12))
        stroke.add(point)
        stroke.finish()
    assert len(doc.undo_stack) == 1
    assert doc.undo() and not doc.undo()


def test_documents_do_not_share_history(patterned):
    a, b = (Document(Path(name), patterned) for name in ["a.png", "b.png"])
    stroke = Stroke(a, Tool("fill", 20))
    stroke.add((30, 30))
    stroke.finish()
    assert not b.undo()
    assert b.image.tobytes() == patterned.tobytes()


@pytest.mark.parametrize("opacity,expected", [(0, (40, 80, 120, 255)), (50, (20, 40, 60, 255)), (100, (0, 0, 0, 255))])
def test_fill_opacity_composites_over_original(opacity, expected):
    doc = Document(Path("image.png"), Image.new("RGBA", (80, 80), (40, 80, 120, 255)))
    stroke = Stroke(doc, Tool("fill", 12, opacity=opacity))
    stroke.add((40, 40))
    changed = stroke.finish()
    assert doc.image.getpixel((40, 40)) == expected
    assert doc.image.getpixel((0, 0)) == (40, 80, 120, 255)
    assert changed == (opacity != 0)
    assert doc.edited == (opacity != 0)
    if changed:
        assert doc.undo()
        assert not doc.edited
        assert doc.redo()
        assert doc.edited


def test_partial_fill_on_transparent_pixels_preserves_alpha():
    doc = Document(Path("image.png"), Image.new("RGBA", (80, 80), (120, 50, 70, 0)))
    stroke = Stroke(doc, Tool("fill", 12, color="#204060", opacity=50))
    stroke.add((40, 40))
    stroke.finish()
    assert doc.image.getpixel((40, 40)) == (32, 64, 96, 128)
    assert doc.image.getpixel((0, 0)) == (120, 50, 70, 0)


def test_edit_state_includes_rgb_changes_and_returns_to_original():
    doc = Document(Path("image.png"), Image.new("RGBA", (20, 20), (255, 255, 255, 0)))
    doc.image.putpixel((5, 5), (0, 0, 0, 0))
    doc.update_edited()
    assert doc.edited
    doc.image = doc.original.copy()
    doc.update_edited()
    assert not doc.edited


def test_orientation_applied_before_metadata_removed(tmp_path):
    path = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = "private artist"
    Image.new("RGB", (80, 40), "red").save(path, exif=exif)
    result = load_image(path)
    assert result.size == (40, 80)
    assert not result.info and not result.getexif()


def test_icc_conversion_strips_profile(tmp_path):
    from PIL import ImageCms
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    path = tmp_path / "tagged.png"
    Image.new("RGBA", (40, 30), (50, 120, 180, 100)).save(path, icc_profile=profile)
    result = load_image(path)
    assert result.getpixel((0, 0)) == (50, 120, 180, 100)
    assert not result.info


def test_invalid_icc_rejected(tmp_path):
    path = tmp_path / "icc.png"
    Image.new("RGB", (20, 20)).save(path, icc_profile=b"invalid private data")
    with pytest.raises(ImageProblem, match="ICC"):
        load_image(path)


def test_animated_and_corrupt_rejected(tmp_path):
    path = tmp_path / "animated.png"
    Image.new("RGBA", (20, 20), "red").save(path, save_all=True, append_images=[Image.new("RGBA", (20, 20), "blue")])
    with pytest.raises(ImageProblem, match="アニメーション"):
        load_image(path)
    path.write_bytes(b"private invalid content")
    with pytest.raises(ImageProblem) as error:
        load_image(path)
    assert "private" not in str(error.value)


def test_huge_image_rejected_without_decoding(tmp_path, monkeypatch):
    import sumire.imaging as imaging
    path = tmp_path / "too-big.png"
    Image.new("RGB", (50, 50)).save(path)
    monkeypatch.setattr(imaging, "MAX_PIXELS", 100)
    with pytest.raises(ImageProblem, match="大きすぎ"):
        load_image(path)


def test_drag_completely_outside_image_is_safe(patterned):
    doc = Document(Path("test.png"), patterned)
    stroke = Stroke(doc, Tool("fill", 10))
    stroke.add((150, 60))
    stroke.add((200, 60))
    assert stroke.add((230, 60)) is None
    stroke.add((250, -100))
    stroke.add((80, 60))
    assert stroke.finish()
    assert doc.image.getpixel((150, 60)) == (0, 0, 0, 255)
    assert doc.undo()
    assert doc.image.tobytes() == patterned.tobytes()


def test_extreme_aspect_ratio_rejected(tmp_path, monkeypatch):
    import sumire.imaging as imaging
    path = tmp_path / "wide.png"
    Image.new("RGB", (200, 1)).save(path)
    monkeypatch.setattr(imaging, "MAX_DIMENSION", 100)
    with pytest.raises(ImageProblem, match="32,768"):
        load_image(path)


def test_a_stroke_compares_only_the_changed_area(patterned, monkeypatch):
    """Issue #1: every stroke compared the whole image with the original."""
    from PIL import ImageChops
    doc = Document(Path("test.png"), patterned)
    sizes = []
    difference = ImageChops.difference
    monkeypatch.setattr(ImageChops, "difference", lambda a, b: sizes.append(a.size) or difference(a, b))
    stroke = Stroke(doc, Tool("fill", 8))
    stroke.add((20, 20))
    stroke.finish()
    assert doc.edited and sizes and all(size != patterned.size for size in sizes)
    # Back to the original: then (only then) the whole image is compared, and it is not edited.
    sizes.clear()
    doc.undo()
    assert not doc.edited
