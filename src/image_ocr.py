from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tempfile


class OcrBackendUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class OcrResult:
    text: str
    engine: str


def ocr_image(path: Path | str) -> OcrResult:
    image_path = Path(path)
    try:
        return _ocr_with_vision(image_path)
    except OcrBackendUnavailable as vision_error:
        try:
            return _ocr_with_tesseract(image_path)
        except OcrBackendUnavailable as tesseract_error:
            raise OcrBackendUnavailable(
                "No local OCR backend available: "
                f"Vision: {vision_error}; Tesseract: {tesseract_error}"
            ) from tesseract_error


def _ocr_with_vision(path: Path) -> OcrResult:
    try:
        from Foundation import NSURL
        import Vision
    except ImportError as exc:
        raise OcrBackendUnavailable("Vision framework is not installed") from exc

    def reader(image_path: Path) -> str:
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setUsesLanguageCorrection_(True)
        if hasattr(request, "setAutomaticallyDetectsLanguage_"):
            request.setAutomaticallyDetectsLanguage_(True)

        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(
            NSURL.fileURLWithPath_(str(image_path)),
            None,
        )
        success, error = handler.performRequests_error_([request], None)
        if not success:
            message = str(error) if error else "Vision OCR request failed"
            raise OcrBackendUnavailable(message)

        observations = request.results() or []
        lines: list[str] = []
        for observation in observations:
            candidates = observation.topCandidates_(1)
            if candidates:
                candidate_text = candidates[0].string().strip()
                if candidate_text:
                    lines.append(candidate_text)
        return "\n".join(lines)

    text = _best_text_from_variants(path, reader)
    if not text:
        raise OcrBackendUnavailable("Vision OCR returned no text")
    return OcrResult(text=text, engine="vision")


def _ocr_with_tesseract(path: Path) -> OcrResult:
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise OcrBackendUnavailable("pytesseract or Pillow is not installed") from exc

    def reader(image_path: Path) -> str:
        with Image.open(image_path) as image:
            return pytesseract.image_to_string(image)

    text = _best_text_from_variants(path, reader)
    if not text.strip():
        raise OcrBackendUnavailable("Tesseract returned no text")
    return OcrResult(text=text.strip(), engine="tesseract")


def _best_text_from_variants(path: Path, reader) -> str:
    candidate_texts: list[str] = []
    for candidate_path in _iter_variant_paths(path):
        try:
            text = _normalize_text(reader(candidate_path))
        except Exception:
            continue
        if text:
            candidate_texts.append(text)

    if not candidate_texts:
        return ""

    return max(candidate_texts, key=_score_text)


def _iter_variant_paths(path: Path):
    yield path
    try:
        from PIL import Image, ImageFilter, ImageOps
    except ImportError:
        return

    with Image.open(path) as original_image:
        image = original_image.convert("RGB")
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            variants = [
                ("grayscale.png", ImageOps.grayscale(image)),
                ("autocontrast.png", ImageOps.autocontrast(ImageOps.grayscale(image))),
            ]

            width, height = image.size
            scale = 2 if max(width, height) < 2200 else 1
            if scale > 1:
                upscaled = image.resize((width * scale, height * scale), Image.Resampling.LANCZOS)
                variants.append(("upscaled.png", upscaled))
                variants.append(("upscaled-sharp.png", upscaled.filter(ImageFilter.SHARPEN)))

            for name, variant in variants:
                variant_path = temp_root / name
                variant.save(variant_path)
                yield variant_path


def _normalize_text(text: str) -> str:
    collapsed = text.replace("\r\n", "\n").replace("\r", "\n")
    collapsed = "\n".join(line.strip() for line in collapsed.split("\n"))
    collapsed = re.sub(r"\n{3,}", "\n\n", collapsed)
    return collapsed.strip()


def _score_text(text: str) -> int:
    words = re.findall(r"[A-Za-z][A-Za-z'’-]*", text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    odd_symbols = len(re.findall(r"[^\w\s\-—–.,;:'\"!?()]", text))
    author_bonus = 0
    if lines:
        last_line = lines[-1]
        if re.match(r"^(?:[-—–]{1,2}\s*)?[A-Z][A-Za-z.'\- ]{1,60}$", last_line) and len(last_line.split()) <= 5:
            author_bonus = 15
    return len(words) * 4 + len(text) - odd_symbols * 6 + author_bonus
