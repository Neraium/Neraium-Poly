"""A separate immutable weather enrollment using the existing domain controller."""
from pathlib import Path
from types import SimpleNamespace

from neraium_poly.research.phase24.archive import latest
from neraium_poly.research.phase24.continuous import DomainResearch, DomainResearchStudy
from neraium_poly.research.phase25.continuous import SourceAdapter

from . import weather


class WorldWeatherResearchStudy(DomainResearchStudy):
    """New challengers only; frozen original and expansion journals stay intact."""


class ScopedStore:
    def __init__(self, store):
        self.underlying = store

    def latest(self, kind, limit=100):
        return latest(self.underlying, 'WorldWeatherResearchStudy', limit=limit) if kind == 'DomainResearchStudy' else []

    def get(self, identity):
        return self.underlying.get(identity)

    def append(self, record):
        if not isinstance(record, DomainResearchStudy):
            raise TypeError('world weather namespace rejects unrelated record')
        row = WorldWeatherResearchStudy.model_validate(record.model_dump()).model_copy(
            update={'source': 'neraium-poly/world-weather-research/v35'})
        return self.underlying.append(row)


class WorldWeatherResearch(DomainResearch):
    """Reuse bounded scheduling, durable checkpoints and source/book validation.

    Caller supplies existing archive budget admission, clock and optional book
    provider. No new database, outcome authority, risk gate or order path exists.
    """

    def __init__(self, store, *, adapters=None, **kwargs):
        selected = {name: SourceAdapter(module) for name, module in
                    ({'weather': weather} if adapters is None else adapters).items()}
        selected['_integration_policy'] = SimpleNamespace(
            __file__=str(Path(__file__)), definitions=list,
            supports=lambda *args, **kw: {'supported': False, 'reasons': []})
        super().__init__(ScopedStore(store), adapters=selected, **kwargs)
