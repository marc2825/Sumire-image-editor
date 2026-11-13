from pathlib import Path

import pytest
from PIL import Image, ImageChops, PngImagePlugin

from sumire.editing import EditSpec, apply_edit, geometry, resized_output
from sumire.export import file_digest, save_image, verify_export
from sumire.imaging import Document, ImageProblem, Stroke, Tool, region_mask
from sumire.metadata import inspect_metadata
from sumire.projects import read_project, write_project
from sumire.masks import MaskStore
from sumire.preferences import Preferences
from sumire.storage import migrate_records
from sumire.organize import rename_images


def document(patterned):
    doc = Document(Path("source.png"), patterned)
    doc.edit_mask.paste(255, (10, 20, 40, 70))
    return doc


@pytest.mark.parametrize("spec,expected", [
    (EditSpec(crop=(7, 13, 100, 60)), (100, 60)),
    (EditSpec(rotation=90), (120, 160)), (EditSpec(rotation=180), (160, 120)),
    (EditSpec(rotation=270, horizontal=True), (120, 160)), (EditSpec(vertical=True), (160, 120)),
    (EditSpec(size=(80, 30)), (80, 30)),
    (EditSpec(crop=(10, 20, 90, 60), rotation=90, size=(30, 45)), (30, 45)),
])
def test_geometry_transforms_pixels_original_and_binary_mask_together(patterned, spec, expected):
    doc = document(patterned)
    mask = doc.edit_mask.copy()
    initial = patterned.tobytes()
    assert apply_edit(doc, spec)
    assert doc.image.size == doc.original.size == doc.edit_mask.size == expected
    assert doc.image.tobytes() == geometry(patterned, spec).tobytes()
    assert doc.edit_mask.tobytes() == geometry(mask, spec, mask=True).tobytes()
    assert set(doc.edit_mask.tobytes()) <= {0, 255}
    assert doc.edited and doc.dirty
    assert doc.initial_original.tobytes() == initial
    assert doc.undo()
    assert doc.image.size == patterned.size and doc.image.tobytes() == initial
    assert doc.edit_mask.tobytes() == mask.tobytes()
    assert not doc.geometry_edited and not doc.edited
    assert doc.redo() and doc.image.size == expected


def test_mixed_brush_full_image_undo_reset_and_eraser(patterned):
    doc = document(patterned)
    stroke = Stroke(doc, Tool("fill", 16, color="#f0f000", expansion=0))
    stroke.add((25, 40))
    assert stroke.finish()
    painted = doc.image.copy()
    assert apply_edit(doc, EditSpec(crop=(10, 20, 80, 70), rotation=90))
    transformed = doc.image.copy()
    eraser = Stroke(doc, Tool("erase", 12, expansion=0))
    eraser.add((20, 20))
    eraser.finish()
    assert doc.image.getpixel((20, 20)) == doc.original.getpixel((20, 20))
    assert doc.reset_edits() and doc.image.size == patterned.size
    assert doc.image.tobytes() == patterned.tobytes() and not doc.edit_mask.getbbox()
    assert doc.undo() and doc.image.size == transformed.size
    assert doc.undo() and doc.image.tobytes() == transformed.tobytes()
    assert doc.undo() and doc.image.tobytes() == painted.tobytes()
    assert doc.undo() and doc.image.tobytes() == patterned.tobytes()


@pytest.mark.parametrize("spec", [EditSpec(brightness=0.5), EditSpec(contrast=1.8), EditSpec(saturation=0),
                                     EditSpec(brightness=1.2, contrast=1.2, saturation=0.5)])
def test_color_preserves_alpha_mask_and_original_and_can_undo(patterned, spec):
    image = patterned.copy()
    image.putalpha(Image.linear_gradient("L").resize(image.size))
    doc = document(image)
    mask = doc.edit_mask.tobytes()
    assert apply_edit(doc, spec)
    assert doc.image.getchannel("A").tobytes() == image.getchannel("A").tobytes()
    assert doc.edit_mask.tobytes() == mask and doc.original.tobytes() == image.tobytes()
    assert not doc.geometry_edited
    assert doc.undo() and doc.image.tobytes() == image.tobytes()


@pytest.mark.parametrize("spec", [EditSpec(size=(0, 10)), EditSpec(size=(10000, 10000)), EditSpec(crop=(-1, 0, 20, 20)),
                                     EditSpec(crop=(150, 0, 100, 30)), EditSpec(rotation=45), EditSpec(brightness=4)])
def test_invalid_edit_keeps_document_and_history_unchanged(patterned, spec):
    doc = document(patterned)
    snapshot = doc.snapshot()
    with pytest.raises(ImageProblem):
        apply_edit(doc, spec)
    assert doc.snapshot() == snapshot and not doc.undo_stack


def test_polygon_lasso_invert_and_expansion_have_hard_edges():
    points = [(10, 10), (70, 15), (20, 70)]
    mask = region_mask((100, 100), points, "polygon")
    assert mask.getpixel((20, 20)) == 255 and mask.getpixel((80, 80)) == 0
    assert region_mask((100, 100), points, "lasso").tobytes() == mask.tobytes()
    inverse = region_mask((100, 100), points, "polygon", invert=True)
    assert ImageChops.add(mask, inverse).getextrema() == (255, 255)
    expanded = region_mask((100, 100), points, "polygon", 3)
    assert sum(expanded.histogram()[255:]) > sum(mask.histogram()[255:])
    assert set(expanded.tobytes()) == {0, 255}


def test_project_after_geometry_preserves_full_reset_and_mask(patterned, tmp_path):
    doc = document(patterned)
    apply_edit(doc, EditSpec(crop=(10, 20, 80, 70), rotation=90, brightness=0.6))
    target = tmp_path / "geometry.sumire"
    write_project(target, doc.original, doc.image, doc.edit_mask,
                  {"edited": True, "original_edited": False, "original_known": True, "geometry": True}, initial=doc.initial_original)
    restored = read_project(target)
    assert restored.image.size == doc.image.size
    assert restored.image.tobytes() == doc.image.tobytes()
    assert restored.edit_mask.tobytes() == doc.edit_mask.tobytes()
    assert restored.reset_edits() and restored.image.size == patterned.size
    assert restored.image.tobytes() == patterned.tobytes()


def test_geometry_recipe_tracks_digest_rename_and_record_migration(tmp_path, patterned):
    source = tmp_path / "input.png"
    patterned.save(source)
    digest = file_digest(source)
    steps = [{"crop": [10, 20, 80, 60], "rotation": 90}]
    store = MaskStore(tmp_path)
    store.store_geometry(source, digest, steps, digest)
    assert store.get_geometry(source, digest, digest) == steps
    assert store.get_geometry(source, b"wrong", digest) is None
    renamed = tmp_path / "renamed.png"
    rename_images({source: renamed}, record_folders={tmp_path})
    assert store.get_geometry(renamed, digest, digest) == steps
    assert store.get_geometry(source, digest, digest) is None
    migrate_records([tmp_path], "app", Preferences())
    assert MaskStore(tmp_path).get_geometry(renamed, digest, digest) == steps


def test_scaled_output_keeps_editor_resolution_and_jpeg_quality(patterned, tmp_path):
    source = tmp_path / "source.png"
    patterned.save(source)
    digest = source.read_bytes()
    original = patterned.tobytes()
    small = resized_output(patterned, (80, 80))
    assert small.size == (80, 60)
    assert resized_output(patterned, (1000, 1000)).size == patterned.size
    for quality in (20, 95):
        path = tmp_path / f"quality-{quality}.jpg"
        save_image(small, path, source=source, format="JPEG", jpeg_quality=quality)
        verify_export(path, small.size, "JPEG")
    assert (tmp_path / "quality-20.jpg").stat().st_size < (tmp_path / "quality-95.jpg").stat().st_size
    assert source.read_bytes() == digest and patterned.tobytes() == original


def test_metadata_inspection_exposes_fixed_categories_only(tmp_path, patterned, encode_stealth):
    source = tmp_path / "private.png"
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", "sensitive prompt never displayed")
    info.add_text("unusual private key", "private camera note")
    encode_stealth(Image.new("RGBA", (100, 100), "white")).save(source, pnginfo=info)
    original = source.read_bytes()
    categories = inspect_metadata(source)
    assert "生成プロンプト" in categories and "Stealth PNGInfo（隠し情報）" in categories
    assert "private" not in repr(categories) and "sensitive" not in repr(categories)
    assert source.read_bytes() == original
    clean = tmp_path / "clean.png"
    patterned.save(clean)
    assert inspect_metadata(clean) == []
