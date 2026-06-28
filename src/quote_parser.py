from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class QuoteRecord:
    quote: str
    author: str
    source_image: str
    raw_ocr: str


_AUTHOR_PREFIX_RE = re.compile(r"^(?:[-—–]{1,2}\s*)(.+?)\s*$")


def _is_author_only_line(line: str) -> bool:
    match = _AUTHOR_PREFIX_RE.match(line.strip())
    return bool(match and match.group(1).strip())


def _normalize_text(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    cleaned: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if not previous_blank:
                cleaned.append("")
            previous_blank = True
            continue
        cleaned.append(line)
        previous_blank = False
    return "\n".join(cleaned).strip()


def _split_blocks(text: str) -> list[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return []
    return [block.strip() for block in re.split(r"\n\s*\n", normalized) if block.strip()]


def _extract_author(lines: list[str]) -> tuple[str, str]:
    if len(lines) < 2:
        return "\n".join(lines).strip(), ""

    final_line = lines[-1].strip()
    match = _AUTHOR_PREFIX_RE.match(final_line)
    if match:
        author = match.group(1).strip()
        if author:
            return "\n".join(lines[:-1]).strip(), author

    return "\n".join(lines).strip(), ""


def extract_quote_records(text: str, source_image: str) -> list[QuoteRecord]:
    records: list[QuoteRecord] = []
    for block in _split_blocks(text):
        lines = [line for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        if len(lines) == 1 and _is_author_only_line(lines[0]):
            continue
        quote, author = _extract_author(lines)
        if not quote.strip():
            continue
        records.append(
            QuoteRecord(
                quote=quote.strip(),
                author=author.strip(),
                source_image=source_image,
                raw_ocr=block,
            )
        )

    if records:
        return records

    normalized = _normalize_text(text)
    if not normalized:
        return []
    normalized_lines = [line for line in normalized.split("\n") if line.strip()]
    if len(normalized_lines) == 1 and _is_author_only_line(normalized_lines[0]):
        return []
    return [QuoteRecord(quote=normalized, author="", source_image=source_image, raw_ocr=normalized)]
