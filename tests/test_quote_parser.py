import sys
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from quote_parser import extract_quote_records


class QuoteParserTests(unittest.TestCase):
    def test_extract_quote_records_splits_trailing_dash_author(self):
        records = extract_quote_records(
            "You have power over your mind — not outside events.\n— Marcus Aurelius",
            source_image="stoic-001.jpg",
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].quote, "You have power over your mind — not outside events.")
        self.assertEqual(records[0].author, "Marcus Aurelius")
        self.assertEqual(records[0].source_image, "stoic-001.jpg")

    def test_extract_quote_records_leaves_author_blank_when_missing(self):
        records = extract_quote_records(
            "Waste no more time arguing what a good man should be. Be one.",
            source_image="stoic-002.jpg",
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].author, "")
        self.assertEqual(records[0].quote, "Waste no more time arguing what a good man should be. Be one.")

    def test_extract_quote_records_splits_multiple_blocks_from_one_image(self):
        records = extract_quote_records(
            (
                "First quote line.\n— Seneca\n\n"
                "Second quote line.\n- Epictetus"
            ),
            source_image="stoic-003.jpg",
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].author, "Seneca")
        self.assertEqual(records[1].author, "Epictetus")

    def test_extract_quote_records_does_not_turn_title_case_endings_into_authors(self):
        records = extract_quote_records(
            "Do it now.\nChoose Courage",
            source_image="stoic-004.jpg",
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].author, "")
        self.assertEqual(records[0].quote, "Do it now.\nChoose Courage")

    def test_extract_quote_records_skips_author_only_blocks(self):
        records = extract_quote_records(
            "— Seneca",
            source_image="stoic-005.jpg",
        )

        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
