import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from image_ocr import OcrBackendUnavailable, OcrResult, ocr_image


class ImageOcrTests(unittest.TestCase):
    def test_ocr_image_prefers_vision_when_available(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "quote.png"
            image_path.write_bytes(b"fake")

            with mock.patch("image_ocr._ocr_with_vision", return_value=OcrResult(text="vision text", engine="vision")) as vision_mock, \
                 mock.patch("image_ocr._ocr_with_tesseract") as tesseract_mock:
                result = ocr_image(image_path)

        self.assertEqual(result.text, "vision text")
        self.assertEqual(result.engine, "vision")
        vision_mock.assert_called_once_with(image_path)
        tesseract_mock.assert_not_called()

    def test_ocr_image_falls_back_to_tesseract_when_vision_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "quote.png"
            image_path.write_bytes(b"fake")

            with mock.patch("image_ocr._ocr_with_vision", side_effect=OcrBackendUnavailable("vision missing")), \
                 mock.patch("image_ocr._ocr_with_tesseract", return_value=OcrResult(text="tesseract text", engine="tesseract")) as tesseract_mock:
                result = ocr_image(image_path)

        self.assertEqual(result.text, "tesseract text")
        self.assertEqual(result.engine, "tesseract")
        tesseract_mock.assert_called_once_with(image_path)

    def test_ocr_image_raises_clear_error_when_no_local_backend_is_available(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "quote.png"
            image_path.write_bytes(b"fake")

            with mock.patch("image_ocr._ocr_with_vision", side_effect=OcrBackendUnavailable("vision missing")), \
                 mock.patch("image_ocr._ocr_with_tesseract", side_effect=OcrBackendUnavailable("tesseract missing")):
                with self.assertRaises(OcrBackendUnavailable) as ctx:
                    ocr_image(image_path)

        self.assertIn("No local OCR backend available", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
