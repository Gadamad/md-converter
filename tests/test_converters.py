import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

import converters


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
