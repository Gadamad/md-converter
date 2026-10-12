import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from quote_checkpoint import QuoteCheckpoint, fingerprint
from quote_parser import QuoteRecord
from quote_repairs import apply_verified_corrections


def batch(tmp_path):
    sources = [tmp_path / 'one.jpg', tmp_path / 'two.jpg']
    for source in sources:
        source.write_bytes(source.name.encode())
    checkpoint = QuoteCheckpoint(tmp_path, 'quotes', [str(p) for p in sources], 'always')
    for item, text in zip(checkpoint.items, ['A test quoteiỊi', 'Árvíztűrő tükörfúrógép.']):
        checkpoint.complete(item, [QuoteRecord(text, '', Path(item['path']).name, text)], fingerprint(item['path']))
    checkpoint.save('completed')
    target = checkpoint.items[0]
    correction = {'path': target['path'], 'record_index': 0, 'fingerprint': target['fingerprint'],
                  'expected_record': copy.deepcopy(target['records'][0]), 'quote': 'A test quote.', 'author': ''}
    return checkpoint, correction


def test_verified_repair_keeps_original_ocr_and_other_results_and_exports_clean_text(tmp_path):
    checkpoint, correction = batch(tmp_path)
    other = copy.deepcopy(checkpoint.items[1])
    original = copy.deepcopy(checkpoint.items[0]['records'][0])
    assert apply_verified_corrections(checkpoint, [correction]) == 1
    checkpoint.save('completed')
    restored = QuoteCheckpoint.load(checkpoint.report_path)
    repaired = restored.items[0]
    assert repaired['records'][0]['quote'] == 'A test quote.'
    assert repaired['records'][0]['raw_ocr'] == original['raw_ocr']
    assert repaired['correction_history'][0]['before'] == original
    assert repaired['verified_records'] == [0]
    assert restored.items[1] == other
    markdown = restored.path.read_text()
    assert 'iỊi' not in markdown
    assert 'Árvíztűrő tükörfúrógép.' in markdown
    assert 'Verified against original images: 1 quote' in markdown


@pytest.mark.parametrize('bad_guard', ['source', 'record', 'later_record'])
def test_repair_checks_every_guard_before_mutating_any_result(tmp_path, bad_guard):
    checkpoint, correction = batch(tmp_path)
    if bad_guard == 'source':
        Path(correction['path']).write_bytes(b'changed image')
    elif bad_guard == 'record':
        correction['expected_record']['quote'] = 'Changed text'
    else:
        correction = [correction, {**correction, 'record_index': 99}]
    before = copy.deepcopy(checkpoint.report)
    with pytest.raises(ValueError):
        apply_verified_corrections(checkpoint, correction if isinstance(correction, list) else [correction])
    assert checkpoint.report == before


def test_fresh_ocr_clears_source_verification_but_keeps_correction_audit(tmp_path):
    checkpoint, correction = batch(tmp_path)
    apply_verified_corrections(checkpoint, [correction])
    item = checkpoint.items[0]
    checkpoint.complete(item, [QuoteRecord('New recognized text.', '', 'one.jpg', 'New raw OCR.')], item['fingerprint'])
    checkpoint.save('completed')
    assert 'verified_records' not in QuoteCheckpoint.load(checkpoint.report_path).items[0]
    assert item['correction_history']
    assert 'New raw OCR.' in checkpoint.path.read_text()


def test_invalid_later_history_does_not_partially_apply_repairs(tmp_path):
    checkpoint, first = batch(tmp_path)
    second_item = checkpoint.items[1]
    second_item['correction_history'] = 'invalid metadata'
    second = {**first, 'path': second_item['path'], 'fingerprint': second_item['fingerprint'],
              'expected_record': copy.deepcopy(second_item['records'][0])}
    before = copy.deepcopy(checkpoint.report)
    with pytest.raises(ValueError, match='history'):
        apply_verified_corrections(checkpoint, [first, second])
    assert checkpoint.report == before
