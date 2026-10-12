import json
from pathlib import Path
import sys
import time
from unittest import mock

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import image_ocr
import ocr_worker


def error_class(name):
    assert hasattr(image_ocr, name), f'OCR needs a distinct {name} outcome'
    return getattr(image_ocr, name)


@pytest.fixture
def quote_image(tmp_path):
    path = tmp_path / 'quote.png'
    Image.new('RGB', (100, 100), 'white').save(path)
    with mock.patch('pytesseract.image_to_data', return_value=tesseract_data([])):
        yield path


def tesseract_data(words, confidences=None, lines=None, paragraphs=None):
    count = len(words)
    return {'text': words, 'conf': confidences if confidences is not None else [95] * count,
            'block_num': [1] * count, 'par_num': paragraphs or [1] * count,
            'line_num': lines or [1] * count}


def test_result_accepts_optional_json_serializable_diagnostics():
    assert image_ocr.OcrResult('Legacy text', 'vision').diagnostics == []
    details = [{'engine': 'vision', 'variant': 'original', 'status': 'text', 'elapsed_seconds': 0.5}]
    result = image_ocr.OcrResult('A readable quote.', 'vision', details)
    assert json.loads(json.dumps(result.diagnostics)) == details


def test_two_empty_backends_are_no_text_not_unavailable():
    no_text = error_class('OcrNoTextDetected')
    details = [{'engine': 'vision', 'variant': 'original', 'status': 'no_text', 'elapsed_seconds': 0.1}]
    with mock.patch.object(image_ocr, '_run_backend', side_effect=[no_text('empty', details), no_text('empty')]):
        with pytest.raises(no_text) as caught:
            image_ocr.ocr_image('image.png')
    assert caught.value.code == 'no_text'
    assert details[0] in caught.value.diagnostics
    assert 'No local OCR backend available' not in str(caught.value)


@pytest.mark.parametrize('name,code', [('OcrTimeout', 'timeout'),
                                      ('OcrProcessingError', 'processing_error'),
                                      ('OcrBackendUnavailable', 'unavailable')])
def test_empty_fallback_does_not_hide_a_real_engine_failure(name, code):
    no_text = error_class('OcrNoTextDetected')
    failure = error_class(name)
    with mock.patch.object(image_ocr, '_run_backend', side_effect=[failure('broken'), no_text('empty')]):
        with pytest.raises(failure) as caught:
            image_ocr.ocr_image('image.png')
    assert caught.value.code == code
    assert not isinstance(caught.value, no_text)


def test_successful_fallback_retains_first_engine_diagnostics():
    detail = {'engine': 'vision', 'variant': 'original', 'status': 'timeout', 'elapsed_seconds': 30.0}
    with mock.patch.object(image_ocr, '_run_backend', side_effect=[
        image_ocr.OcrTimeout('late', [detail]), image_ocr.OcrResult('A recovered quote.', 'tesseract')
    ]):
        result = image_ocr.ocr_image('image.png')
    assert detail in result.diagnostics


def test_empty_backend_plus_unavailable_does_not_claim_neither_ran():
    with mock.patch.object(image_ocr, '_run_backend', side_effect=[
        image_ocr.OcrNoTextDetected(), image_ocr.OcrBackendUnavailable('Tesseract missing')
    ]):
        with pytest.raises(image_ocr.OcrBackendUnavailable) as caught:
            image_ocr.ocr_image('image.png')
    assert str(caught.value).startswith('OCR backend unavailable:')
    assert 'vision: No text detected.' in str(caught.value)


def test_tesseract_tries_quote_layouts_after_default_empty_then_stops(quote_image):
    with mock.patch.object(image_ocr, 'tesseract_executable', return_value='/test/tesseract'), \
         mock.patch('pytesseract.image_to_string', return_value='') as reader, \
         mock.patch('pytesseract.image_to_data', side_effect=[tesseract_data([]),
             tesseract_data('We become what we repeatedly do.'.split())]) as recovery:
        result = image_ocr._ocr_with_tesseract(quote_image)
    calls = reader.call_args_list + recovery.call_args_list
    assert [call.kwargs.get('config', '') for call in calls] == ['', '--psm 6', '--psm 11']
    assert result.text == 'We become what we repeatedly do.'
    assert [detail['status'] for detail in result.diagnostics] == ['no_text', 'no_text', 'text']
    assert all(detail['engine'] == 'tesseract' and detail['variant'] == 'original' for detail in result.diagnostics)
    assert all(0 < call.kwargs['timeout'] <= 30 for call in calls)


def test_good_default_text_avoids_extra_layouts_and_variants(quote_image):
    with mock.patch.object(image_ocr, 'tesseract_executable', return_value='/test/tesseract'), \
         mock.patch('pytesseract.image_to_string', return_value='We become what we repeatedly do.') as reader:
        result = image_ocr._ocr_with_tesseract(quote_image)
    assert reader.call_count == 1
    assert result.diagnostics[0]['status'] == 'text'


def test_all_successfully_empty_variants_have_no_text_diagnostics(quote_image):
    no_text = error_class('OcrNoTextDetected')
    with mock.patch.object(image_ocr, 'tesseract_executable', return_value='/test/tesseract'), \
         mock.patch('pytesseract.image_to_string', return_value=''):
        with pytest.raises(no_text) as caught:
            image_ocr._ocr_with_tesseract(quote_image)
    details = caught.value.diagnostics
    assert {d['variant'] for d in details} == {'original', 'grayscale', 'autocontrast', 'upscaled', 'upscaled-sharp'}
    assert len(details) == 15
    assert all(d['status'] == 'no_text' and d['elapsed_seconds'] >= 0 for d in details)
    json.dumps(details)


def test_reader_exception_is_preserved_instead_of_becoming_no_text(quote_image):
    processing = error_class('OcrProcessingError')
    with mock.patch.object(image_ocr, 'tesseract_executable', return_value='/test/tesseract'), \
         mock.patch('pytesseract.image_to_string', side_effect=RuntimeError('traineddata unreadable')):
        with pytest.raises(processing) as caught:
            image_ocr._ocr_with_tesseract(quote_image)
    assert caught.value.code == 'processing_error'
    assert any(d.get('error_type') == 'RuntimeError' and d.get('error') == 'traineddata unreadable' for d in caught.value.diagnostics)


def test_backend_reader_errors_cannot_be_masked_by_later_empty_variants(quote_image):
    processing = error_class('OcrProcessingError')
    responses = iter([RuntimeError('first attempt failed')])
    def read(*args, **kwargs):
        outcome = next(responses, '')
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    with mock.patch.object(image_ocr, 'tesseract_executable', return_value='/test/tesseract'), \
         mock.patch('pytesseract.image_to_string', side_effect=read):
        with pytest.raises(processing) as caught:
            image_ocr._ocr_with_tesseract(quote_image)
    assert any(d['status'] == 'no_text' for d in caught.value.diagnostics)
    assert any(d.get('error') == 'first attempt failed' for d in caught.value.diagnostics)


def test_worker_serializes_typed_failure_and_details(tmp_path):
    no_text = error_class('OcrNoTextDetected')
    detail = {'engine': 'vision', 'variant': 'original', 'status': 'no_text', 'elapsed_seconds': 0.2}
    destination = tmp_path / 'result.json'
    with mock.patch.object(ocr_worker.tempfile, 'tempdir', str(tmp_path)), \
         mock.patch.object(ocr_worker, '_ocr_with_vision', side_effect=no_text('Nothing recognized', [detail])):
        assert ocr_worker.main(['vision', '/tmp/image.png', str(destination)]) == 0
    payload = json.loads(destination.read_text())
    assert payload['code'] == 'no_text'
    assert payload['error_type'] == 'OcrNoTextDetected'
    assert payload['diagnostics'] == [detail]


def test_supervisor_deserializes_structured_failure(tmp_path):
    no_text = error_class('OcrNoTextDetected')
    detail = {'engine': 'tesseract', 'variant': 'original', 'status': 'no_text', 'elapsed_seconds': 0.2}
    def command(engine, path, result):
        payload = json.dumps({'error': 'Nothing recognized', 'code': 'no_text', 'error_type': 'OcrNoTextDetected', 'diagnostics': [detail]})
        return [sys.executable, '-c', f'from pathlib import Path; Path({str(result)!r}).write_text({payload!r})']
    with mock.patch.object(image_ocr, '_worker_command', side_effect=command):
        with pytest.raises(no_text) as caught:
            image_ocr._run_backend('tesseract', tmp_path / 'image.png', timeout=2)
    assert detail in caught.value.diagnostics


def test_supervisor_timeout_keeps_last_worker_diagnostics(tmp_path):
    detail = {'engine': 'vision', 'variant': 'grayscale', 'status': 'running', 'elapsed_seconds': 0}
    def command(engine, path, result):
        payload = json.dumps({'diagnostics': [detail]})
        return [sys.executable, '-c', f'import time; from pathlib import Path; Path({str(result)!r}).write_text({payload!r}); time.sleep(60)']
    with mock.patch.object(image_ocr, '_worker_command', side_effect=command):
        with pytest.raises(image_ocr.OcrTimeout) as caught:
            image_ocr._run_backend('vision', tmp_path / 'image.png', timeout=0.3)
    assert detail in caught.value.diagnostics
    assert any(d['status'] == 'timeout' for d in caught.value.diagnostics)


def test_supervisor_accepts_legacy_string_failure(tmp_path):
    def command(engine, path, result):
        payload = json.dumps({'error': 'legacy failure'})
        return [sys.executable, '-c', f'from pathlib import Path; Path({str(result)!r}).write_text({payload!r})']
    with mock.patch.object(image_ocr, '_worker_command', side_effect=command):
        with pytest.raises(image_ocr.OcrBackendUnavailable, match='legacy failure'):
            image_ocr._run_backend('vision', tmp_path / 'image.png', timeout=2)


def test_variant_recovery_shares_one_deadline(quote_image):
    timeouts = []
    def read(*args, **kwargs):
        timeouts.append(kwargs['timeout'])
        time.sleep(0.03)
        return ''
    with mock.patch.object(image_ocr, 'tesseract_executable', return_value='/test/tesseract'), \
         mock.patch('pytesseract.image_to_string', side_effect=read):
        with pytest.raises(image_ocr.OcrTimeout) as caught:
            image_ocr._ocr_with_tesseract(quote_image, deadline=time.monotonic() + 0.05)
    assert 1 <= len(timeouts) <= 2
    assert all(0 < timeout <= 0.05 for timeout in timeouts)
    assert timeouts == sorted(timeouts, reverse=True)
    assert caught.value.diagnostics[-1]['status'] == 'timeout'


def test_tesseract_timeout_is_typed_and_keeps_original_exception(quote_image):
    with mock.patch.object(image_ocr, 'tesseract_executable', return_value='/test/tesseract'), \
         mock.patch('pytesseract.image_to_string', side_effect=RuntimeError('Tesseract process timeout')) as reader:
        with pytest.raises(image_ocr.OcrTimeout) as caught:
            image_ocr._ocr_with_tesseract(quote_image)
    assert reader.call_count == 1
    assert caught.value.diagnostics[0]['error_type'] == 'RuntimeError'
    assert caught.value.diagnostics[0]['error'] == 'Tesseract process timeout'


def test_vision_request_error_is_not_classified_as_empty(quote_image):
    request = mock.Mock()
    request.results.return_value = []
    vision = mock.Mock()
    vision.VNRecognizeTextRequest.alloc.return_value.init.return_value = request
    handler = vision.VNImageRequestHandler.alloc.return_value.initWithURL_options_.return_value
    handler.performRequests_error_.side_effect = [(False, 'Vision request rejected')] + [(True, None)] * 4
    with mock.patch.dict(sys.modules, {'Vision': vision, 'Foundation': mock.Mock()}):
        with pytest.raises(image_ocr.OcrProcessingError) as caught:
            image_ocr._ocr_with_vision(quote_image)
    assert len(caught.value.diagnostics) == 5
    assert caught.value.diagnostics[0]['error'] == 'Vision request rejected'
    assert caught.value.diagnostics[-1]['status'] == 'no_text'


def test_worker_launch_failure_is_typed_with_diagnostics(tmp_path):
    with mock.patch.object(image_ocr.subprocess, 'Popen', side_effect=OSError('executable denied')):
        with pytest.raises(image_ocr.OcrBackendUnavailable) as caught:
            image_ocr._run_backend('vision', tmp_path / 'image.png', timeout=2)
    assert caught.value.code == 'unavailable'
    assert caught.value.diagnostics[0]['error_type'] == 'OSError'
    assert caught.value.diagnostics[0]['error'] == 'executable denied'


@pytest.mark.parametrize('words,confidences', [(['~', '|', ';'], [95, 98, 99]),
                                             (['~~~~|', 'a'], [99, 10]),
                                             (['ge', 'if', 'ee', 'Pe', 'Be'], [46, 47, 45, 31, 37]),
                                             (['inspiring', 'but', 'unreliable', 'noise'], [90, 12, 5, 11])])
def test_recovery_modes_reject_texture_and_low_confidence_noise(quote_image, words, confidences):
    with mock.patch.object(image_ocr, 'tesseract_executable', return_value='/test/tesseract'), \
         mock.patch('pytesseract.image_to_string', return_value=''), \
         mock.patch('pytesseract.image_to_data', return_value=tesseract_data(words, confidences)):
        with pytest.raises(image_ocr.OcrNoTextDetected) as caught:
            image_ocr._ocr_with_tesseract(quote_image)
    rejected = [d for d in caught.value.diagnostics if d.get('config')]
    assert len(rejected) == 10
    assert all(d['confidence_accepted'] is False and d['rejection_reason'] for d in rejected)
    assert all('confidence_mean' in d and d['candidate_characters'] > 0 for d in rejected)


def test_recovery_accepts_one_high_confidence_word_without_extra_variants(quote_image):
    with mock.patch.object(image_ocr, 'tesseract_executable', return_value='/test/tesseract'), \
         mock.patch('pytesseract.image_to_string', return_value='') as default, \
         mock.patch('pytesseract.image_to_data', return_value=tesseract_data(['Hope.'], [97])) as recovery:
        result = image_ocr._ocr_with_tesseract(quote_image)
    assert result.text == 'Hope.'
    assert default.call_count == recovery.call_count == 1
    assert result.diagnostics[-1]['confidence_accepted'] is True


def test_recovery_preserves_reading_order_lines_and_paragraphs(quote_image):
    data = tesseract_data(['Be', 'kind.', 'Stay', 'curious.', 'Author'],
                         lines=[1, 1, 2, 2, 1], paragraphs=[1, 1, 1, 1, 2])
    with mock.patch.object(image_ocr, 'tesseract_executable', return_value='/test/tesseract'), \
         mock.patch('pytesseract.image_to_string', return_value=''), \
         mock.patch('pytesseract.image_to_data', return_value=data):
        result = image_ocr._ocr_with_tesseract(quote_image)
    assert result.text == 'Be kind.\nStay curious.\n\nAuthor'


def test_recovery_reader_exception_is_preserved(quote_image):
    with mock.patch.object(image_ocr, 'tesseract_executable', return_value='/test/tesseract'), \
         mock.patch('pytesseract.image_to_string', return_value=''), \
         mock.patch('pytesseract.image_to_data', side_effect=RuntimeError('TSV reader failed')):
        with pytest.raises(image_ocr.OcrProcessingError) as caught:
            image_ocr._ocr_with_tesseract(quote_image)
    assert any(d.get('config') == '--psm 6' and d.get('error') == 'TSV reader failed'
               for d in caught.value.diagnostics)
