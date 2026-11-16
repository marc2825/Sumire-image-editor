"""1.2.0: tags, gathering label folders, cut / copy / paste of image files, Ctrl+click,
dragging near the edges, one-image collages and NovelAI with the generation information."""
import struct
from pathlib import Path

from PIL import Image, PngImagePlugin
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from sumire.file_clipboard import DROP_EFFECT, clipboard_files, copy_files, file_mime
from sumire.folders import label_folders, move_image
from sumire.labels import ReviewLabels, clean_tags, split_tags
from sumire.tag_dialog import TagDialog

from test_gui import window  # noqa: F401  (fixture)


def idle(qtbot, window):
    qtbot.waitUntil(lambda: not window.busy() and not window.saving and not window.finalizing, timeout=10000)


def row_point(window, path):
    return window.list.visualRect(window.proxy.mapFromSource(window.model.index(window.model.rows[path]))).center()


# --- tags --------------------------------------------------------------------------

def test_tags_are_cleaned_and_kept_with_the_image(tmp_path, patterned):
    assert split_tags("背景, 修正、 背景 ,  TODO，todo\n要確認") == ("TODO", "修正", "背景", "要確認")
    assert clean_tags(["x" * 60]) == ("x" * 40,) and len(clean_tags(str(n) for n in range(50))) == 30
    image = tmp_path / "a.png"
    patterned.save(image)
    ReviewLabels(tmp_path).set_tags({image: ["背景", "修正"]})
    assert ReviewLabels(tmp_path).tags_of(image) == ("修正", "背景")
    (tmp_path / "moved").mkdir()
    moved = move_image(image, tmp_path / "moved")  # tags move with the file, like labels and notes
    assert ReviewLabels(tmp_path / "moved").tags_of(moved) == ("修正", "背景")
    assert ReviewLabels(tmp_path).tags_of(image) == ()


def test_tag_dialog_adds_removes_and_keeps_partial_tags(qtbot, tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    dialog = TagDialog({a: ("背景", "共通"), b: ("共通",)}, ["ほか"])
    qtbot.addWidget(dialog)
    items = {item.text(): item for item in dialog.items()}
    assert items["共通"].checkState() == Qt.CheckState.Checked
    assert items["背景"].checkState() == Qt.CheckState.PartiallyChecked  # only some have it: kept as it is
    assert items["ほか"].checkState() == Qt.CheckState.Unchecked
    items["共通"].setCheckState(Qt.CheckState.Unchecked)
    dialog.entry.setText("新規、要修正")
    dialog.accept_typed()  # typed but not yet added still counts
    assert dialog.result_tags() == {a: ("新規", "背景", "要修正"), b: ("新規", "要修正")}


def test_tags_in_the_list_filter_search_and_undo(qtbot, window):
    first, second, third = window.model.paths
    window.write_tags({first: ("背景",), third: ("背景", "修正")}, {first: (), third: ()})
    assert window.model.tags[third] == ("背景", "修正")
    assert ReviewLabels(first.parent).tags_of(third) == ("修正", "背景")
    assert "#背景" in window.model.data(window.model.index(window.model.rows[first]), Qt.ItemDataRole.ToolTipRole)
    window.tag_combo.setCurrentIndex(window.tag_combo.findData("修正"))
    qtbot.waitUntil(lambda: window.visible_paths() == [third], timeout=5000)
    window.reset_filters()
    qtbot.waitUntil(lambda: len(window.visible_paths()) == 3, timeout=5000)
    window.search.setText("背景")
    qtbot.waitUntil(lambda: window.visible_paths() == [first, third], timeout=5000)
    window.search.setText("")
    qtbot.waitUntil(lambda: len(window.visible_paths()) == 3, timeout=5000)
    window.undo_organization()
    assert first not in window.model.tags and third not in window.model.tags
    assert ReviewLabels(first.parent).tags_of(first) == ()
    assert second not in window.model.tags


def test_tags_follow_a_rename(qtbot, window):
    source = window.document.path
    window.write_tags({source: ("背景",)})
    target = source.with_name("renamed.png")
    window.rename_paths({source: target})
    qtbot.waitUntil(lambda: window.batch_job is None and target in window.model.rows, timeout=10000)
    assert ReviewLabels(target.parent).tags_of(target) == ("背景",) and window.model.tags.get(target) == ("背景",)


# --- selection and dragging --------------------------------------------------------

def test_ctrl_click_takes_one_image_out_of_the_selection(qtbot, window):
    first, second, third = window.model.paths
    window.select_paths([first, second, third])
    shown = window.document.path
    QTest.mouseClick(window.list.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, row_point(window, second))
    qtbot.wait(300)
    assert window.selected_paths() == [first, third] and window.document.path == shown
    assert "Ctrl+クリック" in window.selection_label.toolTip()


def test_dragging_near_the_edges_scrolls_faster_further_in(qtbot, window, monkeypatch):
    view = window.list
    height = view.viewport().height()
    assert view.edge_step(height // 2) == 0
    assert view.edge_step(view.EDGE - 1) < 0 < view.edge_step(height - view.EDGE + 1)
    assert view.edge_step(height + 500) == view.MAX_STEP and view.edge_step(-500) == -view.MAX_STEP  # outside: full speed
    assert view.edge_step(height - 2) > view.edge_step(height - view.EDGE + 2)
    window.thumbnail_size.setValue(240)
    window.view_combo.setCurrentIndex(1)
    for name in range(40):
        Image.new("RGB", (8, 8)).save(window.document.path.parent / f"more{name:02d}.png")
    window.reload_workspace()
    qtbot.waitUntil(lambda: len(window.model.paths) == 43 and not window.loading, timeout=10000)
    bar = view.verticalScrollBar()
    bar.setValue(0)
    below = view.viewport().mapToGlobal(QPoint(10, view.viewport().height() + 20))  # just under the list
    monkeypatch.setattr("sumire.library.QCursor.pos", lambda: below)
    monkeypatch.setattr("sumire.library.QApplication.widgetAt", lambda point: None)
    view.edge_scroll()
    assert bar.value() > 0
    # The wheel scrolls the list while an image is dragged.
    view.dragging = True
    before = bar.value()
    wheel = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    assert view.eventFilter(window.canvas, wheel) and bar.value() > before
    view.dragging = False
    assert not view.eventFilter(window.canvas, wheel)


# --- cut, copy, paste --------------------------------------------------------------

def test_copy_never_overwrites_and_explorer_cut_is_understood(tmp_path, patterned):
    source = tmp_path / "a.png"
    patterned.save(source)
    (tmp_path / "into").mkdir()
    (tmp_path / "into" / "a.png").write_bytes(b"existing")
    copied, failed = copy_files([source], tmp_path / "into")
    assert not failed and copied[source] == tmp_path / "into" / "a_2.png"
    assert (tmp_path / "into" / "a.png").read_bytes() == b"existing"
    assert (tmp_path / "into" / "a_2.png").read_bytes() == source.read_bytes()
    assert clipboard_files(file_mime([source], cut=True)) == ([source], True)
    assert clipboard_files(file_mime([source], cut=False)) == ([source], False)
    explorer = QMimeData()  # what Explorer puts on the clipboard for Ctrl+X
    explorer.setUrls(file_mime([source], cut=True).urls())
    explorer.setData(DROP_EFFECT, struct.pack("<I", 2))
    assert clipboard_files(explorer) == ([source], True)
    folder_only = QMimeData()
    folder_only.setUrls(file_mime([tmp_path], cut=False).urls())
    assert clipboard_files(folder_only) == ([], False)


def test_copy_and_paste_files_into_the_tab_folder(qtbot, window, tmp_path, patterned):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    outside = elsewhere / "outside.png"
    patterned.save(outside)
    QApplication.clipboard().setMimeData(file_mime([outside], cut=False))
    window.paste_image()
    pasted = window.document.path.parent / "outside.png"
    qtbot.waitUntil(lambda: pasted in window.model.rows, timeout=10000)
    idle(qtbot, window)
    assert outside.exists() and pasted.read_bytes() == outside.read_bytes()
    # Ctrl+C in the list copies the files, not the picture.
    window.select_paths([pasted])
    window.list.setFocus()
    window.copy_image()
    assert clipboard_files(QApplication.clipboard().mimeData()) == ([pasted], False)


def test_cut_and_paste_moves_with_records_and_undo(qtbot, window, tmp_path, patterned):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    outside = elsewhere / "cut.png"
    patterned.save(outside)
    ReviewLabels(elsewhere).set(outside, "rejected")
    QApplication.clipboard().setMimeData(file_mime([outside], cut=True))
    window.paste_image()
    pasted = window.document.path.parent / "cut.png"
    qtbot.waitUntil(lambda: pasted in window.model.rows, timeout=10000)
    idle(qtbot, window)
    assert not outside.exists() and window.model.labels.get(pasted) == "rejected"
    assert clipboard_files(QApplication.clipboard().mimeData()) == ([], False)  # cut files paste once
    window.undo_organization()
    qtbot.waitUntil(outside.exists, timeout=10000)
    assert not pasted.exists()


# --- gathering label folders --------------------------------------------------------

def test_gather_the_label_folders_back_and_undo(qtbot, window, monkeypatch, patterned):
    root = window.document.path.parent
    accepted, rejected = root / "採用", root / "不採用"
    for folder, name, label in ((accepted, "00.png", "accepted"), (rejected, "00.png", "rejected")):
        folder.mkdir()
        patterned.save(folder / name)
        ReviewLabels(folder).set(folder / name, label)
    assert label_folders(root)[0] == root and set(label_folders(root)[1]) == {accepted, rejected}
    assert label_folders(accepted)[0] == root  # from inside one: its neighbours
    monkeypatch.setattr(type(window), "confirm_dialog", lambda self, dialog, accepted=None: True)
    window.merge_label_folders()
    qtbot.waitUntil(lambda: not accepted.exists() and not rejected.exists(), timeout=10000)
    idle(qtbot, window)
    gathered = {path.name: ReviewLabels(root).get(path) for path in root.glob("00*.png")}
    assert gathered == {"00.png": gathered["00.png"], "00_2.png": gathered["00_2.png"]}
    assert set(gathered.values()) == {"accepted", "rejected"}  # labels moved with the images
    assert {root / "00.png", root / "00_2.png"} <= set(window.model.rows)
    assert "まとめました" in window.status.text()
    window.undo_organization()
    qtbot.waitUntil(lambda: (accepted / "00.png").exists() and (rejected / "00.png").exists(), timeout=10000)
    assert ReviewLabels(accepted).get(accepted / "00.png") == "accepted"


# --- collage -------------------------------------------------------------------------

def test_collage_from_one_image_and_adding_more(qtbot, tmp_path, patterned):
    from sumire.output_dialogs import CollageDialog
    added = tmp_path / "added.png"
    patterned.save(added)
    loaded = []
    dialog = CollageDialog(["one.png"], [patterned.convert("RGBA")], loader=lambda path: loaded.append(path) or patterned.convert("RGBA"))
    qtbot.addWidget(dialog)
    assert dialog.ok.isEnabled() and dialog.layout_combo.count() == 1 and not dialog.remove_button.isEnabled()
    assert dialog.renderer()().size == (160, 120)
    assert dialog.add_images([added]) == [] and loaded == [added]
    assert len(dialog.sources) == 2 and dialog.image_list.count() == 2 and dialog.remove_button.isEnabled()
    assert dialog.renderer()().size[0] == 320  # side by side
    dialog.remove_image(0)
    assert dialog.names == ["added.png"] and not dialog.remove_button.isEnabled()


# --- NovelAI ---------------------------------------------------------------------------

def novelai_png(path, encode_stealth):
    info = PngImagePlugin.PngInfo()
    info.add_text("Software", "NovelAI")
    info.add_text("Comment", '{"prompt": "synthetic prompt", "uc": "x"}')
    encode_stealth(Image.new("RGBA", (200, 160), "#8877aa")).save(path, pnginfo=info)


def test_novelai_gets_the_generation_information_only_when_asked(tmp_path, encode_stealth):
    from sumire.metadata import inspect_metadata
    from sumire.novelai import prepare_image
    source = tmp_path / "nai.png"
    novelai_png(source, encode_stealth)
    pixels = Image.open(source).convert("RGBA")
    plain = prepare_image(pixels, source)
    try:
        assert not plain.metadata and inspect_metadata(plain.path) == []
    finally:
        plain.cleanup()
    kept = prepare_image(pixels, source, keep_metadata=True)
    try:
        found = inspect_metadata(kept.path)
        assert kept.metadata and "生成プロンプト" in found and "Stealth PNGInfo（隠し情報）" in found
    finally:
        kept.cleanup()
    # Shrunk below what the hidden data needs: the text is still attached.
    small = prepare_image(pixels, source, keep_metadata=True, max_size=(20, 16))
    try:
        found = inspect_metadata(small.path)
        assert small.metadata and "生成プロンプト" in found and "Stealth PNGInfo（隠し情報）" not in found
    finally:
        small.cleanup()


def test_novelai_option_is_saved_and_off_at_first(window):
    assert not window.novelai_metadata.isChecked()
    window.novelai_metadata.setChecked(True)
    assert window.workspace_settings()["novelai_metadata"] is True


# --- messages --------------------------------------------------------------------------

def test_a_result_shown_while_the_next_image_loads_is_shown_again_after(window):
    window.loading = True
    try:
        window.report("移動しました · 1枚")
        assert window.after_load_message == "移動しました · 1枚"
    finally:
        window.loading = False
        window.after_load_message = None


def test_tags_survive_sorting_and_reordering(qtbot, window):
    """The list is rebuilt when it is sorted or reordered; the tags must stay with their images."""
    first, second, third = window.model.paths
    window.write_tags({second: ("残す",)})
    window.sort_combo.setCurrentIndex(window.sort_combo.findData("name_desc"))
    qtbot.waitUntil(lambda: window.model.paths[0] != first, timeout=5000)
    assert window.model.tags == {second: ("残す",)}
    window.reorder_selection([str(second)], str(window.model.paths[0]))
    assert window.model.tags == {second: ("残す",)}


def test_reset_edits_says_whether_it_will_be_saved(qtbot, window, monkeypatch):
    """Issue #1 review: the text about saving after the reset was built but never shown."""
    from test_gui import draw
    draw(window)
    seen = []
    monkeypatch.setattr(type(window), "confirm_dialog", lambda self, dialog, accepted=None: seen.append(dialog.informativeText()) or False)
    window.auto.setChecked(True)
    idle(qtbot, window)
    window.reset_edits()
    window.auto.setChecked(False)
    idle(qtbot, window)
    window.reset_edits()
    assert len(seen) == 2 and "自動保存" in seen[0] and "未保存" in seen[1]
