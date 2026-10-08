# Reliability review — 8 October 2026

## Implemented in version 0.1.0

The stalled app had completed 49 images and was blocked in Apple's Vision framework while recognizing an enlarged copy of image 50. The native call never returned, so neither fallback nor cooperative cancellation could run. This release moves OCR into supervised subprocesses. Each backend gets 30 seconds, including startup and preprocessing. Timeout or cancellation kills the owned process group; temporary files belong to the parent. A Vision timeout selects Tesseract for subsequent images in that batch. App shutdown also cleans up active workers.

Successful image results are saved before the next image starts. Each batch produces an atomic Markdown checkpoint and a `.progress.json` report containing current status, processed count, failed paths, and fallback notices. Bad images are reported and skipped, as requested. The progress label changes before starting an image. Staged queues are cleared before launching the worker, and job reservation prevents simultaneous jobs. Failure paths release the job guard rather than leaving the app permanently busy.

Other verified defects repaired:

| Problem | New behavior |
| --- | --- |
| Same-title inputs overwrote earlier exports and vault copies | Output names are reserved exclusively and numbered on collision |
| Mixed PDFs silently omitted scanned pages | Pages without selectable text are OCR'd when they contain image/vector content; errors produce a partial result with page-level explanations |
| PDF OCR had no deadline | Uses the same supervised Tesseract worker, with cancellation passed from the GUI |
| DOCX hyperlink text disappeared | Hyperlink runs are read in document order |
| DOCX paragraphs/tables were searched repeatedly | Each XML block is wrapped once, avoiding quadratic traversal |
| Pipes in DOCX table cells broke Markdown columns | Literal pipes are escaped |
| HTTP Retry-After could sleep for a day or accept infinity | Retry delays are finite and capped at eight seconds |
| A malformed output-directory preference could prevent startup | Invalid values fall back safely; preference writes are atomic |
| Paste/URL failures were labelled Done | Failures have a failed summary |
| Finder launch could fail to find Homebrew Tesseract | Standard Homebrew executable locations are resolved explicitly |
| Installed builds identified themselves only as 0.0.0 | Version 0.1.0, Git revision, source digest, and build timestamp are recorded |

## Verification and measured performance

- 119 unit and regression tests passed. New cases cover real sleeping/crashed subprocesses, cancellation, normal app-exit cleanup, fallback selection, checkpoints, bad images, job reservation, mixed PDFs, output collisions, DOCX content, and malformed settings.
- The original troublesome image completed through the source pipeline after Vision's 30-second timeout: total 31.00 seconds. The following image used Tesseract directly and completed in 1.14 seconds.
- The built macOS application's actual OCR workers converted those two images in 3.33 seconds in a fresh run; both completed successfully, with a completed progress report. This test used a minimal Finder-like PATH. Native Vision behavior can vary between runs, which is why process isolation remains necessary.
- Canceling a running packaged OCR worker returned in 0.54 seconds.
- A 1,000-paragraph DOCX, median of three runs on this machine: baseline 0.574 seconds; updated 0.217 seconds (approximately 2.6 times faster). This measures the same input under both versions, including export writing.
- Existing 2048-pixel images are no longer enlarged to 4096 pixels. This removes two unnecessary OCR variants and avoids their fourfold pixel count.
- The 92 MB macOS bundle built successfully, passed deep/strict ad-hoc signature verification, opened its native window, and closed cleanly. The original installed app was left running.
- Dependency consistency check (`pip check`) passed. The tested environment is recorded in `constraints-macos-py314.txt`.

The entire 406-item batch has not been rerun. These checks cover the original failing image, the next image, deliberately blocked workers, and regression cases. They do not promise that every image will be recognized correctly or that every operating-system failure is recoverable.

## Recommended next improvements

1. **Resume and retry controls.** Checkpoints preserve work, but automatic resume and a “retry failed images” action are not implemented. Add source fingerprints so changed files cannot accidentally reuse old OCR results.
2. **Persistent vault configuration and safer installation.** The app still reads vault configuration relative to the bundle/source directory; the installer does not migrate it into Application Support. Move it to a persistent user location and migrate explicitly. The current installer also forcibly quits/replaces the installed app; add backup-and-rollback installation before wider distribution.
3. **Stream large spreadsheets.** Read-only openpyxl currently feeds fully materialized row lists. Stream rows and delay emitting trailing empty rows, with limits for formatting-inflated sheet dimensions.
4. **Improve staging validation.** The reported 406 items include 405 images and an existing Markdown file. `.md` is not a conversion input in the current router. Report unsupported items during staging, instead of waiting until conversion.
5. **Reduce OCR work with quality measurements.** Current OCR still evaluates several image variants. Benchmark a representative corpus before introducing confidence-based early exits, a selectable language, or limited Tesseract concurrency. Keep Vision isolated; adding threads does not solve the native hang.
6. **PDF layout fidelity.** Per-page OCR now prevents omission of fully scanned pages. A page containing both selectable text and a separate scanned region still needs region-aware handling. Complex columns/tables need additional fixtures before changing extraction strategies.
7. **Release automation.** Run the regression suite and a packaged worker smoke test on macOS for each release. Keep a tested dependency constraints file and source digest with each artifact. A future worker crash from an abrupt OS kill may leave an interrupted `running` checkpoint, which should be offered for recovery at startup.

## Dependency update candidates

Checked against primary PyPI project pages on 8 October 2026. These are suggested update trials, not changes installed during this repair. Test the source suite and packaged OCR after each group of upgrades; none is established as a fix for the native Vision stall.

| Component | Installed/tested | Published version checked | Recommendation |
| --- | --- | --- | --- |
| PyObjC core / Vision | 12.2.1 | [12.2.2](https://pypi.org/project/pyobjc-core/) / [Vision 12.2.2](https://pypi.org/project/pyobjc-framework-Vision/) | Test all used PyObjC framework bindings together; some installed bindings are still 12.1 |
| PyInstaller | 6.19.0 | [6.22.3](https://pypi.org/project/pyinstaller/) | Rebuild in an isolated environment; verify worker dispatch, signing, and packaged resources |
| PyMuPDF | 1.27.2.2 | [1.28.2](https://pypi.org/project/pymupdf/) | Test mixed/scanned PDFs and layout extraction against saved fixtures |
| Pillow | 12.2.0 | [12.3.0](https://pypi.org/project/pillow/) | Test image loading and OCR preprocessing across all supported formats |
| pywebview | 6.2.1 | [6.2.1](https://pypi.org/project/pywebview/) | No newer release identified in this check |
| python-docx | 1.2.0 | [1.2.0](https://pypi.org/project/python-docx/) | No newer release identified in this check |
| pytesseract | 0.3.13 | [0.3.13](https://pypi.org/project/pytesseract/) | No newer release identified in this check; the external Tesseract executable is a separate dependency |

Lower-bound-only requirements do not make reproducible builds. Also, rerunning the current installer does not upgrade dependencies that already satisfy those bounds. Use the tested constraints snapshot for this release; review and refresh it deliberately for a dependency update.
