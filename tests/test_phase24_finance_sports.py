"""Controlled source fixtures, never authentic games or market performance."""
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, PriceLevel
from neraium_poly.research.phase14.contracts import DomainEvidence
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24 import finance, sports

NOW=datetime(2026,11,7,22,tzinfo=UTC)
START=datetime(2026,11,8,0,30,tzinfo=UTC)


def market(**changes):
    local=START.astimezone(ZoneInfo('America/New_York'));deadline=(local+timedelta(days=2)).replace(hour=23,minute=59)
    rules=(f'In the upcoming NBA game between Nets and Hawks, originally scheduled for {local.strftime("%A, %B %-d, %Y")} at {local.strftime("%-I:%M %p")} ET (as of creation of the first market related to the event):\n'
        'If the Nets win, the market will resolve to "Nets".\nIf the Hawks win, the market will resolve to "Hawks".\n'
        f"If this market's outcome was definitively determined under its rules by the listed resolution sources before abandonment, that outcome will stand. Otherwise, the following no-result provisions apply. If the game is canceled, does not start by {deadline.strftime('%A, %B %-d, %Y')}, 11:59 PM ET, or is abandoned with no official result by that time, this market will resolve 50-50.\n"
        'The result will be determined based on the final score including any overtime periods.')
    raw={'id':'controlled-m','timestamp':NOW,'available_at':NOW,'source':'https://gamma-api.polymarket.com',
        'market_id':'controlled-market','event_id':'controlled-parent','token_id':'controlled-token','question':'Nets vs. Hawks',
        'outcome':'Hawks','probability':.5,'status':'active','resolution_source':'https://www.nba.com/','resolution_rules':rules,'end_time':START}
    raw.update(changes);return MarketSnapshot(**raw)


def book():
    m=market();return OrderBookSnapshot(id='controlled-book',timestamp=NOW,available_at=NOW,source='https://clob.polymarket.com',
        market_id=m.market_id,token_id=m.token_id,bids=(PriceLevel(price=.49,size=200),),asks=(PriceLevel(price=.5,size=200),))


def event(identity,start,home,away,*,final=True,home_win=True):
    names=sorted(sports.TEAMS);h=names.index(home)+1;a=names.index(away)+1
    return {'id':identity,'date':start.isoformat(),'season':{'type':2},'status':{'type':{'completed':final,'name':'STATUS_FINAL' if final else 'STATUS_SCHEDULED','state':'post' if final else 'pre'}},
        'competitions':[{'competitors':[{'homeAway':'home','score':'120' if home_win else '100','winner':home_win if final else False,'team':{'id':str(h),'name':home}},
        {'homeAway':'away','score':'100' if home_win else '120','winner':not home_win if final else False,'team':{'id':str(a),'name':away}}]}]}


def evidence(*,future=False,wrong_schedule=False,short=False):
    names=sorted(sports.TEAMS);responses=[]
    for d in range(25 if not short else 2):
        day=NOW-timedelta(days=25-d);events=[]
        for j in range(4):
            i=d*4+j;home=names[(i*2)%30];away=names[(i*2+1)%30]
            events.append(event(f'controlled-{i}',day-timedelta(hours=j),home,away,home_win=i%3!=0))
        raw=json.dumps({'leagues':[{'id':'46','slug':'nba'}],'events':events})
        responses.append({'url':sports.ORIGIN+sports.PATH+'?dates='+day.strftime('%Y%m%d'),'requested_at':NOW.isoformat(),'retrieved_at':NOW.isoformat(),
            'raw_utf8':raw,'raw_sha256':hashlib.sha256(raw.encode()).hexdigest()})
    raw=json.dumps({'leagues':[{'id':'46','slug':'nba'}],'events':[event('controlled-target',START+timedelta(hours=1) if wrong_schedule else START,'Hawks','Nets',final=False)]})
    responses.append({'url':sports.ORIGIN+sports.PATH+'?dates=20261107','requested_at':NOW.isoformat(),'retrieved_at':NOW.isoformat(),'raw_utf8':raw,'raw_sha256':hashlib.sha256(raw.encode()).hexdigest()})
    p={'responses':responses};at=NOW+timedelta(seconds=1) if future else NOW
    return DomainEvidence(id='controlled-evidence',timestamp=at,available_at=at,retrieved_at=at,source=sports.ORIGIN+sports.PATH,
        domain='sports',provider='ESPN public NBA scoreboard',source_id='controlled',content_sha256=digest(p),payload=p,
        independent_of_polymarket=True,qualification='qualified_research')


def test_exact_NBA_rules_time_side_and_reference():
    assert sports.supports(market(),cutoff=NOW)['supported']
    for m in [market(resolution_rules=market().resolution_rules+' other'),market(resolution_source='https://www.espn.com/'),market(outcome='Lakers'),market(end_time=START+timedelta(hours=1))]:
        assert not sports.supports(m,cutoff=NOW)['supported']
    assert not sports.supports(market(),cutoff=START)['supported']


def test_two_independent_from_market_models_reproduce_and_do_not_use_quote():
    a=sports._predict(market().model_dump(mode='json'),evidence(),cutoff=NOW)
    b=sports._predict(market(probability=.1).model_dump(mode='json'),evidence(),cutoff=NOW)
    assert len(a)==2 and a[0]['model_id']!=a[1]['model_id']
    assert all(x['training_observations']==100 and x['target_conditioning']=='official_completed_game' for x in a)
    assert [x['probability'] for x in a]==[x['probability'] for x in b]
    assert all(x['lower_probability']==0 and x['upper_probability']==1 and x['market_probability'] is None and not x['trading_authority'] for x in a)


@pytest.mark.parametrize('kind',['future','hash','schedule','short','tie','winner','duplicate'])
def test_source_leakage_corruption_and_identity_fail_closed(kind):
    e=evidence(future=kind=='future',wrong_schedule=kind=='schedule',short=kind=='short')
    if kind in {'hash','tie','winner','duplicate'}:
        p=deepcopy(e.payload);raw=p['responses'][0]['raw_utf8'];doc=json.loads(raw)
        if kind=='hash':p['responses'][0]['raw_utf8']=raw+' '
        else:
            c=doc['events'][0]['competitions'][0]['competitors']
            if kind=='tie':c[1]['score']=c[0]['score']
            if kind=='winner':c[0]['winner']=not c[0]['winner']
            if kind=='duplicate':doc['events'].append(deepcopy(doc['events'][0]));doc['events'][-1]['competitions'][0]['competitors'][0]['score']='333'
            raw=json.dumps(doc);p['responses'][0].update(raw_utf8=raw,raw_sha256=hashlib.sha256(raw.encode()).hexdigest())
        e=e.model_copy(update={'payload':p,'content_sha256':digest(p)})
    with pytest.raises(ValueError):sports._predict(market().model_dump(mode='json'),e,cutoff=NOW)


async def test_prospective_book_provenance_replay_and_cancellation_handling(monkeypatch,tmp_path):
    async def collect(**kw):return evidence()
    monkeypatch.setattr(sports,'collect_evidence',collect)
    result=await sports.forecast(market(),book(),clock=lambda:NOW)
    assert len(result['forecasts'])==2
    for f in result['forecasts']:
        assert sports.replay(f,result['evidence'],as_of=NOW)['verified']
        assert f['market_expected_payout']==.495 and f['market_probability'] is None
        mutated=deepcopy(f);mutated['probability']=1-mutated['probability']
        with pytest.raises(ValueError):sports.replay(mutated,result['evidence'],as_of=NOW)
        pending=await sports.verify_outcome(f,directory=tmp_path,clock=lambda:NOW)
        assert pending['status']=='pending' and pending['outcome'] is None


async def test_no_result_rule_not_silently_treated_as_binary_settlement(monkeypatch,tmp_path):
    async def collect(**kw):return evidence()
    monkeypatch.setattr(sports,'collect_evidence',collect)
    result=await sports.forecast(market(),book(),clock=lambda:NOW)
    f=result['forecasts'][0]
    assert 'Cancellation' in ' '.join(f['limitations'])
    assert f['contract']['parameters']['void_payout']==.5
    assert f['target_conditioning']=='official_completed_game'


def fred_evidence(*,future=False):
    rows=['observation_date,SP500']
    for i in range(260):
        day=NOW.date()-timedelta(days=260-i);rows.append(f'{day.isoformat()},{3000+i+(i%5)*2}')
    raw='\n'.join(rows)+'\n';p={'url':finance.URL,'series':'SP500','price_definition':'daily_cash_index_close',
        'requested_at':NOW.isoformat(),'retrieved_at':NOW.isoformat(),'raw_utf8':raw,'raw_sha256':hashlib.sha256(raw.encode()).hexdigest()}
    at=NOW+timedelta(seconds=1) if future else NOW
    return DomainEvidence(id='controlled-FRED',timestamp=at,available_at=at,retrieved_at=at,source=finance.URL,domain='finance',
        provider='Federal Reserve Bank of St. Louis FRED',source_id='SP500',content_sha256=digest(p),payload=p,independent_of_polymarket=True,qualification='qualified_research')


def test_financial_history_actual_availability_and_research_not_market_enrollment():
    e=fred_evidence();p=finance.terminal_research_probability(e,threshold=3300,business_days=1,cutoff=NOW)
    assert 0<=p['probability']<=1 and p['training_observations']==253 and not p['trading_authority']
    assert finance.definitions()==[]
    with pytest.raises(ValueError):finance.replay_history(fred_evidence(future=True),cutoff=NOW)
    m=market(question='WTI price?',resolution_source='https://app.pyth.com/explore?search=CLL')
    assert 'Pyth' in finance.supports(m,cutoff=NOW)['reasons'][0]
    m=market(question='Index close?',resolution_source='https://finance.yahoo.com/')
    assert 'not_a_settlement_substitute' in finance.supports(m,cutoff=NOW)['reasons'][0]


async def test_missing_shared_book_is_refreshed_from_native_source(monkeypatch):
    calls=[]
    async def collect(**kw):return evidence()
    class Adapter:
        def __init__(self,**kw):pass
        async def book(self,market_id,token_id):
            calls.append((market_id,token_id));return book()
        async def close(self):calls.append('closed')
    monkeypatch.setattr(sports,'collect_evidence',collect)
    monkeypatch.setattr(sports,'OperationalPolymarketAdapter',Adapter)
    result=await sports.forecast(market(),None,clock=lambda:NOW)
    assert len(result['forecasts'])==2 and calls==[('controlled-market','controlled-token'),'closed']
    assert all(f['book']['id']=='controlled-book' for f in result['forecasts'])


def test_fred_explicit_missing_closes_are_not_filled_or_invented():
    e=fred_evidence();p=deepcopy(e.payload);rows=p['raw_utf8'].splitlines();rows[20]=rows[20].split(',')[0]+','
    p['raw_utf8']='\n'.join(rows)+'\n';p['raw_sha256']=hashlib.sha256(p['raw_utf8'].encode()).hexdigest()
    e=e.model_copy(update={'payload':p,'content_sha256':digest(p)})
    result=finance.replay_history(e,cutoff=NOW)
    assert len(result)==259 and all(row['close']>0 for row in result)
