"""Internal OCR subprocess entry point; does not import or open the GUI."""
import json
from pathlib import Path
import sys
import tempfile

from image_ocr import _ocr_with_tesseract, _ocr_with_vision


def main(args=None) -> int:
    args = sys.argv[1:] if args is None else args
    if len(args) != 3 or args[0] not in {"vision", "tesseract"}:
        return 2
    engine, source, destination = args
    result_path = Path(destination)
    # The parent removes this directory even when native OCR must be killed.
    tempfile.tempdir = str(result_path.parent)
    try:
        reader = _ocr_with_vision if engine == "vision" else _ocr_with_tesseract
        result = reader(Path(source))
        payload = {"text": result.text, "engine": result.engine}
    except Exception as exc:
        payload = {"error": f"{type(exc).__name__}: {exc}"}
    result_path.write_text(json.dumps(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
