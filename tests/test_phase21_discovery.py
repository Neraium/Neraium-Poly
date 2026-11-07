"""Controlled collection ordering only; no fixture is actual forecasting evidence."""
from copy import deepcopy
from datetime import timedelta

import pytest
from neraium_poly.data.operational import DiscoveryBatch
from neraium_poly.data.polymarket import normalize_book, normalize_market
from neraium_poly.research.phase19.collection import select_priority_pool
from neraium_poly.research.phase21.discovery import prioritize_raw_candidates, rank_research_markets
from test_phase19_discovery import NOW, book, native


def fixture(parent, market_id, asset='bitcoin', size=100):
    raw = {**native(asset), 'id': market_id, 'eventId': parent,
           'clobTokenIds': f'["{market_id}-yes","{market_id}-no"]'}
    records = normalize_market(raw, NOW)
    books = []
    for record in records:
        b = book(record.token_id)
        b['bids'][0]['size'] = str(size)
        b['asks'][0]['size'] = str(size)
        books.append(normalize_book(b, record.market_id, record.token_id, NOW).model_dump(mode='json'))
    return raw, records, books


def test_ready_parent_diversity_prevents_large_parent_monopolizing_admissions():
    a, am, ab = fixture('CONTROLLED-parent-A', 'a', size=1000)
    b, bm, bb = fixture('CONTROLLED-parent-A', 'b', size=900)
    c, cm, cb = fixture('CONTROLLED-parent-B', 'c', 'ethereum', size=100)
    originals = deepcopy(([a, b, c], ab+bb+cb))
    ordered, result = prioritize_raw_candidates([a, b, c], ab+bb+cb, now=NOW)
    assert [m['id'] for m in ordered] == ['a', 'c', 'b']
    assert result['priority_ready_parent_events'] == 2 and result['priority_ready_markets'] == 3
    assert result['markets'][0]['observed_top3_entry_principal_at25percent'] == 102.5
    assert originals == ([a, b, c], ab+bb+cb)
    assert not result['trading_authority'] and not result['certification_authority']
    assert all(not r['forecast_qualified'] and not r['event_independence_reviewed'] for r in result['markets'])
    assert rank_research_markets(list(am+bm+cm), ab+bb+cb, now=NOW) == result


@pytest.mark.parametrize('mutation,reason', [
    ('stale', 'stale_book'), ('future', 'future_data'), ('source', 'native_book_identity_or_source_mismatch'),
    ('identity', 'native_book_identity_or_source_mismatch'), ('duplicate', 'duplicate_native_token_observation'),
    ('thin', 'standard_minimum_notional_or_lot_depth_unavailable'), ('one_sided', 'missing_liquidity')])
def test_quality_and_minimum_depth_are_not_manufactured(mutation, reason):
    _raw, markets, books = fixture('CONTROLLED-parent', 'a')
    if mutation == 'stale':
        for b in books: b['timestamp'] = (NOW-timedelta(seconds=60)).isoformat()
    elif mutation == 'future':
        for b in books: b['timestamp'] = b['available_at'] = (NOW+timedelta(seconds=1)).isoformat()
    elif mutation == 'source':
        for b in books: b['source'] = 'CONTROLLED unknown'
    elif mutation == 'identity':
        for b in books: b['market_id'] = 'CONTROLLED unrelated'
    elif mutation == 'duplicate': books += deepcopy(books)
    elif mutation == 'thin':
        for b in books:
            for side in ['bids', 'asks']: b[side][0]['size'] = 1
    else:
        for b in books: b['asks'] = []
    row = rank_research_markets(list(markets), books, now=NOW)['markets'][0]
    assert not row['priority_ready'] and reason in row['rejections']


def test_unsupported_longer_term_domain_remains_visible_without_probability():
    _raw, markets, books = fixture('CONTROLLED-weather', 'weather')
    markets = tuple(m.model_copy(update={'question': 'CONTROLLED rainfall question',
        'resolution_source': 'https://www.weather.gov/', 'end_time': NOW+timedelta(days=20)}) for m in markets)
    row = rank_research_markets(list(markets), books, now=NOW)['markets'][0]
    assert row['domain'] == 'weather' and not row['near_term'] and row['settlement_horizon_seconds'] > 86400
    assert not row['priority_ready'] and row['supported_research_model'] is None
    assert row['external_input_status'] == 'qualified_adapter_or_model_unavailable'
    assert row['settlement_at'] and row['rejections']


def test_integrated_admission_order_and_sticky_capital_are_preserved():
    a, am, ab = fixture('CONTROLLED-parent-A', 'a', size=1000)
    b, _bm, bb = fixture('CONTROLLED-parent-A', 'b', size=900)
    c, _cm, cb = fixture('CONTROLLED-parent-B', 'c', 'ethereum', size=100)
    base = DiscoveryBatch((), 0, False, (), 0)
    discovery = {'markets': [a, b, c], 'books': ab+bb+cb}
    selected, pool, reasons = select_priority_pool(base, {}, discovery, now=NOW, limit=2, max_tokens=4)
    assert list(pool) == ['a', 'c'] and len(selected.markets) == 4 and reasons['priority_market_budget_full'] == 1
    previous = {'a': [m.model_dump(mode='json') for m in am]}
    _, pool, _ = select_priority_pool(base, previous, {'markets': [c], 'books': cb}, now=NOW,
        limit=1, max_tokens=2, protected=['a'], protection_status='verified_read_only')
    assert list(pool) == ['a']  # a valid replacement never evicts protected/in-flight capital


def test_invalid_limits_and_ambiguous_identity_fail_closed():
    with pytest.raises(ValueError): rank_research_markets([], [], now=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError): prioritize_raw_candidates([{}]*41, [], now=NOW)
    _raw, markets, books = fixture('CONTROLLED-parent', 'a')
    changed = list(markets)
    changed[1] = changed[1].model_copy(update={'resolution_rules': 'CONTROLLED contradiction'})
    with pytest.raises(ValueError, match='ambiguous'):
        rank_research_markets(changed, books, now=NOW)
