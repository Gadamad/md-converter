"""Synthetic quote examples only; personal source text must stay outside Git."""
import json
from pathlib import Path
import sys
from unittest import mock

from PIL import Image
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import image_ocr


SUSPECT = 'You can begin again, even when it feels too lateiỊi'
CLEAN = 'You can begin again, even when it feels too late.'


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'synthetic.png'
    Image.new('RGB', (120, 80), 'white').save(path)
    return path


def read_variants(source, texts):
    outcomes = iter(texts)
    return image_ocr._best_text_from_variants(source, lambda *args: next(outcomes, ''), engine='vision')


def suspicious_error():
    assert hasattr(image_ocr, 'OcrSuspiciousText'), 'Uncertain OCR needs a distinct review outcome'
    return image_ocr.OcrSuspiciousText


@pytest.mark.parametrize('text', [
    SUSPECT,
    'ẠỗYou can build a kind life one choice at a time.',
    'Keep your heart open and enjoy the little thingsạ',
    'The path becomes clear when you take the first step.ọ',
    'ịYou have enough strength to begin again today.',
    'Az élet akkor szép, ha minden nap tanulsz valamitạ',
    'The road is longạ and you can take another step today.',
])
def test_suspicious_prefix_suffix_and_interior_runs_try_remaining_variants(source, text):
    result = read_variants(source, [text, CLEAN])
    assert result.text == CLEAN
    rejected = [d for d in result.diagnostics if d['status'] == 'suspicious_text']
    assert rejected and rejected[0]['candidate_text'] == text
    assert rejected[0]['quality_reasons']


@pytest.mark.parametrize('text', [
    'Árvíztűrő tükörfúrógép. Őszintén örülj annak, amit a szíved őriz.',
    'A\u0301rvi\u0301ztu\u030bro\u030b tu\u0308ko\u0308rfu\u0301ro\u0301ge\u0301p.',
    'Hãy giữ lòng tốt và biết ơn những người ở lại bên bạn.',
    'Chị nói rằng mỗi ngày là một cơ hội để học hỏi.',
    'I met Thị yesterday. We talked about kindness.',
    'Learning begins with lòng biết ơn. Keep growing.',
    'We can learn from ViệtNam and other places around the world.',
    'Kindness is found in Ọmọ and in the people around you.',
    'The word ị is part of another language, and we can learn it.',
    'Đỗ Thị Mai', 'lại', 'ạ',
    'Be kind. Soyez aimable. Sé amable. Будь добрым. 親切にしてください。',
])
def test_accents_and_multilingual_text_are_preserved_exactly(source, text):
    assert read_variants(source, [text]).text == text


def test_all_suspicious_variants_raise_review_and_keep_candidates(source):
    with pytest.raises(suspicious_error()) as caught:
        read_variants(source, [SUSPECT] * 5)
    assert caught.value.code == 'suspicious_text'
    assert str(caught.value).startswith('Uncertain OCR text.')
    assert len(caught.value.diagnostics) == 5
    assert all(d['candidate_text'] == SUSPECT for d in caught.value.diagnostics)
    json.dumps(caught.value.diagnostics)


@pytest.mark.parametrize('texts', [[SUSPECT, 'Be kind.'], ['Be kind.', SUSPECT]])
def test_weak_or_truncated_variant_cannot_bypass_quality_review(source, texts):
    with pytest.raises(suspicious_error()) as caught:
        read_variants(source, texts)
    assert any(d.get('candidate_text') == SUSPECT for d in caught.value.diagnostics)
    assert any(d.get('candidate_text') == 'Be kind.' for d in caught.value.diagnostics)


def test_small_natural_variation_is_not_rejected_as_truncation(source):
    shorter = 'You can begin again, even when it feels late.'
    assert read_variants(source, [SUSPECT, shorter]).text == shorter


def test_single_word_fallback_cannot_replace_a_four_word_uncertain_quote(source):
    with pytest.raises(suspicious_error()):
        read_variants(source, ['Always choose kindness todayiỊi', 'Kindness'])


def test_suspicious_vision_result_tries_tesseract_without_stripping_text():
    with mock.patch.object(image_ocr, '_run_backend', side_effect=[
        image_ocr.OcrResult(SUSPECT, 'vision'), image_ocr.OcrResult(CLEAN, 'tesseract')
    ]) as reader:
        result = image_ocr.ocr_image('synthetic.png')
    assert result.text == CLEAN and result.engine == 'tesseract'
    assert reader.call_count == 2
    assert any(d.get('candidate_text') == SUSPECT for d in result.diagnostics)


@pytest.mark.parametrize('fallback', ['Be kind.', None])
def test_no_trustworthy_fallback_keeps_original_candidate_for_review(fallback):
    with mock.patch.object(image_ocr, '_run_backend', side_effect=[
        image_ocr.OcrResult(SUSPECT, 'vision'),
        image_ocr.OcrResult(fallback, 'tesseract') if fallback else image_ocr.OcrNoTextDetected()
    ]):
        with pytest.raises(suspicious_error()) as caught:
            image_ocr.ocr_image('synthetic.png')
    assert any(d.get('candidate_text') == SUSPECT for d in caught.value.diagnostics)


def test_worker_protocol_preserves_suspicious_candidate(tmp_path):
    details = [{'engine': 'vision', 'variant': 'original', 'status': 'suspicious_text',
                'candidate_text': SUSPECT, 'elapsed_seconds': 0.2}]
    def command(engine, path, result):
        payload = json.dumps({'error': 'Uncertain OCR text.', 'code': 'suspicious_text', 'diagnostics': details})
        return [sys.executable, '-c', f'from pathlib import Path; Path({str(result)!r}).write_text({payload!r})']
    with mock.patch.object(image_ocr, '_worker_command', side_effect=command):
        with pytest.raises(suspicious_error()) as caught:
            image_ocr._run_backend('vision', tmp_path / 'synthetic.png')
    assert caught.value.diagnostics == details


def test_fallback_worker_keeps_trying_after_a_clean_but_truncated_first_read(source):
    project_src = str(Path(image_ocr.__file__).parent)
    def command(engine, path, result):
        if engine == 'vision':
            payload = json.dumps({'text': SUSPECT, 'engine': 'vision'})
            script = f'from pathlib import Path; Path({str(result)!r}).write_text({payload!r})'
        else:
            script = f'''
import sys
sys.path.insert(0, {project_src!r})
import image_ocr, ocr_worker
def reader(path, **kwargs):
    texts = iter(['Be kind to others.', {CLEAN!r}])
    return image_ocr._best_text_from_variants(path, lambda *args: next(texts, ''),
        engine='tesseract', **kwargs)
ocr_worker._ocr_with_tesseract = reader
ocr_worker.main(['tesseract', {str(path)!r}, {str(result)!r}])
'''
        return [sys.executable, '-B', '-c', script]
    with mock.patch.object(image_ocr, '_worker_command', side_effect=command):
        result = image_ocr.ocr_image(source)
    assert result.text == CLEAN and result.engine == 'tesseract'
    assert any(d.get('candidate_text') == 'Be kind to others.' for d in result.diagnostics)


def test_timeout_after_uncertain_recognition_preserves_review_candidate():
    details = [{'engine': 'vision', 'variant': 'original', 'status': 'suspicious_text',
                'candidate_text': SUSPECT, 'elapsed_seconds': 0.1}]
    with mock.patch.object(image_ocr, '_run_backend', side_effect=[
        image_ocr.OcrTimeout('Variant timed out', details), image_ocr.OcrNoTextDetected()
    ]):
        with pytest.raises(suspicious_error()) as caught:
            image_ocr.ocr_image('synthetic.png')
    assert caught.value.diagnostics[0]['candidate_text'] == SUSPECT
