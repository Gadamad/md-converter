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

## GUI Walkthrough

The app is designed for non-technical use:

1. Drop files onto the window, or click to browse.
2. Paste a URL to convert a web page.
3. Paste plain text to save it as Markdown.
4. Click `Convert`.
5. Use `Open Output` to jump straight to the generated files.

If an Obsidian vault is configured, you can also send copies there automatically.

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
