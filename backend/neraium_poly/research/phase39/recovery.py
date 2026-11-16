"""Verified paged source selection around the unchanged frozen SII experiment.

Only rows the original observe() immediately ignores are filtered. Actionable
originals remain byte-authenticated, unmodified, chronologically ordered, and
subject to the original 1,000-row / 64-MiB guard and timely enrollment veto.
"""
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Literal

from neraium_poly.contracts import Record
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase17.provenance import ReadonlyArchive, _json, _time

MAX_BYTES=64*1024**2
MAX_PAYLOAD=16*1024**2


class PairedRecoveryAudit(Record):
    result:dict
    research_only:Literal[True]=True
    trading_authority:Literal[False]=False
    certification_authority:Literal[False]=False


def recovery_sources(store, *, frontier, cutoff, max_rows=100000, seconds=60):
    """Snapshot catalog pages, authenticate every original, retain no ignored rows.

    A complete bounded scan must finish before any candidate reaches enrollment.
    Missing/corrupt sources, elapsed/row/byte limits and unavailable cold originals
    fail closed. No archive owner, restoration, compaction, or mutation is opened.
    """
    if not 1<=max_rows<=100000 or not 0<seconds<=60:raise ValueError('bounded paired recovery scan required')
    frontier,cutoff=_time(frontier),_time(cutoff)
    if cutoff<frontier:raise ValueError('paired recovery future frontier')
    directory=getattr(store,'directory',None)
    reader=ReadonlyArchive(directory,max_payload_bytes=MAX_PAYLOAD,max_query_bytes=MAX_BYTES) if directory else None
    if reader:
        db=reader._connection(reader.catalog_path);table='records'
    else:
        name=store.connection.execute('PRAGMA database_list').fetchone()[2]
        if not name:raise ValueError('file-backed paired recovery source required')
        db=sqlite3.connect(Path(name).resolve().as_uri()+'?mode=ro',uri=True,timeout=3)
        db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON');db.execute('PRAGMA cache_size=-2048');table='events'
    started=time.monotonic();cursor=(frontier.isoformat(),'');rows=0;ignored=0;raw_bytes=0;kept_bytes=2;originals=[];chain=hashlib.sha256()
    try:
        db.execute('BEGIN')
        while True:
            page=db.execute('SELECT id,kind,available_at,event_time,digest'+(',segment' if reader else '')+
                f' FROM {table} WHERE kind=? AND available_at>? AND available_at<=? AND (available_at,id)>(?,?) ORDER BY available_at,id LIMIT 128',
                ('EventProbabilityStudy',frontier.isoformat(),cutoff.isoformat(),*cursor)).fetchall()
            if not page:break
            for row in page:
                rows+=1
                if rows>max_rows or time.monotonic()-started>seconds:raise ValueError('paired recovery scan incomplete; no enrollment')
                if reader:raw=reader._fetch(row)[1]
                else:
                    size=db.execute('SELECT length(CAST(payload AS BLOB)) FROM events WHERE id=?',(row['id'],)).fetchone()[0]
                    if not 0<size<=MAX_PAYLOAD:raise ValueError('bounded paired recovery source payload required')
                    raw=db.execute('SELECT payload FROM events WHERE id=?',(row['id'],)).fetchone()[0]
                if hashlib.sha256(raw.encode()).hexdigest()!=row['digest']:raise ValueError('paired recovery source hash mismatch')
                original=_json(raw)
                if (original.get('id')!=row['id'] or _time(original['available_at'])!=_time(row['available_at'])
                    or _time(original['timestamp'])!=_time(row['event_time']) or _time(original['timestamp'])>_time(original['available_at'])):
                    raise ValueError('paired recovery source identity/time mismatch')
                raw_bytes+=len(raw.encode());chain.update(digest([row['id'],row['digest'],row['available_at']]).encode())
                cursor=(row['available_at'],row['id'])
                if original.get('operation')!='forecast_scan' or not original.get('forecast'):
                    ignored+=1;continue
                kept_bytes+=len(json.dumps(original).encode())+2
                if len(originals)>=999 or kept_bytes>MAX_BYTES:raise ValueError('bounded paired recovery snapshot required')
                originals.append(original)
    finally:
        db.close()
        if reader:reader.close()
    return originals,{'frontier':frontier.isoformat(),'cutoff':cutoff.isoformat(),'verified_rows':rows,
        'ignored_non_forecasts':ignored,'retained_originals':len(originals),'source_bytes_verified':raw_bytes,
        'retained_serialized_bytes':kept_bytes,'source_chain_sha256':chain.hexdigest(),
        'scan_complete':True,'snapshot_guard_bytes':MAX_BYTES,'page_rows':128,'max_source_payload_bytes':MAX_PAYLOAD}


class PairedRecoveryStore:
    """I/O view only: frozen scientific source, experiment and checkpoints unchanged."""
    def __init__(self,store,*,clock,can_write):self.store,self.clock,self.can_write=store,clock,can_write
    def __getattr__(self,name):return getattr(self.store,name)
    def latest(self,kind,limit=100):
        if kind!='EventProbabilityStudy':return self.store.latest(kind,limit=limit)
        if limit!=1000:raise ValueError('frozen paired recovery query required')
        checkpoints=self.store.latest('PairedForecastStudy',limit=1)
        if not checkpoints:raise ValueError('existing paired declaration required')
        row=checkpoints[0];state=row['checkpoint']
        if (digest(state)!=row['checkpoint_sha256'] or digest(row['experiment'])!=state['experiment_sha256']
            or row.get('trading_authority') is not False or row.get('certification_authority') is not False):
            raise ValueError('paired recovery checkpoint integrity mismatch')
        now=_time(self.clock())
        originals,result=recovery_sources(self.store,frontier=state['last_source_at'] or state['declared_at'],cutoff=now)
        result.update(checkpoint_id=row['id'],experiment_sha256=state['experiment_sha256'],
            recovery_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        if self.can_write() is not True:raise ValueError('paired recovery audit storage backpressure')
        self.store.append(PairedRecoveryAudit(id=digest(['paired-recovery-audit',result]),timestamp=now,available_at=now,
            source='neraium-poly/paired-recovery/v39',result=result))
        return originals
