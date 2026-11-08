from pathlib import Path
import sys
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from preferences import Preferences


@pytest.fixture
def api(tmp_path, monkeypatch):
    import converter_app as app
    monkeypatch.setattr(app, 'default_preferences_path', lambda: tmp_path / 'preferences.json')
    monkeypatch.setattr(app, 'VAULT_DIR', None)
    return app.Api()


def test_compact_default_and_saved_display_choice_survive_preferences_save(api):
    assert Preferences().show_source_details is False
    saved = api.set_show_source_details(True)
    assert saved['show_source_details'] is True
    saved = api.save_preferences({'theme': 'dark'})
    assert saved['show_source_details'] is True
    import converter_app as app
    assert app.Api().get_preferences() == saved


@pytest.mark.parametrize('invalid', [None, 'true', 0, 1, [], {}])
def test_display_choice_requires_boolean(api, invalid):
    before = api.get_preferences()
    with pytest.raises(ValueError, match='boolean'):
        api.set_show_source_details(invalid)
    assert api.get_preferences() == before


def test_failed_display_save_preserves_previous_choice(api, monkeypatch):
    api.set_show_source_details(True)
    before = api._preferences_path.read_bytes()
    monkeypatch.setattr(Preferences, 'save', lambda *args: (_ for _ in ()).throw(OSError('Disk full')))
    with pytest.raises(OSError, match='Disk full'):
        api.set_show_source_details(False)
    assert api.get_preferences()['show_source_details'] is True
    assert api._preferences_path.read_bytes() == before


def test_open_completed_file_uses_original_without_changing_queue(api, tmp_path):
    original = tmp_path / 'árvíztűrő kép.jpg'
    original.write_bytes(b'original image fixture')
    api.stage_files([str(original)])
    item = api.get_queue_state()['items'][0]
    api._queue_store.update_item(item['id'], status='done', output_path='/tmp/batch.md')
    before = api.get_queue_state()
    with mock.patch('queue_api.subprocess.Popen') as launch:
        assert api.open_queue_item(item['id']) is True
    assert launch.call_args.args[0] == ['/usr/bin/open', str(original)]
    assert api.get_queue_state() == before
    assert original.read_bytes() == b'original image fixture'


def test_open_completed_website_opens_saved_output(api, tmp_path):
    api.stage_text('https://example.com/article')
    item = api.get_queue_state()['items'][0]
    output = tmp_path / 'article.md'
    output.write_text('Saved website')
    api._queue_store.update_item(item['id'], status='done', output_path=str(output))
    with mock.patch('queue_api.subprocess.Popen') as launch:
        assert api.open_queue_item(item['id']) is True
    assert launch.call_args.args[0] == ['/usr/bin/open', str(output)]


def test_open_missing_source_never_launches_a_path_or_mutates_queue(api, tmp_path):
    image = tmp_path / 'removed.jpg'
    image.write_bytes(b'fixture')
    api.stage_files([str(image)])
    item = api.get_queue_state()['items'][0]
    api._queue_store.update_item(item['id'], status='done')
    image.unlink()
    before = api.get_queue_state()
    with mock.patch('queue_api.subprocess.Popen') as launch, pytest.raises(FileNotFoundError, match='Source'):
        api.open_queue_item(item['id'])
    launch.assert_not_called()
    assert api.get_queue_state() == before


@pytest.fixture
def partial_pdf(api, tmp_path):
    source = tmp_path / 'Árvíztűrő.PDF'
    source.write_bytes(b'PDF fixture')
    item = api.stage_files([str(source)])['items'][0]
    output_root = tmp_path / 'frozen-exports'
    output = output_root / 'pdf' / 'Árvíztűrő.md'
    output.parent.mkdir(parents=True)
    output.write_text('Saved page text')
    api._queue_store.update_item(item['id'], status='failed', output_path=str(output),
        error='Partial PDF: Missing pages: 2, 5.', options={'output_dir': str(output_root)})
    return item['id'], output


def test_partial_pdf_remains_failed_and_retryable_with_or_without_saved_output(api, partial_pdf):
    item_id, _ = partial_pdf
    for remove_output in (False, True):
        if remove_output:
            api._queue_store.update_item(item_id, output_path=None)
        state = api.get_queue_state()
        assert state['items'][0].get('partial_pdf') is True
        assert state['items'][0]['status'] == 'failed'
        assert (state['failed'], state['review'], state['done']) == (1, 0, 0)
    with mock.patch.object(api, '_start_job', return_value=True) as start:
        assert api.retry_failed() is True
    start.assert_called_once_with(api._queue_worker, state['active_id'], True)


def test_legacy_partial_pdf_is_retryable_without_claiming_a_published_output(api, partial_pdf):
    item_id, output = partial_pdf
    api._queue_store.update_item(item_id, output_path=None,
        error=f'PARTIAL -> {output.name}; OCR failed on pages 2, 5')
    state = api.get_queue_state()
    assert state['items'][0].get('partial_pdf') is True
    assert state['items'][0]['output_path'] is None
    assert (state['failed'], state['review'], state['done']) == (1, 0, 0)


def test_open_partial_pdf_uses_frozen_destination_without_changing_queue(api, tmp_path, partial_pdf):
    item_id, output = partial_pdf
    api.save_preferences({'output_dir': str(tmp_path / 'different-exports')})
    before = api.get_queue_state()
    with mock.patch('queue_api.subprocess.Popen') as launch:
        assert api.open_partial_pdf(item_id) is True
    assert launch.call_args.args[0] == ['/usr/bin/open', str(output)]
    assert api.get_queue_state() == before


@pytest.mark.parametrize('change', ['not_partial', 'not_failed', 'not_pdf', 'not_file'])
def test_open_partial_pdf_requires_a_partial_failed_pdf_item(api, tmp_path, partial_pdf, change):
    item_id, output = partial_pdf
    if change == 'not_file':
        item_id = api.stage_text('https://example.com/book.pdf')['items'][-1]['id']
        api._queue_store.update_item(item_id, status='failed', error='Partial PDF: Missing pages: 2.',
            output_path=str(output), options={'output_dir': str(output.parent.parent)})
    else:
        changes = {'not_partial': {'error': 'Conversion failed'}, 'not_failed': {'status': 'done'},
                   'not_pdf': {'source': str(tmp_path / 'a.docx')}}
        api._queue_store.update_item(item_id, **changes[change])
    item = next(item for item in api.get_queue_state()['items'] if item['id'] == item_id)
    assert item.get('partial_pdf') is not True
    with mock.patch('queue_api.subprocess.Popen') as launch, pytest.raises(ValueError, match='partial PDF'):
        api.open_partial_pdf(item_id)
    launch.assert_not_called()


@pytest.mark.parametrize('case', ['outside', 'relative', 'traversal', 'wrong_suffix', 'no_frozen_dir',
                                  'symlink_file', 'symlink_pdf_dir', 'symlink_base'])
def test_open_partial_pdf_rejects_paths_outside_frozen_pdf_boundary(api, tmp_path, partial_pdf, case):
    item_id, output = partial_pdf
    fields = {}
    if case == 'outside':
        path = tmp_path / 'other.md'
        path.write_text('Unrelated output')
    elif case == 'relative':
        path = Path('frozen-exports') / 'pdf' / output.name
    elif case == 'traversal':
        path = output.parent / '..' / 'pdf' / output.name
    elif case == 'wrong_suffix':
        path = output.with_suffix('.txt')
        path.write_text('Wrong format')
    elif case == 'no_frozen_dir':
        path = output
        fields['options'] = {}
    elif case == 'symlink_file':
        path = output.with_name('redirect.md')
        path.symlink_to(output)
    elif case == 'symlink_pdf_dir':
        path = output
        moved = output.parent.with_name('redirect')
        output.parent.rename(moved)
        output.parent.symlink_to(moved, target_is_directory=True)
    else:
        path = output
        base = output.parent.parent
        moved = base.with_name('redirect')
        base.rename(moved)
        base.symlink_to(moved, target_is_directory=True)
    api._queue_store.update_item(item_id, output_path=str(path), **fields)
    with mock.patch('queue_api.subprocess.Popen') as launch, pytest.raises(ValueError, match='partial PDF'):
        api.open_partial_pdf(item_id)
    launch.assert_not_called()


@pytest.mark.parametrize('published', [False, True])
def test_open_partial_pdf_reports_an_unavailable_export_without_launching(api, partial_pdf, published):
    item_id, output = partial_pdf
    if published:
        output.unlink()
    else:
        api._queue_store.update_item(item_id, output_path=None)
    with mock.patch('queue_api.subprocess.Popen') as launch, pytest.raises(FileNotFoundError, match='partial PDF'):
        api.open_partial_pdf(item_id)
    launch.assert_not_called()
