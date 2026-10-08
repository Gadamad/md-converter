from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import atexit
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time


class OcrBackendUnavailable(RuntimeError):
    pass


class OcrTimeout(OcrBackendUnavailable):
    pass


class OcrCancelled(RuntimeError):
    pass


@dataclass
class OcrSession:
    vision_timed_out: bool = False


@dataclass(frozen=True)
class OcrResult:
    text: str
    engine: str


OCR_TIMEOUT_SECONDS = 30.0
_workers_lock = threading.Lock()
_active_workers = {}
_shutting_down = False


def _worker_command(engine: str, path: Path, result_path: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        prefix = [sys.executable, "--ocr-worker"]
    else:
        prefix = [sys.executable, "-B", str(Path(__file__).with_name("ocr_worker.py"))]
    return prefix + [engine, str(path.resolve()), str(result_path)]


def _stop_worker(process: subprocess.Popen) -> None:
    # Each worker owns a new process group, including any Tesseract children.
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.poll() is None:
        process.kill()
    process.wait(timeout=5)


def _shutdown_workers():
    global _shutting_down
    with _workers_lock:
        _shutting_down = True
        workers = tuple(_active_workers.items())
    for process, directory in workers:
        try:
            _stop_worker(process)
        except (OSError, subprocess.TimeoutExpired):
            pass
        shutil.rmtree(directory, ignore_errors=True)


atexit.register(_shutdown_workers)


def _run_backend(engine: str, path: Path, *, timeout: float = OCR_TIMEOUT_SECONDS,
                 should_cancel=None) -> OcrResult:
    if should_cancel and should_cancel():
        raise OcrCancelled("OCR canceled")
    with tempfile.TemporaryDirectory(prefix="md-converter-ocr-") as directory:
        result_path = Path(directory) / "result.json"
        deadline = time.monotonic() + timeout
        with open(Path(directory) / "stderr.log", "w+") as diagnostics:
            with _workers_lock:
                if _shutting_down:
                    raise OcrCancelled("Application is closing")
                process = subprocess.Popen(
                    _worker_command(engine, path, result_path),
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=diagnostics,
                    start_new_session=(os.name == "posix"),
                )
                _active_workers[process] = directory
            try:
                while process.poll() is None:
                    if should_cancel and should_cancel():
                        raise OcrCancelled("OCR canceled")
                    if time.monotonic() >= deadline:
                        raise OcrTimeout(f"{engine} exceeded {timeout:g}s")
                    time.sleep(0.05)
                if should_cancel and should_cancel():
                    raise OcrCancelled("OCR canceled")
                if process.returncode != 0:
                    raise OcrBackendUnavailable(f"{engine} worker exited with code {process.returncode}")
                try:
                    payload = json.loads(result_path.read_text(encoding="utf-8"))
                    if payload.get("error"):
                        raise OcrBackendUnavailable(payload["error"])
                    text = payload["text"]
                    if not isinstance(text, str) or not text.strip():
                        raise ValueError("no text")
                    return OcrResult(text=text, engine=engine)
                except (OSError, ValueError, KeyError, AttributeError) as exc:
                    raise OcrBackendUnavailable(f"{engine} returned an invalid OCR result: {exc}") from exc
            finally:
                try:
                    _stop_worker(process)
                finally:
                    with _workers_lock:
                        _active_workers.pop(process, None)


def ocr_image(path: Path | str, *, should_cancel=None, session: OcrSession | None = None,
              on_status=None, timeout: float = OCR_TIMEOUT_SECONDS) -> OcrResult:
    session = session if session is not None else OcrSession()
    engines = ["tesseract"] if session.vision_timed_out else ["vision", "tesseract"]
    errors = []
    for engine in engines:
        try:
            return _run_backend(engine, Path(path), timeout=timeout, should_cancel=should_cancel)
        except OcrBackendUnavailable as exc:
            errors.append(f"{engine}: {exc}")
            if engine == "vision":
                if isinstance(exc, OcrTimeout):
                    session.vision_timed_out = True
                if on_status:
                    on_status(f"{exc}; trying Tesseract" +
                              (" (using Tesseract for the rest of this batch)" if session.vision_timed_out else ""))
    raise OcrBackendUnavailable("No local OCR backend available: " + "; ".join(errors))


def tesseract_executable() -> str:
    candidate = shutil.which("tesseract")
    if candidate:
        return candidate
    for candidate in ("/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"):
        if os.access(candidate, os.X_OK):
            return candidate
    raise OcrBackendUnavailable("Tesseract is not installed (brew install tesseract)")


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
    pytesseract.pytesseract.tesseract_cmd = tesseract_executable()

    def reader(image_path: Path) -> str:
        with Image.open(image_path) as image:
            return pytesseract.image_to_string(image, timeout=OCR_TIMEOUT_SECONDS)

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
            # Small screenshots benefit from enlargement; 2048px originals do not.
            scale = 2 if max(width, height) <= 1100 else 1
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
