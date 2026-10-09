# MD Converter

Turn PDFs, DOCX files, XLSX workbooks, web pages, pasted text, TXT, and RTF into clean Markdown you can actually use.

`MD Converter` gives you two ways to work:

- A simple macOS app with drag-and-drop, paste, and one-click output folders.
- A command-line entry point for batch conversion and scripting.

Version 0.3.4 adds an **Include subfolders** choice beside **Add folder**, remembered across restarts and applied to both folder picking and folder drops. Unreadable folders are reported, and a broken website shortcut no longer blocks neighboring files. Collect websites, documents, folders and pasted text now, close the app, and convert another day. It retains named saved queues, visible queue deletion, supervised OCR, resumable image batches, streaming spreadsheets and the redesigned Mac interface. Build metadata records the Git revision and a source SHA-256 digest.

File conversion and OCR run locally on your Mac. Converting a website URL fetches that website; source documents and images are not uploaded to an OCR service.

## Why People Find It Useful

- Convert research, notes, reports, and articles into Markdown for Obsidian or plain files.
- OCR scanned PDFs locally with Tesseract.
- Keep outputs organized automatically by input type.
- Optionally copy finished Markdown into an Obsidian vault with frontmatter.

## What It Supports

| Input | What happens |
| --- | --- |
| JPG / PNG / WebP | Extracts quotes with local OCR; saves and resumes large image batches |
| PDF | Extracts selectable text, or falls back to OCR for scanned PDFs |
| DOCX | Preserves headings, bold, italics, lists, quotes, and tables |
| XLSX | Converts each workbook sheet into a separate Markdown table file |
| HTML / URL | Reads local HTML or fetches a URL and converts the main content to Markdown |
| TXT | Wraps plain text in a clean Markdown document |
| RTF | Converts RTF content into plain Markdown text |
| Pasted text | Saves pasted text directly as Markdown from the app |

## Quick Start For macOS Users

This is the fastest path if you just want the app.

```bash
git clone https://github.com/Gadamad/md-converter.git
cd md-converter
bash install.sh
```

What `install.sh` does:

1. Checks for Python 3.
2. Creates `.venv/`.
3. Installs Python dependencies.
4. Installs `pyinstaller`.
5. Checks whether `tesseract` is available for scanned PDFs.
6. Builds and verifies `MD Converter.app`, backs up an existing installation to `release-backups/`, and installs to `/Applications`. Close the running app before installing.

After that, open `MD Converter` from Launchpad, Spotlight, or Finder.

## Quick Start For CLI Users

If you prefer the terminal:

```bash
git clone https://github.com/Gadamad/md-converter.git
cd md-converter
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Convert one or more files:

```bash
python3 src/converter_app.py document.pdf report.docx notes.txt
```

Convert a workbook, writing one Markdown file per sheet:

```bash
python3 src/converter_app.py workbook.xlsx
```

Convert a URL:

```bash
python3 src/converter_app.py https://example.com/article
```

Output is written to `converted/` and grouped by type:

```text
converted/
  pdf/
  docx/
  spreadsheets/
  html/
  txt/
  rtf/
```

When you run the installed macOS app, converted output is written to a persistent user location instead of inside the app bundle:

```text
~/Documents/MD Converter/converted/
```

That means reinstalling the app no longer removes previous converted files.

## GUI Walkthrough

1. Use **Files & folders** to drop files, add files, or use **Add folder** for a folder containing any supported file types. Before adding or dropping a folder, choose **Include subfolders**: checked collects supported files throughout nested folders; unchecked collects only files directly in the selected folder. The app remembers this choice; changing it leaves existing queued items unchanged. Unsupported files are ignored. Unreadable subfolders and broken website shortcuts are reported with their full paths in **Activity**; readable sources continue to be collected.
2. Choose a name under **Saved queues** to reopen that queue immediately, or create one with **New**. Each addition is saved automatically. Selecting a queue does not start conversion.
3. Drag website links or `.webloc` shortcuts into the app, or select **Text or URL**, paste text or one website address per line, and click **Add to queue**. Adding a link does not fetch it; the website is read when conversion starts.
4. Click **Convert queue** to process waiting items. **Retry failed** processes unsuccessful items only. Successful items remain visible with their saved output paths; they are not converted again.
5. Use **Stop & save** to retain completed work and leave unfinished items for later. Reopen the app to find the same collection and statuses. Missing sources offer **Locate file**.
6. Use **Open output** to find your files. Preferences control appearance, destination, original image text and automatic opening of Finder.

Select a saved queue, then use **Delete queue…** beside **New** and **Rename** to remove its name and all its entries after confirmation. The same action remains under **Queue actions**. **Clear completed** removes only finished entries; **Clear all items** empties the queue while keeping its name. Original files, converted Markdown and other queues are kept. Deleting the last queue creates a fresh, empty Inbox. Queue deletion cannot be undone.

### Image recovery

Saved queues keep documents, links, text and images together in a local database, independent of the selected output folder. Conversion options are retained when work starts, so an interrupted run resumes into its original destination. Folder contents are collected when added; the queue does not watch for future folder changes. File entries reference the originals, so keep them available until conversion.

On a Mac installation, saved queues live in `~/Library/Application Support/MD Converter/queues.sqlite3`; `queue-cache` beside it retains completed conversion receipts for reliable export recovery. Back up that directory together with your original files and output folders. Development runs keep these files beside `preferences.json`. Removing queue entries does not delete original files or exported Markdown. Saving a link does not archive today's website content.

The controls below remain available for image batches created before saved queues. New image batches use the queue's Convert and Retry failed controls.

- Image results are saved after each file to Markdown and a neighboring `.progress.json` journal.
- If the app closes unexpectedly, **Resume** continues pending images. Submitting the same interrupted collection again resumes it automatically.
- **Retry failed** processes only unsuccessful images, preserving successful results and their order.
- **Finish export** repairs interrupted Markdown or vault delivery without repeating completed OCR.
- Missing original files do not erase text already saved. Changed images are reconverted; if replacement extraction fails, their previous text is retained in a clearly labeled section.
- Each OCR engine has a 30-second deadline. A Vision timeout switches the remainder of that batch to Tesseract. Unreadable images are reported and the batch continues.
- An operating-system lock protects journals from concurrent app instances. Resume updates the same Markdown and vault export.
- Recovery works for version 0.2.0 journals. Earlier versions did not retain the records needed for automatic resume. New independent batches receive unique output filenames.

### Preferences

The app keeps the main conversion screen focused and uses a small Preferences modal instead of a sidebar.

Current Preferences include:

- **Theme** — `System`, `Dark`, or `Light`
- **Raw OCR display**
  - `Show when different only` (recommended default)
  - `Always show`
  - `Never show`
- **Output directory** — use the default output location or choose a custom one
- **Auto-open output after export** — open the result folder automatically after successful exports

Preferences are stored persistently for the installed app at:

```text
~/Library/Application Support/MD Converter/preferences.json
```

Incomplete batches appear in the workspace for recovery. Completed batches remain in the output folder.

## Optional Obsidian Vault Delivery

If you want converted files copied into an Obsidian vault:

```bash
cp config.example.json config.json
```

Then edit `config.json`:

```json
{
  "vault_path": "~/Documents/My-Obsidian-Vault/Converted"
}
```

Notes:

- `config.json` is optional.
- `config.json` is git-ignored.
- If no `config.json` is present, conversion still works normally and vault copying stays disabled.

## What The Output Looks Like

Each converted file gets:

- A Markdown title.
- A metadata header with source information.
- Word count.
- Optional extra metadata such as page count or OCR timing, depending on the source.

If vault delivery is enabled, the copied version also gets YAML frontmatter for easier use in Obsidian.

XLSX workbook conversion creates one Markdown file per non-empty sheet. Formulas are read as the cached workbook values available in the file; the converter does not recalculate formulas.

Quote-image folder conversion creates one merged Markdown export per batch and includes:

- source image name for each extracted record
- detected author line when confidently separated
- quote body
- raw OCR text for traceability

## OCR And Privacy

- OCR uses local `tesseract`.
- Scanned PDF support depends on `tesseract` being installed.
- No document content is sent to a remote API by this project.

Install Tesseract on macOS with:

```bash
brew install tesseract
```

## Limits And Expectations

- The GUI and installer are currently macOS-focused.
- The app bundle build script is for macOS.
- OCR is slower than normal text extraction because each PDF page is rendered and processed locally.
- HTML conversion strips common layout noise such as `script`, `style`, `nav`, `header`, and `footer`, but some pages will still need cleanup depending on site structure.

## Troubleshooting

### The app installs but scanned PDFs do not work

Install Tesseract:

```bash
brew install tesseract
```

### I only want local output, not Obsidian copies

Do nothing. `config.json` is optional.

### The CLI says vault delivery is disabled

That is expected when `config.json` does not exist yet.

### A URL returns `429 Too Many Requests`

Some publishers reject generic script-style HTTP headers even when the page is public.

The current app now fetches URLs with browser-like headers, which fixes known cases like VentureBeat rejecting the older `MDConverter/1.0` request header.

It also now retries a small set of transient failures for URL fetches:

- `429 Too Many Requests`
- `500`, `502`, `503`, `504`
- temporary connection errors and timeouts

When a site sends a valid `Retry-After` header, the app uses it before retrying. Otherwise it falls back to a short exponential backoff.

If your installed app predates this fix, rebuild or reinstall it:

```bash
bash scripts/build_app.sh
```

Or run the full installer again:

```bash
bash install.sh
```

Real publisher-side throttling can still happen. If a site is genuinely rate-limiting traffic, wait and retry later.

### The app will not build

Re-run:

```bash
bash install.sh
```

Or build manually:

```bash
bash scripts/build_app.sh
```

## Development

Build the macOS app bundle:

```bash
bash scripts/build_app.sh
```

Run the complete regression suite:

```bash
python3 -B -m unittest discover -s tests
```

## Project Structure

```text
md-converter/
  src/
    converter_app.py   # GUI + CLI entry point
    converters.py      # Format conversion logic
    native_drop.py     # Native macOS drag-and-drop support
  scripts/
    build_app.sh       # PyInstaller app build
    generate_icon.py   # App icon generator
    launch.command     # Double-click launcher
  tests/
    test_cli_mode.py   # CLI regression test
  install.sh           # Main setup script
  config.example.json  # Optional vault config template
  requirements.txt     # Python dependencies
```

## Shareability Notes

This repo is set up to be shareable:

- Personal config is excluded via `config.json` in `.gitignore`.
- Generated outputs are excluded.
- Input/sample document folders used during local work are excluded.

That keeps the public repo focused on the tool itself rather than personal data.

## License

MIT. See `LICENSE`.

## Reliability and review notes

- Image OCR runs in disposable subprocesses. Timeouts and Abort terminate their process groups, including any Tesseract child.
- A failed image does not stop the remaining images; failed files and fallback notices appear in the progress report.
- Repeated exports use numbered filenames, preserving earlier exports and vault copies.
- Mixed PDFs OCR pages without selectable text when those pages contain image or vector content. OCR failures retain available text and are reported as partial exports.
- macOS builds show version 0.1.0 in their window title and store the revision/source hash in `Contents/Info.plist`.
- `constraints-macos-py314.txt` records the environment used for this release. To reproduce it in a compatible macOS ARM64 / Python 3.14 environment, install with `pip install -r requirements.txt -c constraints-macos-py314.txt`, and install the pinned PyInstaller version from that file for builds.

See [the code review and update recommendations](documentation/code-review-2026-10-08.md) for measured performance, remaining limitations, and recommended dependency updates.

## Verified release build

The tested macOS ARM64 / Python 3.14 dependency set is pinned in `constraints-macos-py314.txt`. To reproduce it in a separate environment:

```bash
python3 -m venv .venv-release
.venv-release/bin/python -m pip install -r requirements.txt pytest pyinstaller -c constraints-macos-py314.txt
.venv-release/bin/python -m pytest -q
MD_CONVERTER_VENV="$PWD/.venv-release" bash scripts/build_app.sh
.venv-release/bin/python scripts/install_app.py
```

The installer keeps the prior app in `release-backups/` and restores it if replacement fails. Use `--close-running` only when ready to discard unsaved work in a running older version. Build metadata records the version, source digest and Git revision.
