"""Internal OCR subprocess entry point; does not import or open the GUI."""
import json
from pathlib import Path
import sys
import tempfile
import time

from image_ocr import _failure_detail, _ocr_with_tesseract, _ocr_with_vision


def main(args=None) -> int:
    args = sys.argv[1:] if args is None else args
    if len(args) != 3 or args[0] not in {"vision", "tesseract"}:
        return 2
    engine, source, destination = args
    result_path = Path(destination)
    # The parent removes this directory even when native OCR must be killed.
    tempfile.tempdir = str(result_path.parent)
    started = time.monotonic()

    def write_payload(payload):
        temporary = result_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(result_path)

    def publish_diagnostics(details):
        # A hard-killed native reader cannot serialize its own exception. Keep
        # completed attempts and the current variant available to the watchdog.
        write_payload({"engine": engine, "diagnostics": details})

    try:
        context = []
        if result_path.exists():
            context = json.loads(result_path.read_text(encoding="utf-8")).get("quality_context", [])
            if not isinstance(context, list) or not all(isinstance(detail, dict) for detail in context):
                raise ValueError("Invalid OCR quality context")
        reader = _ocr_with_vision if engine == "vision" else _ocr_with_tesseract
        result = reader(Path(source), on_diagnostics=publish_diagnostics, quality_context=context)
        payload = {"text": result.text, "engine": result.engine, "diagnostics": result.diagnostics}
    except Exception as exc:
        details = getattr(exc, "diagnostics", None) or [
            _failure_detail(engine, "backend", started, "error", exc)]
        payload = {"error": str(exc),
                   "code": getattr(exc, "code", "processing_error"),
                   "error_type": type(exc).__name__, "diagnostics": details}
    write_payload(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
