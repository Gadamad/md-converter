# MD Converter 0.4.2

Incomplete PDF conversions now save their Markdown in the regular output folder with a warning and the unresolved page numbers. **Open partial** on the queue row opens the saved text. **Try again** or **Retry failed** uses the saved page results and runs targeted local OCR only on unresolved pages. New snapshots save separately, preserving earlier exports and edits.

The update can recover existing v0.4.1 PDF attempts when their cached Markdown matches the saved source and failure list. Page checkpoints verify the source before continuing. If optional delivery fails, the app can finish copying the saved snapshot without repeating OCR. No database migration or new dependency is required.

An isolated test recovered all three unresolved illustration pages of a 235-page PDF. Exactly those three pages were retried, all 231 saved page sections matched the previous export, and regular, extra-folder and Obsidian delivery passed.

Validation: 758 tests and 62 subtests passed. Independent review and regression tests checked cache containment, snapshot and receipt integrity, and preservation of edited legacy exports. The partial row and actions were checked in actual Safari at 640 × 640 in dark appearance and 820 × 780 in light appearance with an isolated local preview. Five existing PyMuPDF deprecation warnings remain.
