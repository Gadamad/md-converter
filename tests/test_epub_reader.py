"""Small generated EPUBs exercise the public reader seam without personal books."""
import itertools
import sys
import warnings
import zipfile
from dataclasses import FrozenInstanceError
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import epub_reader
from epub_reader import EpubBook, EpubCancelled, EpubError, read_epub, render_markdown, render_text


CONTAINER = '''<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
<rootfiles><rootfile full-path="OPS/book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'''


def chapter(body, *, encoding="utf-8"):
    return (f'<?xml version="1.0" encoding="{encoding}"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
            '<head><title>Document metadata must not become body</title></head>'
            f'<body>{body}</body></html>').encode(encoding)


def package(items=None, spine=None, *, version="3.0", metadata=None):
    items = items if items is not None else [('one', 'one.xhtml', 'application/xhtml+xml', '')]
    spine = spine if spine is not None else [('one', '')]
    manifest = ''.join(f'<item id="{item_id}" href="{escape(href)}" media-type="{media}" {attrs}/>'
                       for item_id, href, media, attrs in items)
    refs = ''.join(f'<itemref idref="{item_id}" {attrs}/>' for item_id, attrs in spine)
    metadata = metadata if metadata is not None else '<dc:title>Árvíztűrő tükörfúrógép</dc:title><dc:creator>Őri Éva</dc:creator><dc:creator>Ács Pál</dc:creator>'
    return (f'<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/" version="{version}">'
            f'<metadata>{metadata}</metadata><manifest>{manifest}</manifest><spine>{refs}</spine></package>')


def make_epub(tmp_path, *, opf=None, documents=None, extra=None, container=CONTAINER, name="book.epub"):
    members = [('mimetype', b'application/epub+zip'), ('META-INF/container.xml', container),
               ('OPS/book.opf', opf if opf is not None else package())]
    members += list((documents if documents is not None else {'OPS/one.xhtml': chapter('<h1>Első fejezet</h1><p>Olvasható könyv.</p>')}).items())
    members += list((extra or {}).items())
    path = tmp_path / name
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for member, contents in members:
            archive.writestr(member, contents)
    return path


def test_reads_metadata_and_frozen_chapter_body_without_prefixing_rendered_metadata(tmp_path):
    book = read_epub(make_epub(tmp_path))
    assert book.title == 'Árvíztűrő tükörfúrógép'
    assert book.authors == ('Őri Éva', 'Ács Pál')
    assert isinstance(book.chapters, tuple)
    with pytest.raises(FrozenInstanceError):
        book.title = 'Changed'
    assert render_markdown(book).startswith('# Első fejezet')
    assert 'Árvíztűrő' not in render_markdown(book)
    assert 'Őri Éva' not in render_text(book)
    assert 'Document metadata' not in render_text(book)


@pytest.mark.parametrize('version', ['2.0', '3.0'])
def test_spine_order_is_invariant_under_all_manifest_and_zip_permutations(tmp_path, version):
    items = [('a', 'a.xhtml', 'application/xhtml+xml', ''), ('b', 'b.xhtml', 'application/xhtml+xml', ''),
             ('c', 'c.xhtml', 'application/xhtml+xml', '')]
    docs = [('OPS/a.xhtml', chapter('<p>Alpha first.</p>')), ('OPS/b.xhtml', chapter('<p>Beta second.</p>')),
            ('OPS/c.xhtml', chapter('<p>Gamma third.</p>'))]
    for manifest_order in itertools.permutations(items):
        for zip_order in itertools.permutations(docs):
            path = make_epub(tmp_path, opf=package(manifest_order, [('c', ''), ('a', 'linear="no"'), ('b', '')], version=version), documents=dict(zip_order))
            assert render_text(read_epub(path)).splitlines()[::2] == ['Gamma third.', 'Alpha first.', 'Beta second.']


@pytest.mark.parametrize('text', ['Árvíztűrő tükörfúrógép', 'őŐűŰéÉóÓ', 'Zażółć gęślą jaźń', '中文 日本語', 'e\u0301 ő\u030b', '«A & B» < C'])
@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16'])
def test_unicode_text_is_preserved_across_xml_encodings(tmp_path, text, encoding):
    book = read_epub(make_epub(tmp_path, documents={'OPS/one.xhtml': chapter('<p>' + escape(text) + '</p>', encoding=encoding)}))
    assert render_text(book).strip() == text
    assert text.replace('<', r'\<') in render_markdown(book) or text in render_markdown(book)


def test_preserves_inline_spacing_paragraphs_lists_tables_headers_and_footers(tmp_path):
    body = '''<header><p>Book header</p></header><h2>Cím</h2>
    <p>First <em>emphasized</em> words and co<strong>operate</strong>.</p><p>Second paragraph.</p>
    <ul><li>Apple</li><li>Pear</li></ul><ol start="3"><li>Third</li><li>Fourth</li></ol>
    <table><tr><th>Termék</th><th>Ár</th></tr><tr><td>Könyv</td><td>10</td></tr></table>
    <footer><p>Book footer</p></footer>'''
    book = read_epub(make_epub(tmp_path, documents={'OPS/one.xhtml': chapter(body)}))
    markdown = render_markdown(book)
    text = render_text(book)
    assert 'First *emphasized* words and co**operate**.' in markdown
    assert 'First emphasized words and cooperate.\n\nSecond paragraph.' in text
    assert '- Apple' in markdown and '- Pear' in markdown
    assert 'Apple' in text and 'Pear' in text and 'Third' in text and 'Fourth' in text
    assert '| Termék | Ár |' in markdown and '| Könyv | 10 |' in markdown
    assert 'Termék\tÁr' in text and 'Könyv\t10' in text
    for output in (markdown, text):
        assert 'Book header' in output and 'Book footer' in output
    assert '**' not in text and '##' not in text


def test_removes_navigation_active_content_and_image_alt_but_keeps_http_links(tmp_path):
    body = '''<nav><a href="one.xhtml">Navigation title</a></nav>
    <section epub:type="toc"><p>EPUB table of contents</p></section>
    <div role="navigation">ARIA navigation</div><script>Dangerous script</script><style>Body style</style>
    <template>Hidden template</template><img src="cover.png" alt="Image alt is not book text"/>
    <p>Read <a href="https://example.com/reference">external reference</a> and <a href="two.xhtml#note">internal note</a>.</p>'''
    book = read_epub(make_epub(tmp_path, documents={'OPS/one.xhtml': chapter(body)}))
    markdown = render_markdown(book)
    assert '[external reference](https://example.com/reference)' in markdown
    assert 'internal note' in markdown and 'two.xhtml' not in markdown
    for absent in ['Navigation title', 'EPUB table of contents', 'ARIA navigation', 'Dangerous script', 'Body style', 'Hidden template', 'Image alt']:
        assert absent not in markdown
        assert absent not in render_text(book)


def test_decodes_nested_percent_encoded_package_and_chapter_paths(tmp_path):
    container = CONTAINER.replace('OPS/book.opf', 'OPS/K%C3%B6nyv/book.opf')
    path = make_epub(tmp_path, container=container, documents={}, extra={
        'OPS/Könyv/book.opf': package([('one', '../Sz%C3%B6veg/els%C5%91%20r%C3%A9sz.xhtml#start', 'application/xhtml+xml', '')]),
        'OPS/Szöveg/első rész.xhtml': chapter('<p>Első rész tartalma.</p>')})
    assert render_text(read_epub(path)).strip() == 'Első rész tartalma.'


def test_uses_first_package_rootfile_instead_of_guessing_another(tmp_path):
    container = CONTAINER.replace('</rootfiles>', '<rootfile full-path="other.opf" media-type="application/oebps-package+xml"/></rootfiles>')
    assert 'Első fejezet' in render_text(read_epub(make_epub(tmp_path, container=container, extra={'other.opf': b'broken'})))


def test_supports_html_and_foreign_manifest_fallback_to_xhtml(tmp_path):
    opf = package([('foreign', 'unknown.bin', 'application/x-unknown', 'fallback="html"'), ('html', 'one.html', 'text/html', '')], [('foreign', '')])
    book = read_epub(make_epub(tmp_path, opf=opf, documents={'OPS/one.html': '<html><body><p>HTML &eacute; text</p></body></html>'}))
    assert render_text(book).strip() == 'HTML é text'


@pytest.mark.parametrize('body', ['<img src="page.jpg" alt="A scanned page"/>', '<nav><p>Contents</p></nav>', '<svg><title>Cover title</title><image href="cover.jpg"/></svg>', '<script>Text</script>'])
def test_rejects_books_without_extractable_body_text(tmp_path, body):
    with pytest.raises(EpubError, match='(?i)(no .*text|text .*unavailable|extractable)'):
        read_epub(make_epub(tmp_path, documents={'OPS/one.xhtml': chapter(body)}))


def encryption_xml(uri):
    return f'''<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" xmlns:enc="http://www.w3.org/2001/04/xmlenc#"><enc:EncryptedData><enc:EncryptionMethod Algorithm="http://www.idpf.org/2008/embedding"/><enc:CipherData><enc:CipherReference URI="{uri}"/></enc:CipherData></enc:EncryptedData></encryption>'''


def test_rejects_encrypted_selected_chapter_but_allows_obfuscated_fonts(tmp_path):
    readable = make_epub(tmp_path, extra={'META-INF/encryption.xml': encryption_xml('OPS/font.otf'), 'OPS/font.otf': b'obfuscated'})
    assert 'Olvasható' in render_text(read_epub(readable))
    encrypted = make_epub(tmp_path, extra={'META-INF/encryption.xml': encryption_xml('OPS/one.xhtml')})
    with pytest.raises(EpubError, match='(?i)encrypt'):
        read_epub(encrypted)


@pytest.mark.parametrize('container', ['', '<container>', CONTAINER.replace('OPS/book.opf', 'missing.opf'), '<container><rootfiles/></container>'])
def test_rejects_missing_or_malformed_container_and_package(tmp_path, container):
    with pytest.raises(EpubError):
        read_epub(make_epub(tmp_path, container=container))


@pytest.mark.parametrize('opf', ['<package>', package(spine=[]), package(spine=[('missing', '')]),
    package([('one', 'one.xhtml', 'image/png', '')]),
    package([('one', 'one.xhtml', 'application/x-other', 'fallback="one"')]),
    package([('one', 'one.xhtml', 'application/xhtml+xml', ''), ('one', 'other.xhtml', 'application/xhtml+xml', '')])])
def test_rejects_invalid_or_unsupported_spine_without_guessing(tmp_path, opf):
    with pytest.raises(EpubError):
        read_epub(make_epub(tmp_path, opf=opf))


def test_rejects_missing_selected_chapter(tmp_path):
    with pytest.raises(EpubError, match='(?i)(missing|not found)'):
        read_epub(make_epub(tmp_path, documents={}))


@pytest.mark.parametrize('control_name', ['META-INF/container.xml', 'OPS/book.opf', 'META-INF/encryption.xml'])
@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16'])
def test_rejects_dtds_in_control_xml_even_when_utf16(tmp_path, control_name, encoding):
    originals = {'META-INF/container.xml': CONTAINER, 'OPS/book.opf': package(), 'META-INF/encryption.xml': encryption_xml('OPS/font.otf')}
    xml = originals[control_name]
    if xml.startswith('<?xml'):
        xml = xml.split('?>', 1)[1]
    payload = ('<?xml version="1.0" encoding="' + encoding + '"?><!DOCTYPE anything [<!ENTITY x "expanded">]>' + xml).encode(encoding)
    kwargs = {'container': payload} if control_name == 'META-INF/container.xml' else {'opf': payload} if control_name == 'OPS/book.opf' else {'extra': {control_name: payload}}
    with pytest.raises(EpubError, match='(?i)(DTD|doctype)'):
        read_epub(make_epub(tmp_path, **kwargs))


@pytest.mark.parametrize('member', ['../outside', '/absolute', 'OPS/../../outside', 'OPS\\chapter.xhtml', 'OPS/%2e%2e/hidden', 'C:/drive'])
def test_rejects_unsafe_archive_members_without_extracting(tmp_path, member):
    with pytest.raises(EpubError, match='(?i)(path|unsafe)'):
        read_epub(make_epub(tmp_path, extra={member: 'never extract'}))
    assert not (tmp_path / 'outside').exists()


@pytest.mark.parametrize('href', ['../../outside.xhtml', '%2e%2e/%2e%2e/outside.xhtml', '/outside.xhtml', 'https://example.com/chapter.xhtml', 'C:/drive.xhtml'])
def test_rejects_unsafe_or_remote_selected_resource_paths(tmp_path, href):
    with pytest.raises(EpubError):
        read_epub(make_epub(tmp_path, opf=package([('one', href, 'application/xhtml+xml', '')])))


def test_rejects_duplicate_zip_members(tmp_path):
    path = make_epub(tmp_path)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        with zipfile.ZipFile(path, 'a') as archive:
            archive.writestr('OPS/one.xhtml', chapter('<p>Ambiguous replacement</p>'))
    with pytest.raises(EpubError, match='(?i)(duplicate|ambiguous)'):
        read_epub(path)


def test_reports_invalid_zip_as_reader_error(tmp_path):
    path = tmp_path / 'bad.epub'
    path.write_bytes(b'not a zip archive')
    with pytest.raises(EpubError):
        read_epub(path)


@pytest.mark.parametrize('limit_name,value,match', [('MAX_ARCHIVE_ENTRIES', 3, 'entries'), ('MAX_CONTROL_XML_BYTES', 30, 'limit'), ('MAX_CHAPTER_BYTES', 30, 'limit'), ('MAX_TOTAL_DOCUMENT_BYTES', 800, 'limit')])
def test_bounds_archive_and_uncompressed_documents(tmp_path, monkeypatch, limit_name, value, match):
    path = make_epub(tmp_path, documents={'OPS/one.xhtml': chapter('<p>' + 'Large text. ' * 200 + '</p>')})
    monkeypatch.setattr(epub_reader, limit_name, value)
    with pytest.raises(EpubError, match='(?i)' + match):
        read_epub(path)


def test_checks_actual_stream_bytes_instead_of_trusting_member_size(tmp_path, monkeypatch):
    path = make_epub(tmp_path, documents={'OPS/one.xhtml': chapter('<p>' + 'Large text. ' * 200 + '</p>')})
    original_open = zipfile.ZipFile.open
    def dishonest_open(archive, member, *args, **kwargs):
        stream = original_open(archive, member, *args, **kwargs)
        if getattr(member, 'filename', member) == 'OPS/one.xhtml':
            stream._orig_file_size = stream._left = 100000
        return stream
    # A smaller limit is enforced while the real ZIP stream is read; header sizes are
    # deliberately understated only after opening so the reader must count bytes.
    original_infolist = zipfile.ZipFile.infolist
    def understated(archive):
        items = original_infolist(archive)
        for item in items:
            if item.filename == 'OPS/one.xhtml':
                item.file_size = 1
        return items
    monkeypatch.setattr(epub_reader, 'MAX_CHAPTER_BYTES', 400)
    monkeypatch.setattr(zipfile.ZipFile, 'infolist', understated)
    monkeypatch.setattr(zipfile.ZipFile, 'open', dishonest_open)
    with pytest.raises(EpubError, match='(?i)limit'):
        read_epub(path)


def test_cancels_before_open_and_while_reading_chunks(tmp_path, monkeypatch):
    with pytest.raises(EpubCancelled):
        read_epub(tmp_path / 'not-present.epub', should_cancel=lambda: True)
    path = make_epub(tmp_path, documents={'OPS/one.xhtml': chapter('<p>' + 'Text ' * 20000 + '</p>')})
    reads = 0
    original_read = zipfile.ZipExtFile.read
    def counted_read(stream, *args, **kwargs):
        nonlocal reads
        data = original_read(stream, *args, **kwargs)
        reads += 1
        return data
    monkeypatch.setattr(zipfile.ZipExtFile, 'read', counted_read)
    with pytest.raises(EpubCancelled):
        read_epub(path, should_cancel=lambda: reads >= 3)


@pytest.mark.parametrize('renderer', [render_markdown, render_text])
def test_rendering_checks_cancellation_between_chapters(renderer):
    book = EpubBook('Metadata', (), ('<p>First</p>', '<p>Second</p>'))
    calls = 0
    def should_cancel():
        nonlocal calls
        calls += 1
        return calls > 2
    with pytest.raises(EpubCancelled):
        renderer(book, should_cancel=should_cancel)


@pytest.mark.parametrize('body', ['<ul><li></li></ul>', '<ol><li><img src="page.png" alt="Scanned words"/></li></ol>', '<table><tr><td></td></tr></table>'])
def test_generated_list_or_table_formatting_does_not_count_as_extractable_book_text(tmp_path, body):
    with pytest.raises(EpubError, match='(?i)extractable'):
        read_epub(make_epub(tmp_path, documents={'OPS/one.xhtml': chapter(body)}))


@pytest.mark.parametrize('metadata', ['', '<dc:title> \n </dc:title>'])
def test_uses_unicode_source_filename_when_title_metadata_is_missing(tmp_path, metadata):
    path = make_epub(tmp_path, opf=package(metadata=metadata), name='Őszi könyv.epub')
    assert read_epub(path).title == 'Őszi könyv'


def test_preserves_hidden_note_text_while_removing_navigation(tmp_path):
    body = '<p>A passage<sup><a href="#note">1</a></sup>.</p><aside epub:type="footnote" hidden="hidden" aria-hidden="true" id="note"><p>Source note retained for export.</p></aside>'
    book = read_epub(make_epub(tmp_path, documents={'OPS/one.xhtml': chapter(body)}))
    assert 'Source note retained for export.' in render_text(book)
    assert 'Source note retained for export.' in render_markdown(book)


def test_reports_corrupt_deflate_chapter_as_reader_error(tmp_path):
    import struct

    path = make_epub(tmp_path)
    with zipfile.ZipFile(path) as archive:
        chapter_info = archive.getinfo('OPS/one.xhtml')
    data = bytearray(path.read_bytes())
    filename_length, extra_length = struct.unpack_from('<HH', data, chapter_info.header_offset + 26)
    payload_offset = chapter_info.header_offset + 30 + filename_length + extra_length
    data[payload_offset:payload_offset + 3] = b'\xff\xff\xff'
    path.write_bytes(data)

    with pytest.raises(EpubError, match='(?i)(archive|corrupt|read)'):
        read_epub(path)


def test_keeps_readable_object_and_canvas_fallback_text_without_active_content(tmp_path):
    body = ('<p>Main paragraph.</p>'
            '<object data="https://example.com/widget.bin" type="application/x-widget">'
            '<p>Readable object fallback paragraph.</p></object>'
            '<canvas onclick="active()"><p>Readable canvas fallback paragraph.</p>'
            '<script>not exported</script></canvas>')
    book = read_epub(make_epub(tmp_path, documents={'OPS/one.xhtml': chapter(body)}))
    for output in (render_markdown(book), render_text(book)):
        assert 'Main paragraph.' in output
        assert 'Readable object fallback paragraph.' in output
        assert 'Readable canvas fallback paragraph.' in output
        assert 'not exported' not in output
        assert 'widget.bin' not in output
        assert 'active()' not in output
    assert '<object' not in book.chapters[0] and '<canvas' not in book.chapters[0]
    assert '<script' not in book.chapters[0] and 'onclick' not in book.chapters[0]


@pytest.mark.parametrize('tag', ['object', 'canvas'])
def test_fallback_text_alone_counts_as_extractable_body_text(tmp_path, tag):
    book = read_epub(make_epub(tmp_path, documents={'OPS/one.xhtml': chapter(f'<{tag}><p>Fallback book text.</p></{tag}>')}))
    assert render_text(book).strip() == 'Fallback book text.'
