"""Bounded additive forecast coverage; never evict a market carrying paper capital."""

import asyncio
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import timedelta
from pathlib import Path

from pydantic import Field

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, Record
from neraium_poly.data import assess_book
from neraium_poly.data.operational import DiscoveryBatch
from neraium_poly.data.polymarket import normalize_market
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase18.forecasting import map_event_contract
from neraium_poly.research.phase19.discovery import discover_forecast_markets


class PriorityIdentityError(ValueError):
    """Contradictory token/settlement identities must withhold the source cycle."""


def assert_same_contract(left, right):
    fields = ("exchange", "market_id", "event_id", "token_id", "outcome", "question",
              "resolution_rules", "resolution_source", "end_time")
    if any(getattr(left,k) != getattr(right,k) for k in fields):
        raise PriorityIdentityError("forecast_priority_contract_identity_changed")


class ForecastDiscoveryStudy(Record):
    provenance: list[dict] = Field(default_factory=list)
    candidate_market_ids: tuple[str, ...] = ()
    selected_market_ids: tuple[str, ...] = ()
    native_books: list[dict] = Field(default_factory=list)
    health_by_market: dict = Field(default_factory=dict)
    rejections: dict = Field(default_factory=dict)
    protection_status: str
    protected_market_ids: tuple[str, ...] = ()
    base_markets: int
    resulting_markets: int
    request_count: int
    trading_authority: bool = False


def protected_markets(directory):
    """Independent read-only capital references; unknown means retain old priorities.

    Read broker first, then risk reservations/positions to cover an order-to-fill
    transition. New live priority markets are retained regardless of exposure.
    Expired priorities cannot acquire new exposure through the existing strategy
    end-time gates. No foreign account is opened as a writer or reconciled here.
    """
    directory=Path(directory).absolute();protected=set()
    try:
        for filename in ['broker.sqlite','risk.sqlite']:
            path=directory/filename
            if path.is_symlink() or not path.is_file():raise ValueError('missing_or_symlinked_paper_capital_store')
            db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)
            try:
                db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
                if filename=='broker.sqlite':
                    rows=db.execute("SELECT intent FROM orders WHERE json_extract(report,'$.status') IN ('open','partial') LIMIT 4097").fetchall()
                    if len(rows)>4096:raise ValueError('bounded_open_order_protection_required')
                    for row in rows:protected.add(json.loads(row[0])['market_id'])
                else:
                    rows=db.execute('SELECT market FROM positions WHERE quantity>0 UNION SELECT market FROM reservations WHERE released=0 AND remaining>0 LIMIT 4097').fetchall()
                    if len(rows)>4096:raise ValueError('bounded_capital_protection_required')
                    protected.update(row[0] for row in rows)
            finally:db.close()
        return protected,'verified_read_only'
    except (OSError,ValueError,TypeError,KeyError,sqlite3.Error):
        return set(),'unavailable_retain_priorities'


def select_priority_pool(base, previous, discovery, *, now, limit, max_tokens, protected=(), protection_status='unavailable_retain_priorities'):
    if type(limit) is not int or not 1<=limit<=20:raise ValueError('bounded forecast priority count required')
    if not isinstance(previous,dict) or len(previous)>20:raise ValueError('bounded retained priority pool required')
    reasons=Counter();pool={};protected=set(protected)
    for market_id,values in previous.items():
        records=tuple(MarketSnapshot.model_validate(x) for x in values)
        if not records or any(m.market_id!=market_id for m in records):raise ValueError('priority checkpoint identity mismatch')
        if (protection_status!='verified_read_only' or market_id in protected
            or any(m.end_time is None or m.end_time+timedelta(seconds=300)>now for m in records)):
            pool[market_id]=records
    if len(pool)>limit:raise ValueError('retained exposure exceeds configured priority limit')
    baseline={m.token_id:m for m in base.markets}
    retained_by_token={m.token_id:m for values in pool.values() for m in values}
    for m in base.markets:
        if m.token_id in retained_by_token:assert_same_contract(m,retained_by_token[m.token_id])
        if m.market_id in pool and m.token_id not in {x.token_id for x in pool[m.market_id]}:
            raise PriorityIdentityError("retained_priority_token_binding_changed")
    books={b['token_id']:b for b in discovery['books']}
    from neraium_poly.research.phase21.discovery import prioritize_raw_candidates

    ordered_candidates, _priority_report = prioritize_raw_candidates(discovery['markets'], discovery['books'], now=now)
    for raw in ordered_candidates:
        records=normalize_market(raw,now);market_id=str(raw['id'])
        if market_id in pool:
            prior={m.token_id:m for m in pool[market_id]}
            if set(prior)!={m.token_id for m in records}:
                raise PriorityIdentityError("priority_provider_token_binding_changed")
            for m in records:assert_same_contract(m,prior[m.token_id])
        if len(records)!=2 or any(not map_event_contract(m,now=now).compatible for m in records):
            reasons['exact_current_day_contract_required']+=1;continue
        healthy=[]
        for m in records:
            value=books.get(m.token_id)
            if value is None:continue
            b=OrderBookSnapshot.model_validate(value)
            if (b.source in PUBLIC_BOOK_SOURCES and b.exchange==m.exchange and b.market_id==m.market_id
                and assess_book(b,now,max_spread=.05,expected_token=m.token_id).healthy):healthy.append(b)
        if not healthy:reasons['no_fresh_two_sided_preflight_book']+=1;continue
        if any(m.token_id in baseline and (baseline[m.token_id].market_id!=m.market_id
                or baseline[m.token_id].event_id!=m.event_id or baseline[m.token_id].resolution_rules!=m.resolution_rules) for m in records):
            raise PriorityIdentityError('forecast_priority_identity_conflict')
        if market_id not in pool and len(pool)>=limit:reasons['priority_market_budget_full']+=1;continue
        trial={**baseline,**{m.token_id:m for values in pool.values() for m in values},**{m.token_id:m for m in records}}
        if len(trial)>max_tokens:reasons['subscription_budget_full']+=1;continue
        pool[market_id]=records
    # Forecast coverage is additive: broad discovery and its existing ordering remain.
    incoming={m.token_id:m for values in pool.values() for m in values}
    incoming.update(baseline)
    if len(incoming)>max_tokens:raise ValueError('protected priority subscriptions exceed token budget')
    return DiscoveryBatch(tuple(incoming.values()),base.scanned_count,base.truncated,base.errors,base.next_offset),pool,dict(reasons)


async def augment_discovery(runtime, batch):
    """All source responses and selection inputs committed before exposure to consumers."""
    now=runtime.clock();previous=runtime.ledger.get('forecast_priority_pool',{})
    protected,status=await asyncio.to_thread(protected_markets,runtime.config.forecast_protected_directory)
    protected.update(p.market_id for p in runtime.risk.positions(now=now))
    if runtime.activation:protected.update(runtime.activation.relationship_tokens)
    discovery=await discover_forecast_markets(now=now,max_requests=3,max_candidates=40)
    now=runtime.clock();selected,pool,reasons=select_priority_pool(batch,previous,discovery,now=now,
        limit=runtime.config.forecast_priority_market_limit,max_tokens=runtime.config.max_subscription_tokens,
        protected=protected,protection_status=status)
    if not runtime._budget_ok():raise ValueError('forecast_discovery_archive_unavailable')
    payload={'source_discovery':discovery,'selected':sorted(pool),'base_id':sorted({m.market_id for m in batch.markets})}
    identity=hashlib.sha256(json.dumps(payload,sort_keys=True,allow_nan=False).encode()).hexdigest()
    row=ForecastDiscoveryStudy(id=identity,timestamp=now,available_at=now,source='phase19-public-forecast-discovery',
        provenance=discovery['provenance'],candidate_market_ids=tuple(str(m['id']) for m in discovery['markets']),
        selected_market_ids=tuple(pool),native_books=discovery['books'],health_by_market=discovery['health_by_market'],
        rejections=dict(Counter(discovery['rejections'])+Counter(reasons)),protection_status=status,protected_market_ids=tuple(sorted(protected)),
        base_markets=len({m.market_id for m in batch.markets}),resulting_markets=len({m.market_id for m in selected.markets}),request_count=discovery['requests_used'])
    runtime.events.append(row)
    runtime.ledger.put('forecast_priority_pool',{k:[m.model_dump(mode='json') for m in values] for k,values in pool.items()})
    return selected,{'study_id':row.id,'compatible_candidates':len(discovery['markets']),
        'priority_markets':len(pool),'requests':discovery['requests_used'],'rejections':row.rejections,
        'protection':status,'scope':'bounded additive independent-research coverage; no order authorization'}
