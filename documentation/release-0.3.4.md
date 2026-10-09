# MD Converter 0.3.4

Choose **Include subfolders** beside **Add folder** before adding or dropping a folder:

- Checked: collect supported files throughout nested folders.
- Unchecked: collect only supported files directly in the selected folder.

The choice starts checked and is remembered across app restarts. Changing it leaves existing saved queue entries unchanged. Files picked individually are still collected wherever they are located. Adding the same folder again with subfolders enabled collects new nested sources without duplicating previously queued files.

Folder intake waits while the choice is saved. If saving fails, the checkbox returns to the previous saved choice and reports the error. Preferences saves preserve the choice, and conversion keeps intake controls disabled. Existing unreadable-folder and malformed-shortcut reporting remains available.

No new dependencies or database changes are required.

Validation: 300 tests and 14 subtests pass. Checks cover saved off/on choices across restarts, all folder intake entrypoints, overlapping additions, explicit nested file selection, save failure rollback, concurrent native drops and minimum-window browser layout. Five existing PyMuPDF deprecation warnings remain.

Native Mac verification collected one direct file with subfolders disabled, retained that choice and queue across a restart, then collected a deeply nested file with subfolders enabled. Previously queued files were not duplicated. The temporary test queue was removed, and existing user queues and items were verified unchanged.
