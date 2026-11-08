"""Publish incomplete PDFs and recover only unresolved pages of the saved book."""
import io
import json
from pathlib import Path
import sys
from unittest import mock
from uuid import uuid4

import pymupdf as fitz
from PIL import Image
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import converters
from image_ocr import OcrNoTextDetected
from queue_runner import QueueRunner
from queue_store import QueueStore


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'Test book.pdf'
    image = io.BytesIO()
    Image.new('RGB', (32, 32), 'grey').save(image, 'PNG')
    with fitz.open() as pdf:
        pdf.new_page().insert_text((40, 50), 'First selectable page.')
        pdf.new_page().insert_image(fitz.Rect(30, 40, 200, 200), stream=image.getvalue())
        pdf.new_page().insert_text((40, 50), 'Third page remains intact.')
        pdf.new_page().insert_image(fitz.Rect(30, 40, 200, 200), stream=image.getvalue())
        pdf.save(path)
    store = QueueStore(tmp_path / 'queues.sqlite3')
    store.add_items(store.active_id, [dict(kind='file', source=str(path), title=path.name)])
    options = {'output_dir': str(tmp_path / 'out'), 'vault_dir': str(tmp_path / 'vault'),
               'raw_ocr_mode': 'different', 'copy_dir': str(tmp_path / 'out' / 'Copies')}
    return path, store, options, tmp_path / 'cache'


def run(book, *, retry=False, **kwargs):
    _, store, options, cache = book
    return QueueRunner(store, cache, options, **kwargs).run(store.active_id, retry_failed=retry)['items'][0]


def blocked(page, **kwargs):
    raise OcrNoTextDetected('tesseract returned no text')


def make_legacy_partial(book):
    source, store, options, cache = book
    item = store.items(store.active_id)[0]
    work = cache / item['id'] / uuid4().hex
    with mock.patch.object(converters, '_ocr_pdf_page', side_effect=blocked):
        result = converters.convert_pdf(str(source), work / 'converted' / 'pdf')
    assert not result.success and 'OCR failed on pages [2, 4]' in result.message
    store.update_item(item['id'], status='failed', error=result.message,
                      receipt_path=str(work / 'receipt.json'), options=options)
    return Path(result.output_path)


def test_first_partial_publishes_warning_to_configured_destinations(book, monkeypatch):
    _, _, options, _ = book
    monkeypatch.setattr(converters, '_ocr_pdf_page', blocked)
    item = run(book)
    assert item['status'] == 'failed' and item['error'].startswith('Partial PDF:')
    target = Path(item['output_path'])
    assert target.parent == Path(options['output_dir']) / 'pdf'
    body = target.read_text()
    assert 'First selectable page.' in body and 'Third page remains intact.' in body
    assert 'Incomplete PDF' in body and '2, 4' in body
    assert Path(options['copy_dir'], 'pdf', target.name).read_bytes() == target.read_bytes()
    assert body in Path(options['vault_dir'], 'pdf', target.name).read_text()


def test_retry_uses_saved_pages_and_keeps_old_partial_and_unrelated_files(book, monkeypatch):
    import pdf_page_ocr
    _, _, options, _ = book
    monkeypatch.setattr(converters, '_ocr_pdf_page', blocked)
    item = run(book)
    partial = Path(item['output_path'])
    partial.write_text('User edited this partial.')
    unrelated = partial.parent / 'unrelated.md'
    unrelated.write_text('Keep my prior conversion.')
    calls = []
    def recovery(page, **kwargs):
        calls.append(page.number + 1)
        if page.number == 3:
            raise OcrNoTextDetected('still unreadable')
        return 'Recovered second page.'
    monkeypatch.setattr(pdf_page_ocr, 'recover_pdf_page', recovery)
    item = run(book, retry=True)
    assert calls == [2, 4] and item['status'] == 'failed'
    assert 'Recovered second page.' in Path(item['output_path']).read_text()
    assert Path(item['output_path']) != partial
    def finish(page, **kwargs):
        calls.append(page.number + 1)
        return 'Recovered fourth page.'
    monkeypatch.setattr(pdf_page_ocr, 'recover_pdf_page', finish)
    item = run(book, retry=True)
    assert calls == [2, 4, 4] and item['status'] == 'done'
    body = Path(item['output_path']).read_text()
    assert body.index('First selectable') < body.index('Recovered second') < body.index('Third page') < body.index('Recovered fourth')
    assert '**Warning**:' not in body
    assert partial.read_text() == 'User edited this partial.'
    assert unrelated.read_text() == 'Keep my prior conversion.'
    assert Path(options['copy_dir'], 'pdf', Path(item['output_path']).name).read_bytes() == Path(item['output_path']).read_bytes()


def test_imports_real_legacy_output_without_rerunning_successful_pages(book, monkeypatch):
    import pdf_page_ocr
    legacy = make_legacy_partial(book)
    original = legacy.read_bytes()
    calls = []
    def recover(page, **kwargs):
        calls.append(page.number + 1)
        return f'Recovered PDF page {page.number + 1}.'
    monkeypatch.setattr(pdf_page_ocr, 'recover_pdf_page', recover)
    monkeypatch.setattr(converters, '_ocr_pdf_page', lambda *a, **k: pytest.fail('Legacy retry must use targeted OCR'))
    item = run(book, retry=True)
    assert calls == [2, 4] and item['status'] == 'done', item['error']
    assert 'Third page remains intact.' in Path(item['output_path']).read_text()
    assert legacy.read_bytes() == original


def test_missing_legacy_partial_does_not_restart_whole_book(book, monkeypatch):
    legacy = make_legacy_partial(book)
    legacy.unlink()
    monkeypatch.setattr(converters, '_ocr_pdf_page', lambda *a, **k: pytest.fail('Do not restart whole PDF'))
    item = run(book, retry=True)
    assert item['status'] == 'failed' and not item['output_path']
    assert 'partial' in item['error'].lower()


def test_failed_copy_retry_uses_snapshot_before_more_ocr(book, monkeypatch):
    _, _, options, _ = book
    destination = Path(options['copy_dir'])
    destination.parent.mkdir()
    destination.write_text('Folder unavailable')
    monkeypatch.setattr(converters, '_ocr_pdf_page', blocked)
    item = run(book)
    primary = Path(item['output_path'])
    original = primary.read_bytes()
    assert item['status'] == 'failed' and item['error'].startswith('Partial PDF:')
    destination.unlink()
    import pdf_page_ocr
    monkeypatch.setattr(pdf_page_ocr, 'recover_pdf_page', lambda *a, **k: pytest.fail('Delivery retry must not OCR'))
    item = run(book, retry=True)
    assert item['status'] == 'failed' and item['error'].startswith('Partial PDF:')
    assert Path(item['output_path']) == primary and primary.read_bytes() == original
    assert Path(destination, 'pdf', primary.name).read_bytes() == original


def test_partial_remains_available_if_source_is_moved(book, monkeypatch):
    source, _, _, _ = book
    monkeypatch.setattr(converters, '_ocr_pdf_page', blocked)
    item = run(book)
    partial = Path(item['output_path'])
    original = partial.read_bytes()
    source.rename(source.with_name('Moved.pdf'))
    item = run(book, retry=True)
    assert item['status'] == 'failed' and item['error'].startswith('Partial PDF:')
    assert 'use Locate file' in item['error']
    assert Path(item['output_path']) == partial and partial.read_bytes() == original


def test_partial_receipt_cannot_publish_as_complete_after_metadata_damage(book, monkeypatch):
    monkeypatch.setattr(converters, '_ocr_pdf_page', blocked)
    item = run(book)
    receipt = Path(item['receipt_path'])
    data = json.loads(receipt.read_text())
    receipt.write_text(json.dumps({**data, 'pdf_failed_pages': [], 'pdf_delivery_pending': True}))
    retried = run(book, retry=True)
    assert retried['status'] == 'failed' and 'snapshot' in retried['error'].lower()
    assert retried['output_path'] == item['output_path']


def test_vault_delivery_does_not_reuse_unverified_derived_cache(book, monkeypatch):
    _, _, options, _ = book
    bad_vault = Path(options['vault_dir'])
    bad_vault.write_text('Temporarily unavailable')
    monkeypatch.setattr(converters, '_ocr_pdf_page', blocked)
    item = run(book)
    assert item['status'] == 'failed'
    target = Path(item['output_path'])
    cache = Path(item['receipt_path']).parent / 'pdf-snapshots'
    derived, = cache.glob('vault-*.md')
    derived.write_text('Unrelated derived cache text.')
    bad_vault.unlink()
    item = run(book, retry=True)
    assert target.read_text() in (bad_vault / 'pdf' / target.name).read_text()


def test_old_completed_receipt_retry_preserves_user_edited_primary(book, monkeypatch):
    source, store, options, cache = book
    item = store.items(store.active_id)[0]
    work = cache / item['id'] / uuid4().hex
    monkeypatch.setattr(converters, '_ocr_pdf_page', lambda *a, **k: 'Previously saved scanned page.')
    result = converters.convert_pdf(str(source), work / 'converted' / 'pdf')
    private = Path(result.output_path)
    receipt = work / 'receipt.json'
    receipt.write_text(json.dumps({'source_output': str(private), 'word_count': result.word_count,
                                   'format': 'pdf', 'filename': private.name}))
    primary = Path(options['output_dir']) / 'pdf' / f"{private.stem}_{item['id'][:12]}.md"
    primary.parent.mkdir(parents=True)
    primary.write_text('User edited the saved export.')
    store.update_item(item['id'], status='failed', error='Extra copy failed', output_path=str(primary),
                      receipt_path=str(receipt), options=options)
    source.unlink()
    retried = run(book, retry=True)
    assert retried['status'] == 'done', retried['error']
    assert primary.read_text() == 'User edited the saved export.'
    assert Path(retried['output_path']).read_bytes() == private.read_bytes()
