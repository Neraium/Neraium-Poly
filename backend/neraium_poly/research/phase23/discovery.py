"""Bounded category/parent discovery; never probability or admission authority."""

import base64
import gzip
import hashlib
import io
import json
import math
import re
from collections import Counter, defaultdict, deque
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from neraium_poly.contracts import MarketSnapshot, Record
from neraium_poly.data import assess_book
from neraium_poly.data.polymarket import GAMMA, normalize_market, timestamp
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.discovery import TAG_SLUGS, classify_market, classify_snapshot
from neraium_poly.research.phase18.forecasting import map_event_contract
from neraium_poly.research.phase19.collection import PriorityIdentityError, assert_same_contract
from pydantic import Field

MAX_REQUESTS = 28
MAX_CANDIDATES = 2000
MAX_EVIDENCE_BYTES = 24 * 1024**2


class DiscoveryIntelligenceStudy(Record):
    provenance: list[dict] = Field(default_factory=list)
    classifications: list[dict] = Field(default_factory=list)
    report: dict = Field(default_factory=dict)
    trading_authority: bool = False
    certification_authority: bool = False


def replay_discovery_payload(proof):
    """Restore bounded newly collected evidence; historical originals untouched."""
    size = proof['canonical_bytes']
    if type(size) is not int or not 0 < size <= MAX_EVIDENCE_BYTES:
        raise ValueError('bounded metadata proof size required')
    encoded = proof['payload_gzip_base64']
    if not isinstance(encoded, str) or len(encoded) > MAX_EVIDENCE_BYTES*2:
        raise ValueError('bounded compressed evidence required')
    try:
        compressed = base64.b64decode(encoded, validate=True)
        if hashlib.sha256(compressed).hexdigest() != proof['gzip_sha256']:
            raise ValueError('compressed evidence hash mismatch')
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
            restored = stream.read(size+1)
        if len(restored) != size or hashlib.sha256(restored).hexdigest() != proof['canonical_payload_sha256']:
            raise ValueError('metadata evidence hash or length mismatch')
        return json.loads(restored)
    except (OSError, EOFError, TypeError, KeyError, UnicodeError) as error:
        raise ValueError('invalid compressed metadata evidence') from error


def _number(value):
    try:
        n = float(value)
        return n if not isinstance(value, bool) and math.isfinite(n) and n >= 0 else 0.
    except (ValueError, TypeError, OverflowError):
        return 0.


def _time(now):
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('aware discovery cutoff required')
    return now.astimezone(UTC)


def select_diverse(candidates, *, books, now, max_markets, max_tokens):
    """Balance domains then parents; order each parent using causal quality.

    Unknown independent evidence/performance remain unknown. Quote data only
    prioritizes collection; it never generates an independent forecast.
    """
    now = _time(now)
    if (type(max_markets) is not int or not 1 <= max_markets <= 500
        or type(max_tokens) is not int or not 2 <= max_tokens <= 2000
        or not isinstance(candidates, list) or len(candidates) > MAX_CANDIDATES):
        raise ValueError('bounded research universe required')
    tokens, markets, grouped = {}, set(), defaultdict(lambda: defaultdict(list))
    for item in candidates:
        records = tuple(MarketSnapshot.model_validate(x) for x in item['markets'])
        if not records:
            raise ValueError('outcome records required')
        m = records[0]
        identities = {tuple(getattr(r, k) for k in ('exchange', 'event_id', 'market_id', 'question',
            'resolution_rules', 'resolution_source', 'end_time')) for r in records}
        if (len(identities) != 1 or len({r.token_id for r in records}) != len(records)
            or m.market_id in markets or any(r.timestamp > now or r.available_at > now for r in records)):
            raise ValueError('ambiguous or future discovery identity')
        if any(r.status != 'active' for r in records) or (m.end_time is not None and m.end_time <= now):
            continue
        for r in records:
            if r.token_id in tokens and tokens[r.token_id] != m.market_id:
                raise ValueError('token bound to conflicting markets')
            tokens[r.token_id] = m.market_id
        markets.add(m.market_id)
        classification = item.get('classification')
        domain = classification['domain'] if classification else classify_snapshot(m, now).domain
        metadata = classification.get('metadata', {}) if classification else {}
        depths, spreads = [], []
        for r in records:
            b = books.get(r.token_id)
            if (b is not None and b.market_id == r.market_id and b.exchange == r.exchange
                and b.source in PUBLIC_BOOK_SOURCES and assess_book(b, now, expected_token=r.token_id).healthy):
                depths.append(min(sum(p.price*p.size for p in b.bids[:3]), sum(p.price*p.size for p in b.asks[:3])))
                spreads.append(b.asks[0].price-b.bids[0].price)
        supported = any(map_event_contract(r, now=now).compatible for r in records)
        future_rule_supported = False
        if m.end_time and now < m.end_time <= now+timedelta(hours=72):
            start = m.end_time.astimezone(ZoneInfo('America/New_York'))-timedelta(days=1)
            if start > now:
                # Interpret already observed rules at their future window start;
                # no future data, features or forecast is acquired or invented.
                future_rule_supported = any(map_event_contract(r, now=start).compatible for r in records)
        nfl_hint = m.resolution_source.rstrip('/') == 'https://www.nfl.com/scores' and bool(re.fullmatch(r'[^:()]+ vs\. [^:()]+', m.question))
        horizon = (m.end_time-now).total_seconds() if m.end_time else None
        row = {'market_id': m.market_id, 'parent_event': m.event_id, 'domain': domain,
            'classification_basis': classification['classification_basis'] if classification else 'normalized_source_projection',
            'source_record_ids': [r.id for r in records], 'source_available_at': max(r.available_at for r in records).isoformat(),
            'fresh_book_tokens': len(depths), 'top3_two_sided_depth_usd': max(depths) if depths else None,
            'spread': min(spreads) if spreads else None, 'metadata_liquidity_usd': metadata.get('liquidity_usd'),
            'metadata_volume24h_usd': metadata.get('volume_24h_usd'), 'horizon_seconds': horizon,
            'near_term': horizon is not None and 0 < horizon <= 86400,
            'exact_rule_model_supported': supported, 'future_daily_rule_adapter': future_rule_supported,
            'nfl_mapping_candidate_requires_qualified_schedule': nfl_hint, 'independent_evidence_available': None,
            'historical_model_performance': None, 'event_independence_reviewed': False,
            'forecast_qualified': False, 'trading_authority': False}
        key = (not bool(depths), not (supported or future_rule_supported or nfl_hint), not bool(m.resolution_rules and m.resolution_source),
            not row['near_term'], -(max(depths) if depths else 0), min(spreads) if spreads else 1.,
            -_number(metadata.get('liquidity_usd')), -_number(metadata.get('volume_24h_usd')), m.market_id)
        grouped[domain][m.event_id].append((key, records, row))
    queues = {}
    for domain, parents in grouped.items():
        parents = {p: deque(sorted(items, key=lambda x: x[0])) for p, items in parents.items()}
        ordered = deque()
        while parents:
            for parent in sorted(parents, key=lambda p: parents[p][0][0]):
                ordered.append(parents[parent].popleft())
                if not parents[parent]:
                    del parents[parent]
        queues[domain] = ordered
    selected, token_count = [], 0
    while queues and len(selected) < max_markets:
        for domain in sorted(queues):
            _key, records, row = queues[domain].popleft()
            if token_count+len(records) <= max_tokens:
                selected.append((records, row));token_count += len(records)
            if not queues[domain]:
                del queues[domain]
            if len(selected) >= max_markets:
                break
    rows = [row for _, row in selected]
    return tuple(r for records, _ in selected for r in records), {
        'selected_markets': len(selected), 'selected_tokens': token_count,
        'category_distribution': dict(Counter(row['domain'] for row in rows)),
        'parent_events': len({row['parent_event'] for row in rows}), 'markets': rows,
        'selection': 'domain then parent round robin; causal executable quality, supported rules, horizon and metadata liquidity',
        'scope': 'collection only; parent diversity is not event independence; actual taxonomy/source hosts only',
        'trading_authority': False, 'certification_authority': False}


async def augment_diverse(coordinator, batch):
    """Use shared public rate limiting; at most28 GETs and24MiB evidence per cycle."""
    adapter, clock = coordinator.adapter, coordinator.clock
    tags = dict(coordinator.ledger.get('phase23_discovery', {}).get('tags', {}))
    provenance, errors, candidates = [], Counter(), {}
    requests = evidence_bytes = 0
    reserve = 2*coordinator.config.forecast_priority_market_limit if coordinator.config.forecast_discovery_enabled else 0
    max_tokens = coordinator.config.max_subscription_tokens-reserve
    async def read(path, params=None):
        nonlocal requests, evidence_bytes
        if requests >= MAX_REQUESTS:
            raise ValueError('discovery_request_budget')
        requests += 1
        raw = await adapter._get(GAMMA, path, params)
        observed = _time(clock());body = json.dumps(raw, sort_keys=True, separators=(',', ':'), allow_nan=False)
        if evidence_bytes+len(body.encode()) > MAX_EVIDENCE_BYTES:
            raise ValueError('discovery_evidence_byte_budget')
        evidence_bytes += len(body.encode())
        compressed = gzip.compress(body.encode(), mtime=0)
        proof = {'source': GAMMA+path, 'params': params or {}, 'received_at': observed.isoformat(),
            'available_at': observed.isoformat(), 'canonical_payload_sha256': hashlib.sha256(body.encode()).hexdigest(),
            'hash_semantics': 'canonical JSON, not original HTTP bytes', 'canonical_bytes': len(body.encode()),
            'payload_gzip_base64': base64.b64encode(compressed).decode(),
            'gzip_sha256': hashlib.sha256(compressed).hexdigest(),
            'retention_format': 'lossless compressed newly collected evidence; no existing original modified'}
        if replay_discovery_payload(proof) != raw:
            raise ValueError('independent immediate evidence restoration mismatch')
        provenance.append(proof)
        return raw, observed
    def accept_events(rows, observed):
        added = 0
        if not isinstance(rows, list) or len(rows) > 8:
            raise ValueError('bounded_event_page_required')
        for event in rows:
            if not isinstance(event, dict) or not event.get('id'):
                errors['invalid_event'] += 1;continue
            markets = event.get('markets', [])
            if not isinstance(markets, list) or len(markets) > 1000:
                errors['bounded_event_markets_required'] += 1;continue
            event_added = 0
            for raw in markets:
                if (added >= 120 or event_added >= 32
                    or len(candidates) >= MAX_CANDIDATES-coordinator.config.max_markets):
                    break
                if not isinstance(raw, dict) or raw.get('enableOrderBook') is False or raw.get('acceptingOrders') is False:
                    continue
                if raw.get('eventId') is not None and str(raw['eventId']) != str(event['id']):
                    errors['contradictory_parent_event'] += 1;continue
                merged = {**raw, 'eventId': event['id'], 'events': [{'id': event['id'],
                    'tags': event.get('tags', []), 'category': event.get('category')}]}
                try:
                    records = normalize_market(merged, observed);c = classify_market(merged, observed)
                    if any(r.status != 'active' for r in records):
                        continue
                    prior = candidates.get(records[0].market_id)
                    identity = lambda items: {tuple(getattr(r, k) for k in ('exchange', 'market_id', 'event_id', 'token_id', 'outcome', 'question', 'resolution_rules', 'resolution_source', 'end_time')) for r in items}
                    if prior and identity(prior['markets']) != identity(records):
                        raise PriorityIdentityError('contradictory_event_market_identity')
                    candidates[records[0].market_id] = {'markets': records, 'classification': c.model_dump(mode='json')}
                    if prior is None:
                        added += 1;event_added += 1
                except PriorityIdentityError:
                    raise
                except (ValueError, TypeError, KeyError) as error:
                    reason = str(error)
                    label = ('incomplete_outcome_identifiers_or_prices' if 'incomplete outcome' in reason else
                             'missing_market_event_identity' if 'missing market/event' in reason else
                             'invalid_market_schema')
                    errors[label] += 1
    # Generic sports near-term queries are dominated by unsupported leagues.
    # Resolve an actual NFL tag, then retain upcoming official-source moneylines.
    try:
        if 'nfl' not in tags:
            raw, _ = await read('/tags/slug/nfl')
            if not isinstance(raw, dict) or raw.get('slug') != 'nfl' or not raw.get('id'):
                raise ValueError('verified_nfl_tag_required')
            tags['nfl'] = {'id': str(raw['id']), 'slug': 'nfl'}
        cursor, deadline = clock(), clock()+timedelta(hours=72)
        for _ in range(3):
            rows, observed = await read('/events', {'tag_id': tags['nfl']['id'], 'active': 'true',
                'closed': 'false', 'limit': 3, 'order': 'endDate', 'ascending': 'true',
                'end_date_min': cursor.isoformat(), 'end_date_max': deadline.isoformat()})
            accept_events(rows, observed)
            ends = [timestamp(e['endDate']) for e in rows if e.get('endDate')]
            if not ends or max(ends) <= cursor:
                break
            # Skip the completed scheduling band, not just individual prop IDs:
            # numerous related prop events must not monopolize all requests.
            cursor = max(ends)+timedelta(microseconds=1)
            if cursor >= deadline:
                break
    except PriorityIdentityError:
        raise
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
        errors['nfl_'+type(error).__name__] += 1
    tomorrow = clock().astimezone(ZoneInfo('America/New_York'))+timedelta(days=1)
    for asset in ('bitcoin', 'ethereum'):
        slug = f"what-price-will-{asset}-hit-on-{tomorrow.strftime('%B').lower()}-{tomorrow.day}-{tomorrow.year}"
        try:
            rows, observed = await read('/events', {'slug': slug})
            if not isinstance(rows, list) or len(rows) > 4 or any(e.get('slug') != slug for e in rows):
                raise ValueError('exact_future_slug_identity_required')
            if not rows:
                errors['future_exact_event_unavailable'] += 1
            accept_events(rows, observed)
        except PriorityIdentityError:
            raise
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
            errors['future_'+type(error).__name__] += 1
    for domain, slugs in TAG_SLUGS.items():
        if requests >= MAX_REQUESTS:
            break
        try:
            if domain not in tags:
                raw, _ = await read('/tags/slug/'+slugs[0])
                if not isinstance(raw, dict) or not raw.get('id') or raw.get('slug') not in slugs:
                    errors['unverified_tag_identity'] += 1;continue
                tags[domain] = {'id': str(raw['id']), 'slug': raw['slug']}
            rows, observed = await read('/events', {'tag_id': tags[domain]['id'], 'active': 'true',
                'closed': 'false', 'limit': 8, 'order': 'volume24hr', 'ascending': 'false'})
            accept_events(rows, observed)
        except PriorityIdentityError:
            raise
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
            errors[type(error).__name__] += 1
    for market in batch.markets:
        key = market.market_id
        if key not in candidates:
            candidates[key] = {'markets': [], 'classification': None}
        if candidates[key]['classification'] is None:
            candidates[key]['markets'].append(market)
    if len(candidates) > MAX_CANDIDATES:
        raise ValueError('candidate_budget')
    by_token = {r.token_id: r for c in candidates.values() for r in c['markets']}
    for old in batch.markets:
        if old.token_id in by_token:
            assert_same_contract(old, by_token[old.token_id])
    selected, report = select_diverse(list(candidates.values()), books=coordinator.books,
        now=clock(), max_markets=coordinator.config.max_markets, max_tokens=max_tokens)
    report.update(status='research_collection_only', candidate_markets=len(candidates), requests=requests,
        evidence_bytes=evidence_bytes, stored_compressed_bytes=sum(len(p['payload_gzip_base64']) for p in provenance), errors=dict(errors), max_requests=MAX_REQUESTS, max_evidence_bytes=MAX_EVIDENCE_BYTES,
        selected_limit=coordinator.config.max_markets, subscription_limit=max_tokens,
        candidate_limits={'per_query':120,'per_event':32,'total':MAX_CANDIDATES}, observed_at=clock().isoformat())
    study = DiscoveryIntelligenceStudy(id=hashlib.sha256(json.dumps([report, provenance], sort_keys=True).encode()).hexdigest(),
        timestamp=clock(), available_at=clock(), source='neraium-poly/discovery-intelligence/v23', provenance=provenance,
        classifications=[c['classification'] for c in candidates.values() if c['classification']], report=report)
    coordinator.events.append(study)
    coordinator.ledger.put('phase23_discovery', {'tags': tags, 'latest_study_id': study.id})
    base_ids = {m.market_id for m in batch.markets}
    return replace(batch, markets=selected, scanned_count=batch.scanned_count+len(set(candidates)-base_ids),
        errors=batch.errors+tuple('phase23:'+k+':'+str(v) for k,v in errors.items())), report
