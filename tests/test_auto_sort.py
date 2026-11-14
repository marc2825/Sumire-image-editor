"""「ラベルのフォルダーへ自動で振り分ける」: a label moves the image into the label's folder at once."""
from sumire.folders import label_folder_target
from sumire.labels import ReviewLabels
from sumire.settings_dialog import SettingsDialog

from test_gui import window  # noqa: F401  (fixture)


def idle(qtbot, window):
    qtbot.waitUntil(lambda: not window.busy() and not window.saving and not window.finalizing, timeout=10000)


def test_target_follows_the_existing_folders_and_their_language(tmp_path):
    (tmp_path / "accept").mkdir()
    image = tmp_path / "x.png"
    assert label_folder_target(image, "accepted") == tmp_path / "accept"
    assert label_folder_target(image, "rejected") == tmp_path / "Reject"  # named like the folders already there
    inside = tmp_path / "accept" / "y.png"
    assert label_folder_target(inside, "accepted") is None  # already there
    assert label_folder_target(inside, "pending") == tmp_path / "Hold"  # beside it
    (tmp_path / "plain").mkdir()
    assert label_folder_target(tmp_path / "plain" / "z.png", "accepted") is None  # no label folders: no sorting


def test_label_moves_the_image_into_a_label_folder_inside_its_folder(qtbot, window, tmp_path):
    (tmp_path / "採用").mkdir()
    window.auto_sort_action.setChecked(True)
    current = window.document.path
    window.set_review_label("rejected")
    target = tmp_path / "不採用" / current.name
    qtbot.waitUntil(target.is_file, timeout=10000)
    idle(qtbot, window)
    assert not current.exists() and current not in window.model.paths
    assert window.document is not None and window.document.path != current  # on to the next image
    assert ReviewLabels(target.parent).get(target) == "rejected"  # the label moved with it
    window.undo_organization()
    qtbot.waitUntil(current.is_file, timeout=10000)
    idle(qtbot, window)
    assert not target.exists()


def test_changing_the_label_inside_a_label_folder_moves_it_beside(qtbot, window, tmp_path, patterned):
    hold = (tmp_path / "保留").resolve()
    hold.mkdir()
    (tmp_path / "採用").mkdir()
    for name in ("a.png", "b.png"):
        patterned.save(hold / name)
    window.auto_sort_action.setChecked(True)
    window.open_inputs([str(hold)])
    qtbot.waitUntil(lambda: window.document is not None and window.document.path.parent == hold and window.canvas.ready,
                    timeout=10000)
    current = window.document.path
    window.set_review_label("pending")  # already in 保留
    idle(qtbot, window)
    assert current.exists()
    window.set_review_label("accepted")
    qtbot.waitUntil((tmp_path / "採用" / current.name).is_file, timeout=10000)
    idle(qtbot, window)
    assert not current.exists()


def test_nothing_moves_without_label_folders_or_with_the_mode_off(qtbot, window, tmp_path):
    current = window.document.path
    window.auto_sort_action.setChecked(True)
    window.set_review_label("accepted")
    idle(qtbot, window)
    assert current.exists() and not (tmp_path / "採用").exists()
    window.set_review_label(None)  # removing a label never moves
    (tmp_path / "Reject").mkdir()
    window.auto_sort_action.setChecked(False)
    window.set_review_label("rejected")
    idle(qtbot, window)
    assert current.exists() and not any((tmp_path / "Reject").iterdir())


def test_the_mode_is_in_the_settings_and_the_label_menu(window):
    assert window.auto_sort_action in window.label_menu.actions()
    dialog = SettingsDialog(window)
    try:
        # Short in the dialog; the whole rule on hover.
        assert "保留" in dialog.auto_sort.toolTip() and dialog.auto_sort_note.toolTip() == dialog.auto_sort.toolTip()
        assert len(dialog.auto_sort_note.text()) < len(dialog.auto_sort.toolTip()) / 3
        dialog.auto_sort.setChecked(True)
        assert window.auto_sort_action.isChecked() and window.workspace_settings()["auto_sort"] is True
    finally:
        dialog.done(0)
    window.restore_settings(window.default_settings)
    assert not window.auto_sort_action.isChecked()
