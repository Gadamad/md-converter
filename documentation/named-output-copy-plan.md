# Named output copy implementation plan

Approved behavior: a dashboard checkbox enables an extra copy of finished files in a user-named subfolder of the current Save to location. The app requests the folder name when enabling the option. Regular outputs remain saved.

Architecture: persist an optional copy_subfolder preference, freeze the resolved copy_dir in each new queue item's existing options, and deliver exact UTF-8 Markdown copies from saved outputs. Preserve existing format and workbook subfolders. Durable receipt/journal mappings reserve collision-safe filenames and let delivery retries reuse conversions. Existing completed entries and original files remain unchanged.

1. Test and add folder-name validation, immutable preference persistence, API busy guards, and a dashboard checkbox/name dialog/path preview. Cancel and failed saves preserve the previous choice; names allow Hungarian accents and reject separators and traversal. The existing minimum window size must remain usable.
2. Test and implement a focused output_copy module. Persist destination reservations before publishing; stream atomic copies; preserve existing unrelated or user-edited files; reuse known owned destinations after interrupted writes. Keep pending delivery state until all outputs reach the destination.
3. Test and integrate copy delivery into document/workbook receipts and image journals. A copy failure preserves primary output and extracted text. Retry repairs only delivery, and image recovery/skipping synchronizes the same copy with the final report. Capture the destination for the run rather than following later preference changes.
4. Review changes, run the full suite and real/native checks, preserve current user state, commit and release v0.3.7, verify the build metadata, install and restart. Keep personal files, queues and backup data outside Git.

Tests cover successful exact copies, multiple worksheet outputs, filename collisions, failed/partial delivery, retry without conversion/OCR, changed copied files, accent-safe names, cancellation, preferences rollback, UI alignment and old queue/journal compatibility.
