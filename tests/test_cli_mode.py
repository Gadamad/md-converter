import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
from collections import namedtuple
from dataclasses import dataclass
from pathlib import Path
from unittest import mock


PROJECT_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_DIR / "src" / "converter_app.py"


def load_converter_app(config_text=None, frozen=False, home_path: Path | None = None):
    webview_stub = types.ModuleType("webview")
    webview_stub.OPEN_DIALOG = "OPEN_DIALOG"
    webview_stub.FOLDER_DIALOG = "FOLDER_DIALOG"
    converters_stub = types.ModuleType("converters")
    native_drop_stub = types.ModuleType("native_drop")
    preferences_stub = types.ModuleType("preferences")

    @dataclass(frozen=True)
    class Preferences:
        theme: str = "system"
        raw_ocr_mode: str = "different"
        output_dir: Path | None = None
        auto_open_output: bool = False

        def to_dict(self) -> dict[str, object]:
            return {
                "theme": self.theme,
                "raw_ocr_mode": self.raw_ocr_mode,
                "output_dir": str(self.output_dir) if self.output_dir is not None else None,
                "auto_open_output": self.auto_open_output,
            }

        def save(self, path: Path) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self.to_dict()), encoding="utf-8")

        @classmethod
        def from_dict(cls, data: dict[str, object]):
            output_dir = data.get("output_dir")
            return cls(
                theme=str(data.get("theme", "system")),
                raw_ocr_mode=str(data.get("raw_ocr_mode", "different")),
                output_dir=Path(output_dir) if output_dir else None,
                auto_open_output=bool(data.get("auto_open_output", False)),
            )

        @classmethod
        def load(cls, path: Path):
            if not path.exists():
                return cls()
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls.from_dict(data)

    preferences_stub.Preferences = Preferences
    preferences_path = Path(tempfile.mkdtemp()) / "preferences.json"
    preferences_stub.default_preferences_path = lambda: preferences_path

    convert_result = namedtuple("ConvertResult", "success output_path word_count message")
    converters_stub.SUPPORTED = {".txt", ".png", ".jpg", ".jpeg", ".webp"}
    converters_stub.ConvertResult = convert_result
    converters_stub.route = lambda path, output_dir, vault_dir=None: convert_result(
        True,
        str(output_dir / "example.md"),
        2,
        "OK -> example.md",
    )
    converters_stub.convert_pasted = lambda text, output_dir, vault_dir=None: convert_result(
        True,
        str(output_dir / "pasted.md"),
        len(text.split()),
        "OK -> pasted.md",
    )
    converters_stub.convert_image_folder_quotes = lambda paths, output_dir, vault_dir=None, hooks=None: convert_result(
        True,
        str(output_dir / "extracted_quotes.md"),
        10,
        "OK -> extracted_quotes.md",
    )
    native_drop_stub.setup_native_drop = lambda window, callback: None

    original_modules = {
        name: sys.modules.get(name)
        for name in ("webview", "converters", "native_drop", "preferences")
    }
    sys.modules["webview"] = webview_stub
    sys.modules["converters"] = converters_stub
    sys.modules["native_drop"] = native_drop_stub
    sys.modules["preferences"] = preferences_stub

    spec = importlib.util.spec_from_file_location("test_converter_app", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None

    config_path = PROJECT_DIR / "config.json"
    real_exists = Path.exists
    real_read_text = Path.read_text
    real_home = Path.home

    def fake_exists(path_obj):
        if config_text is not None and path_obj == config_path:
            return True
        return real_exists(path_obj)

    def fake_read_text(path_obj, *args, **kwargs):
        if config_text is not None and path_obj == config_path:
            return config_text
        return real_read_text(path_obj, *args, **kwargs)

    def fake_home(cls):
        if home_path is not None:
            return home_path
        return real_home()

    with mock.patch("pathlib.Path.exists", fake_exists), mock.patch("pathlib.Path.read_text", fake_read_text), mock.patch("pathlib.Path.home", classmethod(fake_home)), mock.patch.object(sys, "frozen", frozen, create=True):
        spec.loader.exec_module(module)

    for name, original in original_modules.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original

    return module


class CliModeTests(unittest.TestCase):
    def test_cli_mode_reports_vault_disabled_when_not_configured(self):
        module = load_converter_app()
        module.VAULT_DIR = None

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            module.cli_mode(["/tmp/example.txt"])

        text = output.getvalue()
        self.assertIn("SUMMARY: 1/1 converted | 2 total words", text)
        self.assertIn("Vault:  disabled (no config.json)", text)

    def test_cli_mode_displays_url_inputs_without_path_mangling(self):
        module = load_converter_app()
        module.VAULT_DIR = None

        output = io.StringIO()
        url = "https://example.com/article"
        with contextlib.redirect_stdout(output):
            module.cli_mode([url])

        self.assertIn(url, output.getvalue())

    def test_invalid_config_falls_back_to_disabled_vault(self):
        module = load_converter_app(config_text="{invalid json}")
        self.assertIsNone(module.VAULT_DIR)

    def test_frozen_app_uses_persistent_documents_output_dir(self):
        fake_home = Path("/Users/tester")
        module = load_converter_app(frozen=True, home_path=fake_home)

        self.assertEqual(
            module.OUTPUT_DIR,
            fake_home / "Documents" / "MD Converter" / "converted",
        )

    def test_source_mode_keeps_repo_local_output_dir(self):
        fake_home = Path("/Users/tester")
        module = load_converter_app(frozen=False, home_path=fake_home)

        self.assertEqual(module.OUTPUT_DIR, PROJECT_DIR / "converted")

    def test_get_preferences_returns_defaults(self):
        module = load_converter_app()
        api = module.Api()

        prefs = api.get_preferences()

        self.assertEqual(prefs["theme"], "system")
        self.assertEqual(prefs["raw_ocr_mode"], "different")
        self.assertFalse(prefs["auto_open_output"])

    def test_save_preferences_updates_current_preferences(self):
        module = load_converter_app()
        api = module.Api()

        api.save_preferences(
            {
                "theme": "light",
                "raw_ocr_mode": "never",
                "output_dir": "/tmp/custom-output",
                "auto_open_output": True,
            }
        )

        prefs = api.get_preferences()
        self.assertEqual(prefs["theme"], "light")
        self.assertEqual(prefs["raw_ocr_mode"], "never")
        self.assertEqual(prefs["output_dir"], "/tmp/custom-output")
        self.assertTrue(prefs["auto_open_output"])

    def test_open_output_uses_preference_output_directory(self):
        module = load_converter_app()
        api = module.Api()
        api.save_preferences({"output_dir": "/tmp/custom-output"})

        with mock.patch.object(module.subprocess, "run") as run_mock:
            api.open_output()

        run_mock.assert_called_once_with(["open", "/tmp/custom-output"])


class FolderDiscoveryTests(unittest.TestCase):
    def test_discover_quote_images_returns_supported_images_recursively(self):
        module = load_converter_app()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested = root / "nested"
            nested.mkdir()
            (root / "cover.jpg").write_bytes(b"img")
            (nested / "page.png").write_bytes(b"img")
            (root / "notes.txt").write_text("ignore", encoding="utf-8")

            images = module.discover_quote_images(root)

        self.assertEqual(
            images,
            [
                str(root / "cover.jpg"),
                str(nested / "page.png"),
            ],
        )

    def test_browse_folder_stages_supported_images_from_selected_directory(self):
        module = load_converter_app()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "cover.jpg").write_bytes(b"img")

            api = module.Api()
            api.stage_quote_folder(root)

        self.assertEqual(len(api._staged_folders), 1)
        self.assertEqual(api._staged_folders[0].path, root)
        self.assertEqual(api._staged_folders[0].image_count, 1)

    def test_stage_quote_folder_replaces_previous_folder_by_default(self):
        module = load_converter_app()

        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "first"
            second = Path(temp_dir) / "second"
            first.mkdir()
            second.mkdir()
            (first / "one.jpg").write_bytes(b"img")
            (second / "two.jpg").write_bytes(b"img")

            api = module.Api()
            api.stage_quote_folder(first)
            api.stage_quote_folder(second)

        self.assertEqual(len(api._staged_folders), 1)
        self.assertEqual(api._staged_folders[0].path, second)

    def test_stage_quote_folder_append_mode_keeps_existing_folder(self):
        module = load_converter_app()

        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "first"
            second = Path(temp_dir) / "second"
            first.mkdir()
            second.mkdir()
            (first / "one.jpg").write_bytes(b"img")
            (second / "two.jpg").write_bytes(b"img")

            api = module.Api()
            api.stage_quote_folder(first)
            api.stage_quote_folder(second, replace=False)

        self.assertEqual([folder.path for folder in api._staged_folders], [first, second])

    def test_stage_quote_folder_keeps_previous_queue_when_new_folder_has_no_images(self):
        module = load_converter_app()

        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "first"
            empty = Path(temp_dir) / "empty"
            first.mkdir()
            empty.mkdir()
            (first / "one.jpg").write_bytes(b"img")

            api = module.Api()
            api.stage_quote_folder(first)
            api.stage_quote_folder(empty)

        self.assertEqual(len(api._staged_folders), 1)
        self.assertEqual(api._staged_folders[0].path, first)

    def test_remove_staged_folder_removes_only_target_folder(self):
        module = load_converter_app()

        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "first"
            second = Path(temp_dir) / "second"
            first.mkdir()
            second.mkdir()
            (first / "one.jpg").write_bytes(b"img")
            (second / "two.jpg").write_bytes(b"img")

            api = module.Api()
            api.stage_quote_folder(first)
            api.stage_quote_folder(second, replace=False)
            remove_id = api._staged_folders[0].id
            api.remove_staged_folder(remove_id)

        self.assertEqual(len(api._staged_folders), 1)
        self.assertEqual(api._staged_folders[0].path, second)

    def test_clear_staged_folders_empties_folder_queue(self):
        module = load_converter_app()

        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "first"
            first.mkdir()
            (first / "one.jpg").write_bytes(b"img")

            api = module.Api()
            api.stage_quote_folder(first)
            api.clear_staged_folders()

        self.assertEqual(api._staged_folders, [])

    def test_quote_folder_worker_uses_merged_folder_converter(self):
        module = load_converter_app()
        module.VAULT_DIR = None
        api = module.Api()

        with mock.patch.object(module, "convert_image_folder_quotes", return_value=module.ConvertResult(True, "out/extracted_quotes.md", 12, "OK -> extracted_quotes.md")) as convert_mock:
            api._quote_folder_worker(["/tmp/a.jpg", "/tmp/b.png"])

        convert_mock.assert_called_once()
        args, kwargs = convert_mock.call_args
        self.assertEqual(args[:3], (["/tmp/a.jpg", "/tmp/b.png"], module.OUTPUT_DIR / "quotes", None))
        self.assertIn("hooks", kwargs)

    def test_worker_batches_image_paths_into_one_quote_export(self):
        module = load_converter_app()
        module.VAULT_DIR = None
        api = module.Api()

        with mock.patch.object(module, "convert_image_folder_quotes", return_value=module.ConvertResult(True, "out/extracted_quotes.md", 12, "OK -> extracted_quotes.md")) as convert_mock, \
             mock.patch.object(module, "route") as route_mock:
            api._worker(["/tmp/a.jpg", "/tmp/b.png"])

        convert_mock.assert_called_once()
        args, kwargs = convert_mock.call_args
        self.assertEqual(args[:3], (["/tmp/a.jpg", "/tmp/b.png"], module.OUTPUT_DIR / "quotes", None))
        self.assertIn("hooks", kwargs)
        route_mock.assert_not_called()

    def test_worker_splits_mixed_batches_between_quote_images_and_other_files(self):
        module = load_converter_app()
        module.VAULT_DIR = None
        api = module.Api()

        with mock.patch.object(module, "convert_image_folder_quotes", return_value=module.ConvertResult(True, "out/extracted_quotes.md", 12, "OK -> extracted_quotes.md")) as convert_mock, \
             mock.patch.object(module, "route", return_value=module.ConvertResult(True, "out/example.md", 5, "OK -> example.md")) as route_mock:
            api._worker(["/tmp/a.jpg", "/tmp/example.txt"])

        convert_mock.assert_called_once()
        args, kwargs = convert_mock.call_args
        self.assertEqual(args[:3], (["/tmp/a.jpg"], module.OUTPUT_DIR / "quotes", None))
        self.assertIn("hooks", kwargs)
        route_mock.assert_called_once_with("/tmp/example.txt", module.OUTPUT_DIR, None)

    def test_convert_staged_does_not_start_second_job_while_running(self):
        module = load_converter_app()
        api = module.Api()
        api._job_running = True
        api._staged = ["/tmp/example.txt"]

        with mock.patch.object(module.threading, "Thread") as thread_mock:
            api.convert_staged()

        thread_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
