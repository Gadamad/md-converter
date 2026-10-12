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
