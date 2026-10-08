# Saved queues implementation plan

The user approved the collect-now, convert-later design on 2026-10-08. Implement it in this session, retaining the current visual language.

## Experience

- A default Inbox and named collections persist locally. A compact selector, New and Rename controls live above the queue. No explicit Save is needed.
- Files, folder contents, HTTP(S) links, browser link drops, .webloc shortcuts and pasted text enter the selected collection without starting conversion or network requests.
- Each item retains its source, order, status, output and error. Statuses are waiting, processing, done and failed. Interrupted processing becomes waiting after the previous worker has stopped.
- Convert processes waiting items only; Retry failed processes failed items only. Stop keeps saved results and unfinished work. Successful items remain visible and are never silently converted again.
- Missing files offer Locate file. Folder contents are captured when added; overlapping selections deduplicate. Links retain meaningful query parameters. Web content is fetched when conversion starts; page snapshots are outside this release.
- Queue persistence is independent of output preferences. A run saves its output/vault/quote options with its items so recovery uses the same destination.
- Existing image checkpoints and their recovery controls continue to work. Image jobs remain batched with per-image checkpoint reconciliation.

## Architecture and contracts

`queue_store.py`: SQLite durable collections/items, transactions, stable UUIDs, conservative deduplication, an OS worker lock, and interrupted-item recovery. Located beside preferences as queues.sqlite3. No network or GUI dependency.

`queue_sources.py` and `native_drop.py`: pure URL/text/webloc parsing and native file/URL drag intake.

`queue_runner.py`: resumable mixed conversions with durable item state and linked image checkpoints. Normal documents use a per-item private working directory and an output receipt before publication to avoid repeating completed conversions after export interruption.

`converter_app.py`: store and runner integration, dialogs, queue API and refresh. UI calls get_queue_state, create_queue(name), rename_queue(name), select_queue(id), stage_text(text), stage_drop(payload), remove_queue_item(id), clear_completed, clear_queue, locate_queue_item(id), convert_staged and retry_failed.

Queue UI state: `{active_id, queues:[{id,name}], items:[{id,kind,source,title,group_name,status,error,output_path}], waiting,failed,done,total,busy,saved}`. API mutations return this state; conversion entrypoints return a boolean. Rendering uses `renderSavedQueue(state)`; source intake never starts work.

## Execution checklist

- [x] Write store regression tests for reopen, named queues, duplicate sources, interrupted recovery, mutation rollback and worker exclusion; implement store.
- [x] Write parser/native tests for browser URL/text drags, multiline links, webloc and invalid schemes; implement intake.
- [x] Add compact collection UI, per-item statuses, retry/locate actions, and Add to queue for pasted content. Preserve theme and keyboard accessibility.
- [x] Write mixed-run tests for restart, failures, stop, missing files, output recovery and saved image reconciliation; implement runner and API integration.
- [x] Run complete tests, review correctness, exercise the built Mac app with real mixed files and a local test website, restart it and verify persistence.
- [x] Update documentation and version; commit, build and install with backup. Release packaging and delivery are recorded in the release report.
