"""Durable, byte-preserving delivery of additional Markdown and text copies."""
import hashlib
import os
from pathlib import Path
import re
import tempfile

from file_utils import reserve_output_path


_EMPTY_SHA256 = hashlib.sha256(b'').hexdigest()
_UNSPECIFIED = object()
_PRIMARY_OUTPUT_FOLDERS = frozenset({'quotes', 'pdf', 'docx', 'spreadsheets', 'html', 'txt', 'rtf', 'epub'})


def _absolute(value, label):
    if not isinstance(value, (str, Path)):
        raise ValueError(f'Invalid {label}')
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts or '\0' in str(path):
        raise ValueError(f'{label} must be an absolute path without traversal')
    return path


def _roots(base_dir, copy_dir, copy_mode):
    if not isinstance(copy_mode, str) or copy_mode not in ('subfolder', 'existing'):
        raise ValueError('Copy mode must be subfolder or existing')
    base = _absolute(base_dir, 'output directory')
    destination = _absolute(copy_dir, 'copy directory')
    if copy_mode == 'subfolder':
        if destination == base or destination.parent != base:
            raise ValueError('The copy directory must be a direct child of the output directory')
    else:
        if base.is_relative_to(destination):
            raise ValueError('An existing copy folder cannot be the output directory or its ancestor')
        if destination.is_relative_to(base):
            relative = destination.relative_to(base)
            if relative.parts[0].casefold() in _PRIMARY_OUTPUT_FOLDERS:
                raise ValueError('An existing copy folder cannot use a regular export subtree')
    return base, destination


def _relative_source(source, base, destination):
    source = _absolute(source, 'copy source')
    try:
        relative = source.relative_to(base)
    except ValueError:
        raise ValueError('Copy sources must be inside the output directory') from None
    if source.suffix.lower() not in {'.md', '.txt'} or not relative.parts or source.is_relative_to(destination):
        raise ValueError('Only primary Markdown or text outputs can be copied')
    return source, relative


def validate_copy_manifest(*, base_dir: Path, copy_dir: Path, manifest: dict,
                           copy_mode: str = 'subfolder') -> None:
    """Check metadata only; unavailable destinations must not block journal reads."""
    base, destination = _roots(base_dir, copy_dir, copy_mode)
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


def _mounted_identity(path):
    try:
        state = path.stat()
    except (FileNotFoundError, NotADirectoryError):
        return None
    return state.st_dev, state.st_ino


def _existing_root(base, destination):
    # These paths were canonicalized when selected. A new link anywhere along
    # their spelling must not silently redirect delivery after that selection.
    _no_symlinks(Path(base.anchor), base)
    _no_symlinks(Path(destination.anchor), destination)
    if not destination.is_dir():
        raise OSError('The selected copy folder is unavailable; restore it before retrying')
    # APFS can resolve differently capitalized spellings to the same directory.
    # Mounted identity complements pure lexical validation without changing
    # metadata loading for a destination that is currently disconnected.
    destination_id = _mounted_identity(destination)
    if destination_id is None:
        raise OSError('The selected copy folder is unavailable; restore it before retrying')
    if any(_mounted_identity(parent) == destination_id for parent in (base, *base.parents)):
        raise ValueError('An existing copy folder cannot be the output directory or its ancestor')
    primary_ids = set()
    for name in _PRIMARY_OUTPUT_FOLDERS:
        identity = _mounted_identity(base / name)
        if identity is not None:
            primary_ids.add(identity)
    if any(_mounted_identity(parent) in primary_ids for parent in (destination, *destination.parents)):
        raise ValueError('An existing copy folder cannot use a regular export subtree')


def validate_existing_copy_directory(*, base_dir: Path, copy_dir: Path) -> None:
    """Validate a selected mounted directory without creating or changing files."""
    base, destination = _roots(base_dir, copy_dir, 'existing')
    _existing_root(base, destination)


def _existing_parent(base, destination, parent):
    _existing_root(base, destination)
    _no_symlinks(destination, parent)
    current = destination
    for part in parent.relative_to(destination).parts:
        current /= part
        # Never use parents=True here: a removed selected root must stay absent.
        current.mkdir(exist_ok=True)
    _existing_root(base, destination)
    _no_symlinks(destination, parent)


def _reserve_existing_copy(parent, source):
    # The parent has already been prepared within a checked, existing root.
    # Unlike the named-folder helper, reservation cannot recreate that root.
    index = 1
    while True:
        stem = source.stem if index == 1 else f'{source.stem}_{index}'
        target = parent / f'{stem}{source.suffix}'
        try:
            with target.open('xb'):
                pass
            return target
        except FileExistsError:
            index += 1


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
                          manifest: dict, persist, copy_mode: str = 'subfolder') -> None:
    validate_copy_manifest(base_dir=base_dir, copy_dir=copy_dir, manifest=manifest, copy_mode=copy_mode)
    base, destination = _roots(base_dir, copy_dir, copy_mode)
    existing = copy_mode == 'existing'
    target_root = destination if existing else base
    if existing:
        _existing_root(base, destination)
    planned = []
    seen = set()
    # Reject all unsafe inputs before reservations, manifest writes or publication.
    for value in sources:
        source, relative = _relative_source(value, base, destination)
        if str(source) in seen:
            continue
        seen.add(str(source))
        _no_symlinks(base, source)
        _no_symlinks(target_root, (destination / relative).parent)
        if not source.is_file():
            raise OSError('A primary output is unavailable for copying')
        planned.append((source, relative, _sha256(source)))
    for record in manifest.get('copy_exports', {}).values():
        _no_symlinks(target_root, Path(record['path']).parent)

    if existing:
        _existing_root(base, destination)

    exports = manifest.setdefault('copy_exports', {})
    manifest['copy_pending'] = True
    persist()
    for source, relative, digest in planned:
        if existing:
            _existing_root(base, destination)
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
            if existing:
                _existing_parent(base, destination, parent)
                target = _reserve_existing_copy(parent, source)
            else:
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
        if existing:
            _existing_root(base, destination)
        if _target_state(target) != expected_state:
            raise OSError('The additional copy changed before delivery; retry to preserve the edited file')
        if current_hash != digest:
            if existing:
                _existing_parent(base, destination, target.parent)
            else:
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
