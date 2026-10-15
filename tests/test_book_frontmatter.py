"""Book metadata must remain a single, readable frontmatter value."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from converters import vault_frontmatter


def test_quoted_multiline_book_metadata_cannot_break_vault_frontmatter():
    title = 'Az "őszinte" könyv\nMásodik sor'
    source = 'book\\notes "őű".epub'
    header = vault_frontmatter(title, 'epub', source)
    lines = header.splitlines()
    assert len(lines) == 7
    assert json.loads(lines[1].removeprefix('title: ')) == title
    assert json.loads(lines[4].removeprefix('source: ')) == source
    assert lines[0] == lines[5] == '---'
