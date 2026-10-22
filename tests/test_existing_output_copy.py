"""Explicit existing-folder delivery keeps the named-copy safety contract."""
import copy
import hashlib
from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from output_copy import deliver_output_copies, validate_copy_manifest
import output_copy


@pytest.fixture
def outputs(tmp_path):
    root = tmp_path.resolve()
    base = root / 'output'
    sources = [base / 'epub' / 'Könyv.txt', base / 'quotes' / 'Ősz.md']
    for source in sources:
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes('Árvíztűrő tükörfúrógép.\r\nMásodik sor.\n'.encode())
    destination = root / 'Selected folder'
    destination.mkdir()
    return base, sources, destination


def deliver(outputs, manifest, persist=lambda: None):
    base, sources, destination = outputs
    deliver_output_copies(sources, base_dir=base, copy_dir=destination,
                          copy_mode='existing', manifest=manifest, persist=persist)


@pytest.mark.parametrize('folder_name', ['Selected folder', 'epub', 'quotes'])
def test_existing_folder_outside_save_to_keeps_exact_bytes_and_format_subfolders(outputs, folder_name):
    base, sources, _ = outputs
    destination = base.parent / folder_name
    destination.mkdir(exist_ok=True)
    manifest = {}
    before = [source.read_bytes() for source in sources]
    deliver((base, sources, destination), manifest)
    assert (destination / 'epub' / 'Könyv.txt').read_bytes() == before[0]
    assert (destination / 'quotes' / 'Ősz.md').read_bytes() == before[1]
    assert [source.read_bytes() for source in sources] == before
    assert manifest['copy_pending'] is False


def test_existing_non_primary_nested_folder_inside_save_to_is_allowed(outputs):
    base, sources, _ = outputs
    destination = base / 'Research' / 'Published'
    destination.mkdir(parents=True)
    deliver((base, sources, destination), {})
    assert (destination / 'epub' / 'Könyv.txt').read_bytes() == sources[0].read_bytes()


def test_existing_mode_metadata_loads_without_accessing_a_missing_destination(outputs):
    base, sources, _ = outputs
    destination = base.parent / 'Disconnected drive' / 'Selected folder'
    manifest = {'copy_pending': True, 'copy_exports': {str(sources[0]): {
        'path': str(destination / 'epub' / 'Könyv.txt'),
        'sha256': None, 'pending_sha256': hashlib.sha256(sources[0].read_bytes()).hexdigest()}}}
    before = copy.deepcopy(manifest)
    validate_copy_manifest(base_dir=base, copy_dir=destination, copy_mode='existing', manifest=manifest)
    assert manifest == before
    assert not destination.parent.exists()


@pytest.mark.parametrize('previously_delivered', [False, True])
def test_missing_selected_root_is_never_recreated_or_checkpointed(outputs, previously_delivered):
    manifest = {}
    if previously_delivered:
        deliver(outputs, manifest)
    destination = outputs[2]
    shutil.rmtree(destination)
    before = copy.deepcopy(manifest)
    persisted = []
    with pytest.raises(OSError):
        deliver(outputs, manifest, lambda: persisted.append(copy.deepcopy(manifest)))
    assert not destination.exists()
    assert manifest == before and persisted == []
    assert all(source.is_file() for source in outputs[1])


def test_selected_root_replaced_by_a_file_is_rejected_without_changes(outputs):
    destination = outputs[2]
    destination.rmdir()
    destination.write_bytes(b'Keep this unrelated file')
    manifest = {}
    with pytest.raises(OSError):
        deliver(outputs, manifest)
    assert destination.read_bytes() == b'Keep this unrelated file'
    assert manifest == {}


def test_selected_root_removed_during_delivery_is_not_recreated(outputs):
    destination = outputs[2]
    manifest = {}
    def persist():
        if destination.exists():
            shutil.rmtree(destination)
    with pytest.raises(OSError):
        deliver(outputs, manifest, persist)
    assert not destination.exists()
    assert manifest['copy_pending'] is True
    assert all(source.is_file() for source in outputs[1])


@pytest.mark.parametrize('kind', ['same', 'ancestor', 'primary', 'nested_primary', 'uppercase_primary'])
def test_existing_mode_cannot_overlap_primary_output_locations(outputs, kind):
    base, _, _ = outputs
    destinations = {'same': base, 'ancestor': base.parent, 'primary': base / 'quotes',
                    'nested_primary': base / 'epub' / 'Saved copies', 'uppercase_primary': base / 'PDF'}
    destination = destinations[kind]
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {}
    with pytest.raises(ValueError):
        deliver((base, outputs[1], destination), manifest)
    assert manifest == {}


@pytest.mark.parametrize('folder', ['quotes', 'pdf', 'docx', 'spreadsheets', 'html', 'txt', 'rtf', 'epub'])
def test_each_primary_format_subtree_is_rejected_without_filesystem_access(outputs, folder):
    base, _, _ = outputs
    destination = base / folder / 'Existing copies'
    with pytest.raises(ValueError):
        validate_copy_manifest(base_dir=base, copy_dir=destination, copy_mode='existing', manifest={})
    assert not destination.exists()


@pytest.mark.parametrize('copy_mode', [None, False, True, '', 'external', [], {}])
def test_unknown_modes_do_not_relax_destination_constraints(outputs, copy_mode):
    base, _, destination = outputs
    with pytest.raises(ValueError):
        validate_copy_manifest(base_dir=base, copy_dir=destination, copy_mode=copy_mode, manifest={})
    assert list(destination.iterdir()) == []


@pytest.mark.parametrize('explicit_mode', [False, True])
def test_legacy_subfolder_mode_still_rejects_external_destinations(outputs, explicit_mode):
    base, sources, destination = outputs
    kwargs = {'copy_mode': 'subfolder'} if explicit_mode else {}
    with pytest.raises(ValueError):
        deliver_output_copies(sources, base_dir=base, copy_dir=destination,
                              manifest={}, persist=lambda: None, **kwargs)
    assert list(destination.iterdir()) == []


def test_existing_source_inside_destination_cannot_be_copied_recursively(outputs):
    base, _, _ = outputs
    destination = base / 'Research'
    destination.mkdir()
    source = destination / 'original.md'
    source.write_bytes(b'Original copy output')
    with pytest.raises(ValueError):
        deliver((base, [source], destination), {})
    assert list(destination.iterdir()) == [source]


@pytest.mark.parametrize('replacement', ['root', 'ancestor', 'descendant'])
def test_symlink_replacements_cannot_redirect_selected_destination(outputs, replacement):
    base, sources, destination = outputs
    outside = base.parent / 'Outside'
    outside.mkdir()
    if replacement == 'root':
        destination.rmdir()
        destination.symlink_to(outside, target_is_directory=True)
    elif replacement == 'ancestor':
        parent = base.parent / 'Selected parent'
        destination = parent / 'Selected folder'
        destination.mkdir(parents=True)
        parent.rename(base.parent / 'Moved original parent')
        (outside / 'Selected folder').mkdir()
        parent.symlink_to(outside, target_is_directory=True)
    else:
        (destination / 'epub').symlink_to(outside, target_is_directory=True)
    before = sorted(str(path) for path in outside.rglob('*'))
    manifest = {}
    with pytest.raises(ValueError):
        deliver((base, sources, destination), manifest)
    assert manifest == {}
    assert sorted(str(path) for path in outside.rglob('*')) == before
    assert not list(outside.rglob('*.md')) and not list(outside.rglob('*.txt'))


@pytest.mark.parametrize('tamper', ['outside_target', 'wrong_subfolder', 'source_outside_save_to'])
def test_existing_mode_manifest_cannot_redirect_or_change_its_sources(outputs, tamper):
    base, sources, destination = outputs
    source_key = str(sources[0])
    target = destination / 'epub' / 'Könyv.txt'
    if tamper == 'outside_target':
        target = base.parent / 'Unrelated' / 'epub' / 'Könyv.txt'
    elif tamper == 'wrong_subfolder':
        target = destination / 'quotes' / 'Könyv.txt'
    else:
        source_key = str(base.parent / 'Private.txt')
    manifest = {'copy_exports': {source_key: {'path': str(target), 'sha256': None, 'pending_sha256': None}}}
    before = copy.deepcopy(manifest)
    with pytest.raises(ValueError):
        deliver(outputs, manifest)
    assert manifest == before and list(destination.iterdir()) == []


def test_existing_folder_preserves_unrelated_and_edited_files_and_retries_idempotently(outputs):
    destination = outputs[2]
    unrelated = destination / 'epub' / 'Könyv.txt'
    unrelated.parent.mkdir()
    unrelated.write_bytes(b'Unrelated existing notes')
    manifest = {}
    deliver(outputs, manifest)
    first_copy = Path(manifest['copy_exports'][str(outputs[1][0])]['path'])
    assert first_copy == unrelated.with_name('Könyv_2.txt')
    assert unrelated.read_bytes() == b'Unrelated existing notes'
    first_copy.write_bytes(b'User edited the delivered copy')
    deliver(outputs, manifest)
    replacement = Path(manifest['copy_exports'][str(outputs[1][0])]['path'])
    assert replacement == unrelated.with_name('Könyv_3.txt')
    assert replacement.read_bytes() == outputs[1][0].read_bytes()
    assert first_copy.read_bytes() == b'User edited the delivered copy'
    before = copy.deepcopy(manifest)
    deliver(outputs, manifest)
    assert manifest == before
    assert len(list(destination.rglob('*.txt'))) == 3


def test_existing_folder_repairs_crash_after_copy_without_duplicate_publication(outputs):
    manifest, persisted = {}, {}
    source = outputs[1][0]
    def persist():
        nonlocal persisted
        record = manifest.get('copy_exports', {}).get(str(source), {})
        if record.get('sha256') and record.get('pending_sha256') is None:
            raise OSError('Receipt persistence failed')
        persisted = copy.deepcopy(manifest)
    with pytest.raises(OSError, match='Receipt persistence failed'):
        deliver(outputs, manifest, persist)
    first_target = Path(persisted['copy_exports'][str(source)]['path'])
    assert first_target.read_bytes() == source.read_bytes()
    deliver(outputs, persisted)
    assert Path(persisted['copy_exports'][str(source)]['path']) == first_target
    assert persisted['copy_pending'] is False
    assert len(list(outputs[2].rglob('*.txt'))) == 1


@pytest.fixture
def case_alias_outputs(tmp_path):
    root = tmp_path.resolve()
    parent = root / 'Archive'
    base = parent / 'Exports'
    source = base / 'epub' / 'Könyv.txt'
    source.parent.mkdir(parents=True)
    source.write_bytes('Keep the primary book unchanged.\r\n'.encode())
    alias = root / 'archive'
    if not alias.exists() or not alias.samefile(parent):
        pytest.skip('Mounted filesystem is case-sensitive')
    return root, base, source


def alias_destination(case_alias_outputs, kind):
    root, base, _ = case_alias_outputs
    if kind == 'same':
        return root / 'Archive' / 'exports'
    if kind == 'ancestor':
        return root / 'archive'
    if kind == 'primary':
        return root / 'archive' / 'Exports' / 'epub'
    (base / 'epub' / 'Published').mkdir()
    return root / 'archive' / 'exports' / 'EPUB' / 'Published'


@pytest.mark.parametrize('kind', ['same', 'ancestor', 'primary', 'nested_primary'])
def test_delivery_rejects_mounted_case_alias_overlaps_without_writes(case_alias_outputs, kind):
    _, base, source = case_alias_outputs
    destination = alias_destination(case_alias_outputs, kind)
    before = source.read_bytes()
    manifest = {}
    with pytest.raises(ValueError):
        deliver((base, [source], destination), manifest)
    assert manifest == {}
    assert source.read_bytes() == before
    assert list(base.rglob('*.txt')) == [source]


@pytest.mark.parametrize('kind', ['same', 'ancestor', 'primary', 'nested_primary'])
def test_picker_validation_rejects_mounted_case_alias_overlaps(case_alias_outputs, kind):
    _, base, source = case_alias_outputs
    destination = alias_destination(case_alias_outputs, kind)
    with pytest.raises(ValueError):
        output_copy.validate_existing_copy_directory(base_dir=base, copy_dir=destination)
    assert list(base.rglob('*.txt')) == [source]


def test_case_alias_non_primary_subtree_remains_a_valid_existing_destination(case_alias_outputs):
    root, base, source = case_alias_outputs
    (base / 'Research' / 'Published').mkdir(parents=True)
    destination = root / 'archive' / 'exports' / 'Research' / 'Published'
    output_copy.validate_existing_copy_directory(base_dir=base, copy_dir=destination)
    deliver((base, [source], destination), {})
    assert (destination / 'epub' / 'Könyv.txt').read_bytes() == source.read_bytes()


def test_picker_validation_checks_availability_without_creating_selected_root(outputs):
    base, _, destination = outputs
    output_copy.validate_existing_copy_directory(base_dir=base, copy_dir=destination)
    assert list(destination.iterdir()) == []
    destination.rmdir()
    with pytest.raises(OSError):
        output_copy.validate_existing_copy_directory(base_dir=base, copy_dir=destination)
    assert not destination.exists()


def test_selected_root_disappearing_during_identity_check_is_unavailable(outputs, monkeypatch):
    base, _, destination = outputs
    is_dir = Path.is_dir
    def check_then_remove(path):
        result = is_dir(path)
        if path == destination and result:
            destination.rmdir()
        return result
    monkeypatch.setattr(Path, 'is_dir', check_then_remove)
    with pytest.raises(OSError):
        output_copy.validate_existing_copy_directory(base_dir=base, copy_dir=destination)
    assert not destination.exists()
