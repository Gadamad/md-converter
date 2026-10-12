"""Named-copy preference and desktop API regression tests."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cli_mode import load_converter_app
from preferences import Preferences


class CopyFolderApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.base = self.root / 'exports'
        self.module = load_converter_app()
        self.module.Preferences = Preferences
        self.module.OUTPUT_DIR = self.base
        self.api = self.module.Api()
        self.api._preferences_path = self.root / 'preferences.json'
        self.api._preferences = Preferences(output_dir=self.base)

    def require_api(self):
        self.assertTrue(hasattr(self.api, 'set_copy_subfolder'), 'The dashboard needs a guarded named-copy preference API')
        self.assertTrue(hasattr(self.api, '_effective_copy_dir'))

    def test_named_copy_persists_and_exposes_resolved_destination(self):
        self.require_api()
        result = self.api.set_copy_subfolder('  Árvíztűrő jegyzetek  ')
        expected = self.base / 'Árvíztűrő jegyzetek'
        self.assertEqual(result['copy_subfolder'], 'Árvíztűrő jegyzetek')
        self.assertEqual(self.api._effective_copy_dir(), expected)
        self.assertEqual(self.api._effective_output_dir(), self.base)
        self.assertEqual(self.api.get_application_state()['copy_dir'], str(expected))
        self.assertEqual(Preferences.load(self.api._preferences_path).copy_subfolder, result['copy_subfolder'])
        self.assertFalse(expected.exists(), 'Choosing the preference must not create output directories')
        self.assertIsNone(self.api.set_copy_subfolder(None)['copy_subfolder'])
        self.assertIsNone(self.api._effective_copy_dir())

    def test_invalid_name_preserves_memory_and_disk(self):
        self.require_api()
        self.api.set_copy_subfolder('Original')
        before = self.api._preferences_path.read_bytes()
        for invalid in ('', '..', '../outside', '/tmp/outside', 'a\\b', 'a\0b'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.api.set_copy_subfolder(invalid)
            self.assertEqual(self.api.get_preferences()['copy_subfolder'], 'Original')
            self.assertEqual(self.api._preferences_path.read_bytes(), before)

    def test_save_failure_rolls_back_and_releases_job_lock(self):
        self.require_api()
        self.api.set_copy_subfolder('Original')
        before = self.api._preferences_path.read_bytes()
        with mock.patch.object(self.api, '_save_preferences', side_effect=OSError('read-only')):
            with self.assertRaises(OSError):
                self.api.set_copy_subfolder('Changed')
        self.assertEqual(self.api.get_preferences()['copy_subfolder'], 'Original')
        self.assertEqual(self.api._preferences_path.read_bytes(), before)
        self.assertTrue(self.api._job_lock.acquire(blocking=False))
        self.api._job_lock.release()

    def test_busy_and_pending_worker_guard_preserve_preference(self):
        self.require_api()
        self.api._job_running = True
        with self.assertRaises(RuntimeError):
            self.api.set_copy_subfolder('Busy')
        self.api._job_running = False
        self.api._job_lock.acquire()
        try:
            with self.assertRaises(RuntimeError):
                self.api.set_copy_subfolder('Pending')
        finally:
            self.api._job_lock.release()
        self.assertIsNone(self.api.get_preferences()['copy_subfolder'])

    def test_copy_destination_rejects_existing_file_and_symlink_escape(self):
        self.require_api()
        self.base.mkdir()
        (self.base / 'Occupied').write_text('keep', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.api.set_copy_subfolder('Occupied')
        outside = self.root / 'outside'
        outside.mkdir()
        (self.base / 'Escapes').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.api.set_copy_subfolder('Escapes')
        self.assertIsNone(self.api.get_preferences()['copy_subfolder'])

    def test_copy_destination_rejects_alias_to_primary_export_folder(self):
        self.require_api()
        (self.base / 'pdf').mkdir(parents=True)
        (self.base / 'Saved copies').symlink_to(self.base / 'pdf', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'regular exports.*different'):
            self.api.set_copy_subfolder('Saved copies')

    def test_copy_destination_rejects_linked_folders_that_delivery_cannot_use(self):
        self.require_api()
        (self.base / 'Real copies').mkdir(parents=True)
        (self.base / 'Linked copies').symlink_to(self.base / 'Real copies', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'linked folder'):
            self.api.set_copy_subfolder('Linked copies')

    def test_output_base_change_validates_current_copy_before_persisting(self):
        self.require_api()
        self.api.set_copy_subfolder('Notes')
        other = self.root / 'other'
        other.mkdir()
        (other / 'Notes').write_text('existing file', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.api.save_preferences({'output_dir': str(other)})
        self.assertEqual(self.api._effective_output_dir(), self.base)
        self.assertEqual(self.api.get_preferences()['copy_subfolder'], 'Notes')

    def test_later_destination_damage_is_visible_without_breaking_startup(self):
        self.require_api()
        self.api.set_copy_subfolder('Notes')
        self.base.mkdir()
        (self.base / 'Notes').write_text('existing file', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.api._effective_copy_dir()
        state = self.api.get_application_state()
        self.assertIsNone(state['copy_dir'])
        self.assertTrue(state['copy_error'])
        self.assertEqual(self.api.get_preferences()['copy_subfolder'], 'Notes')
        self.assertIsNone(self.api.set_copy_subfolder(None)['copy_subfolder'])

    def test_worker_snapshot_defers_later_file_or_symlink_damage_until_delivery(self):
        self.require_api()
        self.api.set_copy_subfolder('Notes')
        self.base.mkdir()
        destination = self.base / 'Notes'
        destination.write_text('existing file', encoding='utf-8')
        self.assertEqual(self.api._effective_copy_dir(validate_destination=False), destination)
        destination.unlink()
        destination.symlink_to(self.root / 'outside', target_is_directory=True)
        self.assertEqual(self.api._effective_copy_dir(validate_destination=False), destination)
        with self.assertRaises(ValueError):
            self.api._effective_copy_dir()

    def test_old_preferences_stub_without_field_disables_copy(self):
        self.require_api()
        self.api._preferences = type('OldPreferences', (), {'output_dir': None})()
        self.assertIsNone(self.api._effective_copy_dir())


if __name__ == '__main__':
    unittest.main()
