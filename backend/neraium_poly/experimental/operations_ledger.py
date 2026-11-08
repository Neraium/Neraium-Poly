"""Current committed paper-ledger observations; never execution authority.

Each database is read in a separate read-only transaction. This does not perform
expiry, reconciliation, or claim an atomic snapshot across the two ledgers.
"""
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

from neraium_poly.risk.engine import RiskEngine


def _read(path):
    path=Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError('existing regular paper ledger required')
    db=sqlite3.connect('file:'+quote(str(path.resolve()),safe='/')+'?mode=ro',uri=True,timeout=.25)
    try:
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        return db
    except BaseException:
        db.close()
        raise


def operations_ledger(directory,*,clock):
    """Reuse the engine's read-only state math, bypass its writer connection lock.

    The engine still uses its own current locked transaction for every decision.
    A failed/locked read propagates: no cached balance or invented zero is used.
    """
    directory=Path(directory)
    risk_at=clock()
    with closing(_read(directory/'risk.sqlite')) as db:
        capital=RiskEngine._state(SimpleNamespace(db=db),risk_at)
        positions=db.execute('SELECT count(*) FROM positions').fetchone()[0]
        fills=db.execute("SELECT count(*) FROM audit WHERE action IN ('fill','experimental_exit_fill')").fetchone()[0]
    broker_at=clock()
    with closing(_read(directory/'broker.sqlite')) as db:
        orders=db.execute('SELECT count(*) FROM orders').fetchone()[0]
    return capital,{'open_positions':positions,'fills':fills,'orders_submitted':orders,
        'capital_observation':{'risk_read_started_at':risk_at.isoformat(),'broker_read_started_at':broker_at.isoformat(),
            'read_completed_at':clock().isoformat(),'scope':'current committed read-only per-ledger transactions; no cross-ledger atomicity or implicit expiry',
            'admission_authority':False,'reconciliation_performed':False}}
