"""Bounded read-only immutable archive verification with explicit continuation.

Reports are evidence of the stated range only; they never grant order, retention
or startup authority. Active SQLite files are excluded and must be recovered by
their exclusive writer. Each completed segment is fully replayed and compared
to its catalog, including original JSON metadata and the compressed roundtrip.
"""
import argparse
import gzip
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from neraium_poly.data.segmented import CHUNK, NAME, _payload_metadata, _readonly


def audit(directory, *, after="", max_segments=16, max_seconds=60):
    if not 1 <= max_segments <= 256 or not 1 <= max_seconds <= 1800:
        raise ValueError('bounded archive audit required')
    if after and after != 'legacy' and not NAME.fullmatch(after):
        raise ValueError('invalid archive audit cursor')
    root = Path(directory).resolve(strict=True)
    start = monotonic()
    deadline = start + max_seconds

    def check():
        if monotonic() >= deadline:
            raise TimeoutError('archive audit time budget exhausted')

    def fingerprint(path):
        if path.is_symlink() or not path.is_file():
            raise ValueError('archive source missing or symlinked')
        s = path.stat()
        return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)

    def sha(path, *, compressed=False):
        digest, size = hashlib.sha256(), 0
        with (gzip.open(path, 'rb') if compressed else path.open('rb')) as handle:
            while True:
                check()
                chunk = handle.read(CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size

    report = {'started_at': datetime.now(UTC).isoformat(), 'directory': str(root),
              'after': after, 'next_after': after, 'segments': [], 'status': 'partial',
              'records_verified': 0, 'source_bytes_verified': 0,
              'originals_modified': False, 'active_sources_verified': False,
              'admission_authority': False, 'retention_authority': False}
    catalog = _readonly(root / 'events-archive.sqlite')
    catalog.row_factory = sqlite3.Row
    catalog.set_progress_handler(lambda: int(monotonic() >= deadline), 1000)
    try:
        catalog.execute('BEGIN')
        rows = catalog.execute('SELECT * FROM segments WHERE name>? ORDER BY name LIMIT ?',
                               (after, max_segments + 1)).fetchall()
        for stored in rows[:max_segments]:
            check()
            row = dict(stored)
            name = row['name']
            if name != 'legacy' and not NAME.fullmatch(name):
                raise ValueError('invalid archive segment identity')
            if row['status'] not in ('sealed', 'legacy'):
                report['segments'].append({'segment': name, 'status': 'active_withheld'})
                report['next_after'] = name
                continue
            raw = root / 'events.sqlite' if name == 'legacy' else root / 'events-segments' / name
            identity = fingerprint(raw)
            for suffix in ('-wal', '-journal'):
                sidecar = Path(str(raw) + suffix)
                if sidecar.is_symlink() or (sidecar.exists() and sidecar.stat().st_size):
                    raise ValueError('immutable archive has uncheckpointed writer')
            if sha(raw) != (row['raw_sha'], row['raw_size']):
                raise ValueError('immutable archive source changed')
            manifest = Path(str(raw) + '.manifest.json')
            if name != 'legacy':
                fingerprint(manifest)
                if manifest.stat().st_size > 16384:
                    raise ValueError('archive manifest too large')
                expected = {'schema_version': '1.0', 'segment': name, 'raw_sha256': row['raw_sha'],
                            'raw_bytes': row['raw_size'], 'records': row['records'], 'retention_policy': 'retain_original'}
                if json.loads(manifest.read_text()) != expected:
                    raise ValueError('immutable archive manifest changed')
            db = _readonly(raw)
            db.set_progress_handler(lambda: int(monotonic() >= deadline), 1000)
            count = 0
            try:
                if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                    raise ValueError('archive SQLite integrity failed')
                indexed = iter(catalog.execute(
                    'SELECT id,kind,available_at,event_time,digest,segment,qualified FROM records '
                    'WHERE segment=? ORDER BY id', (name,)))
                for rid, kind, available, event, payload, digest in db.execute(
                    'SELECT id,kind,available_at,event_time,payload,digest FROM events ORDER BY id'):
                    check()
                    if hashlib.sha256(payload.encode()).hexdigest() != digest:
                        raise ValueError('archive payload hash mismatch')
                    expected = (rid, kind, available, event, digest, name,
                                _payload_metadata(payload, rid, available, event))
                    actual = next(indexed, None)
                    if actual is None or tuple(actual) != expected:
                        raise ValueError('archive catalog identity mismatch')
                    count += 1
                if next(indexed, None) is not None or count != row['records']:
                    raise ValueError('archive catalog completeness mismatch')
            finally:
                db.close()
            if row['gzip_sha']:
                zipped = Path(str(raw) + '.gz')
                zip_identity = fingerprint(zipped)
                if sha(zipped) != (row['gzip_sha'], row['gzip_size']):
                    raise ValueError('compressed archive hash mismatch')
                if sha(zipped, compressed=True) != (row['raw_sha'], row['raw_size']):
                    raise ValueError('compressed archive roundtrip mismatch')
                if fingerprint(zipped) != zip_identity:
                    raise ValueError('compressed archive changed during audit')
            if fingerprint(raw) != identity:
                raise ValueError('immutable source changed during audit')
            report['segments'].append({'segment': name, 'status': 'verified', 'records': count,
                'raw_sha256': row['raw_sha'], 'gzip_sha256': row['gzip_sha'], 'raw_bytes': row['raw_size']})
            report['records_verified'] += count
            report['source_bytes_verified'] += row['raw_size']
            report['next_after'] = name
        report['range_complete'] = len(rows) <= max_segments
        report['status'] = 'range_verified'
    except (TimeoutError, ValueError, OSError, sqlite3.Error) as error:
        report.update(status='partial' if isinstance(error, TimeoutError) or monotonic() >= deadline else 'failed',
                      error=f'{type(error).__name__}:{str(error)[:180]}')
    finally:
        catalog.close()
    report.update(elapsed_seconds=monotonic() - start, completed_at=datetime.now(UTC).isoformat())
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    parser.add_argument('--after', default='')
    parser.add_argument('--max-segments', type=int, default=16)
    parser.add_argument('--max-seconds', type=int, default=60)
    args = parser.parse_args()
    print(json.dumps(audit(args.directory, after=args.after, max_segments=args.max_segments,
                           max_seconds=args.max_seconds), sort_keys=True))
