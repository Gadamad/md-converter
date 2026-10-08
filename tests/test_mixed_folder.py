from pathlib import Path
import sys
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cli_mode import load_converter_app


def test_add_folder_stages_mixed_supported_files_recursively(tmp_path):
    app = load_converter_app()
    app.SUPPORTED = {'.pdf', '.docx', '.xlsx', '.txt', '.rtf', '.html', '.htm', '.png', '.jpg', '.jpeg', '.webp'}
    nested = tmp_path / 'nested'
    nested.mkdir()
    names = ['report.DOCX', 'notes.txt', 'book.pdf', 'table.xlsx', 'quote.jpg', 'page.html', 'letter.rtf']
    expected = []
    for index, name in enumerate(names):
        path = (nested if index % 2 else tmp_path) / name
        path.write_bytes(b'fixture')
        expected.append(str(path))
    (tmp_path / 'ignored.zip').write_bytes(b'not supported')
    api = app.Api()
    api.window = mock.Mock()
    api.window.create_file_dialog.return_value = [str(tmp_path)]
    api.add_folder()
    assert set(api._collect_staged_paths()) == set(expected)


def test_dropped_document_folder_is_not_treated_as_empty(tmp_path):
    app = load_converter_app()
    app.SUPPORTED = {'.docx', '.txt'}
    path = tmp_path / 'document.docx'
    path.write_bytes(b'fixture')
    api = app.Api()
    api.stage_files([str(tmp_path), str(path)])
    assert api._collect_staged_paths() == [str(path)]
    assert len(api._staged_folders) == 1


def test_overlapping_mixed_folders_are_deduplicated(tmp_path):
    app = load_converter_app()
    app.SUPPORTED = {'.docx', '.pdf', '.jpg'}
    nested = tmp_path / 'nested'
    nested.mkdir()
    first, second = tmp_path / 'first.docx', nested / 'second.pdf'
    first.write_bytes(b'fixture')
    second.write_bytes(b'fixture')
    api = app.Api()
    api.window = mock.Mock()
    api.window.create_file_dialog.side_effect = [[str(tmp_path)], [str(nested)]]
    api.add_folder()
    api.add_folder()
    assert set(api._collect_staged_paths()) == {str(first), str(second)}
    assert len(api._collect_staged_paths()) == 2


def test_mixed_folder_converts_real_documents_and_spreadsheets(tmp_path, monkeypatch):
    import converter_app as app
    from docx import Document
    from openpyxl import Workbook
    import pymupdf

    source = tmp_path / 'source'
    nested = source / 'nested'
    nested.mkdir(parents=True)
    doc = Document()
    doc.add_paragraph('Folder document conversion works.')
    doc.save(source / 'report.docx')
    workbook = Workbook()
    workbook.active.append(['Item', 'Quantity'])
    workbook.active.append(['Notebook', 3])
    workbook.save(nested / 'inventory.xlsx')
    workbook.close()
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((72,72), 'A folder can contain PDF documents.')
        pdf.save(source / 'book.pdf')
    (nested / 'notes.txt').write_text('Text files belong in the same queue.')
    (source / 'ignore.zip').write_bytes(b'unsupported')

    monkeypatch.setattr(app, 'default_preferences_path', lambda: tmp_path / 'preferences.json')
    monkeypatch.setattr(app, 'VAULT_DIR', None)
    api = app.Api()
    output = tmp_path / 'output'
    api.save_preferences({'output_dir': str(output)})
    api.stage_folder(source)
    assert len(api._collect_staged_paths()) == 4
    api._worker(api._collect_staged_paths())
    outputs = list(output.rglob('*.md'))
    assert len(outputs) == 4
    assert {path.parent.name for path in outputs} == {'docx', 'spreadsheets', 'pdf', 'txt'}
    content = '\n'.join(path.read_text() for path in outputs)
    for text in ('Folder document conversion works.', 'Notebook', 'A folder can contain PDF documents.', 'Text files belong in the same queue.'):
        assert text in content
