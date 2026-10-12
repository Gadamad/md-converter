"""Apply source-verified repairs without replacing unrelated saved work.

Callers hold the queue worker and quote batch locks and back up user data first.
Corrections come from inspection of original images, never character stripping.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from quote_checkpoint import fingerprint


def apply_verified_corrections(checkpoint, corrections):
    by_path = {item['path']: item for item in checkpoint.items}
    prepared = []
    seen = set()
    for correction in corrections:
        path = str(Path(correction['path']).resolve())
        index = correction['record_index']
        if type(index) is not int or index < 0 or (path, index) in seen:
            raise ValueError('Invalid or repeated quote correction')
        seen.add((path, index))
        item = by_path.get(path)
        if item is None or item['status'] != 'success' or index >= len(item['records']):
            raise ValueError('The correction does not identify a saved successful quote')
        if (not isinstance(item.get('correction_history', []), list)
                or not all(isinstance(entry, dict) for entry in item.get('correction_history', []))):
            raise ValueError('Invalid quote correction history')
        if (not isinstance(item.get('verified_records', []), list)
                or any(type(i) is not int or not 0 <= i < len(item['records'])
                       for i in item.get('verified_records', []))):
            raise ValueError('Invalid source verification indices')
        if (not correction.get('fingerprint') or item['fingerprint'] != correction['fingerprint']
                or fingerprint(path) != correction['fingerprint']):
            raise ValueError('The original source image changed; review it again before repairing')
        record = item['records'][index]
        if record != correction['expected_record']:
            raise ValueError('Saved quote changed; review it again before repairing')
        quote, author = correction['quote'], correction['author']
        if (not isinstance(quote, str) or not quote.strip() or '\0' in quote
                or not isinstance(author, str) or '\0' in author):
            raise ValueError('A verified correction must contain valid text')
        prepared.append((item, index, record, quote, author))
    # Validate the whole set before altering any saved quote.
    verified_at = datetime.now(timezone.utc).isoformat()
    for item, index, record, quote, author in prepared:
        item.setdefault('correction_history', []).append({
            'record_index': index, 'before': deepcopy(record),
            'source_fingerprint': item['fingerprint'], 'verified_at': verified_at,
            'method': 'visual_source_review', 'quote': quote, 'author': author,
        })
        record.update(quote=quote, author=author)
        item['verified_records'] = sorted(set(item.get('verified_records', [])) | {index})
    return len(prepared)
