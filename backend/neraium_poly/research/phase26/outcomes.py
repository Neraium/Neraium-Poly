"""Official NHL game/report corroboration; no price-derived or publisher-only labels."""
import hashlib
import importlib
import json
import math
import re
import unicodedata
from datetime import UTC, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx

from neraium_poly.contracts import MarketSnapshot
from neraium_poly.research.phase12.contracts import SettlementProofReference, VerifiedEventOutcome
from neraium_poly.research.phase12.outcome_collector import acquire_verified_outcome, verify_collected_outcome
from neraium_poly.research.phase14.relationships import digest

PROTOCOL='official-sports-v26'
ORIGIN='https://api.nhle.com/stats/rest/en/'
MAX_BYTES=2*1024**2
AUTHORITY={'research_only':True,'trading_authority':False,'certification_authority':False}
_CACHE={}


def at(value):
    value=value if isinstance(value,datetime) else datetime.fromisoformat(value)
    if value.tzinfo is None:raise ValueError('aware_official_outcome_time_required')
    return value.astimezone(UTC)


def _name(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',value) if not unicodedata.combining(c)).upper()


def _mapping(f):
    league=f.get('league')
    if league!='NHL':raise ValueError('official_NBA_source_access_unavailable_no_publisher_substitution')
    module=importlib.import_module('neraium_poly.research.phase25.sports')
    m=MarketSnapshot.model_validate(f['market']);created=at(f['timestamp']);cutoff=at(f['evidence_cutoff'])
    mapped=module.supports(m,cutoff=cutoff)
    if not mapped.get('supported') or mapped['contract']!=f['contract'] or not m.timestamp<=m.available_at<=cutoff<=created<m.end_time:
        raise ValueError('original_exact_NHL_contract_and_prospectivity_required')
    if any(f[k]!=getattr(m,k) for k in ('event_id','market_id','token_id')):raise ValueError('original_market_token_parent_identity_mismatch')
    if f['rules_sha256']!=hashlib.sha256(m.resolution_rules.encode()).hexdigest():raise ValueError('original_rules_hash_mismatch')
    p=f['contract']['parameters'];start=at(p['scheduled_start'])
    if start!=m.end_time or p['selected']!=m.outcome:raise ValueError('original_scheduled_participant_binding_required')
    return m,p,start


def _reference(f):
    return SettlementProofReference(id=f['id'],event_id=f['event_id'],market_id=f['market_id'],token_id=f['token_id'],timestamp=at(f['timestamp']),
        evidence_cutoff=at(f['evidence_cutoff']),resolution_rules_sha256=f['rules_sha256'],original_record_sha256=digest(f))


def game_url(start):
    local=at(start).astimezone(ZoneInfo('America/New_York'));year=local.year if local.month>=7 else local.year-1
    return ORIGIN+'game?'+urlencode({'start':0,'limit':50,'cayenneExp':f"season={year}{year+1} and gameDate='{local.date().isoformat()}'"})


class _Header(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.stack=[];self.tables={};self.images={}
    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        if tag=='table':
            identity=values.get('id');self.stack.append(identity)
            if identity in ('Visitor','Home','GameInfo'):
                if identity in self.tables:raise ValueError('duplicate_official_report_header')
                self.tables[identity]=[];self.images[identity]=[]
        if tag=='img':
            for identity in self.stack:
                if identity in self.tables and values.get('alt'):self.images[identity].append(values['alt'])
        if tag in ('br','td','tr'):
            self.handle_data(' ')
    def handle_endtag(self,tag):
        if tag=='table':
            if not self.stack:raise ValueError('unbalanced_official_report_tables')
            self.stack.pop()
        if tag in ('td','tr'):self.handle_data(' ')
    def handle_data(self,data):
        for identity in self.stack:
            if identity in self.tables:self.tables[identity].append(data)


def _team_ids(teams,participants):
    if not isinstance(teams.get('data'),list) or not 1<=len(teams['data'])<=100:raise ValueError('bounded_official_team_catalog_required')
    result={}
    for name in participants:
        matches=[t for t in teams['data'] if t.get('leagueId')==133 and isinstance(t.get('fullName'),str)
            and (_name(t['fullName']).endswith(' '+_name(name)) or name=='Utah' and t['id']==68 and t['fullName']=='Utah Mammoth')]
        if len(matches)!=1:raise ValueError('unique_official_NHL_team_identity_required')
        result[name]=matches[0]
    if len({x['id'] for x in result.values()})!=2:raise ValueError('distinct_official_NHL_teams_required')
    return result


def select_game(raw,teams_raw,parameters,start):
    """Strict primary identity and final-state check, before fetching the report."""
    if not 0<len(raw)<=MAX_BYTES or not 0<len(teams_raw)<=MAX_BYTES:raise ValueError('bounded_official_source_required')
    data=json.loads(raw);teams=json.loads(teams_raw);ids=_team_ids(teams,parameters['participants'])
    if not isinstance(data.get('data'),list) or not 0<=len(data['data'])<=50 or data.get('total',51)>50:
        raise ValueError('complete_bounded_official_game_date_required')
    local=at(start).astimezone(ZoneInfo('America/New_York'));season=local.year if local.month>=7 else local.year-1
    found=[]
    for row in data['data']:
        if {row.get('homeTeamId'),row.get('visitingTeamId')}!={x['id'] for x in ids.values()}:continue
        value=datetime.fromisoformat(row['easternStartTime'])
        if value.tzinfo is not None:raise ValueError('documented_eastern_game_clock_required')
        scheduled=value.replace(tzinfo=ZoneInfo('America/New_York')).astimezone(UTC)
        if (scheduled!=at(start) or row.get('season')!=int(f'{season}{season+1}') or row.get('gameDate')!=local.date().isoformat()
            or row.get('gameType')!=2 or str(row.get('id'))!=f"{season}02{row['gameNumber']:04d}"):
            continue
        found.append(row)
    if len(found)!=1:raise ValueError('unique_exact_official_schedule_match_required_no_postponement_guess')
    row=found[0]
    if row.get('gameStateId')!=7:return {'status':'pending','reason':'official_game_not_final','official_game_id':row['id']}
    if row.get('gameScheduleStateId')!=1:raise ValueError('official_reschedule_or_cancellation_review_required')
    if any(type(row.get(k)) is not int or not 0<=row[k]<=50 for k in ('homeScore','visitingScore')) or row['homeScore']==row['visitingScore']:
        raise ValueError('official_tied_void_or_invalid_score_unscored')
    return {'status':'final_candidate','game':row,'teams':ids,'report_url':f"https://www.nhl.com/scores/htmlreports/{season}{season+1}/GS02{row['gameNumber']:04d}.HTM"}


def parse_official_nhl(raw,teams_raw,report_raw,parameters,start,*,available_at):
    """Require both the official typed game and explicit final report header."""
    now=at(available_at);candidate=select_game(raw,teams_raw,parameters,start)
    if candidate['status']!='final_candidate':return candidate
    if not 0<len(report_raw)<=MAX_BYTES:raise ValueError('bounded_official_report_required')
    source=report_raw.decode('utf8')
    if re.search(r'\b(?:corrected|disputed|protested|postponed|cancelled|canceled|suspended)\b',source,re.IGNORECASE):
        raise ValueError('official_report_correction_or_dispute_review_required')
    header=_Header();header.feed(source);header.close();row=candidate['game'];teams=candidate['teams']
    if set(header.tables)!= {'Visitor','Home','GameInfo'}:raise ValueError('complete_official_report_header_required')
    texts={k:' '.join(''.join(v).split()) for k,v in header.tables.items()}
    for section,label,score_key,team_key in [('Visitor','VISITOR','visitingScore','visitingTeamId'),('Home','HOME','homeScore','homeTeamId')]:
        team=next(t for t in teams.values() if t['id']==row[team_key]);expected=_name(team['fullName'])
        if not re.match(rf'^{label}\s+{row[score_key]}\s+',texts[section]) or [ _name(x) for x in header.images[section]]!=[expected]:
            raise ValueError('official_report_score_or_team_disagrees')
    info=texts['GameInfo'];number=f"{row['gameNumber']:04d}"
    if not re.search(rf'\bGame {number} Final(?: OT| SO)?$',info):raise ValueError('explicit_official_final_report_required')
    date=re.search(r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), [A-Z][a-z]+ \d{1,2}, 20\d{2}',info)
    clocks=re.search(r'Start (\d{1,2}:\d{2}) ([A-Z]{2,4}); End (\d{1,2}:\d{2}) ([A-Z]{2,4})',info)
    if not date or not clocks:raise ValueError('official_report_date_and_end_clock_required')
    day=datetime.strptime(date.group(),'%A, %B %d, %Y')
    if day.strftime('%A')!=date.group(1):raise ValueError('official_report_calendar_mismatch')
    offsets={'EST':-5,'EDT':-4,'CST':-6,'CDT':-5,'MST':-7,'MDT':-6,'PST':-8,'PDT':-7,'GMT':0,'UTC':0,'CET':1,'CEST':2,'EET':2,'EEST':3}
    def candidates(text,abbr):
        if abbr not in offsets:raise ValueError('reviewed_official_report_timezone_required')
        h,m=map(int,text.split(':'))
        if not 1<=h<=12 or not 0<=m<60:raise ValueError('official_report_12hour_clock_required')
        return [(day+timedelta(days=d)).replace(hour=h%12+half,minute=m,tzinfo=timezone(timedelta(hours=offsets[abbr]))).astimezone(UTC)
                for d in (-1,0,1) for half in (0,12)]
    starts=[x for x in candidates(*clocks.groups()[:2]) if at(start)-timedelta(minutes=15)<=x<=at(start)+timedelta(hours=6)]
    if len(starts)!=1:raise ValueError('unambiguous_official_start_clock_required')
    ends=[x for x in candidates(*clocks.groups()[2:]) if starts[0]<x<=min(starts[0]+timedelta(hours=12),now)]
    if len(ends)!=1:raise ValueError('unambiguous_official_final_clock_required')
    selected=teams[parameters['selected']]['id'];winner=row['homeTeamId'] if row['homeScore']>row['visitingScore'] else row['visitingTeamId']
    return {'status':'final','official_game_id':row['id'],'home_team_id':row['homeTeamId'],'away_team_id':row['visitingTeamId'],
        'home_score':row['homeScore'],'away_score':row['visitingScore'],'expected_payout':int(selected==winner),
        'scheduled_start':at(start).isoformat(),'actual_start_lower':starts[0].isoformat(),'actual_start_upper':(starts[0]+timedelta(minutes=1)).isoformat(),
        'end_lower':ends[0].isoformat(),'end_upper':(ends[0]+timedelta(minutes=1)).isoformat(),'timing_precision':'official minute bounds, not invented exact completion timestamp',
        'report_url':candidate['report_url']}


def _root(directory):
    p=Path(directory).absolute()
    if p.is_symlink() or any(x.is_symlink() for x in p.parents):raise ValueError('outcome_directory_symlink')
    p.mkdir(parents=True,exist_ok=True);return p


async def _fetch(client,url,clock):
    now=at(clock());cached=_CACHE.get(url)
    if cached and 0<=(now-at(cached[1]['retrieved_at'])).total_seconds()<60:return cached
    async with client.stream('GET',url) as response:
        response.raise_for_status();raw=bytearray()
        async for chunk in response.aiter_bytes():
            raw.extend(chunk)
            if len(raw)>MAX_BYTES:raise ValueError('official_source_byte_budget')
    raw=bytes(raw);received=at(clock());item={'source_url':url,'retrieved_at':received.isoformat(),'content_sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
    if not raw:raise ValueError('nonempty_official_source_required')
    _CACHE[url]=(raw,item)
    while len(_CACHE)>16:_CACHE.pop(next(iter(_CACHE)))
    return raw,item


def _save(root,raw,item,suffix):
    item={**item,'raw_file':item['content_sha256']+suffix};p=root/item['raw_file']
    if p.exists():
        if p.is_symlink() or p.read_bytes()!=raw:raise ValueError('official_evidence_existing_content_conflict')
    else:
        with p.open('xb') as handle:handle.write(raw)
    return item


async def verify_sport_outcome(f,*,directory,clock=None):
    clock=clock or (lambda:datetime.now(UTC));now=at(clock())
    try:m,parameters,start=_mapping(f)
    except (ValueError,KeyError,TypeError) as error:return {'verified':False,'status':'withheld','reason':str(error),**AUTHORITY}
    if now<start:return {'verified':False,'status':'pending','reason':'official_scheduled_game_not_started',**AUTHORITY}
    root=_root(directory);native_root='nhl-'+digest(f['id'])[:16];sub=_root(root/native_root)
    try:
        async with httpx.AsyncClient(timeout=10,follow_redirects=False) as client:
            game,item=await _fetch(client,game_url(start),clock);teams,team_item=await _fetch(client,ORIGIN+'team?start=0&limit=100',clock)
            candidate=select_game(game,teams,parameters,start)
            evidence=[_save(sub,game,item,'.json'),_save(sub,teams,team_item,'.json')]
            if candidate['status']!='final_candidate':return {'verified':False,'status':'pending','reason':candidate['reason'],'official_evidence':evidence,**AUTHORITY}
            html,report_item=await _fetch(client,candidate['report_url'],clock);evidence.append(_save(sub,html,report_item,'.html'))
        final=parse_official_nhl(game,teams,html,parameters,start,available_at=at(clock()))
        if not at(f['timestamp'])<at(final['actual_start_lower']):raise ValueError('forecast_did_not_precede_actual_game_start')
        reference=_reference(f);location=sub/('native-'+at(clock()).strftime('%Y%m%dT%H%M%S%fZ'))
        if location.exists():return {'verified':False,'status':'withheld','reason':'existing_native_attempt_preserved',**AUTHORITY}
        native=await acquire_verified_outcome(reference,m,location,clock=clock)
        if native is None or not verify_collected_outcome(native,m,reference,sub):return {'verified':False,'status':'pending','reason':'native_finalized_settlement_proof_unavailable','official_result':final,'official_evidence':evidence,**AUTHORITY}
        if native.payout!=final['expected_payout'] or native.settled_at<at(final['end_upper']):raise ValueError('official_and_native_settlement_disagree_or_premature')
        return {'verified':True,'status':'verified','verification_protocol':PROTOCOL,'forecast_id':f['id'],'event_id':f['event_id'],
            'available_at':at(clock()).isoformat(),'resolved_at':native.settled_at.isoformat(),'native_root':native_root,'official_result':final,
            'official_evidence':evidence,'native_outcome':native.model_dump(mode='json'),**AUTHORITY}
    except (ValueError,TypeError,KeyError,StopIteration,OSError,httpx.HTTPError) as error:
        return {'verified':False,'status':'withheld','reason':type(error).__name__+':'+str(error)[:160],**AUTHORITY}


def replay_sport_outcome(result,study,f,*,evidence_root,as_of):
    now=at(as_of);m,parameters,start=_mapping(f)
    if (result.get('verification_protocol')!=PROTOCOL or result.get('verified') is not True or result.get('status')!='verified'
        or result.get('forecast_id')!=f['id'] or result.get('event_id')!=f['event_id']
        or sum(x.get('id')==f['id'] and digest(x)==digest(f) for x in study.get('forecasts',[]))!=1
        or not at(f['timestamp'])<=at(study['available_at'])<start):raise ValueError('unique_original_prospective_forecast_required')
    module=importlib.import_module('neraium_poly.research.phase25.sports');byid={e['id']:e for e in study['evidence']}
    if len(byid)!=len(study['evidence']):raise ValueError('duplicate_original_source_evidence')
    if module.replay(f,[byid[x] for x in f['evidence_ids']],as_of=now).get('verified') is not True:raise ValueError('original_model_source_replay_failed')
    root=Path(evidence_root).absolute();expected_root='nhl-'+digest(f['id'])[:16]
    if result['native_root']!=expected_root or root.is_symlink() or any(x.is_symlink() for x in root.parents):raise ValueError('official_evidence_root_mismatch')
    sub=root/expected_root
    if sub.is_symlink():raise ValueError('official_evidence_root_alias')
    refs=result['official_evidence']
    if len(refs)!=3:raise ValueError('three_bound_official_sources_required')
    raw=[]
    for index,ref in enumerate(refs):
        suffix='.html' if index==2 else '.json';name=ref['content_sha256']+suffix
        if ref['raw_file']!=name or not re.fullmatch(r'[a-f0-9]{64}\.(?:json|html)',name):raise ValueError('official_evidence_path_mismatch')
        p=sub/name
        if p.is_symlink() or not p.resolve().is_relative_to(sub.resolve()) or not 0<p.stat().st_size<=MAX_BYTES:raise ValueError('official_evidence_path_or_size_invalid')
        body=p.read_bytes()
        if (hashlib.sha256(body).hexdigest()!=ref['content_sha256'] or len(body)!=ref['bytes'] or not at(ref['retrieved_at'])<=at(result['available_at'])<=now
            or index!=1 and at(ref['retrieved_at'])<start):
            raise ValueError('official_evidence_hash_or_receipt_mismatch')
        raw.append(body)
    if refs[0]['source_url']!=game_url(start) or refs[1]['source_url']!=ORIGIN+'team?start=0&limit=100':raise ValueError('exact_official_source_requests_required')
    final=parse_official_nhl(*raw,parameters,start,available_at=max(at(x['retrieved_at']) for x in refs))
    if final!=result['official_result'] or refs[2]['source_url']!=final['report_url']:raise ValueError('official_result_or_report_identity_mismatch')
    native=VerifiedEventOutcome.model_validate(result['native_outcome']);reference=_reference(f)
    if (not verify_collected_outcome(native,m,reference,sub) or native.payout!=final['expected_payout'] or native.settled_at<at(final['end_upper'])
        or not at(f['timestamp'])<at(final['actual_start_lower']) or not native.settled_at<=native.available_at<=at(result['available_at'])
        or at(result['resolved_at'])!=native.settled_at):raise ValueError('official_native_outcome_finality_mismatch')
    p=f['probability'];y=native.payout;likelihood=p if y else 1-p
    return {'verified':True,'forecast_id':f['id'],'event_id':f['event_id'],'market_id':f['market_id'],'token_id':f['token_id'],
        'rules_sha256':f['rules_sha256'],'resolved_at':native.settled_at.isoformat(),'available_at':result['available_at'],'outcome':y,
        'brier':(p-y)**2,'log_loss':-math.log(likelihood) if likelihood>0 else None,'log_loss_status':'finite' if likelihood>0 else 'positive_infinity',
        'market_brier':None,'score_scope':'completion-conditioned NHL score, not unconditional token/market superiority',
        'evidence_sha256':digest(refs),'reviewed_dependency_group':None,**AUTHORITY}
