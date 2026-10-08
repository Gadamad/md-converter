"""Saved collection operations exposed by the desktop application."""
import json
from pathlib import Path
import sqlite3
import threading
import time

from queue_sources import normalize_url, sources_from_text, read_webloc
from queue_store import QueueStore
from queue_runner import QueueRunner


class SavedQueueApi:
    def _init_queue(self):
        self._queue_store = None
        self._queue_error = ''
        self._last_shown_queue_id = None
        self._queue_refresh_at = float('-inf')
        self._queue_last_state = None
        self._queue_refresh_lock = threading.RLock()
        path = self._preferences_path.with_name('queues.sqlite3')
        try:
            self._queue_store = QueueStore(path)
            self._queue_store.recover_interrupted()
            state = self._queue_store.state()
            self._last_shown_queue_id = state['active_id']
            self._reload_staging(state['items'])
        except (sqlite3.Error, OSError, ValueError) as exc:
            self._queue_store = None
            self._queue_error = (f'Saved queues are unavailable. Could not open {path}: {exc}. '
                                 'Existing queue data has not been replaced.')
            self._staged, self._staged_folders = [], []

    def _require_queue_store(self):
        if self._queue_store is None:
            raise RuntimeError(self._queue_error or 'Saved queues are unavailable.')

    def _check_queue_selection(self, expected_id=None):
        self._require_queue_store()
        expected_id = self._last_shown_queue_id if expected_id is None else expected_id
        if self._queue_store.active_id != expected_id:
            self._queue_changed()
            raise RuntimeError('Queue selection changed in another window. Review the selected queue and try again.')
        return expected_id

    def get_queue_state(self):
        if self._queue_store is None:
            return {'active_id': None, 'queues': [], 'items': [], 'waiting': 0,
                    'failed': 0, 'done': 0, 'total': 0, 'busy': False,
                    'saved': False, 'save_error': self._queue_error}
        state = self._queue_store.state()
        self._last_shown_queue_id = state['active_id']
        state.update(busy=self._job_running, saved=not bool(self._queue_error), save_error=self._queue_error)
        return state

    def _queue_changed(self, force=True):
        # Every item still commits immediately; only expensive UI snapshots are
        # throttled while a worker is reporting progress through a large queue.
        with self._queue_refresh_lock:
            now = time.monotonic()
            if not force and now - self._queue_refresh_at < 0.2:
                return self._queue_last_state
            state = self.get_queue_state()
            self._reload_staging(state['items'])
            self._js(f'renderSavedQueue({json.dumps(state)})')
            self._queue_last_state = state
            self._queue_refresh_at = now
            return state

    def _reload_staging(self, items=None):
        # Maintain the existing Python staging facade for integrations. The
        # database remains the source of truth for conversion and UI state.
        from collections import namedtuple
        Folder = namedtuple('Folder', 'id path file_count files')
        self._staged = []
        groups = {}
        if items is None:
            items = self._queue_store.items(self._queue_store.active_id) if self._queue_store else []
        for item in items:
            if item['kind'] != 'file' or item['status'] == 'done':
                continue
            if item['group_name']:
                groups.setdefault(item['group_name'], []).append(item['source'])
            else:
                self._staged.append(item['source'])
        self._staged_folders = [Folder(name, Path(name), len(paths), tuple(paths)) for name, paths in groups.items()]

    def _queue_edit(self, operation, *, allow_selection_change=False, expected_id=None):
        self._require_queue_store()
        if self._job_running:
            raise RuntimeError('Stop the current conversion before changing this queue.')
        queue_id = (self._last_shown_queue_id if allow_selection_change
                    else self._check_queue_selection(expected_id))
        try:
            # Keep the intended ID even if another process selects a collection
            # between the selection check and the store's mutation lock.
            operation(queue_id)
            self._queue_error = ''
        except Exception as exc:
            self._queue_error = str(exc)
            self._queue_changed()
            self._log(f'Queue not saved: {exc}', 'log-error')
            raise
        return self._queue_changed()

    def create_queue(self, name):
        return self._queue_edit(lambda _: self._queue_store.create_queue(name))

    def rename_queue(self, name):
        return self._queue_edit(lambda queue_id: self._queue_store.rename_queue(queue_id, name))

    def select_queue(self, queue_id):
        return self._queue_edit(lambda _: self._queue_store.select_queue(queue_id), allow_selection_change=True)

    def clear_completed(self):
        return self._queue_edit(lambda queue_id: self._queue_store.clear_queue(queue_id, completed_only=True))

    def clear_queue(self):
        return self._queue_edit(lambda queue_id: self._queue_store.clear_queue(queue_id))

    def delete_queue(self, queue_id):
        # The confirmation dialog passes the queue it actually named. Never
        # substitute a new selection if another window changes it meanwhile.
        if not isinstance(queue_id, str) or not queue_id:
            raise ValueError('Choose a saved queue to delete.')
        return self._queue_edit(lambda target: self._queue_store.delete_queue(target), expected_id=queue_id)

    def remove_queue_item(self, item_id):
        return self._queue_edit(lambda _: self._queue_store.remove_item(self._active_item(item_id)['id']))

    def _active_item(self, item_id):
        queue_id = self._check_queue_selection()
        item = self._queue_store.get_item(item_id)
        if item['queue_id'] != queue_id:
            raise ValueError('This item belongs to another queue.')
        return item

    def stage_text(self, text):
        queue_id = self._check_queue_selection()
        entries = sources_from_text(text)
        return self._queue_edit(lambda target: self._queue_store.add_items(target, entries), expected_id=queue_id)

    def fetch_url(self, text):
        """Compatibility entrypoint: pasted sources are now collected first."""
        return self.stage_text(text)

    def stage_drop(self, payload):
        self._require_queue_store()
        if not isinstance(payload, dict):
            raise ValueError('Drop a website link, text, or supported file.')
        if payload.get('files'):
            return self.stage_files(payload['files'])
        if payload.get('urls'):
            if not isinstance(payload['urls'], list):
                raise ValueError('Website links must be a list.')
            return self.stage_text('\n'.join(normalize_url(value) for value in payload['urls']))
        return self.stage_text(payload.get('text', ''))

    def _file_entries(self, paths):
        entries = []
        for raw in paths:
            path = Path(raw).expanduser().resolve()
            if path.is_dir():
                children = sorted(p for p in path.rglob('*') if p.is_file()
                                  and p.suffix.lower() in self._supported | {'.webloc'})
                if not children:
                    self._log(f'No supported files found in {path.name}', 'log-error')
                group = str(path)
            else:
                children, group = [path], ''
            for child in children:
                if child.suffix.lower() == '.webloc':
                    url = read_webloc(child)
                    entries.append(dict(kind='url', source=url, title=child.stem, group_name=group))
                elif child.suffix.lower() in self._supported:
                    entries.append(dict(kind='file', source=str(child), title=child.name, group_name=group))
                else:
                    self._log(f'Unsupported file: {child.name}', 'log-error')
        return entries

    def stage_files(self, paths):
        queue_id = self._check_queue_selection()
        entries = self._file_entries(paths)
        return self._queue_edit(lambda target: self._queue_store.add_items(target, entries), expected_id=queue_id)

    def stage_folder(self, folder, replace=False):
        queue_id = self._check_queue_selection()
        entries = self._file_entries([str(folder)])
        # Add folder always appends. The legacy browse_folder replacement mode
        # removes only old folder rows, preserving individually collected items.
        def save(target):
            if replace and entries:
                for item in self._queue_store.items(target):
                    if item['group_name']:
                        self._queue_store.remove_item(item['id'])
            self._queue_store.add_items(target, entries)
        return self._queue_edit(save, expected_id=queue_id)

    def remove_staged_file(self, path):
        def remove(queue_id):
            for item in self._queue_store.items(queue_id):
                if item['source'] == path:
                    self._queue_store.remove_item(item['id'])
        return self._queue_edit(remove)

    def remove_staged_folder(self, folder_id):
        def remove(queue_id):
            for item in self._queue_store.items(queue_id):
                if item['group_name'] == folder_id:
                    self._queue_store.remove_item(item['id'])
        return self._queue_edit(remove)

    def clear_staged_folders(self):
        def remove(queue_id):
            for item in self._queue_store.items(queue_id):
                if item['group_name']:
                    self._queue_store.remove_item(item['id'])
        return self._queue_edit(remove)

    def locate_queue_item(self, item_id):
        item = self._active_item(item_id)
        if self._job_running or item['kind'] != 'file' or item['status'] != 'failed' or not self.window:
            return self.get_queue_state()
        import webview
        result = self.window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False)
        if not result:
            return self.get_queue_state()
        path = Path(str(result[0])).resolve()
        if not path.is_file() or path.suffix.lower() != Path(item['source']).suffix.lower():
            raise ValueError('Choose an existing file with the same format as the missing source.')
        def relocate(_):
            with self._queue_store.worker_lock():
                self._queue_store.update_item(item_id, source=str(path), title=path.name,
                    status='waiting', error='', checkpoint_path='', receipt_path='', output_path='', options={})
        return self._queue_edit(relocate, expected_id=item['queue_id'])

    def convert_staged(self):
        return self._start_queue(False)

    def retry_failed(self):
        return self._start_queue(True)

    def _start_queue(self, retry):
        queue_id = self._check_queue_selection()
        state = self._queue_store.state()
        if state['active_id'] != queue_id:
            self._check_queue_selection(queue_id)
        if not state['failed' if retry else 'waiting']:
            return False
        return self._start_job(self._queue_worker, queue_id, retry)

    def _queue_worker(self, queue_id, retry):
        self._run_worker(self._queue_worker_body, queue_id, retry)
        self._queue_changed(force=True)

    def _queue_worker_body(self, queue_id, retry):
        self._show_abort_button()
        self._show_log_panel()
        self._set_progress(0)
        options = {'output_dir': str(self._effective_output_dir().resolve()),
                   'vault_dir': str(self._vault_dir.resolve()) if self._vault_checked() and self._vault_dir else None,
                   'raw_ocr_mode': self._preferences.raw_ocr_mode}
        def progress(current, total, title):
            self._set_summary(f'Processing {current} / {total}: {title}')
            self._set_progress(100 * (current - 1) / total if total else 0)
        runner = QueueRunner(self._queue_store, self._preferences_path.parent/'queue-cache', options,
            should_cancel=self._cancel_event.is_set, on_change=lambda: self._queue_changed(force=False),
            on_status=lambda text: self._log(text, 'log-error' if text.startswith('Failed:') else 'log-info'),
            on_progress=progress)
        runner.run(queue_id, retry_failed=retry)
        items = self._queue_store.items(queue_id)
        done = sum(item['status'] == 'done' for item in items)
        failed = sum(item['status'] == 'failed' for item in items)
        waiting = sum(item['status'] == 'waiting' for item in items)
        self._set_progress(100 * (done + failed) / len(items) if items else 0)
        self._set_summary(f"{'Stopped' if self._cancel_event.is_set() else 'Finished'} · {done} saved · {waiting} waiting · {failed} failed")
        self._maybe_auto_open_output([Path(item['output_path']) for item in items if item['status'] == 'done'])
