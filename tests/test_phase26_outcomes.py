"""Controlled NHL protocol fixtures only; never genuine resolved forecasts."""
import json
from datetime import timedelta

import httpx
import pytest
from neraium_poly.research.phase12.contracts import VerifiedEventOutcome
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25 import sports
from neraium_poly.research.phase26 import outcomes
from test_phase25_sports_weather import NOW, START, book, evidence, market

ASOF=NOW+timedelta(hours=9)


def fixtures():
 m=market(outcome="Maple Leafs");e=evidence();b=book();f=sports._predict(m.model_dump(mode='json'),e,cutoff=NOW)[0]
 f.update(id='controlled-forecast',timestamp=NOW.isoformat(),market=m.model_dump(mode='json'),book=b.model_dump(mode='json'),book_id=b.id,
          book_sha256=digest(b.model_dump(mode='json')),market_expected_payout=(b.bids[0].price+b.asks[0].price)/2)
 study={'id':'controlled-original','timestamp':NOW.isoformat(),'available_at':(NOW+timedelta(seconds=1)).isoformat(),
        'forecasts':[f],'evidence':[e.model_dump(mode='json')]}
 row={'id':2026020268,'easternStartTime':'2026-11-07T19:30:00','gameDate':'2026-11-07','gameNumber':268,'gameScheduleStateId':1,
      'gameStateId':7,'gameType':2,'homeScore':4,'homeTeamId':10,'period':3,'season':20262027,'visitingScore':3,'visitingTeamId':8}
 games={'data':[row],'total':1};teams={'data':[{'id':10,'fullName':'Toronto Maple Leafs','leagueId':133},{'id':8,'fullName':'Montréal Canadiens','leagueId':133}]}
 html=b'''<html><table id="Visitor"><tr><td>VISITOR</td><td>3</td><img alt="MONTREAL CANADIENS"><td>MONTREAL CANADIENS</td></tr></table><table id="GameInfo"><td>Game Summary</td><td>Saturday, November 7, 2026</td><td>Start 7:38 EST; End 10:12 EST</td><td>Game 0268</td><td>Final</td></table><table id="Home"><td>HOME</td><td>4</td><img alt="TORONTO MAPLE LEAFS"><td>TORONTO MAPLE LEAFS</td></table></html>'''
 return m,f,study,games,teams,html


def native(f,*,payout=1,settled=None):
 return VerifiedEventOutcome(id='controlled-native',timestamp=settled or ASOF-timedelta(hours=1),available_at=ASOF,
    source='controlled-native-proof',event_id=f['event_id'],market_id=f['market_id'],token_id=f['token_id'],payout=payout,
    resolution_rules_sha256=f['rules_sha256'],settled_at=settled or ASOF-timedelta(hours=1),verification_source='CONTROLLED',proof_sha256='0'*64,verification={})


def test_exact_official_final_report_binds_score_and_minute_bounds():
 _m,f,_s,g,t,h=fixtures();r=outcomes.parse_official_nhl(json.dumps(g).encode(),json.dumps(t).encode(),h,f['contract']['parameters'],START,available_at=ASOF)
 assert r['status']=='final' and r['expected_payout']==1
 assert r['actual_start_lower']=='2026-11-08T00:38:00+00:00'
 assert r['end_lower']=='2026-11-08T03:12:00+00:00' and r['end_upper']=='2026-11-08T03:13:00+00:00'


@pytest.mark.parametrize('fault',['wrong_start','wrong_season','duplicate_game','live','rescheduled','tie','bad_team','bad_report_score','not_final','correction','wrong_report_game','unknown_zone','future_end'])
def test_unsupported_official_inputs_do_not_create_binary_labels(fault):
 _m,f,_s,g,t,h=fixtures();row=g['data'][0]
 if fault=='wrong_start':row['easternStartTime']='2026-11-07T20:00:00'
 elif fault=='wrong_season':row['season']=20252026
 elif fault=='duplicate_game':g['data']*=2
 elif fault=='live':row['gameStateId']=3
 elif fault=='rescheduled':row['gameScheduleStateId']=2
 elif fault=='tie':row['homeScore']=3
 elif fault=='bad_team':t['data'][0]['fullName']='Unrelated Team'
 elif fault=='bad_report_score':h=h.replace(b'<td>4</td>',b'<td>5</td>')
 elif fault=='not_final':h=h.replace(b'>Final<',b'>In Progress<')
 elif fault=='correction':h+=b'CORRECTED'
 elif fault=='wrong_report_game':h=h.replace(b'Game 0268',b'Game 0269')
 elif fault=='unknown_zone':h=h.replace(b'EST',b'UNKNOWN')
 elif fault=='future_end':h=h.replace(b'End 10:12',b'End 2:12')
 if fault=='live':
  assert outcomes.parse_official_nhl(json.dumps(g).encode(),json.dumps(t).encode(),h,f['contract']['parameters'],START,available_at=ASOF)['status']=='pending'
 else:
  with pytest.raises((ValueError,KeyError)):outcomes.parse_official_nhl(json.dumps(g).encode(),json.dumps(t).encode(),h,f['contract']['parameters'],START,available_at=ASOF)


def install(monkeypatch,games,teams,html,*,final_proof=True,payout=1,settled=None):
 outcomes._CACHE.clear();calls=[];original=httpx.AsyncClient
 def handler(request):
  calls.append(str(request.url))
  if request.url.path.endswith('/game'):return httpx.Response(200,json=games)
  if request.url.path.endswith('/team'):return httpx.Response(200,json=teams)
  if request.url.path.endswith('GS020268.HTM'):return httpx.Response(200,content=html)
  raise AssertionError('unexpected source URL')
 monkeypatch.setattr(outcomes.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
 async def acquire(ref,m,location,**kw):
  calls.append('controlled-native-acquire')
  return native(fixtures()[1],payout=payout,settled=settled) if final_proof else None
 monkeypatch.setattr(outcomes,'acquire_verified_outcome',acquire)
 monkeypatch.setattr(outcomes,'verify_collected_outcome',lambda *a:True)
 return calls


async def test_full_candidate_requires_original_model_native_and_replay(monkeypatch,tmp_path):
 _m,f,s,g,t,h=fixtures();calls=install(monkeypatch,g,t,h)
 r=await outcomes.verify_sport_outcome(f,directory=tmp_path,clock=lambda:ASOF)
 assert r['verified'] and r['verification_protocol']==outcomes.PROTOCOL and 'controlled-native-acquire' in calls
 proof=outcomes.replay_sport_outcome(r,s,f,evidence_root=tmp_path,as_of=ASOF)
 assert proof['verified'] and proof['outcome']==1 and proof['brier']==pytest.approx((f['probability']-1)**2)
 assert proof['market_brier'] is None and not proof['trading_authority']


async def test_official_final_without_native_finality_stays_pending(monkeypatch,tmp_path):
 _m,f,_s,g,t,h=fixtures();install(monkeypatch,g,t,h,final_proof=False)
 r=await outcomes.verify_sport_outcome(f,directory=tmp_path,clock=lambda:ASOF)
 assert not r['verified'] and r['status']=='pending' and r['reason']=='native_finalized_settlement_proof_unavailable'


@pytest.mark.parametrize('fault',['flag_only','foreign_study','mutated_probability','changed_source_url','corrupt_raw','path_escape','native_unverified','premature_native'])
async def test_outcome_replay_fails_closed_on_binding_or_integrity_error(monkeypatch,tmp_path,fault):
 _m,f,s,g,t,h=fixtures();install(monkeypatch,g,t,h)
 r=await outcomes.verify_sport_outcome(f,directory=tmp_path,clock=lambda:ASOF);assert r['verified']
 if fault=='flag_only':r={'verified':True}
 elif fault=='foreign_study':s={**s,'forecasts':[]}
 elif fault=='mutated_probability':f={**f,'probability':.999};s={**s,'forecasts':[f]}
 elif fault=='changed_source_url':r['official_evidence'][0]['source_url']='https://example.com/'
 elif fault=='corrupt_raw':(tmp_path/r['native_root']/r['official_evidence'][0]['raw_file']).write_bytes(b'corrupted controlled source')
 elif fault=='path_escape':r['official_evidence'][0]['raw_file']='../outside'
 elif fault=='native_unverified':monkeypatch.setattr(outcomes,'verify_collected_outcome',lambda *a:False)
 elif fault=='premature_native':r['native_outcome']=native(f,settled=START+timedelta(hours=1)).model_dump(mode='json');r['resolved_at']=r['native_outcome']['settled_at']
 with pytest.raises((ValueError,KeyError,StopIteration)):
  outcomes.replay_sport_outcome(r,s,f,evidence_root=tmp_path,as_of=ASOF)


async def test_pending_official_game_does_not_query_report_or_native(monkeypatch,tmp_path):
 _m,f,_s,g,t,h=fixtures();g['data'][0]['gameStateId']=3;calls=install(monkeypatch,g,t,h)
 r=await outcomes.verify_sport_outcome(f,directory=tmp_path,clock=lambda:ASOF)
 assert not r['verified'] and r['status']=='pending' and len(calls)==2


async def test_duplicate_checks_reuse_bounded_official_source_receipts(monkeypatch,tmp_path):
 _m,f,_s,g,t,h=fixtures();calls=install(monkeypatch,g,t,h,final_proof=False)
 await outcomes.verify_sport_outcome(f,directory=tmp_path,clock=lambda:ASOF)
 await outcomes.verify_sport_outcome(f,directory=tmp_path,clock=lambda:ASOF)
 assert sum(x!='controlled-native-acquire' for x in calls)==3 and len(outcomes._CACHE)<=16


async def test_nba_and_future_forecasts_are_withheld_without_provider_bypass(tmp_path):
 _m,f,_s,_g,_t,_h=fixtures()
 r=await outcomes.verify_sport_outcome({**f,'league':'NBA'},directory=tmp_path,clock=lambda:ASOF)
 assert not r['verified'] and 'NBA_source_access_unavailable' in r['reason']
 r=await outcomes.verify_sport_outcome(f,directory=tmp_path,clock=lambda:NOW)
 assert r['status']=='pending'
