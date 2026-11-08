"""Durable page recovery for queued PDFs; the ordinary PDF route stays independent."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re

import pymupdf

from file_utils import atomic_write_text
from image_ocr import OcrCancelled


_SCHEMA = 1
_PROGRESS = 'pdf-progress.json'
CancelCheck = Callable[[], bool] | None


class PdfRecoveryError(ValueError):
    """The PDF or its saved recovery data cannot safely be resumed."""


@dataclass(frozen=True)
class PdfQueueResult:
    output_path: Path | None
    word_count: int
    failed_pages: tuple[int, ...]
    canceled: bool


def _stat_signature(stat: os.stat_result) -> tuple[int, ...]:
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _ensure_source(source: Path, signature: tuple[int, ...]) -> None:
    try:
        unchanged = _stat_signature(source.stat()) == signature
    except OSError:
        unchanged = False
    if not unchanged:
        raise PdfRecoveryError('PDF source changed during conversion. Use Locate file to start again.')


def _fingerprint(source: Path, should_cancel: CancelCheck) -> tuple[tuple[int, ...], str]:
    digest = hashlib.sha256()
    with source.open('rb') as stream:
        signature = _stat_signature(os.fstat(stream.fileno()))
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            if should_cancel and should_cancel():
                raise OcrCancelled('PDF conversion canceled')
            digest.update(chunk)
        if _stat_signature(os.fstat(stream.fileno())) != signature:
            raise PdfRecoveryError('PDF source changed while reading its fingerprint.')
    _ensure_source(source, signature)
    return signature, digest.hexdigest()


def _save_progress(path: Path, identity: dict, pages: list[dict]) -> None:
    atomic_write_text(path, json.dumps({**identity, 'pages': pages}, ensure_ascii=False))


def _load_progress(path: Path, identity: dict) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise PdfRecoveryError('PDF page checkpoint is unreadable.') from exc
    if (not isinstance(data, dict) or type(data.get('schema')) is not int
            or data['schema'] != _SCHEMA or set(data) != {*identity, 'pages'}
            or not isinstance(data['source'], str)
            or not isinstance(data['sha256'], str)
            or re.fullmatch(r'[0-9a-f]{64}', data['sha256']) is None
            or not isinstance(data['pages'], list)):
        raise PdfRecoveryError('Invalid PDF page checkpoint.')
    if data['source'] != identity['source'] or data['sha256'] != identity['sha256']:
        raise PdfRecoveryError('PDF source changed since this checkpoint was saved. Use Locate file to start again.')
    for page in data['pages']:
        if not isinstance(page, dict):
            raise PdfRecoveryError('Invalid saved PDF page state.')
        status = page.get('status')
        valid = ((status == 'pending' and set(page) == {'status'})
                 or (status == 'done' and set(page) == {'status', 'text'} and isinstance(page['text'], str))
                 or (status == 'failed' and set(page) == {'status', 'error'}
                     and isinstance(page['error'], str) and bool(page['error'].strip())))
        if not valid:
            raise PdfRecoveryError('Invalid saved PDF page state.')
    return data['pages']


_LEGACY_PAGE = re.compile(r'^## Page ([1-9][0-9]*)\n', re.MULTILINE)
_LEGACY_ERROR = 'OCR failed: '


def _import_legacy(
    output: Path,
    source: Path,
    work_dir: Path,
    page_count: int,
    source_signature: tuple[int, ...],
    failed: tuple[int, ...],
) -> list[dict]:
    """Import exactly the generated v0.4.1 partial format, or fail closed."""
    invalid = 'Previous PDF partial export is not a verified legacy recovery file.'
    if (not isinstance(failed, tuple) or not failed
            or any(type(number) is not int or not 1 <= number <= page_count for number in failed)
            or tuple(sorted(set(failed))) != failed):
        raise PdfRecoveryError(invalid)
    folder = work_dir / 'converted' / 'pdf'
    if (output.suffix != '.md' or output.parent.absolute() != folder.absolute()
            or output.is_symlink() or output.resolve().parent != folder.absolute().resolve()
            or not output.resolve().is_relative_to(work_dir.resolve())):
        raise PdfRecoveryError(invalid)
    try:
        old_signature = _stat_signature(output.stat())
        # Legacy outputs do not contain a source digest. A newer inode change
        # also invalidates the cache when the source mtime has been restored.
        if old_signature[3] < max(source_signature[3], source_signature[4]):
            raise PdfRecoveryError('Previous PDF partial export predates the current source.')
        content = output.read_text(encoding='utf-8')
        if _stat_signature(output.stat()) != old_signature:
            raise PdfRecoveryError('Previous PDF partial export changed while reading it.')
    except (OSError, UnicodeError) as exc:
        raise PdfRecoveryError(invalid) from exc

    prefix = (f'# {source.stem}\n\n> **Source**: `{source.name}`  \n'
              f'> **Pages**: {page_count}  \n> **Word Count**: ')
    if not content.startswith(prefix):
        raise PdfRecoveryError(invalid)
    header = re.match(r'([0-9][0-9,]*)  \n\n---\n', content[len(prefix):])
    if header is None:
        raise PdfRecoveryError(invalid)
    body = content[len(prefix) + header.end():]
    headings = list(_LEGACY_PAGE.finditer(body))
    if not headings or headings[0].start() != 0:
        raise PdfRecoveryError(invalid)
    pages = [{'status': 'done', 'text': ''} for _ in range(page_count)]
    failed_set = set(failed)
    seen_failed = []
    previous, words = 0, 0
    for index, heading in enumerate(headings):
        try:
            number = int(heading[1])
        except ValueError as exc:
            raise PdfRecoveryError(invalid) from exc
        if not previous < number <= page_count:
            raise PdfRecoveryError(invalid)
        previous = number
        end = headings[index + 1].start() if index + 1 < len(headings) else len(body)
        section = body[heading.end():end]
        if not section.endswith('\n\n'):
            raise PdfRecoveryError(invalid)
        section = section[:-2]
        if not section.strip():
            raise PdfRecoveryError(invalid)
        if number in failed_set:
            if not section.startswith(_LEGACY_ERROR) or not section[len(_LEGACY_ERROR):].strip():
                raise PdfRecoveryError(invalid)
            pages[number - 1] = {'status': 'failed', 'error': section[len(_LEGACY_ERROR):]}
            seen_failed.append(number)
        else:
            if section.startswith(_LEGACY_ERROR):
                raise PdfRecoveryError(invalid)
            pages[number - 1]['text'] = section
            words += len(section.split())
    if tuple(seen_failed) != failed or header[1] != f'{words:,}':
        raise PdfRecoveryError(invalid)
    return pages


def _statistics(pages: list[dict]) -> tuple[int, tuple[int, ...]]:
    words = sum(len(page['text'].split()) for page in pages if page['status'] == 'done')
    failures = tuple(index for index, page in enumerate(pages, 1) if page['status'] == 'failed')
    return words, failures


def pdf_header(source: Path, page_count: int, words: int, failures: tuple[int, ...]) -> str:
    from converters import build_header
    extras = {'Pages': str(page_count)}
    if failures:
        failed_list = ', '.join(str(number) for number in failures)
        page_label = 'page' if len(failures) == 1 else 'pages'
        extras['Warning'] = f'Incomplete PDF. OCR failed on {page_label} {failed_list}.'
    return build_header(source.stem, source.name, words, **extras)


def _export(source: Path, work_dir: Path, pages: list[dict]) -> PdfQueueResult:
    words, failures = _statistics(pages)
    if not words and not failures:
        raise PdfRecoveryError('PDF has no extractable text.')
    sections = [pdf_header(source, len(pages), words, failures)]
    for number, page in enumerate(pages, 1):
        if page['status'] == 'failed':
            sections.append(f"## Page {number}\nOCR failed: {page['error']}\n\n")
        elif page['text']:
            sections.append(f"## Page {number}\n{page['text']}\n\n")
    output = save_pdf_snapshot(work_dir, ''.join(sections))
    return PdfQueueResult(output, words, failures, False)


def save_pdf_snapshot(work_dir: Path, content: str) -> Path:
    """Store an immutable snapshot before its publication receipt exists."""
    directory = work_dir / 'pdf-snapshots'
    if directory.is_symlink():
        raise PdfRecoveryError('PDF recovery data cannot use a symbolic link.')
    directory.mkdir(exist_ok=True)
    digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
    output = directory / f'{digest}.md'
    if output.is_symlink():
        raise PdfRecoveryError('PDF recovery data cannot use a symbolic link.')
    if output.exists():
        if output.read_text(encoding='utf-8') != content:
            raise PdfRecoveryError('Saved PDF output snapshot was modified.')
    else:
        atomic_write_text(output, content)
    return output


def convert_queued_pdf(
    source: Path,
    work_dir: Path,
    *,
    should_cancel: CancelCheck = None,
    legacy_output: Path | None = None,
    legacy_failed_pages: tuple[int, ...] = (),
) -> PdfQueueResult:
    """Process pending pages and retry prior failures in a private queue attempt.

    The caller serializes operations in `work_dir`. Successful text is persisted
    per page and never rerun. A canceled invocation leaves pending and failed
    states intact and does not export. Prior rendered snapshots remain immutable.
    Corrupt checkpoints and changed sources raise `PdfRecoveryError`.
    """
    from converters import _ocr_pdf_page, normalize_blanks

    source = Path(source)
    work_dir = Path(work_dir)
    if any(p.is_symlink() for p in (work_dir, work_dir / _PROGRESS, work_dir / 'pdf-snapshots')):
        raise PdfRecoveryError('PDF recovery data cannot use a symbolic link.')
    if should_cancel and should_cancel():
        return PdfQueueResult(None, 0, (), True)
    try:
        signature, digest = _fingerprint(source, should_cancel)
    except OcrCancelled:
        return PdfQueueResult(None, 0, (), True)
    identity = {'schema': _SCHEMA, 'source': str(source.resolve()), 'sha256': digest}
    progress_path = work_dir / _PROGRESS
    pages = _load_progress(progress_path, identity) if progress_path.exists() else None
    with pymupdf.open(source) as document:
        _ensure_source(source, signature)
        page_count = len(document)
        if not page_count:
            raise PdfRecoveryError('PDF is empty and contains no pages.')
        if pages is not None:
            if len(pages) != page_count:
                raise PdfRecoveryError('PDF page checkpoint has a different page count.')
        else:
            if legacy_output is not None:
                pages = _import_legacy(Path(legacy_output), source, work_dir, page_count, signature, legacy_failed_pages)
            elif legacy_failed_pages:
                raise PdfRecoveryError('Previous PDF partial export is missing; cannot safely retry its pages.')
            else:
                pages = [{'status': 'pending'} for _ in range(page_count)]
            _ensure_source(source, signature)
            work_dir.mkdir(parents=True, exist_ok=True)
            _save_progress(progress_path, identity, pages)

        plan = tuple(page['status'] for page in pages)
        if 'failed' in plan:
            from pdf_page_ocr import recover_pdf_page

        for index, status in enumerate(plan):
            if status == 'done':
                continue
            if should_cancel and should_cancel():
                return PdfQueueResult(None, *_statistics(pages), True)
            _ensure_source(source, signature)
            try:
                page = document[index]
                if status == 'failed':
                    text = recover_pdf_page(page, should_cancel=should_cancel).strip()
                    if not text:
                        raise ValueError('No text detected on this page.')
                else:
                    text = page.get_text().strip()
                    if not text and (page.get_images() or page.get_drawings()):
                        text = _ocr_pdf_page(page, should_cancel=should_cancel).strip()
                        if not text:
                            raise ValueError('No text detected on this page.')
                state = {'status': 'done', 'text': normalize_blanks(text)}
            except OcrCancelled:
                return PdfQueueResult(None, *_statistics(pages), True)
            except Exception as exc:
                error = ' '.join(str(exc).split()) or type(exc).__name__
                state = {'status': 'failed', 'error': error}
            _ensure_source(source, signature)
            pages[index] = state
            _save_progress(progress_path, identity, pages)

    if should_cancel and should_cancel():
        return PdfQueueResult(None, *_statistics(pages), True)
    _ensure_source(source, signature)
    return _export(source, work_dir, pages)
