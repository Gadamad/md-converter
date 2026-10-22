"""An existing copy destination is a saved, optional alternative to a new name."""
from pathlib import Path
import sys
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from preferences import Preferences


@pytest.fixture
def api(tmp_path, monkeypatch):
    import converter_app as app
    monkeypatch.setattr(app, 'default_preferences_path', lambda: tmp_path / 'settings' / 'preferences.json')
    monkeypatch.setattr(app, 'VAULT_DIR', None)
    instance = app.Api()
    instance.save_preferences({'output_dir': str(tmp_path / 'exports')})
    return instance


def test_existing_selection_survives_restart_and_keeps_primary_destination(api, tmp_path):
    selected = tmp_path / 'Meglévő gyűjtemény'
    selected.mkdir()
    marker = selected / 'keep.txt'
    marker.write_bytes(b'User content')
    before = api._effective_output_dir()
    result = api.set_copy_existing_directory(str(selected))
    assert result['copy_existing_dir'] == str(selected.resolve())
    assert result['copy_subfolder'] is None
    assert api._effective_output_dir() == before
    assert api.get_application_state()['copy_dir'] == str(selected.resolve())
    import converter_app as app
    restored = app.Api()
    assert restored._effective_copy_dir() == selected.resolve()
    assert restored.save_preferences({'theme': 'dark'})['copy_existing_dir'] == str(selected.resolve())
    assert marker.read_bytes() == b'User content'
    assert list(selected.iterdir()) == [marker]


def test_switching_modes_and_disabling_clears_previous_destination(api, tmp_path):
    selected = tmp_path / 'existing'
    selected.mkdir()
    api.set_copy_subfolder('Named')
    api.set_copy_existing_directory(str(selected))
    assert api.get_preferences()['copy_subfolder'] is None
    result = api.set_copy_subfolder('New name')
    assert result['copy_existing_dir'] is None
    assert api._effective_copy_dir() == api._effective_output_dir() / 'New name'
    api.set_copy_existing_directory(str(selected))
    result = api.set_copy_subfolder(None)
    assert result['copy_subfolder'] is None and result['copy_existing_dir'] is None
    assert api._effective_copy_dir() is None


def test_native_picker_cancel_and_selection_only_stage_the_path(api, tmp_path):
    selected = tmp_path / 'Existing'
    selected.mkdir()
    before = api.get_preferences()
    disk = api._preferences_path.read_bytes()
    api.window = mock.Mock()
    api.window.create_file_dialog.return_value = None
    assert api.browse_copy_directory() is None
    api.window.create_file_dialog.return_value = [str(selected)]
    assert api.browse_copy_directory() == str(selected.resolve())
    args, options = api.window.create_file_dialog.call_args
    import converter_app as app
    assert args == (app.webview.FOLDER_DIALOG,)
    assert options['allow_multiple'] is False
    assert api.get_preferences() == before
    assert api._preferences_path.read_bytes() == disk


@pytest.mark.parametrize('invalid', ['', 'relative/folder', '../escape', '/tmp/../escape', False, {}, [], 'a\0b'])
def test_invalid_existing_path_does_not_disable_previous_copy(api, invalid):
    before = api.set_copy_subfolder('Original')
    disk = api._preferences_path.read_bytes()
    with pytest.raises(ValueError):
        api.set_copy_existing_directory(invalid)
    assert api.get_preferences() == before
    assert api._preferences_path.read_bytes() == disk


def test_existing_selection_rejects_missing_file_and_primary_locations(api, tmp_path):
    base = api._effective_output_dir()
    (base / 'quotes' / 'nested').mkdir(parents=True)
    file = tmp_path / 'occupied'
    file.write_text('keep')
    for selected in (tmp_path / 'missing', file, base, base.parent, base / 'quotes', base / 'quotes' / 'nested'):
        with pytest.raises(ValueError):
            api.set_copy_existing_directory(str(selected))
    assert api.get_preferences()['copy_subfolder'] is None


def test_existing_selection_rejects_same_macos_folder_with_different_capitalization(api):
    base = api._effective_output_dir()
    base.mkdir()
    alias = base.with_name(base.name.upper())
    if not alias.is_dir() or not alias.samefile(base):
        pytest.skip('Requires a case-insensitive filesystem')
    before = api.get_preferences()
    disk = api._preferences_path.read_bytes()
    with pytest.raises(ValueError):
        api.set_copy_existing_directory(str(alias))
    assert api.get_preferences() == before and api._preferences_path.read_bytes() == disk


def test_existing_selection_busy_and_save_failure_preserve_committed_choice(api, tmp_path):
    selected = tmp_path / 'existing'
    selected.mkdir()
    before = api.set_copy_subfolder('Original')
    disk = api._preferences_path.read_bytes()
    api._job_running = True
    with pytest.raises(RuntimeError):
        api.set_copy_existing_directory(str(selected))
    api._job_running = False
    api._job_lock.acquire()
    try:
        with pytest.raises(RuntimeError):
            api.browse_copy_directory()
    finally:
        api._job_lock.release()
    with mock.patch.object(api, '_save_preferences', side_effect=OSError('read-only')):
        with pytest.raises(OSError):
            api.set_copy_existing_directory(str(selected))
    assert api.get_preferences() == before
    assert api._preferences_path.read_bytes() == disk
    assert api._job_lock.acquire(blocking=False)
    api._job_lock.release()


def test_later_missing_existing_root_is_visible_but_queue_snapshot_remains_stable(api, tmp_path):
    selected = tmp_path / 'removable'
    selected.mkdir()
    api.set_copy_existing_directory(str(selected))
    selected.rmdir()
    assert api._effective_copy_dir(validate_destination=False) == selected.resolve()
    state = api.get_application_state()
    assert state['copy_dir'] is None and state['copy_error']
    assert api.get_preferences()['copy_existing_dir'] == str(selected.resolve())
    assert not selected.exists()
    assert api.set_copy_subfolder(None)['copy_existing_dir'] is None


def test_unavailable_optional_folder_does_not_block_unrelated_preferences(api, tmp_path):
    selected = tmp_path / 'removable'
    selected.mkdir()
    api.set_copy_existing_directory(str(selected))
    selected.rmdir()
    assert api.save_preferences({'theme': 'dark'})['theme'] == 'dark'
    assert api.set_include_subfolders(False)['include_subfolders'] is False
    assert api.set_show_source_details(True)['show_source_details'] is True
    assert api.get_preferences()['copy_existing_dir'] == str(selected)
    assert api.get_application_state()['copy_error']
    with pytest.raises(ValueError):
        api.set_copy_existing_directory(str(selected))


def test_existing_mode_is_frozen_for_queue_delivery(api, tmp_path):
    selected = tmp_path / 'chosen'
    selected.mkdir()
    api.set_copy_existing_directory(str(selected))
    queue_id = api.stage_text('Keep this note.')['active_id']
    captured = {}
    class Runner:
        def __init__(self, store, cache, options, **kwargs):
            captured.update(options)
            api.set_copy_subfolder('Later choice')
        def run(self, *args, **kwargs):
            pass
    with mock.patch('queue_api.QueueRunner', Runner):
        api._queue_worker_body(queue_id, False)
    assert captured['copy_dir'] == str(selected.resolve())
    assert captured['copy_mode'] == 'existing'
    assert api.get_preferences()['copy_subfolder'] == 'Later choice'


def test_existing_preferences_are_additive_and_invalid_disk_data_falls_back():
    assert Preferences.from_dict({'copy_subfolder': 'Old name'}).copy_existing_dir is None
    for invalid in ('relative', '../escape', False, [], {}):
        prefs = Preferences.from_dict({'copy_existing_dir': invalid, 'copy_subfolder': 'Old name'})
        assert prefs.copy_subfolder == 'Old name' and prefs.copy_existing_dir is None
    prefs = Preferences.from_dict({'copy_existing_dir': '/missing/book notes'})
    assert prefs.copy_existing_dir == Path('/missing/book notes')


def test_conflicting_destination_save_is_rejected_atomically(api, tmp_path):
    selected = tmp_path / 'chosen'
    selected.mkdir()
    before = api.get_preferences()
    disk = api._preferences_path.read_bytes()
    with pytest.raises(ValueError):
        api.save_preferences({'copy_subfolder': 'Named', 'copy_existing_dir': str(selected)})
    assert api.get_preferences() == before and api._preferences_path.read_bytes() == disk
