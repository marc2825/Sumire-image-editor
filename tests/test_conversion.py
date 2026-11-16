"""Format conversion, compression, save-as, collages and zero-padded numbering."""
import io

import pytest
from PIL import Image, PngImagePlugin
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from sumire.collage import CollageSpec, collage_layouts, render_collage
from sumire.convert import Encoding, TARGETS, encode, size_summary, writable
from sumire.export import file_digest
from sumire.imaging import ImageProblem, load_image
from sumire.metadata import MetadataStore, unpack_backup
from sumire.organize import sequence_stems
from sumire.output_dialogs import CollageDialog, ConvertDialog, LabelExportDialog

from test_gui import window
from test_editor_gui import settled


def transparent(patterned):
    image = patterned.copy()
    image.putpixel((0, 0), (10, 20, 30, 0))
    image.putpixel((1, 0), (200, 100, 50, 128))
    return image


@pytest.mark.parametrize("format", [format for format in TARGETS if writable(format)])
def test_every_target_decodes_to_a_single_metadata_free_frame(patterned, format):
    raw = encode(transparent(patterned), Encoding(format, quality=80 if format in {"JPEG", "AVIF", "HEIF"} else None,
                                                   lossless=format == "WEBP"))
    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        assert image.format == format and image.size == (160, 120) and getattr(image, "n_frames", 1) == 1
        assert format == "TIFF" or not image.getexif()


@pytest.mark.parametrize("encoding", [Encoding("PNG"), Encoding("WEBP", lossless=True), Encoding("TIFF")])
def test_lossless_encodings_keep_every_pixel_including_transparency(patterned, encoding):
    source = transparent(patterned)
    assert not encoding.lossy
    with Image.open(io.BytesIO(encode(source, encoding))) as image:
        assert image.convert("RGBA").tobytes() == source.tobytes()


def test_png_optimisation_uses_an_exact_palette_for_few_colours():
    flat = Image.new("RGBA", (200, 100), (30, 60, 90, 255))
    flat.paste((250, 10, 10, 255), (0, 0, 100, 100))
    raw = encode(flat, Encoding("PNG"))
    with Image.open(io.BytesIO(raw)) as image:
        assert image.mode == "P" and image.convert("RGBA").tobytes() == flat.tobytes()


def test_lossy_flags_and_size_limits(patterned):
    assert Encoding("JPEG", quality=80).lossy and Encoding("PNG", colors=64).lossy and Encoding("PNG", max_side=10).lossy
    assert not Encoding("WEBP", lossless=True).lossy
    raw = encode(patterned, Encoding("WEBP", lossless=True, max_side=40))
    with Image.open(io.BytesIO(raw)) as image:
        assert image.size == (40, 30)
    with pytest.raises(ImageProblem):
        encode(patterned, Encoding("JPEG", quality=0))


def test_size_summary_matches_the_requested_wording():
    assert size_summary(3_355_443, 757_760) == "元画像3.2 MB → 圧縮後740 KB（77%削減）"
    assert size_summary(1000, 1500, "変換後").endswith("（50%増加）")


@pytest.mark.parametrize("count, first, last", [(1, "00", "00"), (9, "00", "08"), (10, "00", "09"),
                                                (11, "000", "010"), (100, "000", "099"), (101, "0000", "0100")])
def test_sequence_names_share_one_width_with_a_spare_digit(count, first, last):
    stems = sequence_stems(count)
    assert stems[0] == first and stems[-1] == last and len({len(stem) for stem in stems}) == 1


def with_metadata(path, patterned):
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", "secret prompt")
    patterned.save(path, pnginfo=info)
    return path


def confirm_with(collected, configure=None, answer=True):
    def confirm(self, dialog, accepted=None):
        if isinstance(dialog, QMessageBox):
            collected.append({"title": dialog.windowTitle(), "text": dialog.text(), "info": dialog.informativeText()})
            return answer
        collected.append(type(dialog).__name__)
        if configure:
            configure(dialog)
        return True
    return confirm


def test_conversion_writes_new_files_keeps_originals_and_backs_up_metadata(qtbot, window, monkeypatch):
    page = window
    source = with_metadata(page.model.paths[0], Image.open(page.model.paths[0]).copy())
    page.reload_workspace()
    qtbot.waitUntil(lambda: not page.loading and page.document is not None and page.canvas.ready, timeout=10000)
    originals = {path: path.read_bytes() for path in page.model.paths}
    seen = []
    def configure(dialog):
        dialog.format_combo.setCurrentIndex(dialog.format_combo.findData("AVIF"))
    monkeypatch.setattr(type(page), "confirm_dialog", confirm_with(seen, configure))
    page.convert_images(list(page.model.paths), "convert")
    settled(qtbot, page)
    qtbot.waitUntil(lambda: page.batch_job is None and page.status.text().startswith("変換しました"), timeout=20000)
    folder = source.parent / "変換済み"
    outputs = sorted(folder.glob("*.avif"))
    assert seen[0] == "ConvertDialog" and seen[1]["title"] == "形式変換の確認"
    assert seen[1]["text"].startswith("元画像 合計") and "変換後 合計" in seen[1]["text"]
    assert [path.stem for path in outputs] == sorted(path.stem for path in page.model.paths)
    assert {path: path.read_bytes() for path in page.model.paths} == originals
    assert not list(folder.glob(".sumire-staging-*")) and not list(folder.glob(".sumire-convert-*"))
    converted = folder / f"{source.stem}.avif"
    with Image.open(converted) as image:
        assert image.format == "AVIF" and not image.getexif() and "parameters" not in image.info
    payload = MetadataStore(folder).get(converted, file_digest(converted))
    assert payload is not None and unpack_backup(payload)[0] == "PNG"


def test_compression_reports_sizes_and_cancel_writes_nothing(qtbot, window, monkeypatch):
    page = window
    seen = []
    def configure(dialog):
        dialog.options["jpeg"][0].setChecked(True)
    monkeypatch.setattr(type(page), "confirm_dialog", confirm_with(seen, configure, answer=False))
    page.convert_images([page.document.path], "compress")
    qtbot.waitUntil(lambda: page.batch_job is None and "取り消しました" in page.status.text(), timeout=20000)
    summary = seen[1]["text"]
    assert summary.startswith("元画像") and "→ 圧縮後" in summary and "%" in summary
    assert "非可逆" in seen[1]["info"]
    assert not (page.document.path.parent / "圧縮済み").exists()


def test_compress_dialog_separates_lossless_and_lossy_and_estimates(qtbot, patterned, tmp_path):
    dialog = ConvertDialog("compress", 3, tmp_path, ("a.png", 50_000, lambda: patterned), source_format="PNG")
    qtbot.addWidget(dialog)
    assert dialog.options["png"][0].isChecked() and not dialog.encoding().lossy
    assert dialog.quality.isHidden()
    qtbot.waitUntil(lambda: "1枚目（a.png）の試算：元画像" in dialog.estimate.text(), timeout=10000)
    assert "可逆（画質は変わりません）" in dialog.estimate.text()
    dialog.options["avif"][0].setChecked(True)
    assert dialog.encoding().lossy and not dialog.quality.isHidden() and dialog.quality.value() == 60
    qtbot.waitUntil(lambda: "非可逆" in dialog.estimate.text() and "試算：" in dialog.estimate.text(), timeout=10000)
    assert dialog.destination() == (tmp_path / "圧縮済み").resolve()
    dialog.chooser.name.setText("bad/name")
    assert not dialog.ok.isEnabled()
    dialog.reject()


def test_label_export_moves_into_a_numbered_label_folder_by_default(qtbot, window, monkeypatch):
    page = window
    paths = list(page.model.paths)
    labels = {path.name: path.read_bytes() for path in paths}
    page.write_labels({paths[0]: "accepted", paths[2]: "accepted"}, {paths[0]: None, paths[2]: None})
    assert page.export_accepted_button.isEnabled() and page.export_accepted_button.text() == "ラベルごとに書き出す…"
    seen = []
    monkeypatch.setattr(type(page), "confirm_dialog", confirm_with(seen))
    page.export_accepted_button.click()
    qtbot.waitUntil(lambda: not page.finalizing and "ラベルごとに移動しました" in page.status.text(), timeout=20000)
    folder = paths[0].parent / "採用"
    assert seen == ["LabelExportDialog"]
    assert sorted(path.name for path in folder.iterdir() if not path.name.startswith(".")) == ["00.png", "01.png"]
    assert not paths[0].exists() and not paths[2].exists() and paths[1].exists()
    assert (folder / "00.png").read_bytes() == labels[paths[0].name]  # moved as they were
    assert paths[0] not in page.model.rows and paths[1] in page.model.rows
    qtbot.waitUntil(lambda: not page.busy() and not page.saving, timeout=10000)
    page.undo_organization()
    qtbot.waitUntil(lambda: paths[0].exists() and paths[2].exists(), timeout=10000)


def test_label_export_of_every_label_copies_into_a_folder_per_label(qtbot, window, monkeypatch):
    page = window
    paths = list(page.model.paths)
    page.write_labels({paths[0]: "accepted", paths[1]: "pending", paths[2]: "rejected"}, dict.fromkeys(paths[:3]))

    def choose(self, dialog, accepted=None):
        dialog.label_combo.setCurrentIndex(dialog.label_combo.findData("all"))
        dialog.move.setChecked(False)
        return True
    monkeypatch.setattr(type(page), "confirm_dialog", choose)
    page.export_labels()
    qtbot.waitUntil(lambda: page.batch_job is None and "一括処理完了" in page.status.text(), timeout=20000)
    for folder, source in (("採用", paths[0]), ("保留", paths[1]), ("不採用", paths[2])):
        written = [path for path in (source.parent / folder).iterdir() if not path.name.startswith(".")]
        assert [path.name for path in written] == ["00.png"], folder
        with Image.open(written[0]) as image:
            assert not image.info
    assert all(path.exists() for path in paths)  # copying leaves the originals


def test_label_export_dialog_options(qtbot, tmp_path):
    dialog = LabelExportDialog({"accepted": 3, "pending": 0, "rejected": 2}, tmp_path)
    qtbot.addWidget(dialog)
    assert dialog.label() == "accepted" and dialog.moving() and not dialog.format_combo.isEnabled()
    assert dialog.renumber.isChecked() and "00, 01 … 02" in dialog.names.text() and dialog.ok.text() == "3枚を移動する"
    assert dialog.destinations() == {"accepted": (tmp_path / "採用").resolve()}
    pending = dialog.label_combo.findData("pending")
    assert not dialog.label_combo.model().item(pending).isEnabled()
    dialog.label_combo.setCurrentIndex(dialog.label_combo.findData("rejected"))
    assert dialog.chooser.name.text() == "不採用" and dialog.ok.text() == "2枚を移動する"
    dialog.label_combo.setCurrentIndex(dialog.label_combo.findData("all"))
    assert dialog.destinations() == {"accepted": tmp_path.resolve() / "採用", "rejected": tmp_path.resolve() / "不採用"}
    dialog.move.setChecked(False)
    assert dialog.format_combo.isEnabled() and dialog.format() == "SOURCE" and dialog.ok.text() == "5枚を書き出す"
    dialog.renumber.setChecked(False)
    assert "元の名前のまま" in dialog.names.text()
    dialog.chooser.elsewhere.setChecked(True)
    assert not dialog.ok.isEnabled()


def test_save_as_writes_a_clean_copy_in_the_chosen_format(qtbot, window, monkeypatch, tmp_path):
    page = window
    target = tmp_path / "copy.webp"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(target), ""))
    page.workflow_actions["save_as"].trigger()
    qtbot.waitUntil(lambda: not page.finalizing and target.exists(), timeout=10000)
    with Image.open(target) as image:
        assert image.format == "WEBP" and not image.getexif()
        assert image.convert("RGBA").tobytes() == page.document.image.tobytes()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(page.document.path), ""))
    page.save_as()
    assert "既にあるファイル" in page.status.text()


def test_collage_layouts_and_rendering(patterned):
    assert collage_layouts(2)[0][1:] == (1, 2)
    assert collage_layouts(4)[0] == ("4分割（2×2）", 2, 2)
    images = [patterned, patterned.rotate(90, expand=True), patterned, patterned]
    result = render_collage(images, CollageSpec(2, 2, "contain", 4, "#000000"))
    assert result.size == (2 * 160 + 3 * 4, 2 * 120 + 3 * 4) and result.getpixel((0, 0)) == (0, 0, 0, 255)
    covered = render_collage(images[:2], CollageSpec(2, 1, "cover", 0, None))
    # Two cells of the median size (140 × 140); "cover" fills both completely.
    assert covered.size == (140, 280) and covered.getchannel("A").getextrema() == (255, 255)
    # One image is a collage too (a frame or background around it); none, or too many, is not.
    assert len(collage_layouts(1)) == 1 and collage_layouts(1)[0][1:] == (1, 1)
    single = render_collage(images[:1], CollageSpec(1, 1, "contain", 10, "#ffffff"))
    assert single.size == (160 + 20, 120 + 20) and single.getpixel((0, 0)) == (255, 255, 255, 255)
    with pytest.raises(ImageProblem):
        render_collage([], CollageSpec(1, 1))
    with pytest.raises(ImageProblem):
        render_collage([patterned] * 17, CollageSpec(4, 5))


def test_collage_from_selection_is_saved_without_metadata(qtbot, window, monkeypatch, tmp_path):
    page = window
    page.select_paths(page.model.paths[:2])
    assert page.workflow_actions["collage"].isEnabled()
    target = tmp_path / "out" / "two.png"
    monkeypatch.setattr(type(page), "confirm_dialog", lambda self, dialog, accepted=None: isinstance(dialog, CollageDialog))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(target), ""))
    page.workflow_actions["collage"].trigger()
    qtbot.waitUntil(lambda: target.exists() and not page.finalizing, timeout=10000)
    assert load_image(target).size == (320, 120) and "コラージュを保存しました" in page.status.text()
