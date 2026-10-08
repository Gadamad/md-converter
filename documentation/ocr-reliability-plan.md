# OCR batch reliability — 2026-10-08

## Scope and design

The approved repair addresses a live Vision OCR call that never returned. A thread timeout cannot stop native code, so each OCR backend runs in an owned subprocess, with a 30-second deadline including startup and preprocessing. The parent polls cancellation, kills the worker process group on timeout/cancellation, and owns temporary files. The packaged executable dispatches its internal worker before loading the GUI. Tesseract receives an explicit executable path, including standard Homebrew locations.

Vision remains the preferred engine. After its first timeout in a batch, the remaining images use Tesseract rather than repeatedly paying the timeout. Individual OCR failures are reported and the batch continues by default. Every completed image updates an atomic Markdown checkpoint and a JSON progress report; errors and cancellation preserve partial output. The displayed filename changes before OCR starts. No automatic installation or termination of the existing hung app is part of implementation.

The alternatives considered were a thread timeout (cannot stop the native hang) and replacing Vision entirely with Tesseract (changes output quality unnecessarily). A supervised process retains both engines with a bounded failure path.

## Implementation and verification

- [x] Add regression tests for genuine blocked/crashed workers, cancellation, fallback, process cleanup, and source/frozen worker command routing.
- [x] Implement subprocess supervision in `src/image_ocr.py` and a small `src/ocr_worker.py` entry point. Keep native imports inside the child.
- [x] Test and implement per-image failure handling, atomic checkpoints, in-flight progress, and preservation of earlier results.
- [x] Test and repair job-start races, failure cleanup, and misleading completion messages in `src/converter_app.py`.
- [x] Reduce unnecessary image enlargement, explicitly resolve Tesseract, and review other modules for concrete errors.
- [x] Run the complete regression suite; run the originally troublesome image through the source and packaged app paths. Exercise timeout and cancellation with deliberately stalled processes.
- [x] Build a separate app bundle, verify packaging, review the diff, and commit changes on `codex/ocr-batch-reliability`.
- [x] Record measured results, remaining limitations, and independently verified dependency update recommendations.

## Acceptance criteria

An OCR hang must release the job through fallback, a visible per-image failure, or cancellation. Completed images must already be on disk before the next image starts. A failed image must never be counted as a successful conversion. Only one conversion job may start at a time. Unexpected worker/UI/output errors must release the job guard. The installed legacy app and original images remain untouched while the new build is verified.
