import threading
import unittest
from unittest import mock
from test_cli_mode import load_converter_app


class JobReliabilityTests(unittest.TestCase):
    def test_start_reserves_job_before_background_thread_runs(self):
        module = load_converter_app()
        api = module.Api()
        with mock.patch.object(module.threading, 'Thread') as thread:
            api.convert_files(['a.jpg'])
            api.convert_files(['b.jpg'])
        self.assertEqual(thread.call_count, 1)
        self.assertTrue(api._job_running)

    def test_setup_failure_releases_job_and_hides_abort(self):
        module = load_converter_app()
        api = module.Api()
        api.window = mock.Mock()
        with mock.patch.object(api, '_effective_output_dir', side_effect=OSError('disk unavailable')):
            api._worker(['a.jpg'])
        self.assertFalse(api._job_running)
        calls = str(api.window.evaluate_js.call_args_list)
        self.assertIn('disk unavailable', calls)
        self.assertIn('hideAbortButton()', calls)

    def test_paste_failure_is_not_reported_as_done(self):
        module = load_converter_app()
        api = module.Api()
        api.window = mock.Mock()
        with mock.patch.object(module, 'convert_pasted', side_effect=OSError('disk full')):
            api._paste_worker('hello')
        calls = str(api.window.evaluate_js.call_args_list)
        self.assertIn('Failed:', calls)
        self.assertNotIn('Done: 1 item converted', calls)

    def test_progress_identifies_in_flight_image_before_completion(self):
        module = load_converter_app()
        api = module.Api()
        api.window = mock.Mock()
        def convert(paths, output, vault, hooks, **kwargs):
            self.assertTrue(callable(getattr(hooks, 'on_image_started', None)))
            hooks.on_image_started(1, 2, 'a.jpg')
            self.assertIn('Processing 1 / 2: a.jpg', str(api.window.evaluate_js.call_args_list))
            hooks.on_image_processed(1, 2, 'a.jpg')
            hooks.on_image_started(2, 2, 'b.jpg')
            self.assertIn('Processing 2 / 2: b.jpg', str(api.window.evaluate_js.call_args_list))
            return module.ConvertResult(True, '/tmp/result.md', 2, 'OK')
        with mock.patch.object(module, 'convert_image_folder_quotes', side_effect=convert):
            api._worker(['a.jpg', 'b.jpg'])
        self.assertNotIn('ERROR:', str(api.window.evaluate_js.call_args_list))

    def test_staged_queue_clears_before_worker_changes_view(self):
        module = load_converter_app()
        api = module.Api()
        api._staged = ['a.jpg']
        events = []
        with mock.patch.object(api, '_refresh_stage_ui', side_effect=lambda: events.append('queue')), \
             mock.patch.object(api, '_worker', side_effect=lambda paths: events.append('worker')), \
             mock.patch.object(module.threading, 'Thread') as thread:
            thread.side_effect = lambda **kwargs: mock.Mock(start=kwargs['target'])
            api.convert_staged()
        self.assertEqual(events, ['queue', 'worker'])


if __name__ == '__main__':
    unittest.main()
