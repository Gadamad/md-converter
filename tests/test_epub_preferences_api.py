"""EPUB preference persistence and desktop intake/worker boundary contracts."""
from pathlib import Path
import sys
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


@pytest.fixture
def api(tmp_path, monkeypatch):
    import converter_app as app
    monkeypatch.setattr(app, 'default_preferences_path', lambda: tmp_path / 'settings' / 'preferences.json')
    monkeypatch.setattr(app, 'VAULT_DIR', None)
    return app.Api()


def test_epub_preference_survives_save_restart_and_unrelated_save(api):
    prefs = api.save_preferences({'epub_output_format': 'txt'})
    assert prefs['epub_output_format'] == 'txt'
    import converter_app as app
    restored = app.Api()
    assert restored.get_preferences()['epub_output_format'] == 'txt'
    assert restored.save_preferences({'theme': 'dark'})['epub_output_format'] == 'txt'


@pytest.mark.parametrize('invalid', ['html', 'MD', '', None, False, [], {}])
def test_explicit_invalid_epub_save_preserves_memory_and_disk(api, invalid):
    before = api.save_preferences({'epub_output_format': 'txt', 'theme': 'light'})
    disk_before = api._preferences_path.read_bytes()
    with pytest.raises(ValueError, match='(?i)epub'):
        api.save_preferences({'epub_output_format': invalid, 'theme': 'dark'})
    assert api.get_preferences() == before
    assert api._preferences_path.read_bytes() == disk_before


def test_failed_epub_preference_write_preserves_committed_memory_and_disk(api, monkeypatch):
    before = api.save_preferences({'epub_output_format': 'txt'})
    disk_before = api._preferences_path.read_bytes()
    def fail_replace(*args):
        raise OSError('Disk is full')
    monkeypatch.setattr('file_utils.os.replace', fail_replace)
    with pytest.raises(OSError, match='Disk is full'):
        api.save_preferences({'epub_output_format': 'md', 'theme': 'dark'})
    assert api.get_preferences() == before
    assert api._preferences_path.read_bytes() == disk_before
    assert not list(api._preferences_path.parent.glob('.preferences.json.*'))


def test_native_picker_offers_epub_and_collects_without_conversion(api, tmp_path):
    book = tmp_path / 'Árvíztűrő.epub'
    book.write_bytes(b'book fixture; intake must not open it')
    class Window:
        def create_file_dialog(self, dialog_type, **options):
            assert '*.epub' in options['file_types'][0]
            assert 'EPUB books (*.epub)' in options['file_types']
            return [str(book)]
    api.window = Window()
    with mock.patch.object(api, '_start_job') as start:
        state = api.browse_files()
    start.assert_not_called()
    assert state['items'][0]['source'] == str(book.resolve())
    assert state['items'][0]['status'] == 'waiting'


def test_queue_worker_freezes_epub_format_at_start(api):
    api.save_preferences({'epub_output_format': 'txt'})
    queue_id = api.stage_text('A queued note')['active_id']
    captured = {}
    class Runner:
        def __init__(self, store, cache, options, **kwargs):
            captured.update(options)
            api.save_preferences({'epub_output_format': 'md'})
        def run(self, *args, **kwargs):
            pass
    with mock.patch('queue_api.QueueRunner', Runner):
        api._queue_worker_body(queue_id, False)
    assert captured['epub_output_format'] == 'txt'
    assert api.get_preferences()['epub_output_format'] == 'md'


def test_queue_worker_defaults_old_preference_objects_to_markdown(api):
    from types import SimpleNamespace
    api._preferences = SimpleNamespace(output_dir=None, raw_ocr_mode='different', auto_open_output=False)
    captured = {}
    class Runner:
        def __init__(self, store, cache, options, **kwargs):
            captured.update(options)
        def run(self, *args, **kwargs):
            pass
    with mock.patch('queue_api.QueueRunner', Runner):
        api._queue_worker_body(api._queue_store.active_id, False)
    assert captured['epub_output_format'] == 'md'


def test_legacy_worker_passes_epub_format_and_cancellation_only_where_supported(api):
    import converter_app as app
    api.save_preferences({'epub_output_format': 'txt'})
    calls = {}
    def convert(path, output_dir, vault_dir, **options):
        calls[path] = options
        return app.ConvertResult(True, None, 2, 'Converted')
    with mock.patch.object(app, 'route', convert):
        api._worker_body(['/tmp/book.EPUB', '/tmp/file.txt', '/tmp/file.pdf'])
    assert calls['/tmp/book.EPUB']['epub_output_format'] == 'txt'
    assert calls['/tmp/book.EPUB']['should_cancel']() is False
    assert calls['/tmp/file.txt'] == {}
    assert list(calls['/tmp/file.pdf']) == ['should_cancel']
    api._cancel_event.set()
    assert calls['/tmp/book.EPUB']['should_cancel']() is True
