"""Durable, byte-preserving delivery of additional Markdown and text copies."""
import hashlib
import os
from pathlib import Path
import re
import tempfile

from file_utils import reserve_output_path


_EMPTY_SHA256 = hashlib.sha256(b'').hexdigest()
_UNSPECIFIED = object()


def _absolute(value, label):
    if not isinstance(value, (str, Path)):
        raise ValueError(f'Invalid {label}')
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts or '\0' in str(path):
        raise ValueError(f'{label} must be an absolute path without traversal')
    return path


def _roots(base_dir, copy_dir):
    base = _absolute(base_dir, 'output directory')
    destination = _absolute(copy_dir, 'copy directory')
    if destination == base or destination.parent != base:
        raise ValueError('The copy directory must be a direct child of the output directory')
    return base, destination


def _relative_source(source, base, destination):
    source = _absolute(source, 'copy source')
    try:
        relative = source.relative_to(base)
    except ValueError:
        raise ValueError('Copy sources must be inside the output directory') from None
    if source.suffix.lower() not in {'.md', '.txt'} or not relative.parts or relative.parts[0] == destination.name:
        raise ValueError('Only primary Markdown or text outputs can be copied')
    return source, relative


def validate_copy_manifest(*, base_dir: Path, copy_dir: Path, manifest: dict) -> None:
    """Check metadata only; unavailable destinations must not block journal reads."""
    base, destination = _roots(base_dir, copy_dir)
    if not isinstance(manifest, dict):
        raise ValueError('Invalid copy manifest')
    if 'copy_pending' in manifest and not isinstance(manifest['copy_pending'], bool):
        raise ValueError('Invalid pending copy flag')
    exports = manifest.get('copy_exports', {})
    if not isinstance(exports, dict):
        raise ValueError('Invalid copy exports')
    seen = set()
    for source_key, record in exports.items():
        if not isinstance(source_key, str):
            raise ValueError('Copy source keys must be absolute paths')
        source, relative = _relative_source(source_key, base, destination)
        if not isinstance(record, dict) or set(record) != {'path', 'sha256', 'pending_sha256'}:
            raise ValueError('Invalid copy destination record')
        target = _absolute(record['path'], 'copy target')
        if target.parent != (destination / relative).parent or target.suffix != source.suffix:
            raise ValueError('Copy targets must preserve the source subfolders and file suffix')
        number = target.stem.removeprefix(source.stem + '_')
        if target.stem != source.stem and not (target.stem.startswith(source.stem + '_')
                                               and number.isascii() and number.isdigit() and int(number) >= 2):
            raise ValueError('Invalid reserved copy filename')
        if str(target) in seen:
            raise ValueError('Copy destinations must be unique')
        seen.add(str(target))
        for key in ('sha256', 'pending_sha256'):
            digest = record[key]
            if digest is not None and (not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest)):
                raise ValueError('Invalid copy content hash')


def _no_symlinks(root, path):
    relative = path.relative_to(root)
    current = root
    if current.is_symlink():
        raise ValueError('Copy paths cannot use symbolic links')
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('Copy paths cannot use symbolic links')


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _target_state(path):
    try:
        state = path.lstat()
        return state.st_dev, state.st_ino, state.st_size, state.st_mtime_ns
    except FileNotFoundError:
        return None


def atomic_copy_file(source: Path, target: Path, *, expected_state=_UNSPECIFIED) -> None:
    """Stream raw bytes to a durable atomic replacement; never rewrite text."""
    source, target = Path(source), Path(target)
    if source.is_symlink() or target.is_symlink():
        raise ValueError('Copy files cannot use symbolic links')
    before = _target_state(target)
    if expected_state is not _UNSPECIFIED and before != expected_state:
        raise OSError('The additional copy changed before delivery; retry to preserve the edited file')
    temporary = None
    try:
        with source.open('rb') as original, tempfile.NamedTemporaryFile(
                mode='wb', dir=target.parent, prefix=f'.{target.name}.', delete=False) as stream:
            temporary = Path(stream.name)
            for chunk in iter(lambda: original.read(65536), b''):
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if _target_state(target) != before:
            raise OSError('The additional copy changed during delivery; retry to preserve the edited file')
        os.replace(temporary, target)
        directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _owned_content(target, record):
    state = _target_state(target)
    if target.is_symlink() or (target.exists() and not target.is_file()):
        return False, None, state
    if not target.exists():
        return True, None, state
    digest = _sha256(target)
    if _target_state(target) != state:
        return False, None, state
    owned = digest in {record['sha256'], record['pending_sha256']}
    # A durable mapping with no delivered hash owns its initial empty reservation.
    owned = owned or (record['sha256'] is None and digest == _EMPTY_SHA256)
    return owned, digest, state


def deliver_output_copies(sources: list[Path], *, base_dir: Path, copy_dir: Path,
                          manifest: dict, persist) -> None:
    validate_copy_manifest(base_dir=base_dir, copy_dir=copy_dir, manifest=manifest)
    base, destination = _roots(base_dir, copy_dir)
    planned = []
    seen = set()
    # Reject all unsafe inputs before reservations, manifest writes or publication.
    for value in sources:
        source, relative = _relative_source(value, base, destination)
        if str(source) in seen:
            continue
        seen.add(str(source))
        _no_symlinks(base, source)
        _no_symlinks(base, (destination / relative).parent)
        if not source.is_file():
            raise OSError('A primary output is unavailable for copying')
        planned.append((source, relative, _sha256(source)))
    for record in manifest.get('copy_exports', {}).values():
        _no_symlinks(base, Path(record['path']).parent)

    exports = manifest.setdefault('copy_exports', {})
    manifest['copy_pending'] = True
    persist()
    for source, relative, digest in planned:
        key = str(source)
        record = exports.get(key)
        current_hash = None
        expected_state = None
        owned = False
        if record is not None:
            target = Path(record['path'])
            owned, current_hash, expected_state = _owned_content(target, record)
        if not owned:
            parent = (destination / relative).parent
            _no_symlinks(base, parent)
            target = reserve_output_path(parent, source.stem, source.suffix)
            expected_state = _target_state(target)
            current_hash = None
            record = {'path': str(target), 'sha256': None, 'pending_sha256': digest}
            exports[key] = record
        else:
            # If the prior process published its pending bytes before crashing,
            # promote that actual owned hash before planning a newer source.
            if current_hash is not None:
                record['sha256'] = current_hash
            record['pending_sha256'] = digest
        persist()
        if _target_state(target) != expected_state:
            raise OSError('The additional copy changed before delivery; retry to preserve the edited file')
        if current_hash != digest:
            _no_symlinks(base, target.parent)
            target.parent.mkdir(parents=True, exist_ok=True)
            _no_symlinks(base, target.parent)
            atomic_copy_file(source, target, expected_state=expected_state)
            if _sha256(target) != digest:
                raise OSError('The primary output changed during copy delivery; retry the saved output')
        record.update(sha256=digest, pending_sha256=None)
        persist()
    manifest['copy_pending'] = False
    try:
        persist()
    except Exception:
        manifest['copy_pending'] = True
        raise
