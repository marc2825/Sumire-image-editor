import threading
from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QDesktopServices, QDrag
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from sumire.export import Cancelled, verify_export
from sumire.novelai import NOVELAI_URL, NovelAIImportDialog, prepare_image


def test_handoff_png_removes_metadata_and_preserves_source(tmp_path, patterned, encode_stealth, decode_stealth):
    source = tmp_path / "private-name.png"
    pixels = encode_stealth(patterned)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("prompt", "private synthetic prompt")
    pixels.save(source, pnginfo=metadata)
    before = source.read_bytes()
    with Image.open(source) as image:
        prepared = prepare_image(image, source)
    try:
        verify_export(prepared.path, patterned.size, "PNG")
        with Image.open(prepared.path) as image:
            assert not image.info and decode_stealth(image) is None
            assert image.convert("RGB").tobytes() == patterned.convert("RGB").tobytes()
        assert source.read_bytes() == before
        assert prepared.path.name == "sumire-i2i.png"
    finally:
        prepared.cleanup()
    assert not prepared.path.parent.exists()


@pytest.mark.parametrize("cancelled", [True, False])
def test_handoff_cleans_up_on_cancel_or_export_failure(tmp_path, patterned, monkeypatch, cancelled):
    import sumire.novelai as module
    from tempfile import TemporaryDirectory
    monkeypatch.setattr(module, "TemporaryDirectory", lambda **kwargs: TemporaryDirectory(dir=tmp_path, **kwargs))
    cancel = threading.Event()
    if cancelled:
        cancel.set()
    else:
        def fail(*args, **kwargs):
            raise OSError("synthetic failure")
        monkeypatch.setattr(module, "save_image", fail)
        monkeypatch.setattr("sumire.batch_features.save_image", fail)  # whole-list work saves from here
    with pytest.raises(Cancelled if cancelled else OSError):
        prepare_image(patterned, tmp_path / "original.png", cancel)
    assert list(tmp_path.iterdir()) == []


def test_dialog_copy_drag_browser_failure_and_cleanup(qtbot, tmp_path, patterned, monkeypatch):
    opened, dragged = [], []
    def open_url(url):
        opened.append(url.toString())
        return False
    monkeypatch.setattr(QDesktopServices, "openUrl", open_url)
    def drag_exec(drag, *args):
        dragged.extend(url.toLocalFile() for url in drag.mimeData().urls())
        return Qt.DropAction.CopyAction
    monkeypatch.setattr(QDrag, "exec", drag_exec)
    prepared = prepare_image(patterned, tmp_path / "original.png")
    dialog = NovelAIImportDialog(prepared)
    # WA_DeleteOnClose owns this dialog; the finally block closes it exactly once.
    try:
        dialog.show()
        dialog.open_browser()
        assert opened == [NOVELAI_URL]
        assert "ブラウザーを開けません" in dialog.message.text()
        QTest.mouseClick(dialog.copy_button, Qt.MouseButton.LeftButton)
        clipboard = QApplication.clipboard().mimeData()
        assert clipboard.hasImage() and clipboard.hasFormat("image/png")
        assert bytes(clipboard.data("image/png")) == prepared.path.read_bytes()
        assert not clipboard.hasUrls()
        QTest.mousePress(dialog.preview, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))
        QTest.mouseMove(dialog.preview, QPoint(80, 50))
        QTest.mouseRelease(dialog.preview, Qt.MouseButton.LeftButton, pos=QPoint(80, 50))
        assert [Path(path) for path in dragged] == [prepared.path]
        assert Path(dragged[0]).is_file()
    finally:
        dialog.close()
    assert not prepared.path.parent.exists()
    # The clipboard owns bytes, so pasting still works after closing the dialog.
    assert QApplication.clipboard().mimeData().hasImage()
    QApplication.clipboard().clear()
