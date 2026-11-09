"""RO replay of existing official-labelled original forecasts; no writes to production."""
import json
from datetime import UTC, datetime
from pathlib import Path

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase24.operations import original
from neraium_poly.research.phase26.reporting import callbacks
from neraium_poly.research.phase35.validation import audit_market_baselines

source=Path('/home/ubuntu/Neraium-Poly/data/experimental-paper')
store=ReadonlyArchive(source)
labels=store.latest('OfficialEventLabelStudy',64)

def records():
    for label in labels:
        study=original(store,label['original_study_id'])
        if digest(study)!=label['original_study_sha256']:raise ValueError('original study hash')
        forecast=next(f for f in study['forecasts'] if f['id']==label['forecast_id'])
        if digest(forecast)!=label['original_forecast_sha256']:raise ValueError('original forecast hash')
        yield {'study':study,'forecast':forecast}

report=audit_market_baselines(records(),as_of=datetime.now(UTC),forecast_verifier=callbacks(store,source)[0])
print(json.dumps(report,indent=2,sort_keys=True))
