from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def test_collect_restart_convert_and_retry_real_website(tmp_path, monkeypatch):
    import converter_app as app
    calls = []
    available = {'/article': True, '/later': False}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            if not available.get(self.path):
                self.send_error(404, 'Not available yet')
                return
            content = b'<html><title>Saved research</title><body><h1>Collect today</h1><p>Convert this useful website tomorrow.</p></body></html>'
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(app, 'default_preferences_path', lambda: tmp_path/'settings'/'preferences.json')
    monkeypatch.setattr(app, 'VAULT_DIR', None)
    try:
        api = app.Api()
        api.save_preferences({'output_dir': str(tmp_path/'output')})
        api.create_queue('Research for tomorrow')
        url = f'http://127.0.0.1:{server.server_port}'
        api.stage_text(f'{url}/article\n{url}/later')
        text_file = tmp_path/'notes.txt'
        text_file.write_text('Local documents belong in this queue too.')
        api.stage_files([str(text_file)])
        assert calls == []
        reopened = app.Api()
        assert reopened.get_queue_state()['waiting'] == 3
        reopened._queue_worker_body(reopened.get_queue_state()['active_id'], False)
        state = reopened.get_queue_state()
        assert state['done'] == 2 and state['failed'] == 1
        assert calls == ['/article', '/later']
        available['/later'] = True
        reopened._queue_worker_body(state['active_id'], True)
        assert reopened.get_queue_state()['done'] == 3
        assert calls == ['/article', '/later', '/later']
        assert len(list((tmp_path/'output').rglob('*.md'))) == 3
        assert any('Convert this useful website tomorrow.' in path.read_text() for path in (tmp_path/'output').rglob('*.md'))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
