# MD Converter 0.2.1

**Add folder** now accepts folders containing any supported file types: PDF, DOCX, XLSX, HTML, TXT, RTF and quote images. It searches subfolders, skips unsupported extensions and avoids duplicate work when selected folders overlap or individual files are also queued. Folder rows display file counts, and the picker starts in Documents.

This release also includes the redesigned light/dark Mac interface, supervised OCR, saved image progress, resume, failed-only retry and streaming spreadsheet conversion introduced in 0.2.0. See [the detailed change report](release-0.2.0.md).

Validation: 150 automated tests passed. Coverage includes mixed folders, nested files, dropped folders, overlapping selections and actual DOCX/PDF/XLSX/TXT conversion into the expected Markdown outputs. The prior 405-image recovery verification remains documented in the 0.2.0 report.

## Download

`MD-Converter-0.2.1-macOS-arm64.zip` contains the Apple silicon Mac app. Unzip it and move MD Converter.app to Applications after closing any running copy. This build is locally signed, not Developer ID signed or notarized. Tesseract is a separate dependency for scanned PDFs and image OCR fallback (`brew install tesseract`).

The source is available in the repository at tag `v0.2.1`. Build metadata identifies the exact source digest and Git commit. The local installer retains a backup of the previous app.
