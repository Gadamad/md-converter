from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import atexit
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time


class OcrError(RuntimeError):
    code = "processing_error"

    def __init__(self, message="OCR failed", diagnostics=None):
        super().__init__(message)
        self.diagnostics = list(diagnostics or [])


class OcrBackendUnavailable(OcrError):
    code = "unavailable"


class OcrTimeout(OcrBackendUnavailable):
    code = "timeout"


class OcrProcessingError(OcrBackendUnavailable):
    code = "processing_error"


class OcrNoTextDetected(OcrError):
    code = "no_text"

    def __init__(self, message="No text detected.", diagnostics=None):
        super().__init__(message, diagnostics)


class OcrCancelled(RuntimeError):
    pass


@dataclass
class OcrSession:
    # Retained for callers using the old session API; failures are image-local.
    vision_timed_out: bool = False


@dataclass(frozen=True)
class OcrResult:
    text: str
    engine: str
    diagnostics: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class _ReaderResult:
    text: str
    details: dict


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


def _payload_diagnostics(payload) -> list[dict]:
    details = payload.get("diagnostics", []) if isinstance(payload, dict) else []
    return [detail for detail in details if isinstance(detail, dict)] if isinstance(details, list) else []


def _last_worker_diagnostics(result_path: Path) -> list[dict]:
    try:
        return _payload_diagnostics(json.loads(result_path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []


def _failure_detail(engine, variant, started, status, exc=None, **extra):
    detail = {"engine": engine, "variant": variant, "status": status,
              "elapsed_seconds": round(max(0.0, time.monotonic() - started), 6), **extra}
    if exc is not None:
        detail.update(error_type=type(exc).__name__, error=str(exc))
    return detail


def _run_backend(engine: str, path: Path, *, timeout: float = OCR_TIMEOUT_SECONDS,
                 should_cancel=None) -> OcrResult:
    if should_cancel and should_cancel():
        raise OcrCancelled("OCR canceled")
    with tempfile.TemporaryDirectory(prefix="md-converter-ocr-") as directory:
        result_path = Path(directory) / "result.json"
        started = time.monotonic()
        deadline = started + timeout
        with open(Path(directory) / "stderr.log", "w+") as stderr:
            with _workers_lock:
                if _shutting_down:
                    raise OcrCancelled("Application is closing")
                try:
                    process = subprocess.Popen(
                        _worker_command(engine, path, result_path),
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=stderr,
                        start_new_session=(os.name == "posix"),
                    )
                except OSError as exc:
                    details = [_failure_detail(engine, "backend", started, "error", exc)]
                    raise OcrBackendUnavailable(f"{engine} worker could not start: {exc}", details) from exc
                _active_workers[process] = directory
            try:
                while process.poll() is None:
                    if should_cancel and should_cancel():
                        raise OcrCancelled("OCR canceled")
                    if time.monotonic() >= deadline:
                        details = _last_worker_diagnostics(result_path)
                        details.append(_failure_detail(engine, "backend", started, "timeout"))
                        raise OcrTimeout(f"{engine} exceeded {timeout:g}s", details)
                    time.sleep(0.05)
                if should_cancel and should_cancel():
                    raise OcrCancelled("OCR canceled")
                if process.returncode != 0:
                    details = _last_worker_diagnostics(result_path)
                    stderr.seek(0)
                    details.append(_failure_detail(engine, "backend", started, "error",
                                                   returncode=process.returncode, stderr=stderr.read(4096)))
                    raise OcrProcessingError(f"{engine} worker exited with code {process.returncode}", details)
                try:
                    payload = json.loads(result_path.read_text(encoding="utf-8"))
                    details = _payload_diagnostics(payload)
                    if payload.get("error"):
                        error_type = {"no_text": OcrNoTextDetected, "timeout": OcrTimeout,
                                      "processing_error": OcrProcessingError,
                                      "unavailable": OcrBackendUnavailable}.get(payload.get("code"), OcrBackendUnavailable)
                        raise error_type(str(payload["error"]), details)
                    text = payload["text"]
                    if not isinstance(text, str) or not text.strip():
                        raise ValueError("no text")
                    return OcrResult(text=text, engine=engine, diagnostics=details)
                except (OSError, ValueError, KeyError, AttributeError, TypeError) as exc:
                    details = _last_worker_diagnostics(result_path)
                    details.append(_failure_detail(engine, "backend", started, "error", exc))
                    raise OcrProcessingError(f"{engine} returned an invalid OCR result: {exc}", details) from exc
            finally:
                try:
                    _stop_worker(process)
                finally:
                    with _workers_lock:
                        _active_workers.pop(process, None)


def ocr_image(path: Path | str, *, should_cancel=None, session: OcrSession | None = None,
              on_status=None, timeout: float = OCR_TIMEOUT_SECONDS) -> OcrResult:
    if session is not None:
        session.vision_timed_out = False
    errors = []
    diagnostics = []
    for engine in ("vision", "tesseract"):
        try:
            result = _run_backend(engine, Path(path), timeout=timeout, should_cancel=should_cancel)
            return OcrResult(result.text, result.engine, diagnostics + result.diagnostics)
        except OcrError as exc:
            errors.append((engine, exc))
            diagnostics.extend(exc.diagnostics)
            if engine == "vision":
                if on_status:
                    on_status(f"{exc}; trying Tesseract")
    if all(isinstance(exc, OcrNoTextDetected) for _, exc in errors):
        raise OcrNoTextDetected(diagnostics=diagnostics)
    failure_type = OcrBackendUnavailable
    if any(isinstance(exc, OcrTimeout) for _, exc in errors):
        failure_type = OcrTimeout
    elif any(isinstance(exc, OcrProcessingError) for _, exc in errors):
        failure_type = OcrProcessingError
    prefix = "OCR failed"
    if failure_type is OcrBackendUnavailable:
        prefix = ("OCR backend unavailable" if any(isinstance(exc, OcrNoTextDetected) for _, exc in errors)
                  else "No local OCR backend available")
    raise failure_type(prefix + ": " + "; ".join(f"{engine}: {exc}" for engine, exc in errors), diagnostics)


def tesseract_executable() -> str:
    candidate = shutil.which("tesseract")
    if candidate:
        return candidate
    for candidate in ("/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"):
        if os.access(candidate, os.X_OK):
            return candidate
    raise OcrBackendUnavailable("Tesseract is not installed (brew install tesseract)")


def _ocr_with_vision(path: Path, *, on_diagnostics=None, deadline=None) -> OcrResult:
    try:
        from Foundation import NSURL
        import Vision
    except ImportError as exc:
        raise OcrBackendUnavailable("Vision framework is not installed") from exc

    def reader(image_path: Path, config: str, remaining: float) -> str:
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
            raise OcrProcessingError(message)

        observations = request.results() or []
        lines: list[str] = []
        for observation in observations:
            candidates = observation.topCandidates_(1)
            if candidates:
                candidate_text = candidates[0].string().strip()
                if candidate_text:
                    lines.append(candidate_text)
        return "\n".join(lines)

    return _best_text_from_variants(path, reader, engine="vision", deadline=deadline,
                                    on_diagnostics=on_diagnostics)


def _ocr_with_tesseract(path: Path, *, on_diagnostics=None, deadline=None) -> OcrResult:
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise OcrBackendUnavailable("pytesseract or Pillow is not installed") from exc
    pytesseract.pytesseract.tesseract_cmd = tesseract_executable()

    def reader(image_path: Path, config: str, remaining: float) -> str | _ReaderResult:
        with Image.open(image_path) as image:
            try:
                if config:
                    data = pytesseract.image_to_data(image, config=config, timeout=remaining,
                                                    output_type=pytesseract.Output.DICT)
                    return _text_from_recovery_data(data)
                return pytesseract.image_to_string(image, config=config, timeout=remaining)
            except RuntimeError as exc:
                # pytesseract uses RuntimeError for its subprocess deadline.
                if "Tesseract process timeout" in str(exc):
                    raise OcrTimeout(str(exc)) from exc
                raise

    return _best_text_from_variants(path, reader, engine="tesseract", deadline=deadline,
                                    configs=("", "--psm 6", "--psm 11"),
                                    on_diagnostics=on_diagnostics)


def _text_from_recovery_data(data: dict) -> _ReaderResult:
    """Require confidence for added layouts, which can see text in photo texture."""
    words = []
    for index, word in enumerate(data["text"]):
        word = word.strip()
        if not word:
            continue
        confidence = float(data["conf"][index])
        if not math.isfinite(confidence) or not -1 <= confidence <= 100:
            raise ValueError("Tesseract returned invalid word confidence")
        line = tuple(data[key][index] for key in ("block_num", "par_num", "line_num"))
        words.append((word, confidence, line))
    parts = []
    previous_line = None
    for word, _, line in words:
        if previous_line is not None:
            parts.append(" " if line == previous_line else "\n" if line[:2] == previous_line[:2] else "\n\n")
        parts.append(word)
        previous_line = line
    text = "".join(parts)
    # Punctuation confidence cannot make a low-confidence letter look reliable.
    weighted_words = [(sum(character.isalnum() for character in word), confidence)
                      for word, confidence, _ in words]
    weight = sum(length for length, _ in weighted_words)
    mean = sum(length * confidence for length, confidence in weighted_words) / weight if weight else 0.0
    accepted = bool(weight and mean >= 70)
    details = {"confidence_mean": round(mean, 2), "confidence_threshold": 70,
               "confidence_accepted": accepted, "candidate_characters": len(text)}
    if text and not accepted:
        details["rejection_reason"] = "low_confidence" if weight else "no_alphanumeric_text"
    return _ReaderResult(text if accepted else "", details)


def _looks_readable(text: str) -> bool:
    words = re.findall(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*", text, re.UNICODE)
    return len(words) >= 3 and sum(map(len, words)) >= 12


def _best_text_from_variants(path: Path, reader, *, engine: str, configs=("",),
                             deadline=None, on_diagnostics=None) -> OcrResult:
    started = time.monotonic()
    deadline = started + OCR_TIMEOUT_SECONDS if deadline is None else deadline
    diagnostics = []
    candidate_texts: list[str] = []
    failures = []

    def publish():
        if on_diagnostics:
            on_diagnostics([dict(detail) for detail in diagnostics])

    variants = _iter_variant_paths(path)
    try:
        for index, candidate_path in enumerate(variants):
            variant = "original" if index == 0 else candidate_path.stem
            for config in configs:
                attempt_started = time.monotonic()
                remaining = min(OCR_TIMEOUT_SECONDS, deadline - attempt_started)
                extra = {"config": config} if engine == "tesseract" else {}
                if remaining <= 0:
                    diagnostics.append(_failure_detail(engine, variant, started, "timeout", **extra))
                    publish()
                    raise OcrTimeout(f"{engine} exceeded its OCR deadline", diagnostics)
                diagnostics.append(_failure_detail(engine, variant, attempt_started, "running", **extra))
                publish()
                try:
                    read_result = reader(candidate_path, config, remaining)
                    if isinstance(read_result, _ReaderResult):
                        extra.update(read_result.details)
                        text = _normalize_text(read_result.text)
                    else:
                        text = _normalize_text(read_result)
                except Exception as exc:
                    status = "timeout" if isinstance(exc, OcrTimeout) else "error"
                    # Preserve the originating exception even when it is wrapped for classification.
                    original_error = exc.__cause__ if isinstance(exc, OcrTimeout) and exc.__cause__ else exc
                    diagnostics[-1] = _failure_detail(engine, variant, attempt_started, status, original_error, **extra)
                    publish()
                    if isinstance(exc, OcrTimeout):
                        raise OcrTimeout(str(exc), diagnostics) from exc
                    failures.append(exc)
                    continue
                diagnostics[-1] = _failure_detail(engine, variant, attempt_started,
                                                  "text" if text else "no_text", **extra)
                publish()
                if text:
                    candidate_texts.append(text)
                    if extra.get("confidence_accepted") or _looks_readable(text):
                        return OcrResult(text, engine, diagnostics)
                    # Alternative segmentation modes recover empty default results.
                    # Weak nonempty text is compared with the remaining image variants.
                    break
    except OcrTimeout:
        raise
    except Exception as exc:
        failures.append(exc)
        diagnostics.append(_failure_detail(engine, "preprocessing", started, "error", exc))
        publish()
    finally:
        variants.close()
    if not candidate_texts:
        if failures:
            raise OcrProcessingError(f"{engine} could not process the image: " +
                                     "; ".join(dict.fromkeys(str(exc) for exc in failures)), diagnostics)
        raise OcrNoTextDetected(f"{engine} returned no text", diagnostics)
    return OcrResult(max(candidate_texts, key=_score_text), engine, diagnostics)


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
