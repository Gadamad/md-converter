"""The targeted pass recovers sparse PDF scan text without trusting art noise."""
import io
import os
from pathlib import Path
import sys
import time

import fitz
from PIL import Image, ImageDraw, ImageFont
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from image_ocr import OcrBackendUnavailable, OcrCancelled, OcrNoTextDetected, OcrTimeout, tesseract_executable


def recover(page, **kwargs):
    from pdf_page_ocr import recover_pdf_page
    return recover_pdf_page(page, **kwargs)


def scanned_page(book, image):
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    page = book.new_page(width=520, height=700)
    page.insert_image(page.rect, stream=buffer.getvalue())
    return page


def require_tesseract():
    try:
        tesseract_executable()
    except OcrBackendUnavailable:
        pytest.skip('Local Tesseract is not installed')


def test_recovers_light_heading_and_sign_from_illustrated_page():
    require_tesseract()
    scan = Image.new('L', (780, 1050), 255)
    draw = ImageDraw.Draw(scan)
    font = ImageFont.load_default(size=37)
    draw.rectangle((95, 120, 690, 230), fill=28)
    draw.text((190, 150), '12', fill=250, font=font)
    draw.ellipse((248, 168, 261, 181), fill=250)
    draw.text((281, 150), 'Lantern Road', fill=250, font=font)
    draw.ellipse((170, 340, 640, 855), fill=135, outline=28, width=12)
    draw.rectangle((234, 415, 546, 506), fill=26)
    draw.text((287, 438), 'Crossroads', fill=255, font=font)
    draw.rectangle((234, 690, 546, 781), fill=26)
    draw.text((287, 713), 'Crossroads', fill=255, font=font)
    with fitz.open() as book:
        text = recover(scanned_page(book, scan))
    assert '12' in text and 'Lantern Road' in text
    assert text.count('Crossroads') == 2
    assert text.index('Lantern Road') < text.index('Crossroads')


def test_recovers_dark_text_rotated_inside_an_illustration():
    require_tesseract()
    scan = Image.new('L', (780, 1050), 255)
    draw = ImageDraw.Draw(scan)
    draw.rectangle((100, 130, 680, 230), fill=30)
    draw.ellipse((145, 345, 330, 537), fill=32)
    draw.polygon([(470, 200), (650, 305), (602, 521), (438, 457)], fill=90)
    note = Image.new('L', (365, 155), 255)
    label = ImageDraw.Draw(note)
    font = ImageFont.load_default(size=35)
    label.text((18, 12), 'Measure twice.', fill=16, font=font)
    label.text((18, 67), 'Cut with care.', fill=16, font=font)
    note = note.rotate(20, expand=True, fillcolor=255)
    scan.paste(note, (180, 575))
    with fitz.open() as book:
        text = recover(scanned_page(book, scan))
    assert 'Measure twice.' in text
    assert 'Cut with care.' in text


def test_textless_art_remains_an_explicit_no_text_result():
    require_tesseract()
    scan = Image.new('L', (500, 700), 255)
    draw = ImageDraw.Draw(scan)
    draw.rectangle((70, 75, 430, 620), fill=45)
    draw.ellipse((103, 146, 399, 573), fill=175)
    with fitz.open() as book:
        with pytest.raises(OcrNoTextDetected):
            recover(scanned_page(book, scan))


def test_cancelled_call_does_not_render_the_page():
    class UnrenderedPage:
        def get_pixmap(self, *args, **kwargs):
            pytest.fail('Cancellation must be checked before rendering')
    with pytest.raises(OcrCancelled):
        recover(UnrenderedPage(), should_cancel=lambda: True)


def test_refinement_keeps_corroborated_lower_confidence_word_without_edge_strokes():
    from pdf_page_ocr import _Word, _refine
    proposals = [[_Word('Observe.', 94, (20, 10, 95, 35))],
                 [_Word('Carefully.', 95, (20, 42, 110, 68))]]
    refined = [[_Word('Observe.', 93, (20, 12, 120, 37))],
               [_Word('—', 0, (8, 53, 16, 56)), _Word('Carefully.', 79, (20, 49, 130, 74)),
                _Word('|', 54, (138, 53, 144, 81))]]
    assert _refine(Image.new('L', (160, 100), 255), proposals, light=False,
                   recognize=lambda image, psm: refined) == 'Observe.\nCarefully.'


@pytest.mark.skipif(os.name != 'posix', reason='Uses a POSIX process fixture')
@pytest.mark.parametrize('cancel', [False, True])
def test_active_tesseract_process_is_reaped_on_timeout_or_cancellation(tmp_path, monkeypatch, cancel):
    import pdf_page_ocr
    candidate = tmp_path / 'candidate.png'
    marker = candidate.with_suffix('.png.pid')
    worker = tmp_path / 'stalling-ocr'
    worker.write_text('#!/bin/sh\nprintf %s "$$" > "$1.pid"\nexec /bin/sleep 60\n')
    worker.chmod(0o700)
    pids = []
    spawn = pdf_page_ocr.subprocess.Popen
    def observe_spawn(*args, **kwargs):
        process = spawn(*args, **kwargs)
        pids.append(process.pid)
        return process
    monkeypatch.setattr(pdf_page_ocr.subprocess, 'Popen', observe_spawn)
    monkeypatch.setattr(pdf_page_ocr, '_ATTEMPT_SECONDS', 3 if cancel else .3)
    with pytest.raises(OcrCancelled if cancel else OcrTimeout):
        pdf_page_ocr._recognize(candidate, str(worker), 11, time.monotonic() + 5,
                                marker.exists if cancel else None)
    assert len(pids) == 1
    with pytest.raises(ProcessLookupError):
        os.kill(pids[0], 0)


def test_expired_page_budget_does_not_begin_rendering(monkeypatch):
    import pdf_page_ocr
    monkeypatch.setattr(pdf_page_ocr, '_TOTAL_SECONDS', 0)
    class UnrenderedPage:
        def get_pixmap(self, *args, **kwargs):
            pytest.fail('An expired recovery budget must not render')
    with pytest.raises(OcrTimeout):
        recover(UnrenderedPage())
