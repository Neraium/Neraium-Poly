"""Descriptive event-group scoring; no fitted calibration or model promotion."""
import math
from collections import defaultdict

from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase24.continuous import at


def scores(forecasts,labels):
    by_model=defaultdict(list)
    def market_baseline(f):
        book=f.get('book',{})
        try:
            if book['token_id']!=f['token_id'] or book['market_id']!=f['market_id'] or book['source'] not in PUBLIC_BOOK_SOURCES or not 0<=(at(f['timestamp'])-at(book['available_at'])).total_seconds()<=15 or not at(book['timestamp'])<=at(book['available_at']):return None
            midpoint=(book['bids'][0]['price']+book['asks'][0]['price'])/2
            recorded=f.get('market_probability') if f.get('market_probability') is not None else f.get('market_expected_payout')
            if type(recorded) not in (int,float) or abs(recorded-midpoint)>1e-10:return None
            return midpoint
        except (KeyError,TypeError,ValueError,IndexError):return None
    for fid,label in labels.items():
        f=forecasts[fid];p=f.get('probability');m=market_baseline(f);y=label.get('payout')
        if y not in (0,1) or type(p) not in (int,float) or type(m) not in (int,float) or not 0<=p<=1 or not 0<=m<=1:continue
        by_model[f['model_id']].append((f['event_id'],p,m,y))
    out={}
    for name,rows in by_model.items():
        groups=defaultdict(list)
        for event,p,m,y in rows:groups[event].append((p,m,y))
        metrics={}
        for key,index in (('model',0),('market',1),('neutral',None)):
            bs=[];logs=[]
            for values in groups.values():
                ps=[.5 if index is None else v[index] for v in values];ys=[v[2] for v in values]
                bs.append(sum((p-y)**2 for p,y in zip(ps,ys,strict=True))/len(ps))
                logs.append(-sum(y*math.log(max(1e-12,p))+(1-y)*math.log(max(1e-12,1-p)) for p,y in zip(ps,ys,strict=True))/len(ps))
            metrics[key]={'brier':sum(bs)/len(bs),'log_loss':sum(logs)/len(logs)}
        out[name]={'forecasts':len(rows),'native_parent_groups':len(groups),'reviewed_independent_groups':0,
            'scores':metrics,'model_minus_market_brier':metrics['model']['brier']-metrics['market']['brier'],
            'market_baseline':'original causal executable-book midpoint / token expected payout; not an independent model probability','confidence_interval':None,'calibration_fit':None,'status':'descriptive_only; independent cohort review and sufficient heldout groups required'}
    return out
