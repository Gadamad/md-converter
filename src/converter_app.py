#!/usr/bin/env python3
"""
MD Converter — Universal Markdown Converter App
Drag-and-drop (or browse) any PDF, DOCX, XLSX, HTML, TXT, or RTF file.
Converts to Markdown, organizes by type, delivers to Obsidian vault.
"""

import json
import subprocess
import sys
import threading
from pathlib import Path

import webview

from converters import SUPPORTED, ConvertResult, route, convert_pasted

try:
    from native_drop import setup_native_drop
    _NATIVE_DROP = True
except ImportError:
    _NATIVE_DROP = False

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

APP_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = APP_DIR / "converted"

# Vault path: loaded from config.json if it exists, otherwise disabled.
# Copy config.example.json -> config.json and set your Obsidian vault path.
_CONFIG_PATH = APP_DIR / "config.json"
_config = {}
if _CONFIG_PATH.exists():
    try:
        _config = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"WARNING: ignoring invalid config.json: {exc}", file=sys.stderr)
        _config = {}

VAULT_DIR = (
    Path(_config["vault_path"]).expanduser()
    if "vault_path" in _config
    else None
)

FILETYPES = (
    "All supported (*.pdf;*.docx;*.xlsx;*.html;*.htm;*.txt;*.rtf)",
    "PDF files (*.pdf)",
    "Word files (*.docx)",
    "Excel files (*.xlsx)",
    "HTML files (*.html;*.htm)",
    "Text files (*.txt)",
    "RTF files (*.rtf)",
)


# ---------------------------------------------------------------------------
# CLI mode
# ---------------------------------------------------------------------------

def cli_mode(paths: list[str], vault: bool = True):
    """Convert files from command line without GUI."""
    vault_dir = VAULT_DIR if vault else None
    results: list[ConvertResult] = []

    print(f"{'File':<55} {'Words':>10} {'Status'}")
    print("-" * 85)

    for path in paths:
        display_source = path if path.startswith(("http://", "https://")) else Path(path).name
        display = display_source[:52]
        if len(display_source) > 55:
            display += "..."
        try:
            r = route(path, OUTPUT_DIR, vault_dir)
            results.append(r)
            print(f"{display:<55} {r.word_count:>10,} {r.message}")
        except Exception as e:
            results.append(ConvertResult(False, "", 0, f"ERROR: {e}"))
            print(f"{display:<55} {'?':>10} ERROR: {e}")

    ok = sum(1 for r in results if r.success)
    words = sum(r.word_count for r in results)
    print(f"\n{'=' * 85}")
    print(f"SUMMARY: {ok}/{len(paths)} converted | {words:,} total words")
    print(f"Output: {OUTPUT_DIR.resolve()}")
    if vault:
        if VAULT_DIR:
            print(f"Vault:  {VAULT_DIR.resolve()}")
        else:
            print("Vault:  disabled (no config.json)")


# ---------------------------------------------------------------------------
# Inline HTML for the pywebview GUI
# ---------------------------------------------------------------------------

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MD Converter</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif;
    background: #1e1e2e; color: #cdd6f4;
    display: flex; flex-direction: column;
    height: 100vh; overflow: hidden;
    user-select: none; -webkit-user-select: none;
  }
  h1 { font-size: 22px; font-weight: 700; text-align: center; padding-top: 18px; color: #fff; }
  .subtitle { text-align: center; font-size: 12px; color: #6c7086; padding: 4px 0 14px; }

  /* Drop zone */
  #drop-zone {
    margin: 0 24px; padding: 32px 20px;
    border: 2px dashed #585b70; border-radius: 10px;
    background: #313244; text-align: center; cursor: pointer;
    transition: border-color 0.2s, background 0.2s;
    flex-shrink: 0;
  }
  #drop-zone:hover, #drop-zone.drag-over {
    border-color: #a6e3a1; background: #3b3d50;
  }
  #drop-zone .main-text { font-size: 15px; color: #a6adc8; pointer-events: none; }
  #drop-zone .sub-text  { font-size: 11px; color: #585b70; margin-top: 4px; pointer-events: none; }
  #drop-zone .badge {
    font-size: 11px; font-weight: 700; color: #a6e3a1;
    margin-top: 6px; display: none; pointer-events: none;
  }

  /* URL row */
  .url-row {
    display: flex; margin: 10px 24px 6px; gap: 8px; flex-shrink: 0;
  }
  .url-row input {
    flex: 1; padding: 7px 10px; font-size: 13px;
    background: #313244; color: #cdd6f4; border: 1px solid #585b70;
    border-radius: 6px; outline: none; caret-color: #cdd6f4;
  }
  .url-row input:focus { border-color: #a6adc8; }
  .url-row input::placeholder { color: #585b70; }
  .btn {
    padding: 7px 14px; font-size: 12px; font-weight: 700;
    background: #45475a; color: #fff; border: none; border-radius: 6px;
    cursor: pointer; white-space: nowrap;
    transition: background 0.15s;
  }
  .btn:hover { background: #585b70; }

  /* Options row */
  .options-row {
    display: flex; align-items: center; justify-content: space-between;
    margin: 0 24px 0; flex-shrink: 0;
  }
  .options-row label {
    font-size: 12px; color: #a6adc8; cursor: pointer;
    display: flex; align-items: center; gap: 6px;
  }
  .options-row input[type="checkbox"] {
    accent-color: #a6e3a1; width: 15px; height: 15px;
  }

  /* Log header */
  .log-header {
    display: flex; justify-content: space-between; align-items: center;
    margin: 10px 24px 4px; flex-shrink: 0;
  }
  .log-title { font-size: 11px; color: #585b70; text-transform: uppercase; letter-spacing: 1px; }
  .copy-btn {
    background: transparent; border: 1px solid #585b70; color: #6c7086;
    border-radius: 4px; padding: 3px 6px; cursor: pointer;
    display: flex; align-items: center; gap: 4px; font-size: 10px;
    transition: all 0.15s;
  }
  .copy-btn:hover { border-color: #a6adc8; color: #cdd6f4; }

  /* Status log */
  #log-container {
    margin: 0 24px 6px; flex: 1; min-height: 0;
    background: #11111b; border: 1px solid #313244; border-radius: 6px;
    overflow-y: auto; padding: 8px 10px;
    font-family: "Menlo", "SF Mono", monospace; font-size: 12px;
    line-height: 1.5;
  }
  #log-container::-webkit-scrollbar { width: 6px; }
  #log-container::-webkit-scrollbar-track { background: transparent; }
  #log-container::-webkit-scrollbar-thumb { background: #313244; border-radius: 3px; }
  .log-ok    { color: #a6e3a1; }
  .log-error { color: #f38ba8; }
  .log-info  { color: #a6adc8; }

  /* Progress bar */
  .progress-wrap {
    margin: 0 24px 4px; height: 6px; background: #313244;
    border-radius: 3px; overflow: hidden; flex-shrink: 0;
  }
  .progress-bar {
    height: 100%; width: 0%; background: #a6e3a1;
    transition: width 0.25s ease;
  }

  /* Convert button row */
  .convert-row {
    display: flex; justify-content: center; margin: 10px 24px 0; flex-shrink: 0;
  }
  .convert-btn {
    padding: 10px 40px; font-size: 14px; font-weight: 700;
    background: #a6e3a1; color: #1e1e2e; border: none; border-radius: 8px;
    cursor: pointer; transition: background 0.15s;
  }
  .convert-btn:hover { background: #94d89a; }

  /* Summary */
  .summary {
    font-size: 12px; color: #6c7086; padding: 0 28px 12px;
    flex-shrink: 0;
  }
</style>
</head>
<body>

<h1>Markdown Converter</h1>
<div class="subtitle">PDF &nbsp;|&nbsp; DOCX &nbsp;|&nbsp; XLSX &nbsp;|&nbsp; HTML / URL &nbsp;|&nbsp; TXT &nbsp;|&nbsp; RTF</div>

<div id="drop-zone">
  <div class="main-text">Drop files here or click to browse</div>
  <div class="sub-text">PDF, DOCX, XLSX, HTML, TXT, RTF</div>
  <div class="badge" id="badge"></div>
</div>

<div class="convert-row" id="convert-row" style="display:none">
  <button class="convert-btn" id="convert-btn">Convert</button>
</div>

<div class="url-row">
  <input type="text" id="url-input" placeholder="Paste a URL or text to convert...">
  <button class="btn" id="fetch-btn">Convert</button>
</div>

<div class="options-row">
  <label><input type="checkbox" id="vault-cb" VAULT_CHECKED> Copy to Obsidian vault</label>
  <div style="display:flex;gap:6px;">
    <button class="btn" id="open-btn">Open Output</button>
    <button class="btn" id="vault-btn">Open Vault</button>
  </div>
</div>

<div class="log-header">
  <span class="log-title">Log</span>
  <button class="copy-btn" id="copy-btn" title="Copy log to clipboard">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
    </svg>
  </button>
</div>
<div id="log-container"></div>

<div class="progress-wrap"><div class="progress-bar" id="progress"></div></div>
<div class="summary" id="summary">Ready</div>

<script>
  const dropZone  = document.getElementById('drop-zone');
  const badge     = document.getElementById('badge');
  const logEl     = document.getElementById('log-container');
  const progress  = document.getElementById('progress');
  const summary   = document.getElementById('summary');
  const urlInput  = document.getElementById('url-input');
  const fetchBtn  = document.getElementById('fetch-btn');
  const openBtn   = document.getElementById('open-btn');
  const vaultCb   = document.getElementById('vault-cb');
  const vaultBtn  = document.getElementById('vault-btn');

  let stagedFiles = [];

  /* ---- Drag-and-drop ---- */
  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropZone.classList.add('drag-over');
  });
  dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('drag-over');
  });
  document.addEventListener('dragover', (e) => e.preventDefault());
  document.addEventListener('drop', (e) => e.preventDefault());
  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropZone.classList.remove('drag-over');
    /* Native drop handler (PyObjC) intercepts file paths at the Cocoa level.
       JS only needs to prevent the default browser behaviour here. */
  });

  /* ---- Click to browse ---- */
  dropZone.addEventListener('click', () => {
    pywebview.api.browse_files();
  });

  /* ---- Fetch URL ---- */
  fetchBtn.addEventListener('click', () => {
    const url = urlInput.value.trim();
    if (url) {
      urlInput.value = '';
      pywebview.api.fetch_url(url);
    }
  });
  urlInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') fetchBtn.click();
  });

  /* ---- Open Output ---- */
  openBtn.addEventListener('click', () => {
    pywebview.api.open_output();
  });

  /* ---- Open Vault ---- */
  vaultBtn.addEventListener('click', () => {
    pywebview.api.open_vault();
  });

  /* ---- Convert staged files ---- */
  document.getElementById('convert-btn').addEventListener('click', () => {
    document.getElementById('convert-row').style.display = 'none';
    pywebview.api.convert_staged();
  });

  /* ---- Keyboard shortcuts ---- */
  document.addEventListener('keydown', (e) => {
    if (e.metaKey && e.key === 'o') { e.preventDefault(); pywebview.api.browse_files(); }
    if (e.metaKey && e.key === 'w') { e.preventDefault(); pywebview.api.close_window(); }
  });

  /* ---- Helper: called from Python ---- */
  function appendLog(text, cls) {
    const div = document.createElement('div');
    div.className = cls || 'log-info';
    div.textContent = text;
    logEl.appendChild(div);
    logEl.scrollTop = logEl.scrollHeight;
  }
  function setProgress(pct) {
    progress.style.width = pct + '%';
  }
  function setSummary(text) {
    summary.textContent = text;
  }
  function setBadge(text) {
    if (text) {
      badge.textContent = text;
      badge.style.display = 'block';
    } else {
      badge.style.display = 'none';
    }
  }
  function getVaultChecked() {
    return vaultCb.checked;
  }
  function showConvertButton() {
    document.getElementById('convert-row').style.display = 'flex';
  }
  function hideConvertButton() {
    document.getElementById('convert-row').style.display = 'none';
  }

  /* ---- Copy log to clipboard (via Python API — navigator.clipboard needs HTTPS) ---- */
  document.getElementById('copy-btn').addEventListener('click', () => {
    const text = logEl.innerText;
    pywebview.api.copy_to_clipboard(text);
    const btn = document.getElementById('copy-btn');
    const origHTML = btn.innerHTML;
    btn.innerHTML = '<span style="color:#a6e3a1">&#10003; Copied</span>';
    btn.style.borderColor = '#a6e3a1';
    setTimeout(() => { btn.innerHTML = origHTML; btn.style.borderColor = ''; }, 1500);
  });
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# pywebview API class
# ---------------------------------------------------------------------------

class Api:
    """Exposed to JavaScript via pywebview.api."""

    def __init__(self):
        self.window = None          # set after window creation
        self._staged: list[str] = []

    # -- helpers to call JS safely from threads --
    def _js(self, code: str):
        """Evaluate JS on the UI thread."""
        if self.window:
            try:
                self.window.evaluate_js(code)
            except Exception:
                pass

    def _log(self, text: str, tag: str = "log-info"):
        safe = json.dumps(text)
        self._js(f"appendLog({safe}, {json.dumps(tag)})")

    def _set_progress(self, pct: float):
        self._js(f"setProgress({pct:.1f})")

    def _set_summary(self, text: str):
        self._js(f"setSummary({json.dumps(text)})")

    def _set_badge(self, text: str | None):
        self._js(f"setBadge({json.dumps(text)})")

    def _vault_checked(self) -> bool:
        if self.window:
            try:
                val = self.window.evaluate_js("getVaultChecked()")
                return bool(val)
            except Exception:
                return True
        return True

    # -- public API exposed to JS --

    def convert_files(self, paths):
        """Called from JS drop or browse."""
        threading.Thread(target=self._worker, args=(list(paths),), daemon=True).start()

    def browse_files(self):
        """Open native file dialog and stage selected files."""
        if not self.window:
            return
        result = self.window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=FILETYPES,
        )
        if result:
            self.stage_files([str(p) for p in result])

    def fetch_url(self, url):
        """Convert a URL or pasted text to markdown."""
        if not url:
            return
        text = url.strip()
        threading.Thread(target=self._paste_worker, args=(text,), daemon=True).start()

    def stage_files(self, paths):
        """Stage files for conversion without converting immediately."""
        self._staged.extend(paths)
        count = len(self._staged)
        self._set_badge(f"{count} file{'s' if count != 1 else ''} staged")
        for p in paths:
            self._log(f"Staged: {Path(p).name}", "log-info")
        self._js("showConvertButton()")

    def convert_staged(self):
        """Convert all staged files."""
        if not self._staged:
            return
        paths = list(self._staged)
        self._staged.clear()
        self._js("hideConvertButton()")
        threading.Thread(target=self._worker, args=(paths,), daemon=True).start()

    def open_output(self):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(OUTPUT_DIR)])

    def open_vault(self):
        if VAULT_DIR:
            VAULT_DIR.mkdir(parents=True, exist_ok=True)
            subprocess.run(["open", str(VAULT_DIR)])
        else:
            self._log("No vault configured. Copy config.example.json -> config.json and set vault_path.", "log-error")

    def copy_to_clipboard(self, text):
        """Copy text to macOS clipboard via pbcopy."""
        try:
            proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            proc.communicate(text.encode("utf-8"))
        except Exception:
            pass

    def close_window(self):
        if self.window:
            self.window.destroy()

    # -- paste worker (URL or plain text) --

    def _paste_worker(self, text: str):
        use_vault = self._vault_checked()
        vault_dir = VAULT_DIR if use_vault else None

        is_url = text.startswith("http://") or text.startswith("https://")
        display = text[:60] if is_url else f"Pasted text ({len(text.split())} words)"
        self._log(f"Converting: {display}", "log-info")
        self._set_progress(0)

        try:
            r = convert_pasted(text, OUTPUT_DIR, vault_dir)
            tag = "log-ok" if r.success else "log-error"
            self._log(f"  {r.message} ({r.word_count:,} words)", tag)
        except Exception as e:
            self._log(f"  ERROR: {e}", "log-error")

        self._set_progress(100)
        self._set_summary(f"Done: 1 item converted")

    # -- worker (runs in background thread) --

    def _worker(self, paths: list[str]):
        use_vault = self._vault_checked()
        vault_dir = VAULT_DIR if use_vault else None
        ok_count = 0
        total_words = 0
        total = len(paths)

        self._set_progress(0)

        for i, path in enumerate(paths):
            name = Path(path).name if not path.startswith("http") else path[:60]
            self._log(f"Converting: {name}", "log-info")

            try:
                r = route(path, OUTPUT_DIR, vault_dir)
                total_words += r.word_count
                if r.success:
                    ok_count += 1
                    tag = "log-ok"
                else:
                    tag = "log-error"
                self._log(f"  {r.message} ({r.word_count:,} words)", tag)
            except Exception as e:
                self._log(f"  ERROR: {e}", "log-error")

            pct = ((i + 1) / total) * 100
            self._set_progress(pct)

        summary_text = f"Done: {ok_count}/{total} converted | {total_words:,} total words"
        self._log(f"\n{summary_text}", "log-ok")
        self._set_summary(summary_text)
        self._set_badge(None)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    # CLI mode: arguments provided
    if len(sys.argv) > 1:
        cli_mode(sys.argv[1:])
        return

    # GUI mode
    api = Api()
    # Inject vault checkbox state into HTML before creating window
    vault_checked = "checked" if VAULT_DIR else ""
    html = HTML.replace("VAULT_CHECKED", vault_checked)

    window = webview.create_window(
        "MD Converter",
        html=html,
        js_api=api,
        width=660,
        height=580,
        resizable=True,
        background_color="#1e1e2e",
    )
    api.window = window

    def on_loaded():
        if _NATIVE_DROP:
            def drop_callback(file_paths):
                api.stage_files(file_paths)
            threading.Thread(
                target=setup_native_drop,
                args=(window, drop_callback),
                daemon=True,
            ).start()

    webview.start(func=on_loaded)


if __name__ == "__main__":
    main()
