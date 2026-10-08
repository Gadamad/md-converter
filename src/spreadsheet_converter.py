import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from tempfile import TemporaryFile
from typing import Protocol, TextIO


class WrittenSheet(Protocol):
    output_path: str


class SheetWriter(Protocol):
    """Write a sheet, consuming all body chunks before returning."""

    def __call__(
        self,
        body: str | Iterable[str],
        title: str,
        source_file: str,
        word_count: int,
        output_dir: Path,
        source_type: str,
        vault_dir: Path | None = None,
        header_extras: dict[str, str] | None = None,
    ) -> WrittenSheet: ...


def _cell_to_md(value) -> str:
    if value is None:
        return ""
    return str(value).replace("|", r"\|").replace("\n", " ").strip()


def _trim_rows(rows: list[list[str]]) -> list[list[str]]:
    while rows and not any(rows[-1]):
        rows.pop()

    if not rows:
        return []

    last_col = 0
    for row in rows:
        for index, cell in enumerate(row, start=1):
            if cell:
                last_col = max(last_col, index)

    return [row[:last_col] for row in rows]


def _rows_to_md(rows: list[list[str]]) -> str:
    trimmed_rows = _trim_rows(rows)
    if not trimmed_rows:
        return ""

    col_count = max(len(row) for row in trimmed_rows)
    normalized = [row + [""] * (col_count - len(row)) for row in trimmed_rows]
    lines = ["| " + " | ".join(normalized[0]) + " |"]
    lines.append("| " + " | ".join(["---"] * col_count) + " |")
    for row in normalized[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _spooled_rows_to_md(
    spool: TextIO, row_count: int, col_count: int
) -> Iterator[str]:
    """Render normalized rows a line at a time, with no trailing newline."""
    spool.seek(0)
    for index in range(row_count):
        row = json.loads(spool.readline())
        row.extend([""] * (col_count - len(row)))
        prefix = "\n" if index else ""
        yield prefix + "| " + " | ".join(row) + " |"
        if index == 0:
            yield "\n| " + " | ".join(["---"] * col_count) + " |"


def write_xlsx_sheets(
    path: str,
    output_dir: Path,
    vault_dir: Path | None,
    write_sheet: SheetWriter,
) -> tuple[int, int, list[str]]:
    from openpyxl import load_workbook

    source_path = Path(path)
    workbook = load_workbook(path, read_only=True, data_only=True)
    sheet_count = 0
    total_words = 0
    output_paths: list[str] = []

    try:
        for sheet in workbook.worksheets:
            # Read actual XML rows without padding to potentially stale bounds.
            sheet.reset_dimensions()
            with TemporaryFile(mode="w+", encoding="utf-8") as spool:
                row_count = 0
                col_count = 0
                cell_words = 0
                for index, values in enumerate(sheet.iter_rows(values_only=True), start=1):
                    row = [_cell_to_md(cell) for cell in values]
                    while row and not row[-1]:
                        row.pop()
                    if row:
                        row_count = index
                        col_count = max(col_count, len(row))
                        cell_words += sum(len(cell.split()) for cell in row)
                    spool.write(json.dumps(row, ensure_ascii=False) + "\n")

                if not row_count:
                    continue

                # Each data/header row adds col_count + 1 pipe tokens; the
                # separator adds those pipes plus col_count dash tokens.
                # This exactly matches len(body.split()) without building body.
                word_count = cell_words + row_count * (col_count + 1) + 2 * col_count + 1
                title = f"{source_path.stem} {sheet.title}"
                result = write_sheet(
                    _spooled_rows_to_md(spool, row_count, col_count),
                    title,
                    source_path.name,
                    word_count,
                    output_dir,
                    "spreadsheets",
                    vault_dir,
                    header_extras={"Sheet": sheet.title},
                )
            sheet_count += 1
            total_words += word_count
            output_paths.append(Path(result.output_path).name)
    finally:
        workbook.close()

    return sheet_count, total_words, output_paths
