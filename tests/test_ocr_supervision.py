import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import image_ocr


class OcrSupervisionTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(image_ocr, '_run_backend'), 'OCR needs a supervised subprocess boundary')

    def test_stalled_worker_is_killed_and_temporary_files_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / 'pid'
            work_dirs = []
            def command(engine, path, result):
                work_dirs.append(result.parent)
                code = f'import os,time; open({str(pid_file)!r},"w").write(str(os.getpid())); time.sleep(60)'
                return [sys.executable, '-c', code]
            start = time.monotonic()
            with mock.patch.object(image_ocr, '_worker_command', side_effect=command):
                with self.assertRaises(image_ocr.OcrTimeout):
                    image_ocr._run_backend('vision', Path('quote.png'), timeout=0.5)
            self.assertLess(time.monotonic() - start, 3)
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pid_file.read_text()), 0)
            self.assertFalse(work_dirs[0].exists())

    def test_cancellation_interrupts_live_worker(self):
        start = time.monotonic()
        with mock.patch.object(image_ocr, '_worker_command', return_value=[sys.executable, '-c', 'import time; time.sleep(60)']):
            with self.assertRaises(image_ocr.OcrCancelled):
                image_ocr._run_backend('vision', Path('quote.png'), timeout=30,
                                       should_cancel=lambda: time.monotonic() - start > 0.25)
        self.assertLess(time.monotonic() - start, 3)

    def test_crashed_worker_is_a_reported_failure(self):
        with mock.patch.object(image_ocr, '_worker_command', return_value=[sys.executable, '-c', 'raise SystemExit(7)']):
            with self.assertRaisesRegex(image_ocr.OcrBackendUnavailable, '7'):
                image_ocr._run_backend('vision', Path('quote.png'), timeout=2)

    def test_worker_result_protocol(self):
        def command(engine, path, result):
            payload = json.dumps({'text': 'Readable quote.', 'engine': engine})
            return [sys.executable, '-c', f'from pathlib import Path; Path({str(result)!r}).write_text({payload!r})']
        with mock.patch.object(image_ocr, '_worker_command', side_effect=command):
            result = image_ocr._run_backend('vision', Path('quote.png'), timeout=2)
        self.assertEqual(result.text, 'Readable quote.')

    def test_timeout_switches_remaining_batch_to_tesseract(self):
        session = image_ocr.OcrSession()
        notices = []
        with mock.patch.object(image_ocr, '_run_backend', side_effect=[
            image_ocr.OcrTimeout('Vision timed out'),
            image_ocr.OcrResult('one', 'tesseract'),
            image_ocr.OcrResult('two', 'tesseract'),
        ]) as run:
            image_ocr.ocr_image('one.png', session=session, on_status=notices.append)
            image_ocr.ocr_image('two.png', session=session, on_status=notices.append)
        self.assertEqual([call.args[0] for call in run.call_args_list], ['vision', 'tesseract', 'tesseract'])
        self.assertTrue(notices)

    def test_cancellation_does_not_start_fallback(self):
        with mock.patch.object(image_ocr, '_run_backend', side_effect=image_ocr.OcrCancelled()) as run:
            with self.assertRaises(image_ocr.OcrCancelled):
                image_ocr.ocr_image('quote.png')
        self.assertEqual(run.call_count, 1)

    def test_frozen_command_uses_internal_mode(self):
        with mock.patch.object(sys, 'frozen', True, create=True):
            command = image_ocr._worker_command('vision', Path('/tmp/a.jpg'), Path('/tmp/result.json'))
        self.assertEqual(command[:2], [sys.executable, '--ocr-worker'])

    def test_image_variants_never_enlarge_2048_image_to_4096(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'quote.png'
            Image.new('RGB', (2048, 2048), 'white').save(path)
            for variant in image_ocr._iter_variant_paths(path):
                with Image.open(variant) as im:
                    self.assertLessEqual(max(im.size), 2200)

    def test_normal_app_exit_stops_active_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / 'worker.pid'
            source = str(Path(image_ocr.__file__).parent)
            worker_code = f"import os,time; open({str(pid_file)!r}, 'w').write(str(os.getpid())); time.sleep(60)"
            parent_code = f"""
import sys,threading,time
from pathlib import Path
sys.path.insert(0, {source!r})
import image_ocr
image_ocr._worker_command = lambda *args: [sys.executable, '-c', {worker_code!r}]
threading.Thread(target=lambda: image_ocr._run_backend('vision', Path('quote.png')), daemon=True).start()
deadline=time.monotonic()+3
while not Path({str(pid_file)!r}).exists() and time.monotonic()<deadline:
    time.sleep(0.01)
"""
            result = subprocess.run([sys.executable, '-B', '-c', parent_code], capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertTrue(pid_file.exists())
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pid_file.read_text()), 0)


if __name__ == '__main__':
    unittest.main()
