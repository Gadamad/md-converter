#!/usr/bin/env python3
"""
Universal Markdown Converters
Five format converters with shared utilities for consistent output.
"""

import hashlib
import math
import random
import re
import shutil
import time
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from collections.abc import Callable
from typing import NamedTuple
from urllib.parse import urlsplit

import os
import ssl

import certifi

# Fix SSL certificate discovery on macOS + Python 3.14 + OpenSSL 3.6:
# certifi's bundled CA file may be rejected by newer OpenSSL builds.
# Prefer the system/Homebrew CA file that OpenSSL ships with; fall back
# to certifi only when no system file is found.
def _find_ca_file() -> str:
    """Return the best available CA certificate bundle path."""
    # 1. Already set by user/environment
    env_ca = os.environ.get("SSL_CERT_FILE")
    if env_ca and os.path.isfile(env_ca):
        return env_ca
    # 2. System OpenSSL default (works with Homebrew OpenSSL 3.x)
    _paths = ssl.get_default_verify_paths()
    for candidate in (_paths.cafile, _paths.openssl_cafile):
        if candidate and os.path.isfile(candidate):
            return candidate
    # 3. Fallback to certifi
    return certifi.where()

_CA_FILE = _find_ca_file()
os.environ["SSL_CERT_FILE"] = _CA_FILE

import fitz  # PyMuPDF
import requests
from bs4 import BeautifulSoup
from docx import Document
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph
from docx.text.run import Run
from image_ocr import OcrCancelled, OcrSession, ocr_image, _run_backend
from file_utils import atomic_write_text, reserve_output_path
from markdownify import markdownify as html_to_md
from quote_markdown import render_quote_batch_markdown
from quote_parser import extract_quote_records
from quote_checkpoint import QuoteCheckpoint
from spreadsheet_converter import write_xlsx_sheets
from striprtf.striprtf import rtf_to_text


WEB_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

WEB_FETCH_MAX_ATTEMPTS = 3
WEB_FETCH_BASE_DELAY_SECONDS = 1.0
WEB_FETCH_MAX_DELAY_SECONDS = 8.0
WEB_FETCH_JITTER_SECONDS = 0.25
WEB_FETCH_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
WEB_FETCH_RETRYABLE_EXCEPTIONS = (requests.ConnectionError, requests.Timeout)


def _parse_retry_after(value: str | None) -> float | None:
    """Parse Retry-After seconds or HTTP date into a sleep delay."""
    if not value:
        return None

    value = value.strip()
    try:
        seconds = float(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()

    return max(seconds, 0.0) if math.isfinite(seconds) else None


def _retry_delay_seconds(attempt: int) -> float:
    """Calculate a short exponential backoff with a small amount of jitter."""
    base_delay = min(WEB_FETCH_BASE_DELAY_SECONDS * (2 ** (attempt - 1)), WEB_FETCH_MAX_DELAY_SECONDS)
    return base_delay + random.uniform(0.0, WEB_FETCH_JITTER_SECONDS)


def _fetch_url_html(url: str) -> str:
    """Fetch HTML with conservative retries for transient failures only."""
    for attempt in range(1, WEB_FETCH_MAX_ATTEMPTS + 1):
        try:
            resp = requests.get(url, timeout=30, headers=WEB_REQUEST_HEADERS, verify=_CA_FILE)
        except WEB_FETCH_RETRYABLE_EXCEPTIONS:
            if attempt == WEB_FETCH_MAX_ATTEMPTS:
                raise
            time.sleep(_retry_delay_seconds(attempt))
            continue

        if resp.status_code in WEB_FETCH_RETRYABLE_STATUSES and attempt < WEB_FETCH_MAX_ATTEMPTS:
            retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
            delay = retry_after if retry_after is not None else _retry_delay_seconds(attempt)
            time.sleep(min(delay, WEB_FETCH_MAX_DELAY_SECONDS))
            continue

        resp.raise_for_status()
        return resp.text

    raise RuntimeError("URL fetch retry loop exited unexpectedly")


# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------

class ConvertResult(NamedTuple):
    success: bool
    output_path: str
    word_count: int
    message: str


@dataclass(frozen=True)
class QuoteBatchHooks:
    on_image_processed: Callable[[int, int, str], None] | None = None
    should_cancel: Callable[[], bool] | None = None
    on_image_started: Callable[[int, int, str], None] | None = None
    on_status: Callable[[str], None] | None = None


# ---------------------------------------------------------------------------
# Shared utilities (extracted from pdf_to_md / docx_to_md)
# ---------------------------------------------------------------------------

def safe_filename(name: str) -> str:
    """Sanitize a document title into a lowercase-dash filename."""
    safe = re.sub(r'[^\w\s\-]', '', name).strip()
    return re.sub(r'\s+', '-', safe).lower()


def output_stem(title: str, source_file: str, source_type: str) -> str:
    """Build a stable output stem, avoiding collisions for URL-based pages."""
    stem = safe_filename(title) or "converted"

    if source_type != "html" or not source_file.startswith(("http://", "https://")):
        return stem

    parsed = urlsplit(source_file)
    tail = Path(parsed.path).name.replace(".", " ")
    tail_slug = safe_filename(tail)
    url_hash = hashlib.sha1(source_file.encode("utf-8")).hexdigest()[:8]
    suffix = f"{tail_slug}-{url_hash}" if tail_slug else url_hash
    return f"{stem}-{suffix}"


def quote_batch_stem(paths: list[str]) -> str:
    parent_paths = [str(Path(path).resolve().parent) for path in paths]
    if not parent_paths:
        slug = "quotes"
    else:
        common_parent = Path(os.path.commonpath(parent_paths))
        slug = safe_filename(common_parent.name) or "quotes"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{slug}_quotes_{len(paths)}-images_{timestamp}"


def unique_markdown_path(output_dir: Path, stem: str) -> Path:
    candidate = output_dir / f"{stem}.md"
    if not candidate.exists():
        return candidate

    suffix = 2
    while True:
        candidate = output_dir / f"{stem}_{suffix}.md"
        if not candidate.exists():
            return candidate
        suffix += 1


def normalize_blanks(text: str) -> str:
    """Collapse 3+ consecutive newlines into 2."""
    return re.sub(r'\n{3,}', '\n\n', text)


def build_header(title: str, source: str, word_count: int, **extras) -> str:
    """Build the blockquote metadata header used by all converters."""
    lines = [f"# {title}", ""]
    lines.append(f"> **Source**: `{source}`  ")
    for key, val in extras.items():
        lines.append(f"> **{key}**: {val}  ")
    lines.append(f"> **Word Count**: {word_count:,}  ")
    lines.extend(["", "---", ""])
    return "\n".join(lines)


def vault_frontmatter(title: str, source_type: str, source_file: str) -> str:
    """Generate Obsidian-compatible YAML frontmatter."""
    return (
        f"---\n"
        f'title: "{title}"\n'
        f"tags: [converted, {source_type}]\n"
        f"created: {date.today().isoformat()}\n"
        f'source: "{source_file}"\n'
        f"---\n\n"
    )


def write_output(
    body: str,
    title: str,
    source_file: str,
    word_count: int,
    output_dir: Path,
    source_type: str,
    vault_dir: Path | None = None,
    header_extras: dict | None = None,
) -> ConvertResult:
    """Write markdown to output_dir and optionally copy to vault."""
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = reserve_output_path(output_dir, output_stem(title, source_file, source_type))
    md_name = md_path.name

    header = build_header(title, source_file, word_count, **(header_extras or {}))
    content = header + body + "\n"
    atomic_write_text(md_path, content)

    # Vault delivery
    if vault_dir:
        vault_type_dir = vault_dir / source_type
        vault_type_dir.mkdir(parents=True, exist_ok=True)
        vault_path = reserve_output_path(vault_type_dir, md_path.stem)
        vault_content = vault_frontmatter(title, source_type, source_file) + content
        atomic_write_text(vault_path, vault_content)

    return ConvertResult(True, str(md_path), word_count, f"OK -> {md_name}")


# ---------------------------------------------------------------------------
# Format routing
# ---------------------------------------------------------------------------

SUPPORTED = {'.pdf', '.docx', '.html', '.htm', '.txt', '.rtf', '.xlsx', '.png', '.jpg', '.jpeg', '.webp'}

SUBFOLDER = {
    '.pdf': 'pdf', '.docx': 'docx',
    '.html': 'html', '.htm': 'html',
    '.txt': 'txt', '.rtf': 'rtf',
    '.xlsx': 'spreadsheets',
    '.png': 'quotes', '.jpg': 'quotes', '.jpeg': 'quotes', '.webp': 'quotes',
}


def route(path: str, base_output: Path, vault_dir: Path | None = None, *, should_cancel=None) -> ConvertResult:
    """Detect format and call the right converter."""
    # URL detection
    if path.startswith("http://") or path.startswith("https://"):
        out = base_output / "html"
        return convert_html(path, out, vault_dir)

    p = Path(path)
    ext = p.suffix.lower()
    if ext not in SUPPORTED:
        return ConvertResult(False, "", 0, f"Unsupported format: {ext}")

    out = base_output / SUBFOLDER[ext]
    if ext == ".pdf":
        return convert_pdf(path, out, vault_dir, should_cancel=should_cancel)
    converters = {
        '.pdf': convert_pdf,
        '.docx': convert_docx,
        '.html': convert_html,
        '.htm': convert_html,
        '.txt': convert_txt,
        '.rtf': convert_rtf,
        '.xlsx': convert_xlsx,
        '.png': convert_image_quotes,
        '.jpg': convert_image_quotes,
        '.jpeg': convert_image_quotes,
        '.webp': convert_image_quotes,
    }
    return converters[ext](path, out, vault_dir)


def convert_image_quotes(path: str, output_dir: Path, vault_dir: Path | None = None) -> ConvertResult:
    return convert_image_folder_quotes([path], output_dir, vault_dir)


def convert_image_folder_quotes(
    paths: list[str],
    output_dir: Path,
    vault_dir: Path | None = None,
    hooks: QuoteBatchHooks | None = None,
    raw_ocr_mode: str = "different",
) -> ConvertResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    total = len(paths)
    processed = 0
    canceled = False
    session = OcrSession()
    checkpoint = QuoteCheckpoint(output_dir, quote_batch_stem(paths), total, raw_ocr_mode)
    checkpoint.save(records, processed, "running")
    should_cancel = hooks.should_cancel if hooks else None

    def notice(message):
        checkpoint.report["notices"].append(message)
        if hooks and hooks.on_status:
            hooks.on_status(message)

    for path in sorted(paths):
        if should_cancel and should_cancel():
            canceled = True
            break
        name = Path(path).name
        checkpoint.save(records, processed, "running", str(path))
        if hooks and hooks.on_image_started:
            hooks.on_image_started(processed + 1, total, name)
        try:
            ocr_result = ocr_image(Path(path), should_cancel=should_cancel,
                                   session=session, on_status=notice)
            new_records = extract_quote_records(ocr_result.text, source_image=name)
            if not new_records:
                raise ValueError("No quotes found in image")
            records.extend(new_records)
        except OcrCancelled:
            canceled = True
            break
        except Exception as exc:
            checkpoint.report["failed"].append({"image": str(path), "error": str(exc)})
            notice(f"Failed: {name}: {exc}")
        processed += 1
        checkpoint.save(records, processed, "running")
        if hooks and hooks.on_image_processed:
            hooks.on_image_processed(processed, total, name)

    failed = len(checkpoint.report["failed"])
    state = "canceled" if canceled else "completed_with_errors" if failed else "completed"
    checkpoint.save(records, processed, state)
    output_path = checkpoint.path
    total_words = sum(len(record.quote.split()) for record in records)

    if vault_dir and records:
        vault_quotes_dir = vault_dir / "quotes"
        vault_path = reserve_output_path(vault_quotes_dir, output_path.stem)
        atomic_write_text(vault_path, output_path.read_text(encoding="utf-8"))

    if canceled:
        message = f"CANCELED -> {output_path.name} ({processed}/{total} images)" if records else f"CANCELED ({processed}/{total} images processed)"
        return ConvertResult(False, str(output_path), total_words, message)
    if failed:
        return ConvertResult(False, str(output_path), total_words,
                             f"PARTIAL -> {output_path.name} ({processed - failed}/{total} succeeded; {failed} failed; see progress report)")
    if not records:
        return ConvertResult(False, str(output_path), 0, "SKIPPED (no quotes found)")
    return ConvertResult(True, str(output_path), total_words, f"OK -> {output_path.name}")


# ---------------------------------------------------------------------------
# 1. PDF converter (with OCR auto-fallback)
# ---------------------------------------------------------------------------

def _ocr_pdf_page(page, should_cancel=None) -> str:
    # Cap rendered dimensions to avoid unbounded 300-DPI image allocations.
    scale = min(200 / 72, 2200 / max(page.rect.width, page.rect.height))
    with tempfile.TemporaryDirectory(prefix="md-converter-pdf-") as directory:
        path = Path(directory) / "page.png"
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB)
        pix.save(path)
        return _run_backend("tesseract", path, should_cancel=should_cancel).text


def convert_pdf(path: str, output_dir: Path, vault_dir: Path | None = None, *, should_cancel=None) -> ConvertResult:
    """Extract each page independently, preserving partial results on OCR failure."""
    source = Path(path)
    body = []
    failures = []
    words = 0
    canceled = False
    with fitz.open(path) as doc:
        page_count = len(doc)
        for index, page in enumerate(doc, start=1):
            if should_cancel and should_cancel():
                canceled = True
                break
            text = page.get_text().strip()
            if not text and (page.get_images() or page.get_drawings()):
                try:
                    text = _ocr_pdf_page(page, should_cancel=should_cancel)
                except OcrCancelled:
                    canceled = True
                    break
                except Exception as exc:
                    failures.append(index)
                    body.extend([f"## Page {index}", f"OCR failed: {exc}", ""])
                    continue
            if text:
                words += len(text.split())
                body.extend([f"## Page {index}", normalize_blanks(text), ""])
    if not body:
        return ConvertResult(False, "", 0, "CANCELED" if canceled else "SKIPPED (empty PDF)")
    result = write_output("\n".join(body), source.stem, source.name, words,
                          output_dir, "pdf", vault_dir, header_extras={"Pages": str(page_count)})
    if canceled:
        return ConvertResult(False, result.output_path, words, f"CANCELED -> {Path(result.output_path).name}")
    if failures:
        return ConvertResult(False, result.output_path, words,
                             f"PARTIAL -> {Path(result.output_path).name}; OCR failed on pages {failures}")
    return result


# ---------------------------------------------------------------------------
# 2. DOCX converter (ported from docx_to_md.py)
# ---------------------------------------------------------------------------

def _run_to_md(run) -> str:
    text = run.text
    if not text:
        return ""
    if run.bold and run.italic:
        return f"***{text}***"
    if run.bold:
        return f"**{text}**"
    if run.italic:
        return f"*{text}*"
    return text


def _para_to_md(para) -> str:
    style = para.style.name.lower()
    # Paragraph.runs omits hyperlink runs. XPath preserves their document order.
    parts = [_run_to_md(Run(element, para))
             for element in para._p.xpath("./w:r | ./w:hyperlink/w:r")]
    text = "".join(parts).strip() or para.text.strip()
    if not text:
        return ""

    if style.startswith("heading"):
        try:
            level = min(int(style.split()[-1]), 6)
        except (ValueError, IndexError):
            level = 1
        return f"{'#' * level} {text}"
    if style == "title":
        return f"# {text}"
    if style == "subtitle":
        return f"## {text}"
    if style.startswith("list bullet"):
        depth = style.count("2") + style.count("3")
        return f"{'  ' * depth}- {text}"
    if style.startswith("list number"):
        depth = style.count("2") + style.count("3")
        return f"{'  ' * depth}1. {text}"
    if "quote" in style:
        return f"> {text}"
    return text


def _table_to_md(table: DocxTable) -> str:
    rows = []
    for row in table.rows:
        cells = [c.text.strip().replace("|", r"\|").replace("\n", " ") for c in row.cells]
        rows.append(cells)
    if not rows:
        return ""
    cols = max(len(r) for r in rows)
    for r in rows:
        while len(r) < cols:
            r.append("")
    lines = ["| " + " | ".join(rows[0]) + " |"]
    lines.append("| " + " | ".join(["---"] * cols) + " |")
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def convert_docx(path: str, output_dir: Path, vault_dir: Path | None = None) -> ConvertResult:
    """Convert a DOCX file preserving headings, formatting, lists, and tables."""
    p = Path(path)
    doc = Document(path)
    blocks = []
    word_count = 0

    for child in doc.element.body:
        tag = child.tag.split("}")[-1]
        if tag == "p":
            line = _para_to_md(Paragraph(child, doc))
            blocks.append(line if line else "")
            if line:
                word_count += len(line.split())
        elif tag == "tbl":
            md = _table_to_md(DocxTable(child, doc))
            if md:
                blocks.extend(["", md, ""])
                word_count += len(md.split())

    body = normalize_blanks("\n".join(blocks)).strip()
    if word_count == 0:
        return ConvertResult(False, "", 0, "SKIPPED (empty)")

    return write_output(body, p.stem, p.name, word_count, output_dir, "docx", vault_dir)


# ---------------------------------------------------------------------------
# 3. HTML / URL converter
# ---------------------------------------------------------------------------

def convert_html(path_or_url: str, output_dir: Path, vault_dir: Path | None = None) -> ConvertResult:
    """Convert HTML file or URL to Markdown."""
    is_url = path_or_url.startswith("http://") or path_or_url.startswith("https://")

    if is_url:
        html = _fetch_url_html(path_or_url)
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else path_or_url
        source = path_or_url
    else:
        p = Path(path_or_url)
        html = p.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else p.stem
        source = p.name

    # Remove script/style tags before conversion
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    body = html_to_md(str(soup), heading_style="ATX", strip=["img"])
    body = normalize_blanks(body).strip()
    word_count = len(body.split())

    if word_count == 0:
        return ConvertResult(False, "", 0, "SKIPPED (empty page)")

    extras = {"URL": f"`{path_or_url}`"} if is_url else {}
    return write_output(body, title, source, word_count, output_dir, "html", vault_dir, extras)


# ---------------------------------------------------------------------------
# 4. TXT converter
# ---------------------------------------------------------------------------

def convert_txt(path: str, output_dir: Path, vault_dir: Path | None = None) -> ConvertResult:
    """Wrap a plain text file in a Markdown metadata header."""
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace").strip()
    word_count = len(text.split())

    if word_count == 0:
        return ConvertResult(False, "", 0, "SKIPPED (empty)")

    return write_output(text, p.stem, p.name, word_count, output_dir, "txt", vault_dir)


# ---------------------------------------------------------------------------
# 5. RTF converter
# ---------------------------------------------------------------------------

def convert_rtf(path: str, output_dir: Path, vault_dir: Path | None = None) -> ConvertResult:
    """Convert RTF to Markdown by stripping RTF formatting."""
    p = Path(path)
    try:
        # Read as raw bytes first — RTF files are almost never UTF-8.
        raw_bytes = p.read_bytes()

        # Decode with latin-1, which maps every byte 0x00-0xFF one-to-one to
        # Unicode code-points. This preserves the original bytes so that
        # striprtf can interpret RTF encoding directives (\\ansicpg, etc.)
        # and produce correct Unicode output.
        raw = raw_bytes.decode("latin-1")

        text = rtf_to_text(raw, errors="ignore").strip()
    except Exception as e:
        return ConvertResult(False, "", 0, f"ERROR reading RTF: {e}")

    word_count = len(text.split())

    if word_count == 0:
        return ConvertResult(False, "", 0, "SKIPPED (empty)")

    return write_output(text, p.stem, p.name, word_count, output_dir, "rtf", vault_dir)


def convert_xlsx(path: str, output_dir: Path, vault_dir: Path | None = None) -> ConvertResult:
    """Convert each XLSX workbook sheet to a separate Markdown file."""
    sheet_count, total_words, output_paths = write_xlsx_sheets(
        path,
        output_dir,
        vault_dir,
        write_output,
    )

    if sheet_count == 0:
        return ConvertResult(False, "", 0, "SKIPPED (empty workbook)")

    return ConvertResult(
        True,
        str(output_dir),
        total_words,
        f"OK -> {sheet_count} sheets: {', '.join(output_paths)}",
    )


# ---------------------------------------------------------------------------
# 7. Raw pasted text converter
# ---------------------------------------------------------------------------

def convert_raw_text(text: str, output_dir: Path, vault_dir: Path | None = None) -> ConvertResult:
    """Save raw pasted text as a Markdown file."""
    text = text.strip()
    word_count = len(text.split())
    if word_count == 0:
        return ConvertResult(False, "", 0, "SKIPPED (empty)")

    # Generate title from first line (truncated to 60 chars)
    first_line = text.split('\n')[0].strip()
    title = first_line[:60] if first_line else "Pasted Text"
    # Clean title for display
    title = re.sub(r'[#*>\-=]', '', title).strip() or "Pasted Text"

    return write_output(text, title, "pasted-text", word_count, output_dir, "txt", vault_dir)


# ---------------------------------------------------------------------------
# 8. Pasted input router (text or URL)
# ---------------------------------------------------------------------------

def convert_pasted(text: str, base_output: Path, vault_dir: Path | None = None) -> ConvertResult:
    """Route pasted text - if it looks like a URL, fetch it; otherwise save as text."""
    text = text.strip()
    if text.startswith("http://") or text.startswith("https://"):
        out = base_output / "html"
        return convert_html(text, out, vault_dir)
    return convert_raw_text(text, base_output / "txt", vault_dir)
