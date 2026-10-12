"""Image text stays durable while an optional named output copy is delivered."""
import copy
import json
from pathlib import Path
import sys
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from quote_checkpoint import QuoteCheckpoint, fingerprint
from quote_parser import QuoteRecord


def make_checkpoint(tmp_path, *, failed=False, pending=False, copy_enabled=True):
    source = tmp_path/'sources'/'quote.png'
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b'original image')
    paths = [str(source)]
    if failed or pending:
        other = source.with_name('review.png')
        other.write_bytes(b'another original image')
        paths.append(str(other))
    checkpoint = QuoteCheckpoint(tmp_path/'output'/'quotes', 'saved-quotes', paths, 'different')
    saved = next(item for item in checkpoint.items if item['path'] == str(source))
    checkpoint.complete(saved, [QuoteRecord('Keep this saved quote.', 'Author', str(source), 'Original OCR')], fingerprint(str(source)))
    if failed:
        review = next(item for item in checkpoint.items if item['path'] != str(source))
        checkpoint.complete(review, [], fingerprint(review['path']), error='No text detected.', error_code='no_text')
    if copy_enabled:
        checkpoint.report['copy_dir'] = str(tmp_path/'output'/'Külön másolat')
    return checkpoint


def copied_path(checkpoint):
    return Path(checkpoint.report['copy_exports'][str(checkpoint.path.resolve())]['path'])


@pytest.mark.parametrize('status,failed,pending', [
    ('completed', False, False), ('completed_with_errors', True, False), ('canceled', False, True),
])
def test_final_report_is_copied_exactly_into_named_folder(tmp_path, status, failed, pending):
    checkpoint = make_checkpoint(tmp_path, failed=failed, pending=pending)
    before = copy.deepcopy(checkpoint.items)
    checkpoint.save(status)
    destination = copied_path(checkpoint)
    assert destination == Path(checkpoint.report['copy_dir'])/'quotes'/checkpoint.path.name
    assert destination.read_bytes() == checkpoint.path.read_bytes()
    assert checkpoint.items == before
    assert checkpoint.report['copy_pending'] is False
    assert checkpoint.report['export_pending'] is False
    assert [path.name for path in Path(checkpoint.report['copy_dir']).rglob('*') if path.is_file()] == [checkpoint.path.name]
    assert all(Path(item['path']).is_file() for item in checkpoint.items)


def test_running_saves_keep_ocr_and_primary_output_without_delivering_copy(tmp_path):
    checkpoint = make_checkpoint(tmp_path)
    checkpoint.save('running')
    assert checkpoint.path.is_file()
    assert not Path(checkpoint.report['copy_dir']).exists()
    assert QuoteCheckpoint.load(checkpoint.report_path).items == checkpoint.items
    checkpoint.save('completed')
    assert copied_path(checkpoint).read_bytes() == checkpoint.path.read_bytes()


def test_old_journal_without_copy_option_keeps_legacy_behavior(tmp_path):
    checkpoint = make_checkpoint(tmp_path, copy_enabled=False)
    checkpoint.save('completed')
    restored = QuoteCheckpoint.load(checkpoint.report_path)
    assert not any(key.startswith('copy_') for key in restored.report)
    assert restored.path.read_bytes() == checkpoint.path.read_bytes()


def test_copy_failure_preserves_primary_and_repairs_using_saved_records(tmp_path, monkeypatch):
    import converters
    import quote_checkpoint
    checkpoint = make_checkpoint(tmp_path)
    before = copy.deepcopy(checkpoint.items)
    with mock.patch.object(quote_checkpoint, 'deliver_output_copies', side_effect=OSError('copy volume unavailable')):
        with pytest.raises(OSError, match='Image text is saved; additional copy failed'):
            checkpoint.save('completed')
    interrupted = QuoteCheckpoint.load(checkpoint.report_path)
    assert interrupted.report['export_pending'] is True
    assert interrupted.report['copy_pending'] is True
    assert interrupted.items == before
    assert 'Keep this saved quote.' in checkpoint.path.read_text()
    interrupted.save('running')
    assert QuoteCheckpoint.load(checkpoint.report_path).report['export_pending'] is True
    monkeypatch.setattr(converters, 'ocr_image', lambda *args, **kwargs: pytest.fail('Saved text must not be OCRed again'))
    converters.convert_image_folder_quotes(
        [item['path'] for item in checkpoint.items], checkpoint.path.parent,
        checkpoint_path=checkpoint.report_path, preserve_completed=True)
    repaired = QuoteCheckpoint.load(checkpoint.report_path)
    assert repaired.items == before
    assert repaired.report['export_pending'] is False and repaired.report['copy_pending'] is False
    assert copied_path(repaired).read_bytes() == repaired.path.read_bytes()


def test_copy_destination_file_does_not_block_running_journal_or_loading_retry(tmp_path):
    checkpoint = make_checkpoint(tmp_path)
    copy_dir = Path(checkpoint.report['copy_dir'])
    copy_dir.parent.mkdir(parents=True, exist_ok=True)
    copy_dir.write_bytes(b'unrelated file at destination')
    checkpoint.save('running')
    assert QuoteCheckpoint.load(checkpoint.report_path).items == checkpoint.items
    with pytest.raises(OSError, match='Image text is saved; additional copy failed'):
        checkpoint.save('completed')
    interrupted = QuoteCheckpoint.load(checkpoint.report_path)
    assert interrupted.report['export_pending'] is True
    assert 'Keep this saved quote.' in checkpoint.path.read_text()
    assert copy_dir.read_bytes() == b'unrelated file at destination'
    copy_dir.unlink()
    interrupted.save('completed')
    assert copied_path(interrupted).read_bytes() == checkpoint.path.read_bytes()


def test_skip_updates_named_copy_and_existing_vault_copy(tmp_path):
    checkpoint = make_checkpoint(tmp_path, failed=True)
    checkpoint.save('completed_with_errors')
    destination = copied_path(checkpoint)
    vault = tmp_path/'vault'/'quotes'/checkpoint.path.name
    vault.parent.mkdir(parents=True)
    vault.write_bytes(checkpoint.path.read_bytes())
    checkpoint.report['vault_exports'] = {str(vault.parent): vault.name}
    success_before = copy.deepcopy(next(item for item in checkpoint.items if item['status'] == 'success'))
    review = next(item for item in checkpoint.items if item['status'] == 'failed')
    checkpoint.mark_skipped(review['path'])
    assert copied_path(checkpoint) == destination
    assert destination.read_bytes() == checkpoint.path.read_bytes() == vault.read_bytes()
    assert 'Skipped:' in destination.read_text()
    assert next(item for item in checkpoint.items if item['status'] == 'success') == success_before


def test_skip_copy_failure_can_be_retried_without_discarding_successful_text(tmp_path):
    import quote_checkpoint
    checkpoint = make_checkpoint(tmp_path, failed=True)
    checkpoint.save('completed_with_errors')
    destination = copied_path(checkpoint)
    successful_before = copy.deepcopy(next(item for item in checkpoint.items if item['status'] == 'success'))
    review = next(item for item in checkpoint.items if item['status'] == 'failed')
    with mock.patch.object(quote_checkpoint, 'deliver_output_copies', side_effect=OSError('copy not writable')):
        with pytest.raises(OSError):
            checkpoint.mark_skipped(review['path'])
    interrupted = QuoteCheckpoint.load(checkpoint.report_path)
    assert interrupted.report['export_pending'] and interrupted.report['copy_pending']
    assert 'Skipped:' in checkpoint.path.read_text()
    assert 'Skipped:' not in destination.read_text()
    interrupted.mark_skipped(review['path'])
    assert copied_path(interrupted) == destination
    assert destination.read_bytes() == checkpoint.path.read_bytes()
    assert next(item for item in interrupted.items if item['status'] == 'success') == successful_before


def test_copy_edited_by_user_is_preserved_when_skipped_report_is_delivered(tmp_path):
    checkpoint = make_checkpoint(tmp_path, failed=True)
    checkpoint.save('completed_with_errors')
    original_copy = copied_path(checkpoint)
    original_copy.write_text('User edited this copy.\n')
    review = next(item for item in checkpoint.items if item['status'] == 'failed')
    checkpoint.mark_skipped(review['path'])
    assert original_copy.read_text() == 'User edited this copy.\n'
    assert copied_path(checkpoint) != original_copy
    assert copied_path(checkpoint).read_bytes() == checkpoint.path.read_bytes()


@pytest.mark.parametrize('field,value', [
    ('copy_dir', 'relative/path'), ('copy_dir', '/tmp/outside-saved-output'),
    ('copy_pending', 'yes'), ('copy_exports', []),
    ('copy_exports', {'/tmp/source.md': {'path': '/tmp/elsewhere.md', 'sha256': None, 'pending_sha256': None}}),
])
def test_invalid_copy_metadata_is_rejected_on_load_without_changing_files(tmp_path, field, value):
    checkpoint = make_checkpoint(tmp_path, copy_enabled=False)
    checkpoint.save('completed')
    data = json.loads(checkpoint.report_path.read_text())
    data[field] = value
    checkpoint.report_path.write_text(json.dumps(data))
    original_report, original_markdown = checkpoint.report_path.read_bytes(), checkpoint.path.read_bytes()
    with pytest.raises(ValueError):
        QuoteCheckpoint.load(checkpoint.report_path)
    assert checkpoint.report_path.read_bytes() == original_report
    assert checkpoint.path.read_bytes() == original_markdown


def test_copy_metadata_loads_when_primary_markdown_needs_reconstruction(tmp_path):
    checkpoint = make_checkpoint(tmp_path)
    checkpoint.save('completed')
    before = copy.deepcopy(checkpoint.items)
    checkpoint.path.unlink()
    restored = QuoteCheckpoint.load(checkpoint.report_path)
    assert restored.items == before
    restored.save('completed')
    assert restored.path.read_bytes() == copied_path(restored).read_bytes()


def test_copy_journal_reloads_when_output_uses_a_parent_directory_alias(tmp_path):
    real_parent = tmp_path/'actual-parent'
    real_parent.mkdir()
    alias = tmp_path/'parent-alias'
    alias.symlink_to(real_parent, target_is_directory=True)
    source = tmp_path/'source.png'
    source.write_bytes(b'image fixture')
    checkpoint = QuoteCheckpoint(alias/'output'/'quotes', 'saved', [str(source)], 'different')
    checkpoint.complete(checkpoint.items[0], [QuoteRecord('Saved quote.', '', source.name, 'Saved quote.')], fingerprint(str(source)))
    checkpoint.report['copy_dir'] = str(alias/'output'/'Copies')
    checkpoint.save('completed')
    restored = QuoteCheckpoint.load(checkpoint.report_path)
    assert restored.items == checkpoint.items
    assert Path(restored.report['copy_exports'][str(restored.path)]['path']).read_bytes() == restored.path.read_bytes()
