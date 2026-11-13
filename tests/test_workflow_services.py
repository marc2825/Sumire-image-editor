import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest
from PIL import Image
from PySide6.QtCore import QPointF

from sumire.analysis import difference_hash, find_duplicates
from sumire.compare import ComparisonDialog
from sumire.export import Cancelled, file_digest, save_image, verify_export
from sumire.imaging import ImageProblem
from sumire.labels import ReviewLabels
from sumire.locking import image_locks
from sumire.novelai import ImageAdjustmentDialog, prepare_image, transform_image
from sumire.organize import pending_renames, recover_rename, rename_images
from sumire.preferences import Preferences


def test_notes_and_bulk_labels_survive_reopen_and_cyclic_rename(tmp_path):
    paths = [tmp_path / f"{i}.png" for i in range(3)]
    for number, path in enumerate(paths):
        Image.new("RGB", (20, 20), (number * 60, 0, 0)).save(path)
    index = ReviewLabels(tmp_path)
    index.set_many({paths[0]: "accepted", paths[1]: "pending"})
    index.set_note(paths[0], "手を修正\n背景を再生成")
    index.set_note(paths[2], "ラベルなしのメモ")
    mapping = dict(zip(paths, paths[1:] + paths[:1]))
    rename_images(mapping)
    index.remap_paths(mapping)
    reopened = ReviewLabels(tmp_path)
    assert [reopened.get(path) for path in paths] == [None, "accepted", "pending"]
    assert reopened.note(paths[1]) == "手を修正\n背景を再生成"
    assert reopened.note(paths[0]) == "ラベルなしのメモ"
    assert reopened.note(paths[2]) == ""


def test_oversized_note_rejected_without_losing_previous(tmp_path):
    index = ReviewLabels(tmp_path)
    source = tmp_path / "image.png"
    index.set_note(source, "keep")
    with pytest.raises(ValueError):
        index.set_note(source, "x" * 4001)
    assert ReviewLabels(tmp_path).note(source) == "keep"


def test_exact_and_similar_duplicates_report_groups_and_bad_images(tmp_path, patterned):
    first, exact, changed, different, broken = [tmp_path / f"{name}.png" for name in ("first", "exact", "changed", "different", "broken")]
    patterned.save(first)
    exact.write_bytes(first.read_bytes())
    modified = patterned.copy()
    modified.putpixel((0, 0), (255, 255, 255, 255))
    modified.save(changed)
    Image.new("RGBA", patterned.size, "black").save(different)
    broken.write_bytes(b"bad file")
    paths = [first, exact, changed, different, broken]
    progress = []
    groups, errors = find_duplicates(paths, progress=lambda *args: progress.append(args))
    assert groups == [[first, exact]] and not errors  # Exact matching compares file bytes.
    groups, errors = find_duplicates(paths, similar=True)
    assert any({first, exact, changed}.issubset(group) for group in groups)
    assert broken in errors
    assert progress[-1] == (5, 5)
    assert difference_hash(patterned) == difference_hash(modified)


def test_duplicate_scan_honors_cancel(tmp_path):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        find_duplicates([tmp_path / "missing.png"], cancel=cancel)


def test_crop_resize_preserves_original_and_metadata_validation(tmp_path, patterned):
    original = patterned.tobytes()
    prepared = prepare_image(patterned, tmp_path / "source.png", crop=(20, 10, 100, 80), max_size=(50, 50))
    try:
        verify_export(prepared.path, (50, 40), "PNG")
        with Image.open(prepared.path) as output:
            expected = patterned.crop((20, 10, 120, 90)).resize((50, 40), Image.Resampling.LANCZOS)
            assert output.tobytes() == expected.tobytes()
        assert patterned.tobytes() == original
        with pytest.raises(ImageProblem):
            transform_image(patterned, (100, 0, 100, 10))
    finally:
        prepared.cleanup()


def test_handoff_removes_hidden_carrier_before_crop_and_resize(tmp_path, patterned, encode_stealth):
    pixels = encode_stealth(patterned)
    prepared = prepare_image(pixels, tmp_path / "source.png", crop=(10, 10, 100, 80), max_size=(50, 50))
    try:
        with Image.open(prepared.path) as output:
            assert output.getchannel("A").getextrema() == (255, 255)
            assert output.size == (50, 40) and not output.info
    finally:
        prepared.cleanup()


def test_adjustment_controls_keep_crop_inside_image(qtbot, patterned):
    dialog = ImageAdjustmentDialog(patterned)
    qtbot.addWidget(dialog)
    dialog.set_crop((100, 90, 100, 100))
    dialog.fields[4].setValue(30)
    dialog.fields[5].setValue(40)
    assert dialog.options() == ((100, 90, 60, 30), (30, 40))


def test_comparison_synchronizes_zoom_and_relative_center(qtbot, tmp_path, patterned):
    paths = [tmp_path / "a.png", tmp_path / "b.png"]
    dialog = ComparisonDialog(paths, [patterned, patterned.resize((320, 240))])
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    first, second = dialog.views
    dialog.linked.setChecked(True)
    first.zoom(2)
    assert second.scale == first.scale
    first.offset += QPointF(-24, 15)
    first.viewChanged.emit()
    centers = [view.to_image(QPointF(view.width() / 2, view.height() / 2)) for view in dialog.views]
    assert centers[0].x() / 160 == pytest.approx(centers[1].x() / 320)
    assert centers[0].y() / 120 == pytest.approx(centers[1].y() / 240)
    assert first.locked and second.locked


def test_settings_atomic_persistence_and_corruption_recovery(tmp_path):
    path = tmp_path / "settings" / "workspace.json"
    preferences = Preferences(path)
    data = {"settings": {"brush": 91}, "inputs": ["日本語"], "workspaces": {"key": {"current": "image.png"}}}
    preferences.save(data)
    assert Preferences(path).data == data
    assert not list(path.parent.glob(".sumire-settings-*"))
    path.write_text("{broken", encoding="utf-8")
    assert Preferences(path).data == {}


CRASH_RENAME = """
import os
from pathlib import Path
import sys
import sumire.organize as module
folder = Path(sys.argv[1])
phase = sys.argv[2]
paths = [folder / f'{i}.png' for i in range(3)]
link = module.os.link
unlink = Path.unlink
write = module._journal
count = 0
def crash_link(*args, **kwargs):
    global count
    result = link(*args, **kwargs)
    count += 1
    if (phase == 'staging' and count == 1) or (phase == 'target' and count == 4):
        os._exit(33)
    return result
def crash_unlink(self, *args, **kwargs):
    result = unlink(self, *args, **kwargs)
    if phase == 'removal' and self == paths[0]:
        os._exit(33)
    return result
def crash_journal(path, data):
    write(path, data)
    if phase == 'committed' and data['phase'] == 'committed':
        os._exit(33)
module.os.link = crash_link
Path.unlink = crash_unlink
module._journal = crash_journal
module.rename_images(dict(zip(paths, paths[1:] + paths[:1])))
"""


@pytest.mark.parametrize("phase", ["staging", "removal", "target", "committed"])
def test_killed_rename_recovers_without_losing_images(tmp_path, phase):
    paths = [tmp_path / f"{i}.png" for i in range(3)]
    originals = {path: bytes([i]) * 100 for i, path in enumerate(paths)}
    for path, data in originals.items():
        path.write_bytes(data)
    result = subprocess.run([sys.executable, "-c", CRASH_RENAME, str(tmp_path), phase], capture_output=True, timeout=15)
    assert result.returncode == 33, result.stderr.decode()
    journals = pending_renames(tmp_path)
    assert len(journals) == 1
    recover_rename(journals[0])
    expected = originals if phase != "committed" else {new: originals[old] for old, new in zip(paths, paths[1:] + paths[:1])}
    assert {path: path.read_bytes() for path in paths} == expected
    assert not list(tmp_path.glob(".sumire-rename-*"))


def test_recovery_rejects_unrelated_replacement(tmp_path):
    for i in range(3):
        (tmp_path / f"{i}.png").write_bytes(bytes([i]))
    subprocess.run([sys.executable, "-c", CRASH_RENAME, str(tmp_path), "target"], capture_output=True, timeout=15)
    unrelated = tmp_path / "0.png"
    unrelated.write_bytes(b"new unrelated image")
    journal = pending_renames(tmp_path)[0]
    with pytest.raises(ImageProblem, match="別のファイル"):
        recover_rename(journal)
    assert unrelated.read_bytes() == b"new unrelated image" and journal.exists()


def test_foreign_recovery_journal_is_rejected(tmp_path):
    journal = tmp_path / ".sumire-rename-invalid.json"
    journal.write_text(json.dumps({"entries": []}))
    with pytest.raises(ImageProblem):
        recover_rename(journal)
    assert journal.exists()


def test_cross_process_lock_blocks_saves_and_releases_after_crash(tmp_path, patterned):
    source = tmp_path / "source.png"
    patterned.save(source)
    code = """
from pathlib import Path
import sys
from PIL import Image
from sumire.export import save_image
from sumire.imaging import ImageProblem
try:
    save_image(Image.new('RGBA', (20,20)), Path(sys.argv[2]), source=Path(sys.argv[1]))
except ImageProblem:
    sys.exit(44)
"""
    target = tmp_path / "output.png"
    with image_locks([source]):
        result = subprocess.run([sys.executable, "-c", code, str(source), str(target)], capture_output=True, timeout=15)
        assert result.returncode == 44, result.stderr.decode()
        assert not target.exists()
    crash = "from pathlib import Path; import os,sys; from sumire.locking import image_locks; lock=image_locks([Path(sys.argv[1])]); lock.__enter__(); os._exit(0)"
    subprocess.run([sys.executable, "-c", crash, str(source)], check=True, timeout=15)
    save_image(patterned, target, source=source)
    assert target.is_file()


def test_rename_undo_digest_check_rejects_external_change(tmp_path):
    old, new = tmp_path / "old.png", tmp_path / "new.png"
    old.write_bytes(b"old")
    rename_images({old: new})
    digest = file_digest(new)
    new.write_bytes(b"changed")
    with pytest.raises(ImageProblem):
        rename_images({new: old}, expected_digests={new: digest})
    assert new.read_bytes() == b"changed" and not old.exists()
