"""Behavioral regression coverage for decoding, cached effects, and memory release."""
import threading

import pytest
from PIL import Image, ImageCms, ImageFile
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from sumire.imaging import Document, Stroke, Tool, brush_segment, load_image, load_thumbnail, make_effect
from sumire.library import LibraryModel

from test_gui import draw, window
from test_workspace_tabs import open_page, picture, ready, tabs


@pytest.mark.parametrize("kind", ["RGBA", "P", "L", "ICC", "EXIF", "stealth-alpha", "stealth-rgb"])
def test_preview_preserves_transparency_colour_orientation_and_cleans_metadata(tmp_path, patterned, encode_stealth, kind):
    image = patterned.resize((640, 480))
    options = {}
    if kind == "RGBA":
        image.putalpha(Image.linear_gradient("L").resize(image.size))
    elif kind in {"P", "L"}:
        image = image.convert(kind)
        if kind == "P":
            options["transparency"] = 0
    elif kind == "ICC":
        options["icc_profile"] = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    elif kind == "EXIF":
        exif = Image.Exif()
        exif[274] = 6
        options["exif"] = exif
    elif kind.startswith("stealth"):
        image = encode_stealth(image, channel="alpha" if kind.endswith("alpha") else "rgb")
    path = tmp_path / "preview.png"
    image.save(path, **options)
    original = path.read_bytes()
    expected = load_image(path)
    expected.thumbnail((256, 256), Image.Resampling.LANCZOS)
    result = load_thumbnail(path)
    assert result.size == expected.size and result.mode == "RGBA"
    assert result.tobytes() == expected.tobytes()
    assert not result.info and not result.getexif()
    assert path.read_bytes() == original


def test_jpeg_preview_uses_decoder_reduction_with_orientation_and_profile(tmp_path, monkeypatch):
    path = tmp_path / "large.jpg"
    exif = Image.Exif()
    exif[274] = 6
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    Image.new("RGB", (2048, 1024), (180, 60, 40)).save(path, exif=exif, icc_profile=profile)
    from PIL import JpegImagePlugin
    original = JpegImagePlugin.JpegImageFile.load
    sizes = []
    def track(image, *args, **kwargs):
        if image.tile:
            sizes.append(image.size)
        return original(image, *args, **kwargs)
    monkeypatch.setattr(JpegImagePlugin.JpegImageFile, "load", track)
    result = load_thumbnail(path)
    assert result.size == (128, 256)
    assert sizes and sizes[0][0] < 2048
    assert all(abs(a - b) <= 3 for a, b in zip(result.getpixel((30, 30)), (180, 60, 40, 255)))
    assert not result.info


def test_preview_rejects_oversized_and_animated_inputs(tmp_path, monkeypatch):
    from sumire import imaging
    from sumire.imaging import ImageProblem
    path = tmp_path / "large.png"
    Image.new("RGB", (32, 24)).save(path)
    monkeypatch.setattr(imaging, "MAX_PIXELS", 500)
    with pytest.raises(ImageProblem, match="大きすぎ"):
        load_thumbnail(path)
    monkeypatch.setattr(imaging, "MAX_PIXELS", 24_000_000)
    Image.new("RGB", (32, 24), "red").save(path, save_all=True, append_images=[Image.new("RGB", (32, 24), "blue")])
    with pytest.raises(ImageProblem, match="アニメーション"):
        load_thumbnail(path)


def test_sort_and_append_preserve_thumbnails_but_reload_invalidates(qapp, tmp_path):
    from PySide6.QtGui import QIcon, QPixmap
    paths = [tmp_path / f"{n}.png" for n in range(3)]
    model = LibraryModel()
    model.set_paths(paths[:2])
    model.cache[paths[0]] = QIcon(QPixmap(20, 20))
    key = model.cache[paths[0]].cacheKey()
    model.set_paths([paths[1], paths[0], paths[2]], preserve_cache=True)
    assert model.cache[paths[0]].cacheKey() == key
    model.set_paths(paths)
    assert not model.cache


def test_brush_geometry_changes_reuse_effect_and_strength_rebuilds(qtbot, window, monkeypatch):
    import sumire.window as module
    qtbot.waitUntil(lambda: window.effect_job is None)
    original = module.make_effect
    calls = []
    monkeypatch.setattr(module, "make_effect", lambda image, tool: calls.append(tool.effect_key) or original(image, tool))
    effect = window.canvas.effect
    window.brush.setValue(window.brush.value() + 15)
    window.expansion.setValue((window.expansion.value() + 1) % (window.expansion.maximum() + 1))
    window.shape_combo.setCurrentIndex(window.shape_combo.findData("rectangle"))
    qtbot.wait(150)
    assert window.canvas.ready and window.canvas.effect is effect and not calls
    window.strength.setValue(window.strength.value() + 1)
    qtbot.waitUntil(lambda: bool(calls) and window.canvas.ready and window.effect_job is None)
    assert len(calls) == 1 and window.canvas.effect is not effect


@pytest.mark.parametrize("return_to_previous", [False, True])
def test_effect_in_flight_handles_geometry_and_return_to_previous_strength(qtbot, window, monkeypatch, return_to_previous):
    import sumire.window as module
    qtbot.waitUntil(lambda: window.effect_job is None)
    original = module.make_effect
    started, release = threading.Event(), threading.Event()
    previous = window.strength.value()
    calls = []
    def slow(image, tool):
        calls.append(tool.effect_key)
        started.set()
        release.wait(5)
        return original(image, tool)
    monkeypatch.setattr(module, "make_effect", slow)
    window.strength.setValue(previous + 1)
    qtbot.waitUntil(started.is_set)
    try:
        window.brush.setValue(window.brush.value() + 2)
        if return_to_previous:
            window.strength.setValue(previous)
        qtbot.wait(100)
    finally:
        release.set()
    qtbot.waitUntil(lambda: window.canvas.ready and window.effect_job is None)
    assert calls[-1] == ("mosaic", previous if return_to_previous else previous + 1)
    assert len(calls) == (2 if return_to_previous else 1)


@pytest.mark.parametrize("overwrite", [True, False])
def test_reopen_saved_image_decodes_each_file_once(qtbot, window, monkeypatch, overwrite):
    window.list.hide()
    window.model.pool.waitForDone()
    window.overwrite.setChecked(overwrite)
    window.save()
    qtbot.waitUntil(lambda: window.document.output is not None and not window.saving)
    source, output = window.document.path, window.document.output
    window.documents.clear()
    decodes = []
    original = ImageFile.ImageFile.load
    def track(image, *args, **kwargs):
        if image.tile:
            decodes.append(str(image.filename))
        return original(image, *args, **kwargs)
    monkeypatch.setattr(ImageFile.ImageFile, "load", track)
    window._load_index(window.index)
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready)
    assert decodes.count(str(source)) == 1
    assert decodes.count(str(output)) == 1
    assert window.document.saved_revision == 0


def test_background_tab_releases_display_and_preserves_edit_undo_mask_zoom(qtbot, tabs, tmp_path, patterned):
    a = open_page(qtbot, tabs, picture(tmp_path / "a.png", patterned))
    a.auto.setChecked(False)
    draw(a)
    ready(qtbot, a)
    a.canvas.zoom(1.5)
    scale, offset = a.canvas.scale, a.canvas.offset
    document = a.document
    pixels, mask = document.image.tobytes(), document.edit_mask.tobytes()
    before = a.memory_usage
    b = open_page(qtbot, tabs, picture(tmp_path / "b.png", patterned), "new")
    assert a.canvas.image.isNull() and a.canvas.original.isNull() and a.canvas.effect is None
    assert a.memory_usage < before and a.document is document and document.dirty
    tabs.tabs.setCurrentWidget(a)
    ready(qtbot, a)
    assert a.canvas.scale == scale and a.canvas.offset == offset
    assert document.image.tobytes() == pixels and document.edit_mask.tobytes() == mask
    a.history()
    ready(qtbot, a)
    assert not document.edited and document.redo_stack
    assert b.canvas.image.isNull()


def test_global_budget_evicts_cached_documents_and_protects_open_edits(qtbot, tabs, tmp_path, patterned):
    a = open_page(qtbot, tabs, picture(tmp_path / "a.png", patterned))
    cached_path = picture(tmp_path / "cached.png", patterned)
    a.documents[cached_path] = Document(cached_path, patterned)
    a.auto.setChecked(False)
    draw(a)
    ready(qtbot, a)
    document = a.document
    b = open_page(qtbot, tabs, picture(tmp_path / "b.png", patterned), "new")
    tabs.memory_limit = 1
    tabs.trim_memory()
    assert cached_path not in a.documents
    assert a.documents[document.path] is document and document.dirty and document.undo_stack
    assert b.document.path in b.documents
    tabs.tabs.setCurrentWidget(a)
    ready(qtbot, a)


def test_switching_tabs_during_a_gesture_cancels_only_that_gesture(qtbot, tabs, tmp_path, patterned):
    a = open_page(qtbot, tabs, picture(tmp_path / "a.png", patterned))
    a.auto.setChecked(False)
    draw(a)
    ready(qtbot, a)
    pixels, mask = a.document.image.tobytes(), a.document.edit_mask.tobytes()
    history = list(a.document.undo_stack)
    point = (a.canvas.offset + a.canvas.scale * QPointF(80, 70)).toPoint()
    QTest.mousePress(a.canvas, Qt.MouseButton.LeftButton, pos=point)
    assert a.canvas.stroke is not None
    open_page(qtbot, tabs, picture(tmp_path / "b.png", patterned), "new")
    assert a.canvas.stroke is None and not a.busy()
    assert a.document.image.tobytes() == pixels and a.document.edit_mask.tobytes() == mask
    assert a.document.undo_stack == history
    tabs.tabs.setCurrentWidget(a)
    ready(qtbot, a)


@pytest.mark.parametrize("mode", ["fill", "blur", "mosaic", "erase"])
def test_sparse_stroke_overlaps_tiles_cancel_undo_redo(tmp_path, patterned, mode):
    image = patterned.resize((521, 393))
    document = Document(tmp_path / "test.png", image)
    if mode == "erase":
        first = Stroke(document, Tool("fill", diameter=100))
        first.add((220, 190))
        first.finish()
    before, mask_before = document.image.tobytes(), document.edit_mask.tobytes()
    tool = Tool(mode, diameter=35, expansion=2, opacity=50)
    effect = document.original if mode == "erase" else make_effect(document.image, tool)
    expected = document.image.copy()
    mask = Image.new("L", image.size)
    points = [(120, 120), (140, 135), (260, 260), (120, 120)]
    last = points[0]
    for point in points:
        brush_segment(mask, last, point, tool.diameter + 2 * tool.expansion)
        last = point
    expected.paste(effect, (0, 0), mask)
    stroke = Stroke(document, tool, effect)
    assert not stroke.tiles
    for point in points:
        stroke.add(point)
    assert document.image.tobytes() == expected.tobytes()
    stroke.cancel()
    assert document.image.tobytes() == before and document.edit_mask.tobytes() == mask_before
    stroke = Stroke(document, tool, effect)
    for point in points:
        stroke.add(point)
    assert stroke.finish()
    after_mask = document.edit_mask.tobytes()
    assert document.undo()
    assert document.image.tobytes() == before and document.edit_mask.tobytes() == mask_before
    assert document.redo()
    assert document.image.tobytes() == expected.tobytes() and document.edit_mask.tobytes() == after_mask


def test_tiny_stroke_captures_small_region_in_large_image(tmp_path):
    document = Document(tmp_path / "large.png", Image.new("RGBA", (2048, 2048), "white"))
    effect = Image.new("RGBA", document.image.size, "black")
    stroke = Stroke(document, Tool("fill", diameter=10), effect)
    stroke.add((500, 500))
    captured = sum(pixels.width * pixels.height * 5 for pixels, mask in stroke.tiles.values())
    assert captured < 128 * 128 * 5 * 5
    stroke.cancel()
    assert document.image.getpixel((500, 500)) == (255, 255, 255, 255)


def test_folder_scan_runs_off_gui_thread_and_ignores_old_scope(qtbot, window, tmp_path, monkeypatch):
    window.watch_timer.stop()
    monitor = window.watch_monitor
    started, release = threading.Event(), threading.Event()
    main_thread = threading.get_ident()
    threads = []
    original = monitor.scan
    def slow(*args):
        threads.append(threading.get_ident())
        started.set()
        release.wait(5)
        return original(*args)
    monkeypatch.setattr(monitor, "scan", slow)
    window.poll_folders()
    qtbot.waitUntil(started.is_set)
    try:
        assert threads == [threads[0]] and threads[0] != main_thread
        assert monitor.job is not None
        monitor.set_scope(set())
        qtbot.wait(30)
    finally:
        release.set()
    qtbot.waitUntil(lambda: monitor.job is None)
    assert not monitor.candidates


def test_idle_monitor_does_not_rescan_until_notification_or_fallback(qtbot, window, monkeypatch):
    window.watch_timer.stop()
    monitor = window.watch_monitor
    calls = []
    original = monitor.scan
    monkeypatch.setattr(monitor, "scan", lambda *args: calls.append(1) or original(*args))
    window.poll_folders()
    qtbot.waitUntil(lambda: monitor.job is None)
    # Consume any native notification generated during setup.
    monitor.dirty = False
    for _ in range(5):
        window.poll_folders()
    assert len(calls) == 1
    monitor.changed()
    window.poll_folders()
    qtbot.waitUntil(lambda: monitor.job is None)
    assert len(calls) == 2
    monitor.last_scan -= 31
    window.poll_folders()
    qtbot.waitUntil(lambda: monitor.job is None)
    assert len(calls) == 3


def test_monitor_rechecks_empty_then_growing_files_without_new_notification(qtbot, window, tmp_path, patterned):
    window.watch_timer.stop()
    path = tmp_path / "writing.png"
    path.touch()
    window.poll_folders()
    qtbot.waitUntil(lambda: window.watch_monitor.job is None)
    assert path not in window.model.rows
    assert path in window.watch_monitor.candidates
    patterned.save(path)
    window.poll_folders()
    qtbot.waitUntil(lambda: window.watch_monitor.job is None)
    assert path not in window.model.rows
    window.poll_folders()
    qtbot.waitUntil(lambda: window.watch_monitor.job is None)
    assert path in window.model.rows


def test_new_folder_cannot_receive_pending_discovery_from_previous_scope(qtbot, window, tmp_path, patterned):
    previous = tmp_path / "previous-new.png"
    patterned.save(previous)
    window.poll_folders()
    qtbot.waitUntil(lambda: window.watch_monitor.job is None)
    window.loading = True
    window.accept_watched_images([previous])
    assert window.watch_pending == {previous}
    window.loading = False
    folder = tmp_path / "next"
    folder.mkdir()
    source = picture(folder / "next.png", patterned)
    window.open_inputs([str(folder)])
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready)
    assert window.model.paths == [source] and not window.watch_pending
    assert window.watch_monitor.folders == {folder}


def test_background_autosave_finishes_without_rebuilding_display(qtbot, tabs, tmp_path, patterned):
    a = open_page(qtbot, tabs, picture(tmp_path / "a.png", patterned))
    draw(a)
    qtbot.waitUntil(lambda: not a.finalizing)
    document = a.document
    open_page(qtbot, tabs, picture(tmp_path / "b.png", patterned), "new")
    qtbot.waitUntil(lambda: not a.saving and document.saved_revision == document.revision)
    assert a.canvas.image.isNull() and a.canvas.effect is None
    with Image.open(document.output) as saved:
        assert saved.convert("RGBA").tobytes() == document.image.tobytes()


def test_deferred_discovery_checks_stability_again_after_busy_period(qtbot, window, tmp_path, patterned):
    window.watch_timer.stop()
    path = tmp_path / "deferred.png"
    patterned.save(path)
    window.poll_folders()
    qtbot.waitUntil(lambda: window.watch_monitor.job is None)
    window.loading = True
    window.accept_watched_images([path])
    assert path in window.watch_pending
    patterned.resize((320, 240)).save(path)
    window.loading = False
    window.poll_folders()
    qtbot.waitUntil(lambda: window.watch_monitor.job is None)
    assert path not in window.model.rows
    window.poll_folders()
    qtbot.waitUntil(lambda: window.watch_monitor.job is None)
    assert path in window.model.rows


@pytest.mark.parametrize("overwrite", [False, True])
def test_verified_reopen_still_rejects_files_changed_during_decode(qtbot, window, patterned, monkeypatch, overwrite):
    import sumire.window as module
    window.overwrite.setChecked(overwrite)
    window.save()
    qtbot.waitUntil(lambda: not window.saving and window.document.output is not None)
    previous = window.document
    output = previous.output
    original = module.load_verified_export
    def changed(*args):
        result = original(*args)
        patterned.transpose(Image.Transpose.FLIP_LEFT_RIGHT).save(output)
        return result
    monkeypatch.setattr(module, "load_verified_export", changed)
    window.documents.clear()
    window._load_index(window.index)
    qtbot.waitUntil(lambda: not window.loading)
    assert window.document is previous
    assert "変更されました" in window.status.text()
