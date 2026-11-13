import pytest
from PIL import Image
from PySide6.QtWidgets import QFileDialog

from sumire.export import file_digest, verify_export
from sumire.metadata import MetadataStore, unpack_backup
from sumire.preferences import Preferences
from test_gui import draw, wait_saved, window
from test_metadata import source_with_metadata


def open_metadata(qtbot, window, tmp_path):
    folder = tmp_path / "復元テスト"
    folder.mkdir()
    source = source_with_metadata(folder / "画像.png", "PNG")
    window.open_inputs([str(source)])
    qtbot.waitUntil(lambda: window.document is not None and window.document.path == source and window.canvas.ready, timeout=10000)
    return source


@pytest.mark.parametrize("overwrite", [True, False])
def test_autosave_backup_and_restore_current_edits(qtbot, window, tmp_path, monkeypatch, overwrite):
    source = open_metadata(qtbot, window, tmp_path)
    original = source.read_bytes()
    window.overwrite.setChecked(overwrite)
    assert window.metadata_backup.isChecked()
    draw(window, (10, 10), (40, 30))
    wait_saved(qtbot, window)
    output = window.document.output
    clean_bytes = output.read_bytes()
    assert window.metadata_state.text() == "メタデータ：無し"
    assert MetadataStore(output.parent).get(output, file_digest(output))
    window.auto.setChecked(False)
    window.set_mode("fill")
    qtbot.waitUntil(lambda: window.canvas.ready)
    draw(window, (10, 40), (60, 40))
    qtbot.waitUntil(lambda: not window.finalizing)
    pixels = window.document.image.tobytes()
    restored = source.with_name("メタデータ復元.png")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(restored), ""))
    window.metadata_restore.trigger()
    qtbot.waitUntil(lambda: not window.finalizing and restored.exists(), timeout=10000)
    assert "メタデータ：有り" in window.status.text()
    with Image.open(restored) as image:
        assert image.info["parameters"] == "日本語のプロンプト " * 100
        assert image.convert("RGBA").tobytes() == pixels
    assert output.read_bytes() == clean_bytes
    assert source.read_bytes() == (clean_bytes if overwrite else original)
    assert window.document.path == source and window.document.dirty
    # The separate copy must keep its metadata after the UI returns to idle.
    qtbot.wait(300)
    with Image.open(restored) as image:
        assert "parameters" in image.info


def test_backup_disabled_persists_and_restore_explains_missing_data(qtbot, window, tmp_path, monkeypatch):
    source = open_metadata(qtbot, window, tmp_path)
    window.metadata_backup.setChecked(False)
    window.remember_workspace()
    assert Preferences().data["settings"]["metadata_backup"] is False
    window.metadata_backup.setChecked(True)
    window.restore_settings()
    assert not window.metadata_backup.isChecked()
    window.save(force=True)
    qtbot.waitUntil(lambda: not window.saving and window.metadata_state.text() == "メタデータ：無し", timeout=10000)
    assert MetadataStore(source.parent).get(source, file_digest(source)) is None
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: pytest.fail("No dialog without a backup"))
    window.metadata_restore.trigger()
    assert "復元用メタデータがありません" in window.status.text()


def test_batch_backup_survives_reopen(qtbot, window, tmp_path, monkeypatch):
    source = open_metadata(qtbot, window, tmp_path)
    window._start_batch([source])
    qtbot.waitUntil(lambda: window.batch_job is None, timeout=10000)
    payload = MetadataStore(source.parent).get(source, file_digest(source))
    assert unpack_backup(payload)[0] == "PNG"
    window.open_inputs([str(source)])
    qtbot.waitUntil(lambda: not window.loading and window.canvas.ready, timeout=10000)
    before = source.read_bytes()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(source), ""))
    window.metadata_restore.trigger()
    assert "新しいファイル名" in window.status.text()
    assert source.read_bytes() == before
    restored = source.with_name("復元.png")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(restored), ""))
    window.metadata_restore.trigger()
    qtbot.waitUntil(lambda: not window.finalizing and restored.exists(), timeout=10000)
    with Image.open(restored) as image:
        assert image.getexif()[315] == "synthetic artist"
    verify_export(source, window.document.image.size, "PNG")
