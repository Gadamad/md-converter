# Recovery, performance and interface release

1. Add versioned image checkpoints containing the input manifest, source fingerprints, extracted records and per-image outcomes. Resume the same interrupted batch automatically when it is submitted again. Surface recovery on launch. Retry only failed images on request, retaining saved results and the same output path.
2. Stream spreadsheet rows through a temporary spool to Markdown, keeping memory independent of worksheet row count and ignoring inaccurate sheet dimensions.
3. Replace the crowded interface with an aligned native Mac layout, clear source/queue/activity states, accessible preferences and recovery actions.
4. Upgrade Pillow, PyMuPDF, PyInstaller and the complete installed PyObjC family in an isolated environment; record the tested dependency set.
5. Test cancellation, interruption, source changes, retry, real OCR, output streaming and both themes. Build and verify the signed app, commit the release, back up the existing installation, replace it and launch the new version.

The original stuck app predates checkpoints, so its 49 in-memory results cannot be resumed. Original input files remain available. New checkpoints are authoritative; Markdown can be regenerated from them after interruption. No software can promise that every future failure is impossible; bounded OCR workers and persisted outcomes prevent the observed native OCR stall from blocking an entire batch indefinitely.
