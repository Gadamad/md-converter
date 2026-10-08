# MD Converter 0.3.0

Collect websites, files, folders and text now; convert them another day. Queues save automatically on your Mac and restore when the app reopens.

- **Inbox and named queues:** create, select and rename collections with compact controls that fit the existing interface.
- **Website collection:** drag browser links or `.webloc` shortcuts, or paste one URL per line and choose Add to queue. Websites are fetched only when conversion starts.
- **Recoverable mixed work:** each item retains its status, result and failure details. Convert queue processes waiting items; Retry failed processes unsuccessful items. Completed conversions are preserved, including when an export needs repair.
- **Reconnect missing files:** Locate file updates the source while retaining the queue entry.
- **Large queues:** paged rows and throttled screen updates keep the interface responsive while each result is saved immediately.
- **Continuity:** existing image-only recovery remains available. New image jobs retain shared Markdown exports and per-image checkpoints through the queue.

## Using saved queues

Choose Inbox or create a queue with New. Add sources, wait for the Saved indicator, then close the app whenever you like. Reopen it and choose Convert queue when ready. Stop & save leaves unfinished work waiting. The queue menu can clear completed entries; clearing entries does not remove original files or exported Markdown.

File entries reference their originals; folder contents are collected when added. Saved website links refer to the page available at conversion time, rather than a captured copy from the day the link was added. A run retains its original output and vault destinations when resumed.

Saved queues and export-recovery data are kept in `~/Library/Application Support/MD Converter/`. Back up that directory together with source files and output folders.

## Validation

All 265 automated tests pass. Coverage includes reopening, transaction rollback, separate application instances, interrupted workers, export receipts, image checkpoint reconciliation, missing-file relocation, URL parsing and browser UI behavior. An end-to-end local website test verifies no requests while collecting, restoration after restart, conversion and failed-only retry. Native Mac checks verified a named queue across application restart, website failure/retry, and successful PDF, DOCX, XLSX and TXT conversion. Tests also cover multi-sheet workbook export repair without duplication.

## Mac download

The ZIP contains the Apple silicon Mac app. This build is locally signed, not Developer ID signed or notarized. Tesseract remains a separate dependency for scanned PDFs and image OCR fallback (`brew install tesseract`). The local installer retains the previous app as a backup.
