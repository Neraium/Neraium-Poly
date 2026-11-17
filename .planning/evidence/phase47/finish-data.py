"""Bounded readonly preservation/proof/economic comparison after observation."""
import hashlib,json,statistics
from pathlib import Path

from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase44.native import replay
from neraium_poly.research.phase47.storage import read

HERE=Path(__file__).resolve().parent
before=json.loads((HERE/'preservation-baseline.json').read_bytes());root=Path(before['root'])
for name,old in before['files'].items():
    p=root/name;assert p.is_file() and p.stat().st_size==old['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==old['sha256'],f'original changed: {name}'
store=ReadonlyArchive(root.parent);proofs=[]
for r in store.latest('NativePayout44',64):
    if not r['verified'] or str(Path(r['directory'])/'proof.json.gz') in before['files']:continue
    path=root/r['directory']
    if not (path/'proof.json.gz').exists():continue
    verified=replay(path);assert verified==r['proof']
    files=[p for p in path.rglob('*') if p.is_file()]
    original=json.loads(read(path/'bundle.json'))['forecast']
    proofs.append({'forecast_identity':{k:original.get(k) for k in ('id','timestamp','domain','model_id','market_id','event_id','token_id','probability','market_probability')},'question':original['market']['question'],'attempt_id':r['id'],'directory':r['directory'],'proof':verified,'physical_bytes':sum(p.stat().st_size for p in files),'decoded_bytes':sum(len(read(p.with_suffix(''))) if p.suffix=='.gz' else p.stat().st_size for p in files)})

def observation(path, startup=False):
    rows=[json.loads(s) for s in path.read_text().splitlines()] if path.exists() else json.loads((path.parent/'compact-samples.json').read_text())
    if startup:
        start=next(r['elapsed'] for r in rows if r.get('health',{}).get('status')=='ok' and r.get('research',{}).get('reference_feed'));rows=[r for r in rows if r['elapsed']>=start]
    # Warm predeployment includes ALL failed/slow samples, with no health-based
    # exclusion. Actual post-restart recovery is reported separately.

    cycles={r['research']['as_of']:r['research']['shadow_worker']['cycle_seconds'] for r in rows if r.get('research',{}).get('shadow_worker')};ts=list(cycles.values())
    return {'samples':len(rows),'seconds':rows[-1]['elapsed']-rows[0]['elapsed'],'fresh':sum(r.get('research',{}).get('status')=='fresh' for r in rows),'unique_cycles':len(ts),'median_cycle':statistics.median(ts),'max_cycle':max(ts),'fee_verified_peak':max(r.get('research',{}).get('current_fee_coverage',{}).get('verified_tokens',0) for r in rows),'peak_memory_bytes':max(int(r['service']['MemoryCurrent']) for r in rows),'restarts':rows[-1]['service']['NRestarts'],'oom_kills':rows[-1]['memory_events']['oom_kill']}
post=json.loads((HERE/'activation/postflight.json').read_bytes());report=post['report'];old=json.loads((HERE/'result.json').read_bytes())['final']['research'];current=report['phase45_explorer'];prior=old['phase45_explorer'];deltas={}
for profile,s in current['profiles'].items():
    deltas[profile]={key:sum(v[key]-prior['profiles'][profile]['strategies'][name][key] for name,v in s['strategies'].items()) for key in ('orders','fill_events','modeled_exit_net_pnl','verified_settlement_net_pnl')}
summary={'source':post['source'],'pid':post['pid'],'preserved_original_files':len(before['files']),'new_verified_proofs':proofs,'native_bytes_now':sum(p.stat().st_size for p in root.rglob('*') if p.is_file()),'native_cap_bytes':64*1024**2,'before':observation(HERE/'samples.jsonl'),'after':observation(HERE/'activation/observation/samples.jsonl',startup=True),'frozen14':report['phase47_cohort'],'outcome_program':report['outcome_program'],'native_inventory':report['native_outcome_inventory'],'event_group_scores':report['event_group_scores'],'native_reconciliation':report['native_reconciliation'],'fee_coverage':report['current_fee_coverage'],'positions':report['positions'],'strategy_deltas':deltas,'current_strategies':current['profiles'],'loss_attribution':current['loss_attribution']['by_strategy'],'legacy_profiles':report['profiles'],'economic_candidates':current['economic_candidates'],'accounts':post['postflight']['accounts'],'storage':post['archive']['archive'],'reference_unchanged':post['postflight']['services']['neraium-poly-paper.service']['MainPID']=='555731','stop_latched':post['postflight']['accounts']['experimental-paper']['risk.sqlite']['account']['kill']==1,'limitation':'official metadata, verified native results, modeled exits, unfilled intents and conditional EV remain distinct; no certified independent groups or superiority asserted'}
assert summary['native_bytes_now']<=summary['native_cap_bytes'];(HERE/'closing.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({k:summary[k] for k in ('source','pid','preserved_original_files','native_bytes_now','before','after','strategy_deltas')}));print('new_native_proofs',len(proofs))
