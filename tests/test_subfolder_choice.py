import json
from pathlib import Path
import sys
import threading
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


@pytest.fixture
def api(tmp_path, monkeypatch):
    import converter_app as app
    monkeypatch.setattr(app, 'default_preferences_path', lambda: tmp_path / 'settings' / 'preferences.json')
    monkeypatch.setattr(app, 'VAULT_DIR', None)
    return app.Api()


def make_folder(root):
    nested = root / 'one' / 'two' / 'three'
    nested.mkdir(parents=True)
    direct = root / 'direct.txt'
    deep = nested / 'deep.txt'
    direct.write_text('Direct child')
    deep.write_text('Nested child')
    return direct.resolve(), deep.resolve()


@pytest.mark.parametrize('intake', ['stage_folder', 'stage_files', 'stage_drop'])
def test_folder_intake_uses_saved_choice_and_reenabling_appends_nested_items(api, tmp_path, intake):
    direct, deep = make_folder(tmp_path / 'source')
    original_queue = api.get_queue_state()['active_id']
    result = api.set_include_subfolders(False)
    assert result['include_subfolders'] is False
    arguments = str(direct.parent) if intake == 'stage_folder' else [str(direct.parent)]
    if intake == 'stage_drop':
        arguments = {'files': arguments}
    state = getattr(api, intake)(arguments)
    assert [item['source'] for item in state['items']] == [str(direct)]
    original_ids = [item['id'] for item in state['items']]

    import converter_app as app
    restored = app.Api()
    assert restored.get_preferences()['include_subfolders'] is False
    assert restored.get_queue_state()['active_id'] == original_queue
    assert [item['id'] for item in restored.get_queue_state()['items']] == original_ids
    restored.set_include_subfolders(True)
    assert [item['id'] for item in restored.get_queue_state()['items']] == original_ids
    state = getattr(restored, intake)(arguments)
    assert {item['source'] for item in state['items']} == {str(direct), str(deep)}
    restored.set_include_subfolders(False)
    assert restored.get_queue_state()['total'] == 2


def test_explicit_deep_file_selection_is_allowed_with_subfolders_disabled(api, tmp_path):
    _, deep = make_folder(tmp_path / 'source')
    api.set_include_subfolders(False)
    assert api.stage_files([str(deep)])['items'][0]['source'] == str(deep)


def test_preferences_modal_save_preserves_omitted_subfolder_choice(api):
    api.set_include_subfolders(False)
    prefs = api.save_preferences({'theme': 'dark', 'raw_ocr_mode': 'never', 'auto_open_output': True})
    assert prefs['include_subfolders'] is False
    assert prefs['theme'] == 'dark'
    import converter_app as app
    assert app.Api().get_preferences() == prefs


@pytest.mark.parametrize('invalid', [None, 'false', 0, 1, [], {}])
def test_subfolder_choice_rejects_non_booleans_without_changing_preferences(api, invalid):
    before = api.get_preferences()
    with pytest.raises(ValueError, match='(?i)boolean'):
        api.set_include_subfolders(invalid)
    assert api.get_preferences() == before
    assert not api._preferences_path.exists()


def test_subfolder_choice_rejects_active_conversion(api):
    before = api.get_preferences()
    api._job_running = True
    try:
        with pytest.raises(RuntimeError, match='(?i)conversion'):
            api.set_include_subfolders(False)
    finally:
        api._job_running = False
    assert api.get_preferences() == before


@pytest.mark.parametrize('method,payload', [
    ('set_include_subfolders', False),
    ('save_preferences', {'include_subfolders': False, 'theme': 'dark'}),
])
def test_preference_save_failure_preserves_committed_memory_and_disk(api, monkeypatch, method, payload):
    before = api.save_preferences({'theme': 'light'})
    disk_before = api._preferences_path.read_bytes()
    def fail_save(self, path):
        raise OSError('Disk is full')
    monkeypatch.setattr(type(api._preferences), 'save', fail_save)
    with pytest.raises(OSError, match='Disk is full'):
        getattr(api, method)(payload)
    assert api.get_preferences() == before
    assert api._preferences_path.read_bytes() == disk_before
    assert api._job_lock.acquire(blocking=False)
    api._job_lock.release()


def test_multi_folder_drop_captures_choice_once_even_if_it_changes_mid_scan(api, tmp_path):
    sources = [tmp_path / 'first', tmp_path / 'second']
    expected = {str(path) for root in sources for path in make_folder(root)}
    original_walk = __import__('os').walk
    changed = False
    def walk_and_change(*args, **kwargs):
        nonlocal changed
        for entry in original_walk(*args, **kwargs):
            if not changed:
                changed = True
                api.set_include_subfolders(False)
            yield entry
    with mock.patch('queue_api.os.walk', side_effect=walk_and_change):
        state = api.stage_files([str(root) for root in sources])
    assert {item['source'] for item in state['items']} == expected
    assert api.get_preferences()['include_subfolders'] is False


@pytest.mark.parametrize('save_fails', [False, True])
def test_native_intake_waits_for_pending_preference_save(api, tmp_path, monkeypatch, save_fails):
    direct, deep = make_folder(tmp_path / 'source')
    api.save_preferences({'theme': 'light'})
    started, finish = threading.Event(), threading.Event()
    intake_started, intake_finished = threading.Event(), threading.Event()
    errors, intake_errors, intake_results = [], [], []
    original_save = type(api._preferences).save
    def delayed_save(self, path):
        started.set()
        if not finish.wait(5):
            raise TimeoutError('Test did not release preference save')
        if save_fails:
            raise OSError('Disk is full')
        original_save(self, path)
    monkeypatch.setattr(type(api._preferences), 'save', delayed_save)
    def change_choice():
        try:
            api.set_include_subfolders(False)
        except BaseException as exc:
            errors.append(exc)
    def native_intake():
        intake_started.set()
        try:
            intake_results.append(api.stage_files([str(direct.parent)]))
        except BaseException as exc:
            intake_errors.append(exc)
        finally:
            intake_finished.set()
    thread = threading.Thread(target=change_choice, daemon=True)
    native_thread = threading.Thread(target=native_intake, daemon=True)
    thread.start()
    try:
        assert started.wait(5)
        native_thread.start()
        assert intake_started.wait(5)
        assert not intake_finished.wait(0.1), 'Native intake must wait for the pending option save.'
        assert api.get_preferences()['include_subfolders'] is True
    finally:
        finish.set()
        thread.join(5)
        if native_thread.ident is not None:
            native_thread.join(5)
    assert not thread.is_alive() and not native_thread.is_alive() and not intake_errors
    if save_fails:
        assert len(errors) == 1 and isinstance(errors[0], OSError)
    else:
        assert not errors
    expected_sources = {str(direct), str(deep)} if save_fails else {str(direct)}
    assert {item['source'] for item in intake_results[0]['items']} == expected_sources
    assert api.get_preferences()['include_subfolders'] is save_fails
    assert json.loads(api._preferences_path.read_text())['include_subfolders'] is save_fails
