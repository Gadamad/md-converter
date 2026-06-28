# MD Converter

Turn PDFs, DOCX files, XLSX workbooks, web pages, pasted text, TXT, and RTF into clean Markdown you can actually use.

`MD Converter` gives you two ways to work:

- A simple macOS app with drag-and-drop, paste, and one-click output folders.
- A command-line entry point for batch conversion and scripting.

Everything runs locally on your machine. No API calls, no cloud upload, no hidden service dependency.

## Why People Find It Useful

- Convert research, notes, reports, and articles into Markdown for Obsidian or plain files.
- OCR scanned PDFs locally with Tesseract.
- Keep outputs organized automatically by input type.
- Optionally copy finished Markdown into an Obsidian vault with frontmatter.

## What It Supports

| Input | What happens |
| --- | --- |
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
6. Builds `MD Converter.app` and copies it to `/Applications`.

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

The app is designed for non-technical use:

1. Drop files onto the window, or click to browse.
2. Use `Select Folder` to stage one quote-image folder and replace any previously staged quote folders.
3. Use `Add Folder` to append another quote-image folder to the current queue.
4. Remove one staged quote folder or clear the folder queue directly inside the main operational panel.
5. Paste a URL to convert a web page.
6. Paste plain text to save it as Markdown.
7. Click `Convert`.
8. Watch per-image progress in the progress bar and summary line while larger quote batches run.
9. Use `Abort` to stop a running batch after the current image finishes.
10. Use `Open Output` to jump straight to the generated files.
11. Use `Preferences` for app-wide defaults like theme, Raw OCR visibility, output folder, and auto-open behavior.

If an Obsidian vault is configured, you can also send copies there automatically.

### Quote Image Operational Panel

The quote-image workflow uses one larger operational panel instead of separate staging and log sections:

- Before conversion, that panel shows the staged quote folders with inline remove controls.
- `Select Folder` replaces the current quote-folder queue by default.
- `Add Folder` lets you intentionally combine another quote-image folder into the same batch.
- Each staged folder shows its folder name, full path, and image count.
- You can remove one staged folder at a time or clear the whole folder queue.
- During conversion, the same panel switches into live progress/log mode.
- Progress updates per image, so a batch with hundreds of screenshots shows where it is.
- `Abort` is cooperative: the app stops after the current image completes and keeps any partial output already written.
- Quote exports are merged into one Markdown file per batch.
- Quote export filenames are versioned automatically, for example:
  - `stoicism-app_quotes_355-images_20260627_174500.md`
  - `stoicism-app_quotes_355-images_20260627_174500_2.md`

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

This version does **not** add a History panel or sidebar. The main screen remains dedicated to conversion.

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

Run the basic CLI regression test:

```bash
python3 -m unittest tests/test_cli_mode.py
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
