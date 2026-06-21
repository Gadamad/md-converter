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


if __name__ == "__main__":
    unittest.main()
