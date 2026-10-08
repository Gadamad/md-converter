import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import converters
import fitz
from PIL import Image


class PdfRecoveryTests(unittest.TestCase):
    def make_mixed_pdf(self, path):
        image=Image.new('RGB', (200,200), 'white')
        buffer=io.BytesIO()
        image.save(buffer, format='PNG')
        with fitz.open() as doc:
            page=doc.new_page()
            page.insert_text((72,72), 'Selectable cover text')
            page=doc.new_page()
            page.insert_image(fitz.Rect(0,0,200,200), stream=buffer.getvalue())
            doc.save(path)

    def test_mixed_pdf_ocr_includes_scanned_page(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'mixed.pdf'
            self.make_mixed_pdf(source)
            with mock.patch.object(converters, '_ocr_pdf_page', return_value='Scanned page contents.', create=True) as ocr:
                result=converters.convert_pdf(str(source), Path(directory)/'out')
            self.assertEqual(ocr.call_count, 1)
            content=Path(result.output_path).read_text()
            self.assertIn('Selectable cover text', content)
            self.assertIn('Scanned page contents.', content)

    def test_page_ocr_failure_preserves_text_and_is_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'mixed.pdf'
            self.make_mixed_pdf(source)
            with mock.patch.object(converters, '_ocr_pdf_page', side_effect=RuntimeError('OCR deadline'), create=True):
                result=converters.convert_pdf(str(source), Path(directory)/'out')
            self.assertFalse(result.success)
            content=Path(result.output_path).read_text()
            self.assertIn('Selectable cover text', content)
            self.assertIn('Page 2', content)
            self.assertIn('OCR deadline', content)

    def test_cancel_during_pdf_ocr_preserves_preceding_text(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'mixed.pdf'
            self.make_mixed_pdf(source)
            with mock.patch.object(converters, '_ocr_pdf_page', side_effect=converters.OcrCancelled('canceled')):
                result=converters.convert_pdf(str(source), Path(directory)/'out', should_cancel=lambda: False)
            self.assertFalse(result.success)
            self.assertIn('CANCELED', result.message)
            self.assertIn('Selectable cover text', Path(result.output_path).read_text())


if __name__ == '__main__':
    unittest.main()
