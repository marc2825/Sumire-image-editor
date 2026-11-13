import json
import os

from PIL import Image, PngImagePlugin
from PySide6.QtCore import QStandardPaths

from sumire import legacy
from sumire.export import file_digest, save_image
from sumire.metadata import MetadataStore
from sumire.organize import pending_renames, recover_rename
from sumire.preferences import Preferences, settings_path
from sumire.projects import read_project, write_project
from sumire.storage import record_path
from test_explorer import Registry
from sumire.explorer import BASE, LEGACY_OWNER, LEGACY_VERBS, apply_context_menu, context_entries


def test_settings_environment_and_legacy_profile_are_preserved(tmp_path, monkeypatch):
    monkeypatch.delenv('SUMIRE_SETTINGS_FILE')
    old = tmp_path / 'legacy.json'
    monkeypatch.setenv(legacy.SETTINGS_ENV, str(old))
    assert settings_path() == old
    new = tmp_path / 'new.json'
    monkeypatch.setenv('SUMIRE_SETTINGS_FILE', str(new))
    assert settings_path() == new
    monkeypatch.delenv('SUMIRE_SETTINGS_FILE')
    monkeypatch.delenv(legacy.SETTINGS_ENV)
    config = tmp_path / 'config'
    new_folder = config / 'Sumīre' / 'Sumīre'
    monkeypatch.setattr(QStandardPaths, 'writableLocation', lambda *_: str(new_folder))
    old = config / legacy.APP_NAME / legacy.APP_NAME / legacy.SETTINGS_FILENAME
    Preferences(old).save({'settings': {'metadata_backup': False}, 'inputs': ['日本語の画像.png']})
    assert settings_path() == old
    assert Preferences().data['settings']['metadata_backup'] is False
    current = new_folder / 'sumire-workspace.json'
    Preferences(current).save({'settings': {'metadata_backup': True}})
    assert settings_path() == current
    assert Preferences().data['settings']['metadata_backup'] is True


def test_existing_db_preserves_metadata_backups_under_legacy_filename(tmp_path):
    source = tmp_path / 'image.png'
    info = PngImagePlugin.PngInfo(); info.add_text('parameters', 'synthetic existing prompt')
    Image.new('RGB', (20, 30), 'red').save(source, pnginfo=info)
    from sumire.imaging import load_image
    result = save_image(load_image(source), source, source=source, overwrite_source=True,
                        source_digest=file_digest(source), backup_metadata=True)
    payload = MetadataStore(tmp_path).get(source, result.digest)
    new = record_path(tmp_path)
    previous = tmp_path / legacy.DATABASE_FILENAME
    new.rename(previous)
    assert record_path(tmp_path) == previous
    assert MetadataStore(tmp_path).get(source, result.digest) == payload
    # A new, explicit database takes priority when both names exist.
    new.write_bytes(previous.read_bytes())
    assert record_path(tmp_path) == new


def test_existing_separate_output_folder_is_reused(tmp_path):
    assert legacy.default_output_folder(tmp_path) == tmp_path / 'Sumīre'
    old = tmp_path / legacy.APP_NAME
    old.mkdir()
    assert legacy.default_output_folder(tmp_path) == old
    current = tmp_path / 'Sumīre'
    current.mkdir()
    assert legacy.default_output_folder(tmp_path) == current


def test_legacy_project_and_interrupted_rename_remain_recoverable(tmp_path):
    original = Image.new('RGBA', (20, 30), 'red')
    mask = Image.new('L', original.size)
    path = tmp_path / ('old' + legacy.PROJECT_EXTENSION)
    state = {'edited': False, 'original_edited': False, 'original_known': True}
    write_project(path, original, original, mask, state)
    assert read_project(path).image.tobytes() == original.tobytes()
    source = tmp_path / 'image.png'; original.save(source)
    renamed = source.with_name('renamed.png')
    token = 'a' * 32
    temporary = tmp_path / f'.{legacy.SLUG}-rename-{token}-0.tmp'
    os.link(source, temporary)
    source.rename(renamed)
    journal = tmp_path / f'.{legacy.SLUG}-rename-{token}.json'
    journal.write_text(json.dumps({'id': token, 'phase': 'renaming', 'entries': [
        {'old': str(source), 'new': str(renamed), 'temp': str(temporary), 'digest': file_digest(renamed).hex()}]}))
    assert pending_renames(tmp_path) == [journal]
    recover_rename(journal)
    assert source.exists() and not renamed.exists() and not temporary.exists()


def legacy_registry():
    registry = Registry()
    for verb in LEGACY_VERBS:
        path = BASE + verb
        registry.values[path] = {'': legacy.APP_NAME + 'で開く', 'SumiOwner': LEGACY_OWNER, 'MultiSelectModel': 'Single'}
        registry.values[path + '\\command'] = {'': 'old launcher'}
    return registry


def test_right_click_name_migration_removes_only_owned_old_items():
    registry = legacy_registry()
    foreign = BASE + next(iter(LEGACY_VERBS))
    registry.values[foreign]['SumiOwner'] = 'different application'
    entries = context_entries(['sumire.exe', '--open'])
    apply_context_menu(entries, registry=registry)
    assert all(registry.values[path][''] == 'Sumīreで開く' for path in entries)
    assert registry.values[foreign]['SumiOwner'] == 'different application'
    assert len(registry.values) == 16  # Seven new verbs plus one foreign verb.


def test_right_click_migration_write_failure_restores_old_registration():
    registry = legacy_registry()
    before = {key: dict(value) for key, value in registry.values.items()}
    registry.fail_at = 7
    import pytest
    with pytest.raises(OSError):
        apply_context_menu(context_entries(['sumire.exe']), registry=registry)
    assert registry.values == before
