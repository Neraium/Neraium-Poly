"""Reproduce retained comparisons from the immutable recorded cycle, not latest."""
import hashlib,json,math
from collections import defaultdict
from pathlib import Path

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.checkpoints import unpack_checkpoint
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase44.metrics import scores

expected=json.loads(Path(__file__).with_name('comparisons.json').read_bytes())
store=ReadonlyArchive('/home/ubuntu/Neraium-Poly/data/experimental-paper');raw=store.get(expected['cycle_id']);assert raw and hashlib.sha256(raw[1].encode()).hexdigest()==raw[2]
cycle=json.loads(raw[1]);assert digest(cycle)==expected['cycle_sha256'];state=unpack_checkpoint(cycle['checkpoint']);assert digest(state)==cycle['state_sha256'];model_scores=scores(state['forecasts'],state['labels']);assert model_scores==expected['existing_model_and_market_scores']
groups=defaultdict(lambda:defaultdict(list))
for fid,label in state['labels'].items():
    f=state['forecasts'][fid]
    if label.get('native_payout_verified') and label['payout'] in (0,1):groups[f['model_id']][f['event_id']].append(label['payout'])
for model,values in groups.items():
    assert len(values)==model_scores[model]['native_parent_groups'] and sum(map(len,values.values()))==model_scores[model]['forecasts']
    for name,constant in (('zero',0),('one',1)):
        brier=sum(sum((constant-y)**2 for y in ys)/len(ys) for ys in values.values())/len(values)
        loss=sum(sum(-math.log(1e-12) if y!=constant else 0 for y in ys)/len(ys) for ys in values.values())/len(values)
        assert expected['trivial_baselines_equal_native_parent_weight'][model][name]=={'brier':brier,'log_loss_clipped':loss}
print('Exact archived cycle and matched model/market/zero/one comparisons verified; no outcome fitting.')
