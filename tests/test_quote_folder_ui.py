import tempfile
import unittest
from pathlib import Path
import sys
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cli_mode import load_converter_app


class QuoteFolderUiTests(unittest.TestCase):
    def test_html_contains_folder_queue_and_abort_controls(self):
        module = load_converter_app()

        self.assertIn('id="add-folder-btn"', module.HTML)
        self.assertIn('id="folder-queue"', module.HTML)
        self.assertIn('id="clear-folders-btn"', module.HTML)
        self.assertIn('id="abort-btn"', module.HTML)

    def test_html_contains_preferences_button_and_modal(self):
        module = load_converter_app()

        self.assertIn('id="preferences-btn"', module.HTML)
        self.assertIn('id="preferences-modal"', module.HTML)
        self.assertIn('id="preferences-close-btn"', module.HTML)

    def test_preferences_modal_contains_approved_fields(self):
        module = load_converter_app()
        html = module.HTML

        self.assertIn('id="theme-select"', html)
        self.assertIn('id="raw-ocr-mode-select"', html)
        self.assertIn('id="output-dir-value"', html)
        self.assertIn('id="output-dir-browse-btn"', html)
        self.assertIn('id="auto-open-output-cb"', html)

    def test_preferences_ui_has_no_sidebar_or_history_panel(self):
        module = load_converter_app()
        html = module.HTML

        self.assertNotIn('id="history-panel"', html)
        self.assertNotIn('class="sidebar"', html)

    def test_preferences_ui_calls_backend_preferences_apis(self):
        module = load_converter_app()
        html = module.HTML

        self.assertIn('pywebview.api.get_preferences()', html)
        self.assertIn('pywebview.api.save_preferences(', html)
        self.assertIn('pywebview.api.browse_output_directory()', html)

    def test_browse_output_directory_does_not_persist_until_save(self):
        module = load_converter_app()

        class FakeWindow:
            def create_file_dialog(self, dialog_type, allow_multiple=False, directory=None):
                return ["/tmp/new-output"]

        api = module.Api()
        api.window = FakeWindow()

        selected = api.browse_output_directory()

        self.assertEqual(selected, "/tmp/new-output")
        self.assertIsNone(api.get_preferences()["output_dir"])

    # --- Approved single-operational-panel contract ---

    def test_html_has_single_operational_panel(self):
        module = load_converter_app()
        self.assertIn('class="operations-shell"', module.HTML)
        self.assertIn('class="operations-panel"', module.HTML)

    def test_no_separate_folder_row_section(self):
        module = load_converter_app()
        self.assertNotIn('class="folder-row"', module.HTML)

    def test_folder_queue_is_inside_operations_panel(self):
        module = load_converter_app()
        html = module.HTML
        panel_open = html.find('class="operations-panel"')
        queue_pos = html.find('id="folder-queue"')
        self.assertGreater(panel_open, -1, "operations-panel not found")
        self.assertGreater(queue_pos, -1, "folder-queue not found")
        self.assertGreater(queue_pos, panel_open,
                           "folder-queue must come after operations-panel opens")

    def test_log_container_is_inside_operations_panel(self):
        module = load_converter_app()
        html = module.HTML
        panel_open = html.find('class="operations-panel"')
        log_pos = html.find('id="log-container"')
        self.assertGreater(panel_open, -1, "operations-panel not found")
        self.assertGreater(log_pos, -1, "log-container not found")
        self.assertGreater(log_pos, panel_open,
                           "log-container must come after operations-panel opens")

    def test_progress_and_summary_inside_operations_shell(self):
        module = load_converter_app()
        html = module.HTML
        panel_open = html.find('class="operations-shell"')
        progress_pos = html.find('id="progress"')
        summary_pos = html.find('id="summary"')
        self.assertGreater(panel_open, -1)
        self.assertGreater(progress_pos, panel_open,
                           "progress bar must be inside operations-shell")
        self.assertGreater(summary_pos, panel_open,
                           "summary must be inside operations-shell")

    def test_remove_button_is_inside_operational_panel_context(self):
        module = load_converter_app()
        html = module.HTML
        panel_open = html.find('class="operations-shell"')
        remove_btn = html.find("remove.className = 'btn folder-remove-btn'")
        self.assertGreater(panel_open, -1, "operations-shell not found")
        self.assertGreater(remove_btn, -1, "folder-remove-btn not found")
        self.assertGreater(remove_btn, panel_open,
                           "folder-remove-btn template must be after operations-shell opens")

    def test_cancel_current_job_sets_cancel_event(self):
        module = load_converter_app()
        api = module.Api()

        api.cancel_current_job()

        self.assertTrue(api._cancel_event.is_set())

    def test_worker_passes_hooks_to_quote_batch_converter_and_updates_progress(self):
        module = load_converter_app()
        module.VAULT_DIR = None

        class FakeWindow:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def evaluate_js(self, code):
                self.calls.append(code)
                return None

        def fake_convert(paths, output_dir, vault_dir=None, hooks=None, raw_ocr_mode="different"):
            assert hooks is not None
            hooks.on_image_processed(1, 2, "a.jpg")
            hooks.on_image_processed(2, 2, "b.jpg")
            return module.ConvertResult(True, "out/extracted_quotes.md", 12, "OK -> extracted_quotes.md")

        api = module.Api()
        api.window = FakeWindow()

        with mock.patch.object(module, "convert_image_folder_quotes", side_effect=fake_convert):
            api._worker(["/tmp/a.jpg", "/tmp/b.jpg"])

        js_calls = "\n".join(api.window.calls)
        self.assertIn("setProgress(50.0)", js_calls)
        self.assertIn("setProgress(100.0)", js_calls)
        self.assertIn("Processing 1 / 2: a.jpg", js_calls)
        self.assertIn('setSummary("Done: 2/2 processed | 12 total words")', js_calls)

    def test_worker_passes_raw_ocr_mode_and_output_dir_preferences(self):
        module = load_converter_app()
        module.VAULT_DIR = None
        api = module.Api()
        api.save_preferences({
            "raw_ocr_mode": "never",
            "output_dir": "/tmp/custom-output",
        })

        with mock.patch.object(module, "convert_image_folder_quotes", return_value=module.ConvertResult(True, "out/extracted_quotes.md", 12, "OK -> extracted_quotes.md")) as convert_mock:
            api._worker(["/tmp/a.jpg"])

        args, kwargs = convert_mock.call_args
        self.assertEqual(args[:3], (["/tmp/a.jpg"], Path("/tmp/custom-output") / "quotes", None))
        self.assertEqual(kwargs["raw_ocr_mode"], "never")

    def test_worker_auto_opens_output_when_preference_enabled(self):
        module = load_converter_app()
        module.VAULT_DIR = None
        api = module.Api()
        api.save_preferences({"auto_open_output": True})

        with mock.patch.object(module, "convert_image_folder_quotes", return_value=module.ConvertResult(True, str(Path("/tmp/output") / "result.md"), 12, "OK -> result.md")), \
             mock.patch.object(module.subprocess, "run") as run_mock:
            api._worker(["/tmp/a.jpg"])

        run_mock.assert_called_with(["open", str(Path("/tmp/output").resolve())])

    def test_collect_staged_paths_dedupes_overlapping_folder_images(self):
        module = load_converter_app()

        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir) / "parent"
            child = parent / "child"
            parent.mkdir()
            child.mkdir()
            first = parent / "one.jpg"
            second = child / "two.jpg"
            first.write_bytes(b"img")
            second.write_bytes(b"img")

            api = module.Api()
            api.stage_quote_folder(parent)
            api.stage_quote_folder(child, replace=False)

            paths = api._collect_staged_paths()

        self.assertEqual(len(paths), 2)
        self.assertEqual({Path(path).name for path in paths}, {"one.jpg", "two.jpg"})

    def test_collect_staged_paths_dedupes_directly_staged_duplicates(self):
        module = load_converter_app()
        api = module.Api()
        api._staged = ["/tmp/example.txt", "/tmp/example.txt"]

        paths = api._collect_staged_paths()

        self.assertEqual(paths, ["/tmp/example.txt"])

    def test_folder_badge_uses_unique_image_count_for_overlapping_folders(self):
        module = load_converter_app()

        class FakeWindow:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def evaluate_js(self, code):
                self.calls.append(code)
                return None

        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir) / "parent"
            child = parent / "child"
            parent.mkdir()
            child.mkdir()
            (parent / "one.jpg").write_bytes(b"img")
            (child / "two.jpg").write_bytes(b"img")

            api = module.Api()
            api.window = FakeWindow()
            api.stage_quote_folder(parent)
            api.stage_quote_folder(child, replace=False)

        js_calls = "\n".join(api.window.calls)
        self.assertIn('setBadge("2 folders staged (2 images)")', js_calls)

    def test_worker_sets_failed_summary_when_quote_batch_raises(self):
        module = load_converter_app()
        module.VAULT_DIR = None

        class FakeWindow:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def evaluate_js(self, code):
                self.calls.append(code)
                return None

        api = module.Api()
        api.window = FakeWindow()

        with mock.patch.object(module, "convert_image_folder_quotes", side_effect=RuntimeError("boom")):
            api._worker(["/tmp/a.jpg", "/tmp/b.jpg"])

        js_calls = "\n".join(api.window.calls)
        self.assertIn('setSummary("Failed: 0/2 processed | 0 total words")', js_calls)
        self.assertNotIn('setSummary("Done: 0/2 processed | 0 total words")', js_calls)

    def test_paste_worker_does_not_show_abort_button(self):
        module = load_converter_app()
        module.VAULT_DIR = None

        class FakeWindow:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def evaluate_js(self, code):
                self.calls.append(code)
                return None

        api = module.Api()
        api.window = FakeWindow()
        api._paste_worker("hello world")

        js_calls = "\n".join(api.window.calls)
        self.assertNotIn("showAbortButton()", js_calls)


if __name__ == "__main__":
    unittest.main()
