"""Real EPUB routing, frozen queue options, and durable text delivery."""
import hashlib
import json
from pathlib import Path
import re
import sys
import threading
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import converters
from output_copy import deliver_output_copies, validate_copy_manifest
from queue_runner import QueueRunner
from queue_store import QueueStore


TITLE = 'Ősz és öröm'
AUTHOR = 'Tóth Árpád'
FIRST = 'Árvíztűrő tükörfúrógép őrzi a bátor szavakat.'
SECOND = 'Második történet: öröm és hűség.'
NOTE = 'Kiegészítő jegyzet a könyv végén.'


def make_epub(path, *, encrypted=False):
    """Archive/manifest order deliberately disagrees with the reading order."""
    container = '''<?xml version="1.0" encoding="UTF-8"?>
    <container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
      <rootfiles><rootfile full-path="EPUB/package.opf"
        media-type="application/oebps-package+xml"/></rootfiles>
    </container>'''
    package = f'''<?xml version="1.0" encoding="UTF-8"?>
    <package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
      <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
        <dc:identifier id="id">urn:uuid:epub-delivery-fixture</dc:identifier>
        <dc:title>{TITLE}</dc:title><dc:creator>{AUTHOR}</dc:creator>
        <dc:language>hu</dc:language>
        <meta property="dcterms:modified">2026-10-15T00:00:00Z</meta>
      </metadata>
      <manifest>
        <item id="second" href="Text/second.xhtml" media-type="application/xhtml+xml"/>
        <item id="notes" href="Text/notes.xhtml" media-type="application/xhtml+xml"/>
        <item id="nav" href="nav.xhtml" properties="nav" media-type="application/xhtml+xml"/>
        <item id="first" href="Text/first.xhtml" media-type="application/xhtml+xml"/>
      </manifest>
      <spine><itemref idref="nav"/><itemref idref="first"/>
        <itemref idref="second"/><itemref idref="notes" linear="no"/></spine>
    </package>'''
    first = '''<html xmlns="http://www.w3.org/1999/xhtml"><head><title>First</title></head>
      <body><header><h1>Első fejezet</h1></header>
      <p>Árvíztűrő tükörfúrógép őrzi a <strong>bátor</strong> szavakat.</p>
      <ul><li>Őszinte gondolat</li><li>Hűséges emlék</li></ul>
      <script>DO_NOT_EXPORT_SCRIPT</script></body></html>'''
    second = f'''<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Second</title></head>
      <body><h2>Második fejezet</h2><p>{SECOND}</p></body></html>'''
    notes = f'''<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Notes</title></head>
      <body><h2>Jegyzetek</h2><p>{NOTE}</p></body></html>'''
    nav = '''<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
      <head><title>Contents</title></head><body><nav epub:type="toc">
      <h1>DO_NOT_EXPORT_NAVIGATION</h1><ol><li><a href="Text/first.xhtml">First</a></li>
      <li><a href="Text/second.xhtml">Second</a></li></ol></nav></body></html>'''
    with ZipFile(path, 'w') as archive:
        archive.writestr('mimetype', 'application/epub+zip', compress_type=ZIP_STORED)
        for name, content in (
                ('EPUB/Text/second.xhtml', second), ('EPUB/Text/notes.xhtml', notes),
                ('EPUB/nav.xhtml', nav), ('META-INF/container.xml', container),
                ('EPUB/package.opf', package), ('EPUB/Text/first.xhtml', first)):
            archive.writestr(name, content, compress_type=ZIP_DEFLATED)
        if encrypted:
            archive.writestr('META-INF/encryption.xml', '''
              <encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container"
                          xmlns:enc="http://www.w3.org/2001/04/xmlenc#">
                <enc:EncryptedData><enc:EncryptionMethod Algorithm="urn:fixture:drm"/>
                  <enc:CipherData><enc:CipherReference URI="EPUB/Text/first.xhtml"/>
                  </enc:CipherData></enc:EncryptedData>
              </encryption>''')
    return path


@pytest.fixture
def book_path(tmp_path):
    return make_epub(tmp_path / 'Eredeti könyv.epub')


def make_queue(tmp_path, paths):
    store = QueueStore(tmp_path / 'queues.sqlite3')
    store.add_items(store.active_id, [
        {'kind': 'file', 'source': str(path), 'title': path.name} for path in paths
    ])
    return store


def options(tmp_path, output_format='md', *, deliveries=False):
    output = tmp_path / 'output'
    return {
        'output_dir': str(output), 'raw_ocr_mode': 'different',
        'epub_output_format': output_format,
        'vault_dir': str(tmp_path / 'vault') if deliveries else None,
        'copy_dir': str(output / 'Árvíztűrő másolatok') if deliveries else None,
    }


def assert_plain_text(content):
    assert FIRST in content and SECOND in content and NOTE in content
    assert 'DO_NOT_EXPORT_NAVIGATION' not in content
    assert 'DO_NOT_EXPORT_SCRIPT' not in content
    assert not re.search(r'^\s*(?:#{1,6}\s|>\s|---\s*$|[-*+]\s)', content, re.MULTILINE)
    assert '**bátor**' not in content
    assert '<strong>' not in content
    assert 'Word Count' not in content and '**Source**' not in content


def test_epub_routes_to_markdown_by_default_without_changing_original(book_path, tmp_path):
    original = book_path.read_bytes()
    modified = book_path.stat().st_mtime_ns
    result = converters.route(str(book_path), tmp_path / 'output')
    assert result.success, result.message
    target = Path(result.output_path)
    assert target.parent == tmp_path / 'output' / 'epub'
    assert target.suffix == '.md'
    content = target.read_text(encoding='utf-8')
    assert TITLE in content and AUTHOR in content
    assert '# Első fejezet' in content and '## Második fejezet' in content
    assert '**bátor**' in content
    assert content.index('Árvíztűrő') < content.index(SECOND) < content.index(NOTE)
    assert 'DO_NOT_EXPORT_NAVIGATION' not in content
    assert 'DO_NOT_EXPORT_SCRIPT' not in content
    assert book_path.read_bytes() == original
    assert book_path.stat().st_mtime_ns == modified


def test_epub_txt_is_plain_utf8_and_vault_delivery_is_markdown(book_path, tmp_path):
    result = converters.route(str(book_path), tmp_path / 'output', tmp_path / 'vault',
                              epub_output_format='txt')
    assert result.success, result.message
    target = Path(result.output_path)
    assert target.parent == tmp_path / 'output' / 'epub' and target.suffix == '.txt'
    content = target.read_text(encoding='utf-8')
    assert_plain_text(content)
    assert TITLE in content and AUTHOR in content
    notes = list((tmp_path / 'vault' / 'epub').glob('*.md'))
    assert len(notes) == 1 and not list((tmp_path / 'vault').rglob('*.txt'))
    vault_content = notes[0].read_text(encoding='utf-8')
    assert vault_content.startswith('---\n') and 'tags: [converted, epub]' in vault_content
    assert content.strip() in vault_content


@pytest.mark.parametrize('output_format', ['md', 'txt'])
def test_direct_epub_converter_accepts_output_format_keyword(book_path, tmp_path, output_format):
    result = converters.convert_epub(str(book_path), tmp_path / 'direct',
                                     output_format=output_format)
    assert result.success, result.message
    assert len(result) == 4, 'Existing converter callers unpack the four-field ConvertResult'
    assert Path(result.output_path).suffix == f'.{output_format}'
    assert SECOND in Path(result.output_path).read_text(encoding='utf-8')


@pytest.mark.parametrize('output_format', ['md', 'txt'])
def test_repeated_direct_conversion_preserves_existing_outputs(book_path, tmp_path, output_format):
    first = converters.route(str(book_path), tmp_path / 'output', epub_output_format=output_format)
    assert first.success, first.message
    first_path = Path(first.output_path)
    first_path.write_text('User edited the first export.', encoding='utf-8')
    second = converters.route(str(book_path), tmp_path / 'output', epub_output_format=output_format)
    assert second.success, second.message
    assert Path(second.output_path) != first_path
    assert Path(second.output_path).suffix == f'.{output_format}'
    assert first_path.read_text(encoding='utf-8') == 'User edited the first export.'
    assert SECOND in Path(second.output_path).read_text(encoding='utf-8')


@pytest.mark.parametrize('output_format', ['md', 'txt'])
def test_epub_queue_snapshots_format_and_preserves_delivery_extensions(book_path, tmp_path, output_format):
    store = make_queue(tmp_path, [book_path])
    selected = options(tmp_path, output_format, deliveries=True)
    state = QueueRunner(store, tmp_path / 'cache', selected).run(store.active_id)
    assert state['done'] == 1, state['items'][0]['error']
    item = state['items'][0]
    assert item['options']['epub_output_format'] == output_format
    primary = Path(item['output_path'])
    assert primary.parent == Path(selected['output_dir']) / 'epub'
    assert primary.suffix == f'.{output_format}'
    copied = Path(selected['copy_dir']) / primary.relative_to(selected['output_dir'])
    assert copied.read_bytes() == primary.read_bytes()
    notes = list((Path(selected['vault_dir']) / 'epub').glob('*.md'))
    assert len(notes) == 1 and not list(Path(selected['vault_dir']).rglob('*.txt'))
    assert notes[0].read_text(encoding='utf-8').startswith('---\n')
    assert primary.read_text(encoding='utf-8').strip() in notes[0].read_text(encoding='utf-8')
    if output_format == 'txt':
        assert_plain_text(primary.read_text(encoding='utf-8'))


def test_txt_copy_retry_reuses_private_conversion_after_source_and_preferences_change(book_path, tmp_path):
    store = make_queue(tmp_path, [book_path])
    selected = options(tmp_path, 'txt', deliveries=True)
    output, copy_dir = Path(selected['output_dir']), Path(selected['copy_dir'])
    output.mkdir()
    copy_dir.write_text('A file blocks this copy destination.', encoding='utf-8')
    state = QueueRunner(store, tmp_path / 'cache', selected).run(store.active_id)
    assert state['failed'] == 1
    item = state['items'][0]
    assert item['output_path'], item['error']
    primary = Path(item['output_path'])
    assert primary.suffix == '.txt' and primary.is_file()
    assert 'saved' in item['error'].lower() and 'copy' in item['error'].lower()
    saved_bytes = primary.read_bytes()
    receipt = json.loads(Path(item['receipt_path']).read_text(encoding='utf-8'))
    private = Path(receipt['source_output'])
    before = private.stat().st_mtime_ns, hashlib.sha256(private.read_bytes()).hexdigest()
    copy_dir.unlink()
    book_path.unlink()
    changed = {**selected, 'epub_output_format': 'md',
               'output_dir': str(tmp_path / 'other-output'),
               'copy_dir': str(tmp_path / 'other-output' / 'Other copies'),
               'vault_dir': str(tmp_path / 'other-vault')}
    restarted = QueueStore(store.path)
    def no_reconversion(*args, **kwargs):
        pytest.fail('A saved delivery retry must not reopen or convert the original EPUB')
    state = QueueRunner(restarted, tmp_path / 'cache', changed,
                        route_fn=no_reconversion).run(restarted.active_id, retry_failed=True)
    assert state['done'] == 1, state['items'][0]['error']
    restored = state['items'][0]
    assert restored['options']['epub_output_format'] == 'txt'
    assert Path(restored['output_path']) == primary and primary.read_bytes() == saved_bytes
    assert (copy_dir / primary.relative_to(output)).read_bytes() == saved_bytes
    assert (private.stat().st_mtime_ns, hashlib.sha256(private.read_bytes()).hexdigest()) == before
    assert not Path(changed['output_dir']).exists() and not Path(changed['vault_dir']).exists()
    assert len(list(output.joinpath('epub').glob('*.txt'))) == 1
    assert len(list((tmp_path / 'vault' / 'epub').glob('*.md'))) == 1


def test_old_markdown_receipt_stays_markdown_when_current_preference_is_txt(tmp_path):
    source = tmp_path / 'legacy.txt'
    source.write_text('Legacy source.', encoding='utf-8')
    store = make_queue(tmp_path, [source])
    item = store.items(store.active_id)[0]
    private = tmp_path / 'cache' / item['id'] / 'converted' / 'txt' / 'legacy.md'
    private.parent.mkdir(parents=True)
    private.write_text('# Saved legacy Markdown\n\nKeep **this** unchanged.\n', encoding='utf-8')
    receipt_path = private.parents[2] / 'receipt.json'
    receipt_path.write_text(json.dumps({'source_output': str(private), 'word_count': 7,
                                       'format': 'txt', 'filename': 'legacy.md'}), encoding='utf-8')
    frozen = options(tmp_path)
    frozen.pop('epub_output_format')
    with store.worker_lock():
        store.update_item(item['id'], status='failed', error='Interrupted delivery',
                          receipt_path=str(receipt_path), options=frozen)
    source.unlink()
    state = QueueRunner(store, tmp_path / 'cache', options(tmp_path, 'txt')).run(
        store.active_id, retry_failed=True)
    assert state['done'] == 1, state['items'][0]['error']
    primary = Path(state['items'][0]['output_path'])
    assert primary.suffix == '.md' and primary.read_bytes() == private.read_bytes()


def test_cancelled_epub_route_does_not_save_an_empty_export(book_path, tmp_path):
    result = converters.route(str(book_path), tmp_path / 'output',
                              epub_output_format='txt', should_cancel=lambda: True)
    assert not result.success and not result.output_path
    assert not list(tmp_path.joinpath('output').rglob('*.txt'))
    assert not list(tmp_path.joinpath('output').rglob('*.md'))


def test_cancellation_after_queue_start_keeps_epub_waiting(book_path, tmp_path):
    store = make_queue(tmp_path, [book_path])
    stopped = threading.Event()
    state = QueueRunner(store, tmp_path / 'cache', options(tmp_path, 'txt'),
                        should_cancel=stopped.is_set,
                        on_progress=lambda *args: stopped.set()).run(store.active_id)
    item = state['items'][0]
    assert item['status'] == 'waiting' and not item['error']
    assert not item['output_path']
    assert not list(tmp_path.joinpath('output').rglob('*.txt'))


def test_bad_and_encrypted_epubs_do_not_block_the_next_good_book(book_path, tmp_path):
    broken = tmp_path / 'broken.epub'
    broken.write_bytes(b'This is not a ZIP archive.')
    encrypted = make_epub(tmp_path / 'encrypted.epub', encrypted=True)
    store = make_queue(tmp_path, [broken, encrypted, book_path])
    state = QueueRunner(store, tmp_path / 'cache', options(tmp_path)).run(store.active_id)
    assert [item['status'] for item in state['items']] == ['failed', 'failed', 'done']
    assert any(word in state['items'][1]['error'].lower() for word in ('encrypt', 'drm'))
    assert SECOND in Path(state['items'][2]['output_path']).read_text(encoding='utf-8')


def test_txt_named_copy_is_exact_bytes_and_preserves_colliding_user_file(tmp_path):
    base = tmp_path / 'output'
    source = base / 'epub' / 'Ősz.txt'
    source.parent.mkdir(parents=True)
    source.write_bytes('Ősz és öröm.\r\nTűrő képesség.\n'.encode('utf-8'))
    copies = base / 'Másolatok'
    collision = copies / 'epub' / source.name
    collision.parent.mkdir(parents=True)
    collision.write_bytes(b'User-owned existing text.')
    manifest = {}
    deliver_output_copies([source], base_dir=base, copy_dir=copies,
                          manifest=manifest, persist=lambda: None)
    target = Path(manifest['copy_exports'][str(source)]['path'])
    assert target.suffix == '.txt' and target != collision
    assert target.read_bytes() == source.read_bytes()
    assert collision.read_bytes() == b'User-owned existing text.'


def test_txt_copy_manifest_cannot_change_extension(tmp_path):
    base = tmp_path / 'output'
    source = base / 'epub' / 'book.txt'
    copies = base / 'Copies'
    manifest = {'copy_exports': {str(source): {
        'path': str(copies / 'epub' / 'book.txt'), 'sha256': None, 'pending_sha256': None,
    }}}
    validate_copy_manifest(base_dir=base, copy_dir=copies, manifest=manifest)
    manifest['copy_exports'][str(source)]['path'] = str(copies / 'epub' / 'book.md')
    with pytest.raises(ValueError):
        validate_copy_manifest(base_dir=base, copy_dir=copies, manifest=manifest)
    assert not copies.exists()


@pytest.mark.parametrize('suffix', ['.epub', '.json', '.html', '.pdf'])
def test_named_copy_still_rejects_non_output_files_before_writing(tmp_path, suffix):
    base = tmp_path / 'output'
    source = base / 'epub' / f'book{suffix}'
    source.parent.mkdir(parents=True)
    source.write_bytes(b'Not a text output.')
    copies = base / 'Copies'
    with pytest.raises(ValueError):
        deliver_output_copies([source], base_dir=base, copy_dir=copies,
                              manifest={}, persist=lambda: None)
    assert not copies.exists()
