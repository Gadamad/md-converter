import sys
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from quote_parser import QuoteRecord
from quote_markdown import render_quote_batch_markdown


class QuoteMarkdownTests(unittest.TestCase):
    def test_render_quote_batch_markdown_includes_source_author_and_raw_ocr(self):
        records = [
            QuoteRecord(
                quote="You have power over your mind.",
                author="Marcus Aurelius",
                source_image="stoic-001.jpg",
                raw_ocr="You have power over your mind.\n— Marcus Aurelius",
            ),
            QuoteRecord(
                quote="Be one.",
                author="",
                source_image="stoic-002.jpg",
                raw_ocr="Be one.",
            ),
        ]

        markdown = render_quote_batch_markdown(records, raw_ocr_mode="always")

        self.assertIn("# Extracted Quotes", markdown)
        self.assertIn("**Source image:** stoic-001.jpg", markdown)
        self.assertIn("**Author:** Marcus Aurelius", markdown)
        self.assertIn("> You have power over your mind.", markdown)
        self.assertIn("**Raw OCR:**", markdown)
        self.assertIn("**Source image:** stoic-002.jpg", markdown)
        self.assertIn("**Author:**", markdown)

    def test_render_quote_batch_markdown_keeps_multiline_quotes_inside_blockquote(self):
        records = [
            QuoteRecord(
                quote="Line one.\nLine two.",
                author="",
                source_image="stoic-003.jpg",
                raw_ocr="Line one.\nLine two.",
            )
        ]

        markdown = render_quote_batch_markdown(records)

        self.assertIn("> Line one.\n> Line two.", markdown)

    def test_always_mode_shows_raw_ocr(self):
        records = [
            QuoteRecord(
                quote="You have power over your mind.",
                author="Marcus Aurelius",
                source_image="stoic-001.jpg",
                raw_ocr="You have power over your mind.\n— Marcus Aurelius",
            ),
        ]
        markdown = render_quote_batch_markdown(records, raw_ocr_mode="always")
        self.assertIn("**Raw OCR:**", markdown)
        self.assertIn("You have power over your mind.\n— Marcus Aurelius", markdown)

    def test_never_mode_hides_raw_ocr(self):
        records = [
            QuoteRecord(
                quote="You have power over your mind.",
                author="Marcus Aurelius",
                source_image="stoic-001.jpg",
                raw_ocr="You have power over your mind.\n— Marcus Aurelius",
            ),
        ]
        markdown = render_quote_batch_markdown(records, raw_ocr_mode="never")
        self.assertNotIn("**Raw OCR:**", markdown)

    def test_never_mode_hides_raw_ocr_even_when_different(self):
        records = [
            QuoteRecord(
                quote="Be one.",
                author="",
                source_image="stoic-002.jpg",
                raw_ocr="Be one.\n[noise artifacts]",
            ),
        ]
        markdown = render_quote_batch_markdown(records, raw_ocr_mode="never")
        self.assertNotIn("**Raw OCR:**", markdown)
        self.assertNotIn("noise artifacts", markdown)

    def test_different_mode_hides_when_raw_matches_quote_and_author(self):
        records = [
            QuoteRecord(
                quote="You have power over your mind.",
                author="Marcus Aurelius",
                source_image="stoic-001.jpg",
                raw_ocr="You have power over your mind.\n— Marcus Aurelius",
            ),
        ]
        markdown = render_quote_batch_markdown(records, raw_ocr_mode="different")
        self.assertNotIn("**Raw OCR:**", markdown)

    def test_different_mode_hides_when_only_author_dash_style_differs(self):
        records = [
            QuoteRecord(
                quote="You have power over your mind.",
                author="Marcus Aurelius",
                source_image="stoic-001.jpg",
                raw_ocr="You have power over your mind.\n- Marcus Aurelius",
            ),
        ]
        markdown = render_quote_batch_markdown(records, raw_ocr_mode="different")
        self.assertNotIn("**Raw OCR:**", markdown)

    def test_different_mode_hides_when_raw_matches_quote_no_author(self):
        records = [
            QuoteRecord(
                quote="Be one.",
                author="",
                source_image="stoic-002.jpg",
                raw_ocr="Be one.",
            ),
        ]
        markdown = render_quote_batch_markdown(records, raw_ocr_mode="different")
        self.assertNotIn("**Raw OCR:**", markdown)

    def test_different_mode_shows_when_raw_has_extra_info(self):
        records = [
            QuoteRecord(
                quote="Be one.",
                author="",
                source_image="stoic-002.jpg",
                raw_ocr="Be one.\n[some OCR noise]",
            ),
        ]
        markdown = render_quote_batch_markdown(records, raw_ocr_mode="different")
        self.assertIn("**Raw OCR:**", markdown)
        self.assertIn("[some OCR noise]", markdown)

    def test_different_mode_shows_when_raw_differs_from_parsed_quote(self):
        records = [
            QuoteRecord(
                quote="Happiness depends upon ourselves.",
                author="Aristotle",
                source_image="phil-001.jpg",
                raw_ocr="Happiness depends upon ourselves\n-- Aristotle\n(extra line)",
            ),
        ]
        markdown = render_quote_batch_markdown(records, raw_ocr_mode="different")
        self.assertIn("**Raw OCR:**", markdown)

    def test_different_mode_handles_multiline_raw_with_trailing_whitespace(self):
        records = [
            QuoteRecord(
                quote="Line one.\nLine two.",
                author="",
                source_image="img.jpg",
                raw_ocr="  Line one.  \n  Line two.  ",
            ),
        ]
        markdown = render_quote_batch_markdown(records, raw_ocr_mode="different")
        self.assertNotIn("**Raw OCR:**", markdown)

    def test_default_mode_hides_identical_raw_ocr(self):
        records = [
            QuoteRecord(
                quote="Be one.",
                author="",
                source_image="stoic-002.jpg",
                raw_ocr="Be one.",
            ),
        ]
        markdown = render_quote_batch_markdown(records)
        self.assertNotIn("**Raw OCR:**", markdown)

    def test_different_mode_batch_mixed(self):
        records = [
            QuoteRecord(
                quote="You have power over your mind.",
                author="Marcus Aurelius",
                source_image="stoic-001.jpg",
                raw_ocr="You have power over your mind.\n— Marcus Aurelius",
            ),
            QuoteRecord(
                quote="Be one.",
                author="",
                source_image="stoic-002.jpg",
                raw_ocr="Be one.\n[noise]",
            ),
        ]
        markdown = render_quote_batch_markdown(records, raw_ocr_mode="different")
        count = markdown.count("**Raw OCR:**")
        self.assertEqual(count, 1)
        self.assertIn("[noise]", markdown)


if __name__ == "__main__":
    unittest.main()
