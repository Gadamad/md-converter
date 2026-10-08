import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import converters
from image_ocr import OcrBackendUnavailable, OcrResult


class BatchRecoveryTests(unittest.TestCase):
    def test_success_is_saved_before_next_image_and_survives_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'out'
            def read(path, **kwargs):
                if path.name == 'a.jpg':
                    return OcrResult('First quote.\n— Seneca', 'vision')
                saved = list(output.glob('*.md'))
                self.assertEqual(len(saved), 1, 'Completed image must be on disk before next OCR starts')
                self.assertIn('First quote.', saved[0].read_text())
                raise OcrBackendUnavailable('both engines failed')
            with mock.patch.object(converters, 'ocr_image', side_effect=read):
                result = converters.convert_image_folder_quotes(['a.jpg', 'b.jpg'], output)
            self.assertFalse(result.success)
            self.assertIn('First quote.', Path(result.output_path).read_text())
            report = json.loads(next(output.glob('*.progress.json')).read_text())
            self.assertEqual(report['processed'], 2)
            self.assertEqual(Path(report['failed'][0]['image']).name, 'b.jpg')
            self.assertEqual(report['status'], 'completed_with_errors')

    def test_bad_image_does_not_prevent_later_images(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(converters, 'ocr_image', side_effect=[
                OcrBackendUnavailable('broken image'), OcrResult('Second succeeds.', 'tesseract')
            ]) as read:
                result = converters.convert_image_folder_quotes(['a.jpg', 'b.jpg'], Path(directory))
            self.assertEqual(read.call_count, 2)
            self.assertFalse(result.success)
            self.assertIn('Second succeeds.', Path(result.output_path).read_text())

    def test_started_hook_fires_before_ocr_and_finished_hook_after(self):
        self.assertIn('on_image_started', converters.QuoteBatchHooks.__dataclass_fields__)
        events = []
        hooks = converters.QuoteBatchHooks(
            on_image_started=lambda n, total, name: events.append(('start', name)),
            on_image_processed=lambda n, total, name: events.append(('done', name)),
        )
        def read(path, **kwargs):
            events.append(('ocr', path.name))
            return OcrResult('A useful quote.', 'vision')
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(converters, 'ocr_image', side_effect=read):
                converters.convert_image_folder_quotes(['a.jpg'], Path(directory), hooks=hooks)
        self.assertEqual(events, [('start', 'a.jpg'), ('ocr', 'a.jpg'), ('done', 'a.jpg')])

    def test_cancellation_during_ocr_preserves_previous_output(self):
        import image_ocr
        self.assertTrue(hasattr(image_ocr, 'OcrCancelled'))
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(converters, 'ocr_image', side_effect=[
                OcrResult('Keep this quote.', 'vision'), image_ocr.OcrCancelled('canceled')
            ]) as read:
                result = converters.convert_image_folder_quotes(['a.jpg', 'b.jpg', 'c.jpg'], Path(directory))
            self.assertEqual(read.call_count, 2)
            self.assertIn('CANCELED', result.message)
            self.assertIn('Keep this quote.', Path(result.output_path).read_text())
            report = json.loads(next(Path(directory).glob('*.progress.json')).read_text())
            self.assertEqual(report['status'], 'canceled')
            self.assertEqual(report['processed'], 1)


if __name__ == '__main__':
    unittest.main()
