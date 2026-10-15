"""Bounded, local EPUB text extraction behind a small immutable book interface.

No archive member is extracted and no book resource is fetched. Control XML is
parsed without DTDs; selected HTML is cleaned before the existing Markdown
renderer sees it. Limits apply to actual decompressed document reads as well as
ZIP size metadata. Image-only books need OCR, which this reader does not perform.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import posixpath
import re
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile
import zlib

from bs4 import BeautifulSoup, Comment, NavigableString, Tag, UnicodeDammit
from markdownify import markdownify


MAX_ARCHIVE_ENTRIES = 10_000
MAX_CONTROL_XML_BYTES = 1024 * 1024
MAX_CHAPTER_BYTES = 8 * 1024 * 1024
MAX_TOTAL_DOCUMENT_BYTES = 64 * 1024 * 1024
_READ_CHUNK_BYTES = 64 * 1024
_TEXT_MEDIA_TYPES = frozenset({'application/xhtml+xml', 'text/html'})
CancelCheck = Callable[[], bool] | None


class EpubError(ValueError):
    """The book cannot be converted safely or has no extractable body text."""


class EpubCancelled(Exception):
    """Cooperative cancellation requested by the caller."""


@dataclass(frozen=True)
class EpubBook:
    """Book metadata and cleaned chapter-body HTML in declared reading order."""

    title: str
    authors: tuple[str, ...]
    chapters: tuple[str, ...]


def _check_cancel(should_cancel: CancelCheck) -> None:
    if should_cancel is not None and should_cancel():
        raise EpubCancelled('EPUB conversion cancelled')


def _local_name(name: str) -> str:
    return name.rsplit('}', 1)[-1].rsplit(':', 1)[-1]


def _validate_path_text(path: str) -> None:
    if not path or '\\' in path or any(ord(char) < 32 for char in path):
        raise EpubError('Unsafe EPUB resource path')
    if path.startswith('/') or re.match(r'^[A-Za-z]:', path):
        raise EpubError('Unsafe absolute EPUB resource path')


def _archive_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    entries = archive.infolist()
    if len(entries) > MAX_ARCHIVE_ENTRIES:
        raise EpubError(f'EPUB archive has too many entries (limit: {MAX_ARCHIVE_ENTRIES})')
    members = {}
    for info in entries:
        name = info.filename
        _validate_path_text(name)
        if info.orig_filename != name:
            raise EpubError('Unsafe EPUB archive member path')
        # Even unused members must not disguise traversal in their ZIP name.
        decoded = unquote(name, encoding='utf-8', errors='strict')
        _validate_path_text(decoded)
        if any(part in {'.', '..'} for part in decoded.rstrip('/').split('/')):
            raise EpubError('Unsafe EPUB archive member path')
        if name in members:
            raise EpubError(f'Duplicate EPUB archive member: {name}')
        members[name] = info
    return members


def _resource_path(base: str, reference: str) -> str:
    """Resolve one local URI against an archive directory, rejecting root escapes."""
    try:
        parsed = urlsplit(reference)
        if parsed.scheme or parsed.netloc:
            raise EpubError('Remote or unsupported EPUB reading-order resource')
        decoded = unquote(parsed.path, encoding='utf-8', errors='strict')
    except (UnicodeError, ValueError) as exc:
        if isinstance(exc, EpubError):
            raise
        raise EpubError('Invalid EPUB resource path') from exc
    _validate_path_text(decoded)
    # A URI path can use ../ to reach an adjacent directory, never outside ZIP root.
    resolved = posixpath.normpath(posixpath.join(base, decoded))
    if resolved == '..' or resolved.startswith('../'):
        raise EpubError('Unsafe EPUB resource path traversal')
    _validate_path_text(resolved)
    return resolved


class _NoDtdBuilder(ET.TreeBuilder):
    def doctype(self, name, pubid, system):
        raise EpubError('DTD declarations are not supported in EPUB control XML')


class _BookArchive:
    def __init__(self, archive: zipfile.ZipFile, should_cancel: CancelCheck):
        self.archive = archive
        self.members = _archive_members(archive)
        self.should_cancel = should_cancel
        self.total_read = 0

    def read(self, name: str, limit: int) -> bytes:
        _check_cancel(self.should_cancel)
        info = self.members.get(name)
        if info is None or info.is_dir():
            raise EpubError(f'Missing EPUB document: {name}')
        if info.flag_bits & 1:
            raise EpubError(f'Encrypted EPUB document is unsupported: {name}')
        if info.file_size > limit:
            raise EpubError(f'EPUB document exceeds size limit: {name}')
        if self.total_read + info.file_size > MAX_TOTAL_DOCUMENT_BYTES:
            raise EpubError('EPUB cumulative document size limit exceeded')
        chunks = []
        document_read = 0
        with self.archive.open(info) as stream:
            while True:
                _check_cancel(self.should_cancel)
                chunk = stream.read(min(_READ_CHUNK_BYTES, limit - document_read + 1))
                if not chunk:
                    break
                document_read += len(chunk)
                self.total_read += len(chunk)
                if document_read > limit:
                    raise EpubError(f'EPUB document exceeds size limit: {name}')
                if self.total_read > MAX_TOTAL_DOCUMENT_BYTES:
                    raise EpubError('EPUB cumulative document size limit exceeded')
                chunks.append(chunk)
        _check_cancel(self.should_cancel)
        return b''.join(chunks)

    def xml(self, name: str, root_name: str) -> ET.Element:
        data = self.read(name, MAX_CONTROL_XML_BYTES)
        try:
            root = ET.fromstring(data, parser=ET.XMLParser(target=_NoDtdBuilder()))
        except (ET.ParseError, LookupError, ValueError) as exc:
            if isinstance(exc, EpubError):
                raise
            raise EpubError(f'Invalid EPUB control XML: {name}') from exc
        if _local_name(root.tag) != root_name:
            raise EpubError(f'Invalid EPUB {root_name} document: {name}')
        return root


def _child(element: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in element if _local_name(child.tag) == name), None)


def _element_text(element: ET.Element) -> str:
    return ' '.join(''.join(element.itertext()).split())


def _selected_chapters(package: ET.Element, package_path: str) -> tuple[str, ...]:
    manifest = _child(package, 'manifest')
    spine = _child(package, 'spine')
    if manifest is None or spine is None:
        raise EpubError('EPUB package has no manifest or reading-order spine')
    resources = {}
    for item in manifest:
        if _local_name(item.tag) != 'item':
            continue
        item_id = item.get('id', '').strip()
        if not item_id or item_id in resources:
            raise EpubError('EPUB manifest has missing or duplicate resource IDs')
        resources[item_id] = item
    chapters = []
    for itemref in spine:
        if _local_name(itemref.tag) != 'itemref':
            continue
        resource_id = itemref.get('idref', '').strip()
        seen = set()
        while True:
            if not resource_id or resource_id not in resources:
                raise EpubError('EPUB reading-order spine references a missing resource')
            if resource_id in seen:
                raise EpubError('EPUB reading-order resource fallback cycle')
            seen.add(resource_id)
            item = resources[resource_id]
            if item.get('media-type', '').strip().lower() in _TEXT_MEDIA_TYPES:
                chapters.append(_resource_path(posixpath.dirname(package_path), item.get('href', '')))
                break
            resource_id = item.get('fallback', '').strip()
            if not resource_id:
                raise EpubError('Unsupported EPUB reading-order document; XHTML or HTML is required')
    if not chapters:
        raise EpubError('EPUB has no reading-order spine documents')
    return tuple(chapters)


def _encrypted_resources(book: _BookArchive) -> set[str]:
    if 'META-INF/encryption.xml' not in book.members:
        return set()
    root = book.xml('META-INF/encryption.xml', 'encryption')
    encrypted = set()
    for reference in root.iter():
        if _local_name(reference.tag) == 'CipherReference':
            uri = reference.get('URI')
            if uri is None:
                raise EpubError('Invalid EPUB encryption resource reference')
            encrypted.add(_resource_path('', uri))
    return encrypted


def _clean_body(data: bytes) -> str:
    decoded = UnicodeDammit(data, is_html=True).unicode_markup
    if decoded is None:
        raise EpubError('EPUB chapter text encoding is unsupported')
    # Avoid parsing an XML declaration as HTML while retaining its detected encoding.
    decoded = re.sub(r'^\s*<\?xml\b[^?]*\?>', '', decoded, count=1, flags=re.I)
    soup = BeautifulSoup(decoded, 'html.parser')
    for tag in soup.find_all(True):
        tag.name = _local_name(tag.name).lower()
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    for tag in list(soup.find_all(True)):
        if tag.parent is None:
            continue
        epub_types = str(tag.get('epub:type', '')).split()
        roles = tag.get('role', [])
        roles = roles.split() if isinstance(roles, str) else roles
        if (tag.name in {'head', 'title', 'meta', 'link', 'nav', 'script', 'style', 'template', 'img',
                         'svg', 'embed', 'iframe', 'audio', 'video', 'source', 'noscript'}
                or set(epub_types) & {'toc', 'landmarks', 'page-list'}
                or set(roles) & {'navigation', 'doc-toc', 'doc-pagelist', 'doc-landmarks'}):
            tag.decompose()
            continue
        if tag.name in {'object', 'canvas'}:
            # Export readable fallback descendants without retaining active media.
            # Descendants remain in this pass and receive the same sanitization.
            tag.unwrap()
            continue
        if tag.name == 'a':
            href = tag.get('href', '')
            try:
                external = urlsplit(href).scheme.lower() in {'http', 'https'} and bool(urlsplit(href).netloc)
            except ValueError:
                external = False
            if not external:
                tag.unwrap()
                continue
            tag.attrs = {'href': href}
        else:
            # Retain note text even if a reading system hides it for popovers.
            # Keep only structural list hints; output never needs active attributes.
            tag.attrs = {key: value for key, value in tag.attrs.items()
                         if tag.name == 'ol' and key == 'start'}
    body = soup.body or soup
    return body.decode_contents().strip()


def read_epub(path: str | Path, *, should_cancel: CancelCheck = None) -> EpubBook:
    """Read selected chapter bodies in spine order, or raise ``EpubError``.

    Limits: 10,000 ZIP entries, 1 MiB per control XML, 8 MiB per chapter and
    64 MiB of cumulative decompressed documents. Cancellation raises
    ``EpubCancelled`` and is checked before opening and during streamed reads.
    """
    _check_cancel(should_cancel)
    try:
        with zipfile.ZipFile(path) as archive:
            book = _BookArchive(archive, should_cancel)
            container = book.xml('META-INF/container.xml', 'container')
            rootfiles = _child(container, 'rootfiles')
            rootfile = next((element for element in rootfiles if _local_name(element.tag) == 'rootfile'), None) if rootfiles is not None else None
            if rootfile is None:
                raise EpubError('EPUB container has no package rootfile')
            package_path = _resource_path('', rootfile.get('full-path', ''))
            package = book.xml(package_path, 'package')
            selected = _selected_chapters(package, package_path)
            encrypted = _encrypted_resources(book)
            chapters = []
            for chapter_path in selected:
                _check_cancel(should_cancel)
                if chapter_path in encrypted:
                    raise EpubError(f'Encrypted EPUB chapter is unsupported: {chapter_path}')
                chapters.append(_clean_body(book.read(chapter_path, MAX_CHAPTER_BYTES)))
            metadata = _child(package, 'metadata')
            title = ''
            authors = []
            if metadata is not None:
                for element in metadata:
                    name = _local_name(element.tag)
                    if name == 'title' and not title:
                        title = _element_text(element)
                    elif name == 'creator':
                        author = _element_text(element)
                        if author:
                            authors.append(author)
            result = EpubBook(title or Path(path).stem, tuple(authors), tuple(chapters))
            if not any(BeautifulSoup(chapter, 'html.parser').get_text().strip()
                       for chapter in result.chapters):
                raise EpubError('EPUB has no extractable body text; image-only books require OCR')
            _check_cancel(should_cancel)
            return result
    except (zipfile.BadZipFile, zipfile.LargeZipFile, zlib.error, OSError, RuntimeError, UnicodeError, NotImplementedError) as exc:
        raise EpubError(f'Cannot read EPUB archive: {exc}') from exc


def render_markdown(book: EpubBook, *, should_cancel: CancelCheck = None) -> str:
    """Render chapter bodies only; callers own book title/author presentation."""
    _check_cancel(should_cancel)
    chapters = []
    for chapter in book.chapters:
        _check_cancel(should_cancel)
        rendered = markdownify(chapter, heading_style='ATX', bullets='-').strip()
        if rendered:
            chapters.append(rendered)
    _check_cancel(should_cancel)
    return '\n\n'.join(chapters).strip() + ('\n' if chapters else '')


_BLOCK_TAGS = frozenset({'address', 'article', 'aside', 'blockquote', 'div', 'dl', 'dt', 'dd', 'footer', 'form',
                         'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header', 'main', 'p', 'pre', 'section'})


def _node_text(node) -> str:
    if isinstance(node, NavigableString):
        return re.sub(r'\s+', ' ', str(node))
    if not isinstance(node, Tag):
        return ''
    if node.name == 'br':
        return '\n'
    if node.name == 'hr':
        return '\n\n'
    if node.name in {'ul', 'ol'}:
        try:
            start = int(node.get('start', '1'))
        except (TypeError, ValueError):
            start = 1
        rows = []
        for index, item in enumerate(node.find_all('li', recursive=False)):
            prefix = f'{start + index}. ' if node.name == 'ol' else '• '
            rows.append(prefix + ''.join(_node_text(child) for child in item.children).strip())
        return '\n\n' + '\n'.join(rows) + '\n\n'
    if node.name == 'table':
        rows = []
        for row in node.find_all('tr'):
            cells = [''.join(_node_text(child) for child in cell.children).strip()
                     for cell in row.find_all(['th', 'td'], recursive=False)]
            if cells:
                rows.append('\t'.join(cells))
        return '\n\n' + '\n'.join(rows) + '\n\n'
    text = ''.join(_node_text(child) for child in node.children)
    return '\n\n' + text.strip() + '\n\n' if node.name in _BLOCK_TAGS else text


def _plain_chapter(chapter: str) -> str:
    soup = BeautifulSoup(chapter, 'html.parser')
    text = ''.join(_node_text(child) for child in soup.children)
    lines = [re.sub(r'[^\S\n\t]+', ' ', line).strip(' ') for line in text.splitlines()]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()


def render_text(book: EpubBook, *, should_cancel: CancelCheck = None) -> str:
    """Render readable plain chapter text without Markdown metadata or markers."""
    _check_cancel(should_cancel)
    chapters = []
    for chapter in book.chapters:
        _check_cancel(should_cancel)
        text = _plain_chapter(chapter)
        if text:
            chapters.append(text)
    _check_cancel(should_cancel)
    return '\n\n'.join(chapters).strip() + ('\n' if chapters else '')
