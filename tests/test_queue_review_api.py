"""Review actions must preserve saved OCR work and the original source files."""
import copy
from pathlib import Path
import sqlite3
import sys
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cli_mode import load_converter_app
from quote_checkpoint import QuoteCheckpoint, batch_lock
from quote_parser import QuoteRecord
from queue_store import QueueBusyError, QueueStore


@pytest.fixture
def api():
    return load_converter_app().Api()


def add_file(api, path, status='failed', error='No text detected in this image.'):
    path.write_bytes(b'original image content')
    state = api.stage_files([str(path)])
    item = next(item for item in state['items'] if item['source'] == str(path.resolve()))
    api._queue_store.update_item(item['id'], status=status, error=error)
    return api._queue_store.get_item(item['id'])


def checkpoint_with_failure(api, tmp_path):
    failed = add_file(api, tmp_path/'empty.png')
    success = add_file(api, tmp_path/'saved.png', status='done', error=None)
    checkpoint = QuoteCheckpoint(tmp_path/'quotes', 'review', [failed['source'], success['source']], 'different')
    for record in checkpoint.items:
        if record['path'] == failed['source']:
            checkpoint.complete(record, [], None, error='No text detected in this image.')
        else:
            checkpoint.complete(record, [QuoteRecord('Preserve this saved quote.', 'Author', success['source'], 'raw text')], None)
    checkpoint.save('completed_with_errors')
    api._queue_store.update_items([failed['id'], success['id']], checkpoint_path=str(checkpoint.report_path))
    return api._queue_store.get_item(failed['id']), api._queue_store.get_item(success['id']), checkpoint


def test_no_text_is_decorated_as_review_without_changing_sqlite(api, tmp_path):
    review = add_file(api, tmp_path/'empty.png')
    failure = add_file(api, tmp_path/'timeout.png', error='Vision timed out after 30 seconds.')
    success = add_file(api, tmp_path/'saved.png', status='done', error=None)
    stored = api._queue_store.items(api._queue_store.active_id)
    state = api.get_queue_state()
    assert (state['review'], state['failed'], state['done'], state['total']) == (1, 1, 1, 3)
    by_id = {item['id']: item for item in state['items']}
    assert by_id[review['id']]['status'] == 'review'
    assert by_id[review['id']]['error_code'] == 'no_text'
    assert by_id[failure['id']]['status'] == 'failed'
    assert by_id[success['id']]['status'] == 'done'
    assert api._queue_store.items(api._queue_store.active_id) == stored


def test_global_retry_does_not_start_when_only_review_items_remain(api, tmp_path):
    add_file(api, tmp_path/'empty.png')
    with mock.patch.object(api, '_start_job') as start:
        assert api.retry_failed() is False
    start.assert_not_called()


@pytest.mark.parametrize('error', ['No text detected in this image.', 'Engine failed'])
def test_single_retry_selects_only_requested_failed_or_review_item(api, tmp_path, error):
    target = add_file(api, tmp_path/'target.png', error=error)
    add_file(api, tmp_path/'other.png', error='Engine failed')
    with mock.patch.object(api, '_start_job', return_value=True) as start:
        assert api.retry_queue_item(target['id']) is True
    start.assert_called_once_with(api._queue_worker, target['queue_id'], True, {target['id']})


@pytest.mark.parametrize('status', ['done', 'waiting', 'processing'])
def test_single_retry_rejects_items_that_are_not_failed(api, tmp_path, status):
    item = add_file(api, tmp_path/'image.png', status=status)
    with mock.patch.object(api, '_start_job') as start:
        with pytest.raises(ValueError, match='(?i)(failed|review|unsuccessful)'):
            api.retry_queue_item(item['id'])
    start.assert_not_called()


def test_preview_launches_quick_look_without_shell_or_source_changes(api, tmp_path):
    item = add_file(api, tmp_path/'image with spaces.png')
    source = Path(item['source'])
    before = source.read_bytes()
    with mock.patch('queue_api.subprocess.Popen') as launch:
        assert api.preview_queue_item(item['id']) is True
    assert launch.call_args.args[0] == ['qlmanage', '-p', str(source)]
    assert not launch.call_args.kwargs.get('shell')
    assert source.read_bytes() == before
    assert api._queue_store.get_item(item['id']) == item


def test_preview_rejects_missing_sources_and_nonfiles(api, tmp_path):
    item = add_file(api, tmp_path/'gone.png')
    Path(item['source']).unlink()
    text = api.stage_text('A note')['items'][-1]
    with mock.patch('queue_api.subprocess.Popen') as launch:
        with pytest.raises((ValueError, FileNotFoundError)):
            api.preview_queue_item(item['id'])
        with pytest.raises(ValueError):
            api.preview_queue_item(text['id'])
    launch.assert_not_called()


@pytest.mark.parametrize('action', ['preview_queue_item', 'retry_queue_item', 'skip_queue_item'])
def test_review_actions_reject_items_from_another_queue(api, tmp_path, action):
    item = add_file(api, tmp_path/'old.png')
    api.create_queue('Other queue')
    with pytest.raises(ValueError, match='another queue'):
        getattr(api, action)(item['id'])
    assert api._queue_store.get_item(item['id']) == item


def test_skip_preserves_source_successful_row_and_saved_quote(api, tmp_path):
    failed, success, checkpoint = checkpoint_with_failure(api, tmp_path)
    source_bytes = Path(failed['source']).read_bytes()
    saved_records = copy.deepcopy(next(item for item in checkpoint.items if item['status'] == 'success'))
    result = api.skip_queue_item(failed['id'])
    assert result['total'] == 1 and result['done'] == 1 and result['review'] == 0
    assert api._queue_store.get_item(success['id']) == success
    assert Path(failed['source']).read_bytes() == source_bytes
    restored = QuoteCheckpoint.load(checkpoint.report_path)
    assert next(item for item in restored.items if item['path'] == failed['source'])['skipped'] is True
    assert next(item for item in restored.items if item['path'] == success['source']) == saved_records
    assert 'Preserve this saved quote.' in checkpoint.path.read_text()
    assert 'Skipped' in checkpoint.path.read_text()


def test_skip_failed_file_without_checkpoint_only_removes_queue_entry(api, tmp_path):
    item = add_file(api, tmp_path/'failed.txt', error='Document conversion failed')
    assert api.skip_queue_item(item['id'])['total'] == 0
    assert Path(item['source']).is_file()


@pytest.mark.parametrize('status', ['done', 'waiting', 'processing'])
def test_skip_rejects_unfailed_items(api, tmp_path, status):
    item = add_file(api, tmp_path/'image.png', status=status)
    with pytest.raises(ValueError, match='(?i)(failed|review|unsuccessful)'):
        api.skip_queue_item(item['id'])
    assert api._queue_store.get_item(item['id']) == item


def test_skip_rejects_successful_journal_even_if_queue_row_is_stale(api, tmp_path):
    failed, success, checkpoint = checkpoint_with_failure(api, tmp_path)
    api._queue_store.update_item(success['id'], status='failed', error='Stale failure')
    before = checkpoint.report_path.read_bytes()
    with pytest.raises(ValueError):
        api.skip_queue_item(success['id'])
    assert checkpoint.report_path.read_bytes() == before
    assert api._queue_store.get_item(success['id'])['status'] == 'failed'


def test_skip_refuses_other_worker_and_busy_batch_without_changing_anything(api, tmp_path):
    failed, success, checkpoint = checkpoint_with_failure(api, tmp_path)
    other = QueueStore(api._queue_store.path)
    before = checkpoint.report_path.read_bytes()
    with other.worker_lock(), pytest.raises(QueueBusyError):
        api.skip_queue_item(failed['id'])
    with batch_lock(checkpoint.report_path.parent), pytest.raises(RuntimeError):
        api.skip_queue_item(failed['id'])
    assert checkpoint.report_path.read_bytes() == before
    assert api._queue_store.get_item(failed['id']) == failed
    assert api._queue_store.get_item(success['id']) == success


def test_skip_database_failure_is_safely_retryable_after_journal_save(api, tmp_path):
    failed, success, checkpoint = checkpoint_with_failure(api, tmp_path)
    with sqlite3.connect(api._queue_store.path) as connection:
        connection.execute("CREATE TRIGGER reject_delete BEFORE DELETE ON items BEGIN SELECT RAISE(ABORT, 'write failed'); END")
    with pytest.raises(sqlite3.DatabaseError, match='write failed'):
        api.skip_queue_item(failed['id'])
    assert api._queue_store.get_item(failed['id']) == failed
    assert next(item for item in QuoteCheckpoint.load(checkpoint.report_path).items
                if item['path'] == failed['source'])['skipped'] is True
    with sqlite3.connect(api._queue_store.path) as connection:
        connection.execute('DROP TRIGGER reject_delete')
    assert api.skip_queue_item(failed['id'])['total'] == 1
    assert api._queue_store.get_item(success['id']) == success


def test_skip_journal_save_failure_leaves_queue_entry(api, tmp_path):
    failed, _, checkpoint = checkpoint_with_failure(api, tmp_path)
    with mock.patch.object(QuoteCheckpoint, 'mark_skipped', side_effect=OSError('storage full')):
        with pytest.raises(OSError, match='storage full'):
            api.skip_queue_item(failed['id'])
    assert api._queue_store.get_item(failed['id']) == failed


def test_removal_callback_runs_under_worker_lock_and_can_abort(api, tmp_path):
    item = add_file(api, tmp_path/'failed.png')
    other = QueueStore(api._queue_store.path)
    def reject(current):
        assert current == item
        with pytest.raises(QueueBusyError), other.worker_lock():
            pass
        raise ValueError('Keep this row')
    with pytest.raises(ValueError, match='Keep this row'):
        api._queue_store.remove_item(item['id'], before_remove=reject)
    assert api._queue_store.get_item(item['id']) == item


def test_skip_rechecks_current_row_after_another_worker_finishes(api, tmp_path):
    item = add_file(api, tmp_path/'raced.png')
    remove_item = api._queue_store.remove_item
    def finish_before_lock(item_id, **kwargs):
        api._queue_store.update_item(item_id, status='done', error=None, output_path=str(tmp_path/'saved.md'))
        return remove_item(item_id, **kwargs)
    with mock.patch.object(api._queue_store, 'remove_item', side_effect=finish_before_lock):
        with pytest.raises(ValueError, match='(?i)(failed|review|unsuccessful)'):
            api.skip_queue_item(item['id'])
    assert api._queue_store.get_item(item['id'])['status'] == 'done'
    assert Path(item['source']).is_file()


def test_skip_rechecks_queue_selection_under_worker_lock(api, tmp_path):
    item = add_file(api, tmp_path/'raced.png')
    other = QueueStore(api._queue_store.path)
    other_queue = other.create_queue('Other window')
    api.select_queue(item['queue_id'])
    remove_item = api._queue_store.remove_item
    def change_before_lock(item_id, **kwargs):
        other.select_queue(other_queue)
        return remove_item(item_id, **kwargs)
    with mock.patch.object(api._queue_store, 'remove_item', side_effect=change_before_lock):
        with pytest.raises(RuntimeError, match='selection changed'):
            api.skip_queue_item(item['id'])
    assert api._queue_store.get_item(item['id']) == item


def test_skip_rejects_local_busy_state_without_changing_journal(api, tmp_path):
    failed, _, checkpoint = checkpoint_with_failure(api, tmp_path)
    before = checkpoint.report_path.read_bytes()
    api._job_running = True
    with pytest.raises(RuntimeError, match='Stop the current conversion'):
        api.skip_queue_item(failed['id'])
    assert checkpoint.report_path.read_bytes() == before
    assert api._queue_store.get_item(failed['id']) == failed


def test_worker_forwards_selected_ids_and_counts_completed_attempts(api, tmp_path):
    target = add_file(api, tmp_path/'review.png')
    add_file(api, tmp_path/'failed.png', error='Engine failed')
    selected = {target['id']}
    runner = mock.Mock()
    def make_runner(*args, **kwargs):
        def run(*args, **run_kwargs):
            kwargs['on_progress'](1, 1, 'review.png')
            kwargs['on_item_processed'](1, 1)
        runner.run.side_effect = run
        return runner
    with mock.patch('queue_api.QueueRunner', side_effect=make_runner), \
         mock.patch.object(api, '_set_progress') as progress, \
         mock.patch.object(api, '_set_summary') as summary:
        api._queue_worker_body(target['queue_id'], True, selected)
    runner.run.assert_called_once_with(target['queue_id'], retry_failed=True, selected_ids=selected)
    assert [call.args[0] for call in progress.call_args_list] == [0, 0, 100, 100]
    assert '1 failed' in summary.call_args.args[0] and '1 to review' in summary.call_args.args[0]


def test_real_worker_single_item_retry_leaves_other_failed_rows_unchanged(api, tmp_path):
    api.save_preferences({'output_dir': str(tmp_path/'exports')})
    first = api.stage_text('A selected note to retry.')['items'][0]
    second = api.stage_text('Another failed note stays untouched.')['items'][1]
    api._queue_store.update_items([first['id'], second['id']], status='failed', error='Previous failure')
    second_before = api._queue_store.get_item(second['id'])
    api._queue_worker_body(first['queue_id'], True, {first['id']})
    result = api._queue_store.get_item(first['id'])
    assert result['status'] == 'done'
    assert Path(result['output_path']).read_text().strip().endswith(first['source'])
    assert api._queue_store.get_item(second['id']) == second_before


def test_skip_can_repair_markdown_write_failure_before_removing_queue_row(api, tmp_path):
    import quote_checkpoint
    failed, success, checkpoint = checkpoint_with_failure(api, tmp_path)
    write = quote_checkpoint.atomic_write_text
    def fail_markdown(path, content):
        if Path(path) == checkpoint.path:
            raise OSError('Markdown destination unavailable')
        return write(path, content)
    with mock.patch.object(quote_checkpoint, 'atomic_write_text', side_effect=fail_markdown):
        with pytest.raises(OSError, match='Markdown destination unavailable'):
            api.skip_queue_item(failed['id'])
    assert api._queue_store.get_item(failed['id']) == failed
    interrupted = QuoteCheckpoint.load(checkpoint.report_path)
    assert interrupted.report['export_pending'] is True
    assert api.skip_queue_item(failed['id'])['total'] == 1
    assert QuoteCheckpoint.load(checkpoint.report_path).report['export_pending'] is False
    assert api._queue_store.get_item(success['id']) == success
