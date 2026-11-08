"""Prospective payout hypotheses with deterministic enrollment/horizon identity."""
import json
from collections import Counter
from typing import Literal

from pydantic import Field

from neraium_poly.contracts import Record
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25.dependencies import at


class PayoutForecastStudy(Record):
    enrollment_id: str
    enrollment: list = Field(default_factory=list)
    original_study_id: str
    original_study_sha256: str
    horizon: str
    forecasts: list = Field(default_factory=list)
    research_only: Literal[True] = True
    trading_authority: Literal[False] = False


def propose_spx(studies, frame, *, store, enrollment_id, as_of, verified_forecast_ids, adapter=None, clock=None):
    if adapter is None:
        from . import forecasting as adapter
    now = at(as_of)
    raw = frame.model_dump(mode='json') if hasattr(frame, 'model_dump') else frame
    markets = {m['token_id']: m for m in raw['markets']}
    books = {b['token_id']: b for b in raw['books']}
    candidates = {}; results = []; reasons = Counter()
    for study in studies:
        for f in study.get('forecasts', []):
            if f['id'] not in verified_forecast_ids or not f.get('model_id', '').startswith('spx-'):
                continue
            key = (f['event_id'], f['market_id'], f['token_id'])
            if key not in candidates or f['id'] < candidates[key][1]['id']:
                candidates[key] = study, f
    definitions = adapter.definitions()
    for study, f in candidates.values():
        hours = (at(f['event_end_time'])-now).total_seconds()/3600
        if hours <= 0:
            reasons['payout_target_not_future'] += 1
            continue
        horizon = 'beyond48h' if hours > 48 else '48h' if hours > 24 else '24h' if hours > 6 else '6h' if hours > 1 else '1h'
        identity = digest(['payout-prospective', enrollment_id, adapter.BASELINE_MODEL, f['event_id'], f['market_id'], f['token_id'], horizon])
        existing = store.get(identity)
        if existing is not None:
            value = existing if isinstance(existing, dict) else json.loads(existing[1])
            record = PayoutForecastStudy.model_validate(value)
            if (record.enrollment_id != enrollment_id or record.trading_authority or record.horizon != horizon
                    or record.original_study_id != study['id'] or record.original_study_sha256 != digest(study)
                    or at(record.available_at) > now):
                raise ValueError('prospective payout recovery binding mismatch')
            if len(record.forecasts) != 1:
                raise ValueError('unique original prospective payout required')
            proof = adapter.replay_spx_payout(record.forecasts[0], study, f, as_of=now)
            if not isinstance(proof, dict) or proof.get('verified') is not True:
                raise ValueError('recovered payout source/model replay required')
            results.append(record.model_dump(mode='json'))
            continue
        if f['token_id'] not in markets or f['token_id'] not in books:
            reasons['payout_current_market_or_book_missing'] += 1
            continue
        try:
            estimate = adapter.derive_spx_payout(study, f, market=markets[f['token_id']], book=books[f['token_id']], cutoff=now, model_id=adapter.BASELINE_MODEL)
            proof = adapter.replay_spx_payout(estimate, study, f, as_of=now)
            if not isinstance(proof, dict) or proof.get('verified') is not True:
                raise ValueError('new payout model/source replay required')
            if at(estimate['timestamp']) != now:
                raise ValueError('prospective payout timestamp differs from generation')
            completed = at(clock()) if clock is not None else now
            if completed < now or completed >= at(estimate['contract']['period_start']):
                raise ValueError('payout_generation_not_available_before_event_start')
            record = PayoutForecastStudy(id=identity, timestamp=now, available_at=completed,
                source='neraium-poly/payout-research/v27', enrollment_id=enrollment_id,
                enrollment=definitions, original_study_id=study['id'], original_study_sha256=digest(study),
                horizon=horizon, forecasts=[estimate])
            store.append(record)
            results.append(record.model_dump(mode='json'))
        except (ValueError, TypeError, KeyError, StopIteration) as error:
            reasons[str(error)[:160]] += 1
    return results, dict(reasons)
