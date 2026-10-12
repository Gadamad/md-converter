"""The macOS webview interface. No network assets or UI framework required."""
HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MD Converter</title>
<style>
:root { color-scheme: light; --bg:#f5f6f4; --surface:#fff; --soft:#eff1ee; --ink:#202822; --muted:#616b64; --line:#d8ded8; --accent:#246b48; --accent-soft:#e6f1e9; --on-accent:#fff; --danger:#a43b40; --danger-soft:#fae9e9; --focus:#287b55; --shadow:0 18px 70px #15281f26; }
body[data-theme="dark"] { color-scheme:dark; --bg:#181c1a; --surface:#202622; --soft:#2a322c; --ink:#edf2ec; --muted:#a6b2a8; --line:#3b473e; --accent:#a3d7b2; --accent-soft:#2c4033; --on-accent:#163522; --danger:#f0a3a6; --danger-soft:#412b2d; --focus:#b3e7c3; --shadow:0 18px 70px #0006; }
* { box-sizing:border-box; } [hidden] { display:none!important; }
body { margin:0; height:100vh; background:var(--bg); color:var(--ink); font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; overflow:hidden; -webkit-user-select:none; user-select:none; }
button,input,textarea,select { font:inherit; } button { -webkit-app-region:no-drag; }
button { display:inline-flex; align-items:center; justify-content:center; gap:8px; min-height:36px; padding:7px 13px; border:1px solid var(--line); border-radius:8px; background:var(--surface); color:var(--ink); cursor:pointer; font-weight:550; white-space:nowrap; transition:none; }
button:hover:not(:disabled) { background:var(--soft); border-color:var(--muted); } button:disabled { opacity:.46; cursor:default; }
button:focus-visible,input:focus-visible,textarea:focus-visible,select:focus-visible,a:focus-visible { outline:3px solid var(--focus); outline-offset:3px; }
button.primary { background:var(--accent); color:var(--on-accent); border-color:var(--accent); min-width:148px; min-height:42px; }
button.primary:hover:not(:disabled) { filter:brightness(.94); background:var(--accent); border-color:var(--accent); }
button.quiet { background:transparent; border-color:transparent; } button.quiet:hover:not(:disabled) { border-color:transparent; background:var(--soft); }
button.danger { background:var(--danger-soft); border-color:var(--danger); color:var(--danger); min-height:42px; }
svg { width:18px; height:18px; flex:none; fill:none; stroke:currentColor; stroke-width:1.6; stroke-linecap:round; stroke-linejoin:round; }
.app { height:100%; max-width:1160px; margin:auto; padding:24px 28px 0; display:flex; flex-direction:column; gap:18px; }
.app-header { display:flex; align-items:center; justify-content:space-between; gap:20px; }
.brand { display:flex; align-items:center; gap:12px; } .brand-mark { display:grid; place-items:center; width:42px; height:42px; border-radius:12px; background:var(--accent); color:var(--on-accent); } .brand-mark svg { width:26px; height:26px; }
h1 { margin:0; font-size:21px; line-height:1.2; letter-spacing:-.5px; font-weight:650; } .tagline { margin:4px 0 0; color:var(--muted); font-size:12px; }
.source-heading { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:12px; }
.segmented { display:inline-flex; gap:2px; padding:3px; border:1px solid var(--line); border-radius:10px; background:var(--soft); }
.segmented button { min-height:30px; padding:4px 14px; background:transparent; border-color:transparent; border-radius:7px; color:var(--muted); font-size:13px; }
.segmented button[aria-selected="true"] { background:var(--surface); color:var(--ink); box-shadow:0 1px 3px #0001; }
.local-note { color:var(--muted); font-size:12px; display:flex; gap:5px; align-items:center; } .local-note svg { width:14px; height:14px; }
.drop-zone { width:100%; display:flex; flex-direction:column; gap:4px; min-height:114px; padding:18px; border:1px dashed var(--line); border-radius:12px; background:var(--surface); }
.drop-zone:hover:not(:disabled),.drop-zone.drag-over { border-color:var(--accent); background:var(--accent-soft); }
.drop-zone .drop-title { font-size:15px; font-weight:550; } .drop-zone .drop-subtitle { color:var(--muted); font-size:12px; font-weight:400; }
.drop-symbol { width:26px; height:26px; color:var(--accent); margin-bottom:2px; }
.input-toolbar { display:flex; gap:8px; align-items:center; margin-top:10px; } .input-hint { margin-left:auto; font-size:12px; color:var(--muted); }
.folder-choice { margin-left:auto; display:flex; align-items:center; gap:7px; min-height:36px; font-size:12px; color:var(--muted); cursor:pointer; white-space:nowrap; } .folder-choice input { margin:0; flex:none; } .folder-choice:has(input:disabled) { opacity:.46; cursor:default; }
textarea { display:block; resize:none; width:100%; height:130px; padding:14px; color:var(--ink); background:var(--surface); border:1px solid var(--line); border-radius:10px; line-height:1.5; -webkit-user-select:text; user-select:text; }
textarea::placeholder { color:var(--muted); }
.operations-shell { flex:1; min-height:170px; display:flex; flex-direction:column; border:1px solid var(--line); border-radius:12px; background:var(--surface); overflow:hidden; }
.workspace-toolbar { display:flex; align-items:center; justify-content:space-between; min-height:48px; padding:0 12px; border-bottom:1px solid var(--line); }
.workspace-tabs { display:flex; align-self:stretch; gap:18px; } .workspace-tabs button { position:relative; border:0; padding:0 3px; border-radius:0; background:transparent!important; font-size:13px; color:var(--muted); }
.workspace-tabs button[aria-selected="true"] { color:var(--ink); } .workspace-tabs button[aria-selected="true"]::after { content:""; position:absolute; height:2px; background:var(--accent); bottom:0; left:0; right:0; }
.queue-pagination { display:flex; align-items:center; gap:3px; margin-left:auto; margin-right:8px; }
.queue-pagination button { min-width:28px; min-height:28px; padding:2px 7px; font-size:18px; } #queue-page-range { color:var(--muted); font-size:11px; white-space:nowrap; font-variant-numeric:tabular-nums; }
.count { padding:1px 6px; border-radius:5px; background:var(--soft); font-size:11px; font-variant-numeric:tabular-nums; }
.small { font-size:12px; min-height:30px; padding:5px 9px; }
.queue-toolbar { display:flex; flex-direction:column; gap:7px; padding:10px 12px; border-bottom:1px solid var(--line); }
.queue-picker-heading { display:flex; align-items:center; flex-wrap:wrap; gap:8px; } .queue-picker-heading label { font-size:12px; font-weight:600; } .queue-picker-heading span { font-size:11px; color:var(--muted); }
.queue-details-choice { display:flex; align-items:center; gap:6px; margin-left:auto; white-space:nowrap; color:var(--muted); cursor:pointer; } .queue-picker-heading .queue-details-choice { font-weight:400; } .queue-details-choice input { margin:0; } .queue-details-choice:has(input:disabled) { opacity:.46; cursor:default; }
#queue-attention-btn { margin-left:auto; min-height:24px; padding:2px 7px; font-size:11px; } #queue-attention-btn[aria-pressed="true"] { color:var(--accent); background:var(--accent-soft); }
.queue-picker-controls { display:flex; align-items:center; gap:6px; }
.queue-picker-controls .delete-saved-queue { color:var(--danger); } .queue-picker-controls .delete-saved-queue:hover:not(:disabled) { background:var(--danger-soft); }
.queue-toolbar select { min-width:100px; max-width:280px; flex:1; height:32px; font-size:12px; background:var(--surface); }
.save-state { margin-left:auto; color:var(--muted); font-size:11px; white-space:nowrap; } .save-state.unsaved { color:var(--danger); }
.queue-status { font-size:11px; color:var(--muted); white-space:nowrap; } .queue-status.done { color:var(--accent); } .queue-status.failed { color:var(--danger); } .queue-status.processing { color:var(--accent); }
.queue-error { color:var(--danger); font-size:11px; line-height:1.45; margin-top:4px; overflow-wrap:anywhere; -webkit-user-select:text; user-select:text; }
.queue-error.review { color:var(--muted); }
.queue-item-actions { display:flex; align-items:center; gap:3px; }
.queue-actions-menu { position:fixed; z-index:2; min-width:168px; padding:5px; border:1px solid var(--line); border-radius:9px; background:var(--surface); }
.queue-actions-menu button { width:100%; justify-content:flex-start; } .queue-actions-menu button:last-child { color:var(--danger); }
.text-toolbar { margin-top:8px; } .text-toolbar .input-hint { margin:0; white-space:normal; } .text-toolbar button { margin-left:auto; }
.operations-panel { flex:1; min-height:0; overflow:auto; } .queue-empty { display:flex; height:100%; min-height:96px; align-items:center; justify-content:center; flex-direction:column; gap:4px; padding:18px; color:var(--muted); font-size:13px; text-align:center; } .queue-empty strong { font-weight:500; color:var(--ink); } .queue-empty p { margin:0; font-size:12px; }
.queue-empty.error strong { color:var(--danger); } .queue-empty.error p { max-width:64ch; overflow-wrap:anywhere; -webkit-user-select:text; user-select:text; }
.queue-row { display:flex; align-items:center; gap:12px; padding:13px 16px; border-bottom:1px solid var(--line); } .queue-row:last-child { border:0; }
.queue-row.compact { padding-top:7px; padding-bottom:7px; } .queue-row.compact .file-icon { height:30px; } .queue-row.compact .queue-meta { display:none; }
.file-icon { color:var(--accent); background:var(--accent-soft); border-radius:8px; width:34px; height:38px; display:grid; place-items:center; font-size:10px; font-weight:650; flex:none; }
.queue-copy { min-width:0; flex:1; } .queue-name { overflow:hidden; white-space:nowrap; text-overflow:ellipsis; font-size:13px; font-weight:550; } .queue-meta { color:var(--muted); font-size:11px; overflow:hidden; white-space:nowrap; text-overflow:ellipsis; margin-top:3px; }
.folder-remove-btn { color:var(--muted); font-size:12px; min-height:32px; padding:4px 9px; border-color:transparent; background:transparent; }
#log { -webkit-user-select:text; user-select:text; font:12px/1.75 ui-monospace,SFMono-Regular,Menlo,monospace; padding:12px 16px; overflow-wrap:anywhere; white-space:pre-wrap; }
.log-info { color:var(--muted); } .log-ok { color:var(--accent); } .log-error { color:var(--danger); } #log:empty::after { content:'Conversion details will appear here.'; color:var(--muted); }
.recovery { margin:12px; flex-shrink:0; background:var(--accent-soft); border:1px solid var(--line); border-radius:10px; padding:10px 14px; overflow:visible; } .recovery-heading { font-size:12px; font-weight:650; margin:0 0 6px; }
.recovery-row { display:flex; align-items:center; gap:8px; padding:7px 0; } .recovery-row+.recovery-row { border-top:1px solid var(--line); } .recovery-copy { flex:1; min-width:0; } .recovery-name { font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; } .recovery-meta { color:var(--muted); font-size:11px; }
.bottom { flex:none; padding-bottom:22px; } .status-line { display:flex; justify-content:space-between; align-items:baseline; gap:14px; padding:13px 16px 8px; border-top:1px solid var(--line); }
#summary { font-size:12px; overflow:hidden; white-space:nowrap; text-overflow:ellipsis; color:var(--muted); } #progress-label { font-size:11px; font-variant-numeric:tabular-nums; color:var(--muted); }
.progress-track { margin:0 16px 13px; height:4px; border-radius:8px; overflow:hidden; background:var(--soft); flex:none; } #progress { width:0; height:100%; background:var(--accent); transition:width .18s; border-radius:8px; }
.destination { display:flex; align-items:center; gap:7px; color:var(--muted); font-size:12px; margin:0 0 12px; } .destination svg { width:15px; height:15px; } #destination-path { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1; } .destination button { padding:0 3px; min-height:24px; font-size:12px; color:var(--accent); }
.save-options { display:flex; align-items:center; gap:24px; margin:-6px 0 12px; }
.copy-destination { display:flex; align-items:center; gap:9px; min-height:26px; flex:1; min-width:0; font-size:12px; color:var(--muted); }
.copy-destination label { display:flex; align-items:center; gap:7px; white-space:nowrap; cursor:pointer; } .copy-destination input { margin:0; flex:none; }
#copy-destination-path { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:11px; } #copy-destination-path.error { color:var(--danger); }
#copy-folder-change-btn { min-height:24px; padding:0 3px; font-size:12px; color:var(--accent); }
.action-row > button { min-height:42px; } .action-row { display:flex; align-items:center; justify-content:flex-end; gap:8px; } .vault-option { display:flex; align-items:center; gap:7px; min-height:26px; flex:none; font-size:12px; white-space:nowrap; color:var(--muted); } input[type="checkbox"] { width:15px; height:15px; accent-color:var(--accent); } .save-options input { margin:0; flex:none; }
#badge { display:none; } .visually-hidden { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
#preferences-modal { width:min(530px,calc(100vw - 48px)); border:1px solid var(--line); border-radius:16px; padding:0; color:var(--ink); background:var(--surface); box-shadow:var(--shadow); max-height:90vh; }
#preferences-modal::backdrop { background:#10181377; backdrop-filter:blur(4px); } .modal-header { display:flex; justify-content:space-between; align-items:center; padding:20px 22px; border-bottom:1px solid var(--line); } h2 { margin:0; font-size:18px; letter-spacing:-.3px; }
#queue-name-modal, #queue-delete-modal, #copy-folder-modal { width:min(410px,calc(100vw - 48px)); border:1px solid var(--line); border-radius:16px; padding:0; color:var(--ink); background:var(--surface); box-shadow:var(--shadow); max-height:90vh; }
#queue-name-modal::backdrop, #queue-delete-modal::backdrop, #copy-folder-modal::backdrop { background:#10181377; backdrop-filter:blur(4px); } #queue-name-modal .modal-body, #queue-delete-modal .modal-body, #copy-folder-modal .modal-body { padding:20px 22px; }
#queue-delete-title { overflow-wrap:anywhere; } #queue-delete-copy { margin:0; color:var(--muted); font-size:13px; line-height:1.6; } #queue-delete-modal .modal-footer button { min-height:36px; }
#queue-name-modal label, #copy-folder-modal label { display:block; font-size:13px; font-weight:550; margin-bottom:7px; } #queue-name-input, #copy-folder-input { width:100%; padding:9px 10px; border:1px solid var(--line); border-radius:8px; background:var(--surface); color:var(--ink); -webkit-user-select:text; user-select:text; }
#queue-name-error, #queue-delete-error, #copy-folder-error { color:var(--danger); font-size:12px; margin:9px 0 0; overflow-wrap:anywhere; }
#copy-folder-help { color:var(--muted); font-size:12px; line-height:1.5; margin:12px 0 0; } #copy-folder-preview { color:var(--muted); font-size:11px; overflow-wrap:anywhere; margin:7px 0 0; }
.modal-body { padding:4px 22px; } .setting { padding:17px 0; border-bottom:1px solid var(--line); } .setting:last-child { border:0; } .setting-top { display:flex; align-items:center; justify-content:space-between; gap:20px; } .setting label { font-weight:550; font-size:13px; } .setting p { font-size:12px; color:var(--muted); margin:5px 0 0; } select { color:var(--ink); background:var(--soft); border:1px solid var(--line); border-radius:7px; padding:7px; max-width:235px; } .path-row { display:flex; gap:8px; align-items:center; margin-top:10px; } .path-value { font-size:12px; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1; }
.modal-footer { display:flex; gap:8px; justify-content:flex-end; align-items:center; padding:16px 22px; background:var(--bg); border-top:1px solid var(--line); } .version { margin-right:auto; color:var(--muted); font-size:11px; } .modal-footer .primary { min-width:80px; min-height:36px; }
#toast { position:fixed; bottom:88px; left:50%; transform:translateX(-50%); background:var(--ink); color:var(--bg); padding:10px 16px; border-radius:9px; font-size:13px; box-shadow:var(--shadow); max-width:85%; z-index:5; }
@media(max-height:730px) { .app { padding-top:18px; gap:12px; } .drop-zone { min-height:94px; padding:10px; } .bottom { padding-bottom:16px; }  textarea { height:110px; } }
@media(max-height:700px) { .app { gap:10px; } .source-heading { margin-bottom:8px; } .drop-zone { min-height:72px; padding:8px; } .drop-symbol { display:none; } textarea { height:76px; } .workspace-toolbar { min-height:42px; } .queue-toolbar { padding-top:8px; padding-bottom:8px; } .bottom { padding-bottom:12px; } }
@media(max-width:680px) { .app { padding-left:20px; padding-right:20px; } .local-note { display:none; } .input-hint { font-size:11px; } .action-row { gap:6px; flex-wrap:wrap; } .save-options { gap:16px; } button.primary { min-width:130px; } .queue-row { gap:9px; padding:11px 12px; } .queue-item-actions { flex-direction:column; align-items:flex-end; gap:0; } .queue-toolbar select { max-width:none; } }
@media(prefers-reduced-motion:reduce) { *,*::before,*::after { transition:none!important; animation:none!important; } }
</style>
</head>
<body>
<svg aria-hidden="true" style="position:absolute;width:0;height:0"><defs>
<symbol id="i-file" viewBox="0 0 24 24"><path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8zM14 3v5h5M8 13h8M8 17h5"/></symbol>
<symbol id="i-folder" viewBox="0 0 24 24"><path d="M3 7V5a1 1 0 0 1 1-1h5l2 3h9a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7z"/></symbol>
<symbol id="i-plus" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></symbol>
<symbol id="i-sliders" viewBox="0 0 24 24"><path d="M4 7h5m4 0h7M4 17h9m4 0h3M9 4v6M13 14v6"/></symbol>
<symbol id="i-arrow" viewBox="0 0 24 24"><path d="M5 12h14m-5-5 5 5-5 5"/></symbol>
<symbol id="i-check" viewBox="0 0 24 24"><path d="m5 12 4 4L19 6"/></symbol>
</defs></svg>
<main class="app">
<header class="app-header">
 <div class="brand"><div class="brand-mark" aria-hidden="true"><svg viewBox="0 0 28 28"><path d="M4 20V8l5 6 5-6v12M20 8v12m-4-4 4 4 4-4" stroke-width="2"/></svg></div><div><h1>MD Converter</h1><p class="tagline">Your files, ready for Markdown.</p></div></div>
 <button id="preferences-btn" class="quiet" aria-haspopup="dialog"><svg><use href="#i-sliders"/></svg>Preferences</button>
</header>
<section aria-label="Choose a source">
 <div class="source-heading"><div class="segmented" role="tablist" aria-label="Source"><button id="files-tab" role="tab" aria-selected="true" aria-controls="files-source">Files & folders</button><button id="text-tab" role="tab" aria-selected="false" aria-controls="text-source" tabindex="-1">Text or URL</button></div><span class="local-note"><svg><use href="#i-check"/></svg>File conversion stays on your Mac</span></div>
 <div id="files-source" role="tabpanel" aria-labelledby="files-tab">
  <button id="drop-zone" class="drop-zone" aria-label="Drop files, links or text here, or browse files"><svg class="drop-symbol"><use href="#i-file"/></svg><span class="drop-title">Drop something worth keeping</span><span class="drop-subtitle">Files, folders, website links & text</span></button>
  <div class="input-toolbar"><button id="add-files-btn"><svg><use href="#i-plus"/></svg>Add files</button><button id="add-folder-btn"><svg><use href="#i-folder"/></svg>Add folder</button><label class="folder-choice" title="Checked: include nested folders. Unchecked: only files directly in the chosen folder."><input id="include-subfolders-cb" type="checkbox" checked aria-label="Include subfolders" aria-describedby="folder-choice-help">Include subfolders</label></div>
  <span id="folder-choice-help" class="visually-hidden">Applies when adding or dropping folders. Checked includes nested folders; unchecked includes only files directly in the chosen folder. Existing queued items stay unchanged.</span>
 </div>
 <div id="text-source" role="tabpanel" aria-labelledby="text-tab" hidden><label for="url-input" class="visually-hidden">Text or website URLs to add to the queue</label><textarea id="url-input" placeholder="Paste text, or website URLs on separate lines…" spellcheck="false" aria-describedby="text-intake-help"></textarea><div class="input-toolbar text-toolbar"><span id="text-intake-help" class="input-hint">Pages are fetched when you convert the queue.</span><button id="add-text-btn" disabled><svg><use href="#i-plus"/></svg>Add to queue</button></div></div>
</section>

<section class="operations-shell" aria-label="Conversion workspace">
 <div class="workspace-toolbar"><div class="workspace-tabs" role="tablist" aria-label="Workspace"><button id="queue-tab" role="tab" aria-selected="true" aria-controls="queue-panel">Queue <span id="queue-count" class="count">0</span></button><button id="activity-tab" role="tab" aria-selected="false" aria-controls="log-container" tabindex="-1">Activity <span id="activity-alert" class="count" hidden>!</span></button></div><div id="queue-pagination" class="queue-pagination" role="group" aria-label="Queue pages" hidden><button id="queue-prev-btn" class="quiet" aria-label="Previous queue page">‹</button><span id="queue-page-range" role="status" aria-live="polite"></span><button id="queue-next-btn" class="quiet" aria-label="Next queue page">›</button></div><button id="queue-actions-btn" class="quiet small" aria-haspopup="menu" aria-controls="queue-actions-menu" aria-expanded="false" disabled>Queue actions</button><button id="copy-btn" class="quiet small" hidden>Copy log</button></div>
 <div id="queue-toolbar" class="queue-toolbar"><div class="queue-picker-heading"><label for="queue-select">Saved queues</label><span id="queue-select-hint">Choose a name to reopen it.</span><label class="queue-details-choice" title="Show full URLs and source file paths in the queue"><input id="show-source-details-cb" type="checkbox" disabled>Show source details</label><button id="queue-attention-btn" class="quiet small" aria-pressed="false" hidden>Needs attention</button></div><div class="queue-picker-controls"><select id="queue-select" aria-describedby="queue-select-hint" disabled><option>Loading queue…</option></select><button id="new-queue-btn" class="quiet small" aria-haspopup="dialog" disabled>New</button><button id="rename-queue-btn" class="quiet small" aria-haspopup="dialog" disabled>Rename</button><button id="delete-saved-queue-btn" class="quiet small delete-saved-queue" aria-haspopup="dialog" aria-controls="queue-delete-modal" disabled>Delete queue…</button><span id="queue-save-state" class="save-state" role="status" aria-live="polite">Loading…</span></div></div>
 <div class="operations-panel">
  <section id="recovery-panel" class="recovery" aria-labelledby="recovery-title" hidden><h2 id="recovery-title" class="recovery-heading">Continue where you left off</h2><div id="recovery-jobs"></div></section>
  <div id="queue-panel" role="tabpanel" aria-labelledby="queue-tab"><div id="folder-queue"></div><div id="queue-empty" class="queue-empty"><strong id="queue-empty-title">A little order for your next idea.</strong><p id="queue-empty-copy">Add files, links or text, then convert when you’re ready.</p></div></div>
  <div id="log-container" role="tabpanel" aria-labelledby="activity-tab" hidden><div id="log" role="log" aria-label="Conversion activity" aria-live="off"></div></div>
 </div>
 <div class="status-line"><span id="summary" role="status" aria-live="polite">Ready when you are</span><span id="progress-label">0%</span></div><div class="progress-track" role="progressbar" aria-label="Conversion progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><div id="progress"></div></div>
</section>
<footer class="bottom">
 <div class="destination"><svg><use href="#i-folder"/></svg><span>Save to</span><span id="destination-path">Default output folder</span><button id="change-output-btn" class="quiet">Change…</button></div>
 <div class="save-options"><div class="copy-destination"><label><input id="copy-subfolder-cb" type="checkbox" aria-describedby="copy-destination-path">Save to a named folder</label><span id="copy-destination-path">Extra copy of finished Markdown</span><button id="copy-folder-change-btn" class="quiet" aria-haspopup="dialog" hidden>Change name…</button></div><label class="vault-option" id="vault-option"><input id="vault-cb" type="checkbox" VAULT_CHECKED>Copy to Obsidian vault</label></div>
 <div class="action-row"><button id="open-btn"><svg><use href="#i-folder"/></svg>Open output</button><button id="retry-failed-btn" hidden>Retry failed</button><button id="convert-btn" class="primary" disabled>Convert queue<svg><use href="#i-arrow"/></svg></button><button id="abort-btn" class="danger" hidden>Stop & save</button></div>
 <span id="badge"></span>
</footer>
</main>
<dialog id="copy-folder-modal" aria-labelledby="copy-folder-title"><form id="copy-folder-form"><div class="modal-header"><h2 id="copy-folder-title">Name your copy folder</h2></div><div class="modal-body"><label for="copy-folder-input">Folder name</label><input id="copy-folder-input" type="text" required autocomplete="off" autofocus aria-describedby="copy-folder-help copy-folder-preview copy-folder-error"><p id="copy-folder-help">Finished Markdown will also be copied into this folder inside Save to. Your regular exports stay in place.</p><p id="copy-folder-preview"></p><p id="copy-folder-error" role="alert" hidden></p></div><div class="modal-footer"><button id="copy-folder-cancel-btn" type="button">Cancel</button><button id="copy-folder-save-btn" type="submit" class="primary">Use folder</button></div></form></dialog>
<div id="queue-actions-menu" class="queue-actions-menu" role="menu" aria-label="Queue actions" hidden><button id="clear-completed-btn" class="quiet small" role="menuitem" disabled>Clear completed</button><button id="clear-folders-btn" class="quiet small" role="menuitem" disabled>Clear all items</button><button id="delete-queue-btn" class="quiet small" role="menuitem" aria-haspopup="dialog" disabled>Delete queue…</button></div>
<dialog id="queue-delete-modal" aria-labelledby="queue-delete-title" aria-describedby="queue-delete-copy"><div class="modal-header"><h2 id="queue-delete-title">Delete queue?</h2></div><div class="modal-body"><p id="queue-delete-copy"></p><p id="queue-delete-error" role="alert" hidden></p></div><div class="modal-footer"><button id="queue-delete-cancel-btn" autofocus>Cancel</button><button id="queue-delete-confirm-btn" class="danger">Delete queue</button></div></dialog>
<dialog id="queue-name-modal" aria-labelledby="queue-name-title"><form id="queue-name-form"><div class="modal-header"><h2 id="queue-name-title">New queue</h2></div><div class="modal-body"><label for="queue-name-input">Queue name</label><input id="queue-name-input" type="text" maxlength="120" required autocomplete="off" autofocus aria-describedby="queue-name-error"><p id="queue-name-error" role="alert" hidden></p></div><div class="modal-footer"><button id="queue-name-cancel-btn" type="button">Cancel</button><button id="queue-name-save-btn" type="submit" class="primary">Create queue</button></div></form></dialog>
<dialog id="preferences-modal" aria-labelledby="preferences-title">
 <div class="modal-header"><h2 id="preferences-title">Preferences</h2><button id="preferences-close-btn" class="quiet small" aria-label="Close preferences">✕</button></div>
 <div class="modal-body">
  <div class="setting"><div class="setting-top"><label for="theme-select">Appearance</label><select id="theme-select"><option value="system">Match your Mac</option><option value="light">Light</option><option value="dark">Dark</option></select></div><p>A comfortable workspace, day or night.</p></div>
  <div class="setting"><label>Output folder</label><p>Keep converted files together, organized by format.</p><div class="path-row"><span id="output-dir-value" class="path-value">Default output folder</span><button id="output-dir-reset-btn" class="quiet small">Reset</button><button id="output-dir-browse-btn" class="small">Choose…</button></div></div>
  <div class="setting"><div class="setting-top"><label for="raw-ocr-mode-select">Original image text</label><select id="raw-ocr-mode-select"><option value="different">Include when different</option><option value="always">Always include</option><option value="never">Never include</option></select></div><p>Keep the original recognition alongside the cleaned-up quote.</p></div>
  <div class="setting"><div class="setting-top"><label for="auto-open-output-cb">Open output after conversion</label><input id="auto-open-output-cb" type="checkbox"></div><p>Reveal your converted files in Finder when work finishes.</p></div>
 </div>
 <div id="vault-setting" class="setting" style="margin:0 22px" hidden><div class="setting-top"><label>Obsidian vault</label><button id="vault-btn" class="small">Open vault</button></div></div>
 <div class="modal-footer"><span class="version" id="app-version">MD Converter</span><button id="preferences-cancel-btn">Cancel</button><button id="preferences-save-btn" class="primary">Save</button></div>
</dialog>
<div id="toast" role="alert" hidden></div>
<script>
'use strict';
const $ = id => document.getElementById(id);
let busy = false, canStop = false, queued = 0, sourceMode = 'files', workspaceMode = 'queue';
let queueState = {active_id:null,queues:[],items:[],waiting:0,failed:0,done:0,total:0,saved:false};
let queueAttentionOnly = false;
let queueReady = false, queueMutationPending = false, folderPreferencePending = false, displayPreferencePending = false, queueNameMode = 'create', queueNameReturnFocus = null, lastSaveError = '';
let queueDeleteId = null, queueDeleteReturnFocus = null;
let copyPreferencePending = false, copyFolderReturnFocus = null, lastCopySubfolder = '';
const QUEUE_PAGE_SIZE = 200;
let queuePage = 0;
let savedPreferences = {theme:'system',raw_ocr_mode:'different',output_dir:null,auto_open_output:false,include_subfolders:true,show_source_details:false,copy_subfolder:null};
let applicationState = {}, toastTimer;
const themeMedia = window.matchMedia('(prefers-color-scheme: dark)');
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 4500); }
async function callApi(name, ...args) {
 try { if (!window.pywebview) throw Error('The app is not connected yet. Please try again.'); return await pywebview.api[name](...args); }
 catch(error) { const message = error.message || String(error); toast(message); for (const kind of ['name','delete']) { if ($('queue-'+kind+'-modal').open) { $('queue-'+kind+'-error').textContent = message; $('queue-'+kind+'-error').hidden = false; } } return false; }
}
function icon(name) { const svg = document.createElementNS('http://www.w3.org/2000/svg','svg'); const use = document.createElementNS(svg.namespaceURI,'use'); use.setAttribute('href','#i-'+name); svg.appendChild(use); svg.setAttribute('aria-hidden','true'); return svg; }
function queueUnavailable() { return queueReady && !queueState.active_id && queueState.saved === false; }
function updateActions() {
 const locked = busy || queueMutationPending || folderPreferencePending || displayPreferencePending || copyPreferencePending, unavailable = queueUnavailable();
 $('convert-btn').disabled = locked || unavailable || !queued;
 $('convert-btn').title = queued ? `Convert ${queued} waiting ${queued === 1 ? 'item' : 'items'}` : 'Add items to the queue to convert';
 $('convert-btn').hidden = busy && canStop; $('abort-btn').hidden = !(busy && canStop);
 for (const id of ['files-tab','text-tab','preferences-btn','change-output-btn','vault-cb']) $(id).disabled = locked;
 for (const id of ['add-files-btn','add-folder-btn','include-subfolders-cb','drop-zone','url-input']) $(id).disabled = locked || unavailable;
 $('include-subfolders-cb').disabled = locked || unavailable || !queueReady;
 $('show-source-details-cb').disabled = locked || displayPreferencePending || !queueReady;
 $('copy-subfolder-cb').disabled = locked;
 $('copy-folder-change-btn').disabled = locked || !savedPreferences.copy_subfolder;
 $('copy-folder-save-btn').disabled = locked || !$('copy-folder-input').value.trim();
 $('copy-folder-input').disabled = busy || copyPreferencePending;
 $('copy-folder-cancel-btn').disabled = copyPreferencePending;
 if (!applicationState.vault_configured) $('vault-cb').disabled = true;
 $('add-text-btn').disabled = locked || unavailable || !$('url-input').value.trim();
 $('queue-select').disabled = $('new-queue-btn').disabled = locked || unavailable || !queueReady;
 $('rename-queue-btn').disabled = locked || !queueState.active_id;
 $('queue-actions-btn').disabled = locked || !(queueReady ? queueState.active_id : queued);
 $('delete-queue-btn').disabled = $('delete-saved-queue-btn').disabled = locked || !queueState.active_id;
 $('queue-delete-confirm-btn').disabled = locked || !queueDeleteId;
 $('queue-delete-cancel-btn').disabled = queueMutationPending;
 $('clear-folders-btn').disabled = locked || !(queueReady ? queueState.total : queued);
 $('clear-completed-btn').disabled = locked || !queueState.done;
 $('retry-failed-btn').hidden = !queueState.failed || (busy && canStop);
 $('retry-failed-btn').disabled = locked || unavailable || !queueState.failed;
 $('queue-name-save-btn').disabled = locked || !$('queue-name-input').value.trim();
 $('queue-name-input').disabled = queueMutationPending;
 document.querySelectorAll('.folder-remove-btn, .queue-locate-btn, .queue-recovery-btn, .recovery-row button').forEach(button => button.disabled = locked);
 $('queue-attention-btn').disabled = locked || unavailable;
 renderQueuePagination();
 if (locked) closeQueueActions();
}
function setBusy(value) { $('abort-btn').disabled = false; busy = value; document.body.dataset.busy = String(value); updateActions(); }
function showAbortButton() { canStop = true; updateActions(); }
function hideAbortButton() { canStop = false; updateActions(); }
function showConvertButton() { updateActions(); }
function hideConvertButton() { updateActions(); }
function setBadge(text) { $('badge').textContent = text || ''; }
function getVaultChecked() { return $('vault-cb').checked; }
function setProgress(value) { const pct = Math.max(0,Math.min(100,value)); $('progress').style.width = pct+'%'; $('progress-label').textContent = Math.round(pct)+'%'; document.querySelector('.progress-track').setAttribute('aria-valuenow',String(Math.round(pct))); }
function setSummary(text) { $('summary').textContent = text; $('summary').title = text; }
function appendLog(text, cls='log-info') { const line = document.createElement('div'); line.className = cls; line.textContent = text; $('log').appendChild(line); while ($('log').childElementCount > 1500) $('log').firstElementChild.remove(); if (cls === 'log-error') $('activity-alert').hidden = false; if (workspaceMode === 'activity') document.querySelector('.operations-panel').scrollTop = document.querySelector('.operations-panel').scrollHeight; }
function showWorkspace(mode) { workspaceMode = mode; const queue = mode === 'queue'; $('queue-panel').hidden = !queue; $('log-container').hidden = queue; $('queue-toolbar').hidden = !queue; $('queue-actions-btn').hidden = !queue; $('copy-btn').hidden = queue; closeQueueActions(); renderQueuePagination(); for (const [id,selected] of [['queue-tab',queue],['activity-tab',!queue]]) { $(id).setAttribute('aria-selected',String(selected)); $(id).tabIndex = selected ? 0 : -1; } if (!queue) $('activity-alert').hidden = true; }
function showLogPanel() { showWorkspace('activity'); }
function switchSource(mode) { sourceMode = mode; const files = mode === 'files'; $('files-source').hidden = !files; $('text-source').hidden = files; for (const [id,selected] of [['files-tab',files],['text-tab',!files]]) { $(id).setAttribute('aria-selected',String(selected)); $(id).tabIndex = selected ? 0 : -1; } updateActions(); }
function renderQueueSaveState() {
 const label = $('queue-save-state');
 label.textContent = queueMutationPending ? 'Saving…' : !queueReady ? 'Loading…' : queueState.saved === true ? 'Saved' : 'Not saved';
 label.classList.toggle('unsaved',queueReady && !queueMutationPending && queueState.saved !== true);
 label.title = queueMutationPending ? 'Saving this queue on your Mac' : queueState.saved === true ? 'Queue saved on your Mac' : 'This queue has not been saved';
}
function visibleQueueItems(state=queueState) { return queueAttentionOnly ? state.items.filter(item => ['failed','review'].includes(item.status)) : state.items; }
function renderQueuePagination() {
 const count = visibleQueueItems().length, start = queuePage * QUEUE_PAGE_SIZE;
 $('queue-pagination').hidden = workspaceMode !== 'queue' || count <= QUEUE_PAGE_SIZE;
 $('queue-page-range').textContent = `${(count ? start+1 : 0).toLocaleString()}–${Math.min(start+QUEUE_PAGE_SIZE,count).toLocaleString()} of ${count.toLocaleString()}`;
 $('queue-prev-btn').disabled = busy || queueMutationPending || folderPreferencePending || copyPreferencePending || queuePage === 0;
 $('queue-next-btn').disabled = busy || queueMutationPending || folderPreferencePending || copyPreferencePending || start+QUEUE_PAGE_SIZE >= count;
}
function changeQueuePage(delta) {
 if (busy || queueMutationPending || folderPreferencePending || copyPreferencePending) return;
 queuePage = Math.max(0,Math.min(queuePage+delta,Math.ceil(visibleQueueItems().length/QUEUE_PAGE_SIZE)-1));
 renderSavedQueue(queueState); document.querySelector('.operations-panel').scrollTop = 0;
}
function renderSavedQueue(state) {
 if (!state || !Array.isArray(state.items) || !Array.isArray(state.queues)) return;
 const receivedItems = state.active_id === queueState.active_id && state.total > queueState.total;
 if (state.active_id !== queueState.active_id) { queuePage = 0; queueAttentionOnly = false; }
 const visibleItems = visibleQueueItems(state);
 queuePage = Math.max(0,Math.min(queuePage,Math.ceil(visibleItems.length/QUEUE_PAGE_SIZE)-1));
 queueReady = true; queueState = state; queued = state.waiting || 0;
 const unavailable = queueUnavailable();
 if (typeof state.busy === 'boolean') busy = state.busy;
 document.body.dataset.busy = String(busy);
 const selector = $('queue-select'); selector.replaceChildren();
 for (const queue of state.queues) { const option = document.createElement('option'); option.value = queue.id; option.textContent = queue.name; selector.appendChild(option); }
 if (unavailable) { const option = document.createElement('option'); option.value = ''; option.textContent = 'Saved queues unavailable'; selector.appendChild(option); }
 selector.value = state.active_id || ''; selector.title = state.queues.find(queue => queue.id === state.active_id)?.name || '';
 const attention = (state.failed || 0)+(state.review || 0);
 $('queue-attention-btn').hidden = !attention && !queueAttentionOnly;
 $('queue-attention-btn').textContent = queueAttentionOnly ? 'Show all items' : 'Needs attention · '+attention;
 $('queue-attention-btn').setAttribute('aria-pressed',String(queueAttentionOnly));
 $('queue-count').textContent = String(state.total || 0); $('queue-empty').hidden = Boolean(visibleItems.length) && !unavailable;
 $('queue-empty').classList.toggle('error',unavailable);
 $('queue-empty-title').textContent = unavailable ? 'Saved queues need attention' : queueAttentionOnly ? 'Nothing needs attention.' : 'A little order for your next idea.';
 $('queue-empty-copy').textContent = unavailable ? state.save_error || state.error || 'Saved queues are unavailable. Restart the app to try again.' : queueAttentionOnly ? 'Your completed conversions are saved. Show all items to see them.' : 'Add files, links or text, then convert when you’re ready.';
 const rows = document.createDocumentFragment();
 for (const item of visibleItems.slice(queuePage*QUEUE_PAGE_SIZE,(queuePage+1)*QUEUE_PAGE_SIZE)) {
  const row = document.createElement('div'); row.className = 'queue-row'+(savedPreferences.show_source_details ? '' : ' compact'); row.dataset.itemId = item.id;
  const symbol = document.createElement('div'); symbol.className = 'file-icon'; symbol.setAttribute('aria-hidden','true');
  symbol.textContent = item.kind === 'url' ? 'WEB' : item.kind === 'text' ? 'TXT' : (item.title || item.source || '').split('.').pop().slice(0,4).toUpperCase();
  const copy = document.createElement('div'); copy.className = 'queue-copy';
  const name = document.createElement('div'); name.className = 'queue-name'; name.textContent = item.title || (item.kind === 'text' ? 'Pasted text' : item.source); name.title = item.source || name.textContent;
  const meta = document.createElement('div'); meta.className = 'queue-meta';
  const group = item.group_name?.split(/[\\/]/).filter(Boolean).pop();
  const repeatedUrl = item.kind === 'url' && (!item.title || item.title === item.source || item.title === item.source?.slice(0,80));
  if (repeatedUrl) { try { const url = new URL(item.source); const path = decodeURIComponent(url.pathname).replace(/^\/+|\/+$/g,''); name.textContent = url.hostname+(path ? ' · '+path : ''); } catch (_) {} }
  const sourceDescription = item.kind === 'text' ? 'Pasted text' : item.source;
  meta.textContent = [group,sourceDescription].filter(Boolean).join(' · '); meta.title = [item.group_name,item.source].filter(Boolean).join(' · ');
  copy.append(name,meta);
  if (item.error) { const error = document.createElement('div'); error.className = 'queue-error'+(item.status === 'review' ? ' review' : ''); error.textContent = item.error; copy.appendChild(error); }
  const status = document.createElement('span'); status.className = 'queue-status '+item.status; status.textContent = {waiting:'Waiting',processing:'Converting',done:'Done',failed:'Failed',review:'Needs review'}[item.status] || item.status;
  if (item.output_path) status.title = item.output_path;
  const actions = document.createElement('div'); actions.className = 'queue-item-actions';
  const needsReview = item.kind === 'file' && ['failed','review'].includes(item.status);
  if (item.status === 'done') { const open = document.createElement('button'); open.className = 'quiet small queue-recovery-btn queue-open-btn'; open.textContent = 'Open'; const target = item.kind === 'file' ? 'original' : 'output'; open.setAttribute('aria-label','Open '+target+' '+name.textContent); open.title = item.kind === 'file' ? 'Open the original source file' : 'Open the saved Markdown output'; open.onclick = () => callApi('open_queue_item',item.id); actions.appendChild(open); }
  if (needsReview) {
   for (const [label,action] of [['Preview',()=>callApi('preview_queue_item',item.id)],['Try again',()=>startItemRetry(item.id)],['Skip',()=>mutateQueue('skip_queue_item',item.id)]]) { const button = document.createElement('button'); button.className = 'quiet small queue-recovery-btn'; button.textContent = label; button.setAttribute('aria-label',label+' '+name.textContent); if (label === 'Skip') button.title = 'Keep the original file and record this item as skipped'; button.onclick = action; actions.appendChild(button); }
  }
  if (item.kind === 'file' && item.status === 'failed' && /locate|moved|missing|not found/i.test(item.error || '')) { const locate = document.createElement('button'); locate.className = 'quiet small queue-locate-btn'; locate.textContent = 'Locate file'; locate.setAttribute('aria-label','Locate file for '+name.textContent); locate.onclick = () => mutateQueue('locate_queue_item',item.id); actions.appendChild(locate); }
  if (!needsReview) { const remove = document.createElement('button'); remove.className = 'btn folder-remove-btn'; remove.textContent = 'Remove'; remove.setAttribute('aria-label','Remove '+name.textContent); remove.onclick = () => mutateQueue('remove_queue_item',item.id); actions.appendChild(remove); }
  row.append(symbol,copy,status,actions); rows.appendChild(row);
 }
 $('folder-queue').replaceChildren(rows); renderQueueSaveState();
 const saveError = state.save_error || state.error || '';
 if (state.saved !== true && saveError && saveError !== lastSaveError) toast(saveError);
 lastSaveError = state.saved === true ? '' : saveError;
 if (!busy) setSummary(unavailable ? 'Saved queues unavailable' : state.total ? [state.waiting ? state.waiting+' waiting' : '',state.failed ? state.failed+' failed' : '',state.review ? state.review+' need review' : '',state.done ? state.done+' done' : ''].filter(Boolean).join(' · ') : 'Ready when you are');
 if (!busy) setProgress(state.total ? 100*((state.done || 0)+(state.failed || 0)+(state.review || 0))/state.total : 0);
 if (receivedItems && !busy && !queueMutationPending) showWorkspace('queue');
 updateActions();
}
async function mutateQueue(name,...args) {
 if (busy || queueMutationPending || folderPreferencePending || copyPreferencePending || queueUnavailable()) return false;
 const focused = document.activeElement, focusedRow = focused?.closest('#folder-queue .queue-row');
 const rowIndex = focusedRow ? [...$('folder-queue').children].indexOf(focusedRow) : -1;
 const restoreRowFocus = rowIndex >= 0 && focused.tagName === 'BUTTON';
 queueMutationPending = true; renderQueueSaveState(); updateActions();
 try {
  const state = await callApi(name,...args);
  if (state && Array.isArray(state.items)) { renderSavedQueue(state); return state; }
  return false;
 } finally {
  queueMutationPending = false; renderQueueSaveState(); updateActions();
  if (restoreRowFocus && (document.activeElement === focused || document.activeElement === document.body)) {
   const rows = [...$('folder-queue').children], row = rows.find(row => row.dataset.itemId === focusedRow.dataset.itemId) || rows[Math.min(rowIndex,rows.length-1)];
   (row?.querySelector(focused.classList.contains('queue-locate-btn') ? '.queue-locate-btn, .queue-recovery-btn, .folder-remove-btn' : '.queue-recovery-btn, .folder-remove-btn') || $('queue-select')).focus();
  }
 }
}
function closeQueueActions(restoreFocus=false) { $('queue-actions-menu').hidden = true; $('queue-actions-btn').setAttribute('aria-expanded','false'); if (restoreFocus) $('queue-actions-btn').focus(); }
function openDeleteQueue(event) {
 if (busy || queueMutationPending) return;
 const queue = queueState.queues.find(queue => queue.id === queueState.active_id);
 if (!queue) return;
 const trigger = event?.currentTarget;
 queueDeleteReturnFocus = trigger?.closest('#queue-actions-menu') ? $('queue-actions-btn') : trigger || $('delete-saved-queue-btn');
 closeQueueActions(); queueDeleteId = queue.id;
 $('queue-delete-title').textContent = `Delete “${queue.name}”?`;
 $('queue-delete-copy').textContent = `This removes the saved queue and its ${queueState.total || 0} ${(queueState.total || 0) === 1 ? 'item' : 'items'}. Original files and converted Markdown are kept. This cannot be undone.`+(queueState.queues.length === 1 ? ' A new, empty Inbox will be created.' : ' Your other queues are kept.');
 $('queue-delete-error').hidden = true; $('queue-delete-error').textContent = '';
 updateActions(); $('queue-delete-modal').showModal(); $('queue-delete-cancel-btn').focus();
}
function openQueueActions() {
 if ($('queue-actions-btn').disabled) return;
 if (!$('queue-actions-menu').hidden) { closeQueueActions(true); return; }
 const menu = $('queue-actions-menu'), rect = $('queue-actions-btn').getBoundingClientRect();
 menu.hidden = false; menu.style.top = rect.bottom+5+'px'; menu.style.left = Math.max(8,Math.min(window.innerWidth-menu.offsetWidth-8,rect.right-menu.offsetWidth))+'px';
 $('queue-actions-btn').setAttribute('aria-expanded','true'); menu.querySelector('button:not(:disabled)')?.focus();
}
function openQueueName(mode) {
 if (busy || queueMutationPending) return;
 queueNameMode = mode; queueNameReturnFocus = document.activeElement;
 $('queue-name-title').textContent = mode === 'create' ? 'New queue' : 'Rename queue';
 $('queue-name-save-btn').textContent = mode === 'create' ? 'Create queue' : 'Rename queue';
 $('queue-name-input').value = mode === 'create' ? '' : queueState.queues.find(queue => queue.id === queueState.active_id)?.name || '';
 $('queue-name-error').hidden = true; $('queue-name-error').textContent = '';
 updateActions(); $('queue-name-modal').showModal(); $('queue-name-input').focus(); $('queue-name-input').select();
}
function renderFolderQueue(items, state={}) {
 const files = state.files || []; queued = state.total_count ?? ((state.file_count || 0) + items.reduce((n,item) => n + item.file_count,0));
 $('queue-count').textContent = String(queued); $('folder-queue').replaceChildren(); $('queue-empty').hidden = Boolean(queued);
 const all = [...items.map(item => ({...item,folder:true})),...files];
 for (const item of all) {
  const row = document.createElement('div'); row.className = 'queue-row';
  const symbol = document.createElement('div'); symbol.className = 'file-icon'; if (item.folder) symbol.appendChild(icon('folder')); else symbol.textContent = item.name.split('.').pop().slice(0,4).toUpperCase();
  const copy = document.createElement('div'); copy.className = 'queue-copy';
  const name = document.createElement('div'); name.className = 'queue-name'; name.textContent = item.name;
  const meta = document.createElement('div'); meta.className = 'queue-meta'; meta.textContent = (item.folder ? item.file_count+(item.file_count === 1 ? ' file · ' : ' files · ') : '')+item.path; copy.title = item.path; copy.append(name,meta);
  const remove = document.createElement('button'); remove.className = 'btn folder-remove-btn'; remove.textContent = 'Remove'; remove.setAttribute('aria-label','Remove '+item.name); remove.onclick = () => callApi(item.folder ? 'remove_staged_folder' : 'remove_staged_file',item.folder ? item.id : item.path);
  row.append(symbol,copy,remove); $('folder-queue').appendChild(row);
 }
 if (!busy && queued) showWorkspace('queue'); updateActions();
}
function renderRecoveryJobs(jobs) {
 $('recovery-jobs').replaceChildren(); $('recovery-panel').hidden = !jobs.length;
 for (const job of jobs) {
  const row = document.createElement('div'); row.className = 'recovery-row';
  const copy = document.createElement('div'); copy.className = 'recovery-copy'; const name = document.createElement('div'); name.className = 'recovery-name'; name.textContent = job.name; name.title = job.id;
  const meta = document.createElement('div'); meta.className = 'recovery-meta'; meta.textContent = `${job.saved} saved · ${job.pending} remaining` + (job.failed ? ` · ${job.failed} failed` : '') + (job.vault_pending ? ' · Vault delivery pending' : ''); copy.append(name,meta); row.appendChild(copy);
  for (const retry of [false,true]) { if (retry ? !job.failed : !(job.pending || job.needs_finish)) continue; const button = document.createElement('button'); button.className = 'small'; button.textContent = retry ? 'Retry failed' : job.needs_finish ? 'Finish export' : 'Resume'; button.setAttribute('aria-label',button.textContent+' · '+job.name); button.onclick = async () => { if (busy) return; setBusy(true); const started = await callApi('recover_job',job.id,retry); if (!started) setBusy(false); }; row.appendChild(button); }
  $('recovery-jobs').appendChild(row);
 }
 updateActions();
}
function renderApplicationState(state) { applicationState = state; $('destination-path').textContent = state.output_dir || 'Default output folder'; $('destination-path').title = state.output_dir || ''; $('app-version').textContent = 'MD Converter '+(state.version || ''); $('vault-option').title = state.vault_configured ? 'Also save a copy in your configured vault' : 'No Obsidian vault configured'; $('vault-setting').hidden = !state.vault_configured; if (!state.vault_configured) $('vault-cb').checked = false; renderRecoveryJobs(state.recovery_jobs || []); if (state.queue) renderSavedQueue(state.queue); renderCopyDestination(); updateActions(); }
function applyPreferences(prefs) { const previousCopy = savedPreferences.copy_subfolder; savedPreferences = {...prefs,include_subfolders:prefs.include_subfolders !== false,show_source_details:prefs.show_source_details === true,copy_subfolder:typeof prefs.copy_subfolder === 'string' ? prefs.copy_subfolder : null}; if (savedPreferences.copy_subfolder) lastCopySubfolder = savedPreferences.copy_subfolder; if (previousCopy !== savedPreferences.copy_subfolder) applicationState = {...applicationState,copy_dir:null,copy_error:''}; document.body.dataset.theme = prefs.theme === 'system' ? (themeMedia.matches ? 'dark' : 'light') : prefs.theme; $('theme-select').value = prefs.theme; $('raw-ocr-mode-select').value = prefs.raw_ocr_mode; $('output-dir-value').textContent = prefs.output_dir || 'Default output folder'; $('output-dir-value').title = prefs.output_dir || ''; $('auto-open-output-cb').checked = Boolean(prefs.auto_open_output); $('include-subfolders-cb').checked = savedPreferences.include_subfolders; $('show-source-details-cb').checked = savedPreferences.show_source_details; document.querySelectorAll('#folder-queue .queue-row').forEach(row=>row.classList.toggle('compact',!savedPreferences.show_source_details)); renderCopyDestination(); }
function copyPathPreview(name) { const base = applicationState.output_dir || savedPreferences.output_dir; return base && name ? base.replace(/\/$/,'')+'/'+name : 'Extra copy inside the Save to folder'; }
function renderCopyDestination() {
 const name = savedPreferences.copy_subfolder, error = name && applicationState.copy_error;
 $('copy-subfolder-cb').checked = Boolean(name); $('copy-folder-change-btn').hidden = !name;
 const path = $('copy-destination-path'); path.textContent = error || (name ? applicationState.copy_dir || copyPathPreview(name) : 'Extra copy of finished Markdown'); path.title = path.textContent; path.classList.toggle('error',Boolean(error));
}
function openCopyFolder(control) {
 if (busy || queueMutationPending || folderPreferencePending || displayPreferencePending || copyPreferencePending) { renderCopyDestination(); return; }
 copyFolderReturnFocus = control || $('copy-subfolder-cb');
 let suggestion = queueState.queues.find(queue => queue.id === queueState.active_id)?.name || '';
 if (['quotes','pdf','docx','spreadsheets','html','txt','rtf'].includes(suggestion.toLowerCase())) suggestion += ' exports';
 $('copy-folder-input').value = savedPreferences.copy_subfolder || lastCopySubfolder || suggestion;
 $('copy-folder-error').hidden = true; $('copy-folder-error').textContent = '';
 $('copy-folder-preview').textContent = copyPathPreview($('copy-folder-input').value.trim());
 renderCopyDestination(); updateActions(); $('copy-folder-modal').showModal(); $('copy-folder-input').focus(); $('copy-folder-input').select();
}
async function saveCopySubfolder(name) {
 if (busy || queueMutationPending || folderPreferencePending || displayPreferencePending || copyPreferencePending) { renderCopyDestination(); return false; }
 copyPreferencePending = true; updateActions();
 try {
  if (!window.pywebview) throw Error('The app is not connected yet. Please try again.');
  const prefs = await pywebview.api.set_copy_subfolder(name); applyPreferences(prefs);
  const state = await callApi('get_application_state'); if (state && typeof state === 'object') renderApplicationState(state);
  return true;
 } catch(error) {
  const message = error.message || String(error); renderCopyDestination(); toast('Could not save copy folder: '+message);
  if ($('copy-folder-modal').open) { $('copy-folder-error').textContent = message; $('copy-folder-error').hidden = false; }
  return false;
 } finally { copyPreferencePending = false; updateActions(); }
}
function openPreferences() { applyPreferences(savedPreferences); $('preferences-modal').showModal(); }
function closePreferences() { $('preferences-modal').close(); applyPreferences(savedPreferences); }
$('preferences-btn').onclick = openPreferences; $('change-output-btn').onclick = openPreferences;
$('preferences-close-btn').onclick = closePreferences; $('preferences-cancel-btn').onclick = closePreferences;
$('preferences-modal').addEventListener('cancel',()=>applyPreferences(savedPreferences));
$('copy-subfolder-cb').onchange = () => { const enable = $('copy-subfolder-cb').checked; if (enable) openCopyFolder($('copy-subfolder-cb')); else saveCopySubfolder(null); };
$('copy-folder-change-btn').onclick = () => openCopyFolder($('copy-folder-change-btn'));
$('copy-folder-input').oninput = () => { $('copy-folder-preview').textContent = copyPathPreview($('copy-folder-input').value.trim()); updateActions(); };
$('copy-folder-cancel-btn').onclick = () => $('copy-folder-modal').close();
$('copy-folder-modal').addEventListener('cancel',event=>{ if (copyPreferencePending) event.preventDefault(); });
$('copy-folder-modal').addEventListener('close',()=>{ renderCopyDestination(); if (copyFolderReturnFocus?.isConnected && !copyFolderReturnFocus.disabled) copyFolderReturnFocus.focus(); });
$('copy-folder-form').onsubmit = async event => { event.preventDefault(); const name = $('copy-folder-input').value.trim(); if (name && await saveCopySubfolder(name)) $('copy-folder-modal').close(); };
$('theme-select').onchange = () => document.body.dataset.theme = $('theme-select').value === 'system' ? (themeMedia.matches ? 'dark' : 'light') : $('theme-select').value;
$('output-dir-browse-btn').onclick = async () => { const selected = await callApi('browse_output_directory'); if (selected) { $('output-dir-value').textContent = selected; $('output-dir-value').title = selected; } };
$('output-dir-reset-btn').onclick = () => { $('output-dir-value').textContent = 'Default output folder'; };
$('preferences-save-btn').onclick = async () => {
 const path = $('output-dir-value').textContent; const payload = {theme:$('theme-select').value,raw_ocr_mode:$('raw-ocr-mode-select').value,output_dir:path === 'Default output folder' ? null : path,auto_open_output:$('auto-open-output-cb').checked};
 try { const prefs = await pywebview.api.save_preferences(payload); applyPreferences(prefs); $('preferences-modal').close(); renderApplicationState(await pywebview.api.get_application_state()); } catch(error) { toast('Could not save preferences: '+error); }
};
$('files-tab').onclick = () => switchSource('files'); $('text-tab').onclick = () => switchSource('text');
$('queue-tab').onclick = () => showWorkspace('queue'); $('activity-tab').onclick = showLogPanel;
$('queue-prev-btn').onclick = () => changeQueuePage(-1); $('queue-next-btn').onclick = () => changeQueuePage(1);
$('drop-zone').onclick = $('add-files-btn').onclick = async () => { if (await mutateQueue('browse_files')) showWorkspace('queue'); };
$('add-folder-btn').onclick = async () => { if (await mutateQueue('add_folder')) showWorkspace('queue'); };
$('include-subfolders-cb').onchange = async () => {
 if (busy || queueMutationPending || folderPreferencePending || copyPreferencePending || queueUnavailable()) { $('include-subfolders-cb').checked = savedPreferences.include_subfolders; return; }
 const include = $('include-subfolders-cb').checked;
 folderPreferencePending = true; updateActions();
 try { if (!window.pywebview) throw Error('The app is not connected yet. Please try again.'); applyPreferences(await pywebview.api.set_include_subfolders(include)); }
 catch(error) { $('include-subfolders-cb').checked = savedPreferences.include_subfolders; toast('Could not save folder choice: '+(error.message || String(error))); }
 finally { folderPreferencePending = false; updateActions(); }
};
$('clear-folders-btn').onclick = () => { closeQueueActions(); mutateQueue('clear_queue'); };
$('clear-completed-btn').onclick = () => { closeQueueActions(); mutateQueue('clear_completed'); };
$('queue-actions-btn').onclick = openQueueActions;
$('delete-queue-btn').onclick = openDeleteQueue;
$('delete-saved-queue-btn').onclick = openDeleteQueue;
$('queue-delete-cancel-btn').onclick = () => $('queue-delete-modal').close();
$('queue-delete-modal').addEventListener('cancel',event => { if (queueMutationPending) event.preventDefault(); });
$('queue-delete-modal').addEventListener('close',()=>{ queueDeleteId = null; updateActions(); if (queueDeleteReturnFocus?.isConnected && !queueDeleteReturnFocus.disabled) queueDeleteReturnFocus.focus(); });
$('queue-delete-confirm-btn').onclick = async () => { if (!queueDeleteId) return; const state = await mutateQueue('delete_queue',queueDeleteId); if (state) { $('queue-delete-modal').close(); toast('Queue deleted. Original files and converted Markdown kept.'); } };
$('queue-actions-menu').addEventListener('keydown',event => {
 if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closeQueueActions(true); return; }
 if (event.key === 'Tab') { closeQueueActions(true); return; }
 if (!['ArrowDown','ArrowUp','Home','End'].includes(event.key)) return;
 event.preventDefault(); const buttons = [...$('queue-actions-menu').querySelectorAll('button:not(:disabled)')]; const index = buttons.indexOf(document.activeElement);
 const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length-1 : (index+(event.key === 'ArrowDown' ? 1 : -1)+buttons.length)%buttons.length;
 buttons[next]?.focus();
});
document.addEventListener('pointerdown',event => { if (!$('queue-actions-menu').contains(event.target) && !$('queue-actions-btn').contains(event.target)) closeQueueActions(); });
window.addEventListener('resize',()=>closeQueueActions());
$('new-queue-btn').onclick = () => openQueueName('create'); $('rename-queue-btn').onclick = () => openQueueName('rename');
$('queue-select').onchange = async () => { const id = $('queue-select').value; if (!await mutateQueue('select_queue',id)) $('queue-select').value = queueState.active_id || ''; };
$('queue-attention-btn').onclick = () => { if (busy || queueMutationPending || folderPreferencePending || copyPreferencePending || queueUnavailable()) return; queueAttentionOnly = !queueAttentionOnly; queuePage = 0; renderSavedQueue(queueState); document.querySelector('.operations-panel').scrollTop = 0; };
$('show-source-details-cb').onchange = async () => {
 if (busy || queueMutationPending || folderPreferencePending || displayPreferencePending) { $('show-source-details-cb').checked = savedPreferences.show_source_details; return; }
 const show = $('show-source-details-cb').checked;
 displayPreferencePending = true; updateActions();
 try { if (!window.pywebview) throw Error('The app is not connected yet. Please try again.'); applyPreferences(await pywebview.api.set_show_source_details(show)); }
 catch(error) { $('show-source-details-cb').checked = savedPreferences.show_source_details; toast('Could not save display choice: '+(error.message || String(error))); }
 finally { displayPreferencePending = false; updateActions(); }
};
$('queue-name-input').oninput = updateActions;
$('queue-name-cancel-btn').onclick = () => $('queue-name-modal').close();
$('queue-name-modal').addEventListener('close',()=>{ if (queueNameReturnFocus?.isConnected && !queueNameReturnFocus.disabled) queueNameReturnFocus.focus(); });
$('queue-name-form').onsubmit = async event => { event.preventDefault(); const name = $('queue-name-input').value.trim(); if (!name) return; const state = await mutateQueue(queueNameMode === 'create' ? 'create_queue' : 'rename_queue',name); if (state) { $('queue-name-modal').close(); showWorkspace('queue'); } };
$('url-input').oninput = updateActions;
$('add-text-btn').onclick = async () => { const text = $('url-input').value.trim(); if (!text) return; const state = await mutateQueue('stage_text',text); if (state) { $('url-input').value = ''; showWorkspace('queue'); } updateActions(); };
async function startQueueConversion(retry=false) {
 if (busy || queueMutationPending || folderPreferencePending || copyPreferencePending || (retry ? !queueState.failed : !queued)) return;
 setBusy(true); setProgress(0); setSummary(retry ? 'Preparing failed items…' : 'Preparing your conversion…'); showLogPanel();
 const started = await callApi(retry ? 'retry_failed' : 'convert_staged');
 if (started !== true) { setBusy(false); setSummary('Conversion did not start. Your queue is unchanged.'); }
}
async function startItemRetry(id) {
 if (busy || queueMutationPending || folderPreferencePending || copyPreferencePending || queueUnavailable()) return;
 setBusy(true); setProgress(0); setSummary('Preparing this item…'); showLogPanel();
 const started = await callApi('retry_queue_item',id);
 if (started !== true) { setBusy(false); setSummary('Retry did not start. Your queue is unchanged.'); }
}
$('convert-btn').onclick = () => startQueueConversion(); $('retry-failed-btn').onclick = () => startQueueConversion(true);
$('abort-btn').onclick = () => { $('abort-btn').disabled = true; callApi('cancel_current_job'); };
$('open-btn').onclick = () => callApi('open_output'); $('vault-btn').onclick = () => callApi('open_vault');
$('copy-btn').onclick = async () => { if (await callApi('copy_to_clipboard',$('log').innerText) !== false) toast('Activity copied'); };
document.addEventListener('dragover',event => event.preventDefault());
document.addEventListener('drop',async event => {
 event.preventDefault(); if (busy || queueMutationPending || folderPreferencePending || copyPreferencePending || document.querySelector('dialog[open]')) return;
 const transfer = event.dataTransfer; if (!transfer) return;
 // Native Cocoa handles file drops. WKWebView may report Files before exposing the file list.
 if (transfer.files.length || [...transfer.items].some(item => item.kind === 'file') || [...transfer.types].includes('Files')) return;
 const urls = transfer.getData('text/uri-list').split(/\r?\n/).map(line => line.trim()).filter(line => line && !line.startsWith('#'));
 const text = urls.length ? '' : transfer.getData('text/plain');
 if (!urls.length && !text.trim()) return;
 if (await mutateQueue('stage_drop',{text,urls,files:[]})) showWorkspace('queue');
});
$('drop-zone').addEventListener('dragover',()=>{ if (!$('drop-zone').disabled) $('drop-zone').classList.add('drag-over'); });
for (const event of ['dragleave','drop']) $('drop-zone').addEventListener(event,()=> $('drop-zone').classList.remove('drag-over'));
// File paths arrive through the native Cocoa drop handler.
document.querySelectorAll('[role="tablist"]').forEach(list => list.addEventListener('keydown',event=>{ if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return; event.preventDefault(); const tabs=[...list.querySelectorAll('[role="tab"]')]; const index=tabs.indexOf(document.activeElement); const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length; if (!tabs[next].disabled) { tabs[next].focus(); tabs[next].click(); } }));
document.addEventListener('keydown',event=>{ if (!event.metaKey || document.querySelector('dialog[open]')) return; if (event.key==='o' && !$('add-files-btn').disabled) { event.preventDefault(); $('add-files-btn').click(); } if (event.key==='Enter' && !$('convert-btn').disabled) { event.preventDefault(); $('convert-btn').click(); } if (event.key==='w') { event.preventDefault(); callApi('close_window'); } });
themeMedia.addEventListener('change',()=>{ if (savedPreferences.theme==='system' && !$('preferences-modal').open) applyPreferences(savedPreferences); });
window.addEventListener('pywebviewready',async()=>{ try { applyPreferences(await pywebview.api.get_preferences()); renderApplicationState(await pywebview.api.get_application_state()); if (!queueReady) { const state = await callApi('get_queue_state'); if (state) renderSavedQueue(state); } } catch(error) { toast('Could not load app settings: '+error); } });
applyPreferences(savedPreferences); updateActions();
</script>
</body>
</html>'''
