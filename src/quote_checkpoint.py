"""Versioned image journals: saved records are the authority for recovery."""
from dataclasses import asdict
from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path

from file_utils import atomic_write_text, reserve_output_path
from output_copy import deliver_output_copies, validate_copy_manifest
from quote_markdown import render_quote_batch_markdown
from quote_parser import QuoteRecord


NO_TEXT_MESSAGE = 'No text detected. Preview the image or skip it.'
SUSPICIOUS_TEXT_MESSAGE = 'Uncertain OCR text. Preview the image or try again.'


def review_failure_code(item):
    code = item.get('error_code')
    if code in ('no_text', 'suspicious_text'):
        return code
    error = str(item.get('error') or '')
    if error.startswith('No text detected'):
        return 'no_text'
    if error.startswith('Uncertain OCR text.'):
        return 'suspicious_text'
    return None


def is_review_failure(item):
    return review_failure_code(item) is not None


def is_no_text_failure(item):
    return review_failure_code(item) == 'no_text'


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
                       'current_image': None, 'failed': [], 'skipped': [], 'notices': [],
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
            if 'error_code' in item and not isinstance(item['error_code'], str):
                raise ValueError('Invalid OCR error code')
            if 'diagnostics' in item and (not isinstance(item['diagnostics'], list)
                    or not all(isinstance(entry, dict) for entry in item['diagnostics'])):
                raise ValueError('Invalid OCR diagnostics')
            if 'skipped' in item and not isinstance(item['skipped'], bool):
                raise ValueError('Invalid skipped image flag')
            if 'verified_records' in item and (not isinstance(item['verified_records'], list)
                    or any(type(index) is not int or not 0 <= index < len(item['records'])
                           for index in item['verified_records'])):
                raise ValueError('Invalid source verification indices')
            if 'correction_history' in item and (not isinstance(item['correction_history'], list)
                    or not all(isinstance(entry, dict) for entry in item['correction_history'])):
                raise ValueError('Invalid quote correction history')
            if item.get('skipped') and (item['status'] != 'failed' or item['records']
                                        or item.get('previous_records')):
                raise ValueError('Only unsuccessful images without saved text can be skipped')
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
        instance._copy_directory()
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
                                 for item in self.items if item['status'] == 'failed' and not item.get('skipped')]
        self.report['skipped'] = [{'image': item['path'], 'error': item.get('error', 'Unreadable image')}
                                  for item in self.items if item.get('skipped')]

    def invalidate_changed_sources(self):
        for item in self.items:
            if item['status'] != 'success':
                continue
            current = fingerprint(item['path'])
            if current is not None and current != item['fingerprint']:
                item.update(status='pending', previous_records=item['records'], records=[], fingerprint=None)
                item.pop('verified_records', None)
        self.refresh()

    def complete(self, item, records, source_fingerprint, error=None, *,
                 error_code=None, diagnostics=None):
        item.update(status='failed' if error is not None else 'success',
                    records=[asdict(record) for record in records], fingerprint=source_fingerprint)
        item.pop('skipped', None)
        item.pop('verified_records', None)
        item.pop('error_code', None)
        item.pop('diagnostics', None)
        if isinstance(diagnostics, list):
            item['diagnostics'] = diagnostics
        if error is not None:
            item['error'] = str(error)
            if isinstance(error_code, str):
                item['error_code'] = error_code
        else:
            item.pop('error', None)
            item.pop('previous_records', None)
        self.refresh()

    def mark_skipped(self, path):
        """Persist a failed image's dismissal; callers serialize with batch_lock."""
        path = str(Path(path).resolve())
        item = next((item for item in self.items if item['path'] == path), None)
        if item is None:
            raise ValueError('This image does not belong to the saved batch')
        if item['status'] != 'failed' or item['records'] or item.get('previous_records'):
            raise ValueError('Only unsuccessful images without saved text can be skipped')
        if (item.get('skipped') and not self.report.get('export_pending')
                and not self.report.get('copy_pending')):
            return
        self._vault_export_paths()  # Validate saved destinations before changing the item.
        self._copy_directory()
        item['skipped'] = True
        self.refresh()
        status = ('canceled' if any(row['status'] == 'pending' for row in self.items)
                  else 'completed_with_errors' if self.report['failed'] else 'completed')
        self.save(status, sync_vault_exports=True)

    def _vault_export_paths(self):
        paths = []
        for directory, filename in self.report.get('vault_exports', {}).items():
            if (not isinstance(directory, str) or '\0' in directory
                    or not Path(directory).is_absolute() or '..' in Path(directory).parts):
                raise ValueError('Invalid saved vault directory')
            if (not isinstance(filename, str) or '\0' in filename
                    or Path(filename).name != filename or not filename.endswith('.md')):
                raise ValueError('Invalid saved vault filename')
            paths.append(Path(directory) / filename)
        return paths

    def _copy_directory(self):
        """Validate optional delivery metadata without touching its destination."""
        directory = self.report.get('copy_dir')
        exports = self.report.get('copy_exports', {})
        pending = self.report.get('copy_pending', False)
        if not isinstance(exports, dict) or not isinstance(pending, bool):
            raise ValueError('Invalid additional-copy delivery metadata')
        if directory is None:
            if exports or pending:
                raise ValueError('Additional-copy delivery is missing its destination')
            return None
        if not isinstance(directory, str):
            raise ValueError('Invalid additional-copy destination')
        copy_dir = Path(directory)
        validate_copy_manifest(base_dir=self.path.parent.parent, copy_dir=copy_dir, manifest=self.report)
        # The delivery manifest retains the same absolute spelling passed to
        # save, including OS parent aliases such as /var versus /private/var.
        if any(source != str(self.path) for source in exports):
            raise ValueError('Additional quote copies must reference this report\'s Markdown output')
        return copy_dir

    def _persist_report(self):
        atomic_write_text(self.report_path, json.dumps(self.report, indent=2) + '\n')

    def save(self, status: str, current_image=None, *, sync_vault_exports=False):
        self.refresh()
        copy_dir = self._copy_directory()
        copy_recovery_pending = bool(copy_dir is not None and self.report.get('export_pending'))
        # A skipped item and an unfinished export identify a skip interrupted
        # while replacing either the local Markdown or one of its vault copies.
        sync_vault_exports = sync_vault_exports or (self.report.get('export_pending')
                                                    and bool(self.report['skipped']))
        vault_paths = self._vault_export_paths() if sync_vault_exports else []
        self.report.update(status=status, current_image=current_image, export_pending=True)
        # Commit the journal first. A crash before Markdown replacement is repaired
        # by rendering saved records on the next resume, without repeating OCR.
        self._persist_report()
        verified_indices = set()
        offset = 0
        for item in self.items:
            verified_indices.update(offset + index + 1 for index in item.get('verified_records', []))
            offset += len(item['records'])
        markdown = render_quote_batch_markdown(self.records, raw_ocr_mode=self.raw_ocr_mode,
                                               verified_indices=frozenset(verified_indices))
        markdown += f"\n---\n\n## Conversion report\n\nStatus: {status}\n\n"
        markdown += f"Processed: {self.report['processed']}/{self.report['total']} images\n"
        if verified_indices:
            count = len(verified_indices)
            markdown += (f"\nVerified against original images: {count} quote{'s' if count != 1 else ''}. "
                         "Original OCR is retained in the conversion journal.\n")
        for failure in self.report['failed']:
            markdown += f"\n- Failed: {failure['image']} — {failure['error']}\n"
        for skipped in self.report['skipped']:
            markdown += f"\n- Skipped: {skipped['image']} — {skipped['error']}\n"
        previous = [QuoteRecord(**record) for item in self.items for record in item.get('previous_records', [])]
        if previous:
            markdown += '\n## Previous results — source changed\n\nThese saved results belong to an earlier version of the source. Replacement text could not yet be extracted.\n\n'
            markdown += render_quote_batch_markdown(previous, title='Previous saved quotes', raw_ocr_mode=self.raw_ocr_mode)
        atomic_write_text(self.path, markdown)
        for vault_path in vault_paths:
            vault_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(vault_path, markdown)
        if vault_paths and self.report.get('vault_pending'):
            pending_directory = (Path(self.report['vault_pending']) / 'quotes').resolve()
            if any(path.parent.resolve() == pending_directory for path in vault_paths):
                self.report['vault_pending'] = None
        if copy_dir is not None and status in ('completed', 'completed_with_errors', 'canceled'):
            # Persist the extracted text and primary Markdown before touching an
            # optional destination. Delivery failures remain resumable exports.
            self.report['copy_pending'] = True
            self._persist_report()
            try:
                deliver_output_copies([self.path], base_dir=self.path.parent.parent,
                                      copy_dir=copy_dir, manifest=self.report, persist=self._persist_report)
            except (OSError, ValueError, RuntimeError) as exc:
                raise OSError(f'Image text is saved; additional copy failed: {exc}') from exc
        # Recovery writes a temporary "running" report before its final state.
        # Keep the marker until that final report reaches every pending copy.
        self.report['export_pending'] = bool(self.report.get('copy_pending') or
                                             (status == 'running' and
                                              (sync_vault_exports or copy_recovery_pending)))
        self._persist_report()


def recovery_checkpoints(output_dir: Path):
    candidates = sorted(output_dir.glob('*.progress.json'), key=lambda p: p.name, reverse=True)
    for path in candidates:
        try:
            checkpoint = QuoteCheckpoint.load(path)
            if (checkpoint.report['status'] != 'completed' or checkpoint.report.get('export_pending')
                    or checkpoint.report.get('vault_pending') or checkpoint.report.get('copy_pending')):
                yield checkpoint
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue


def matching_checkpoint(output_dir: Path, paths: list[str], raw_ocr_mode: str):
    expected = canonical_paths(paths)
    for checkpoint in recovery_checkpoints(output_dir):
        if ((any(item['status'] == 'pending' for item in checkpoint.items)
                or checkpoint.report.get('export_pending') or checkpoint.report.get('vault_pending')
                or checkpoint.report.get('copy_pending') or checkpoint.report['status'] == 'running')
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
