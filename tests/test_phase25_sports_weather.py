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
from neraium_poly.research.phase25 import sports

NOW=datetime(2026,11,7,22,tzinfo=UTC)
START=datetime(2026,11,8,0,30,tzinfo=UTC)


def market(**changes):
    local=START.astimezone(ZoneInfo('America/New_York'))
    rules=(f'In the upcoming NHL game, scheduled for {local.strftime("%B %-d at %-I:%M%p")} ET:\n'
        'If the Maple Leafs win, the market will resolve to "Maple Leafs".\nIf the Canadiens win, the market will resolve to "Canadiens".\n'
        'If the game is postponed, this market will remain open until the game has been completed.\n'
        'If the game is canceled entirely, with no make-up game, this market will resolve 50-50.\n'
        "The result will be determined based on the final score including any overtime periods and shootouts. In the event of a shootout, one goal will be added to the winning team's score for the purpose of resolution.")
    raw={'id':'controlled-m','timestamp':NOW,'available_at':NOW,'source':'https://gamma-api.polymarket.com',
        'market_id':'controlled-market','event_id':'controlled-parent','token_id':'controlled-token','question':'Maple Leafs vs. Canadiens',
        'outcome':'Canadiens','probability':.5,'status':'active','resolution_source':'https://www.nhl.com/scores','resolution_rules':rules,'end_time':START}
    raw.update(changes);return MarketSnapshot(**raw)


def book():
    m=market();return OrderBookSnapshot(id='controlled-book',timestamp=NOW,available_at=NOW,source='https://clob.polymarket.com',
        market_id=m.market_id,token_id=m.token_id,bids=(PriceLevel(price=.49,size=200),),asks=(PriceLevel(price=.5,size=200),))


def event(identity,start,home,away,*,final=True,home_win=True):
    names=sorted(sports.TEAMS);h=names.index(home)+1;a=names.index(away)+1
    return {'id':identity,'date':start.isoformat(),'season':{'type':2},'status':{'type':{'completed':final,'name':'STATUS_FINAL' if final else 'STATUS_SCHEDULED','state':'post' if final else 'pre'}},
        'competitions':[{'competitors':[{'homeAway':'home','score':'4' if home_win else '2','winner':home_win if final else False,'team':{'id':str(h),'name':home}},
        {'homeAway':'away','score':'2' if home_win else '4','winner':not home_win if final else False,'team':{'id':str(a),'name':away}}]}]}


def evidence(*,future=False,wrong_schedule=False,short=False):
    names=sorted(sports.TEAMS);responses=[]
    for d in range(25 if not short else 2):
        day=NOW-timedelta(days=25-d);events=[]
        for j in range(4):
            i=d*4+j;home=names[(i*2)%32];away=names[(i*2+1)%32]
            events.append(event(f'controlled-{i}',day-timedelta(hours=j),home,away,home_win=i%3!=0))
        raw=json.dumps({'leagues':[{'id':'90','slug':'nhl'}],'events':events})
        responses.append({'url':sports.ORIGIN+sports.PATH+'?dates='+day.strftime('%Y%m%d'),'requested_at':NOW.isoformat(),'retrieved_at':NOW.isoformat(),
            'raw_utf8':raw,'raw_sha256':hashlib.sha256(raw.encode()).hexdigest()})
    raw=json.dumps({'leagues':[{'id':'90','slug':'nhl'}],'events':[event('controlled-target',START+timedelta(hours=1) if wrong_schedule else START,'Canadiens','Maple Leafs',final=False)]})
    responses.append({'url':sports.ORIGIN+sports.PATH+'?dates=20261107','requested_at':NOW.isoformat(),'retrieved_at':NOW.isoformat(),'raw_utf8':raw,'raw_sha256':hashlib.sha256(raw.encode()).hexdigest()})
    p={'responses':responses};at=NOW+timedelta(seconds=1) if future else NOW
    return DomainEvidence(id='controlled-evidence',timestamp=at,available_at=at,retrieved_at=at,source=sports.ORIGIN+sports.PATH,
        domain='sports',provider='ESPN public NHL scoreboard',source_id='controlled',content_sha256=digest(p),payload=p,
        independent_of_polymarket=True,qualification='qualified_research')


def test_exact_NHL_rules_time_side_and_reference():
    assert sports.supports(market(),cutoff=NOW)['supported']
    for m in [market(resolution_rules=market().resolution_rules+' other'),market(resolution_source='https://www.espn.com/'),market(outcome='Oilers'),market(end_time=START+timedelta(hours=1))]:
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




def variable_weather_evidence():
    # Controlled fixture: vary remaining afternoon rise instead of pretending a
    # constant-diurnal fixture identifies a nonzero residual distribution.
    import re

    from test_phase24_weather_economics import weather_evidence
    values=[]
    for e in weather_evidence():
        p=deepcopy(e.payload);rows=json.loads(p['raw_response_utf8'])
        for row in rows:
            t=datetime.fromtimestamp(row['obsTime'],UTC).astimezone(ZoneInfo('Asia/Shanghai'))
            if 12<=t.hour<=16:
                row['rawOb']=re.sub(r'(\d{2})/10',lambda m,day=t.day:f"{int(m[1])+day%3:02d}/10",row['rawOb'])
        raw=json.dumps(rows);p.update(raw_response_utf8=raw,raw_response_sha256=hashlib.sha256(raw.encode()).hexdigest())
        values.append(e.model_copy(update={'payload':p,'content_sha256':digest(p)}))
    return tuple(values)

def test_chengdu_station_is_exactly_added_not_station_substitution():
    from neraium_poly.research.phase25 import weather
    from test_phase24_weather_economics import market as weather_market
    m=weather_market();rules=m.resolution_rules.replace('Chongqing Jiangbei','Chengdu Shuangliu').replace('ZUCK','ZUUU')
    m=m.model_copy(update={'question':m.question.replace('Chongqing','Chengdu'),'resolution_source':m.resolution_source.replace('ZUCK','ZUUU'),'resolution_rules':rules})
    support=weather.supports(m,cutoff=m.available_at)
    assert support['supported'] and support['contract']['station']=='ZUUU'
    assert not weather.supports(m.model_copy(update={'resolution_source':m.resolution_source.replace('ZUUU','ZUCK')}),cutoff=m.available_at)['supported']


def test_weather_models_replay_actual_features_without_market_price_dependence():
    from neraium_poly.research.phase25 import weather
    from test_phase24_weather_economics import NOW as WEATHER_NOW
    from test_phase24_weather_economics import market as weather_market
    m=weather_market();contract=weather.supports(m,cutoff=WEATHER_NOW)['contract'];e=variable_weather_evidence()
    a=weather.estimate(contract,e,cutoff=WEATHER_NOW)
    m=m.model_copy(update={'probability':.05});c=weather.supports(m,cutoff=WEATHER_NOW)['contract'];b=weather.estimate(c,e,cutoff=WEATHER_NOW)
    assert len(a)==2 and [x['probability'] for x in a]==[x['probability'] for x in b]
    assert all(x['effective_analog_sample_size']>=5 and x['lower_probability']==0 and not x['trading_authority'] for x in a)


async def test_weather_prospective_replay_and_tampered_probability(monkeypatch):
    from neraium_poly.research.phase25 import weather
    from test_phase24_weather_economics import NOW as WEATHER_NOW
    from test_phase24_weather_economics import book as weather_book
    from test_phase24_weather_economics import market as weather_market
    async def collect(*a,**kw):return variable_weather_evidence()
    monkeypatch.setattr(weather.base,'collect',collect)
    m=weather_market();result=await weather.forecast(m,weather_book(m),clock=lambda:WEATHER_NOW)
    assert len(result['forecasts'])==2
    for f in result['forecasts']:
        assert weather.replay(f,result['evidence'],as_of=WEATHER_NOW)['verified']
        bad=deepcopy(f);bad['probability']=.123456
        with pytest.raises(ValueError):weather.replay(bad,result['evidence'],as_of=WEATHER_NOW)


def test_weather_future_evidence_and_unobserved_gaussian_variation_fail_closed():
    from neraium_poly.research.phase25 import weather
    from test_phase24_weather_economics import NOW as WEATHER_NOW
    from test_phase24_weather_economics import market as weather_market
    m=weather_market();contract=weather.supports(m,cutoff=WEATHER_NOW)['contract'];e=list(variable_weather_evidence())
    e[0]=e[0].model_copy(update={'available_at':WEATHER_NOW+timedelta(seconds=1)})
    with pytest.raises(ValueError):weather.estimate(contract,e,cutoff=WEATHER_NOW)


def test_nhl_utah_alias_requires_exact_publisher_team_binding():
    e=evidence();payload=deepcopy(e.payload);row=payload['responses'][-1];doc=json.loads(row['raw_utf8'])
    side=doc['events'][0]['competitions'][0]['competitors'][0]
    side['team']={'id':'129764','name':'Mammoth','location':'Utah','abbreviation':'UTA'}
    raw=json.dumps(doc);row.update(raw_utf8=raw,raw_sha256=hashlib.sha256(raw.encode()).hexdigest())
    updated=e.model_copy(update={'payload':payload,'content_sha256':digest(payload)})
    _e,games=sports._parse(updated,NOW);assert next(g for g in games if g['id']=='controlled-target')['home']=='Utah'
    side['team']['id']='incorrect-team';raw=json.dumps(doc);row.update(raw_utf8=raw,raw_sha256=hashlib.sha256(raw.encode()).hexdigest())
    with pytest.raises(ValueError):sports._parse(e.model_copy(update={'payload':payload,'content_sha256':digest(payload)}),NOW)


def test_constant_diurnal_samples_do_not_manufacture_gaussian_uncertainty():
    from neraium_poly.research.phase25 import weather
    from test_phase24_weather_economics import NOW as WEATHER_NOW
    from test_phase24_weather_economics import market as weather_market
    from test_phase24_weather_economics import weather_evidence
    m=weather_market();contract=weather.supports(m,cutoff=WEATHER_NOW)['contract']
    with pytest.raises(ValueError,match='variation'):weather.estimate(contract,weather_evidence(),cutoff=WEATHER_NOW)


def test_weather_gaussian_respects_known_station_high_atom():
    from neraium_poly.research.phase25 import weather
    from test_phase24_weather_economics import NOW as WEATHER_NOW
    from test_phase24_weather_economics import market as weather_market
    m=weather_market(threshold=15);e=variable_weather_evidence();c=weather.supports(m,cutoff=WEATHER_NOW)['contract']
    result=weather.estimate(c,e,cutoff=WEATHER_NOW)[1]
    # Current controlled high is15C. The15C bin includes all clamped lower
    # Gaussian mass, never impossible probabilities below the observed high.
    import math
    mu=result['distribution_assumptions']['sample_mean'];sd=result['distribution_assumptions']['sample_sd']
    expected=.5*(1+math.erf((15.5-mu)/(sd*math.sqrt(2))))
    assert abs(result['probability']-expected)<1e-12
