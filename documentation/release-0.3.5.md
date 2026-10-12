# MD Converter 0.3.5

Image OCR now gives every image a fresh Vision attempt. A timed-out image falls back to Tesseract without disabling Vision for the rest of the batch, and both engines retain their 30-second deadlines. Tesseract tries text-block and sparse-text layouts after empty recognition, alongside contrast and enlargement variants. Added layouts require sufficient word confidence, helping reject photo texture while retaining short, confidently recognized text.

Empty recognition is reported as **Needs review**, separately from timeouts, unavailable engines and processing errors. The **Needs attention** filter finds unresolved entries. **Preview** opens the original in Quick Look; **Try again** retries that entry; **Skip** keeps the source, removes the unsuccessful queue entry and records the skipped image in its batch report and existing Obsidian exports. A failed report write retains the queue entry for repair. Successful entries and any previously saved quote text are protected from this skip action.

Retry progress now counts the selected attempts instead of their positions in the original batch. Image journals retain per-engine and per-variant diagnostics, including errors and elapsed time. Existing queues and journals remain compatible; no dependencies or database migration are required.

Successful image records are reused when retrying or repairing an export. Regression checks cover backend deadlines and cancellation, subsequent Vision attempts, OCR classifications, selected-item progress, skip/report recovery after partial write failures, successful-result preservation and minimum-window browser behavior.

Validation: 394 tests and 14 subtests pass. Five existing PyMuPDF deprecation warnings remain. Real-image checks recovered a previously timed-out quote using Vision and correctly rejected texture in a text-free snow photograph; the added Tesseract layouts retain confidence diagnostics for rejected candidates.
