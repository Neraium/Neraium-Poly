"""Compare financial state, forecast journals, and frozen proof bytes read-only."""
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from threading import RLock

from neraium_poly.research.phase12.ledger import EventForecastLedger
from neraium_poly.research.phase13.runtime import SportsForecastJournal
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase35.native import replay_native_directory
from neraium_poly.research.phase44.native import replay
from neraium_poly.research.phase47.cohort import FROZEN
from neraium_poly.research.phase47.storage import read


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def ro(path):
    return sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)


def accounts(root):
    out={}
    for name in ('paper-live','experimental-paper'):
        directory=Path(root)/name
        with closing(ro(directory/'risk.sqlite')) as db:
            risk=db.execute('SELECT * FROM account ORDER BY id').fetchall()
            positions=db.execute('SELECT * FROM positions ORDER BY 1').fetchall()
            pending=db.execute('SELECT * FROM reservations WHERE released=0 ORDER BY 1').fetchall()
            fills=db.execute("SELECT count(*) FROM audit WHERE action IN ('fill','experimental_exit_fill')").fetchone()[0]
            kill=db.execute('SELECT kill FROM account WHERE id=1').fetchone()[0]
            assert kill==(name=='experimental-paper') and not positions and not pending
            assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        with closing(ro(directory/'broker.sqlite')) as db:
            orders=db.execute('SELECT * FROM orders ORDER BY 1').fetchall()
            assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        out[name]={'risk_sha256':digest(risk),'positions':len(positions),'unreleased_reservations':len(pending),
                   'fills':fills,'orders':len(orders),'broker_orders_sha256':digest(orders),'stop_latched':bool(kill)}
    return out


def journal_heads(directory):
    result={}
    for suffix,cls in [('forecasts.sqlite',EventForecastLedger),('domains/forecasts.sqlite',EventForecastLedger),
                       ('sports/prospective.sqlite',SportsForecastJournal)]:
        obj=cls.__new__(cls)
        obj._lock=RLock()
        obj.max_records=100000
        with closing(ro(directory/'event-intelligence'/suffix)) as db:
            obj.db=db
            db.row_factory=sqlite3.Row
            assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
            result[suffix]=obj.verify()
    return result


def native(directory):
    root=directory/'phase42-native'
    admin=directory/'native-migration48'
    manifest=json.loads((admin/'plan.json').read_bytes())
    for name,entry in manifest['files'].items():
        raw=read(root/name) if entry['compress'] else (root/name).read_bytes()
        assert len(raw)==entry['bytes'] and sha(raw)==entry['sha256'],name
    found={}
    for path in sorted({item.parent for item in root.rglob('proof.json*') if item.name in ('proof.json','proof.json.gz')}):
        bundle=json.loads(read(path/'bundle.json'))
        actual=replay_native_directory(path) if 'parent_event' in bundle else replay(path)
        assert actual==json.loads(read(path/'proof.json'))
        found[str(path.relative_to(root))]=digest(actual)
    assert all(found[name]==expected for name,expected in manifest['proofs'].items())
    return {'proofs':found,'original_files':len(manifest['files']),'backup_sha256':sha((admin/'original-native.tar.gz').read_bytes())}


def trials(get):
    result={}
    for fid in FROZEN:
        row=get(fid)
        assert row[2]==sha(row[1].encode())
        record=json.loads(row[1])
        assert digest(record['source_forecast'])==record['source_binding']['forecast_sha256']
        result[fid]=row[2]
    return result
