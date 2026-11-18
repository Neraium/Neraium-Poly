"""Predeclare the prospective cutoff and hash the unmodified strategies."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE='8d9756ff8a514ad87947646ffc330f0c3e10efc8'
paths=['config/experimental-paper.example.json']
for item in ('phase16/short_horizon.py','phase41/simulation.py','phase42/engine.py','phase42/strategies.py',
             'phase42/controller.py','phase42/sources.py','phase43/economics.py','phase43/tournament.py',
             'phase43/baseline.json','phase44/cohort.py','phase45/cohort.py','phase45/economics.py',
             'phase45/native_positions.py','phase45/complements.py','phase29/costs.py'):
    paths.append('backend/neraium_poly/research/'+item)

spec={
    'source':SOURCE,
    'start':'2026-11-18T05:00:00+00:00',
    'end':'2026-11-19T05:00:00+00:00',
    'metric':'native-settled and modeled executable-exit net dollars, separately reported, against no trade $0; mark and open principal separate',
    'scope':'Phase45 Explorer untouched; Phase42 and Phase44 historical frozen lineages only; Phase16 monetary mark challenger not an entry/exit strategy',
    'selection':'no selection or fitting on this window; all eligible capture times and all hypotheses reported; observed event concentration reported, no superiority inference across strategies without independent groups and multiplicity control',
    'execution':'existing Explorer logic including 0.5 seconds latency, later authentic books, bounded depth and participation, fees/slippage, original exit and risk rules; assumed fees never validate positive net edge; report verified fees and modeled execution separately',
    'unseen':'chronological only, starts after freeze; cross-event independence or unseen market identity is a separate requirement; quarantine overlapping groups when evidenced, do not promote based on unresolved overlap',
    'data':'original point-in-time frames, receipts, verified fee evidence and models where available; no future joins or filling gaps with reconstructed producer health',
    'settlement':'do not force a close at endpoint; missing native payouts stay open',
    'file_sha256':{path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in paths},
}
with (HERE/'prospective-lock.json').open('x') as stream:
    json.dump(spec,stream,indent=2)
    stream.write('\n')
