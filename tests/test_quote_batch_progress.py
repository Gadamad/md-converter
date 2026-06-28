import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

import converters


class QuoteBatchProgressTests(unittest.TestCase):
    def test_convert_image_folder_quotes_reports_progress_per_image(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            first_image = temp_path / "a-quote.png"
            second_image = temp_path / "b-quote.png"
            first_image.write_bytes(b"img")
            second_image.write_bytes(b"img")
            output_dir = temp_path / "out"
            events: list[tuple[int, int, str]] = []

            hooks = converters.QuoteBatchHooks(
                on_image_processed=lambda done, total, current_image: events.append((done, total, current_image)),
            )

            record_one = mock.Mock(
                quote="First quote.",
                author="Seneca",
                source_image=first_image.name,
                raw_ocr="First quote.\n— Seneca",
            )
            record_two = mock.Mock(
                quote="Second quote.",
                author="",
                source_image=second_image.name,
                raw_ocr="Second quote.",
            )

            with mock.patch("converters.ocr_image", side_effect=[mock.Mock(text="ocr one"), mock.Mock(text="ocr two")]), \
                 mock.patch("converters.extract_quote_records", side_effect=[[record_one], [record_two]]):
                converters.convert_image_folder_quotes(
                    [str(first_image), str(second_image)],
                    output_dir,
                    hooks=hooks,
                )

        self.assertEqual(events, [(1, 2, "a-quote.png"), (2, 2, "b-quote.png")])

    def test_convert_image_folder_quotes_writes_partial_output_when_canceled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            first_image = temp_path / "a-quote.png"
            second_image = temp_path / "b-quote.png"
            first_image.write_bytes(b"img")
            second_image.write_bytes(b"img")
            output_dir = temp_path / "out"
            should_cancel = False

            def on_image_processed(done: int, total: int, current_image: str) -> None:
                nonlocal should_cancel
                should_cancel = True

            hooks = converters.QuoteBatchHooks(
                on_image_processed=on_image_processed,
                should_cancel=lambda: should_cancel,
            )

            record_one = mock.Mock(
                quote="First quote.",
                author="Seneca",
                source_image=first_image.name,
                raw_ocr="First quote.\n— Seneca",
            )

            with mock.patch("converters.ocr_image", side_effect=[mock.Mock(text="ocr one"), mock.Mock(text="ocr two")]) as ocr_mock, \
                 mock.patch("converters.extract_quote_records", side_effect=[[record_one]]):
                result = converters.convert_image_folder_quotes(
                    [str(first_image), str(second_image)],
                    output_dir,
                    hooks=hooks,
                )

                self.assertFalse(result.success)
                self.assertIn("CANCELED", result.message)
                self.assertTrue(Path(result.output_path).exists())
                self.assertEqual(ocr_mock.call_count, 1)

    def test_convert_image_folder_quotes_reports_processed_count_when_canceling_without_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            first_image = temp_path / "a-quote.png"
            second_image = temp_path / "b-quote.png"
            first_image.write_bytes(b"img")
            second_image.write_bytes(b"img")
            output_dir = temp_path / "out"
            should_cancel = False

            def on_image_processed(done: int, total: int, current_image: str) -> None:
                nonlocal should_cancel
                should_cancel = True

            hooks = converters.QuoteBatchHooks(
                on_image_processed=on_image_processed,
                should_cancel=lambda: should_cancel,
            )

            with mock.patch("converters.ocr_image", side_effect=[mock.Mock(text="ocr one"), mock.Mock(text="ocr two")]), \
                 mock.patch("converters.extract_quote_records", return_value=[]):
                result = converters.convert_image_folder_quotes(
                    [str(first_image), str(second_image)],
                    output_dir,
                    hooks=hooks,
                )

        self.assertEqual(result.message, "CANCELED (1/2 images processed)")

if __name__ == "__main__":
    unittest.main()
