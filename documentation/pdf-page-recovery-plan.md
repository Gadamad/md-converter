# PDF page recovery

Approved scope: make queued PDF partial exports available with an explicit warning, retry only failed pages, recover the three pages from the existing failed attempt, preserve earlier conversions, and ship the verified macOS update.

- `pdf_recovery.convert_queued_pdf` persists page results and source identity privately. Good pages are never re-extracted on retry. Import the legacy cached partial only when it matches the PDF and reported failures; stop if cache/source cannot be verified. Render immutable Markdown snapshots in reading order and label incomplete exports with the outstanding pages.
- `pdf_page_ocr.recover_pdf_page` performs bounded, local OCR on failed pages with targeted image preparation. Keep uncertain or unreadable pages explicit; never synthesize missing text.
- Queue runner publishes each distinct snapshot as a separate Markdown file, preserving old files and user edits. Receipt tracks pending delivery independently of OCR. Delivery-only retry uses the saved snapshot, and OCR retry uses the same page checkpoint. Normal, extra and vault destinations remain frozen; optional-copy errors preserve the primary file. The saved queue retains its compatible failed state while the dashboard shows Partial and Open partial.
- Verify with failing-then-passing tests for new/legacy retries, cancellation, source changes, ownership/collisions, partial and complete delivery, and browser actions. Review the diff independently. Inspect Safari, test a packaged retry on the real three pages, retain the original PDF/cached export and verify existing output hashes and queue rows before release.

Completed: 758 tests and 62 subtests passed, independent review findings were fixed, Safari checked the affected row at both window sizes, and the installed app completed the targeted recovery. Its extra copy matched, and 29 protected files were unchanged.
