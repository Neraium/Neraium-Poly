"""One isolated live rehearsal. Originals are read-only; all new writes local."""
import json
import time
from threading import RLock
from datetime import UTC, datetime
from pathlib import Path

import httpx
from neraium_poly.data import EventStore
from neraium_poly.risk import RiskLimits
from neraium_poly.experimental.contracts import SharedMarketFrame
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase42.controller import Controller

HERE=Path(__file__).resolve().parent
class Overlay:
    def __init__(self):
        self.original=ReadonlyArchive('/home/ubuntu/Neraium-Poly/data/experimental-paper')
        self.local=EventStore(HERE/'rehearsal-final.sqlite')
        self.catalog=self.original._connection(self.original.catalog_path);self._lock=RLock()
    def get(self,key):return self.local.get(key) or self.original.get(key)
    def latest(self,kind,limit=100):
        values={r['id']:r for r in [*self.original.latest(kind,limit),*self.local.latest(kind,limit)]}
        return sorted(values.values(),key=lambda r:(r['available_at'],r['id']),reverse=True)[:limit]
    def append(self,row):
        if (HERE/'rehearsal-final.sqlite').stat().st_size>64*1024**2:raise ValueError('local rehearsal budget')
        return self.local.append(row)

store=Overlay();risk=json.loads(Path('config/experimental-paper.example.json').read_text())['risk_limits']
c=Controller(store,risk_limits=RiskLimits(**risk).model_dump(),clock=lambda:datetime.now(UTC),can_write=lambda:True,directory=HERE/'native')
before={n:{k:s[k] for k in ('cash','drawdown','suspended','closed')} for n,s in c.engine.state['profiles'].items()}
with httpx.Client(timeout=5,trust_env=False) as client:
    reports=[]
    for _ in range(2):
        for attempt in range(4):
            try:
                response=client.get('http://127.0.0.1:18742/api/market-frame');response.raise_for_status()
                frame=SharedMarketFrame.model_validate_json(response.content)
                if (datetime.now(UTC)-frame.available_at).total_seconds()>10:raise ValueError('stale reference frame')
                break
            except (httpx.HTTPError,ValueError):
                if attempt==3:raise
                time.sleep(2)
        if len(frame.model_dump_json().encode())>8*1024**2:raise ValueError('frame budget')
        from neraium_poly.research.phase29.costs import replay_fee
        fees={}
        for raw in store.original.latest('FeeObservation',128):
            token=raw['token_id']
            if token not in fees:
                proof=replay_fee({'evidence_id':raw['id']},store,token_id=token,as_of=datetime.now(UTC))
                if proof['status']=='verified_current_protocol_curve':fees[token]=proof
        reports.append(c.tick(frame,fees));time.sleep(2)
row=c.engine.last
assert row['checkpoint']['raw_bytes']<8*1024**2
assert c.engine.state['profiles']['aggressive']['suspended'] is True
for n,original in before.items():
    assert c.engine.state['profiles'][n]['cash']<=original['cash']+1e-8 or c.engine.state['profiles'][n]['closed']!=original['closed']
    assert c.engine.state['profiles'][n]['closed'][:len(original['closed'])]==original['closed']
result={'source':'actual loopback reference feed; isolated new decisions, never deployed paper fills',
        'initial':before,'checkpoint_raw_bytes_after':row['checkpoint']['raw_bytes'], 'report':reports[-1]}
(HERE/'rehearsal.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'cycles':reports[-1]['cycles'],'checkpoint_raw_bytes_after':row['checkpoint']['raw_bytes'],'forecasts':reports[-1]['forecasts'],'native_labels':reports[-1]['verified_outcomes'],'tournament':reports[-1]['exit_tournament']['matched_fill_counts']}))
