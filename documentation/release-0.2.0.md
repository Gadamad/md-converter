# MD Converter 0.2.0 — recovery and interface release

The app now groups source selection, queue review, conversion and results into a consistent Mac interface. Files/folders and pasted text/URLs have separate source tabs. Queue and activity share one workspace. Controls have aligned sizes, keyboard focus, clear disabled states and light/dark appearances. The main action stays in one place; image processing exposes Stop & save.

## Reliability

- OCR workers remain isolated and bounded to 30 seconds per engine. A Vision timeout switches the remainder of the batch to Tesseract. Failed images do not prevent later files from converting.
- Versioned journals save absolute source paths, fingerprints, extracted text and outcomes after each image. Reopening the same interrupted collection automatically resumes saved work; the interface also offers Resume.
- Retry failed reads only unsuccessful images. Changed source files are reconverted; missing originals do not erase previously saved results. Failed replacements retain old text in a clearly identified section.
- Interrupted Markdown and Obsidian delivery can be finished without repeating OCR. A file lock prevents two processes from overwriting a batch. Corrupt/older reports are ignored instead of blocking new work.
- The installer verifies the new bundle and backs up the installed app before replacement. Failed replacement restores the old installation. Existing output folders are not part of the replaced bundle.

## Performance and dependencies

Spreadsheet conversion now spools rows and writes Markdown incrementally. The 6,000-row memory regression fixture measured about 1.57 MB peak Python allocation versus 20.7 MB previously. Memory still depends on row width and openpyxl’s workbook metadata/shared strings; this does not claim constant memory for every XLSX file.

The release uses an isolated Python 3.14 environment, with the tested package versions recorded in `constraints-macos-py314.txt`. Notable updates:

| Component | Previous | Tested release |
| --- | --- | --- |
| Pillow | 12.2.0 | 12.3.0 |
| PyMuPDF | 1.27.2.2 | 1.28.2 |
| PyInstaller | 6.19.0 | 6.22.3 |
| Installed PyObjC frameworks | mixed 12.1 / 12.2.1 | all 12.2.2 |
| requests | 2.33.1 | 2.34.2 |
| Beautiful Soup | 4.14.3 | 4.15.0 |
| markdownify | 1.2.2 | 1.2.3 |
| striprtf | 0.0.29 | 0.0.33 |

Package metadata was checked against [Pillow](https://pypi.org/project/Pillow/), [PyMuPDF](https://pypi.org/project/PyMuPDF/), [PyInstaller](https://pypi.org/project/pyinstaller/) and [PyObjC](https://pypi.org/project/pyobjc-core/); actual installed versions are pinned in the constraints file. The PyMuPDF import now uses its supported `pymupdf` name.

## Validation

- 146 automated tests passed, including failure/cancellation, resume, changed and missing sources, concurrent recovery, interrupted exports, streaming XLSX and installer rollback.
- Dependency consistency check passed; Python compilation, shell syntax and Git whitespace checks passed.
- Browser checks covered both themes, a 640 × 612 content viewport, queue rendering, text conversion controls, disabled states, preference cancellation and safe filename rendering.
- Native packaged Mac app checks covered the folder picker, actual pasted-text export, one bad image followed by a good image, and successful failed-only retry into the same export. Test output preferences were restored afterward.
- The original 405-image collection completed with packaged OCR workers. A deliberate process interruption after 208 images preserved the journal; resubmission continued without repeating completed OCR. The initial pass saved 403 images and reported two failures. Retrying those two with normal macOS OCR access completed all **405/405**, with **9,319 extracted quote words** and no remaining failures. The single export is saved locally under `converted/v0.2-validation/`. The resumed segment took 242 seconds; failed-only retry took 2.87 seconds.
- The final signed bundle's source SHA-256 matches the workspace source. The installed bundle will carry the committed Git revision.

## Further product improvements

1. Bundle Tesseract and its language data so a customer does not need a separate Homebrew installation; add an OCR language selector.
2. Add Developer ID signing/notarization and a tested update/rollback channel for distribution.
3. Add a native vault-folder picker and a visual preview for reviewing uncertain OCR before delivery. The existing vault integration still uses configuration.

OCR can misread or miss text; the release prevents the observed indefinite native OCR stall from blocking the entire image queue, and makes failed work recoverable. It cannot guarantee that no future failure will ever occur. Resume applies to version 0.2.0 image batches; the original stalled app did not save enough state to resume its first 49 results.
