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
from typing import Callable, NamedTuple

import webview

from converters import SUPPORTED, ConvertResult, route, convert_pasted, convert_image_folder_quotes
from preferences import Preferences, default_preferences_path

try:
    from native_drop import setup_native_drop
    _NATIVE_DROP = True
except ImportError:
    _NATIVE_DROP = False

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

APP_DIR = Path(__file__).resolve().parent.parent
DEFAULT_QUOTE_FOLDER = Path(
    "/Users/studioware/SynologyDrive/____AI/_Backup - all projects/_Projects/Stoicism app"
)


def _output_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path.home() / "Documents" / "MD Converter" / "converted"
    return APP_DIR / "converted"


OUTPUT_DIR = _output_dir()

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

QUOTE_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


class StagedFolder(NamedTuple):
    id: str
    path: Path
    image_count: int
    images: tuple[str, ...]


class QuoteBatchHooks:
    def __init__(
        self,
        on_image_processed: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ):
        self.on_image_processed = on_image_processed
        self.should_cancel = should_cancel


def discover_quote_images(folder: Path) -> list[str]:
    return sorted(
        str(path)
        for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() in QUOTE_IMAGE_EXTENSIONS
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
  h1 { font-size: 22px; font-weight: 700; text-align: center; padding-top: 16px; color: #fff; }
  .subtitle { text-align: center; font-size: 12px; color: #6c7086; padding: 4px 0 10px; }

  /* Drop zone */
  #drop-zone {
    margin: 0 20px; padding: 26px 18px;
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

  .folder-actions {
    display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  }
  .folder-queue-item {
    display: flex; align-items: center; justify-content: space-between;
    gap: 10px; padding: 10px 12px;
    border: 1px solid #313244; border-radius: 8px; background: #181825;
  }
  .folder-queue-copy {
    min-width: 0; display: flex; flex-direction: column; gap: 2px;
  }
  .folder-queue-name {
    font-size: 12px; color: #cdd6f4; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis;
  }
  .folder-queue-meta {
    font-size: 11px; color: #6c7086; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis;
  }
  .folder-remove-btn {
    padding: 6px 10px; font-size: 11px;
  }

  /* URL row */
  .url-row {
    display: flex; margin: 10px 20px 6px; gap: 8px; flex-shrink: 0;
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
    margin: 0 20px 0; flex-shrink: 0;
  }
  .options-actions {
    display: flex; gap: 6px; align-items: center;
  }
  .options-row label {
    font-size: 12px; color: #a6adc8; cursor: pointer;
    display: flex; align-items: center; gap: 6px;
  }
  .options-row input[type="checkbox"] {
    accent-color: #a6e3a1; width: 15px; height: 15px;
  }

  .operations-shell {
    margin: 10px 20px 12px;
    flex: 1; min-height: 0;
    background: #11111b; border: 1px solid #313244; border-radius: 10px;
    display: flex; flex-direction: column; overflow: hidden;
  }
  .operations-header {
    display: flex; justify-content: space-between; align-items: flex-start;
    gap: 12px; padding: 10px 12px 8px;
    border-bottom: 1px solid #313244; background: #181825;
    flex-shrink: 0;
  }
  .operations-copy {
    min-width: 0; display: flex; flex-direction: column; gap: 2px;
  }
  .operations-title {
    font-size: 11px; color: #585b70; text-transform: uppercase; letter-spacing: 1px;
  }
  .operations-subtitle {
    font-size: 11px; color: #6c7086;
  }
  .operations-header-actions {
    display: flex; align-items: center; justify-content: flex-end; gap: 8px; flex-wrap: wrap;
  }
  .operations-panel {
    flex: 1; min-height: 0; position: relative; background: #11111b;
  }
  .panel-mode {
    display: none; height: 100%; min-height: 0;
  }
  .panel-mode.active {
    display: flex; flex: 1; min-height: 0; flex-direction: column;
  }
  #queue-panel {
    padding: 12px; gap: 8px; overflow-y: auto;
  }
  #queue-panel::-webkit-scrollbar { width: 6px; }
  #queue-panel::-webkit-scrollbar-track { background: transparent; }
  #queue-panel::-webkit-scrollbar-thumb { background: #313244; border-radius: 3px; }
  #folder-queue {
    display: flex; flex-direction: column; gap: 8px;
  }
  .panel-empty {
    min-height: 100%; display: flex; align-items: center; justify-content: center;
    text-align: center; font-size: 12px; color: #6c7086; line-height: 1.5;
    padding: 22px; border: 1px dashed #313244; border-radius: 8px; background: #181825;
  }
  .copy-btn {
    background: transparent; border: 1px solid #585b70; color: #6c7086;
    border-radius: 4px; padding: 3px 6px; cursor: pointer;
    display: flex; align-items: center; gap: 4px; font-size: 10px;
    transition: all 0.15s;
  }
  .copy-btn:hover { border-color: #a6adc8; color: #cdd6f4; }
  .copy-btn.is-disabled {
    opacity: 0.45; cursor: default; pointer-events: none;
  }

  /* Status log */
  #log-container {
    flex: 1; min-height: 0;
    background: transparent; border: none; border-radius: 0;
    overflow-y: auto; padding: 12px;
    font-family: "Menlo", "SF Mono", monospace; font-size: 12px;
    line-height: 1.5;
  }
  #log-container::-webkit-scrollbar { width: 6px; }
  #log-container::-webkit-scrollbar-track { background: transparent; }
  #log-container::-webkit-scrollbar-thumb { background: #313244; border-radius: 3px; }
  .log-ok    { color: #a6e3a1; }
  .log-error { color: #f38ba8; }
  .log-info  { color: #a6adc8; }

  .operations-footer {
    border-top: 1px solid #313244; background: #181825;
    padding: 8px 12px 10px; flex-shrink: 0;
  }

  /* Progress bar */
  .progress-wrap {
    margin: 0 0 8px; height: 6px; background: #313244;
    border-radius: 3px; overflow: hidden;
  }
  .progress-bar {
    height: 100%; width: 0%; background: #a6e3a1;
    transition: width 0.25s ease;
  }

  .footer-row {
    display: flex; align-items: center; justify-content: space-between;
    gap: 10px;
  }

  /* Convert button row */
  .convert-row {
    display: flex; justify-content: flex-end; align-items: center; gap: 8px;
    flex-shrink: 0;
  }
  .convert-btn {
    padding: 9px 28px; font-size: 13px; font-weight: 700;
    background: #a6e3a1; color: #1e1e2e; border: none; border-radius: 8px;
    cursor: pointer; transition: background 0.15s;
  }
  .convert-btn:hover { background: #94d89a; }
  .abort-btn {
    background: #f38ba8; color: #1e1e2e;
  }
  .abort-btn:hover { background: #e07f9a; }

  /* Summary */
  .summary {
    font-size: 12px; color: #6c7086; min-width: 0; flex: 1;
  }

  .modal-backdrop {
    position: fixed; inset: 0; background: rgba(17, 17, 27, 0.76);
    display: none; align-items: center; justify-content: center;
    padding: 24px; z-index: 100;
  }
  .modal-backdrop.active {
    display: flex;
  }
  .modal-card {
    width: min(560px, 100%); background: #181825; border: 1px solid #313244;
    border-radius: 14px; box-shadow: 0 24px 64px rgba(0, 0, 0, 0.35);
    display: flex; flex-direction: column; overflow: hidden;
  }
  .modal-header {
    display: flex; align-items: center; justify-content: space-between;
    gap: 10px; padding: 14px 16px; border-bottom: 1px solid #313244;
  }
  .modal-title {
    font-size: 17px; font-weight: 700; color: #fff;
  }
  .modal-close {
    background: transparent; border: none; color: #a6adc8; font-size: 22px;
    cursor: pointer; line-height: 1; padding: 0 2px;
  }
  .modal-close:hover {
    color: #fff;
  }
  .modal-body {
    display: flex; flex-direction: column; gap: 14px; padding: 16px;
  }
  .preferences-field {
    display: flex; flex-direction: column; gap: 6px;
  }
  .preferences-label {
    font-size: 12px; font-weight: 600; color: #cdd6f4;
  }
  .preferences-help {
    font-size: 11px; color: #6c7086; line-height: 1.4;
  }
  .preferences-select,
  .preferences-checkbox-row,
  .preferences-output-row {
    display: flex; align-items: center; gap: 10px;
  }
  .preferences-select select {
    width: 100%; padding: 8px 10px; font-size: 13px;
    background: #313244; color: #cdd6f4; border: 1px solid #585b70;
    border-radius: 8px;
  }
  .preferences-output-value {
    flex: 1; min-height: 38px; padding: 8px 10px;
    background: #11111b; color: #cdd6f4; border: 1px solid #313244;
    border-radius: 8px; font-size: 12px; line-height: 1.4;
    display: flex; align-items: center;
  }
  .preferences-checkbox-row label {
    display: flex; align-items: center; gap: 8px; font-size: 13px; color: #cdd6f4;
  }
  .preferences-checkbox-row input[type="checkbox"] {
    accent-color: #a6e3a1; width: 16px; height: 16px;
  }
  .modal-footer {
    display: flex; justify-content: flex-end; gap: 8px; padding: 14px 16px;
    border-top: 1px solid #313244; background: #11111b;
  }

  body[data-theme="light"] {
    background: #f5f7fb; color: #1f2937;
  }
  body[data-theme="light"] h1,
  body[data-theme="light"] .modal-title {
    color: #0f172a;
  }
  body[data-theme="light"] .subtitle,
  body[data-theme="light"] .operations-title,
  body[data-theme="light"] .operations-subtitle,
  body[data-theme="light"] .folder-queue-meta,
  body[data-theme="light"] .summary,
  body[data-theme="light"] .preferences-help {
    color: #64748b;
  }
  body[data-theme="light"] #drop-zone,
  body[data-theme="light"] .operations-shell,
  body[data-theme="light"] .folder-queue-item,
  body[data-theme="light"] .panel-empty,
  body[data-theme="light"] .modal-card,
  body[data-theme="light"] .modal-footer,
  body[data-theme="light"] .modal-header,
  body[data-theme="light"] .operations-header,
  body[data-theme="light"] .operations-footer,
  body[data-theme="light"] .preferences-output-value,
  body[data-theme="light"] #log-container {
    background: #ffffff;
    border-color: #d7deea;
  }
  body[data-theme="light"] .url-row input,
  body[data-theme="light"] .preferences-select select {
    background: #ffffff;
    color: #0f172a;
    border-color: #c7d2e0;
  }
  body[data-theme="light"] .btn {
    background: #dbe2f0;
    color: #0f172a;
  }
  body[data-theme="light"] .btn:hover {
    background: #cbd5e1;
  }
  body[data-theme="light"] .convert-btn {
    background: #8fd38c;
  }
  body[data-theme="light"] .abort-btn {
    background: #f4a7b9;
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

<div class="url-row">
  <input type="text" id="url-input" placeholder="Paste a URL or text to convert...">
  <button class="btn" id="fetch-btn">Convert</button>
</div>

<div class="options-row">
  <label><input type="checkbox" id="vault-cb" VAULT_CHECKED> Copy to Obsidian vault</label>
  <div class="options-actions">
    <button class="btn" id="preferences-btn">Preferences</button>
    <button class="btn" id="open-btn">Open Output</button>
    <button class="btn" id="vault-btn">Open Vault</button>
  </div>
</div>

<div class="modal-backdrop" id="preferences-modal">
  <div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="preferences-title">
    <div class="modal-header">
      <div class="modal-title" id="preferences-title">Preferences</div>
      <button class="modal-close" id="preferences-close-btn" aria-label="Close preferences">×</button>
    </div>
    <div class="modal-body">
      <div class="preferences-field">
        <div class="preferences-label">Theme</div>
        <div class="preferences-select">
          <select id="theme-select">
            <option value="system">System</option>
            <option value="dark">Dark</option>
            <option value="light">Light</option>
          </select>
        </div>
      </div>

      <div class="preferences-field">
        <div class="preferences-label">Raw OCR display</div>
        <div class="preferences-select">
          <select id="raw-ocr-mode-select">
            <option value="different">Show when different only</option>
            <option value="always">Always show</option>
            <option value="never">Never show</option>
          </select>
        </div>
        <div class="preferences-help">Use this to hide duplicate Raw OCR blocks when the parsed quote already matches them.</div>
      </div>

      <div class="preferences-field">
        <div class="preferences-label">Output directory</div>
        <div class="preferences-output-row">
          <div class="preferences-output-value" id="output-dir-value">Default output folder</div>
          <button class="btn" id="output-dir-browse-btn">Browse</button>
        </div>
      </div>

      <div class="preferences-field">
        <div class="preferences-checkbox-row">
          <label><input type="checkbox" id="auto-open-output-cb"> Open output automatically after successful export</label>
        </div>
      </div>
    </div>
    <div class="modal-footer">
      <button class="btn" id="output-dir-reset-btn">Use Default</button>
      <button class="btn" id="preferences-save-btn">Save</button>
    </div>
  </div>
</div>

<div class="operations-shell">
  <div class="operations-header">
    <div class="operations-copy">
      <div class="operations-title" id="operations-title">Staged folders</div>
      <div class="operations-subtitle" id="operations-subtitle">Select replaces the queue. Add keeps existing staged folders.</div>
    </div>
    <div class="operations-header-actions">
      <div class="folder-actions">
        <button class="btn" id="folder-btn">Select Folder</button>
        <button class="btn" id="add-folder-btn">Add Folder</button>
        <button class="btn" id="clear-folders-btn">Clear</button>
      </div>
      <button class="copy-btn is-disabled" id="copy-btn" title="Copy log to clipboard" disabled>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
        </svg>
      </button>
    </div>
  </div>

  <div class="operations-panel">
    <div class="panel-mode active" id="queue-panel">
      <div class="panel-empty" id="queue-empty">Stage one or more quote-image folders here. Remove them inline before converting.</div>
      <div id="folder-queue"></div>
    </div>
    <div class="panel-mode" id="log-panel">
      <div id="log-container"></div>
    </div>
  </div>

  <div class="operations-footer">
    <div class="progress-wrap"><div class="progress-bar" id="progress"></div></div>
    <div class="footer-row">
      <div class="summary" id="summary">Ready</div>
      <div class="convert-row" id="convert-row" style="display:none">
        <button class="convert-btn" id="convert-btn">Convert</button>
        <button class="btn abort-btn" id="abort-btn" style="display:none">Abort</button>
      </div>
    </div>
  </div>
</div>

<script>
  const dropZone  = document.getElementById('drop-zone');
  const badge     = document.getElementById('badge');
  const queuePanel = document.getElementById('queue-panel');
  const logPanel  = document.getElementById('log-panel');
  const queueEmpty = document.getElementById('queue-empty');
  const logEl     = document.getElementById('log-container');
  const progress  = document.getElementById('progress');
  const summary   = document.getElementById('summary');
  const folderQueue = document.getElementById('folder-queue');
  const operationsTitle = document.getElementById('operations-title');
  const operationsSubtitle = document.getElementById('operations-subtitle');
  const urlInput  = document.getElementById('url-input');
  const fetchBtn  = document.getElementById('fetch-btn');
  const preferencesBtn = document.getElementById('preferences-btn');
  const preferencesModal = document.getElementById('preferences-modal');
  const preferencesCloseBtn = document.getElementById('preferences-close-btn');
  const preferencesSaveBtn = document.getElementById('preferences-save-btn');
  const themeSelect = document.getElementById('theme-select');
  const rawOcrModeSelect = document.getElementById('raw-ocr-mode-select');
  const outputDirValue = document.getElementById('output-dir-value');
  const outputDirBrowseBtn = document.getElementById('output-dir-browse-btn');
  const outputDirResetBtn = document.getElementById('output-dir-reset-btn');
  const autoOpenOutputCb = document.getElementById('auto-open-output-cb');
  const folderBtn = document.getElementById('folder-btn');
  const addFolderBtn = document.getElementById('add-folder-btn');
  const clearFoldersBtn = document.getElementById('clear-folders-btn');
  const convertBtn = document.getElementById('convert-btn');
  const abortBtn = document.getElementById('abort-btn');
  const convertRow = document.getElementById('convert-row');
  const copyBtn = document.getElementById('copy-btn');
  const openBtn   = document.getElementById('open-btn');
  const vaultCb   = document.getElementById('vault-cb');
  const vaultBtn  = document.getElementById('vault-btn');

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

  folderBtn.addEventListener('click', () => {
    pywebview.api.browse_folder();
  });
  addFolderBtn.addEventListener('click', () => {
    pywebview.api.add_folder();
  });
  clearFoldersBtn.addEventListener('click', () => {
    pywebview.api.clear_staged_folders();
  });
  preferencesBtn.addEventListener('click', () => {
    preferencesModal.classList.add('active');
  });
  preferencesCloseBtn.addEventListener('click', () => {
    preferencesModal.classList.remove('active');
  });
  preferencesModal.addEventListener('click', (event) => {
    if (event.target === preferencesModal) {
      preferencesModal.classList.remove('active');
    }
  });
  outputDirBrowseBtn.addEventListener('click', async () => {
    const selected = await pywebview.api.browse_output_directory();
    if (selected) {
      outputDirValue.textContent = selected;
    }
  });
  outputDirResetBtn.addEventListener('click', () => {
    outputDirValue.textContent = 'Default output folder';
  });
  preferencesSaveBtn.addEventListener('click', async () => {
    const payload = {
      theme: themeSelect.value,
      raw_ocr_mode: rawOcrModeSelect.value,
      output_dir: outputDirValue.textContent === 'Default output folder' ? null : outputDirValue.textContent,
      auto_open_output: autoOpenOutputCb.checked,
    };
    const prefs = await pywebview.api.save_preferences(payload);
    applyPreferences(prefs);
    preferencesModal.classList.remove('active');
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
  convertBtn.addEventListener('click', () => {
    pywebview.api.convert_staged();
  });
  abortBtn.addEventListener('click', () => {
    pywebview.api.cancel_current_job();
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
  function resolveTheme(theme) {
    if (theme === 'system') {
      return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
    }
    return theme;
  }
  function applyPreferences(prefs) {
    const theme = resolveTheme(prefs.theme || 'system');
    document.body.dataset.theme = theme;
    themeSelect.value = prefs.theme || 'system';
    rawOcrModeSelect.value = prefs.raw_ocr_mode || 'different';
    outputDirValue.textContent = prefs.output_dir || 'Default output folder';
    autoOpenOutputCb.checked = Boolean(prefs.auto_open_output);
  }
  function updatePanelMode(mode) {
    const isQueue = mode === 'queue';
    queuePanel.classList.toggle('active', isQueue);
    logPanel.classList.toggle('active', !isQueue);
    operationsTitle.textContent = isQueue ? 'Staged folders' : 'Conversion log';
    operationsSubtitle.textContent = isQueue
      ? 'Select replaces the queue. Add keeps existing staged folders.'
      : 'Live progress and output from the current conversion job.';
    copyBtn.disabled = isQueue;
    copyBtn.classList.toggle('is-disabled', isQueue);
    if (!isQueue) {
      logEl.scrollTop = logEl.scrollHeight;
    }
  }
  function showLogPanel() {
    updatePanelMode('log');
  }
  function showConvertButton() {
    convertRow.style.display = 'flex';
    convertBtn.style.display = 'inline-flex';
  }
  function hideConvertButton() {
    convertBtn.style.display = 'none';
    if (abortBtn.style.display === 'none') {
      convertRow.style.display = 'none';
    }
  }
  function showAbortButton() {
    convertRow.style.display = 'flex';
    abortBtn.style.display = 'inline-flex';
  }
  function hideAbortButton() {
    abortBtn.style.display = 'none';
    if (convertBtn.style.display === 'none') {
      convertRow.style.display = 'none';
    }
  }
  function renderFolderQueue(items, state = {}) {
    updatePanelMode('queue');
    folderQueue.innerHTML = '';
    const fileCount = state.file_count || 0;
    clearFoldersBtn.disabled = items.length === 0;
    clearFoldersBtn.style.opacity = items.length === 0 ? '0.6' : '1';
    for (const item of items) {
      const row = document.createElement('div');
      row.className = 'folder-queue-item';

      const copy = document.createElement('div');
      copy.className = 'folder-queue-copy';

      const name = document.createElement('div');
      name.className = 'folder-queue-name';
      name.textContent = item.name;

      const meta = document.createElement('div');
      meta.className = 'folder-queue-meta';
      const imageLabel = item.image_count === 1 ? 'image' : 'images';
      meta.textContent = `${item.image_count} ${imageLabel} • ${item.path}`;

      copy.appendChild(name);
      copy.appendChild(meta);

      const remove = document.createElement('button');
      remove.className = 'btn folder-remove-btn';
      remove.textContent = 'Remove';
      remove.addEventListener('click', () => {
        pywebview.api.remove_staged_folder(item.id);
      });

      row.appendChild(copy);
      row.appendChild(remove);
      folderQueue.appendChild(row);
    }
    if (items.length > 0) {
      queueEmpty.style.display = 'none';
    } else {
      queueEmpty.style.display = 'flex';
      if (fileCount > 0) {
        const fileLabel = fileCount === 1 ? 'file' : 'files';
        queueEmpty.textContent = `${fileCount} ${fileLabel} staged from the drop zone. Convert when ready, or stage quote folders here.`;
      } else {
        queueEmpty.textContent = 'Stage one or more quote-image folders here. Remove them inline before converting.';
      }
    }
  }

  /* ---- Copy log to clipboard (via Python API — navigator.clipboard needs HTTPS) ---- */
  copyBtn.addEventListener('click', () => {
    const text = logEl.innerText;
    pywebview.api.copy_to_clipboard(text);
    const origHTML = copyBtn.innerHTML;
    copyBtn.innerHTML = '<span style="color:#a6e3a1">&#10003; Copied</span>';
    copyBtn.style.borderColor = '#a6e3a1';
    setTimeout(() => { copyBtn.innerHTML = origHTML; copyBtn.style.borderColor = ''; }, 1500);
  });
  window.addEventListener('pywebviewready', async () => {
    const prefs = await pywebview.api.get_preferences();
    applyPreferences(prefs);
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
        self._staged_folders: list[StagedFolder] = []
        self._cancel_event = threading.Event()
        self._folder_sequence = 0
        self._job_running = False
        self._preferences_path = default_preferences_path()
        self._preferences = Preferences.load(self._preferences_path)

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

    def _show_convert_button(self):
        self._js("showConvertButton()")

    def _hide_convert_button(self):
        self._js("hideConvertButton()")

    def _show_abort_button(self):
        self._js("showAbortButton()")

    def _hide_abort_button(self):
        self._js("hideAbortButton()")

    def _show_log_panel(self):
        self._js("showLogPanel()")

    def _next_folder_id(self) -> str:
        self._folder_sequence += 1
        return f"folder-{self._folder_sequence}"

    def _render_staged_folders(self):
        payload = [
            {
                "id": folder.id,
                "name": folder.path.name,
                "path": str(folder.path),
                "image_count": folder.image_count,
            }
            for folder in self._staged_folders
        ]
        state = {
            "file_count": len(self._staged),
            "folder_count": len(self._staged_folders),
            "image_count": self._unique_staged_folder_image_count(),
        }
        self._js(f"renderFolderQueue({json.dumps(payload)}, {json.dumps(state)})")

    def _preferences_payload(self) -> dict[str, object]:
        return self._preferences.to_dict()

    def _save_preferences(self) -> None:
        self._preferences.save(self._preferences_path)

    def _effective_output_dir(self) -> Path:
        return self._preferences.output_dir or OUTPUT_DIR

    def _maybe_auto_open_output(self, output_paths: list[Path]) -> None:
        if not self._preferences.auto_open_output or not output_paths:
            return
        target = output_paths[0].resolve().parent if len(output_paths) == 1 else self._effective_output_dir().resolve()
        subprocess.run(["open", str(target)])

    def _refresh_stage_ui(self):
        self._render_staged_folders()
        file_count = len(self._staged)
        folder_count = len(self._staged_folders)
        image_count = self._unique_staged_folder_image_count()

        if file_count and folder_count:
            badge = (
                f"{file_count} file{'s' if file_count != 1 else ''} + "
                f"{folder_count} folder{'s' if folder_count != 1 else ''} staged"
            )
        elif file_count:
            badge = f"{file_count} file{'s' if file_count != 1 else ''} staged"
        elif folder_count:
            badge = (
                f"{folder_count} folder{'s' if folder_count != 1 else ''} staged "
                f"({image_count} image{'s' if image_count != 1 else ''})"
            )
        else:
            badge = None

        self._set_badge(badge)
        if file_count or folder_count:
            self._show_convert_button()
        else:
            self._hide_convert_button()

    def _collect_staged_paths(self) -> list[str]:
        paths: list[str] = []
        seen: set[Path] = set()

        for path in self._staged:
            try:
                resolved = Path(path).resolve()
            except OSError:
                resolved = Path(path).absolute()
            if resolved in seen:
                continue
            seen.add(resolved)
            paths.append(path)

        for folder in self._staged_folders:
            for image_path in folder.images:
                path_obj = Path(image_path)
                try:
                    resolved = path_obj.resolve()
                except OSError:
                    resolved = path_obj.absolute()
                if resolved in seen:
                    continue
                seen.add(resolved)
                paths.append(image_path)

        return paths

    def _unique_staged_folder_image_count(self) -> int:
        seen: set[Path] = set()
        count = 0
        for folder in self._staged_folders:
            for image_path in folder.images:
                path_obj = Path(image_path)
                try:
                    resolved = path_obj.resolve()
                except OSError:
                    resolved = path_obj.absolute()
                if resolved in seen:
                    continue
                seen.add(resolved)
                count += 1
        return count

    def _vault_checked(self) -> bool:
        if self.window:
            try:
                val = self.window.evaluate_js("getVaultChecked()")
                return bool(val)
            except Exception:
                return True
        return True

    # -- public API exposed to JS --

    def get_preferences(self):
        return self._preferences_payload()

    def save_preferences(self, payload):
        data = self._preferences_payload()
        if isinstance(payload, dict):
            data.update(payload)
        self._preferences = Preferences.from_dict(data)
        self._save_preferences()
        return self._preferences_payload()

    def browse_output_directory(self):
        if not self.window:
            return None
        result = self.window.create_file_dialog(
            webview.FOLDER_DIALOG,
            allow_multiple=False,
            directory=str(self._effective_output_dir().parent),
        )
        if not result:
            return None
        return str(result[0])

    def convert_files(self, paths):
        """Called from JS drop or browse."""
        if self._job_running:
            self._log("A conversion is already running", "log-error")
            return
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

    def browse_folder(self):
        self._browse_folder_dialog(replace=True)

    def add_folder(self):
        self._browse_folder_dialog(replace=False)

    def _browse_folder_dialog(self, replace: bool):
        if not self.window:
            return
        directory = str(DEFAULT_QUOTE_FOLDER if DEFAULT_QUOTE_FOLDER.exists() else APP_DIR)
        result = self.window.create_file_dialog(
            webview.FOLDER_DIALOG,
            allow_multiple=False,
            directory=directory,
        )
        if not result:
            return
        self.stage_quote_folder(Path(str(result[0])), replace=replace)

    def fetch_url(self, url):
        """Convert a URL or pasted text to markdown."""
        if not url:
            return
        if self._job_running:
            self._log("A conversion is already running", "log-error")
            return
        text = url.strip()
        threading.Thread(target=self._paste_worker, args=(text,), daemon=True).start()

    def stage_files(self, paths):
        """Stage files for conversion without converting immediately."""
        self._staged.extend(paths)
        for p in paths:
            self._log(f"Staged: {Path(p).name}", "log-info")
        self._refresh_stage_ui()

    def stage_quote_folder(self, folder: Path, replace: bool = True):
        images = tuple(discover_quote_images(folder))
        if not images:
            self._log(f"No supported quote images found in {folder.name}", "log-error")
            return

        staged_folder = StagedFolder(
            id=self._next_folder_id(),
            path=folder,
            image_count=len(images),
            images=images,
        )

        if replace:
            self._staged_folders = [staged_folder]
            self._log(
                f"Staged folder: {folder.name} ({staged_folder.image_count} image{'s' if staged_folder.image_count != 1 else ''})",
                "log-info",
            )
        else:
            self._staged_folders = [
                existing for existing in self._staged_folders if existing.path != folder
            ]
            self._staged_folders.append(staged_folder)
            self._log(
                f"Added folder: {folder.name} ({staged_folder.image_count} image{'s' if staged_folder.image_count != 1 else ''})",
                "log-info",
            )

        self._refresh_stage_ui()

    def remove_staged_folder(self, folder_id: str):
        self._staged_folders = [
            folder for folder in self._staged_folders if folder.id != folder_id
        ]
        self._refresh_stage_ui()

    def clear_staged_folders(self):
        self._staged_folders = []
        self._refresh_stage_ui()

    def convert_staged(self):
        """Convert all staged files."""
        paths = self._collect_staged_paths()
        if not paths:
            return
        if self._job_running:
            self._log("A conversion is already running", "log-error")
            return
        self._staged.clear()
        self._staged_folders = []
        self._refresh_stage_ui()
        threading.Thread(target=self._worker, args=(paths,), daemon=True).start()

    def cancel_current_job(self):
        self._cancel_event.set()
        self._log("Abort requested", "log-info")
        self._set_summary("Abort requested…")

    def open_output(self):
        output_dir = self._effective_output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(output_dir)])

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
        self._job_running = True
        self._cancel_event.clear()
        use_vault = self._vault_checked()
        vault_dir = VAULT_DIR if use_vault else None
        output_dir = self._effective_output_dir()

        is_url = text.startswith("http://") or text.startswith("https://")
        display = text[:60] if is_url else f"Pasted text ({len(text.split())} words)"
        self._show_log_panel()
        self._log(f"Converting: {display}", "log-info")
        self._set_progress(0)

        try:
            r = convert_pasted(text, output_dir, vault_dir)
            tag = "log-ok" if r.success else "log-error"
            self._log(f"  {r.message} ({r.word_count:,} words)", tag)
            if r.success and r.output_path:
                self._maybe_auto_open_output([Path(r.output_path)])
        except Exception as e:
            self._log(f"  ERROR: {e}", "log-error")
        finally:
            self._job_running = False
            self._set_progress(100)
            self._set_summary(f"Done: 1 item converted")

    # -- worker (runs in background thread) --

    def _worker(self, paths: list[str]):
        self._job_running = True
        self._cancel_event.clear()
        use_vault = self._vault_checked()
        vault_dir = VAULT_DIR if use_vault else None
        output_dir = self._effective_output_dir()
        ok_count = 0
        total_words = 0
        job_failed = False
        successful_outputs: list[Path] = []
        image_paths = [path for path in paths if Path(path).suffix.lower() in QUOTE_IMAGE_EXTENSIONS]
        other_paths = [path for path in paths if Path(path).suffix.lower() not in QUOTE_IMAGE_EXTENSIONS]
        total = len(other_paths) + len(image_paths)
        processed = 0

        self._show_log_panel()
        self._set_progress(0)
        self._show_abort_button()

        if image_paths:
            self._log(f"Converting: {len(image_paths)} quote image{'s' if len(image_paths) != 1 else ''}", "log-info")
            image_processed = 0
            image_batch_completed = False

            def on_image_processed(current: int, total_images: int, image_name: str):
                nonlocal image_processed
                image_processed = current
                overall_processed = processed + current
                pct = (overall_processed / total) * 100 if total else 100
                self._set_progress(pct)
                self._set_summary(f"Processing {overall_processed} / {total}: {image_name}")

            try:
                result = convert_image_folder_quotes(
                    image_paths,
                    output_dir / "quotes",
                    vault_dir,
                    hooks=QuoteBatchHooks(
                        on_image_processed=on_image_processed,
                        should_cancel=self._cancel_event.is_set,
                    ),
                    raw_ocr_mode=self._preferences.raw_ocr_mode,
                )
                total_words += result.word_count
                if result.success:
                    ok_count += image_processed or len(image_paths)
                    tag = "log-ok"
                    if result.output_path:
                        successful_outputs.append(Path(result.output_path))
                else:
                    job_failed = True
                    tag = "log-error"
                self._log(f"  {result.message} ({result.word_count:,} words)", tag)
                image_batch_completed = result.success
            except Exception as exc:
                job_failed = True
                self._log(f"  ERROR: {exc}", "log-error")

            if self._cancel_event.is_set():
                processed += image_processed
            elif image_batch_completed:
                processed += image_processed or len(image_paths)
            else:
                processed += image_processed
            if total:
                self._set_progress((processed / total) * 100)

        for path in other_paths:
            if self._cancel_event.is_set():
                break

            name = Path(path).name if not path.startswith("http") else path[:60]
            self._log(f"Converting: {name}", "log-info")
            self._set_summary(f"Processing {processed + 1} / {total}: {name}")

            try:
                r = route(path, output_dir, vault_dir)
                total_words += r.word_count
                if r.success:
                    ok_count += 1
                    tag = "log-ok"
                    if r.output_path:
                        successful_outputs.append(Path(r.output_path))
                else:
                    job_failed = True
                    tag = "log-error"
                self._log(f"  {r.message} ({r.word_count:,} words)", tag)
            except Exception as e:
                job_failed = True
                self._log(f"  ERROR: {e}", "log-error")

            processed += 1
            pct = ((processed) / total) * 100 if total else 100
            self._set_progress(pct)

        if self._cancel_event.is_set():
            summary_text = f"Canceled: {processed}/{total} processed | {total_words:,} total words"
            summary_tag = "log-info"
        elif job_failed:
            summary_text = f"Failed: {processed}/{total} processed | {total_words:,} total words"
            summary_tag = "log-error"
        else:
            summary_text = f"Done: {processed}/{total} processed | {total_words:,} total words"
            summary_tag = "log-ok"
        self._log(f"\n{summary_text}", summary_tag)
        self._set_summary(summary_text)
        self._set_badge(None)
        self._hide_abort_button()
        self._maybe_auto_open_output(successful_outputs)
        self._job_running = False

    def _quote_folder_worker(self, paths: list[str]):
        self._worker(paths)


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
