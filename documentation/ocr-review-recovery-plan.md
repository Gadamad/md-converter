# OCR review and recovery — approved 2026-10-12

The user approved all five recommendations: bounded recovery after a Vision timeout; clear no-text/timeout/engine distinctions with preview and skip; better Tesseract quote layouts; useful diagnostics and accurate retry progress; targeted recovery of 19 readable quote images while retaining 1,316 successful images.

## Contracts and safety

- Keep the 30-second per-backend deadline. Each new image can try Vision again; a timeout affects only that image. Preserve per-engine and per-variant outcomes instead of swallowing reader exceptions. Added Tesseract layouts require confidence so textured photographs are not accepted as quote text solely because segmentation produced noise.
- An empty, otherwise successful OCR result is distinct from an unavailable engine, timeout or processing error. Store structured diagnostics in image checkpoint records; keep legacy schema-2 journals readable.
- Keep the existing SQLite schema and four durable statuses. The API decorates empty-recognition failures as `review` for presentation; global failed-only retry excludes these review items. A single-item retry can explicitly attempt either a failure or review item, never a successful item.
- Add Preview, Try again and Skip controls plus an attention filter. Skip removes only an unsuccessful queue entry, keeps the source, and records a skipped flag in the shared image journal. Local reports and existing vault exports list skipped items separately. A failed export retains a durable repair marker and the queue entry. No successful record or exported quote is discarded.
- Count selected retry attempts independently of the full journal ordinal. Busy progress follows the current selection; idle progress retains full-queue completion semantics.
- Back up SQLite through its backup API and copy both quote outputs/journals before updating the installed app or live data. Retry the 19 visually reviewed quote sources only; mark the 21 reviewed non-quote photographs skipped. Compare all prior successful image records and completed queue rows before and after recovery.

## Implementation and verification

1. Add failing OCR tests; implement per-image Vision fallback, structured errors/diagnostics and bounded Tesseract text-block/sparse-text recovery in `image_ocr.py` and `ocr_worker.py`.
2. Add failing journal/runner tests; implement diagnostic records, no-text review, skip reporting, selected-ID retries and monotonic selected-attempt progress in `quote_checkpoint.py`, `converters.py` and `queue_runner.py`.
3. Add API tests; implement review decoration, source preview, explicit single-item retry and safe skip in `queue_api.py`; retain SQLite schema and saved successful rows.
4. Add browser checks; implement attention filtering and recovery controls in `app_ui.py`, preserving themes, minimum-window layout and keyboard access.
5. Review integration, run the full suite, verify real failed-image recovery with the frozen worker, and check text-free samples. Bump version, document final behavior, commit, build and install with backup. Recover the authorized live selection, verify successful results unchanged, publish source/tag/macOS package to GitHub, and restart the final installed app.
