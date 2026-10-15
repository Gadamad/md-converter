"""Plain-text book copies retain the same safety guarantees as Markdown."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from output_copy import deliver_output_copies, validate_copy_manifest


def test_plain_text_copies_keep_accents_bytes_and_user_edits(tmp_path):
    base = tmp_path / 'output'
    source = base / 'epub' / 'book.txt'
    source.parent.mkdir(parents=True)
    source.write_bytes('Árvíztűrő tükörfúrógép.\r\nMásodik bekezdés.\n'.encode())
    destination = base / 'Saved books'
    manifest = {}
    deliver = lambda: deliver_output_copies([source], base_dir=base, copy_dir=destination,
                                            manifest=manifest, persist=lambda: None)
    deliver()
    copied = destination / 'epub' / 'book.txt'
    assert copied.read_bytes() == source.read_bytes()
    copied.write_bytes(b'User annotations')
    deliver()
    assert copied.read_bytes() == b'User annotations'
    replacement = Path(manifest['copy_exports'][str(source)]['path'])
    assert replacement == copied.with_name('book_2.txt')
    assert replacement.read_bytes() == source.read_bytes()
    deliver()
    assert len(list(destination.rglob('*.txt'))) == 2


def test_text_copy_receipt_cannot_redirect_to_a_different_extension(tmp_path):
    base = tmp_path / 'output'
    destination = base / 'Saved books'
    source = base / 'epub' / 'book.txt'
    manifest = {'copy_exports': {str(source): {
        'path': str(destination / 'epub' / 'book.md'), 'sha256': None, 'pending_sha256': None}}}
    with pytest.raises(ValueError):
        validate_copy_manifest(base_dir=base, copy_dir=destination, manifest=manifest)


@pytest.mark.parametrize('suffix', ['.epub', '.json', '.rtf'])
def test_copy_support_does_not_expand_to_arbitrary_source_files(tmp_path, suffix):
    base = tmp_path / 'output'
    source = base / 'epub' / ('book' + suffix)
    source.parent.mkdir(parents=True)
    source.write_text('Private source data')
    destination = base / 'Saved books'
    with pytest.raises(ValueError):
        deliver_output_copies([source], base_dir=base, copy_dir=destination,
                              manifest={}, persist=lambda: None)
    assert not destination.exists()
