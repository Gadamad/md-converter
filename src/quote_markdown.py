from __future__ import annotations

from collections.abc import Iterable
from typing import Literal
import re

from quote_parser import QuoteRecord

RawOcrMode = Literal["always", "never", "different"]


def _render_blockquote(text: str) -> str:
    return "\n".join(f"> {line}" for line in text.splitlines())


def _normalize_for_comparison(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    cleaned: list[str] = []
    prev_blank = False
    for line in lines:
        if not line:
            if not prev_blank:
                cleaned.append("")
            prev_blank = True
            continue
        cleaned.append(line)
        prev_blank = False
    normalized = "\n".join(cleaned).strip()
    normalized = re.sub(r"^(?:[-–—]{1,2}\s*)", "— ", normalized, flags=re.MULTILINE)
    return normalized


def _raw_ocr_effectively_same(record: QuoteRecord) -> bool:
    if record.author:
        reconstructed = f"{record.quote}\n— {record.author}"
    else:
        reconstructed = record.quote
    return _normalize_for_comparison(record.raw_ocr) == _normalize_for_comparison(reconstructed)


def render_quote_batch_markdown(
    records: Iterable[QuoteRecord],
    title: str = "Extracted Quotes",
    raw_ocr_mode: RawOcrMode = "different",
) -> str:
    ordered = list(records)
    lines = [f"# {title}", ""]

    for index, record in enumerate(ordered, start=1):
        lines.extend(
            [
                f"## Quote {index}",
                f"**Source image:** {record.source_image}",
                f"**Author:** {record.author}",
                "",
                _render_blockquote(record.quote),
                "",
            ]
        )

        show_raw = raw_ocr_mode == "always" or (
            raw_ocr_mode == "different" and not _raw_ocr_effectively_same(record)
        )
        if show_raw:
            lines.extend(["**Raw OCR:**", record.raw_ocr, ""])

    return "\n".join(lines).strip() + "\n"
