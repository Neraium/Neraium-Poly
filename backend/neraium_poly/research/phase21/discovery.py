"""Causal collection priority, not forecast qualification or trading authority.

Fresh native liquidity, exact supported rules and parent coverage outrank quoted
volume. Existing subscriptions/capital protection remain the collector's concern.
A provider adapter's availability never certifies its inputs or probabilities.
"""

from collections import Counter, defaultdict, deque
from datetime import UTC, datetime
from math import isfinite

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.data.polymarket import normalize_market
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.discovery import classify_snapshot
from neraium_poly.research.phase18.forecasting import MODEL_VERSION, map_event_contract


def _time(now):
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('aware research priority cutoff required')
    return now.astimezone(UTC)


def rank_research_markets(markets, books, *, now):
    """Describe current research suitability without creating independent evidence.

    The model registry currently contains exactly the unchanged daily-low crypto
    research model. Other categories remain discoverable with explicit blockers.
    One parent receives one admission per round; a parent ID is NOT a reviewed
    independence group. Longer horizons are ranked after near-term contracts,
    not removed. No input record is altered and no external request is made.
    """
    now = _time(now)
    if not isinstance(markets, (tuple, list)) or not isinstance(books, (tuple, list)) or len(markets) > 1000 or len(books) > 2000:
        raise ValueError('bounded research priority observations required')
    grouped, by_token, duplicates = defaultdict(list), {}, set()
    for raw in markets:
        market = raw if isinstance(raw, MarketSnapshot) else MarketSnapshot.model_validate(raw)
        grouped[market.market_id].append(market)
    for raw in books:
        book = raw if isinstance(raw, OrderBookSnapshot) else OrderBookSnapshot.model_validate(raw)
        if book.token_id in by_token:
            duplicates.add(book.token_id)
        by_token[book.token_id] = book
    rows = []
    for market_id, records in grouped.items():
        events = {m.event_id for m in records}
        tokens = {m.token_id for m in records}
        identities = {tuple(getattr(m, k) for k in ('exchange', 'event_id', 'question', 'resolution_rules', 'resolution_source', 'end_time', 'status')) for m in records}
        if len(events) != 1 or len(tokens) != len(records) or len(identities) != 1:
            raise ValueError('ambiguous priority market/event/token identity')
        m = min(records, key=lambda r: r.token_id)
        classified = classify_snapshot(m, now)
        contracts = [map_event_contract(record, now=now) for record in records]
        supported = all(contract.compatible and not contract.review_required and contract.contract_type == 'binance_daily_low_barrier' for contract in contracts)
        reasons = Counter()
        if not supported:
            reasons.update({reason for contract in contracts for reason in contract.reasons} or ('independent_probability_model_unavailable',))
        if not m.resolution_rules.strip() or not m.resolution_source:
            reasons['exact_resolution_rules_and_source_required'] += 1
        horizon = (m.end_time-now).total_seconds() if m.end_time else None
        if horizon is None or horizon <= 0 or m.status != 'active':
            reasons['active_future_settlement_window_required'] += 1
        healthy, depth, entry_capacity, spreads, source_times = [], 0., 0., [], []
        for record in records:
            book = by_token.get(record.token_id)
            if record.token_id in duplicates:
                reasons['duplicate_native_token_observation'] += 1
                continue
            if book is None:
                reasons['missing_order_book'] += 1
                continue
            if book.source not in PUBLIC_BOOK_SOURCES or book.exchange != record.exchange or book.market_id != market_id:
                reasons['native_book_identity_or_source_mismatch'] += 1
                continue
            health = assess_book(book, now, max_spread=.05, expected_token=record.token_id)
            if not health.healthy:
                reasons.update(health.reasons)
                continue
            healthy.append(record.token_id)
            source_times.append(book.timestamp.isoformat())
            spreads.append(health.spread)
            # Conservative top-three observed depth, never an inferred whole book.
            bids = sum(p.price*p.size for p in book.bids[:3])
            asks = sum(p.price*p.size for p in book.asks[:3])
            depth = max(depth, min(bids, asks))
            principal = sum(p.price*p.size*.25 for p in book.asks[:3])
            shares = sum(p.size*.25 for p in book.asks[:3])
            if shares+1e-12 >= record.min_order_size:
                entry_capacity = max(entry_capacity, principal)
        if not healthy:
            reasons['fresh_two_sided_native_book_required'] += 1
        if entry_capacity+1e-12 < 2:
            reasons['standard_minimum_notional_or_lot_depth_unavailable'] += 1
        if depth*.25+1e-12 < 2:
            reasons['two_sided_standard_notional_depth_unavailable'] += 1
        ready = supported and bool(healthy) and horizon is not None and horizon > 0 and entry_capacity+1e-12 >= 2 and depth*.25+1e-12 >= 2
        tier = 0 if ready else 1 if supported and healthy else 2 if supported else 3
        rows.append({'market_id': market_id, 'event_id': m.event_id, 'domain': classified.domain,
            'classification_basis': classified.classification_basis,
            'source_record_ids': [r.id for r in records], 'source_timestamps': source_times,
            'settlement_at': m.end_time.isoformat() if m.end_time else None,
            'settlement_horizon_seconds': horizon, 'near_term': horizon is not None and 0 < horizon <= 86400,
            'supported_research_model': MODEL_VERSION if supported else None,
            'external_input_status': 'collector_available_inputs_unverified' if supported else 'qualified_adapter_or_model_unavailable',
            'calibration_status': 'unvalidated_research' if supported else 'unavailable',
            'healthy_token_ids': healthy, 'minimum_observed_spread': min(spreads) if spreads else None,
            'observed_top3_two_sided_depth_usd': depth, 'observed_top3_entry_principal_at25percent': entry_capacity,
            'priority_ready': ready, 'priority_tier': tier, 'rejections': dict(reasons),
            'event_independence_reviewed': False, 'forecast_qualified': False, 'trading_authority': False})
    def key(row):
        horizon = row['settlement_horizon_seconds']
        return (row['priority_tier'], not row['near_term'],
            horizon if horizon is not None and isfinite(horizon) and horizon > 0 else float('inf'),
            -row['observed_top3_two_sided_depth_usd'], row['market_id'])
    # Breadth is enforced between parents in the same readiness tier, not by
    # promoting unsupported/illiquid contracts ahead of a genuinely ready one.
    ordered = []
    for tier in sorted({r['priority_tier'] for r in rows}):
        parents = defaultdict(list)
        for row in rows:
            if row['priority_tier'] == tier:
                parents[row['event_id']].append(row)
        queues = {parent: deque(sorted(values, key=key)) for parent, values in parents.items()}
        while queues:
            for parent in sorted(queues, key=lambda p: key(queues[p][0])):
                ordered.append(queues[parent].popleft())
                if not queues[parent]:
                    del queues[parent]
    return {'schema_version': 'phase21-research-priority-v1', 'evaluated_at': now.isoformat(),
        'markets': ordered, 'market_count': len(rows), 'parent_events': len({r['event_id'] for r in rows}),
        'priority_ready_markets': sum(r['priority_ready'] for r in rows),
        'priority_ready_parent_events': len({r['event_id'] for r in rows if r['priority_ready']}),
        'domain_distribution': dict(Counter(r['domain'] for r in rows)),
        'domain_distribution_scope': 'normalized metadata projection; unavailable structured tags are not invented; other includes unclassified',
        'selection_scope': 'collection only; parent diversity is not event independence or forecasting skill',
        'trading_authority': False, 'certification_authority': False}


def prioritize_raw_candidates(raw_markets, books, *, now):
    """Order existing bounded native candidates; do not filter their audit inputs."""
    if not isinstance(raw_markets, list) or len(raw_markets) > 40:
        raise ValueError('bounded native priority candidates required')
    normalized = [m for raw in raw_markets for m in normalize_market(raw, now)]
    report = rank_research_markets(normalized, books, now=now)
    ranks = {r['market_id']: i for i, r in enumerate(report['markets'])}
    return sorted(raw_markets, key=lambda raw: ranks[str(raw['id'])]), report
