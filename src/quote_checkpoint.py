"""Versioned image journals: saved records are the authority for recovery."""
from dataclasses import asdict
from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path

from file_utils import atomic_write_text, reserve_output_path
from quote_markdown import render_quote_batch_markdown
from quote_parser import QuoteRecord


def fingerprint(path: str) -> str | None:
    try:
        with Path(path).open('rb') as stream:
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(65536), b''):
                digest.update(chunk)
            return digest.hexdigest()
    except OSError:
        return None


def canonical_paths(paths):
    return sorted({str(Path(path).resolve()) for path in paths})


class QuoteCheckpoint:
    def __init__(self, output_dir: Path, stem: str, paths: list[str], raw_ocr_mode: str):
        paths = canonical_paths(paths)
        self.path = reserve_output_path(output_dir, stem)
        self.report_path = self.path.with_suffix('.progress.json')
        self.raw_ocr_mode = raw_ocr_mode
        self.report = {'schema': 2, 'status': 'running', 'total': len(paths), 'processed': 0,
                       'current_image': None, 'failed': [], 'notices': [],
                       'raw_ocr_mode': raw_ocr_mode, 'items': [
                           {'path': path, 'status': 'pending', 'records': [], 'fingerprint': None}
                           for path in sorted(paths)]}

    @classmethod
    def load(cls, report_path: Path):
        data = json.loads(report_path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('schema') != 2 or not isinstance(data.get('items'), list):
            raise ValueError('This report does not contain resumable image records')
        if data.get('raw_ocr_mode') not in ('always', 'different', 'never'):
            raise ValueError('Invalid quote display setting in checkpoint')
        if data.get('status') not in ('running', 'canceled', 'completed', 'completed_with_errors'):
            raise ValueError('Invalid batch status')
        if not isinstance(data.get('notices'), list) or not all(isinstance(n, str) for n in data['notices']):
            raise ValueError('Invalid batch notices')
        if data.get('vault_pending') is not None and (not isinstance(data['vault_pending'], str) or not Path(data['vault_pending']).is_absolute()):
            raise ValueError('Invalid pending vault delivery')
        if not isinstance(data.get('vault_exports', {}), dict):
            raise ValueError('Invalid vault destinations')
        for item in data['items']:
            if not isinstance(item, dict) or not isinstance(item.get('path'), str):
                raise ValueError('Invalid image manifest')
            if not Path(item['path']).is_absolute() or '\0' in item['path']:
                raise ValueError('Image paths must be absolute')
            if 'fingerprint' not in item or (item['fingerprint'] is not None and
                    (not isinstance(item['fingerprint'], str) or len(item['fingerprint']) != 64)):
                raise ValueError('Invalid source fingerprint')
            if not isinstance(item.get('records'), list) or not isinstance(item.get('previous_records', []), list):
                raise ValueError('Invalid saved records')
            if item.get('status') not in ('pending', 'success', 'failed'):
                raise ValueError('Invalid image state')
            for record in item['records'] + item.get('previous_records', []):
                if not isinstance(record, dict) or set(record) != {'quote', 'author', 'source_image', 'raw_ocr'} or not all(isinstance(v, str) for v in record.values()):
                    raise ValueError('Invalid saved quote')
        if not report_path.name.endswith('.progress.json'):
            raise ValueError('Invalid checkpoint filename')
        instance = cls.__new__(cls)
        instance.report_path = report_path
        # Never trust an output path embedded in a report.
        instance.path = report_path.with_name(report_path.name.removesuffix('.progress.json') + '.md')
        instance.report = data
        instance.raw_ocr_mode = data['raw_ocr_mode']
        instance.report['notices'] = data.get('notices', [])
        instance.refresh()
        return instance

    @property
    def items(self):
        return self.report['items']

    @property
    def records(self):
        return [QuoteRecord(**record) for item in self.items for record in item['records']]

    def refresh(self):
        self.report['total'] = len(self.items)
        self.report['processed'] = sum(item['status'] != 'pending' for item in self.items)
        self.report['failed'] = [{'image': item['path'], 'error': item.get('error', 'Unreadable image')}
                                 for item in self.items if item['status'] == 'failed']

    def invalidate_changed_sources(self):
        for item in self.items:
            if item['status'] != 'success':
                continue
            current = fingerprint(item['path'])
            if current is not None and current != item['fingerprint']:
                item.update(status='pending', previous_records=item['records'], records=[], fingerprint=None)
        self.refresh()

    def complete(self, item, records, source_fingerprint, error=None):
        item.update(status='failed' if error is not None else 'success',
                    records=[asdict(record) for record in records], fingerprint=source_fingerprint)
        if error is not None:
            item['error'] = str(error)
        else:
            item.pop('error', None)
            item.pop('previous_records', None)
        self.refresh()

    def save(self, status: str, current_image=None):
        self.refresh()
        self.report.update(status=status, current_image=current_image, export_pending=True)
        # Commit the journal first. A crash before Markdown replacement is repaired
        # by rendering saved records on the next resume, without repeating OCR.
        atomic_write_text(self.report_path, json.dumps(self.report, indent=2) + '\n')
        markdown = render_quote_batch_markdown(self.records, raw_ocr_mode=self.raw_ocr_mode)
        markdown += f"\n---\n\n## Conversion report\n\nStatus: {status}\n\n"
        markdown += f"Processed: {self.report['processed']}/{self.report['total']} images\n"
        for failure in self.report['failed']:
            markdown += f"\n- Failed: {failure['image']} — {failure['error']}\n"
        previous = [QuoteRecord(**record) for item in self.items for record in item.get('previous_records', [])]
        if previous:
            markdown += '\n## Previous results — source changed\n\nThese saved results belong to an earlier version of the source. Replacement text could not yet be extracted.\n\n'
            markdown += render_quote_batch_markdown(previous, title='Previous saved quotes', raw_ocr_mode=self.raw_ocr_mode)
        atomic_write_text(self.path, markdown)
        self.report['export_pending'] = False
        atomic_write_text(self.report_path, json.dumps(self.report, indent=2) + '\n')


def recovery_checkpoints(output_dir: Path):
    candidates = sorted(output_dir.glob('*.progress.json'), key=lambda p: p.name, reverse=True)
    for path in candidates:
        try:
            checkpoint = QuoteCheckpoint.load(path)
            if checkpoint.report['status'] != 'completed' or checkpoint.report.get('export_pending') or checkpoint.report.get('vault_pending'):
                yield checkpoint
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue


def matching_checkpoint(output_dir: Path, paths: list[str], raw_ocr_mode: str):
    expected = canonical_paths(paths)
    for checkpoint in recovery_checkpoints(output_dir):
        if ((any(item['status'] == 'pending' for item in checkpoint.items)
                or checkpoint.report.get('export_pending') or checkpoint.report.get('vault_pending') or checkpoint.report['status'] == 'running')
                and checkpoint.raw_ocr_mode == raw_ocr_mode
                and canonical_paths(item['path'] for item in checkpoint.items) == expected):
            return checkpoint
    return None


@contextmanager
def batch_lock(output_dir: Path):
    """Serialize journals across app instances; the OS releases locks after a crash."""
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / '.quote-batch.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another conversion is using this output folder. Let it finish before resuming.') from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)
