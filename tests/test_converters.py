import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

import converters


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200, headers: dict | None = None) -> None:
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")
        return None


class ConvertHtmlTests(unittest.TestCase):
    def test_distinct_urls_with_same_page_title_get_distinct_markdown_files(self):
        html = """
        <html>
          <head><title>Welcome to Copenhagen Compliance</title></head>
          <body><main><p>First article body with enough words.</p></main></body>
        </html>
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            first_url = "https://www.copenhagencompliance.com/news/News-3.php"
            second_url = "https://www.copenhagencompliance.com/news/News-10.php"

            with mock.patch("converters.requests.get", return_value=FakeResponse(html)):
                first = converters.convert_html(first_url, output_dir)
                second = converters.convert_html(second_url, output_dir)

        self.assertTrue(first.success)
        self.assertTrue(second.success)
        self.assertNotEqual(Path(first.output_path).name, Path(second.output_path).name)

    def test_url_conversion_uses_browser_headers_for_sites_that_block_generic_clients(self):
        html = """
        <html>
          <head><title>Terminals Beat Vectors</title></head>
          <body><main><p>Article body with enough words to convert cleanly.</p></main></body>
        </html>
        """

        def fake_get(_url, timeout, headers, verify):
            self.assertEqual(timeout, 30)
            self.assertTrue(verify)
            user_agent = headers["User-Agent"]
            if user_agent == "MDConverter/1.0":
                return FakeResponse("blocked", status_code=429)
            if user_agent.startswith("Mozilla/5.0"):
                return FakeResponse(html)
            self.fail(f"Unexpected User-Agent: {user_agent}")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            url = "https://venturebeat.com/orchestration/example"

            with mock.patch("converters.requests.get", side_effect=fake_get):
                try:
                    result = converters.convert_html(url, output_dir)
                except RuntimeError as exc:
                    self.fail(f"convert_html should avoid generic blocked headers: {exc}")

        self.assertTrue(result.success)
        self.assertIn("terminals-beat-vectors", Path(result.output_path).name)

    def test_url_conversion_retries_429_with_retry_after_before_succeeding(self):
        html = """
        <html>
          <head><title>Retry After Win</title></head>
          <body><main><p>Recovered article body after a short throttle.</p></main></body>
        </html>
        """
        responses = iter([
            FakeResponse("busy", status_code=429, headers={"Retry-After": "2"}),
            FakeResponse(html),
        ])

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            url = "https://example.com/retry-after"

            with mock.patch("converters.requests.get", side_effect=lambda *args, **kwargs: next(responses)), \
                 mock.patch("converters.time.sleep") as sleep_mock:
                result = converters.convert_html(url, output_dir)

        self.assertTrue(result.success)
        sleep_mock.assert_called_once_with(2.0)

    def test_url_conversion_retries_connection_error_before_succeeding(self):
        html = """
        <html>
          <head><title>Recovered Connection</title></head>
          <body><main><p>Recovered after a transient network issue.</p></main></body>
        </html>
        """
        responses = iter([
            converters.requests.ConnectionError("temporary network issue"),
            FakeResponse(html),
        ])

        def fake_get(*args, **kwargs):
            response = next(responses)
            if isinstance(response, Exception):
                raise response
            return response

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            url = "https://example.com/retry-connection"

            with mock.patch("converters.requests.get", side_effect=fake_get), \
                 mock.patch("converters.time.sleep") as sleep_mock:
                result = converters.convert_html(url, output_dir)

        self.assertTrue(result.success)
        self.assertEqual(sleep_mock.call_count, 1)

    def test_url_conversion_does_not_retry_non_retryable_http_errors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            url = "https://example.com/not-found"

            with mock.patch("converters.requests.get", return_value=FakeResponse("missing", status_code=404)) as get_mock, \
                 mock.patch("converters.time.sleep") as sleep_mock:
                with self.assertRaises(RuntimeError):
                    converters.convert_html(url, output_dir)

        self.assertEqual(get_mock.call_count, 1)
        sleep_mock.assert_not_called()


class ConvertSpreadsheetTests(unittest.TestCase):
    def test_route_converts_xlsx_each_sheet_to_separate_markdown_file(self):
        from openpyxl import Workbook

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            workbook_path = temp_path / "Workbook.xlsx"
            output_dir = temp_path / "out"

            workbook = Workbook()
            summary = workbook.active
            summary.title = "Summary"
            summary.append(["Name", "Amount"])
            summary.append(["Alpha", 10])

            data_sheet = workbook.create_sheet("Data Sheet")
            data_sheet.append(["Item", "Status"])
            data_sheet.append(["Beta", "Ready"])

            workbook.save(workbook_path)

            result = converters.route(str(workbook_path), output_dir)

            spreadsheet_dir = output_dir / "spreadsheets"
            summary_md = spreadsheet_dir / "workbook-summary.md"
            data_md = spreadsheet_dir / "workbook-data-sheet.md"

            self.assertTrue(result.success)
            self.assertEqual(Path(result.output_path), spreadsheet_dir)
            self.assertIn("2 sheets", result.message)
            self.assertTrue(summary_md.exists())
            self.assertTrue(data_md.exists())

            summary_text = summary_md.read_text(encoding="utf-8")
            data_text = data_md.read_text(encoding="utf-8")
            self.assertIn("| Name | Amount |", summary_text)
            self.assertIn("| Alpha | 10 |", summary_text)
            self.assertNotIn("Beta", summary_text)
            self.assertIn("| Item | Status |", data_text)
            self.assertIn("| Beta | Ready |", data_text)
            self.assertNotIn("Alpha", data_text)


class ImageRoutingTests(unittest.TestCase):
    def test_route_sends_png_files_to_image_quote_converter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            image_path = temp_path / "quote-card.png"
            image_path.write_bytes(b"not-a-real-png")
            output_dir = temp_path / "out"
            expected = converters.ConvertResult(
                True,
                str(output_dir / "quotes" / "extracted_quotes.md"),
                42,
                "OK -> extracted_quotes.md",
            )

            with mock.patch("converters.convert_image_quotes", return_value=expected) as image_mock:
                result = converters.route(str(image_path), output_dir)

        self.assertEqual(result, expected)
        image_mock.assert_called_once_with(str(image_path), output_dir / "quotes", None)

    def test_convert_image_folder_quotes_writes_one_merged_markdown_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            first_image = temp_path / "a-quote.png"
            second_image = temp_path / "b-quote.png"
            first_image.write_bytes(b"img")
            second_image.write_bytes(b"img")
            output_dir = temp_path / "out"

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
                result = converters.convert_image_folder_quotes(
                    [str(first_image), str(second_image)],
                    output_dir,
                )

            self.assertTrue(result.success)
            markdown = Path(result.output_path).read_text(encoding="utf-8")
            self.assertIn("**Source image:** a-quote.png", markdown)
            self.assertIn("**Author:** Seneca", markdown)
            self.assertIn("**Source image:** b-quote.png", markdown)
            self.assertIn("Second quote.", markdown)

    def test_convert_image_folder_quotes_uses_folder_slug_and_timestamp_filename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / "Stoicism App"
            temp_path.mkdir()
            image_path = temp_path / "quote.png"
            image_path.write_bytes(b"img")
            output_dir = temp_path / "out"

            record = mock.Mock(
                quote="First quote.",
                author="Seneca",
                source_image=image_path.name,
                raw_ocr="First quote.\n— Seneca",
            )

            fake_now = mock.Mock()
            fake_now.strftime.return_value = "20260626_154233"

            with mock.patch("converters.ocr_image", return_value=mock.Mock(text="ocr one")), \
                 mock.patch("converters.extract_quote_records", return_value=[record]), \
                 mock.patch("converters.datetime") as datetime_mock:
                datetime_mock.now.return_value = fake_now
                result = converters.convert_image_folder_quotes(
                    [str(image_path)],
                    output_dir,
                )

            self.assertTrue(result.success)
            self.assertEqual(
                Path(result.output_path).name,
                "stoicism-app_quotes_1-images_20260626_154233.md",
            )

    def test_convert_image_folder_quotes_includes_image_count_for_multi_image_batch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / "Stoicism App"
            temp_path.mkdir()
            first_image = temp_path / "quote-a.png"
            second_image = temp_path / "quote-b.png"
            first_image.write_bytes(b"img")
            second_image.write_bytes(b"img")
            output_dir = temp_path / "out"

            record = mock.Mock(
                quote="First quote.",
                author="Seneca",
                source_image=first_image.name,
                raw_ocr="First quote.\n— Seneca",
            )

            fake_now = mock.Mock()
            fake_now.strftime.return_value = "20260626_154233"

            with mock.patch("converters.ocr_image", return_value=mock.Mock(text="ocr one")), \
                 mock.patch("converters.extract_quote_records", return_value=[record]), \
                 mock.patch("converters.datetime") as datetime_mock:
                datetime_mock.now.return_value = fake_now
                result = converters.convert_image_folder_quotes(
                    [str(first_image), str(second_image)],
                    output_dir,
                )

            self.assertEqual(
                Path(result.output_path).name,
                "stoicism-app_quotes_2-images_20260626_154233.md",
            )

    def test_convert_image_folder_quotes_avoids_same_second_filename_collision(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / "Stoicism App"
            temp_path.mkdir()
            image_path = temp_path / "quote.png"
            image_path.write_bytes(b"img")
            output_dir = temp_path / "out"

            record = mock.Mock(
                quote="First quote.",
                author="Seneca",
                source_image=image_path.name,
                raw_ocr="First quote.\n— Seneca",
            )

            fake_now = mock.Mock()
            fake_now.strftime.return_value = "20260626_154233"

            with mock.patch("converters.ocr_image", return_value=mock.Mock(text="ocr one")), \
                 mock.patch("converters.extract_quote_records", return_value=[record]), \
                 mock.patch("converters.datetime") as datetime_mock:
                datetime_mock.now.return_value = fake_now
                first = converters.convert_image_folder_quotes([str(image_path)], output_dir)
                second = converters.convert_image_folder_quotes([str(image_path)], output_dir)

            self.assertNotEqual(first.output_path, second.output_path)
            self.assertTrue(Path(first.output_path).exists())
            self.assertTrue(Path(second.output_path).exists())
            self.assertEqual(Path(second.output_path).name, "stoicism-app_quotes_1-images_20260626_154233_2.md")


if __name__ == "__main__":
    unittest.main()
