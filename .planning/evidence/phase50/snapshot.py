"""Materialize a stratified, byte-verified subset of immutable live archive segments."""
import hashlib
import json
import shutil
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

LIVE_SOURCE = Path('/home/ubuntu/Neraium-Poly/data/experimental-paper')
SOURCE = Path(sys.argv[3]) if len(sys.argv)>3 else LIVE_SOURCE
target = Path(sys.argv[1])
count = int(sys.argv[2])
reserve = 100 * 1024**3
assert 0 < count <= 1600 and not target.exists() and not target.resolve().is_relative_to(LIVE_SOURCE) and not target.resolve().is_relative_to(SOURCE.resolve())
target.mkdir()
(target/'events-segments').mkdir()
manifest = {}
catalog = SOURCE/'events-archive.sqlite'
with closing(sqlite3.connect(catalog.as_uri()+'?mode=ro', uri=True, timeout=8)) as original, closing(sqlite3.connect(target/'events-archive.sqlite')) as copy:
    original.execute('BEGIN')
    eligible = original.execute("SELECT name FROM segments WHERE status='sealed' AND gzip_sha IS NOT NULL ORDER BY name").fetchall()
    chosen = [eligible[i*len(eligible)//count][0] for i in range(count)]
    assert len(set(chosen)) == count
    for schema, in original.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END"):
        copy.execute(schema)
    for row in original.execute('SELECT * FROM archive_meta'):
        copy.execute('INSERT INTO archive_meta VALUES(?,?)', row)
    for name in chosen:
        row = original.execute('SELECT * FROM segments WHERE name=?', (name,)).fetchone()
        assert row
        copy.execute('INSERT INTO segments VALUES(?,?,?,?,?,?,?)', row)
        records = original.execute('SELECT * FROM records WHERE segment=?', (name,)).fetchall()
        assert len(records) == row[4]
        copy.executemany('INSERT INTO records VALUES(?,?,?,?,?,?,?)', records)
        for suffix, expected in [('', row[2]), ('.gz', row[5]), ('.manifest.json', None), ('.cold-proof.json', None)]:
            path = SOURCE/'events-segments'/(name+suffix)
            if not path.exists() and suffix in ('','.cold-proof.json'):
                continue
            assert not path.is_symlink() and shutil.disk_usage(target).free - path.stat().st_size > reserve
            dest = target/'events-segments'/path.name
            shutil.copyfile(path,dest)
            with dest.open('rb') as stream:
                actual = hashlib.file_digest(stream,'sha256').hexdigest()
            if expected:
                assert expected == actual, name
            else:
                assert hashlib.sha256(path.read_bytes()).hexdigest() == actual
            manifest[path.name] = {'bytes':dest.stat().st_size,'sha256':actual}
    copy.commit()
    assert copy.execute('PRAGMA integrity_check').fetchone() == ('ok',)
(target/'snapshot.json').write_text(json.dumps({'population_sealed':len(eligible),'segments':count,'files':manifest},indent=2)+'\n')
