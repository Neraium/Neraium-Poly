"""Read-only exact source audit. Raw original studies remain in source archives."""
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase32.crypto_finance import audit_crypto_finance

root=Path('/home/ubuntu/Neraium-Poly/data/experimental-paper')
connection=sqlite3.connect(f'file:{root}/research-projection.sqlite?mode=ro',uri=True)
connection.execute('PRAGMA query_only=ON')
entries=[json.loads(v[0]) for v in connection.execute('SELECT payload FROM entries')]
connection.close()
with ReadonlyArchive(root,max_payload_bytes=32*1024**2) as archive:
    def load(identity):
        row=archive.get(identity)
        if row is None:raise ValueError('original source missing')
        return json.loads(row[1])
    result=audit_crypto_finance(entries,source_loader=load,as_of=datetime.now(UTC))
Path('.planning/evidence/phase32-crypto/readiness.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ['as_of','forecasts','categories','maturity','source_contract_quarantined','event_groups_with_verified_outcomes','source_groups_read']}))
