"""Durable mixed queues: convert privately, record a receipt, then publish."""
from itertools import groupby
import json
from pathlib import Path
import re
from uuid import uuid4

from file_utils import atomic_write_chunks, atomic_write_text
from quote_checkpoint import QuoteCheckpoint, batch_lock, is_review_failure


IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}
_LEGACY_PDF_PARTIAL = re.compile(r'^PARTIAL -> ([^/\\\n]+\.md); OCR failed on pages \[(\d+(?:, \d+)*)\]$', re.M)


class QueueRunner:
    def __init__(self, store, cache_dir, options, *, should_cancel=lambda: False,
                 on_change=lambda: None, on_status=lambda message: None,
                 on_progress=lambda current, total, title: None,
                 on_item_processed=lambda completed, total: None,
                 route_fn=None, paste_fn=None):
        self.store = store
        self.cache_dir = Path(cache_dir)
        self.options = options
        self.should_cancel = should_cancel
        self.on_change = on_change
        self.on_status = on_status
        self.on_progress = on_progress
        self.on_item_processed = on_item_processed
        self.route_fn = route_fn
        self.paste_fn = paste_fn

    def run(self, queue_id, retry_failed=False, selected_ids=None):
        self.store.recover_interrupted()
        with self.store.worker_lock():
            items = self.store.items(queue_id)
            eligible_status = 'failed' if retry_failed else 'waiting'
            if selected_ids is not None:
                if isinstance(selected_ids, str):
                    raise ValueError('Select item IDs from this collection')
                selected_ids = set(selected_ids)
                if not selected_ids <= {item['id'] for item in items}:
                    raise ValueError('Selected items do not belong to this collection')
                if any(item['status'] != eligible_status for item in items if item['id'] in selected_ids):
                    raise ValueError(f'Only {eligible_status} items can be selected for this run')
            candidates = [item for item in items if item['status'] == eligible_status
                          and (selected_ids is None or item['id'] in selected_ids)]
            selected = []
            journals = {}
            for item in candidates:
                record = {}
                if item['checkpoint_path']:
                    path = item['checkpoint_path']
                    if path not in journals:
                        try:
                            checkpoint = QuoteCheckpoint.load(Path(path))
                            journals[path] = {row['path']: row for row in checkpoint.items}
                        except (OSError, ValueError):
                            # Let normal conversion report an unavailable journal.
                            journals[path] = {}
                    record = journals[path].get(str(Path(item['source']).resolve()), {})
                if record.get('skipped'):
                    if selected_ids is not None:
                        raise ValueError('Skipped images cannot be retried')
                    continue
                if retry_failed and selected_ids is None and (is_review_failure(item) or is_review_failure(record)):
                    continue
                selected.append(item)
            unconfigured = [item['id'] for item in selected if not item['options']]
            self.store.update_items(unconfigured, options=self.options)
            for item in selected:
                if not item['options']:
                    item['options'] = dict(self.options)
            images = [item for item in selected if item['kind'] == 'file'
                      and Path(item['source']).suffix.lower() in IMAGE_EXTENSIONS]
            documents = [item for item in selected if item not in images]
            total = len(selected)
            processed = 0
            for item in documents:
                if self.should_cancel():
                    break
                self.on_progress(processed + 1, total, item['title'])
                if self._document(item):
                    processed += 1
                    self.on_item_processed(processed, total)
                self.on_change()
            # A checkpoint keeps the whole image collection and its shared export.
            # Existing groups are reused; newly queued images get a fresh journal.
            key = lambda item: (item['checkpoint_path'] or '', json.dumps(item['options'], sort_keys=True))
            for _, grouped in groupby(sorted(images, key=key), key=key):
                if self.should_cancel():
                    break
                group = list(grouped)
                processed += self._images(group, retry_failed, processed, total)
            self.on_change()
        return self.store.state()

    def _document(self, item):
        if self.route_fn is None and item['kind'] == 'file' and Path(item['source']).suffix.lower() == '.pdf':
            return self._pdf_document(item)
        item_id = item['id']
        self.store.update_item(item_id, status='processing', error='')
        self.on_change()
        # A stored receipt identifies this source's conversion attempt. Locate
        # file clears it; a fresh attempt must not discover the old source's
        # receipt merely because the queue item kept the same identity.
        saved_receipt = Path(item['receipt_path']) if item['receipt_path'] else None
        receipt_path = (saved_receipt if saved_receipt and saved_receipt.is_file() else
                        self.cache_dir / item_id / uuid4().hex / 'receipt.json')
        work = receipt_path.parent
        self.store.update_item(item_id, receipt_path=str(receipt_path))
        try:
            if receipt_path.exists():
                receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
            else:
                if item['kind'] == 'file' and not Path(item['source']).is_file():
                    raise FileNotFoundError('Source file is missing. Use Locate file to reconnect it.')
                work.mkdir(parents=True, exist_ok=True)
                from converters import route, convert_raw_text
                extension = Path(item['source']).suffix.lower() if item['kind'] == 'file' else ''
                kwargs = {'should_cancel': self.should_cancel} if extension in ('.pdf', '.epub') else {}
                if extension == '.epub':
                    kwargs['epub_output_format'] = item['options'].get('epub_output_format', 'md')
                if item['kind'] == 'text':
                    # Injected paste converters receive the base output folder,
                    # matching the existing test/extension contract. The normal
                    # path must honor the saved kind rather than sniff a URL.
                    result = (self.paste_fn(item['source'], work / 'converted', None)
                              if self.paste_fn else
                              convert_raw_text(item['source'], work / 'converted' / 'txt', None))
                else:
                    result = (self.route_fn or route)(item['source'], work / 'converted', None, **kwargs)
                if not result.success:
                    if self.should_cancel():
                        self.store.update_item(item_id, status='waiting', error='')
                        return False
                    raise RuntimeError(result.message)
                source_output = Path(result.output_path)
                if source_output.is_file():
                    receipt = {'source_output': str(source_output), 'word_count': result.word_count,
                               'format': source_output.parent.name, 'filename': source_output.name}
                elif (item['kind'] == 'file' and Path(item['source']).suffix.lower() == '.xlsx'
                      and source_output.is_dir()):
                    from converters import safe_filename
                    outputs = [{'source_output': str(path), 'filename': path.name}
                               for path in sorted(source_output.glob('*.md')) if path.is_file()]
                    if not outputs:
                        raise OSError('Workbook conversion did not produce any worksheet files.')
                    receipt = {'outputs': outputs, 'word_count': result.word_count,
                               'format': 'spreadsheets',
                               'directory_name': safe_filename(Path(item['source']).stem) or 'workbook'}
                else:
                    raise OSError('Conversion did not produce its expected output file.')
                atomic_write_text(receipt_path, json.dumps(receipt))
            item = self.store.get_item(item_id)
            self._publish(item, receipt)
            self.store.update_item(item_id, status='done', error='', word_count=receipt['word_count'])
            self.on_status(f"Saved: {item['title']}")
        except Exception as exc:
            self.store.update_item(item_id, status='failed', error=str(exc))
            self.on_status(f"Failed: {item['title']}: {exc}")
        return True

    def _pdf_document(self, item):
        """Resume conversion by page; publish only the resulting snapshot."""
        from pdf_delivery import migrate_pdf_receipt, publish_pdf_snapshot
        from pdf_recovery import convert_queued_pdf

        item_id = item['id']
        previous_error = item['error'] or ''
        legacy = _LEGACY_PDF_PARTIAL.search(previous_error)
        partial = previous_error.startswith('Partial PDF:')
        warning = previous_error.split('\n', 1)[0] if partial else ''
        primary_published = False
        root = self.cache_dir.resolve() / item_id
        receipt_path = Path(item['receipt_path']) if item['receipt_path'] else root / uuid4().hex / 'receipt.json'
        work = receipt_path.parent
        # Keep the legacy diagnostic until migration is durable, including if
        # Stop or a process interruption occurs before the first recovery pass.
        self.store.update_item(item_id, status='processing', receipt_path=str(receipt_path))
        self.on_change()
        try:
            if (receipt_path.name != 'receipt.json' or work.parent != root or not re.fullmatch(r'[0-9a-f]{32}', work.name)
                    or receipt_path.resolve() != receipt_path):
                raise ValueError('The saved PDF attempt path is invalid.')
            work.mkdir(parents=True, exist_ok=True)
            receipt = json.loads(receipt_path.read_text(encoding='utf-8')) if receipt_path.is_file() else None
            if receipt is not None and not isinstance(receipt, dict):
                raise ValueError('Invalid PDF delivery receipt.')
            if receipt is not None and 'pdf_failed_pages' not in receipt:
                # Older completed conversions can already have a delivery
                # receipt. Preserve earlier user files while reusing its text.
                receipt = migrate_pdf_receipt(self.store.get_item(item_id), receipt)
                atomic_write_text(receipt_path, json.dumps(receipt))
            if receipt is not None and type(receipt.get('pdf_delivery_pending')) is not bool:
                raise ValueError('Invalid PDF delivery receipt.')
            if receipt is None or (receipt['pdf_failed_pages'] and not receipt['pdf_delivery_pending']):
                checkpoint = work / 'pdf-progress.json'
                if (receipt is not None or partial) and not checkpoint.is_file():
                    raise ValueError('Saved PDF page results are missing. The previous export is still available.')
                legacy_output = work / 'converted' / 'pdf' / legacy[1] if legacy else None
                legacy_pages = tuple(map(int, legacy[2].split(', '))) if legacy else ()
                source = Path(item['source'])
                if not source.is_file():
                    raise FileNotFoundError('PDF source is missing. Restore it to retry saved pages, or use Locate file to start again.')
                result = convert_queued_pdf(source, work, should_cancel=self.should_cancel,
                    legacy_output=legacy_output, legacy_failed_pages=legacy_pages)
                if result.canceled:
                    self.store.update_item(item_id, status='failed' if (partial or legacy) else 'waiting')
                    return False
                if result.output_path is None:
                    raise ValueError('No PDF export was produced.')
                if receipt is None or receipt['source_output'] != str(result.output_path):
                    receipt = {'source_output': str(result.output_path), 'word_count': result.word_count,
                               'pdf_failed_pages': list(result.failed_pages), 'pdf_delivery_pending': True}
                else:
                    receipt['pdf_delivery_pending'] = True
                atomic_write_text(receipt_path, json.dumps(receipt))
            pages = receipt['pdf_failed_pages']
            if pages:
                warning = 'Partial PDF: OCR still needed on pages ' + ', '.join(map(str, pages)) + '.'

            def persist():
                atomic_write_text(receipt_path, json.dumps(receipt))

            def record_primary(output):
                nonlocal primary_published
                self.store.update_item(item_id, output_path=str(output), word_count=receipt['word_count'])
                primary_published = True

            publish_pdf_snapshot(self.store.get_item(item_id), receipt, persist=persist, on_primary=record_primary)
            receipt['pdf_delivery_pending'] = False
            persist()
            if pages:
                self.store.update_item(item_id, status='failed', error=warning)
                self.on_status(f"Saved partial: {item['title']} — {warning}")
            else:
                self.store.update_item(item_id, status='done', error='')
                self.on_status(f"Saved: {item['title']}")
        except Exception as exc:
            if warning and (not primary_published or receipt['pdf_failed_pages']):
                error = f'{warning}\n{exc}'
            elif legacy and not (work / 'pdf-progress.json').is_file():
                error = f'{legacy[0]}\nCould not recover the saved partial PDF: {exc}'
            else:
                error = f'Converted PDF is saved; additional delivery failed: {exc}' if primary_published else str(exc)
            self.store.update_item(item_id, status='failed', error=error)
            self.on_status(f"Failed: {item['title']}: {error}")
        return True

    def _publish(self, item, receipt):
        collection = 'outputs' in receipt
        outputs = receipt['outputs'] if collection else [receipt]
        for entry in outputs:
            if not Path(entry['source_output']).is_file():
                raise FileNotFoundError('Saved conversion data is missing; restore the app’s queue data before retrying.')
        # Stable item identity closes the crash window between publishing and
        # committing done. A workbook owns one folder, and its receipt lists
        # every worksheet so an interrupted export repairs the same files.
        if collection:
            name = f"{receipt['directory_name']}_{item['id'][:12]}"
        else:
            suffix = Path(receipt['filename']).suffix.lower()
            if suffix not in ('.md', '.txt'):
                raise ValueError('Saved conversion has an unsupported output extension.')
            name = f"{Path(receipt['filename']).stem}_{item['id'][:12]}{suffix}"
        output = Path(item['output_path']) if item['output_path'] else Path(item['options']['output_dir']) / receipt['format'] / name
        self.store.update_item(item['id'], output_path=str(output))
        vault = item['options'].get('vault_dir')
        for entry in outputs:
            source = Path(entry['source_output'])
            target = output / entry['filename'] if collection else output
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(encoding='utf-8') as stream:
                atomic_write_chunks(target, iter(lambda: stream.read(65536), ''))
            if vault:
                from converters import vault_frontmatter
                vault_name = name if collection else str(Path(name).with_suffix('.md'))
                vault_target = Path(vault) / receipt['format'] / vault_name
                if collection:
                    vault_target /= entry['filename']
                vault_target.parent.mkdir(parents=True, exist_ok=True)
                def chunks():
                    yield vault_frontmatter(item['title'], receipt['format'], item['source'])
                    with source.open(encoding='utf-8') as stream:
                        yield from iter(lambda: stream.read(65536), '')
                atomic_write_chunks(vault_target, chunks())
        copy_dir = item['options'].get('copy_dir')
        if copy_dir:
            from output_copy import deliver_output_copies
            published = ([output / entry['filename'] for entry in outputs]
                         if collection else [output])
            def persist_receipt():
                atomic_write_text(Path(item['receipt_path']), json.dumps(receipt))
            try:
                deliver_output_copies(published, base_dir=Path(item['options']['output_dir']),
                    copy_dir=Path(copy_dir), manifest=receipt, persist=persist_receipt,
                    copy_mode=item['options'].get('copy_mode', 'subfolder'))
            except (OSError, ValueError) as exc:
                raise RuntimeError(f'Converted output is saved; additional copy failed: {exc}') from exc

    def _images(self, items, retry_failed, completed, total):
        from converters import convert_image_folder_quotes, quote_batch_stem, QuoteBatchHooks
        first = items[0]
        options = first['options']
        output = Path(options['output_dir']) / 'quotes'
        checkpoint_path = first['checkpoint_path']
        started_ids = set()
        finished_ids = set()
        active_id = None

        def finished(item_id):
            if item_id not in finished_ids:
                finished_ids.add(item_id)
                self.on_item_processed(completed + len(finished_ids), total)

        try:
            if not checkpoint_path:
                paths = [item['source'] for item in items]
                with batch_lock(output):
                    checkpoint = QuoteCheckpoint(output, quote_batch_stem(paths), paths, options['raw_ocr_mode'])
                    checkpoint.report['queue_owned'] = True
                    if options.get('copy_dir'):
                        checkpoint.report['copy_dir'] = options['copy_dir']
                        if options.get('copy_mode', 'subfolder') != 'subfolder':
                            checkpoint.report['copy_mode'] = options['copy_mode']
                    checkpoint.save('running')
                checkpoint_path = str(checkpoint.report_path)
                self.store.update_items([item['id'] for item in items], checkpoint_path=checkpoint_path)
                retry_failed = False  # A newly linked checkpoint contains pending images.
            checkpoint = QuoteCheckpoint.load(Path(checkpoint_path))
            if (checkpoint.report.get('copy_dir') != options.get('copy_dir')
                    or checkpoint.report.get('copy_mode', 'subfolder') != options.get('copy_mode', 'subfolder')):
                raise ValueError('The image copy destination differs from the saved queue destination.')
            self.on_change()
            def started(n, count, name):
                nonlocal active_id
                self.on_progress(completed + len(started_ids) + 1, total, name)
                # The journal identifies the exact path, even when filenames repeat.
                current = QuoteCheckpoint.load(Path(checkpoint_path)).report.get('current_image')
                for item in items:
                    if str(Path(item['source']).resolve()) == current:
                        active_id = item['id']
                        started_ids.add(active_id)
                        self.store.update_item(item['id'], status='processing', error='')
                        item.update(status='processing', error='')
                        break
                self.on_change()
            def reconcile(n=None, count=None, name=None):
                nonlocal active_id
                self._reconcile_images(items, Path(checkpoint_path))
                # The converter also reports saved journal totals before OCR.
                # Only an actual started/finished pair completes an attempt.
                if n is not None and active_id is not None:
                    finished(active_id)
                    active_id = None
                self.on_change()
            convert_image_folder_quotes(
                [item['path'] for item in checkpoint.items], output,
                Path(options['vault_dir']) if options.get('vault_dir') else None,
                hooks=QuoteBatchHooks(should_cancel=self.should_cancel,
                    on_image_started=started,
                    on_image_processed=reconcile, on_status=self.on_status),
                raw_ocr_mode=options['raw_ocr_mode'], checkpoint_path=Path(checkpoint_path),
                retry_failed=retry_failed, preserve_completed=True,
                selected_paths={str(Path(item['source']).resolve()) for item in items})
            reconcile()
            # Export repair can finish saved image records without any new OCR.
            for item in items:
                if item['id'] not in started_ids and self.store.get_item(item['id'])['status'] == 'done':
                    finished(item['id'])
        except Exception as exc:
            # Completed image records remain in the image journal even if an
            # export failed. Retry links back to that journal, without new OCR.
            reconciled_ids = set()
            if checkpoint_path and Path(checkpoint_path).is_file():
                try:
                    reconciled_ids = self._reconcile_images(items, Path(checkpoint_path))
                except (OSError, ValueError):
                    pass  # A damaged journal must still produce failed queue rows.
            for item in items:
                current = self.store.get_item(item['id'])
                pending = current['status'] == 'waiting' and item['id'] in reconciled_ids
                if current['status'] != 'done' and not pending and not is_review_failure(current):
                    self.store.update_item(item['id'], status='failed', error=str(exc))
                if not pending:
                    finished(item['id'])
            self.on_status(f'Image batch needs attention: {exc}')
            self.on_change()
        return len(finished_ids)

    def _reconcile_images(self, items, checkpoint_path):
        checkpoint = QuoteCheckpoint.load(checkpoint_path)
        records = {record['path']: record for record in checkpoint.items}
        export_pending = (checkpoint.report.get('export_pending') or checkpoint.report.get('vault_pending')
                          or checkpoint.report.get('copy_pending'))
        reconciled_ids = set()
        for item in items:
            record = records.get(str(Path(item['source']).resolve()))
            if record is None:
                continue
            reconciled_ids.add(item['id'])
            state = {'success': 'done', 'failed': 'failed', 'pending': 'waiting'}[record['status']]
            error = record.get('error', '')
            if state == 'done' and export_pending:
                state, error = 'failed', 'Image text is saved; retry to finish exporting it.'
            if state == 'failed' and not Path(item['source']).is_file() and not export_pending:
                error = 'Source file is missing. Use Locate file to reconnect it.'
            changes = dict(status=state, error=error, output_path=str(checkpoint.path),
                           word_count=sum(len(record['quote'].split()) for record in record['records']))
            if any(item.get(key) != value for key, value in changes.items()):
                self.store.update_item(item['id'], **changes)
                item.update(changes)
        return reconciled_ids
