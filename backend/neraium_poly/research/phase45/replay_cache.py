"""Bounded process-local memoization of byte-identical deterministic model replay.

Current causal binding is still checked outside this cache on every inventory
pass. Only successful full replays are memoized. Restart always revalidates.
No source data, model objects, outcome proofs or risk approvals are retained.
"""
from collections import OrderedDict

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24.continuous import at


class ReplayCache:
    def __init__(self):
        self.keys=OrderedDict();self.hits=0;self.verified=0
    def verify(self,item,models,*,now,replay,study_sha256):
        f=item['forecast'];key=(study_sha256,digest(f),f.get('model_sha256'))
        prior=self.keys.get(key)
        if prior is not None and at(now)>=at(prior):
            self.hits+=1;self.keys.move_to_end(key);return
        replay(item['study'],f,models,now=now)
        self.verified+=1;self.keys[key]=at(now).isoformat();self.keys.move_to_end(key)
        while len(self.keys)>512:self.keys.popitem(last=False)
    def status(self):
        return {'successful_full_replays':self.verified,'identical_input_hits':self.hits,'entries':len(self.keys),'maximum_entries':512,
            'causal_binding_checked_each_inventory_pass':True,'persistent_trust':False,'outcome_proofs_cached':False}
