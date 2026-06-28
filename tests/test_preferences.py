import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from preferences import Preferences, default_preferences_path


class PreferencesDefaultsTests(unittest.TestCase):
    def test_default_theme_is_system(self):
        prefs = Preferences()
        self.assertEqual(prefs.theme, "system")

    def test_default_raw_ocr_mode_is_different(self):
        prefs = Preferences()
        self.assertEqual(prefs.raw_ocr_mode, "different")

    def test_default_output_dir_is_none(self):
        prefs = Preferences()
        self.assertIsNone(prefs.output_dir)

    def test_default_auto_open_output_is_false(self):
        prefs = Preferences()
        self.assertFalse(prefs.auto_open_output)


class PreferencesValidationTests(unittest.TestCase):
    def test_invalid_theme_raises_value_error(self):
        with self.assertRaises(ValueError):
            Preferences(theme="neon")

    def test_invalid_raw_ocr_mode_raises_value_error(self):
        with self.assertRaises(ValueError):
            Preferences(raw_ocr_mode="sometimes")


class PreferencesSerializationTests(unittest.TestCase):
    def test_to_dict_contains_expected_keys(self):
        prefs = Preferences()
        data = prefs.to_dict()
        self.assertEqual(
            set(data.keys()),
            {"theme", "raw_ocr_mode", "output_dir", "auto_open_output"},
        )

    def test_round_trip_preserves_values(self):
        original = Preferences(
            theme="light",
            raw_ocr_mode="never",
            output_dir=Path("/tmp/output"),
            auto_open_output=True,
        )
        restored = Preferences.from_dict(original.to_dict())
        self.assertEqual(restored, original)

    def test_from_dict_ignores_unknown_keys(self):
        prefs = Preferences.from_dict({"theme": "dark", "bogus": 99})
        self.assertEqual(prefs.theme, "dark")

    def test_from_dict_defaults_missing_keys(self):
        prefs = Preferences.from_dict({})
        self.assertEqual(prefs, Preferences())


class PreferencesStoreTests(unittest.TestCase):
    def test_save_then_load_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "prefs.json"
            original = Preferences(
                theme="dark",
                raw_ocr_mode="always",
                output_dir=Path(temp_dir) / "exports",
                auto_open_output=True,
            )
            original.save(path)
            loaded = Preferences.load(path)
        self.assertEqual(loaded, original)

    def test_load_missing_file_returns_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            prefs = Preferences.load(Path(temp_dir) / "missing.json")
        self.assertEqual(prefs, Preferences())

    def test_load_invalid_json_returns_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "prefs.json"
            path.write_text("{invalid json}", encoding="utf-8")
            prefs = Preferences.load(path)
        self.assertEqual(prefs, Preferences())

    def test_load_invalid_theme_preserves_other_valid_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "prefs.json"
            path.write_text(
                json.dumps(
                    {
                        "theme": "broken",
                        "raw_ocr_mode": "never",
                        "output_dir": "/tmp/export",
                        "auto_open_output": True,
                    }
                ),
                encoding="utf-8",
            )
            prefs = Preferences.load(path)

        self.assertEqual(prefs.theme, "system")
        self.assertEqual(prefs.raw_ocr_mode, "never")
        self.assertEqual(prefs.output_dir, Path("/tmp/export"))
        self.assertTrue(prefs.auto_open_output)

    def test_load_string_false_does_not_enable_auto_open_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "prefs.json"
            path.write_text(
                json.dumps({"auto_open_output": "false"}),
                encoding="utf-8",
            )
            prefs = Preferences.load(path)
        self.assertFalse(prefs.auto_open_output)

    def test_load_relative_output_dir_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "prefs.json"
            path.write_text(
                json.dumps({"output_dir": "relative/path"}),
                encoding="utf-8",
            )
            prefs = Preferences.load(path)
        self.assertIsNone(prefs.output_dir)


class PreferencesPathTests(unittest.TestCase):
    def test_frozen_preferences_path_uses_application_support(self):
        original_frozen = getattr(sys, "frozen", None)
        try:
            sys.frozen = True  # type: ignore[attr-defined]
            path = default_preferences_path()
        finally:
            if original_frozen is None:
                delattr(sys, "frozen")
            else:
                sys.frozen = original_frozen  # type: ignore[attr-defined]

        self.assertIn("Application Support", str(path))
        self.assertEqual(path.name, "preferences.json")

    def test_dev_preferences_path_is_project_local(self):
        original_frozen = getattr(sys, "frozen", None)
        try:
            if hasattr(sys, "frozen"):
                delattr(sys, "frozen")
            path = default_preferences_path()
        finally:
            if original_frozen is not None:
                sys.frozen = original_frozen  # type: ignore[attr-defined]

        self.assertEqual(path, PROJECT_DIR / "preferences.json")


if __name__ == "__main__":
    unittest.main()
