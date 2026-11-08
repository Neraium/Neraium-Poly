"""Controlled horizon/recovery fixtures, never authentic forecasts."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from neraium_poly.data import EventStore
from neraium_poly.research.phase27.payout import propose_spx
from test_phase24_integration import NOW


def environment():
    f={'id':'CONTROLLED-old','model_id':'spx-controlled','event_id':'CONTROLLED-parent','market_id':'CONTROLLED-market','token_id':'CONTROLLED-token','event_end_time':(NOW+timedelta(hours=2)).isoformat()}
    s={'id':'CONTROLLED-study','forecasts':[f]}
    frame={'markets':[{'token_id':f['token_id']}],'books':[{'token_id':f['token_id']}]}
    estimate={'id':'CONTROLLED-new','timestamp':NOW.isoformat(),'contract':{'period_start':(NOW+timedelta(hours=1)).isoformat()}}
    adapter=SimpleNamespace(BASELINE_MODEL='CONTROLLED-model',definitions=list,derive_spx_payout=lambda *a,**k:estimate,replay_spx_payout=lambda *a,**k:{'verified':True})
    return s,frame,adapter


def test_same_enrollment_parent_horizon_recovers_without_new_forecast(tmp_path):
    s,frame,adapter=environment();store=EventStore(tmp_path/'controlled.sqlite')
    try:
        args={'store':store,'enrollment_id':'CONTROLLED-enrollment','as_of':NOW,'verified_forecast_ids':{'CONTROLLED-old'},'adapter':adapter,'clock':lambda:NOW}
        rows,rejected=propose_spx([s],frame,**args);assert len(rows)==1 and not rejected
        again,_=propose_spx([s],frame,**{**args,'as_of':NOW+timedelta(seconds=30)})
        assert again==rows and store.count(kind='PayoutForecastStudy')==1
        adapter.replay_spx_payout=lambda *a,**k:{'verified':False}
        with pytest.raises(ValueError,match='recovered payout'):propose_spx([s],frame,**args)
    finally:store.close()


def test_compute_finishes_after_event_start_cannot_backdate_prediction(tmp_path):
    s,frame,adapter=environment();store=EventStore(tmp_path/'controlled.sqlite')
    try:
        rows,rejected=propose_spx([s],frame,store=store,enrollment_id='CONTROLLED',as_of=NOW,verified_forecast_ids={'CONTROLLED-old'},adapter=adapter,clock=lambda:NOW+timedelta(hours=1))
        assert not rows and 'payout_generation_not_available_before_event_start' in rejected
        assert store.count(kind='PayoutForecastStudy')==0
    finally:store.close()
