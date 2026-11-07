"""Controlled synthetic transports are engineering tests, never market evidence."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from neraium_poly.contracts import OrderBookSnapshot, PriceLevel
from neraium_poly.data.operational import DiscoveryBatch
from neraium_poly.data.polymarket import CLOB, normalize_market
from neraium_poly.research.phase14.discovery import classify_market
from neraium_poly.research.phase23.discovery import augment_diverse, select_diverse

NOW = datetime(2026, 11, 7, 12, tzinfo=UTC)


def raw(i, parent=None, domain='weather', **changes):
    return {'id': str(i), 'eventId': parent or 'e'+str(i), 'events': [{'id': parent or 'e'+str(i), 'tags': [{'slug': domain, 'id': '42'}]}],
        'question': 'Controlled contract?', 'clobTokenIds': ['t'+str(i), 'n'+str(i)], 'outcomes': ['Yes', 'No'],
        'outcomePrices': [.4, .6], 'active': True, 'closed': False, 'acceptingOrders': True, 'enableOrderBook': True,
        'description': 'Controlled exact rules', 'resolutionSource': 'https://example.invalid/rules',
        'endDate': (NOW+timedelta(days=3)).isoformat(), 'liquidity': 1000, 'volume24hr': 100, **changes}


def item(i, **changes):
    r = raw(i, **changes)
    return {'markets': normalize_market(r, NOW), 'classification': classify_market(r, NOW).model_dump(mode='json')}


def select(items, **kwargs):
    return select_diverse(items, books={}, now=NOW, max_markets=10, max_tokens=20, **kwargs)


def test_domain_and_parent_breadth_instead_of_single_high_volume_parent():
    xs = [item(1,parent='p',domain='crypto'),item(2,parent='p',domain='crypto'),item(3,parent='q',domain='crypto'), item(4,domain='weather')]
    _markets,r = select_diverse(xs, books={}, now=NOW, max_markets=3,max_tokens=6)
    assert r['category_distribution']=={'crypto':2,'weather':1}
    assert r['parent_events']==3
    assert all(x['independent_evidence_available'] is None and x['historical_model_performance'] is None and not x['trading_authority'] for x in r['markets'])


def test_near_term_priority_and_long_horizons_retained():
    xs=[item(1,parent='p'),item(2,parent='p',endDate=(NOW+timedelta(hours=3)).isoformat())]
    _,r=select(xs)
    assert [x['market_id'] for x in r['markets']]==['2','1']


def test_token_budget_never_splits_market_and_elapsed_events_ignored():
    xs=[item(1),item(2),item(3,endDate=NOW.isoformat())]
    markets,r=select_diverse(xs, books={},now=NOW,max_markets=3,max_tokens=3)
    assert len(markets)==2 and r['selected_markets']==1


def test_future_and_conflicting_parent_token_identity_fail_closed():
    x=item(1);x['markets']=[m.model_copy(update={'available_at':NOW+timedelta(seconds=1)}) for m in x['markets']]
    with pytest.raises(ValueError,match='future'):select([x])
    x=item(1);y=item(2);y['markets']=[m.model_copy(update={'token_id':x['markets'][0].token_id}) for m in y['markets'][:1]]
    with pytest.raises(ValueError,match='conflicting'):select([x,y])


def test_only_fresh_native_bound_books_count_as_executable_depth():
    xs=[item(1),item(2)];m=xs[1]['markets'][0]
    b=OrderBookSnapshot(id='b',timestamp=NOW,available_at=NOW,source=CLOB,market_id=m.market_id,token_id=m.token_id,
        bids=(PriceLevel(price=.39,size=100),),asks=(PriceLevel(price=.4,size=100),))
    _,r=select_diverse(xs,books={m.token_id:b},now=NOW,max_markets=2,max_tokens=4)
    assert r['markets'][0]['market_id']=='2' and r['markets'][0]['top3_two_sided_depth_usd']==39
    _,r=select_diverse(xs,books={m.token_id:b.model_copy(update={'timestamp':NOW-timedelta(minutes=1)})},now=NOW,max_markets=2,max_tokens=4)
    assert all(x['top3_two_sided_depth_usd'] is None for x in r['markets'])


class Adapter:
    def __init__(self, mode='normal'):
        self.calls=[];self.mode=mode
    async def _get(self, base,path,params=None):
        assert base=='https://gamma-api.polymarket.com';self.calls.append((path,params))
        if path.startswith('/tags/slug/'):
            slug=path.split('/')[-1]
            if slug not in ['weather','crypto']:
                request=httpx.Request('GET',base+path);raise httpx.HTTPStatusError('controlled missing tag',request=request,response=httpx.Response(404,request=request))
            return {'id':slug,'slug':slug}
        domain=params['tag_id'];r=raw(domain,domain=domain)
        if self.mode=='mismatch':r['eventId']='wrong'
        if self.mode=='query_does_not_imply_domain':r['events']=[]
        return [{'id':'e'+domain,'tags':[] if self.mode=='query_does_not_imply_domain' else [{'id':domain,'slug':domain}], 'markets':[r]}]


def coordinator(mode='normal'):
    return SimpleNamespace(adapter=Adapter(mode),clock=lambda:NOW,ledger={},books={},events=SimpleNamespace(append=lambda x:None),
        config=SimpleNamespace(max_markets=5,max_subscription_tokens=12,forecast_priority_market_limit=1,forecast_discovery_enabled=True))


@pytest.mark.asyncio
async def test_bounded_actual_tag_discovery_journal_and_cached_tag_reuse():
    c=coordinator();saved=[];c.events.append=saved.append
    b=DiscoveryBatch(normalize_market(raw('base'),NOW),1,True,(),0)
    selected,r=await augment_diverse(c,b)
    assert len({m.market_id for m in selected.markets})==3 and r['requests']<=24
    assert r['category_distribution']=={'crypto':1,'other':1,'weather':1}
    assert len(saved)==1 and not saved[0].trading_authority
    assert saved[0].provenance[0]['hash_semantics'].startswith('canonical JSON')
    c.adapter.calls=[];await augment_diverse(c,b)
    assert '/tags/slug/weather' not in [x[0] for x in c.adapter.calls]


@pytest.mark.asyncio
async def test_query_tag_never_substitutes_for_actual_taxonomy_and_bad_parent_quarantined():
    b=DiscoveryBatch(normalize_market(raw('base'),NOW),1,True,(),0)
    _,r=await augment_diverse(coordinator('query_does_not_imply_domain'),b)
    assert r['category_distribution']=={'other':3}
    _,r=await augment_diverse(coordinator('mismatch'),b)
    assert r['errors']['contradictory_parent_event']==2
    assert r['selected_markets']==1


@pytest.mark.asyncio
async def test_lossless_new_evidence_replay_detects_corruption_without_original_deletion():
    from neraium_poly.research.phase23.discovery import replay_discovery_payload
    c=coordinator();saved=[];c.events.append=saved.append
    await augment_diverse(c,DiscoveryBatch(normalize_market(raw('base'),NOW),1,True,(),0))
    proof=next(x for x in saved[0].provenance if x['source'].endswith('/tags/slug/weather'))
    assert replay_discovery_payload(proof)=={'id':'weather','slug':'weather'}
    assert 'payload' not in proof and proof['retention_format'].startswith('lossless')
    with pytest.raises(ValueError,match='hash'):
        replay_discovery_payload({**proof,'canonical_payload_sha256':'0'*64})
    with pytest.raises(ValueError,match='bounded'):
        replay_discovery_payload({**proof,'canonical_bytes':10**9})


@pytest.mark.asyncio
async def test_upcoming_nfl_scheduling_bands_do_not_repeat_first_game_props():
    class NFLAdapter(Adapter):
        async def _get(self,base,path,params=None):
            if path=='/tags/slug/nfl':
                self.calls.append((path,params));return {'id':'nfl','slug':'nfl'}
            if path=='/events' and params.get('tag_id')=='nfl':
                self.calls.append((path,params));n=sum(p=='/events' and q.get('tag_id')=='nfl' for p,q in self.calls)
                at=NOW+timedelta(hours=n)
                assert datetime.fromisoformat(params['end_date_min'])<at
                return [{'id':f'en{n}','endDate':at.isoformat(),'tags':[{'id':'nfl','slug':'nfl'}],
                    'markets':[raw(f'n{n}',parent=f'en{n}',domain='sports',endDate=at.isoformat())]}]
            return await super()._get(base,path,params)
    c=coordinator();c.adapter=NFLAdapter();c.config.max_markets=8;c.config.max_subscription_tokens=20
    b=DiscoveryBatch(normalize_market(raw('base'),NOW),1,True,(),0)
    selected,r=await augment_diverse(c,b)
    assert {m.event_id for m in selected.markets if m.market_id.startswith('n')}=={'en1','en2','en3'}
    assert r['requests']<=28 and r['evidence_bytes']<=r['max_evidence_bytes']


def test_future_daily_rule_support_does_not_create_future_features_or_forecast():
    from neraium_poly.research.phase18.forecasting import daily_low_rules
    r=raw('tomorrow',domain='crypto',question='Will Bitcoin dip to $70,000 on November 8?',
        description=daily_low_rules('Bitcoin'),resolutionSource='https://www.binance.com/en/trade/BTC_USDT',
        endDate='2026-11-09T05:00:00+00:00')
    candidate={'markets':normalize_market(r,NOW),'classification':classify_market(r,NOW).model_dump(mode='json')}
    markets,report=select([candidate]);row=report['markets'][0]
    assert row['future_daily_rule_adapter'] and not row['exact_rule_model_supported']
    assert not row['forecast_qualified'] and all(m.available_at==NOW for m in markets)
