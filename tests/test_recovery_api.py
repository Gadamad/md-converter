from pathlib import Path
import sys
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cli_mode import load_converter_app
from quote_checkpoint import QuoteCheckpoint
from quote_parser import QuoteRecord


def test_recovery_lists_saved_work_and_rejects_foreign_paths(tmp_path):
    module = load_converter_app()
    api = module.Api()
    api.save_preferences({'output_dir': str(tmp_path)})
    checkpoint = QuoteCheckpoint(tmp_path / 'quotes', 'example', ['/tmp/a.jpg', '/tmp/b.jpg'], 'different')
    checkpoint.complete(checkpoint.items[0], [QuoteRecord('Saved.', '', 'a.jpg', 'Saved.')], None)
    checkpoint.save('canceled')
    jobs = api.get_recovery_jobs()
    assert jobs[0]['saved'] == 1
    assert jobs[0]['pending'] == 1
    assert jobs[0]['id'] == 'example.progress.json'
    with mock.patch.object(api, '_start_job') as start:
        assert api.recover_job('../outside.progress.json') is False
        start.assert_not_called()
        api.recover_job(jobs[0]['id'])
        start.assert_called_once()


def test_clear_queue_removes_both_direct_files_and_folders():
    module = load_converter_app()
    api = module.Api()
    api._staged = ['/tmp/a.jpg']
    api._staged_folders = [object()]
    api.clear_queue()
    assert api._collect_staged_paths() == []
