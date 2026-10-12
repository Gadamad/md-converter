import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import converters
from image_ocr import (OcrBackendUnavailable, OcrCancelled, OcrNoTextDetected,
                       OcrProcessingError, OcrResult, OcrTimeout)
from quote_checkpoint import QuoteCheckpoint, fingerprint
from quote_parser import QuoteRecord
from queue_runner import QueueRunner
from queue_store import QueueStore


NO_TEXT = 'No text detected. Preview the image or skip it.'
DIAGNOSTICS = [{'engine': 'vision', 'variant': 'original', 'status': 'empty',
                'elapsed_seconds': 0.2}]


def seed_batch(tmp_path, states, stem='batch'):
    paths = [tmp_path / f'{stem}-{index}.jpg' for index in range(len(states))]
    for path in paths:
        path.write_bytes(path.name.encode())
    output = tmp_path / 'output' / 'quotes'
    output.mkdir(parents=True, exist_ok=True)
    checkpoint = QuoteCheckpoint(output, stem, [str(path) for path in paths], 'different')
    for item, state in zip(checkpoint.items, states):
        if state == 'success':
            text = f"Saved text from {Path(item['path']).name}."
            checkpoint.complete(item, [QuoteRecord(text, '', Path(item['path']).name, text)],
                                fingerprint(item['path']))
        elif state == 'failed':
            checkpoint.complete(item, [], fingerprint(item['path']), error='Engine unavailable')
    checkpoint.save('canceled' if 'pending' in states else 'completed_with_errors')
    return checkpoint


def queue_batch(tmp_path, checkpoint, store=None):
    store = store or QueueStore(tmp_path / 'queues.sqlite3')
    options = {'output_dir': str(tmp_path / 'output'), 'vault_dir': None,
               'raw_ocr_mode': 'different'}
    store.add_items(store.active_id, [dict(kind='file', source=item['path'],
                    title=Path(item['path']).name) for item in checkpoint.items])
    by_path = {item['path']: item for item in checkpoint.items}
    for item in store.items(store.active_id):
        record = by_path.get(item['source'])
        if record is not None:
            store.update_item(item['id'], options=options,
                              status={'success': 'done', 'failed': 'failed', 'pending': 'waiting'}[record['status']],
                              error=record.get('error', ''), checkpoint_path=str(checkpoint.report_path),
                              output_path=str(checkpoint.path))
    return store


def run_queue(tmp_path, store, **kwargs):
    return QueueRunner(store, tmp_path / 'cache', {'output_dir': str(tmp_path / 'output'),
        'vault_dir': None, 'raw_ocr_mode': 'different'}, **kwargs)


@pytest.mark.parametrize('code,message', [
    ('no_text', 'Backends returned no text'),
    ('timeout', 'OCR timed out after 30 seconds'),
    ('processing_error', 'Image decoding failed'),
    ('unavailable', 'OCR engine is unavailable'),
])
def test_ocr_failure_persists_typed_diagnostics_without_conflating_errors(
    tmp_path, monkeypatch, code, message
):
    checkpoint = seed_batch(tmp_path, ['pending'])
    def fail(*args, **kwargs):
        error_type = {'no_text': OcrNoTextDetected, 'timeout': OcrTimeout,
                      'processing_error': OcrProcessingError, 'unavailable': OcrBackendUnavailable}[code]
        raise error_type(message, diagnostics=DIAGNOSTICS)
    monkeypatch.setattr(converters, 'ocr_image', fail)
    notices = []
    converters.convert_image_folder_quotes([item['path'] for item in checkpoint.items],
        checkpoint.path.parent, checkpoint_path=checkpoint.report_path,
        hooks=converters.QuoteBatchHooks(on_status=notices.append))
    saved = QuoteCheckpoint.load(checkpoint.report_path).items[0]
    assert saved['status'] == 'failed' and saved['records'] == []
    assert saved['error'] == (NO_TEXT if code == 'no_text' else message)
    assert saved['error_code'] == code
    assert saved['diagnostics'] == DIAGNOSTICS
    assert notices[-1].startswith('Needs review:' if code == 'no_text' else 'Failed:')


def test_successful_ocr_keeps_diagnostics_and_clears_prior_review_flags(tmp_path, monkeypatch):
    checkpoint = seed_batch(tmp_path, ['failed'])
    checkpoint.items[0].update(error=NO_TEXT, error_code='no_text', diagnostics=DIAGNOSTICS)
    checkpoint.save('completed_with_errors')
    diagnostics = [{'engine': 'tesseract', 'variant': 'contrast', 'status': 'success'}]
    monkeypatch.setattr(converters, 'ocr_image', lambda *a, **k: SimpleNamespace(
        text='Recovered words.', engine='tesseract', diagnostics=diagnostics))
    result = converters.convert_image_folder_quotes([item['path'] for item in checkpoint.items],
        checkpoint.path.parent, checkpoint_path=checkpoint.report_path, retry_failed=True,
        selected_paths={checkpoint.items[0]['path']})
    saved = QuoteCheckpoint.load(checkpoint.report_path).items[0]
    assert result.success and saved['status'] == 'success'
    assert 'error' not in saved and 'error_code' not in saved
    assert saved['diagnostics'] == diagnostics


@pytest.mark.parametrize('use_code', [True, False])
def test_global_retry_skips_review_items_in_old_and_new_journals(tmp_path, monkeypatch, use_code):
    checkpoint = seed_batch(tmp_path, ['success', 'failed', 'failed'])
    saved_record = copy.deepcopy(checkpoint.items[0])
    checkpoint.items[1]['error'] = NO_TEXT
    if use_code:
        checkpoint.items[1]['error_code'] = 'no_text'
    checkpoint.save('completed_with_errors')
    calls = []
    def extract(path, **kwargs):
        calls.append(path.name)
        return OcrResult('Recovered.', 'vision')
    monkeypatch.setattr(converters, 'ocr_image', extract)
    converters.convert_image_folder_quotes([item['path'] for item in checkpoint.items],
        checkpoint.path.parent, checkpoint_path=checkpoint.report_path, retry_failed=True)
    updated = QuoteCheckpoint.load(checkpoint.report_path)
    assert calls == [Path(checkpoint.items[2]['path']).name]
    assert updated.items[0] == saved_record
    assert updated.items[1]['error'] == NO_TEXT


def test_mark_skipped_is_durable_idempotent_and_preserves_saved_quotes(tmp_path):
    checkpoint = seed_batch(tmp_path, ['success', 'failed'])
    success = copy.deepcopy(checkpoint.items[0])
    skipped_path = checkpoint.items[1]['path']
    checkpoint.mark_skipped(skipped_path)
    persisted = checkpoint.report_path.read_bytes()
    markdown = checkpoint.path.read_bytes()
    loaded = QuoteCheckpoint.load(checkpoint.report_path)
    loaded.mark_skipped(skipped_path)
    assert loaded.report['failed'] == []
    assert loaded.report['skipped'] == [{'image': skipped_path, 'error': 'Engine unavailable'}]
    assert loaded.items[0] == success
    assert loaded.items[1]['skipped'] is True
    assert loaded.report['status'] == 'completed'
    assert loaded.report_path.read_bytes() == persisted
    assert loaded.path.read_bytes() == markdown
    assert b'Skipped:' in markdown and b'Failed:' not in markdown
    assert success['records'][0]['quote'].encode() in markdown


@pytest.mark.parametrize('state', ['success', 'pending', 'previous'])
def test_skipping_cannot_discard_any_saved_text_or_pending_work(tmp_path, state):
    checkpoint = seed_batch(tmp_path, ['failed' if state == 'previous' else state])
    if state == 'previous':
        checkpoint.items[0]['previous_records'] = [dict(quote='Keep me.', author='',
            source_image='old.jpg', raw_ocr='Keep me.')]
        checkpoint.save('completed_with_errors')
    before = checkpoint.report_path.read_bytes(), checkpoint.path.read_bytes()
    with pytest.raises(ValueError):
        checkpoint.mark_skipped(checkpoint.items[0]['path'])
    assert (checkpoint.report_path.read_bytes(), checkpoint.path.read_bytes()) == before


@pytest.mark.parametrize('field,value', [
    ('error_code', 17), ('diagnostics', 'bad'), ('diagnostics', ['bad']),
    ('skipped', 'yes'), ('skipped', 1),
])
def test_optional_journal_metadata_is_validated(tmp_path, field, value):
    checkpoint = seed_batch(tmp_path, ['failed'])
    data = json.loads(checkpoint.report_path.read_text())
    data['items'][0][field] = value
    checkpoint.report_path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        QuoteCheckpoint.load(checkpoint.report_path)


def test_legacy_schema_two_reports_without_ocr_metadata_still_load(tmp_path):
    checkpoint = seed_batch(tmp_path, ['failed'])
    data = json.loads(checkpoint.report_path.read_text())
    data.pop('skipped', None)
    checkpoint.report_path.write_text(json.dumps(data))
    loaded = QuoteCheckpoint.load(checkpoint.report_path)
    assert loaded.items == data['items'] and loaded.report['skipped'] == []


def test_explicit_retry_only_attempts_selected_review_item_across_groups(tmp_path, monkeypatch):
    first = seed_batch(tmp_path, ['success', 'failed', 'failed'], 'first')
    first.items[1].update(error=NO_TEXT, error_code='no_text')
    first.save('completed_with_errors')
    second = seed_batch(tmp_path, ['failed'], 'second')
    second_report = second.report_path.read_bytes()
    second_output = second.path.read_bytes()
    store = queue_batch(tmp_path, first)
    queue_batch(tmp_path, second, store)
    selected = store.items(store.active_id)[1]
    saved = copy.deepcopy(first.items[0])
    calls = []
    def extract(path, **kwargs):
        calls.append(str(path))
        return OcrResult('Recovered selected image.', 'vision')
    monkeypatch.setattr(converters, 'ocr_image', extract)
    run_queue(tmp_path, store).run(store.active_id, retry_failed=True, selected_ids={selected['id']})
    assert calls == [selected['source']]
    assert [item['status'] for item in store.items(store.active_id)] == ['done', 'done', 'failed', 'failed']
    assert QuoteCheckpoint.load(first.report_path).items[0] == saved
    assert (second.report_path.read_bytes(), second.path.read_bytes()) == (second_report, second_output)


@pytest.mark.parametrize('selection', ['foreign', 'done', 'waiting', 'missing'])
def test_explicit_retry_rejects_foreign_or_ineligible_ids_before_work(tmp_path, monkeypatch, selection):
    checkpoint = seed_batch(tmp_path, ['success', 'failed', 'pending'])
    store = queue_batch(tmp_path, checkpoint)
    queue_id = store.active_id
    items = store.items(queue_id)
    choices = {'done': items[0]['id'], 'waiting': items[2]['id'], 'missing': 'unknown'}
    foreign = store.create_queue('Other')
    store.add_items(foreign, [dict(kind='text', source='Other queue.', title='Other')])
    choices['foreign'] = store.items(foreign)[0]['id']
    monkeypatch.setattr(converters, 'ocr_image', lambda *a, **k: pytest.fail('No OCR expected'))
    with pytest.raises(ValueError):
        run_queue(tmp_path, store).run(queue_id, retry_failed=True,
            selected_ids={items[1]['id'], choices[selection]})
    assert store.get_item(items[1]['id'])['status'] == 'failed'


def test_queue_global_retry_filters_no_text_code_and_legacy_prefix(tmp_path, monkeypatch):
    checkpoint = seed_batch(tmp_path, ['failed', 'failed', 'failed'])
    checkpoint.items[0].update(error='Older engine detail', error_code='no_text')
    checkpoint.items[1]['error'] = NO_TEXT
    checkpoint.save('completed_with_errors')
    store = queue_batch(tmp_path, checkpoint)
    calls = []
    def extract(path, **kwargs):
        calls.append(str(path))
        return OcrResult('Recovered.', 'vision')
    monkeypatch.setattr(converters, 'ocr_image', extract)
    run_queue(tmp_path, store).run(store.active_id, retry_failed=True)
    assert calls == [checkpoint.items[2]['path']]


def test_skipped_images_are_never_retried_even_with_explicit_paths(tmp_path, monkeypatch):
    checkpoint = seed_batch(tmp_path, ['failed', 'failed'])
    checkpoint.mark_skipped(checkpoint.items[0]['path'])
    calls = []
    def extract(path, **kwargs):
        calls.append(str(path))
        return OcrResult('Recovered.', 'vision')
    monkeypatch.setattr(converters, 'ocr_image', extract)
    converters.convert_image_folder_quotes([item['path'] for item in checkpoint.items],
        checkpoint.path.parent, checkpoint_path=checkpoint.report_path, retry_failed=True,
        selected_paths={item['path'] for item in checkpoint.items})
    assert calls == [checkpoint.items[1]['path']]
    updated = QuoteCheckpoint.load(checkpoint.report_path)
    assert len(updated.report['skipped']) == 1 and updated.report['failed'] == []


@pytest.mark.parametrize('cancel_second', [False, True])
def test_retry_progress_counts_selected_attempts_and_actual_completions(tmp_path, monkeypatch, cancel_second):
    checkpoint = seed_batch(tmp_path, ['success'] * 4 + ['failed', 'failed'])
    store = queue_batch(tmp_path, checkpoint)
    starts, completed, calls = [], [], []
    def extract(path, **kwargs):
        calls.append(path.name)
        if cancel_second and len(calls) == 2:
            raise OcrCancelled('Stopped')
        return OcrResult('Recovered.', 'vision')
    monkeypatch.setattr(converters, 'ocr_image', extract)
    run_queue(tmp_path, store,
        on_progress=lambda n, total, name: starts.append((n, total)),
        on_item_processed=lambda n, total: completed.append((n, total)),
    ).run(store.active_id, retry_failed=True)
    assert starts == [(1, 2), (2, 2)]
    assert completed == ([(1, 2)] if cancel_second else [(1, 2), (2, 2)])


def test_document_completion_progress_reaches_total(tmp_path):
    store = QueueStore(tmp_path / 'queues.sqlite3')
    store.add_items(store.active_id, [dict(kind='text', source='First.', title='One'),
                                     dict(kind='text', source='Second.', title='Two')])
    events = []
    run_queue(tmp_path, store,
        on_progress=lambda n, total, name: events.append(('start', n, total)),
        on_item_processed=lambda n, total: events.append(('done', n, total)),
    ).run(store.active_id)
    assert events == [('start', 1, 2), ('done', 1, 2), ('start', 2, 2), ('done', 2, 2)]


@pytest.mark.parametrize('damage', ['missing', 'invalid'])
def test_unreadable_image_journal_finishes_failed_attempt_progress(tmp_path, damage):
    checkpoint = seed_batch(tmp_path, ['failed', 'failed'])
    store = queue_batch(tmp_path, checkpoint)
    if damage == 'missing':
        checkpoint.report_path.unlink()
    else:
        checkpoint.report_path.write_text('{')
    completed = []
    run_queue(tmp_path, store,
        on_item_processed=lambda n, total: completed.append((n, total)),
    ).run(store.active_id, retry_failed=True)
    assert completed == [(1, 2), (2, 2)]
    assert all(item['status'] == 'failed' for item in store.items(store.active_id))


def test_skip_report_export_failure_is_repaired_without_losing_saved_text(tmp_path, monkeypatch):
    import quote_checkpoint
    checkpoint = seed_batch(tmp_path, ['success', 'failed'])
    saved = copy.deepcopy(checkpoint.items[0])
    original_write = quote_checkpoint.atomic_write_text
    def fail_markdown(path, text):
        if path == checkpoint.path:
            raise OSError('Output disk unavailable')
        original_write(path, text)
    monkeypatch.setattr(quote_checkpoint, 'atomic_write_text', fail_markdown)
    with pytest.raises(OSError):
        checkpoint.mark_skipped(checkpoint.items[1]['path'])
    loaded = QuoteCheckpoint.load(checkpoint.report_path)
    assert loaded.report['export_pending'] and loaded.items[1]['skipped']
    monkeypatch.setattr(quote_checkpoint, 'atomic_write_text', original_write)
    loaded.mark_skipped(checkpoint.items[1]['path'])
    repaired = QuoteCheckpoint.load(checkpoint.report_path)
    assert not repaired.report['export_pending']
    assert repaired.items[0] == saved
    assert len(repaired.report['skipped']) == 1


def test_queued_skipped_journal_item_is_not_retried_before_row_removal(tmp_path, monkeypatch):
    checkpoint = seed_batch(tmp_path, ['failed', 'failed'])
    store = queue_batch(tmp_path, checkpoint)
    skipped_id = store.items(store.active_id)[0]['id']
    checkpoint.mark_skipped(checkpoint.items[0]['path'])
    calls = []
    def extract(path, **kwargs):
        calls.append(str(path))
        return OcrResult('Recovered.', 'vision')
    monkeypatch.setattr(converters, 'ocr_image', extract)
    run_queue(tmp_path, store).run(store.active_id, retry_failed=True)
    assert calls == [checkpoint.items[1]['path']]
    with pytest.raises(ValueError, match='Skipped'):
        run_queue(tmp_path, store).run(store.active_id, retry_failed=True, selected_ids={skipped_id})


def test_cancel_during_selected_retry_leaves_other_groups_and_saved_results_unchanged(tmp_path, monkeypatch):
    first = seed_batch(tmp_path, ['success', 'failed', 'failed'], 'first')
    second = seed_batch(tmp_path, ['failed'], 'second')
    saved = copy.deepcopy(first.items[0])
    unchanged = second.report_path.read_bytes(), second.path.read_bytes()
    store = queue_batch(tmp_path, first)
    queue_batch(tmp_path, second, store)
    canceled = False
    completed = []
    calls = []
    def extract(path, **kwargs):
        calls.append(str(path))
        return OcrResult('Recovered before stop.', 'vision')
    def stop_after_one(count, total):
        nonlocal canceled
        completed.append((count, total))
        canceled = True
    monkeypatch.setattr(converters, 'ocr_image', extract)
    selected_ids = {item['id'] for item in store.items(store.active_id) if item['status'] == 'failed'}
    run_queue(tmp_path, store, should_cancel=lambda: canceled,
        on_item_processed=stop_after_one).run(store.active_id, retry_failed=True, selected_ids=selected_ids)
    assert calls == [first.items[1]['path']]
    assert completed == [(1, 3)]
    assert QuoteCheckpoint.load(first.report_path).items[0] == saved
    assert (second.report_path.read_bytes(), second.path.read_bytes()) == unchanged


def exported_review_batch(tmp_path, monkeypatch):
    checkpoint = seed_batch(tmp_path, ['pending', 'pending'])
    first_path = checkpoint.items[0]['path']
    def extract(path, **kwargs):
        if str(path) == first_path:
            return OcrResult('Preserve the exported quote.', 'vision')
        raise OcrNoTextDetected(diagnostics=DIAGNOSTICS)
    monkeypatch.setattr(converters, 'ocr_image', extract)
    converters.convert_image_folder_quotes([item['path'] for item in checkpoint.items],
        checkpoint.path.parent, tmp_path / 'vault', checkpoint_path=checkpoint.report_path)
    return QuoteCheckpoint.load(checkpoint.report_path)


def test_skip_updates_all_existing_vault_exports_without_changing_saved_records(tmp_path, monkeypatch):
    checkpoint = exported_review_batch(tmp_path, monkeypatch)
    converters.convert_image_folder_quotes([item['path'] for item in checkpoint.items],
        checkpoint.path.parent, tmp_path / 'another-vault', checkpoint_path=checkpoint.report_path)
    checkpoint = QuoteCheckpoint.load(checkpoint.report_path)
    saved = copy.deepcopy(checkpoint.items[0])
    exports = copy.deepcopy(checkpoint.report['vault_exports'])
    assert len(exports) == 2

    checkpoint.mark_skipped(checkpoint.items[1]['path'])

    assert checkpoint.items[0] == saved
    assert checkpoint.report['vault_exports'] == exports
    assert checkpoint.report['export_pending'] is False
    for directory, filename in exports.items():
        vault_text = (Path(directory) / filename).read_text()
        assert vault_text == checkpoint.path.read_text()
        assert '- Skipped:' in vault_text and '- Failed:' not in vault_text
        assert 'Status: completed\n' in vault_text
        assert vault_text.count('> Preserve the exported quote.') == 1


def test_skip_vault_failure_keeps_queue_row_and_replay_repairs_export(tmp_path, monkeypatch):
    import quote_checkpoint
    from quote_checkpoint import batch_lock, recovery_checkpoints
    checkpoint = exported_review_batch(tmp_path, monkeypatch)
    store = queue_batch(tmp_path, checkpoint)
    failed = store.items(store.active_id)[1]
    saved = copy.deepcopy(checkpoint.items[0])
    directory, filename = next(iter(checkpoint.report['vault_exports'].items()))
    vault_path = Path(directory) / filename
    original_vault = vault_path.read_bytes()
    original_write = quote_checkpoint.atomic_write_text

    def record_skip(current):
        with batch_lock(checkpoint.path.parent):
            QuoteCheckpoint.load(checkpoint.report_path).mark_skipped(current['source'])

    def fail_vault(path, text):
        if Path(path) == vault_path:
            raise OSError('Vault destination unavailable')
        return original_write(path, text)

    monkeypatch.setattr(quote_checkpoint, 'atomic_write_text', fail_vault)
    with pytest.raises(OSError, match='Vault destination unavailable'):
        store.remove_item(failed['id'], before_remove=record_skip)
    assert store.get_item(failed['id']) == failed
    interrupted = QuoteCheckpoint.load(checkpoint.report_path)
    assert interrupted.items[1]['skipped'] is True
    assert interrupted.items[0] == saved
    assert interrupted.report['export_pending'] is True
    assert len(list(recovery_checkpoints(checkpoint.path.parent))) == 1
    assert vault_path.read_bytes() == original_vault

    monkeypatch.setattr(quote_checkpoint, 'atomic_write_text', original_write)
    store.remove_item(failed['id'], before_remove=record_skip)
    repaired = QuoteCheckpoint.load(checkpoint.report_path)
    assert repaired.items[0] == saved and len(repaired.report['skipped']) == 1
    assert repaired.report['export_pending'] is False
    assert len(store.items(store.active_id)) == 1
    assert vault_path.read_bytes() == checkpoint.path.read_bytes()
    persisted = repaired.report_path.read_bytes(), repaired.path.read_bytes(), vault_path.read_bytes()
    repaired.mark_skipped(failed['source'])
    assert (repaired.report_path.read_bytes(), repaired.path.read_bytes(), vault_path.read_bytes()) == persisted


@pytest.mark.parametrize('destination', ['../protected.md', '/tmp/protected.md', 'protected.txt'])
def test_skip_refuses_unsafe_saved_vault_filenames(tmp_path, monkeypatch, destination):
    checkpoint = exported_review_batch(tmp_path, monkeypatch)
    vault_dir = next(iter(checkpoint.report['vault_exports']))
    protected = Path(vault_dir).parent / 'protected.md'
    protected.write_text('Do not overwrite unrelated files.')
    checkpoint.report['vault_exports'][vault_dir] = destination
    with pytest.raises(ValueError, match='vault'):
        checkpoint.mark_skipped(checkpoint.items[1]['path'])
    assert protected.read_text() == 'Do not overwrite unrelated files.'


def test_skip_refuses_relative_saved_vault_directories(tmp_path, monkeypatch):
    checkpoint = exported_review_batch(tmp_path, monkeypatch)
    checkpoint.report['vault_exports'] = {'relative/quotes': 'batch.md'}
    with pytest.raises(ValueError, match='vault'):
        checkpoint.mark_skipped(checkpoint.items[1]['path'])


def test_normal_recovery_finishes_interrupted_skip_vault_export_without_ocr(tmp_path, monkeypatch):
    import quote_checkpoint
    checkpoint = exported_review_batch(tmp_path, monkeypatch)
    directory, filename = next(iter(checkpoint.report['vault_exports'].items()))
    vault_path = Path(directory) / filename
    original_write = quote_checkpoint.atomic_write_text
    def fail_vault(path, text):
        if Path(path) == vault_path:
            raise OSError('Vault unavailable')
        return original_write(path, text)
    monkeypatch.setattr(quote_checkpoint, 'atomic_write_text', fail_vault)
    with pytest.raises(OSError):
        checkpoint.mark_skipped(checkpoint.items[1]['path'])
    monkeypatch.setattr(quote_checkpoint, 'atomic_write_text', original_write)
    monkeypatch.setattr(converters, 'ocr_image', lambda *a, **k: pytest.fail('Saved records must not be OCRed'))
    result = converters.convert_image_folder_quotes([item['path'] for item in checkpoint.items],
        checkpoint.path.parent)
    assert result.success and result.output_path == str(checkpoint.path)
    assert vault_path.read_bytes() == checkpoint.path.read_bytes()
    assert 'Status: completed\n' in vault_path.read_text()
    assert not QuoteCheckpoint.load(checkpoint.report_path).report['export_pending']
