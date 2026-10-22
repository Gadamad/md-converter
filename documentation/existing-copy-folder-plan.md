# Existing copy folder fix

The dashboard's extra-copy option must offer both the existing named subfolder flow and a native picker for an existing folder. Picking stages a choice; Use folder commits it. Cancel, Escape, picker cancellation and failed saves preserve the committed destination. Regular outputs remain saved.

Persist an additive optional `copy_existing_dir`, exclusive with `copy_subfolder`. Existing preferences retain their behavior. A queue freezes `copy_dir` and `copy_mode` (`subfolder` by default, `existing` for a selected root); image journals retain the same mode. Existing roots must be present during delivery and must never be recreated when unavailable. Preserve MD/TXT bytes, format/workbook subfolders, collision reservations, edited files and retries using saved conversions.

Reject malformed paths, overlapping primary output directories and later symbolic-link replacements. Metadata-only journal reads remain possible with an unavailable destination. The UI reuses the established dialog, native controls, tokens and aligned footer.

Verification: preference rollback/restart, picker staging/cancel, mode switching/disable, frozen queue options, missing volume recovery without reconversion or OCR, exact copies/user-edit preservation and old-journal compatibility. Run the existing suite, inspect the rendered dialog/footer in actual Safari at minimum and normal sizes, then verify native picking and persisted selection with disposable data. Preserve current app queues, preferences and successful conversions before installing/restarting the verified update.

Completed: 699 tests and 62 subtests passed, independent review findings were resolved, actual Safari and installed native picker/conversion/restart checks passed. Original queue rows, active selection and preferences were restored exactly; 25 existing outputs remain unchanged. Release 0.4.1 retains both folder options and the usual primary outputs.
