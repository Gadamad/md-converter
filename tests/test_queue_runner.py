import json
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from queue_store import QueueStore
from queue_runner import QueueRunner
from converters import ConvertResult


def setup_queue(tmp_path, sources):
    store = QueueStore(tmp_path / 'queues.sqlite3')
    store.add_items(store.active_id, sources)
    return store


def runner(store, tmp_path, **kwargs):
    return QueueRunner(store, tmp_path / 'cache', {'output_dir': str(tmp_path / 'output'),
                       'vault_dir': None, 'raw_ocr_mode': 'different'}, **kwargs)


def test_success_survives_restart_and_failed_only_retry(tmp_path):
    good = tmp_path / 'good.txt'
    good.write_text('Keep this result.')
    store = setup_queue(tmp_path, [dict(kind='file', source=str(good), title='good.txt'),
                                  dict(kind='url', source='https://example.test/a', title='example.test')])
    calls = []
    def convert(source, output, vault=None, **kwargs):
        calls.append(source)
        if source.startswith('https:'):
            raise RuntimeError('Website temporarily unavailable')
        dest = output / 'txt' / 'good.md'
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text('Keep this result.')
        return ConvertResult(True, str(dest), 3, 'OK')
    runner(store, tmp_path, route_fn=convert).run(store.active_id)
    first, failed = store.items(store.active_id)
    assert first['status'] == 'done' and Path(first['output_path']).read_text() == 'Keep this result.'
    assert failed['status'] == 'failed' and 'unavailable' in failed['error']
    reopened = QueueStore(tmp_path / 'queues.sqlite3')
    runner(reopened, tmp_path, route_fn=convert).run(reopened.active_id, retry_failed=True)
    assert calls == [str(good), 'https://example.test/a', 'https://example.test/a']
    assert len(list((tmp_path / 'output').rglob('*.md'))) == 1


def test_stop_leaves_waiting_work_and_keeps_completed(tmp_path):
    cancel = threading.Event()
    files = []
    for name in ('first.txt', 'second.txt'):
        path = tmp_path / name
        path.write_text(name)
        files.append(dict(kind='file', source=str(path), title=name))
    store = setup_queue(tmp_path, files)
    def convert(source, output, vault=None, **kwargs):
        target = output / 'txt' / 'result.md'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('Saved')
        cancel.set()
        return ConvertResult(True, str(target), 1, 'OK')
    runner(store, tmp_path, route_fn=convert, should_cancel=cancel.is_set).run(store.active_id)
    assert [x['status'] for x in store.items(store.active_id)] == ['done', 'waiting']


def test_missing_file_reports_failure_and_continues(tmp_path):
    store = setup_queue(tmp_path, [dict(kind='file', source=str(tmp_path/'gone.txt'), title='gone'),
                                  dict(kind='text', source='Still convert me.', title='Note')])
    runner(store, tmp_path).run(store.active_id)
    missing, text = store.items(store.active_id)
    assert missing['status'] == 'failed' and 'Locate file' in missing['error']
    assert text['status'] == 'done'


def test_export_retry_uses_receipt_and_original_destination(tmp_path, monkeypatch):
    store = setup_queue(tmp_path, [dict(kind='text', source='Keep this once.', title='Note')])
    first_runner = runner(store, tmp_path)
    real_publish = first_runner._publish
    monkeypatch.setattr(first_runner, '_publish', lambda *args: (_ for _ in ()).throw(OSError('Disk unavailable')))
    first_runner.run(store.active_id)
    item = store.items(store.active_id)[0]
    assert item['status'] == 'failed' and Path(item['receipt_path']).is_file()
    second_runner = QueueRunner(store, tmp_path/'cache', {'output_dir': str(tmp_path/'elsewhere'), 'vault_dir': None, 'raw_ocr_mode':'different'},
                               paste_fn=lambda *args: pytest.fail('Completed conversion must not run again'))
    second_runner.run(store.active_id, retry_failed=True)
    restored = store.items(store.active_id)[0]
    assert restored['status'] == 'done'
    assert str(tmp_path/'output') in restored['output_path']
    assert not (tmp_path/'elsewhere').exists()


def test_crash_after_publish_reuses_same_output(tmp_path, monkeypatch):
    store = setup_queue(tmp_path, [dict(kind='text', source='Once only.', title='Note')])
    work = runner(store, tmp_path)
    publish = work._publish
    def crash(item, receipt):
        publish(item, receipt)
        raise SystemExit('Simulated power loss')
    monkeypatch.setattr(work, '_publish', crash)
    with pytest.raises(SystemExit):
        work.run(store.active_id)
    store.recover_interrupted()
    runner(store, tmp_path, paste_fn=lambda *args: pytest.fail('Do not reconvert')).run(store.active_id)
    assert store.items(store.active_id)[0]['status'] == 'done'
    assert len(list((tmp_path/'output').rglob('*.md'))) == 1


def test_image_queue_resume_and_failed_retry_preserve_success(tmp_path, monkeypatch):
    import converters
    from image_ocr import OcrResult, OcrCancelled
    images = []
    for name in ('a.jpg', 'b.jpg', 'c.jpg'):
        path = tmp_path/name
        path.write_bytes(b'fixture')
        images.append(dict(kind='file', source=str(path), title=name))
    store = setup_queue(tmp_path, images)
    results = iter([OcrResult('Saved first.', 'vision'), ValueError('Unreadable'), OcrCancelled()])
    def extract(*args, **kwargs):
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(converters, 'ocr_image', extract)
    runner(store, tmp_path).run(store.active_id)
    assert [x['status'] for x in store.items(store.active_id)] == ['done', 'failed', 'waiting']
    (tmp_path/'a.jpg').write_bytes(b'changed source should not cause done item reconversion')
    calls = []
    def success(path, **kwargs):
        calls.append(path.name)
        return OcrResult('Next quote.', 'vision')
    monkeypatch.setattr(converters, 'ocr_image', success)
    runner(store, tmp_path).run(store.active_id)
    runner(store, tmp_path).run(store.active_id, retry_failed=True)
    assert calls == ['c.jpg', 'b.jpg']
    assert [x['status'] for x in store.items(store.active_id)] == ['done', 'done', 'done']
    outputs = list((tmp_path/'output'/'quotes').glob('*.md'))
    assert len(outputs) == 1 and 'Saved first.' in outputs[0].read_text()


def test_removed_image_is_not_retried_from_shared_checkpoint(tmp_path, monkeypatch):
    import converters
    from image_ocr import OcrResult
    sources=[]
    for name in ('a.jpg', 'b.jpg'):
        path=tmp_path/name
        path.write_bytes(b'fixture')
        sources.append(dict(kind='file', source=str(path), title=name))
    store=setup_queue(tmp_path, sources)
    monkeypatch.setattr(converters, 'ocr_image', lambda *a,**k: (_ for _ in ()).throw(ValueError('Bad image')))
    runner(store,tmp_path).run(store.active_id)
    store.remove_item(store.items(store.active_id)[0]['id'])
    calls=[]
    def success(path,**kwargs):
        calls.append(path.name)
        return OcrResult('Recovered.', 'vision')
    monkeypatch.setattr(converters,'ocr_image',success)
    runner(store,tmp_path).run(store.active_id,retry_failed=True)
    assert calls == ['b.jpg']
    assert store.items(store.active_id)[0]['status']=='done'


def test_image_journal_survives_crash_before_queue_status_commit(tmp_path, monkeypatch):
    import converters
    from image_ocr import OcrResult
    entries=[]
    for name in ('a.jpg', 'b.jpg'):
        path=tmp_path/name
        path.write_bytes(b'image')
        entries.append(dict(kind='file', source=str(path), title=name))
    store=setup_queue(tmp_path, entries)
    calls=[]
    def extract(path, **kwargs):
        calls.append(path.name)
        return OcrResult('A saved quote.', 'vision')
    monkeypatch.setattr(converters, 'ocr_image', extract)
    first=runner(store,tmp_path)
    monkeypatch.setattr(first,'_reconcile_images',lambda *args: (_ for _ in ()).throw(SystemExit('crash')))
    with pytest.raises(SystemExit):
        first.run(store.active_id)
    resumed=QueueStore(store.path)
    runner(resumed,tmp_path).run(resumed.active_id)
    assert calls == ['a.jpg','b.jpg']
    assert resumed.state()['done'] == 2
    assert len(list((tmp_path/'output'/'quotes').glob('*.md'))) == 1


def test_located_replacement_does_not_reuse_previous_conversion_receipt(tmp_path, monkeypatch):
    original, replacement = tmp_path/'old.txt', tmp_path/'replacement.txt'
    original.write_text('OLD CONTENT')
    replacement.write_text('NEW CONTENT')
    store = setup_queue(tmp_path, [dict(kind='file', source=str(original), title=original.name)])
    first = runner(store, tmp_path)
    monkeypatch.setattr(first, '_publish', lambda *args: (_ for _ in ()).throw(OSError('Disk unavailable')))
    first.run(store.active_id)
    item = store.items(store.active_id)[0]
    old_receipt = Path(item['receipt_path'])
    assert item['status'] == 'failed' and old_receipt.is_file()
    # Locate file intentionally clears all data belonging to the previous source.
    with store.worker_lock():
        store.update_item(item['id'], source=str(replacement), title=replacement.name,
                          status='waiting', error='', checkpoint_path='', receipt_path='',
                          output_path='', options={})
    runner(store, tmp_path).run(store.active_id)
    updated = store.items(store.active_id)[0]
    content = Path(updated['output_path']).read_text()
    assert 'NEW CONTENT' in content and 'OLD CONTENT' not in content
    assert Path(updated['receipt_path']) != old_receipt


def test_text_starting_with_url_stays_text_without_network_fetch(tmp_path, monkeypatch):
    import converters
    from queue_sources import sources_from_text
    text = 'https://example.com/article\nMy notes about this page.'
    store = setup_queue(tmp_path, sources_from_text(text))
    fetched = []
    def fetch(source, *args, **kwargs):
        fetched.append(source)
        return ConvertResult(False, '', 0, 'Unexpected website fetch')
    monkeypatch.setattr(converters, 'convert_html', fetch)
    runner(store, tmp_path).run(store.active_id)
    item = store.items(store.active_id)[0]
    assert fetched == []
    assert item['status'] == 'done'
    assert text in Path(item['output_path']).read_text()


def make_two_sheet_workbook(path):
    from openpyxl import Workbook
    workbook = Workbook()
    # These names sanitize to the same filename; both sheets must survive.
    workbook.active.title = 'Sales&Costs'
    workbook.active.append(['Product', 'Amount'])
    workbook.active.append(['First sheet value', 12])
    second = workbook.create_sheet('SalesCosts')
    second.append(['Product', 'Amount'])
    second.append(['Second sheet value', 34])
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    workbook.close()


def test_real_workbooks_publish_every_sheet_in_distinct_stable_folders(tmp_path):
    paths = [tmp_path/'first'/'report.xlsx', tmp_path/'second'/'report.xlsx']
    for path in paths:
        make_two_sheet_workbook(path)
    store = setup_queue(tmp_path, [dict(kind='file', source=str(path), title=path.name) for path in paths])
    run = runner(store, tmp_path)
    run.options['vault_dir'] = str(tmp_path/'vault')
    run.run(store.active_id)
    items = store.items(store.active_id)
    assert [item['status'] for item in items] == ['done', 'done']
    assert len({item['output_path'] for item in items}) == 2
    for item in items:
        folder = Path(item['output_path'])
        assert folder == tmp_path/'output'/'spreadsheets'/f"report_{item['id'][:12]}"
        files = list(folder.glob('*.md'))
        assert len(files) == 2 and len({path.name for path in files}) == 2
        content = '\n'.join(path.read_text() for path in files)
        assert 'First sheet value' in content and 'Second sheet value' in content
        vault_files = list((tmp_path/'vault'/'spreadsheets'/folder.name).glob('*.md'))
        assert {path.name for path in vault_files} == {path.name for path in files}
        assert len(json.loads(Path(item['receipt_path']).read_text())['outputs']) == 2


def test_workbook_partial_export_retry_reuses_receipt_without_duplicates(tmp_path, monkeypatch):
    import queue_runner
    path = tmp_path/'report.xlsx'
    make_two_sheet_workbook(path)
    store = setup_queue(tmp_path, [dict(kind='file', source=str(path), title=path.name)])
    run = runner(store, tmp_path)
    vault = tmp_path/'vault'
    run.options['vault_dir'] = str(vault)
    write = queue_runner.atomic_write_chunks
    vault_writes = []
    def interrupted_write(target, chunks):
        if vault in Path(target).parents:
            vault_writes.append(Path(target))
            if len(vault_writes) == 2:
                raise OSError('Vault disk unavailable')
        return write(target, chunks)
    monkeypatch.setattr(queue_runner, 'atomic_write_chunks', interrupted_write)
    run.run(store.active_id)
    failed = store.items(store.active_id)[0]
    assert failed['status'] == 'failed' and 'Vault disk unavailable' in failed['error']
    assert len(list((tmp_path/'output').rglob('*.md'))) == 2
    assert len(list(vault.rglob('*.md'))) == 1
    original_destination = failed['output_path']
    monkeypatch.setattr(queue_runner, 'atomic_write_chunks', write)
    retry = runner(store, tmp_path, route_fn=lambda *args, **kwargs: pytest.fail('Do not reconvert completed sheets'))
    retry.options['output_dir'] = str(tmp_path/'elsewhere')
    retry.run(store.active_id, retry_failed=True)
    saved = store.items(store.active_id)[0]
    assert saved['status'] == 'done' and saved['output_path'] == original_destination
    assert saved['receipt_path'] == failed['receipt_path']
    assert len(list((tmp_path/'output').rglob('*.md'))) == 2
    assert len(list(vault.rglob('*.md'))) == 2
    assert not (tmp_path/'elsewhere').exists()


def test_missing_receipt_starts_fresh_attempt_excluding_partial_old_sheets(tmp_path):
    path = tmp_path/'report.xlsx'
    make_two_sheet_workbook(path)
    store = setup_queue(tmp_path, [dict(kind='file', source=str(path), title=path.name)])
    item = store.items(store.active_id)[0]
    old_work = tmp_path/'cache'/item['id']/'interrupted'
    old_sheets = old_work/'converted'/'spreadsheets'
    old_sheets.mkdir(parents=True)
    (old_sheets/'stale-sheet.md').write_text('Do not publish old partial content.')
    store.update_item(item['id'], status='processing', receipt_path=str(old_work/'receipt.json'))
    run = runner(store, tmp_path)
    run.run(store.active_id)
    restored = store.items(store.active_id)[0]
    assert restored['status'] == 'done'
    assert Path(restored['receipt_path']).parent != old_work
    published = list(Path(restored['output_path']).glob('*.md'))
    assert len(published) == 2
    assert all('old partial' not in file.read_text() for file in published)
