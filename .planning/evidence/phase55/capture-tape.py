"""Record the predeclared 05:00–05:15 UTC forward input block, without account access."""
import argparse
import gzip
import json
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase42.sources import read_reference

HERE=Path(__file__).resolve().parent
START=datetime.fromisoformat(json.loads((HERE/'prospective-lock.json').read_text())['start'])
STOP=START+timedelta(minutes=15)
STUDIES=('DomainResearchStudy','ChallengerStudy','RefreshDomainStudy','RefreshCryptoStudy')

def now():
    return datetime.now(UTC)

def run(path, archive):
    if path.resolve().is_relative_to(Path('/home/ubuntu/Neraium-Poly/data')):
        raise ValueError('private output required')
    if not START<=now()<STOP:
        raise ValueError(f'capture only during the predeclared window {START} to {STOP}')
    with gzip.open(path,'xt') as output:
        while now()<STOP-timedelta(seconds=5):
            if shutil.disk_usage(path.parent).free <= 101*1024**3 or path.stat().st_size>=512*1024**2:
                raise ValueError('capture reserve or size limit reached')
            began=time.monotonic()
            try:
                frame=read_reference('http://127.0.0.1:18742/api/market-frame')
                received=now()
            except (ValueError,OSError,httpx.HTTPError) as error:
                row={'received_at':now().isoformat(),'error':type(error).__name__}
            else:
                causal=received.isoformat()
                raw=frame.model_dump(mode='json')
                ids=[]
                for kind in STUDIES:
                    ids.extend(r['id'] for r in archive._catalog_rows(
                        'SELECT id FROM records WHERE kind=? AND available_at<=? ORDER BY available_at DESC,id DESC LIMIT 16',
                        (kind,causal)))
                fees={}
                for item in archive._catalog_rows(
                    'SELECT * FROM records WHERE kind=? AND available_at>=? AND available_at<=? '
                    'ORDER BY available_at DESC,id DESC LIMIT 128',
                    ('FeeObservation',(received-timedelta(seconds=300)).isoformat(),causal)):
                    fee=json.loads(archive._fetch(item)[1])
                    fees.setdefault(fee['token_id'],item['id'])
                row={'received_at':causal,'frame':raw,'sha256':digest(raw),'source_study_ids':ids,'fee_observation_ids':fees}
            output.write(json.dumps(row,separators=(',',':'))+'\n')
            output.flush()
            time.sleep(max(0.,5-(time.monotonic()-began)))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tape',type=Path)
    parser.add_argument('archive',type=Path)
    args=parser.parse_args()
    run(args.tape,ReadonlyArchive(args.archive))
