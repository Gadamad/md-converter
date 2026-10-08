import json
from pathlib import Path
import sys
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import converters
from image_ocr import OcrCancelled, OcrResult


def inputs(tmp_path):
    paths = [tmp_path / name for name in ('a.jpg', 'b.jpg', 'c.jpg')]
    for path in paths:
        path.write_bytes(path.name.encode())
    return [str(p) for p in paths]


def test_resubmit_interrupted_batch_resumes_without_duplicate_output(tmp_path):
    paths = inputs(tmp_path)
    out = tmp_path / 'out'
    with mock.patch.object(converters, 'ocr_image', side_effect=[OcrResult('Saved first.', 'vision'), OcrCancelled()]):
        first = converters.convert_image_folder_quotes(paths, out)
    with mock.patch.object(converters, 'ocr_image', return_value=OcrResult('Next quote.', 'vision')) as read:
        result = converters.convert_image_folder_quotes(paths, out)
    assert [c.args[0].name for c in read.call_args_list] == ['b.jpg', 'c.jpg']
    assert result.success
    assert result.output_path == first.output_path
    assert Path(result.output_path).read_text().count('> Saved first.') == 1
    assert len(list(out.glob('*.md'))) == 1


def test_retry_only_failed_preserves_order_and_updates_report(tmp_path):
    paths = inputs(tmp_path)
    out = tmp_path / 'out'
    with mock.patch.object(converters, 'ocr_image', side_effect=[OcrResult('First.', 'vision'), ValueError('Unreadable'), OcrResult('Third.', 'vision')]):
        first = converters.convert_image_folder_quotes(paths, out)
    report = Path(first.output_path).with_suffix('.progress.json')
    with mock.patch.object(converters, 'ocr_image', return_value=OcrResult('Second.', 'tesseract')) as read:
        result = converters.convert_image_folder_quotes(paths, out, checkpoint_path=report, retry_failed=True)
    assert [c.args[0].name for c in read.call_args_list] == ['b.jpg']
    assert result.success
    text = Path(result.output_path).read_text()
    assert text.index('First.') < text.index('Second.') < text.index('Third.')
    assert json.loads(report.read_text())['failed'] == []


def test_resume_reprocesses_changed_source_and_recreates_missing_markdown(tmp_path):
    paths = inputs(tmp_path)
    out = tmp_path / 'out'
    with mock.patch.object(converters, 'ocr_image', side_effect=[OcrResult('Old.', 'vision'), OcrCancelled()]):
        first = converters.convert_image_folder_quotes(paths, out)
    Path(paths[0]).write_bytes(b'changed')
    Path(first.output_path).unlink()
    with mock.patch.object(converters, 'ocr_image', return_value=OcrResult('Fresh.', 'vision')) as read:
        result = converters.convert_image_folder_quotes(paths, out)
    assert read.call_count == 3
    assert 'Old.' not in Path(result.output_path).read_text()


def test_invalid_and_legacy_reports_do_not_break_new_conversion(tmp_path):
    paths = inputs(tmp_path)
    out = tmp_path / 'out'
    out.mkdir()
    (out / 'broken.progress.json').write_text('{')
    (out / 'legacy.progress.json').write_text('{"status":"canceled"}')
    with mock.patch.object(converters, 'ocr_image', return_value=OcrResult('Good.', 'vision')):
        result = converters.convert_image_folder_quotes(paths, out)
    assert result.success


def test_missing_completed_source_keeps_saved_quote(tmp_path):
    paths = inputs(tmp_path)
    out = tmp_path / 'out'
    with mock.patch.object(converters, 'ocr_image', side_effect=[OcrResult('Keep saved.', 'vision'), OcrCancelled()]):
        first = converters.convert_image_folder_quotes(paths, out)
    Path(paths[0]).unlink()
    with mock.patch.object(converters, 'ocr_image', return_value=OcrResult('Next.', 'vision')) as read:
        result = converters.convert_image_folder_quotes(paths, out)
    assert read.call_count == 2
    assert 'Keep saved.' in Path(result.output_path).read_text()


def test_final_export_failure_can_be_repaired_without_ocr(tmp_path):
    from quote_checkpoint import QuoteCheckpoint, recovery_checkpoints
    from quote_parser import QuoteRecord
    import quote_checkpoint as journal
    paths = inputs(tmp_path)
    checkpoint = QuoteCheckpoint(tmp_path / 'out', 'batch', paths, 'different')
    for item in checkpoint.items:
        checkpoint.complete(item, [QuoteRecord('Saved quote.', '', Path(item['path']).name, 'Saved quote.')], journal.fingerprint(item['path']))
    original = journal.atomic_write_text
    def fail_markdown(path, text):
        if path.suffix == '.md':
            raise OSError('disk full')
        original(path, text)
    import pytest
    with mock.patch.object(journal, 'atomic_write_text', side_effect=fail_markdown), pytest.raises(OSError):
        checkpoint.save('completed')
    assert len(list(recovery_checkpoints(tmp_path / 'out'))) == 1
    with mock.patch.object(converters, 'ocr_image') as read:
        result = converters.convert_image_folder_quotes(paths, tmp_path / 'out')
    read.assert_not_called()
    assert result.success
    assert Path(result.output_path).read_text().count('> Saved quote.') == 3


def test_retry_progress_does_not_count_unprocessed_images(tmp_path):
    paths = inputs(tmp_path)
    out = tmp_path / 'out'
    with mock.patch.object(converters, 'ocr_image', side_effect=[OcrResult('First.', 'vision'), ValueError('bad'), OcrCancelled()]):
        first = converters.convert_image_folder_quotes(paths, out)
    progress = []
    with mock.patch.object(converters, 'ocr_image', return_value=OcrResult('Second.', 'vision')):
        result = converters.convert_image_folder_quotes(paths, out, checkpoint_path=Path(first.output_path).with_suffix('.progress.json'), retry_failed=True,
            hooks=converters.QuoteBatchHooks(on_image_processed=lambda n,t,name: progress.append(n)))
    assert progress == [1, 2]
    assert '2/3' in result.message


def test_failed_reconversion_retains_previous_text_explicitly(tmp_path):
    paths = inputs(tmp_path)
    out = tmp_path / 'out'
    with mock.patch.object(converters, 'ocr_image', side_effect=[OcrResult('Previous saved.', 'vision'), OcrCancelled()]):
        first = converters.convert_image_folder_quotes(paths, out)
    Path(paths[0]).write_bytes(b'changed')
    with mock.patch.object(converters, 'ocr_image', side_effect=[ValueError('bad replacement'), OcrResult('B.', 'vision'), OcrResult('C.', 'vision')]):
        result = converters.convert_image_folder_quotes(paths, out)
    assert 'Previous saved.' in Path(result.output_path).read_text()
    assert 'Previous results' in Path(result.output_path).read_text()


def test_resume_updates_same_vault_export(tmp_path):
    paths = inputs(tmp_path)
    out, vault = tmp_path / 'out', tmp_path / 'vault'
    with mock.patch.object(converters, 'ocr_image', side_effect=[OcrResult('First.', 'vision'), OcrCancelled()]):
        converters.convert_image_folder_quotes(paths, out, vault)
    with mock.patch.object(converters, 'ocr_image', return_value=OcrResult('Next.', 'vision')):
        result = converters.convert_image_folder_quotes(paths, out, vault)
    files = list((vault / 'quotes').glob('*.md'))
    assert len(files) == 1
    assert files[0].read_text() == Path(result.output_path).read_text()


def test_concurrent_resume_cannot_overwrite_active_batch(tmp_path):
    import threading
    import pytest
    paths = inputs(tmp_path)
    out = tmp_path / 'out'
    entered, release = threading.Event(), threading.Event()
    results = []
    def ocr(path, **kwargs):
        entered.set()
        assert release.wait(3)
        return OcrResult('Protected result.', 'vision')
    with mock.patch.object(converters, 'ocr_image', side_effect=ocr):
        worker = threading.Thread(target=lambda: results.append(converters.convert_image_folder_quotes(paths, out)))
        worker.start()
        assert entered.wait(3)
        try:
            with pytest.raises(RuntimeError, match='Another conversion'):
                converters.convert_image_folder_quotes(paths, out)
        finally:
            release.set()
            worker.join(3)
    assert not worker.is_alive()
    assert results[0].success


def test_corrupt_record_is_skipped_in_recovery(tmp_path):
    from quote_checkpoint import recovery_checkpoints
    paths = inputs(tmp_path)
    out = tmp_path / 'out'
    with mock.patch.object(converters, 'ocr_image', side_effect=[OcrResult('Saved.', 'vision'), OcrCancelled()]):
        first = converters.convert_image_folder_quotes(paths, out)
    report = Path(first.output_path).with_suffix('.progress.json')
    data = json.loads(report.read_text())
    del data['items'][0]['fingerprint']
    report.write_text(json.dumps(data))
    assert list(recovery_checkpoints(out)) == []
    with mock.patch.object(converters, 'ocr_image', return_value=OcrResult('Fresh.', 'vision')):
        assert converters.convert_image_folder_quotes(paths, out).success


def test_checkpoint_paths_are_independent_of_working_directory(tmp_path, monkeypatch):
    paths = inputs(tmp_path)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / 'out'
    with mock.patch.object(converters, 'ocr_image', side_effect=[OcrResult('Saved.', 'vision'), OcrCancelled()]):
        first = converters.convert_image_folder_quotes(['a.jpg','b.jpg','c.jpg'], out)
    monkeypatch.chdir(tmp_path.parent)
    with mock.patch.object(converters, 'ocr_image', return_value=OcrResult('Next.', 'vision')) as read:
        result = converters.convert_image_folder_quotes(paths, out)
    assert result.output_path == first.output_path
    assert all(call.args[0].is_absolute() for call in read.call_args_list)


def test_vault_failure_offers_finish_without_repeating_ocr(tmp_path):
    from quote_checkpoint import recovery_checkpoints
    import pytest
    paths = inputs(tmp_path)
    out, vault = tmp_path / 'out', tmp_path / 'vault'
    original = converters.atomic_write_text
    def fail_vault(path, text):
        if vault in path.parents:
            raise OSError('Vault unavailable')
        original(path, text)
    with mock.patch.object(converters, 'ocr_image', return_value=OcrResult('Saved.', 'vision')), mock.patch.object(converters, 'atomic_write_text', side_effect=fail_vault), pytest.raises(OSError):
        converters.convert_image_folder_quotes(paths, out, vault)
    assert len(list(recovery_checkpoints(out))) == 1
    with mock.patch.object(converters, 'ocr_image') as read:
        result = converters.convert_image_folder_quotes(paths, out)
    read.assert_not_called()
    assert result.success
    assert len(list((vault / 'quotes').glob('*.md'))) == 1
    assert list(recovery_checkpoints(out)) == []
