"""The chosen existing root stays frozen across saved conversions and OCR repair."""
import json
from pathlib import Path
from unittest import mock

import pytest

from test_queue_copy_delivery import setup
from queue_store import QueueStore
from queue_runner import QueueRunner


@pytest.mark.parametrize('workbook', [False, True])
def test_queue_existing_destination_retries_saved_output_when_folder_returns(tmp_path, workbook):
    store, source, base, _, calls, runner = setup(tmp_path, workbook=workbook)
    destination = tmp_path / 'Existing collection'
    options = {'output_dir': str(base), 'copy_dir': str(destination), 'copy_mode': 'existing',
               'raw_ocr_mode': 'different', 'vault_dir': None}
    failed = runner(options).run(store.active_id)
    item = failed['items'][0]
    primary = Path(item['output_path'])
    exports = sorted(primary.glob('*.md')) if primary.is_dir() else [primary]
    saved = {path: path.read_bytes() for path in exports}
    assert failed['failed'] == 1 and len(calls) == 1
    assert not destination.exists(), 'Do not silently recreate a missing selected root'
    source.unlink()
    destination.mkdir()
    different = {**options, 'copy_dir': str(base / 'Later name'), 'copy_mode': 'subfolder'}
    finished = runner(different).run(store.active_id, retry_failed=True)
    assert finished['done'] == 1 and len(calls) == 1
    for path, content in saved.items():
        assert path.read_bytes() == content
        assert (destination / path.relative_to(base)).read_bytes() == content
    assert not (base / 'Later name').exists()


def test_image_existing_folder_failure_keeps_text_and_retries_without_ocr(tmp_path, monkeypatch):
    import converters
    from image_ocr import OcrResult
    from quote_checkpoint import QuoteCheckpoint
    image = tmp_path / 'source.jpg'
    image.write_bytes(b'original image')
    store = QueueStore(tmp_path / 'queues.sqlite3')
    store.add_items(store.active_id, [{'kind': 'file', 'source': str(image), 'title': image.name}])
    base, destination = tmp_path / 'output', tmp_path / 'Existing collection'
    options = {'output_dir': str(base), 'copy_dir': str(destination), 'copy_mode': 'existing',
               'raw_ocr_mode': 'different', 'vault_dir': None}
    recognized = mock.Mock(return_value=OcrResult('Őszintén őrizd meg az értékeidet.', 'vision'))
    monkeypatch.setattr(converters, 'ocr_image', recognized)
    failed = QueueRunner(store, tmp_path / 'cache', options).run(store.active_id)
    item = failed['items'][0]
    assert failed['failed'] == 1 and recognized.call_count == 1
    primary = Path(item['output_path'])
    assert 'Őszintén' in primary.read_text()
    journal = QuoteCheckpoint.load(Path(item['checkpoint_path']))
    assert journal.report['copy_mode'] == 'existing'
    assert journal.items[0]['status'] == 'success'
    assert not destination.exists()
    destination.mkdir()
    finished = QueueRunner(store, tmp_path / 'cache',
        {**options, 'copy_dir': str(base / 'Different'), 'copy_mode': 'subfolder'}).run(store.active_id, retry_failed=True)
    assert finished['done'] == 1 and recognized.call_count == 1
    assert (destination / primary.relative_to(base)).read_bytes() == primary.read_bytes()
    assert not (base / 'Different').exists()
    assert image.read_bytes() == b'original image'


def test_changed_image_journal_destination_cannot_redirect_frozen_delivery(tmp_path, monkeypatch):
    import converters
    from image_ocr import OcrResult
    image = tmp_path / 'source.jpg'
    image.write_bytes(b'original image')
    store = QueueStore(tmp_path / 'queues.sqlite3')
    store.add_items(store.active_id, [{'kind': 'file', 'source': str(image), 'title': image.name}])
    base, destination = tmp_path / 'output', tmp_path / 'Missing selected collection'
    options = {'output_dir': str(base), 'copy_dir': str(destination), 'copy_mode': 'existing',
               'raw_ocr_mode': 'different', 'vault_dir': None}
    recognized = mock.Mock(return_value=OcrResult('Őszintén őrizd meg az értékeidet.', 'vision'))
    monkeypatch.setattr(converters, 'ocr_image', recognized)
    failed = QueueRunner(store, tmp_path / 'cache', options).run(store.active_id)
    item = failed['items'][0]
    journal_path = Path(item['checkpoint_path'])
    report = json.loads(journal_path.read_text())
    other = tmp_path / 'Unselected'
    other.mkdir()
    report.update(copy_dir=str(other), copy_mode='existing')
    journal_path.write_text(json.dumps(report))
    failed_again = QueueRunner(store, tmp_path / 'cache', options).run(store.active_id, retry_failed=True)
    assert failed_again['failed'] == 1 and recognized.call_count == 1
    assert not list(other.iterdir())
    assert 'destination' in failed_again['items'][0]['error'].lower()
