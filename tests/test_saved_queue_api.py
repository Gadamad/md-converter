from pathlib import Path
import sys
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cli_mode import load_converter_app


def test_files_links_and_text_restore_without_conversion(tmp_path):
    app = load_converter_app()
    api = app.Api()
    path = tmp_path/'notes.txt'
    path.write_text('A note')
    with mock.patch.object(app, 'route') as convert, mock.patch.object(api, '_start_job') as start:
        api.stage_files([str(path)])
        api.stage_text('https://example.com/one\nhttps://example.com/two')
        api.stage_text('A thought for tomorrow.')
        convert.assert_not_called()
        start.assert_not_called()
    restored = app.Api().get_queue_state()
    assert restored['total'] == 4 and restored['waiting'] == 4
    assert [item['kind'] for item in restored['items']] == ['file', 'url', 'url', 'text']


def test_named_queue_selection_persists_and_rename_keeps_items():
    app = load_converter_app()
    api = app.Api()
    inbox = api.get_queue_state()['active_id']
    api.create_queue('Research')
    api.stage_text('https://example.com/')
    api.rename_queue('Reading list')
    restored = app.Api()
    assert restored.get_queue_state()['queues'][-1]['name'] == 'Reading list'
    assert restored.get_queue_state()['total'] == 1
    restored.select_queue(inbox)
    assert restored.get_queue_state()['total'] == 0


def test_locate_file_reconnects_failed_item_without_starting(tmp_path):
    app = load_converter_app()
    api = app.Api()
    api.stage_files([str(tmp_path/'missing.txt')])
    item = api.get_queue_state()['items'][0]
    api._queue_store.update_item(item['id'], status='failed', error='Missing')
    replacement = tmp_path/'moved.txt'
    replacement.write_text('Found')
    api.window = mock.Mock()
    api.window.create_file_dialog.return_value = [str(replacement)]
    with mock.patch.object(api, '_start_job') as start:
        state = api.locate_queue_item(item['id'])
        start.assert_not_called()
    assert state['items'][0]['source'] == str(replacement)
    assert state['items'][0]['status'] == 'waiting'


def test_queue_does_not_disappear_when_conversion_starts(tmp_path):
    app = load_converter_app()
    api = app.Api()
    api.stage_text('A saved note')
    with mock.patch.object(app.threading, 'Thread'):
        assert api.convert_staged() is True
    assert api.get_queue_state()['total'] == 1


def test_browser_drop_and_webloc_collect_without_fetching(tmp_path):
    import plistlib
    app = load_converter_app()
    api = app.Api()
    shortcut = tmp_path/'Article.webloc'
    shortcut.write_bytes(plistlib.dumps({'URL':'https://example.com/story'}))
    api.stage_files([str(shortcut)])
    api.stage_drop({'urls':['https://example.com/story', 'https://example.com/other']})
    assert api.get_queue_state()['total'] == 2


def test_queue_owned_image_journals_never_enter_legacy_recovery(tmp_path, monkeypatch):
    import converters
    from queue_runner import QueueRunner
    from quote_checkpoint import QuoteCheckpoint
    app = load_converter_app()
    api = app.Api()
    output = tmp_path/'output'
    api.save_preferences({'output_dir': str(output)})
    image = tmp_path/'failed.jpg'
    image.write_bytes(b'image fixture')
    api.stage_files([str(image)])
    monkeypatch.setattr(converters, 'ocr_image', lambda *a, **k: (_ for _ in ()).throw(ValueError('Unreadable image')))
    QueueRunner(api._queue_store, tmp_path/'cache', {
        'output_dir': str(output), 'vault_dir': None, 'raw_ocr_mode': 'different'
    }).run(api._queue_store.active_id)
    queued_report = api.get_queue_state()['items'][0]['checkpoint_path']
    # Clearing the collection must not expose deleted work in legacy Retry failed.
    api.clear_queue()
    legacy = QuoteCheckpoint(output/'quotes', 'legacy', [str(image)], 'different')
    legacy.save('canceled')
    assert [job['id'] for job in api.get_recovery_jobs()] == [legacy.report_path.name]
    assert QuoteCheckpoint.load(Path(queued_report)).report['queue_owned'] is True


def test_corrupt_saved_queues_keep_app_available_without_replacing_database(tmp_path):
    app = load_converter_app()
    app.default_preferences_path = lambda: tmp_path/'preferences.json'
    database = tmp_path/'queues.sqlite3'
    original = b'not a SQLite database; preserve existing data'
    database.write_bytes(original)
    api = app.Api()
    state = api.get_application_state()['queue']
    assert state['active_id'] is None and state['queues'] == [] and state['items'] == []
    assert (state['waiting'], state['failed'], state['done'], state['total']) == (0, 0, 0, 0)
    assert state['busy'] is False and state['saved'] is False
    assert 'unavailable' in state['save_error'].lower()
    assert str(database) in state['save_error']
    assert database.read_bytes() == original


@pytest.mark.parametrize('method,args', [
    ('create_queue', ('Research',)), ('rename_queue', ('Research',)),
    ('select_queue', ('anything',)), ('clear_queue', ()), ('clear_completed', ()),
    ('stage_text', ('Text',)), ('stage_files', (['/tmp/example.txt'],)),
    ('stage_folder', ('/tmp/example-folder',)), ('stage_drop', ({'text': 'Text'},)),
    ('remove_queue_item', ('anything',)), ('remove_staged_file', ('/tmp/example.txt',)),
    ('remove_staged_folder', ('/tmp/example-folder',)), ('clear_staged_folders', ()),
    ('locate_queue_item', ('anything',)), ('convert_staged', ()), ('retry_failed', ()),
])
def test_unavailable_store_mutations_explain_failure(method, args):
    app = load_converter_app()
    with mock.patch('queue_api.QueueStore', side_effect=PermissionError('Read-only storage')):
        api = app.Api()
    with pytest.raises(RuntimeError, match='(?i)saved queues.*unavailable'):
        getattr(api, method)(*args)
    assert api.get_queue_state()['saved'] is False


@pytest.mark.parametrize('method,args', [
    ('stage_text', ('Preserve intended queue',)),
    ('stage_files', (['/tmp/source.txt'],)),
    ('rename_queue', ('Wrong queue',)), ('clear_queue', ()), ('clear_completed', ()),
    ('convert_staged', ()), ('retry_failed', ()),
])
def test_other_instance_selection_refreshes_ui_and_rejects_stale_action(method, args):
    app = load_converter_app()
    first, second = app.Api(), app.Api()
    original_id = first.get_queue_state()['active_id']
    second.create_queue('Other window')
    second.stage_text('Existing text must remain')
    selected_id = second.get_queue_state()['active_id']
    with mock.patch.object(first, '_js') as render, mock.patch.object(first, '_start_job') as start:
        with pytest.raises(RuntimeError, match='(?i)selection.*changed'):
            getattr(first, method)(*args)
        start.assert_not_called()
        assert any('renderSavedQueue(' in call.args[0] for call in render.call_args_list)
    assert first.get_queue_state()['active_id'] == selected_id
    assert first._queue_store.items(original_id) == []
    assert [item['source'] for item in first._queue_store.items(selected_id)] == ['Existing text must remain']
    assert first.get_queue_state()['queues'][-1]['name'] == 'Other window'


def test_explicit_selection_is_allowed_after_other_instance_selects_queue():
    app = load_converter_app()
    first, second = app.Api(), app.Api()
    original_id = first.get_queue_state()['active_id']
    second.create_queue('Another queue')
    state = first.select_queue(original_id)
    assert state['active_id'] == original_id
    assert first.stage_text('Chosen explicitly')['items'][0]['source'] == 'Chosen explicitly'


def test_throttled_worker_refresh_does_not_read_database_or_render_between_intervals():
    app = load_converter_app()
    api = app.Api()
    api.stage_text('Saved text')
    with mock.patch('queue_api.time.monotonic', return_value=100):
        first = api._queue_changed(force=True)
    with mock.patch('queue_api.time.monotonic', return_value=100.1), \
         mock.patch.object(api._queue_store, 'state') as state, \
         mock.patch.object(api._queue_store, 'items') as items, \
         mock.patch.object(api, '_js') as render:
        assert api._queue_changed(force=False) == first
        state.assert_not_called()
        items.assert_not_called()
        render.assert_not_called()
    with mock.patch('queue_api.time.monotonic', return_value=100.21), \
         mock.patch.object(api._queue_store, 'state', wraps=api._queue_store.state) as state:
        assert api._queue_changed(force=False)['total'] == 1
        state.assert_called_once()


def test_forced_final_refresh_ignores_throttle_and_displays_completed_item():
    app = load_converter_app()
    api = app.Api()
    item_id = api.stage_text('Saved text')['items'][0]['id']
    with mock.patch('queue_api.time.monotonic', return_value=100):
        api._queue_changed()
        api._queue_store.update_item(item_id, status='done')
        assert api._queue_changed(force=False)['done'] == 0
        assert api._queue_changed(force=True)['done'] == 1


def test_selection_changed_during_folder_scan_does_not_redirect_new_files(tmp_path):
    app = load_converter_app()
    first, second = app.Api(), app.Api()
    original_id = first.get_queue_state()['active_id']
    discover = first._file_entries
    def change_selection(paths):
        second.create_queue('Selected during scan')
        return discover(paths)
    with mock.patch.object(first, '_file_entries', side_effect=change_selection):
        with pytest.raises(RuntimeError, match='(?i)selection.*changed'):
            first.stage_files([str(tmp_path/'source.txt')])
    assert first._queue_store.items(original_id) == []
    assert first.get_queue_state()['total'] == 0


def test_runner_uses_throttled_refresh_but_final_worker_refresh_is_forced():
    app = load_converter_app()
    api = app.Api()
    queue_id = api.stage_text('Saved text')['active_id']
    def make_runner(*args, **kwargs):
        runner = mock.Mock()
        def run(*args, **run_kwargs):
            kwargs['on_change']()
            kwargs['on_change']()
        runner.run.side_effect = run
        return runner
    with mock.patch('queue_api.QueueRunner', side_effect=make_runner), \
         mock.patch.object(api, '_queue_changed', wraps=api._queue_changed) as refresh:
        api._queue_worker(queue_id, False)
    assert refresh.call_args_list == [mock.call(force=False), mock.call(force=False), mock.call(force=True)]
