"""Evaluate SQLite WAL checkpoint on byte-verified private forecast copies."""
import hashlib
import json
import os
import shutil
import signal
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from neraium_poly.research.phase12.contracts import EventEvidence
from neraium_poly.research.phase12.ledger import EventForecastLedger
from neraium_poly.research.phase14.contracts import DomainEvidence
from neraium_poly.research.phase14.ledger import UniversalForecastLedger

source = Path('/home/ubuntu/Neraium-Poly/data/experimental-paper/event-intelligence')
scratch = Path(sys.argv[1])
assert not scratch.exists() and not scratch.resolve().is_relative_to(source.parent)
scratch.mkdir()
cap = 64*1024**2

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()

def bytes_by_file(path):
    return {file.name:file.stat().st_size for file in path.glob('forecasts.sqlite*')}

def verify(path):
    model=UniversalForecastLedger if path.name=='domains' else EventForecastLedger
    options={'max_bytes':cap} if path.name=='domains' else {'max_bytes':cap,'max_records':20000}
    ledger=model(path,**options)
    db=ledger.engine.db if path.name=='domains' else ledger.db
    digest=hashlib.sha256()
    for row in db.execute('SELECT * FROM journal ORDER BY seq'):
        digest.update((json.dumps(tuple(row))+'\n').encode())
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    return ledger,db,{'chain':ledger.verify(),'logical_sha256':digest.hexdigest()}

results={}
for name, origin, schema in [('legacy',source,EventEvidence),('domains',source/'domains',DomainEvidence)]:
    private = scratch/name
    private.mkdir()
    before = bytes_by_file(origin)
    hashes={}
    for suffix in ('','-wal'):
        p=origin/('forecasts.sqlite'+suffix)
        initial=sha(p)
        duplicate=private/p.name
        shutil.copyfile(p,duplicate)
        assert initial==sha(duplicate)==sha(p)
        hashes[p.name]=initial
    assert before==bytes_by_file(origin)
    ledger,db,initial=verify(private)
    before_checkpoint=bytes_by_file(private)
    payload=db.execute("SELECT payload FROM journal WHERE kind=? ORDER BY seq DESC LIMIT 1",('domain_evidence' if name=='domains' else 'evidence',)).fetchone()[0]
    original=schema.model_validate_json(payload)
    assert ledger.record_evidence(original) is False
    trial=original.model_copy(update={'id':'CONTROLLED-phase50-isolated-retry'})
    try:
        ledger.record_evidence(trial)
    except ValueError as exc:
        assert str(exc)=='forecast storage budget exhausted'
    else:
        raise AssertionError('expected cap rejection')
    assert tuple(db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone())==(0,0,0)
    after_checkpoint=bytes_by_file(private)
    assert sum(after_checkpoint.values())<cap
    assert ledger.verify()==initial['chain']
    ledger.close()
    # Interrupt a new write before its transaction commits. On restart the exact
    # original prefix must survive and the same candidate must be retryable.
    pid=os.fork()
    if pid==0:
        child,child_db,_=verify(private)
        child_db.execute('BEGIN IMMEDIATE')
        assert child.record_evidence(trial) is True
        os.kill(os.getpid(),signal.SIGKILL)
    _,status=os.waitpid(pid,0)
    assert os.WIFSIGNALED(status) and os.WTERMSIG(status)==signal.SIGKILL
    ledger,db,recovered=verify(private)
    assert recovered==initial
    assert ledger.record_evidence(trial) is True and ledger.record_evidence(trial) is False
    committed={'records':ledger.verify()['records'],'id':trial.id}
    ledger.close()
    ledger,db,reopened=verify(private)
    assert ledger.record_evidence(trial) is False and reopened['chain']['records']==initial['chain']['records']+1
    ledger.close()
    results[name]={'source_bytes':before,'source_sha256':hashes,'before_checkpoint':before_checkpoint,
                   'after_checkpoint':after_checkpoint,'headroom_bytes':cap-sum(after_checkpoint.values()),
                   'original':initial,'after_killed_uncommitted_write':recovered,'controlled_retry':committed,
                   'after_restart':reopened,'guard_bytes':cap}
Path(sys.argv[2]).write_text(json.dumps(results,indent=2)+'\n')
