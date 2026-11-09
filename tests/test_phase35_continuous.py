"""Controlled controller fixtures, never authentic research observations."""
from datetime import timedelta

import pytest
from neraium_poly.data import EventStore
from neraium_poly.research.phase24.continuous import DomainResearch, DomainResearchStudy
from neraium_poly.research.phase25.continuous import ExpansionResearch
from neraium_poly.research.phase35.continuous import ScopedStore, WorldWeatherResearch
from test_phase24_integration import NOW, adapter, inputs


async def test_new_namespace_preserves_original_expansion_and_restores_without_duplicates(tmp_path):
    store = EventStore(tmp_path / 'controlled.sqlite')
    _market, _book, evidence, forecast, frame = inputs()
    clock = [NOW]
    make = lambda: adapter(evidence, forecast)
    try:
        original = DomainResearch(store, clock=lambda: clock[0], adapters={'weather': make()})
        expansion = ExpansionResearch(store, clock=lambda: clock[0], adapters={'weather': make()})
        await original.step(frame)
        await expansion.step(frame)
        before = {k: store.latest(k, 100) for k in ('DomainResearchStudy', 'ExpansionResearchStudy')}
        engine = WorldWeatherResearch(store, clock=lambda: clock[0], adapters={'weather': make()})
        assert await engine.step(frame)
        rows = store.latest('WorldWeatherResearchStudy', 100)
        assert len(rows) == 3 and engine.state['forecasts'] == 1
        assert all(r['source'] == 'neraium-poly/world-weather-research/v35' for r in rows)
        assert all(r['research_only'] and not r['trading_authority'] and not r['certification_authority'] for r in rows)
        assert {k: store.latest(k, 100) for k in before} == before
        restored = WorldWeatherResearch(store, clock=lambda: clock[0], adapters={'weather': make()})
        assert restored.state == engine.state
        clock[0] += timedelta(seconds=301)
        assert not await restored.step(frame)
        assert restored.state['forecasts'] == 1
        assert {k: store.latest(k, 100) for k in before} == before
    finally:
        store.close()


async def test_caller_backpressure_and_book_provider_are_preserved(tmp_path):
    store = EventStore(tmp_path / 'controlled.sqlite')
    _market, book, evidence, forecast, frame = inputs()
    requests = []
    allowed = [False]

    async def provider(market):
        requests.append(market.token_id)
        return book

    try:
        engine = WorldWeatherResearch(store, clock=lambda: NOW, can_write=lambda: allowed[0],
                                      book_provider=provider, adapters={'weather': adapter(evidence, forecast)})
        assert not await engine.step(frame)
        assert store.count(kind='WorldWeatherResearchStudy') == 0
        allowed[0] = True
        raw = frame.model_dump(mode='json')
        raw['books'] = []
        assert await engine.step(raw)
        assert requests == [book.token_id]
        assert engine.status()['trading_authority'] is False
    finally:
        store.close()


def test_default_new_models_do_not_modify_legacy_registry_and_reject_unrelated_records(tmp_path):
    store = EventStore(tmp_path / 'controlled.sqlite')
    try:
        engine = WorldWeatherResearch(store, clock=lambda: NOW)
        assert {d['model_id'] for d in engine.definitions} == {
            'awc-calendar-frequency-v35.1', 'awc-jeffreys-frequency-v35.1'}
        assert ScopedStore(store).latest('DomainOutcomeStudy') == []
        with pytest.raises(TypeError, match='unrelated record'):
            ScopedStore(store).append(object())
        assert issubclass(type(engine), DomainResearch)
        assert engine.store.underlying is store
        assert DomainResearchStudy.__name__ == 'DomainResearchStudy'
    finally:
        store.close()
