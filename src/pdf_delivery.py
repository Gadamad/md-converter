"""Publish an immutable PDF snapshot without replacing earlier exports."""
from datetime import date
import hashlib
from itertools import chain
from pathlib import Path
import re

from file_utils import atomic_write_chunks, reserve_output_path
from output_copy import atomic_copy_file, deliver_output_copies


def _identity(path):
    try:
        st = path.lstat()
    except FileNotFoundError:
        return None
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns


def _digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _publish_file(source, directory, stem, receipt, key, persist):
    if not directory.is_absolute() or directory.resolve() != directory:
        raise ValueError('PDF export folder cannot use symbolic links or traversal.')
    directory.mkdir(parents=True, exist_ok=True)
    target = None
    state = None
    saved = receipt.get(key)
    if isinstance(saved, dict):
        name = saved.get('name')
        if isinstance(name, str) and re.fullmatch(re.escape(stem) + r'(?:_[0-9]+)?\.md', name):
            candidate = directory / name
            current = _identity(candidate)
            if current is not None and not candidate.is_symlink() and candidate.is_file():
                if _digest(candidate) == _digest(source) and _identity(candidate) == current:
                    return candidate
                if current[2] == 0 and list(current) == saved.get('reservation'):
                    target, state = candidate, current
    if target is None:
        target = reserve_output_path(directory, stem)
        state = _identity(target)
        if state is None or state[2] != 0 or target.is_symlink():
            raise OSError('The reserved PDF export changed. Retry to preserve the existing file.')
        receipt[key] = {'name': target.name, 'reservation': list(state)}
        persist()
    if directory.resolve() != directory:
        raise ValueError('PDF export folder changed before delivery.')
    atomic_copy_file(source, target, expected_state=state)
    return target


def migrate_pdf_receipt(item, receipt):
    """Make a legacy complete conversion safe to deliver without rerunning OCR."""
    from pdf_recovery import save_pdf_snapshot
    work = Path(item['receipt_path']).parent
    if receipt.get('format') != 'pdf' or not isinstance(receipt.get('source_output'), str):
        raise ValueError('Invalid legacy PDF delivery receipt.')
    source = Path(receipt['source_output'])
    if (source.parent != work / 'converted' / 'pdf' or source.resolve() != source
            or source.suffix != '.md' or not source.is_file()):
        raise ValueError('The legacy PDF export is missing or changed.')
    snapshot = save_pdf_snapshot(work, source.read_text(encoding='utf-8'))
    migrated = {'source_output': str(snapshot), 'word_count': receipt['word_count'],
                'pdf_failed_pages': [], 'pdf_delivery_pending': True}
    if item['output_path']:
        output = Path(item['output_path'])
        if output.parent == Path(item['options']['output_dir']) / 'pdf':
            migrated['pdf_primary'] = {'name': output.name}
            if 'copy_exports' in receipt:
                migrated['copy_exports'] = receipt['copy_exports']
    return migrated


def _verified_snapshot(item, receipt):
    from pdf_recovery import pdf_header
    invalid = 'The saved PDF snapshot does not match its delivery receipt.'
    pages, words = receipt.get('pdf_failed_pages'), receipt.get('word_count')
    if (not isinstance(pages, list) or any(type(n) is not int or n < 1 for n in pages)
            or sorted(set(pages)) != pages or type(words) is not int or words < 0
            or not isinstance(receipt.get('source_output'), str)):
        raise ValueError(invalid)
    source = Path(receipt['source_output'])
    snapshots = Path(item['receipt_path']).parent / 'pdf-snapshots'
    if (source.parent != snapshots or source.resolve() != source or source.suffix != '.md'
            or not source.is_file() or source.stem != _digest(source)):
        raise ValueError('The saved PDF snapshot is missing or changed.')
    original = Path(item['source'])
    lead = f'# {original.stem}\n\n> **Source**: `{original.name}`  \n'
    with source.open(encoding='utf-8') as stream:
        if stream.read(len(lead)) != lead:
            raise ValueError(invalid)
        count = re.fullmatch(r'> \*\*Pages\*\*: ([1-9][0-9]*)  \n', stream.readline(64))
        if count is None or (pages and pages[-1] > int(count[1])):
            raise ValueError(invalid)
        header = pdf_header(original, int(count[1]), words, tuple(pages))
        stream.seek(0)
        if stream.read(len(header)) != header:
            raise ValueError(invalid)
    return source


def publish_pdf_snapshot(item, receipt, *, persist, on_primary):
    """Publish normal, vault and extra copies of a saved queued PDF revision."""
    from converters import safe_filename, vault_frontmatter

    source = _verified_snapshot(item, receipt)
    options = item['options']
    base = Path(options['output_dir'])
    name = safe_filename(Path(item['source']).stem).encode('utf-8')[:160].decode('utf-8', 'ignore') or 'document'
    state = '_partial' if receipt['pdf_failed_pages'] else ''
    stem = f"{name}{state}_{item['id'][:12]}"
    output = _publish_file(source, base / 'pdf', stem, receipt, 'pdf_primary', persist)
    on_primary(output)
    if options.get('vault_dir'):
        vault_source = source.parent / f'vault-{source.name}'
        if vault_source.is_symlink():
            raise ValueError('PDF recovery data cannot use a symbolic link.')
        if 'pdf_vault_created' not in receipt:
            receipt['pdf_vault_created'] = date.today().isoformat()
            persist()
        header = vault_frontmatter(item['title'], 'pdf', item['source'],
                                   created=date.fromisoformat(receipt['pdf_vault_created']))
        with source.open(encoding='utf-8') as stream:
            atomic_write_chunks(vault_source, chain((header,), iter(lambda: stream.read(65536), '')))
        _publish_file(vault_source, Path(options['vault_dir']) / 'pdf', output.stem, receipt, 'pdf_vault', persist)
    if options.get('copy_dir'):
        deliver_output_copies([output], base_dir=base, copy_dir=Path(options['copy_dir']),
            manifest=receipt, persist=persist, copy_mode=options.get('copy_mode', 'subfolder'))
