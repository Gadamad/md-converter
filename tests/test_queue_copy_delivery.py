from pathlib import Path
import sys
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from queue_store import QueueStore
from queue_runner import QueueRunner


def setup(tmp_path, *, workbook=False):
    store = QueueStore(tmp_path / 'queues.sqlite3')
    source = tmp_path / ('book.xlsx' if workbook else 'document.txt')
    source.write_bytes(b'original source')
    store.add_items(store.active_id, [{'kind': 'file', 'source': str(source), 'title': source.name}])
    output = tmp_path / 'output'
    copy = output / 'Árvíztűrő gyűjtemény'
    options = {'output_dir': str(output), 'vault_dir': None, 'raw_ocr_mode': 'different', 'copy_dir': str(copy)}
    calls = []
    def route(path, base, vault, **kwargs):
        calls.append(path)
        if workbook:
            produced = base / 'spreadsheets' / 'book'
            produced.mkdir(parents=True)
            (produced / 'one.md').write_bytes('Első munkalap: őűöüáéíóú.\n'.encode())
            (produced / 'two.md').write_text('Second worksheet.\n')
        else:
            produced = base / 'txt' / 'document.md'
            produced.parent.mkdir(parents=True)
            produced.write_bytes('Árvíztűrő tükörfúrógép.\r\n'.encode())
        return SimpleNamespace(success=True, output_path=str(produced), word_count=2, message='Saved')
    def runner(new_options=None):
        return QueueRunner(store, tmp_path / 'cache', new_options or options, route_fn=route)
    return store, source, output, copy, calls, runner


@pytest.mark.parametrize('workbook', [False, True])
def test_extra_copy_preserves_exact_outputs_format_and_workbook_structure(tmp_path, workbook):
    store, source, output, copied, calls, runner = setup(tmp_path, workbook=workbook)
    state = runner().run(store.active_id)
    assert state['done'] == 1 and len(calls) == 1
    item = state['items'][0]
    path = Path(item['output_path'])
    outputs = sorted(path.glob('*.md')) if path.is_dir() else [path]
    for exported in outputs:
        target = copied / exported.relative_to(output)
        assert target.read_bytes() == exported.read_bytes()
    assert source.read_bytes() == b'original source'


def test_copy_failure_keeps_primary_and_retry_uses_saved_conversion_and_frozen_destination(tmp_path):
    store, source, output, copied, calls, runner = setup(tmp_path)
    output.mkdir(exist_ok=True)
    copied.write_text('A file occupies the requested folder')
    state = runner().run(store.active_id)
    assert state['failed'] == 1
    item = state['items'][0]
    assert Path(item['output_path']).is_file()
    primary = Path(item['output_path']).read_bytes()
    assert 'saved' in item['error'].lower() and 'copy' in item['error'].lower()
    copied.unlink()
    different_options = {**item['options'], 'copy_dir': str(output / 'Different folder')}
    state = runner(different_options).run(store.active_id, retry_failed=True)
    assert state['done'] == 1 and len(calls) == 1
    target = copied / Path(item['output_path']).relative_to(output)
    assert target.read_bytes() == primary
    assert not (output / 'Different folder').exists()


def test_partial_workbook_copy_retries_same_files_without_converting_again(tmp_path):
    store, source, output, copied, calls, runner = setup(tmp_path, workbook=True)
    import output_copy
    actual = output_copy.atomic_copy_file
    attempts = []
    def fail_second(source, target, **kwargs):
        attempts.append(target)
        if len(attempts) == 2:
            raise OSError('Copy disk is full')
        return actual(source, target, **kwargs)
    with mock.patch.object(output_copy, 'atomic_copy_file', side_effect=fail_second):
        state = runner().run(store.active_id)
    assert state['failed'] == 1 and len(calls) == 1
    state = runner().run(store.active_id, retry_failed=True)
    assert state['done'] == 1 and len(calls) == 1
    assert len(list(copied.rglob('*.md'))) == 2


def test_image_copy_failure_keeps_recognized_text_and_retry_avoids_ocr(tmp_path, monkeypatch):
    import converters
    from image_ocr import OcrResult
    from quote_checkpoint import QuoteCheckpoint
    source = tmp_path / 'original.jpg'
    source.write_bytes(b'original image fixture')
    output = tmp_path / 'output'
    output.mkdir()
    copied = output / 'Named collection'
    copied.write_text('File occupies the requested folder')
    store = QueueStore(tmp_path / 'queues.sqlite3')
    store.add_items(store.active_id, [{'kind': 'file', 'source': str(source), 'title': source.name}])
    options = {'output_dir': str(output), 'copy_dir': str(copied), 'vault_dir': None, 'raw_ocr_mode': 'different'}
    recognized = mock.Mock(return_value=OcrResult('Őszintén őrizd meg az értékeidet.', 'vision'))
    monkeypatch.setattr(converters, 'ocr_image', recognized)
    runner = lambda: QueueRunner(store, tmp_path / 'cache', options)
    state = runner().run(store.active_id)
    item = state['items'][0]
    assert state['failed'] == 1 and recognized.call_count == 1
    assert 'Őszintén' in Path(item['output_path']).read_text()
    checkpoint = QuoteCheckpoint.load(Path(item['checkpoint_path']))
    assert checkpoint.items[0]['status'] == 'success'
    copied.unlink()
    state = runner().run(store.active_id, retry_failed=True)
    assert state['done'] == 1 and recognized.call_count == 1
    target = copied / Path(item['output_path']).relative_to(output)
    assert target.read_bytes() == Path(item['output_path']).read_bytes()
    assert source.read_bytes() == b'original image fixture'


def test_copy_failure_and_repair_preserve_image_review_decisions(tmp_path, monkeypatch):
    import converters
    from image_ocr import OcrResult, OcrNoTextDetected
    from quote_checkpoint import is_review_failure
    store = QueueStore(tmp_path / 'queues.sqlite3')
    images = [tmp_path / 'good.jpg', tmp_path / 'review.jpg']
    for image in images:
        image.write_bytes(b'original image')
    store.add_items(store.active_id, [{'kind': 'file', 'source': str(image), 'title': image.name} for image in images])
    output = tmp_path / 'output'
    output.mkdir()
    copied = output / 'Named collection'
    copied.write_bytes(b'occupied folder')
    recognized = mock.Mock(side_effect=[OcrResult('Őszintén őrizd meg az értékeidet.', 'vision'),
                                       OcrNoTextDetected('No text')])
    monkeypatch.setattr(converters, 'ocr_image', recognized)
    runner = lambda: QueueRunner(store, tmp_path / 'cache',
        {'output_dir': str(output), 'copy_dir': str(copied), 'vault_dir': None, 'raw_ocr_mode': 'different'})
    state = runner().run(store.active_id)
    review = next(item for item in state['items'] if item['title'] == 'review.jpg')
    assert is_review_failure(review), 'Copy failure must preserve the image review reason'
    copied.unlink()
    state = runner().run(store.active_id, retry_failed=True)
    assert state['done'] == 1 and recognized.call_count == 2
    review = next(item for item in state['items'] if item['title'] == 'review.jpg')
    assert is_review_failure(review)


def test_stopped_batch_copy_failure_keeps_unattempted_images_waiting(tmp_path, monkeypatch):
    import converters
    from image_ocr import OcrResult
    store = QueueStore(tmp_path / 'queues.sqlite3')
    images = [tmp_path / 'a.jpg', tmp_path / 'b.jpg']
    for image in images:
        image.write_bytes(b'original image')
    store.add_items(store.active_id, [{'kind': 'file', 'source': str(image), 'title': image.name} for image in images])
    output = tmp_path / 'output'
    output.mkdir()
    copied = output / 'Named collection'
    copied.write_bytes(b'occupied folder')
    options = {'output_dir': str(output), 'copy_dir': str(copied), 'vault_dir': None, 'raw_ocr_mode': 'different'}
    recognized = mock.Mock(return_value=OcrResult('Őszintén őrizd meg az értékeidet.', 'vision'))
    monkeypatch.setattr(converters, 'ocr_image', recognized)
    stopped = False
    progress = []
    def stop_after_first(completed, total):
        nonlocal stopped
        progress.append((completed, total))
        stopped = True
    runner = QueueRunner(store, tmp_path / 'cache', options,
                         should_cancel=lambda: stopped, on_item_processed=stop_after_first)
    state = runner.run(store.active_id)
    assert state['failed'] == 1 and state['waiting'] == 1 and recognized.call_count == 1
    assert progress == [(1, 2)]
    copied.unlink()
    state = QueueRunner(store, tmp_path / 'cache', options).run(store.active_id, retry_failed=True)
    assert state['done'] == 1 and state['waiting'] == 1 and recognized.call_count == 1
    state = QueueRunner(store, tmp_path / 'cache', options).run(store.active_id)
    assert state['done'] == 2 and recognized.call_count == 2
    assert len(list(copied.rglob('*.md'))) == 1
