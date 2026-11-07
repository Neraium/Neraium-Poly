"""NHL research from exact contracts and public ESPN scoreboards.

The target is the winner of an officially completed game, including overtime/shootout.
Canceled/no-result contracts are preserved as void/unscored, never binary labels.
ESPN is a publisher, not the NHL's official resolution source. No commercial
redistribution rights or certified trading authority are implied.
"""

import asyncio
import hashlib
import json
import math
import re
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import httpx

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.data.operational import OperationalPolymarketAdapter
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.contracts import DomainContract, DomainEvidence
from neraium_poly.research.phase14.relationships import digest

ORIGIN='https://site.api.espn.com'
PATH='/apis/site/v2/sports/hockey/nhl/scoreboard'
MODELS=('nhl-causal-elo-v25.1','nhl-beta-frequency-v25.1')
FEATURE='nhl-final-results-home-away-v1'
TEAMS={'Ducks','Bruins','Sabres','Flames','Hurricanes','Blackhawks','Avalanche','Blue Jackets','Stars','Red Wings','Oilers','Panthers','Kings','Wild','Canadiens','Predators','Devils','Islanders','Rangers','Senators','Flyers','Penguins','Sharks','Kraken','Blues','Lightning','Maple Leafs','Utah','Canucks','Golden Knights','Capitals','Jets'}
_CACHE={}
_LOCK=None
_LOOP=None


def _at(value):
    value=value if isinstance(value,datetime) else datetime.fromisoformat(value)
    if value.tzinfo is None:raise ValueError('aware NHL cutoff required')
    return value.astimezone(UTC)


def definitions():
    sha=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return [{'model_id':m,'model_version':m,'model_sha256':digest([sha,m]),'feature_version':FEATURE,
        'domain':'sports','hypothesis':hypothesis,'input_requirements':['100 final NHL regular-season games','five results per participant','exact scheduled participants/time','raw ESPN bytes and actual retrieval times'],
        'performance_criteria':['completed-game conditional Brier/log loss','chronological event-disjoint comparison to frequency baseline','market baseline withheld without compatible completion conditioning'],
        'risk_assumptions':'Uncalibrated research, uncertainty[0,1], cancellation probability unmodeled; no execution',
        'source_independence':'Both models share ESPN results; not independent corroboration',
        'failure_conditions':['roster changes','injuries unmodeled','source corrections','postponement','cancellation or no official final'],
        'research_only':True,'trading_authority':False,'certification_authority':False}
        for m,hypothesis in zip(MODELS,['Chronologically updated team strengths and measured league home advantage','Beta(2,2) participant win posterior means with measured league home odds'])]


def supports(market,*,cutoff):
    try:
        now=_at(cutoff);m=MarketSnapshot.model_validate(market.model_dump() if hasattr(market,'model_dump') else market)
        if (m.exchange!='polymarket' or m.source!='https://gamma-api.polymarket.com' or m.status!='active'
            or m.available_at>now or m.timestamp>now or not m.end_time or not 300<(m.end_time-now).total_seconds()<=72*3600):
            raise ValueError('causal_upcoming_NHL_market_required')
        match=re.fullmatch(r'([^:()\n]+) vs\. ([^:()\n]+)',m.question)
        if not match or set(match.groups())-TEAMS or m.outcome not in match.groups() or match.group(1)==match.group(2):
            raise ValueError('exact_NHL_participants_and_outcome_required')
        if m.resolution_source.rstrip('/')!='https://www.nhl.com/scores':raise ValueError('official_NHL_resolution_reference_required')
        left,right=match.groups();local=m.end_time.astimezone(ZoneInfo('America/New_York'))
        expected=(f'In the upcoming NHL game, scheduled for {local.strftime("%B %-d at %-I:%M%p")} ET:\n'
            f'If the {left} win, the market will resolve to "{left}".\nIf the {right} win, the market will resolve to "{right}".\n'
            'If the game is postponed, this market will remain open until the game has been completed.\n'
            'If the game is canceled entirely, with no make-up game, this market will resolve 50-50.\n'
            'The result will be determined based on the final score including any overtime periods and shootouts. In the event of a shootout, one goal will be added to the winning team\'s score for the purpose of resolution.')
        if m.resolution_rules!=expected:raise ValueError('exact_NHL_overtime_no_result_rule_template_required')
        c=DomainContract(id=digest(['nhl-exact-v25',m.id,m.resolution_rules]),timestamp=now,available_at=now,
            source='neraium-poly/NHL-rule-mapping/v25',domain='sports',event_id=m.event_id,market_id=m.market_id,
            token_id=m.token_id,contract_type='nhl_official_completed_game_winner',probability_semantics='binary_event_probability',
            rules_sha256=hashlib.sha256(m.resolution_rules.encode()).hexdigest(),compatible=True,review_required=False,
            parameters={'participants':[left,right],'selected':m.outcome,'scheduled_start':m.end_time.isoformat(),
                'postponed_until_completed':True,'includes_overtime':True,'includes_shootout':True,'void_payout':.5,
                'target_conditioning':'official_completed_game','market_snapshot':m.model_dump(mode='json')})
        return {'supported':True,'reasons':[],'contract':c.model_dump(mode='json')}
    except (ValueError,TypeError,KeyError) as error:
        return {'supported':False,'reasons':[str(error)[:160]],'contract':None}


def _parse(evidence,cutoff):
    e=DomainEvidence.model_validate(evidence.model_dump() if hasattr(evidence,'model_dump') else evidence)
    cutoff=_at(cutoff)
    if (e.source!=ORIGIN+PATH or e.provider!='ESPN public NHL scoreboard' or e.domain!='sports' or e.qualification!='qualified_research'
        or not e.independent_of_polymarket or max(e.available_at,e.retrieved_at,e.timestamp)>cutoff
        or digest(e.payload)!=e.content_sha256 or not 1<=len(e.payload.get('responses',[]))<=32):
        raise ValueError('causal_raw_NHL_source_required')
    result={}
    for response in e.payload['responses']:
        u=urlsplit(response['url']);q=parse_qs(u.query)
        if u.scheme!='https' or u.netloc!='site.api.espn.com' or u.path!=PATH or set(q)!={'dates'} or not re.fullmatch(r'\d{8}',q['dates'][0]):
            raise ValueError('exact_ESPN_daily_source_identity_required')
        received=_at(response['retrieved_at']);requested=_at(response['requested_at']);raw=response['raw_utf8']
        if not requested<=received<=e.available_at or len(raw.encode())>2*1024**2 or hashlib.sha256(raw.encode()).hexdigest()!=response['raw_sha256']:
            raise ValueError('NHL_raw_hash_or_availability_mismatch')
        data=json.loads(raw)
        if len(data.get('events',[]))>40 or not any(x.get('slug')=='nhl' and str(x.get('id'))=='90' for x in data.get('leagues',[])):
            raise ValueError('bounded_NHL_league_source_required')
        for row in data['events']:
            if row.get('season',{}).get('type')!=2:continue
            if len(row.get('competitions',[]))!=1:raise ValueError('one_exact_NHL_competition_required')
            comp=row['competitions'][0];sides={x['homeAway']:x for x in comp['competitors']}
            if set(sides)!={'home','away'}:raise ValueError('two_NHL_participants_required')
            home,away=sides['home'],sides['away']
            for side in (home,away):
                team=side['team']
                if (str(team.get('id'))=='129764' and team.get('abbreviation')=='UTA' and team.get('location')=='Utah' and team.get('name')=='Mammoth'):
                    side['team']={**team,'name':'Utah'} # explicit publisher identity, not fuzzy alias
            status=row['status']['type'];start=_at(row['date'])
            if home['team']['name'] not in TEAMS or away['team']['name'] not in TEAMS or home['team']['id']==away['team']['id']:
                raise ValueError('known_unique_NHL_participant_identity_required')
            final=status.get('completed') is True and status.get('name')=='STATUS_FINAL' and status.get('state')=='post'
            hs,aws=int(home.get('score','0')),int(away.get('score','0'))
            if final and (start>received or hs==aws or hs<0 or aws<0 or hs>50 or aws>50 or home.get('winner') is not (hs>aws) or away.get('winner') is not (aws>hs)):
                raise ValueError('contradictory_NHL_final_result')
            game={'id':str(row['id']),'start':start.isoformat(),'home_id':str(home['team']['id']),'away_id':str(away['team']['id']),
                'home':home['team']['name'],'away':away['team']['name'],'home_score':hs,'away_score':aws,'final':final,
                'scheduled':status.get('state')=='pre' and status.get('name')=='STATUS_SCHEDULED' and status.get('completed') is False,
                'available_at':received.isoformat(),'source_sha256':response['raw_sha256']}
            if game['id'] in result:
                old=result[game['id']]
                keys=('start','home_id','away_id','home_score','away_score','final','scheduled')
                if any(old[k]!=game[k] for k in keys):raise ValueError('conflicting_NHL_source_records')
            result[game['id']]=game
    return e,sorted(result.values(),key=lambda x:(x['start'],x['id']))


async def collect_evidence(*,clock):
    global _LOCK,_LOOP
    now=_at(clock());loop=asyncio.get_running_loop()
    if _LOCK is None or _LOOP is not loop:_LOCK=asyncio.Lock();_LOOP=loop
    async with _LOCK:
        key=now.astimezone(ZoneInfo('America/New_York')).date().isoformat()
        cached=_CACHE.get(key)
        if cached is not None and 0<=(_at(clock())-cached.available_at).total_seconds()<=600:return cached
        responses=[];gate=asyncio.Lock();next_start=0.;semaphore=asyncio.Semaphore(2)
        days=[now.astimezone(ZoneInfo('America/New_York')).date()+timedelta(days=i) for i in range(-28,3)]
        async with httpx.AsyncClient(timeout=8,follow_redirects=False) as client:
            async def one(day):
                nonlocal next_start
                async with semaphore:
                    async with gate:
                        delay=max(0.,next_start-time.monotonic())
                        if delay:await asyncio.sleep(delay)
                        next_start=time.monotonic()+1
                    requested=_at(clock());url=ORIGIN+PATH+'?dates='+day.strftime('%Y%m%d')
                    r=await client.get(url);r.raise_for_status();received=_at(clock())
                    if len(r.content)>2*1024**2:raise ValueError('NHL_response_byte_budget_exceeded')
                    raw=r.content.decode('utf8')
                    return {'url':url,'requested_at':requested.isoformat(),'retrieved_at':received.isoformat(),'raw_utf8':raw,'raw_sha256':hashlib.sha256(raw.encode()).hexdigest()}
            responses=await asyncio.gather(*(one(day) for day in days))
        if sum(len(x['raw_utf8'].encode()) for x in responses)>16*1024**2:raise ValueError('NHL_source_budget_exceeded')
        received=max(_at(x['retrieved_at']) for x in responses);payload={'responses':responses,'availability_basis':'actual_first_observed_retrieval','provider_is_official_NHL':False}
        e=DomainEvidence(id=digest(['ESPN-NHL-v25',digest(payload),received.isoformat()]),timestamp=received,available_at=received,
            retrieved_at=received,source=ORIGIN+PATH,domain='sports',provider='ESPN public NHL scoreboard',source_id=key,
            content_sha256=digest(payload),payload=payload,independent_of_polymarket=True,qualification='qualified_research')
        _parse(e,received);_CACHE.clear();_CACHE[key]=e
        return e


def _predict(market,evidence,*,cutoff):
    now=_at(cutoff);m=MarketSnapshot.model_validate(market);support=supports(m,cutoff=now)
    if not support['supported']:raise ValueError(';'.join(support['reasons']))
    e,games=_parse(evidence,now)
    if (now-e.available_at).total_seconds()>600:raise ValueError('NHL_schedule_source_stale')
    c=support['contract'];params=c['parameters'];start=_at(params['scheduled_start'])
    targets=[g for g in games if {g['home'],g['away']}==set(params['participants']) and _at(g['start'])==start]
    if len(targets)!=1 or not targets[0]['scheduled']:raise ValueError('unique_current_NHL_schedule_match_required')
    target=targets[0];training=[g for g in games if g['final'] and _at(g['start'])<now and _at(g['available_at'])<=now]
    counts=Counter(team for g in training for team in (g['home_id'],g['away_id']))
    if len(training)<100 or min(counts[target['home_id']],counts[target['away_id']])<5:
        raise ValueError('100_league_finals_and_five_per_NHL_participant_required')
    ratings={};wins=Counter();home_wins=0
    for i,g in enumerate(training):
        h,a=g['home_id'],g['away_id'];actual=int(g['home_score']>g['away_score']);prior=(home_wins+2)/(i+4)
        advantage=400*math.log10(prior/(1-prior));p=1/(1+10**((ratings.get(a,1500)-ratings.get(h,1500)-advantage)/400))
        delta=20*(actual-p);ratings[h]=ratings.get(h,1500)+delta;ratings[a]=ratings.get(a,1500)-delta
        wins[h if actual else a]+=1;home_wins+=actual
    h,a=target['home_id'],target['away_id'];home_prior=(home_wins+2)/(len(training)+4);advantage=400*math.log10(home_prior/(1-home_prior))
    elo=1/(1+10**((ratings.get(a,1500)-ratings.get(h,1500)-advantage)/400))
    ph=(wins[h]+2)/(counts[h]+4);pa=(wins[a]+2)/(counts[a]+4)
    odds=ph/(1-ph)/(pa/(1-pa))*home_prior/(1-home_prior);frequency=odds/(1+odds)
    selected_home=params['selected']==target['home'];values=[elo,frequency] if selected_home else [1-elo,1-frequency]
    dataset=digest(training);result=[]
    for definition,p in zip(definitions(),values):
        result.append({**definition,'status':'research_estimate','domain':'sports','league':'NHL','event_id':m.event_id,'market_id':m.market_id,
            'token_id':m.token_id,'probability':p,'probability_semantics':'binary_event_probability','target_conditioning':'official_completed_game',
            'lower_probability':0.,'upper_probability':1.,'uncertainty':{'lower_probability':0.,'upper_probability':1.,'type':'uncalibrated_not_a_coverage_interval'},
            'dataset_sha256':dataset,'rules_sha256':c['rules_sha256'],'evidence_ids':[e.id],'evidence_cutoff':now.isoformat(),
            'event_end_time':start.isoformat(),'event_start_time':start.isoformat(),'prediction_horizon_seconds':(start-now).total_seconds(),
            'source_lineages':['ESPN:NHL:daily-scoreboards'],'calibration_status':'unvalidated_research','independent_of_polymarket':True,
            'training_observations':len(training),'training_event_ids':[g['id'] for g in training],'source_game_id':target['id'],
            'training_interval':[training[0]['start'],training[-1]['start']],'contract':c,
            'market_probability':None,'market_baseline_status':'expected_payout_not_completion_conditioned_win_probability',
            'limitations':['No injury/lineup information','Beta-frequency odds assume conditional team-strength independence; no validation claim','ESPN publisher is not NHL official resolution record','Cancellation/no-result probabilities not estimated; voids retained unscored','No retrospective point-in-time availability claim before raw retrieval','No execution authority or demonstrated after-cost edge']})
    return result


async def forecast(market,book,*,clock):
    now=_at(clock());support=supports(market,cutoff=now)
    if not support['supported']:return {'forecasts':[],'evidence':[],'rejections':support['reasons']}
    try:
        m=MarketSnapshot.model_validate(market.model_dump() if hasattr(market,'model_dump') else market)
        e=await collect_evidence(clock=clock);b=OrderBookSnapshot.model_validate(book.model_dump() if hasattr(book,'model_dump') else book) if book is not None else None
        cutoff=_at(clock())
        if b is None or not assess_book(b,cutoff,max_spread=.05,expected_token=m.token_id).healthy:
            adapter=OperationalPolymarketAdapter(clock=clock)
            try:b=await adapter.book(m.market_id,m.token_id)
            finally:await adapter.close()
            cutoff=_at(clock())
        if (b.market_id!=m.market_id or b.exchange!=m.exchange or b.source not in PUBLIC_BOOK_SOURCES
            or not assess_book(b,cutoff,max_spread=.05,expected_token=m.token_id).healthy):raise ValueError('fresh_native_NHL_two_sided_book_required')
        results=await asyncio.to_thread(_predict,m.model_dump(mode='json'),e,cutoff=cutoff)
        created=_at(clock())
        if not assess_book(b,created,max_spread=.05,expected_token=m.token_id).healthy:raise ValueError('NHL_quote_stale_after_model')
        for f in results:
            f.update(timestamp=created.isoformat(),market=m.model_dump(mode='json'),book=b.model_dump(mode='json'),book_sha256=digest(b.model_dump(mode='json')),
                book_id=b.id,market_expected_payout=(b.bids[0].price+b.asks[0].price)/2)
        return {'forecasts':results,'evidence':[e.model_dump(mode='json')],'rejections':[]}
    except (ValueError,TypeError,KeyError,OverflowError,httpx.HTTPError,OSError) as error:
        return {'forecasts':[],'evidence':[],'rejections':[f'NHL_withheld:{type(error).__name__}:{str(error)[:160]}']}


def replay(forecast,evidence,*,as_of):
    f=forecast;now=_at(as_of);created=_at(f['timestamp']);cutoff=_at(f['evidence_cutoff'])
    if not cutoff<=created<=now or len(evidence)!=1:raise ValueError('NHL_original_causal_forecast_required')
    result=next(x for x in _predict(f['market'],evidence[0],cutoff=cutoff) if x['model_id']==f['model_id'])
    if any(f.get(k)!=v for k,v in result.items()):raise ValueError('NHL_model_source_replay_mismatch')
    b=OrderBookSnapshot.model_validate(f['book']);m=MarketSnapshot.model_validate(f['market'])
    if b.market_id!=m.market_id or b.source not in PUBLIC_BOOK_SOURCES or digest(f['book'])!=f['book_sha256'] or not assess_book(b,created,max_spread=.05,expected_token=m.token_id).healthy:
        raise ValueError('NHL_original_native_quote_mismatch')
    if f['market_probability'] is not None or f['market_expected_payout']!=(b.bids[0].price+b.asks[0].price)/2:
        raise ValueError('NHL_market_quote_is_not_unconditional_win_probability')
    return {'verified':True,'research_only':True,'trading_authority':False,'forecast_id':f.get('id')}


async def verify_outcome(forecast,*,directory,clock):
    """Collect publisher finals, but withhold without independent official NHL proof.

    No score, terminal quote, ESPN final flag or asserted payout alone can become
    the contract's verified settlement. The existing native-proof pipeline may
    bind this evidence once official-source corroboration is accessible.
    """
    del directory
    now=_at(clock());f=forecast
    if now<_at(f['event_start_time']):return {'status':'pending','reasons':['NHL_game_not_started'],'outcome':None}
    try:
        async with httpx.AsyncClient(timeout=8,follow_redirects=False) as client:
            day=_at(f['event_start_time']).astimezone(ZoneInfo('America/New_York')).strftime('%Y%m%d')
            r=await client.get(ORIGIN+PATH,params={'dates':day});r.raise_for_status()
            if len(r.content)>2*1024**2:raise ValueError('NHL_outcome_source_budget')
            events=r.json()['events'];event=next((e for e in events if str(e['id'])==f['source_game_id']),None)
            if not event or event['status']['type'].get('completed') is not True or event['status']['type'].get('name')!='STATUS_FINAL':
                return {'status':'pending','reasons':['NHL_official_final_not_available'],'outcome':None}
            # Official NHL endpoints were observed 403; do not disguise the
            # accessible publisher as the required official resolution record.
            return {'status':'withheld','reasons':['ESPN_final_observed_but_official_NHL_and_native_settlement_replay_required'],
                'outcome':None,'publisher_raw_sha256':hashlib.sha256(r.content).hexdigest(),'observed_at':_at(clock()).isoformat(),
                'trading_authority':False}
    except (ValueError,TypeError,KeyError,httpx.HTTPError,OSError) as error:
        return {'status':'withheld','reasons':[f'NHL_outcome_source_unavailable:{type(error).__name__}'],'outcome':None}
