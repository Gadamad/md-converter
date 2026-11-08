"""Bounded local OCR for sparse text embedded in a PDF illustration."""
from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

import fitz
from PIL import Image, ImageDraw, ImageOps

import image_ocr
from image_ocr import (OcrBackendUnavailable, OcrCancelled, OcrNoTextDetected,
                       OcrProcessingError, OcrSuspiciousText, OcrTimeout)


_PAGE_EDGE = 2200
_TOTAL_SECONDS = 18.0
_ATTEMPT_SECONDS = 4.0
_MAX_ATTEMPTS = 10
_MAX_RUNS = 100_000
_DARK_THRESHOLD = 96
_LIGHT_THRESHOLD = 195
_RUNS = re.compile(rb'\xff+')
_NUMBERED_WORD = re.compile(r'^(\d+[.)])(?=[^\W\d_])')


@dataclass(frozen=True)
class _Word:
    text: str
    confidence: float
    box: tuple[int, int, int, int]


def _check(deadline, should_cancel):
    if should_cancel and should_cancel():
        raise OcrCancelled('OCR canceled')
    if time.monotonic() >= deadline:
        raise OcrTimeout('PDF page OCR recovery exceeded its time budget')


def _render(page):
    edge = max(page.rect.width, page.rect.height)
    if not math.isfinite(edge) or edge <= 0:
        raise OcrProcessingError('Invalid PDF page dimensions')
    scale = min(200 / 72, _PAGE_EDGE / edge)
    try:
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csGRAY, alpha=False)
        gray = Image.frombytes('L', (pixmap.width, pixmap.height), pixmap.samples)
    except (ValueError, RuntimeError) as exc:
        raise OcrProcessingError(f'Could not render PDF page: {exc}') from exc
    bounds = gray.point([255 if value < 247 else 0 for value in range(256)]).getbbox()
    return gray.crop(bounds) if bounds else None


def _isolate(gray, *, light, check):
    """Retain glyph-sized components, removing the page's broad drawing shapes."""
    width, height = gray.size
    foreground = gray.point([255 if (v > _LIGHT_THRESHOLD if light else v < _DARK_THRESHOLD)
                             else 0 for v in range(256)]).tobytes()
    runs, parents, previous = [], [], []

    def root(index):
        while index != parents[index]:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for y in range(height):
        if y % 32 == 0:
            check()
        active, cursor = [], 0
        for match in _RUNS.finditer(foreground, y * width, (y + 1) * width):
            if len(runs) == _MAX_RUNS:
                raise OcrSuspiciousText('The page is too visually dense to isolate reliable text')
            left, right = (point - y * width for point in match.span())
            index = len(runs)
            runs.append((left, right, y))
            parents.append(index)
            active.append(index)
            while cursor < len(previous) and runs[previous[cursor]][1] < left:
                cursor += 1
            prior = cursor
            while prior < len(previous) and runs[previous[prior]][0] <= right:
                parents[root(index)] = root(previous[prior])
                prior += 1
        previous = active

    stats = {}
    for index, (left, right, y) in enumerate(runs):
        if index % 1024 == 0:
            check()
        box = stats.setdefault(root(index), [left, y, right, y + 1, 0])
        box[0], box[2], box[3] = min(box[0], left), max(box[2], right), y + 1
        box[4] += right - left
    keep = set()
    for index, (left, top, right, bottom, count) in stats.items():
        w, h = right - left, bottom - top
        if (2 <= w <= max(48, width * .17) and 3 <= h <= max(55, height * .08)
                and count >= max(8, w * h * .08) and h <= w * 8 and w <= h * 5):
            keep.add(index)
    if not keep:
        return None
    mask = Image.new('L', gray.size, 255)
    draw = ImageDraw.Draw(mask)
    for index, (left, right, y) in enumerate(runs):
        if index % 1024 == 0:
            check()
        if root(index) in keep:
            draw.line((left, y, right - 1, y), fill=0)
    return mask


def _read_tsv(payload):
    groups = {}
    try:
        for line in payload.decode('utf-8', errors='replace').splitlines()[1:]:
            fields = line.split('\t', 11)
            if len(fields) != 12 or fields[0] != '5' or not fields[11].strip():
                continue
            x, y, width, height = map(int, fields[6:10])
            confidence = float(fields[10])
            if min(x, y) < 0 or min(width, height) <= 0 or not 0 <= confidence <= 100:
                continue
            groups.setdefault(tuple(fields[1:5]), []).append(
                _Word(fields[11].strip(), confidence, (x, y, x + width, y + height)))
    except ValueError as exc:
        raise OcrProcessingError('Tesseract returned invalid page OCR coordinates') from exc
    return list(groups.values())


def _recognize(path, executable, psm, deadline, should_cancel):
    deadline = min(deadline, time.monotonic() + _ATTEMPT_SECONDS)
    _check(deadline, should_cancel)
    with image_ocr._workers_lock:
        if image_ocr._shutting_down:
            raise OcrCancelled('Application is closing')
        try:
            process = subprocess.Popen([executable, str(path), 'stdout', '--psm', str(psm), 'tsv'],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=(os.name == 'posix'))
        except OSError as exc:
            raise OcrBackendUnavailable(f'Tesseract could not start: {exc}') from exc
        image_ocr._active_workers[process] = str(path.parent)
    try:
        while True:
            _check(deadline, should_cancel)
            try:
                stdout, stderr = process.communicate(timeout=min(.05, max(.001, deadline - time.monotonic())))
                break
            except subprocess.TimeoutExpired:
                continue
        _check(deadline, should_cancel)
        if process.returncode:
            detail = stderr[:1000].decode('utf-8', errors='replace').strip()
            raise OcrProcessingError(f'Tesseract failed on the PDF page: {detail or process.returncode}')
        return _read_tsv(stdout)
    finally:
        try:
            image_ocr._stop_worker(process)
        finally:
            process.stdout.close()
            process.stderr.close()
            with image_ocr._workers_lock:
                image_ocr._active_workers.pop(process, None)


def _bounds(words):
    return (min(w.box[0] for w in words), min(w.box[1] for w in words),
            max(w.box[2] for w in words), max(w.box[3] for w in words))


def _overlap(first, second):
    l1, t1, r1, b1 = first
    l2, t2, r2, b2 = second
    shared = max(0, min(r1, r2) - max(l1, l2)) * max(0, min(b1, b2) - max(t1, t2))
    return shared >= .6 * min((r1 - l1) * (b1 - t1), (r2 - l2) * (b2 - t2))


def _letter_count(text):
    return sum(c.isalpha() for c in text)


def _anchor(word):
    return _letter_count(word.text) >= 3 and word.confidence >= 80


def _dot(image, before, word, after):
    """Recognize a physical midline dot rather than keeping OCR's stray letter."""
    l, t, r, b = word.box
    width, height = r - l, b - t
    if len(word.text) != 1 or not .75 <= width / height <= 1.35:
        return False
    heights = [neighbour.box[3] - neighbour.box[1] for neighbour in (before, after)]
    centers = [(neighbour.box[1] + neighbour.box[3]) / 2 for neighbour in (before, after)]
    if (not .22 <= height / min(heights) <= .55
            or abs((t + b) / 2 - sum(centers) / 2) > min(heights) * .24):
        return False
    histogram = image.crop(word.box).histogram()
    return .63 <= sum(histogram[:100]) / (width * height) <= .90


def _word_key(text):
    return text.casefold().strip('.,:;!?')


def _corroborated(word, anchors):
    return word.confidence >= 72 and _letter_count(word.text) >= 4 and _word_key(word.text) in anchors


def _line_text(words, image, anchors=frozenset()):
    if not any((_anchor(word) and _letter_count(word.text) >= 4) or _corroborated(word, anchors)
               for word in words):
        return None
    if len(words) == 1 and words[0].confidence < 88 and not _corroborated(words[0], anchors):
        return None
    parts = []
    for index, word in enumerate(words):
        if index and index < len(words) - 1 and _dot(image, words[index - 1], word, words[index + 1]):
            parts.append('•')
            continue
        if not word.text.strip('|/\\_'):
            continue  # isolated drawing strokes
        if (anchors and (index == 0 or index == len(words) - 1) and word.confidence < 20
                and word.text in ('—', '–', '-')):
            continue  # an uncertain stroke outside the corroborated line
        if word.confidence < (60 if _NUMBERED_WORD.match(word.text) else 68):
            return None
        parts.append(_NUMBERED_WORD.sub(r'\1 ', word.text))
    text = ' '.join(parts)
    return text if text and not image_ocr._text_quality_reasons(text) else None


def _nearby(lines):
    """Group nearby aligned text proposals for one tight block read."""
    groups = []
    for line in sorted(lines, key=lambda words: _bounds(words)[1]):
        l, t, r, b = _bounds(line)
        for group in reversed(groups):
            gl, gt, gr, gb = _bounds([word for row in group for word in row])
            if t - gb <= (b - t) * .65 and min(r, gr) - max(l, gl) >= min(r - l, gr - gl) * .35:
                group.append(line)
                break
        else:
            groups.append([line])
    return groups


def _refine(gray, group, *, light, recognize):
    l, t, r, b = _bounds([word for line in group for word in line])
    pad = min(16, max(4, round((b - t) * .05)))
    crop = gray.crop((max(0, l - pad), max(0, t - pad), min(gray.width, r + pad), min(gray.height, b + pad)))
    crop = crop.point([0 if (v > _LIGHT_THRESHOLD if light else v < _DARK_THRESHOLD)
                       else 255 for v in range(256)])
    scale = min(2, (_PAGE_EDGE - 24) / max(crop.size))
    crop = crop.resize(tuple(max(1, round(length * scale)) for length in crop.size), Image.Resampling.LANCZOS)
    crop = ImageOps.expand(crop, border=12, fill=255)
    lines = recognize(crop, 6 if len(group) > 1 else 7)
    anchors = {_word_key(w.text) for line in group for w in line if _anchor(w)}
    recovered = [_line_text(line, crop, anchors) for line in lines
                 if any(_anchor(word) or _corroborated(word, anchors) for word in line)]
    if not recovered or any(text is None for text in recovered):
        return None
    text = '\n'.join(recovered)
    words = {_word_key(word) for word in text.split()}
    if len(anchors & words) < max(1, math.ceil(len(anchors) * .67)):
        return None  # A different reading must not silently replace the reliable words.
    return text


def recover_pdf_page(page, *, should_cancel=None) -> str:
    """Recover trustworthy sparse scan text or report why recovery could not."""
    deadline = time.monotonic() + _TOTAL_SECONDS
    def check():
        _check(deadline, should_cancel)

    check()
    gray = _render(page)
    check()
    if gray is None:
        raise OcrNoTextDetected('No text detected on the PDF page')

    with tempfile.TemporaryDirectory(prefix='md-pdf-page-ocr-') as directory:
        path = Path(directory) / 'candidate.png'
        attempts = 0
        executable = None
        diagnostics = []

        def recognize(image, psm):
            nonlocal attempts, executable
            check()
            if attempts >= _MAX_ATTEMPTS:
                return []
            executable = executable or image_ocr.tesseract_executable()
            attempts += 1
            image.save(path)
            return _recognize(path, executable, psm, deadline, should_cancel)

        def read(mask, original, *, light):
            lines = [line for line in recognize(mask, 11) if any(_anchor(word) for word in line)]
            results = []
            for group in _nearby(lines):
                text = [_line_text(line, mask) for line in group]
                if not all(text):
                    recovered = _refine(original, group, light=light, recognize=recognize)
                    if recovered is None:
                        diagnostics.append({'status': 'suspicious_text', 'candidate_text':
                            '\n'.join(' '.join(w.text for w in line) for line in group)})
                        return []
                else:
                    recovered = '\n'.join(text)
                results.append((_bounds([w for row in group for w in row]), recovered))
            return results

        light = _isolate(gray, light=True, check=check)
        dark = _isolate(gray, light=False, check=check)
        initial = []
        for mask, polarity in ((light, True), (dark, False)):
            if mask is not None:
                initial.extend(read(mask, gray, light=polarity))
        if initial:
            ordered = []
            for box, text in sorted(initial, key=lambda row: (row[0][1], row[0][0])):
                if not any(text == known and _overlap(box, area) for area, known in ordered):
                    ordered.append((box, text))
            return '\n'.join(text for _, text in ordered)
        if dark is not None:
            for angle in (-20, 20, -12, 12):
                check()
                mask = dark.rotate(angle, Image.Resampling.BICUBIC, expand=True, fillcolor=255)
                original = gray.rotate(angle, Image.Resampling.BICUBIC, expand=True, fillcolor=255)
                recovered = read(mask, original, light=False)
                if recovered:
                    return '\n'.join(text for _, text in recovered)
        if diagnostics:
            raise OcrSuspiciousText('Text was detected on the PDF page but could not be read reliably', diagnostics)
        raise OcrNoTextDetected('No reliable text detected on the PDF page')
