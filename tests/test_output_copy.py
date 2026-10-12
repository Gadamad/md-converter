import copy
import hashlib
import json
import shutil
from pathlib import Path
import sys
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def module():
    import output_copy
    return output_copy


@pytest.fixture
def outputs(tmp_path):
    base = tmp_path / 'saved'
    sources = [base / 'xlsx' / 'Költségek' / 'Első lap.md', base / 'quotes' / 'Ősz.md']
    for source in sources:
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes('Árvíztűrő tükörfúrógép\r\nŐsz és öröm.\n'.encode())
    return base, sources, base / 'Másolatok'


def deliver(outputs, manifest, persist=lambda: None):
    base, sources, destination = outputs
    module().deliver_output_copies(sources, base_dir=base, copy_dir=destination,
                                  manifest=manifest, persist=persist)


def test_exact_bytes_subfolders_and_durable_plans(outputs):
    manifest, snapshots = {}, []
    deliver(outputs, manifest, lambda: snapshots.append(copy.deepcopy(manifest)))
    base, sources, destination = outputs
    assert manifest['copy_pending'] is False
    for source in sources:
        record = manifest['copy_exports'][str(source)]
        assert Path(record['path']) == destination / source.relative_to(base)
        assert Path(record['path']).read_bytes() == source.read_bytes()
        assert record['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
        assert record['pending_sha256'] is None
        assert any(s['copy_pending'] and s['copy_exports'].get(str(source), {}).get('pending_sha256')
                   for s in snapshots)
    json.dumps(manifest)


def test_retry_reuses_delivered_paths_without_writes(outputs):
    manifest = {}
    deliver(outputs, manifest)
    before = copy.deepcopy(manifest)
    with mock.patch.object(module(), 'atomic_copy_file') as write:
        deliver(outputs, manifest)
    write.assert_not_called()
    assert manifest == before


def test_unrelated_and_user_edited_copies_are_preserved(outputs):
    base, sources, destination = outputs
    existing = destination / sources[0].relative_to(base)
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b'unrelated')
    manifest = {}
    deliver(outputs, manifest)
    owned = Path(manifest['copy_exports'][str(sources[0])]['path'])
    assert owned.stem.endswith('_2') and existing.read_bytes() == b'unrelated'
    owned.write_bytes(b'edited by user')
    sources[0].write_bytes('Új tartalom.'.encode())
    deliver(outputs, manifest)
    replacement = Path(manifest['copy_exports'][str(sources[0])]['path'])
    assert replacement.stem.endswith('_3')
    assert owned.read_bytes() == b'edited by user'
    assert replacement.read_bytes() == sources[0].read_bytes()


def test_partial_failure_retry_preserves_first_copy_and_reservations(outputs):
    manifest = {}
    copier = module().atomic_copy_file
    calls = []
    def fail_second(source, target, **kwargs):
        calls.append(source)
        if len(calls) == 2:
            raise OSError('disk full')
        copier(source, target, **kwargs)
    with mock.patch.object(module(), 'atomic_copy_file', side_effect=fail_second):
        with pytest.raises(OSError, match='disk full'):
            deliver(outputs, manifest)
    paths = [record['path'] for record in manifest['copy_exports'].values()]
    assert manifest['copy_pending'] is True
    deliver(outputs, manifest)
    assert [record['path'] for record in manifest['copy_exports'].values()] == paths
    assert manifest['copy_pending'] is False


def test_crash_after_copy_before_receipt_commit_is_recoverable(outputs):
    manifest = {}
    persisted = {}
    def persist():
        nonlocal persisted
        record = manifest.get('copy_exports', {}).get(str(outputs[1][0]), {})
        if record.get('sha256') and record.get('pending_sha256') is None:
            raise OSError('receipt failed')
        persisted = copy.deepcopy(manifest)
    with pytest.raises(OSError, match='receipt failed'):
        deliver(outputs, manifest, persist)
    target = persisted['copy_exports'][str(outputs[1][0])]['path']
    assert Path(target).read_bytes() == outputs[1][0].read_bytes()
    outputs[1][0].write_bytes('Changed source after interrupted delivery.'.encode())
    deliver(outputs, persisted)
    assert persisted['copy_exports'][str(outputs[1][0])]['path'] == target
    assert Path(target).read_bytes() == outputs[1][0].read_bytes()


@pytest.mark.parametrize('kind', ['bad_record', 'bad_hash', 'wrong_parent', 'outside', 'journal'])
def test_bad_metadata_and_sources_rejected_before_writes(outputs, kind, tmp_path):
    base, sources, destination = outputs
    record = {'path': str(destination / sources[0].relative_to(base)), 'sha256': None, 'pending_sha256': None}
    manifest = {'copy_exports': {str(sources[0]): record}}
    if kind == 'bad_record':
        record['unknown'] = 'bad'
    elif kind == 'bad_hash':
        record['sha256'] = 'not a hash'
    elif kind == 'wrong_parent':
        record['path'] = str(destination / 'wrong.md')
    elif kind == 'outside':
        record['path'] = str(tmp_path / 'outside.md')
    else:
        sources[1] = sources[1].with_suffix('.json')
        sources[1].write_text('{}')
    with pytest.raises(ValueError):
        deliver(outputs, manifest)
    assert not destination.exists()


@pytest.mark.parametrize('target', ['same', 'nested', 'traversal', 'relative'])
def test_invalid_copy_roots_are_rejected(outputs, target):
    base, sources, destination = outputs
    bad = {'same': base, 'nested': destination / 'nested', 'traversal': base / '..' / 'escape',
           'relative': Path('relative')}[target]
    with pytest.raises(ValueError):
        module().deliver_output_copies(sources, base_dir=base, copy_dir=bad, manifest={}, persist=lambda: None)
    assert not destination.exists()


def test_destination_directory_symlink_cannot_escape(outputs, tmp_path):
    base, sources, destination = outputs
    outside = tmp_path / 'outside'
    outside.mkdir()
    destination.mkdir()
    (destination / 'xlsx').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        deliver(outputs, {})
    assert list(outside.iterdir()) == []


def test_source_symlink_is_not_copied(outputs, tmp_path):
    source = outputs[1][0]
    source.unlink()
    outside = tmp_path / 'outside.md'
    outside.write_text('private outside file')
    source.symlink_to(outside)
    with pytest.raises(ValueError):
        deliver(outputs, {})
    assert not outputs[2].exists()


def test_metadata_validation_does_not_require_accessible_destination(outputs):
    base, sources, destination = outputs
    destination.write_bytes(b'blocking file')
    manifest = {}
    module().validate_copy_manifest(base_dir=base, copy_dir=destination, manifest=manifest)
    with pytest.raises(OSError):
        deliver(outputs, manifest)
    assert manifest['copy_pending'] is True
    assert all(source.is_file() for source in sources)


def test_atomic_copy_failure_does_not_replace_previous_content(outputs):
    source = outputs[1][0]
    target = source.with_name('target.md')
    target.write_bytes(b'previous')
    with mock.patch.object(module().os, 'replace', side_effect=OSError('replace failed')):
        with pytest.raises(OSError):
            module().atomic_copy_file(source, target)
    assert target.read_bytes() == b'previous'
    assert not list(target.parent.glob('.target.md.*'))


def test_user_edit_during_manifest_persistence_is_not_overwritten(outputs):
    manifest = {}
    deliver(outputs, manifest)
    source = outputs[1][0]
    source.write_bytes(b'new generated content')
    target = Path(manifest['copy_exports'][str(source)]['path'])
    edited = False
    def persist():
        nonlocal edited
        record = manifest['copy_exports'][str(source)]
        if record['pending_sha256'] and not edited:
            target.write_bytes(b'user edit during delivery')
            edited = True
    with pytest.raises(OSError, match='changed'):
        deliver(outputs, manifest, persist)
    assert target.read_bytes() == b'user edit during delivery'
    assert manifest['copy_pending'] is True
    deliver(outputs, manifest)
    replacement = Path(manifest['copy_exports'][str(source)]['path'])
    assert replacement != target and replacement.read_bytes() == source.read_bytes()
    assert target.read_bytes() == b'user edit during delivery'


def test_retry_recreates_removed_copy_subdirectories_without_duplicates(outputs):
    manifest = {}
    deliver(outputs, manifest)
    paths = [r['path'] for r in manifest['copy_exports'].values()]
    shutil.rmtree(outputs[2])
    deliver(outputs, manifest)
    assert [r['path'] for r in manifest['copy_exports'].values()] == paths
    assert all(Path(path).is_file() for path in paths)


def test_edited_copy_matching_new_source_still_publishes_reserved_replacement(outputs):
    manifest = {}
    deliver(outputs, manifest)
    source = outputs[1][0]
    previous = Path(manifest['copy_exports'][str(source)]['path'])
    source.write_bytes(b'same new bytes')
    previous.write_bytes(b'same new bytes')
    deliver(outputs, manifest)
    target = Path(manifest['copy_exports'][str(source)]['path'])
    assert target != previous
    assert target.read_bytes() == source.read_bytes()


def test_edit_during_up_to_date_delivery_is_not_reported_as_complete(outputs):
    manifest = {}
    deliver(outputs, manifest)
    source = outputs[1][0]
    target = Path(manifest['copy_exports'][str(source)]['path'])
    def persist():
        if manifest['copy_exports'][str(source)]['pending_sha256']:
            target.write_bytes(b'user edited unchanged copy')
    with pytest.raises(OSError, match='changed'):
        deliver(outputs, manifest, persist)
    assert manifest['copy_pending'] is True
    assert target.read_bytes() == b'user edited unchanged copy'
