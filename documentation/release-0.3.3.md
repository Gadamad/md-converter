# MD Converter 0.3.3

Adding or dropping a parent folder collects supported files throughout its nested subfolders. This update fixes two scan failures:

- Unreadable subfolders are reported in Activity with their full paths. A partially unreadable folder is no longer incorrectly described as containing no supported files.
- A broken `.webloc` website shortcut is reported individually, while valid neighboring documents and shortcuts are still collected.

Deep-folder verification covers real TXT, DOCX and XLSX files, duplicate filenames in separate branches, overlapping parent/child additions, reopening the saved queue, and conversion to distinct outputs. Output continues to be grouped by file type; original folders are kept intact.

No new dependencies or database changes are required.

Validation: 280 tests and 4 subtests pass. Regression tests exercise actual directory permissions, a malformed shortcut beside valid files and links, and the full saved-queue conversion flow. Five existing PyMuPDF deprecation warnings remain.
