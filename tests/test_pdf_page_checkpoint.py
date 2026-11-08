"""Exercise queued PDF recovery with real PDFs and controlled OCR outcomes."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import converters
from pdf_recovery import PdfRecoveryError, convert_queued_pdf


def make_pdf(path, pages):
    with pymupdf.open() as doc:
        for content in pages:
            page = doc.new_page()
            if content == 'scan':
                page.draw_rect(pymupdf.Rect(40, 40, 200, 200))
            elif content:
                page.insert_text((70, 70), content)
        doc.save(path)
    return path


def set_ocr(monkeypatch, *, initial, recovery):
    monkeypatch.setattr(converters, '_ocr_pdf_page', initial)
    monkeypatch.setitem(sys.modules, 'pdf_page_ocr', SimpleNamespace(recover_pdf_page=recovery))


def forbidden_ocr(*_args, **_kwargs):
    pytest.fail('An already completed page or a page outside the retry set was OCRed')


@pytest.mark.parametrize('entry', ['pdf-progress.json', 'pdf-snapshots'])
def test_recovery_rejects_linked_cache_entries(tmp_path, entry):
    pdf = make_pdf(tmp_path / 'example.pdf', ['Opening words'])
    other = tmp_path / 'other-attempt'
    convert_queued_pdf(pdf, other)
    work = tmp_path / 'attempt'
    work.mkdir()
    (work / entry).symlink_to(other / entry)
    before = {p.relative_to(other): p.read_bytes() for p in other.rglob('*') if p.is_file()}
    with pytest.raises(PdfRecoveryError, match='symbolic link'):
        convert_queued_pdf(pdf, work)
    assert {p.relative_to(other): p.read_bytes() for p in other.rglob('*') if p.is_file()} == before


def test_retry_only_failed_pages_and_preserve_immutable_previous_export(tmp_path, monkeypatch):
    pdf = make_pdf(tmp_path / 'example.pdf', ['Opening words', 'scan', 'scan', 'Closing words'])
    work = tmp_path / 'attempt'
    initial_calls, recovery_calls = [], []

    def initial(page, *, should_cancel):
        initial_calls.append(page.number + 1)
        if page.number == 1:
            raise RuntimeError('OCR deadline')
        return 'Saved scan'

    def recovery(page, *, should_cancel):
        recovery_calls.append(page.number + 1)
        return 'Recovered scan'

    set_ocr(monkeypatch, initial=initial, recovery=recovery)
    first = convert_queued_pdf(pdf, work)
    assert not first.canceled
    assert first.failed_pages == (2,)
    assert first.word_count == 6
    first_content = first.output_path.read_bytes()
    first_text = first_content.decode()
    assert 'incomplete' in first_text.lower()
    assert 'page 2' in first_text.lower()
    assert 'OCR deadline' in first_text
    assert first_text.index('Opening words') < first_text.index('Saved scan') < first_text.index('Closing words')
    assert initial_calls == [2, 3]
    assert recovery_calls == []

    second = convert_queued_pdf(pdf, work)
    assert second.failed_pages == ()
    assert second.word_count == 8
    assert initial_calls == [2, 3]
    assert recovery_calls == [2]
    assert second.output_path != first.output_path
    assert first.output_path.read_bytes() == first_content
    text = second.output_path.read_text(encoding='utf-8')
    assert 'incomplete' not in text.lower()
    assert 'OCR deadline' not in text
    assert text.index('Opening words') < text.index('Recovered scan') < text.index('Saved scan') < text.index('Closing words')

    third = convert_queued_pdf(pdf, work)
    assert third.output_path == second.output_path
    assert recovery_calls == [2]


def test_cancel_during_initial_ocr_resumes_pending_pages_with_normal_ocr(tmp_path, monkeypatch):
    pdf = make_pdf(tmp_path / 'book.pdf', ['Page one', 'scan', 'scan'])
    work = tmp_path / 'attempt'
    calls = []

    def initial(page, *, should_cancel):
        calls.append(page.number + 1)
        if calls == [2, 3]:
            raise converters.OcrCancelled('stop after saving page two')
        return f'OCR page {page.number + 1}'

    set_ocr(monkeypatch, initial=initial, recovery=forbidden_ocr)
    first = convert_queued_pdf(pdf, work)
    assert first.canceled and first.output_path is None
    assert first.failed_pages == ()
    assert (work / 'pdf-progress.json').is_file()

    final = convert_queued_pdf(pdf, work)
    assert calls == [2, 3, 3]
    assert not final.canceled and final.failed_pages == ()
    assert 'OCR page 2' in final.output_path.read_text(encoding='utf-8')
    assert 'OCR page 3' in final.output_path.read_text(encoding='utf-8')


def test_canceled_recovery_stays_failed_until_successful_retry(tmp_path, monkeypatch):
    pdf = make_pdf(tmp_path / 'book.pdf', ['Text cover', 'scan'])
    work = tmp_path / 'attempt'

    def fail_initial(*_args, **_kwargs):
        raise RuntimeError('initial OCR failed')

    def cancel_recovery(*_args, **_kwargs):
        raise converters.OcrCancelled('stop retry')

    set_ocr(monkeypatch, initial=fail_initial, recovery=cancel_recovery)
    first = convert_queued_pdf(pdf, work)
    canceled = convert_queued_pdf(pdf, work)
    assert canceled.canceled and canceled.output_path is None
    assert canceled.failed_pages == (2,)
    assert 'initial OCR failed' in first.output_path.read_text(encoding='utf-8')

    set_ocr(monkeypatch, initial=forbidden_ocr, recovery=lambda *_a, **_k: 'Recovered body')
    assert convert_queued_pdf(pdf, work).failed_pages == ()


def test_resume_after_interruption_reuses_saved_pages(tmp_path, monkeypatch):
    pdf = make_pdf(tmp_path / 'book.pdf', ['scan', 'scan'])
    work = tmp_path / 'attempt'
    calls = []

    def initial(page, *, should_cancel):
        calls.append(page.number + 1)
        if calls == [1, 2]:
            raise KeyboardInterrupt
        return f'Scanned page {page.number + 1}'

    set_ocr(monkeypatch, initial=initial, recovery=forbidden_ocr)
    with pytest.raises(KeyboardInterrupt):
        convert_queued_pdf(pdf, work)
    result = convert_queued_pdf(pdf, work)
    assert calls == [1, 2, 2]
    assert result.word_count == 6


def test_source_content_change_with_same_name_and_mtime_is_rejected(tmp_path, monkeypatch):
    pdf = make_pdf(tmp_path / 'book.pdf', ['Original text', 'scan'])
    work = tmp_path / 'attempt'

    def initial(*_a, **_k):
        raise RuntimeError('initial error')

    set_ocr(monkeypatch, initial=initial, recovery=forbidden_ocr)
    first = convert_queued_pdf(pdf, work)
    old_stat = pdf.stat()
    replacement = make_pdf(tmp_path / 'replacement.pdf', ['Modified text', 'scan'])
    replacement.replace(pdf)
    os.utime(pdf, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    with pytest.raises(PdfRecoveryError, match='(?i)source.*chang'):
        convert_queued_pdf(pdf, work)
    assert 'Original text' in first.output_path.read_text(encoding='utf-8')


def test_source_replaced_during_ocr_does_not_commit_new_text(tmp_path, monkeypatch):
    pdf = make_pdf(tmp_path / 'book.pdf', ['Saved opening', 'scan'])
    replacement = make_pdf(tmp_path / 'replacement.pdf', ['Changed opening', 'scan'])
    work = tmp_path / 'attempt'

    def initial(*_a, **_k):
        replacement.replace(pdf)
        return 'Do not save this page'

    set_ocr(monkeypatch, initial=initial, recovery=forbidden_ocr)
    with pytest.raises(PdfRecoveryError, match='(?i)source.*chang'):
        convert_queued_pdf(pdf, work)
    assert 'Do not save this page' not in (work / 'pdf-progress.json').read_text(encoding='utf-8')


@pytest.mark.parametrize('corrupt', ['{invalid', '[]', '{"schema":999}', '{"schema":true}'])
def test_corrupt_checkpoint_never_restarts_whole_pdf(tmp_path, monkeypatch, corrupt):
    pdf = make_pdf(tmp_path / 'book.pdf', ['scan'])
    work = tmp_path / 'attempt'
    work.mkdir()
    state = work / 'pdf-progress.json'
    state.write_text(corrupt, encoding='utf-8')
    set_ocr(monkeypatch, initial=forbidden_ocr, recovery=forbidden_ocr)
    with pytest.raises(PdfRecoveryError, match='(?i)checkpoint'):
        convert_queued_pdf(pdf, work)
    assert state.read_text(encoding='utf-8') == corrupt


def legacy_fixture(tmp_path):
    work = tmp_path / 'attempt'
    pages = [None] * 192
    for number in (4, 110, 190):
        pages[number - 1] = 'scan'
    pdf = make_pdf(tmp_path / 'Book.pdf', pages)
    legacy = work / 'converted' / 'pdf' / 'book.md'
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        '# Book\n\n> **Source**: `Book.pdf`  \n> **Pages**: 192  \n> **Word Count**: 9  \n\n---\n'
        '## Page 1\nAlready extracted opening\n\n'
        '## Page 4\nOCR failed: worker timeout\n\n'
        '## Page 110\nOCR failed: worker timeout\n\n'
        '## Page 189\nAlready extracted middle\n\n'
        '## Page 190\nOCR failed: worker timeout\n\n'
        '## Page 192\nAlready extracted ending\n\n',
        encoding='utf-8',
    )
    return pdf, work, legacy


def test_legacy_partial_retries_only_4_110_190_and_preserves_prior_text(tmp_path, monkeypatch):
    pdf, work, legacy = legacy_fixture(tmp_path)
    original = legacy.read_bytes()
    calls = []

    def recovery(page, *, should_cancel):
        calls.append(page.number + 1)
        return f'Recovered {page.number + 1}'

    set_ocr(monkeypatch, initial=forbidden_ocr, recovery=recovery)
    result = convert_queued_pdf(pdf, work, legacy_output=legacy, legacy_failed_pages=(4, 110, 190))
    assert calls == [4, 110, 190]
    assert result.failed_pages == ()
    assert result.word_count == 15
    assert legacy.read_bytes() == original
    assert result.output_path != legacy
    text = result.output_path.read_text(encoding='utf-8')
    assert text.index('Already extracted opening') < text.index('Recovered 4') < text.index('Recovered 110')
    assert text.index('Recovered 110') < text.index('Already extracted middle') < text.index('Recovered 190')
    assert text.index('Recovered 190') < text.index('Already extracted ending')
    assert 'OCR failed' not in text


@pytest.mark.parametrize('mutation', ['stale', 'restored mtime', 'source', 'pages', 'words', 'failed marker', 'outside', 'ambiguous page', 'unordered failed'])
def test_legacy_ambiguity_or_staleness_is_rejected_before_ocr(tmp_path, monkeypatch, mutation):
    pdf, work, legacy = legacy_fixture(tmp_path)
    original = legacy.read_text(encoding='utf-8')
    failed_pages = (4, 110, 190)
    if mutation == 'stale':
        before_source = pdf.stat().st_mtime_ns - 1_000_000_000
        os.utime(legacy, ns=(before_source, before_source))
    elif mutation == 'restored mtime':
        previous = pdf.stat()
        pdf.write_bytes(pdf.read_bytes() + b'\n')
        os.utime(pdf, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    elif mutation == 'outside':
        elsewhere = tmp_path / 'private.md'
        legacy.replace(elsewhere)
        legacy = elsewhere
    elif mutation == 'unordered failed':
        failed_pages = (190, 4, 110)
    else:
        replacements = {
            'source': ('Book.pdf', 'Other.pdf'),
            'pages': ('**Pages**: 192', '**Pages**: 191'),
            'words': ('**Word Count**: 9', '**Word Count**: 8'),
            'failed marker': ('## Page 190\nOCR failed:', '## Page 190\nExpected body:'),
            'ambiguous page': ('Already extracted middle', '## Page 189\nAlready extracted middle'),
        }
        old, new = replacements[mutation]
        legacy.write_text(original.replace(old, new), encoding='utf-8')
    set_ocr(monkeypatch, initial=forbidden_ocr, recovery=forbidden_ocr)
    with pytest.raises(PdfRecoveryError, match='(?i)legacy|previous'):
        convert_queued_pdf(pdf, work, legacy_output=legacy, legacy_failed_pages=failed_pages)
    assert not (work / 'pdf-progress.json').exists()


def test_textless_pdf_without_failed_pages_is_explicit_failure(tmp_path, monkeypatch):
    pdf = make_pdf(tmp_path / 'blank.pdf', [None])
    set_ocr(monkeypatch, initial=forbidden_ocr, recovery=forbidden_ocr)
    with pytest.raises(PdfRecoveryError, match='(?i)(empty|no extractable text)'):
        convert_queued_pdf(pdf, tmp_path / 'attempt')


def test_blank_ocr_on_a_scan_stays_failed_not_a_successful_empty_page(tmp_path, monkeypatch):
    pdf = make_pdf(tmp_path / 'image.pdf', ['scan'])
    set_ocr(monkeypatch, initial=lambda *_a, **_k: '  ', recovery=forbidden_ocr)
    result = convert_queued_pdf(pdf, tmp_path / 'attempt')
    assert result.failed_pages == (1,)
    assert result.word_count == 0
    assert 'incomplete' in result.output_path.read_text(encoding='utf-8').lower()


def test_unreadable_replacement_still_reports_changed_checkpoint_source(tmp_path, monkeypatch):
    pdf = make_pdf(tmp_path / 'book.pdf', ['Saved text'])
    work = tmp_path / 'attempt'
    set_ocr(monkeypatch, initial=forbidden_ocr, recovery=forbidden_ocr)
    first = convert_queued_pdf(pdf, work)
    pdf.write_bytes(b'not a PDF anymore')
    with pytest.raises(PdfRecoveryError, match='(?i)source.*chang'):
        convert_queued_pdf(pdf, work)
    assert 'Saved text' in first.output_path.read_text(encoding='utf-8')
