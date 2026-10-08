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
textarea { display:block; resize:none; width:100%; height:160px; padding:14px; color:var(--ink); background:var(--surface); border:1px solid var(--line); border-radius:10px; line-height:1.5; -webkit-user-select:text; user-select:text; }
textarea::placeholder { color:var(--muted); }
.operations-shell { flex:1; min-height:170px; display:flex; flex-direction:column; border:1px solid var(--line); border-radius:12px; background:var(--surface); overflow:hidden; }
.workspace-toolbar { display:flex; align-items:center; justify-content:space-between; min-height:48px; padding:0 12px; border-bottom:1px solid var(--line); }
.workspace-tabs { display:flex; align-self:stretch; gap:18px; } .workspace-tabs button { position:relative; border:0; padding:0 3px; border-radius:0; background:transparent!important; font-size:13px; color:var(--muted); }
.workspace-tabs button[aria-selected="true"] { color:var(--ink); } .workspace-tabs button[aria-selected="true"]::after { content:""; position:absolute; height:2px; background:var(--accent); bottom:0; left:0; right:0; }
.count { padding:1px 6px; border-radius:5px; background:var(--soft); font-size:11px; font-variant-numeric:tabular-nums; }
.small { font-size:12px; min-height:30px; padding:5px 9px; }
.operations-panel { flex:1; min-height:0; overflow:auto; } .queue-empty { display:flex; height:100%; min-height:96px; align-items:center; justify-content:center; flex-direction:column; gap:4px; padding:18px; color:var(--muted); font-size:13px; text-align:center; } .queue-empty strong { font-weight:500; color:var(--ink); } .queue-empty p { margin:0; font-size:12px; }
.queue-row { display:flex; align-items:center; gap:12px; padding:13px 16px; border-bottom:1px solid var(--line); } .queue-row:last-child { border:0; }
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
.action-row > button { min-height:42px; } .action-row { display:flex; align-items:center; gap:8px; } .vault-option { margin-right:auto; display:flex; align-items:center; gap:7px; font-size:12px; color:var(--muted); } input[type="checkbox"] { width:15px; height:15px; accent-color:var(--accent); }
#badge { display:none; } .visually-hidden { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
#preferences-modal { width:min(530px,calc(100vw - 48px)); border:1px solid var(--line); border-radius:16px; padding:0; color:var(--ink); background:var(--surface); box-shadow:var(--shadow); max-height:90vh; }
#preferences-modal::backdrop { background:#10181377; backdrop-filter:blur(4px); } .modal-header { display:flex; justify-content:space-between; align-items:center; padding:20px 22px; border-bottom:1px solid var(--line); } h2 { margin:0; font-size:18px; letter-spacing:-.3px; }
.modal-body { padding:4px 22px; } .setting { padding:17px 0; border-bottom:1px solid var(--line); } .setting:last-child { border:0; } .setting-top { display:flex; align-items:center; justify-content:space-between; gap:20px; } .setting label { font-weight:550; font-size:13px; } .setting p { font-size:12px; color:var(--muted); margin:5px 0 0; } select { color:var(--ink); background:var(--soft); border:1px solid var(--line); border-radius:7px; padding:7px; max-width:235px; } .path-row { display:flex; gap:8px; align-items:center; margin-top:10px; } .path-value { font-size:12px; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1; }
.modal-footer { display:flex; gap:8px; justify-content:flex-end; align-items:center; padding:16px 22px; background:var(--bg); border-top:1px solid var(--line); } .version { margin-right:auto; color:var(--muted); font-size:11px; } .modal-footer .primary { min-width:80px; min-height:36px; }
#toast { position:fixed; bottom:88px; left:50%; transform:translateX(-50%); background:var(--ink); color:var(--bg); padding:10px 16px; border-radius:9px; font-size:13px; box-shadow:var(--shadow); max-width:85%; z-index:5; }
@media(max-height:730px) { .app { padding-top:18px; gap:12px; } .drop-zone { min-height:94px; padding:10px; } .bottom { padding-bottom:16px; }  textarea { height:140px; } }
@media(max-width:680px) { .app { padding-left:20px; padding-right:20px; } .local-note { display:none; } .input-hint { font-size:11px; } .action-row { gap:6px; } .vault-option { font-size:11px; } button.primary { min-width:130px; } }
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
  <button id="drop-zone" class="drop-zone" aria-label="Drop files here or browse files"><svg class="drop-symbol"><use href="#i-file"/></svg><span class="drop-title">Drop something worth keeping</span><span class="drop-subtitle">PDF, Word, Excel, images, HTML, text & RTF</span></button>
  <div class="input-toolbar"><button id="add-files-btn"><svg><use href="#i-plus"/></svg>Add files</button><button id="add-folder-btn"><svg><use href="#i-folder"/></svg>Add folder</button><span class="input-hint">Includes supported files in subfolders</span></div>
 </div>
 <div id="text-source" role="tabpanel" aria-labelledby="text-tab" hidden><label for="url-input" class="visually-hidden">Text or website URL to convert</label><textarea id="url-input" placeholder="Paste your text, or a website URL…" spellcheck="false"></textarea></div>
</section>

<section class="operations-shell" aria-label="Conversion workspace">
 <div class="workspace-toolbar"><div class="workspace-tabs" role="tablist" aria-label="Workspace"><button id="queue-tab" role="tab" aria-selected="true" aria-controls="queue-panel">Queue <span id="queue-count" class="count">0</span></button><button id="activity-tab" role="tab" aria-selected="false" aria-controls="log-container" tabindex="-1">Activity <span id="activity-alert" class="count" hidden>!</span></button></div><button id="clear-folders-btn" class="quiet small" disabled>Clear queue</button><button id="copy-btn" class="quiet small" hidden>Copy log</button></div>
 <div class="operations-panel">
  <section id="recovery-panel" class="recovery" aria-labelledby="recovery-title" hidden><h2 id="recovery-title" class="recovery-heading">Continue where you left off</h2><div id="recovery-jobs"></div></section>
  <div id="queue-panel" role="tabpanel" aria-labelledby="queue-tab"><div id="folder-queue"></div><div id="queue-empty" class="queue-empty"><strong>A little order for your next idea.</strong><p>Add files above, then convert when you’re ready.</p></div></div>
  <div id="log-container" role="tabpanel" aria-labelledby="activity-tab" hidden><div id="log" role="log" aria-label="Conversion activity" aria-live="off"></div></div>
 </div>
 <div class="status-line"><span id="summary" role="status" aria-live="polite">Ready when you are</span><span id="progress-label">0%</span></div><div class="progress-track" role="progressbar" aria-label="Conversion progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><div id="progress"></div></div>
</section>
<footer class="bottom">
 <div class="destination"><svg><use href="#i-folder"/></svg><span>Save to</span><span id="destination-path">Default output folder</span><button id="change-output-btn" class="quiet">Change…</button></div>
 <div class="action-row"><label class="vault-option" id="vault-option"><input id="vault-cb" type="checkbox" VAULT_CHECKED>Copy to Obsidian vault</label><button id="open-btn"><svg><use href="#i-folder"/></svg>Open output</button><button id="convert-btn" class="primary" disabled>Convert to Markdown<svg><use href="#i-arrow"/></svg></button><button id="abort-btn" class="danger" hidden>Stop & save</button></div>
 <span id="badge"></span>
</footer>
</main>
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
let savedPreferences = {theme:'system',raw_ocr_mode:'different',output_dir:null,auto_open_output:false};
let applicationState = {}, toastTimer;
const themeMedia = window.matchMedia('(prefers-color-scheme: dark)');
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 4500); }
async function callApi(name, ...args) {
 try { if (!window.pywebview) throw Error('The app is not connected yet. Please try again.'); return await pywebview.api[name](...args); }
 catch(error) { toast(error.message || String(error)); return false; }
}
function icon(name) { const svg = document.createElementNS('http://www.w3.org/2000/svg','svg'); const use = document.createElementNS(svg.namespaceURI,'use'); use.setAttribute('href','#i-'+name); svg.appendChild(use); svg.setAttribute('aria-hidden','true'); return svg; }
function updateActions() {
 $('convert-btn').disabled = busy || (sourceMode === 'files' ? !queued : !$('url-input').value.trim());
 $('convert-btn').hidden = busy && canStop; $('abort-btn').hidden = !(busy && canStop);
 for (const id of ['add-files-btn','add-folder-btn','drop-zone','files-tab','text-tab','preferences-btn','change-output-btn','url-input','vault-cb']) $(id).disabled = busy;
 if (!applicationState.vault_configured) $('vault-cb').disabled = true;
 $('clear-folders-btn').disabled = busy || !queued;
 document.querySelectorAll('.folder-remove-btn, .recovery-row button').forEach(button => button.disabled = busy);
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
function showWorkspace(mode) { workspaceMode = mode; const queue = mode === 'queue'; $('queue-panel').hidden = !queue; $('log-container').hidden = queue; $('clear-folders-btn').hidden = !queue; $('copy-btn').hidden = queue; for (const [id,selected] of [['queue-tab',queue],['activity-tab',!queue]]) { $(id).setAttribute('aria-selected',String(selected)); $(id).tabIndex = selected ? 0 : -1; } if (!queue) $('activity-alert').hidden = true; }
function showLogPanel() { showWorkspace('activity'); }
function switchSource(mode) { sourceMode = mode; const files = mode === 'files'; $('files-source').hidden = !files; $('text-source').hidden = files; for (const [id,selected] of [['files-tab',files],['text-tab',!files]]) { $(id).setAttribute('aria-selected',String(selected)); $(id).tabIndex = selected ? 0 : -1; } updateActions(); }
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
function renderApplicationState(state) { applicationState = state; $('destination-path').textContent = state.output_dir || 'Default output folder'; $('destination-path').title = state.output_dir || ''; $('app-version').textContent = 'MD Converter '+(state.version || ''); $('vault-option').title = state.vault_configured ? 'Also save a copy in your configured vault' : 'No Obsidian vault configured'; $('vault-setting').hidden = !state.vault_configured; if (!state.vault_configured) $('vault-cb').checked = false; renderRecoveryJobs(state.recovery_jobs || []); updateActions(); }
function applyPreferences(prefs) { savedPreferences = {...prefs}; document.body.dataset.theme = prefs.theme === 'system' ? (themeMedia.matches ? 'dark' : 'light') : prefs.theme; $('theme-select').value = prefs.theme; $('raw-ocr-mode-select').value = prefs.raw_ocr_mode; $('output-dir-value').textContent = prefs.output_dir || 'Default output folder'; $('output-dir-value').title = prefs.output_dir || ''; $('auto-open-output-cb').checked = Boolean(prefs.auto_open_output); }
function openPreferences() { applyPreferences(savedPreferences); $('preferences-modal').showModal(); }
function closePreferences() { $('preferences-modal').close(); applyPreferences(savedPreferences); }
$('preferences-btn').onclick = openPreferences; $('change-output-btn').onclick = openPreferences;
$('preferences-close-btn').onclick = closePreferences; $('preferences-cancel-btn').onclick = closePreferences;
$('preferences-modal').addEventListener('cancel',()=>applyPreferences(savedPreferences));
$('theme-select').onchange = () => document.body.dataset.theme = $('theme-select').value === 'system' ? (themeMedia.matches ? 'dark' : 'light') : $('theme-select').value;
$('output-dir-browse-btn').onclick = async () => { const selected = await callApi('browse_output_directory'); if (selected) { $('output-dir-value').textContent = selected; $('output-dir-value').title = selected; } };
$('output-dir-reset-btn').onclick = () => { $('output-dir-value').textContent = 'Default output folder'; };
$('preferences-save-btn').onclick = async () => {
 const path = $('output-dir-value').textContent; const payload = {theme:$('theme-select').value,raw_ocr_mode:$('raw-ocr-mode-select').value,output_dir:path === 'Default output folder' ? null : path,auto_open_output:$('auto-open-output-cb').checked};
 try { const prefs = await pywebview.api.save_preferences(payload); applyPreferences(prefs); $('preferences-modal').close(); renderApplicationState(await pywebview.api.get_application_state()); } catch(error) { toast('Could not save preferences: '+error); }
};
$('files-tab').onclick = () => switchSource('files'); $('text-tab').onclick = () => switchSource('text');
$('queue-tab').onclick = () => showWorkspace('queue'); $('activity-tab').onclick = showLogPanel;
$('drop-zone').onclick = $('add-files-btn').onclick = () => callApi('browse_files'); $('add-folder-btn').onclick = () => callApi('add_folder'); $('clear-folders-btn').onclick = () => callApi('clear_queue');
$('url-input').oninput = updateActions;
$('convert-btn').onclick = async () => { if (busy) return; const mode = sourceMode; setBusy(true); setProgress(0); setSummary('Preparing your conversion…'); showLogPanel(); const result = await callApi(mode === 'files' ? 'convert_staged' : 'fetch_url', ...(mode === 'files' ? [] : [$('url-input').value])); if (result === false) setBusy(false); };
$('abort-btn').onclick = () => { $('abort-btn').disabled = true; callApi('cancel_current_job'); };
$('open-btn').onclick = () => callApi('open_output'); $('vault-btn').onclick = () => callApi('open_vault');
$('copy-btn').onclick = async () => { if (await callApi('copy_to_clipboard',$('log').innerText) !== false) toast('Activity copied'); };
for (const event of ['dragover','drop']) document.addEventListener(event,e=>e.preventDefault());
$('drop-zone').addEventListener('dragover',()=>{ if (!busy) $('drop-zone').classList.add('drag-over'); });
for (const event of ['dragleave','drop']) $('drop-zone').addEventListener(event,()=> $('drop-zone').classList.remove('drag-over'));
// File paths arrive through the native Cocoa drop handler.
document.querySelectorAll('[role="tablist"]').forEach(list => list.addEventListener('keydown',event=>{ if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return; event.preventDefault(); const tabs=[...list.querySelectorAll('[role="tab"]')]; const index=tabs.indexOf(document.activeElement); const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length; if (!tabs[next].disabled) { tabs[next].focus(); tabs[next].click(); } }));
document.addEventListener('keydown',event=>{ if (!event.metaKey || $('preferences-modal').open) return; if (event.key==='o' && !busy) { event.preventDefault(); callApi('browse_files'); } if (event.key==='Enter' && !$('convert-btn').disabled) { event.preventDefault(); $('convert-btn').click(); } if (event.key==='w') { event.preventDefault(); callApi('close_window'); } });
themeMedia.addEventListener('change',()=>{ if (savedPreferences.theme==='system' && !$('preferences-modal').open) applyPreferences(savedPreferences); });
window.addEventListener('pywebviewready',async()=>{ try { applyPreferences(await pywebview.api.get_preferences()); renderApplicationState(await pywebview.api.get_application_state()); } catch(error) { toast('Could not load app settings: '+error); } });
applyPreferences(savedPreferences); updateActions();
</script>
</body>
</html>'''
