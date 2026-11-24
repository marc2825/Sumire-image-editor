"""1.6.0: mosaic sized to the image, copying the processed area, size-capped and watermarked exports."""
import io
import math

import pytest
from PIL import Image, ImageChops, ImageDraw
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QDialog

from sumire.area_copy import apply_area, placed_mask
from sumire.convert import STRUCTURAL_INFO, Encoding, encode
from sumire.imaging import ImageProblem, Tool, load_image
from sumire.masks import MaskStore
from sumire.output_dialogs import ConvertDialog
from sumire.export import file_digest
from sumire.watermark import Watermark, apply_watermark
from sumire.window import Window

from test_gui import draw


def noise(size, seed=0):
    image = Image.effect_noise(size, 50 + seed).convert("L")
    return Image.merge("RGBA", (image, image.transpose(Image.Transpose.FLIP_LEFT_RIGHT), image.point(lambda v: 255 - v),
                                Image.new("L", size, 255)))


@pytest.fixture
def sized(qtbot, tmp_path):
    """A window on three images of different sizes (long sides 1250, 640 and 300 px)."""
    for name, size in (("a.png", (1250, 500)), ("b.png", (480, 640)), ("c.png", (300, 200))):
        noise(size).save(tmp_path / name)
    widget = Window()
    with qtbot.waitExposed(widget):
        widget.show()
    widget.open_inputs([str(tmp_path)])
    qtbot.waitUntil(lambda: widget.document is not None and widget.canvas.ready, timeout=10000)
    yield widget
    qtbot.waitUntil(lambda: not widget.finalizing and not widget.saving and not widget.loading and widget.batch_job is None, timeout=20000)
    widget.auto.setChecked(False)
    widget.pending_action = None
    if widget.document:
        widget.document.saved_revision = widget.document.revision
    widget.close()


def show(qtbot, window, index):
    window.request_index(index)
    qtbot.waitUntil(lambda: window.index == index and window.document is not None and window.canvas.ready and not window.busy(),
                    timeout=10000)


# --- mosaic: 1/100 of the longer side -------------------------------------------------------------

def test_mosaic_follows_one_hundredth_of_the_longer_side(qtbot, sized):
    window = sized
    window.set_mode("mosaic")
    assert window.mosaic_block_for((1250, 500)) == 13 and window.mosaic_block_for((100, 50)) == 2
    assert window.mosaic_block_for((1201, 10)) == math.ceil(1201 / 100) == 13
    window.strength.setValue(5)
    window.mosaic_fit.setChecked(True)
    assert window.strength.value() == 13 and "13 px" in window.mosaic_fit.text()
    show(qtbot, window, 1)
    assert window.strength.value() == 7  # 640 / 100, rounded up
    # In another tool the mosaic's own size still follows the image.
    window.set_mode("blur")
    show(qtbot, window, 2)
    assert window.mode_strengths["mosaic"] == 3
    window.set_mode("mosaic")
    assert window.strength.value() == 3 and window.mosaic_fit.isChecked()
    # A size set by hand is the user's choice: fitting stops.
    window.strength.setValue(10)
    assert not window.mosaic_fit.isChecked() and window.strength.value() == 10
    show(qtbot, window, 0)
    assert window.strength.value() == 10
    assert window.workspace_settings()["mosaic_fit"] is False
    window.set_mode("fill")
    assert window.mosaic_fit.isHidden()


def test_mosaic_fit_can_go_past_the_slider_maximum(qtbot, tmp_path):
    noise((12_340, 40)).save(tmp_path / "wide.png")
    window = Window()
    qtbot.addWidget(window)
    window.show()
    window.open_inputs([str(tmp_path)])
    qtbot.waitUntil(lambda: window.document is not None and window.canvas.ready, timeout=20000)
    window.mosaic_fit.setChecked(True)
    assert window.strength.value() == 124 and window.strength.maximum() >= 124
    window.auto.setChecked(False)


# --- copying the processed area -------------------------------------------------------------------

def test_area_is_placed_relative_or_at_the_same_pixels():
    mask = Image.new("L", (100, 50))
    ImageDraw.Draw(mask).rectangle((80, 40, 99, 49), fill=255)
    relative = placed_mask(mask, (200, 200), "relative")
    assert relative.getbbox() == (160, 160, 200, 200)
    pixels = placed_mask(mask, (200, 200), "pixels")
    assert pixels.getbbox() == (80, 40, 100, 50)
    image = noise((200, 200))
    result, new_mask, changed = apply_area(image, None, relative, Tool("fill", color="#000000"))
    assert changed and new_mask.getbbox() == (160, 160, 200, 200)
    assert result.getpixel((180, 180)) == (0, 0, 0, 255) and result.getpixel((10, 10)) == image.getpixel((10, 10))
    unchanged, _, changed = apply_area(image, None, Image.new("L", (200, 200)), Tool("mosaic"))
    assert not changed and unchanged is image


def test_processed_area_is_copied_to_the_selected_images_and_saved(qtbot, sized, monkeypatch):
    window = sized
    window.auto.setChecked(False)
    window.set_mode("fill")
    window.strength.setValue(100)
    window.shape_combo.setCurrentIndex(window.shape_combo.findData("rectangle"))
    qtbot.waitUntil(lambda: window.canvas.ready and not window.busy())  # the fill effect is prepared first
    # The lower right of the 1250×500 image (the canvas may show a reduced copy of a large image).
    shown = window.canvas.image.width() / window.document.image.width
    draw(window, (900 * shown, 300 * shown), (1200 * shown, 450 * shown))
    qtbot.waitUntil(lambda: not window.finalizing and window.canvas.ready)
    assert window.workflow_actions["copy_area"].isEnabled()
    # (Unsaved, the shown image would first be saved, or the user asked: autosave is off here.)
    window.save()
    qtbot.waitUntil(lambda: window.document.saved_revision == window.document.revision and not window.saving, timeout=10000)
    source_area = window.document.edit_mask.getbbox()
    first, second, third = window.model.paths
    before = {path: path.read_bytes() for path in (second, third)}
    selection = window.list.selectionModel()
    selection.select(window.proxy.index(1, 0), QItemSelectionModel.SelectionFlag.Select)
    seen = []

    def accept(self, dialog, accepted=None):
        seen.append(dialog.chosen())
        return True
    monkeypatch.setattr(type(window), "confirm_dialog", accept)
    window.workflow_actions["copy_area"].trigger()
    qtbot.waitUntil(lambda: window.batch_job is None and "加工の範囲を写しました" in window.status.text(), timeout=20000)
    assert seen and seen[0][0] == [second] and seen[0][1:] == ("fill", "relative")
    assert "保存 1 / 失敗 0" in window.status.text()
    assert third.read_bytes() == before[third]  # not selected: untouched
    # Overwritten in place (the tests save over originals), black in the same relative area.
    copied = load_image(second).convert("RGBA")
    width, height = copied.size
    scale_x, scale_y = width / 1250, height / 500
    inside = (round((source_area[0] + source_area[2]) / 2 * scale_x), round((source_area[1] + source_area[3]) / 2 * scale_y))
    assert copied.getpixel(inside) == (0, 0, 0, 255)
    assert copied.getpixel((5, 5)) != (0, 0, 0, 255)
    stored = MaskStore(second.parent).get(second, file_digest(second), copied.size)
    assert stored is not None and stored.getpixel(inside) == 255
    # The copied image shows its new pixels when opened.
    show(qtbot, window, 1)
    assert window.document.image.getpixel(inside) == (0, 0, 0, 255)


def test_nothing_to_copy_without_a_processed_area(window_three):
    window = window_three
    window.copy_area_to_images()
    assert "写せる加工の範囲がありません" in window.status.text()


@pytest.fixture
def window_three(qtbot, tmp_path, patterned):
    for name in ("one.png", "two.png", "three.png"):
        patterned.save(tmp_path / name)
    widget = Window()
    qtbot.addWidget(widget)
    widget.show()
    widget.open_inputs([str(tmp_path)])
    qtbot.waitUntil(lambda: widget.document is not None and widget.canvas.ready, timeout=10000)
    yield widget
    widget.auto.setChecked(False)


# --- exports: a size cap and a watermark ----------------------------------------------------------

@pytest.mark.parametrize("encoding", [Encoding("JPEG", quality=95, max_bytes=60 * 1024), Encoding("PNG", max_bytes=120 * 1024),
                                      Encoding("WEBP", lossless=True, max_bytes=80 * 1024)])
def test_size_cap_is_met_by_quality_then_by_size(encoding):
    raw = encode(noise((900, 700)), encoding)
    assert len(raw) <= encoding.max_bytes and encoding.lossy
    with Image.open(io.BytesIO(raw)) as result:
        assert result.format == encoding.format and not set(result.info) - STRUCTURAL_INFO


def test_size_cap_lowers_the_quality_before_the_size():
    smooth = Image.linear_gradient("L").resize((900, 700)).convert("RGBA")
    full = encode(smooth, Encoding("JPEG", quality=95))
    raw = encode(smooth, Encoding("JPEG", quality=95, max_bytes=len(full) * 3 // 4))
    with Image.open(io.BytesIO(raw)) as result:
        assert result.size == (900, 700) and len(raw) <= len(full) * 3 // 4


def test_size_cap_that_cannot_be_met_is_refused():
    with pytest.raises(ImageProblem, match="上限"):
        encode(noise((600, 600)), Encoding("PNG", max_bytes=1024))
    with pytest.raises(ImageProblem):
        encode(noise((60, 60)), Encoding("PNG", max_bytes=10))


def test_watermark_text_sits_in_its_corner_and_signature_images_work(tmp_path):
    base = Image.new("RGBA", (800, 600), (40, 90, 140, 255))
    marked = apply_watermark(base, Watermark(text="© 2026 Sumīre 透かし", position="bottom_right", opacity=100))
    box = ImageChops.difference(marked, base).getbbox(alpha_only=False)
    assert box is not None and box[0] > 400 and box[1] > 450 and box[2] <= 800 and box[3] <= 600
    assert apply_watermark(base, Watermark()) is base  # nothing to draw
    signature = Image.new("RGBA", (200, 80))
    ImageDraw.Draw(signature).ellipse((5, 5, 195, 75), outline=(255, 0, 0, 255), width=6)
    signature.save(tmp_path / "sign.png")
    signed = apply_watermark(base, Watermark(image=str(tmp_path / "sign.png"), position="top_left", size=10, shadow=False))
    box = ImageChops.difference(signed, base).getbbox(alpha_only=False)
    assert box is not None and box[0] < 40 and box[1] < 40 and box[3] - box[1] == 80  # 10 % of the longer side
    tiled = apply_watermark(base, Watermark(text="SAMPLE", position="tiled"))
    difference = ImageChops.difference(tiled, base).convert("L").point(lambda v: 255 if v else 0)
    quarters = [difference.crop((x, y, x + 400, y + 300)).getbbox() for x in (0, 400) for y in (0, 300)]
    assert all(quarters)  # repeated across the whole image
    with pytest.raises(ImageProblem):
        apply_watermark(base, Watermark(image=str(tmp_path / "missing.png")))


def test_watermark_settings_are_checked_when_read():
    mark = Watermark.from_settings({"text": "x" * 500, "position": "nowhere", "size": 99, "opacity": 0, "color": "red", "shadow": "yes"})
    assert len(mark.text) == 200 and mark.position == "bottom_right" and mark.size == 4 and mark.opacity == 60
    assert mark.color == "#ffffff" and mark.shadow is True
    assert Watermark.from_settings(Watermark(text="a", size=8).to_settings()) == Watermark(text="a", size=8)


def test_export_dialog_adds_the_cap_and_the_mark_and_keeps_originals_unmarked(qtbot, tmp_path):
    sample = ("a.png", 10_000, lambda: noise((300, 200)))
    dialog = ConvertDialog("compress", 2, tmp_path, sample, watermark=Watermark(text="© me"), watermark_on=True,
                           size_limit_kb=300, size_limit_on=True)
    qtbot.addWidget(dialog)
    encoding = dialog.encoding()
    assert encoding.max_bytes == 300 * 1024 and encoding.watermark.text == "© me"
    qtbot.waitUntil(lambda: dialog.preview.isVisible() or not dialog.isVisible(), timeout=1)  # not shown: no wait needed
    dialog.replace.setChecked(True)
    assert not dialog.ok.isEnabled() and "上書きできません" in dialog.problem.text()
    dialog.mark_on.setChecked(False)
    assert dialog.ok.isEnabled() and dialog.encoding().watermark is None
    dialog.done(QDialog.DialogCode.Rejected)


def test_convert_remembers_the_mark_and_the_cap(qtbot, window_three, monkeypatch):
    window = window_three
    chosen = {}

    def accept(self, dialog, accepted=None):
        if isinstance(dialog, ConvertDialog):
            dialog.mark_on.setChecked(True)
            dialog.mark_text.setText("© 2026")
            dialog.size_limit.setChecked(True)
            dialog.size_limit_value.setValue(500)
            chosen["encoding"] = dialog.encoding()
            return True
        return False  # the size confirmation: stop before writing
    monkeypatch.setattr(type(window), "confirm_dialog", accept)
    window.convert_images(list(window.model.paths), "convert")
    qtbot.waitUntil(lambda: window.batch_job is None, timeout=20000)
    remembered = window.preferences.data["export"]
    assert remembered["watermark"]["text"] == "© 2026" and remembered["watermark_on"] is True
    assert remembered["size_limit_kb"] == 500 and remembered["size_limit_on"] is True
    assert chosen["encoding"].max_bytes == 500 * 1024
