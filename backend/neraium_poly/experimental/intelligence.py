"""Descriptive persistent relationship evidence, separate from order authority."""

from datetime import datetime

from neraium_poly.contracts import MarketRelationship, MarketSnapshot, OrderBookSnapshot
from neraium_poly.data.operational import build_statistical_relationships
from neraium_poly.intelligence import EvidenceContext, RelationshipEngine, RelationshipPolicy


class ExperimentalRelationshipIntelligence:
    def __init__(self, max_relationships: int = 200):
        self.engine = RelationshipEngine(
            RelationshipPolicy(max_relationships=max_relationships, max_age_seconds=15)
        )
        self.definitions: dict[str, MarketRelationship] = {}
        self.latest = []
        self.dependency_groups = {}

    def observe(self, markets: dict[str, MarketSnapshot], books: dict[str, OrderBookSnapshot], now: datetime):
        # Only explicit YES contracts support this descriptive same-event prior.
        # Named binary outcomes are not renamed YES, and correlation is no payoff identity.
        observations = {}
        selected = {}
        self.dependency_groups = {}
        for token, market in markets.items():
            self.dependency_groups.setdefault(market.event_id, []).append(market.market_id)
            book = books.get(token)
            if book is None or not book.bids or not book.asks or market.outcome.casefold() != "yes":
                continue
            if (book.market_id, book.token_id, book.exchange) != (market.market_id, token, market.exchange):
                continue
            if market.market_id in selected and selected[market.market_id] != token:
                observations.pop(market.market_id, None)
                continue
            selected[market.market_id] = token
            observations[market.market_id] = market.model_copy(
                update={
                    "id": book.id,
                    "timestamp": book.timestamp,
                    "available_at": max(book.available_at, market.available_at),
                    "source": book.source + ":observed-midpoint",
                    "probability": (book.bids[0].price + book.asks[0].price) / 2,
                }
            )
        generated, _ = build_statistical_relationships(
            tuple(observations.values()), now, max_pairs=self.engine.policy.max_relationships
        )
        active = {r.id for r in generated}
        self.engine.retain(active)
        self.definitions = {k: r for k, r in self.definitions.items() if k in active}
        self.latest = []
        for definition in generated:
            relationship = self.definitions.setdefault(definition.id, definition)
            paired = [observations[mid] for mid in relationship.market_ids]
            pair_books = [books[selected[m.market_id]] for m in paired]
            context = EvidenceContext(
                complete=True,
                liquidity_usd=min(sum(p.price * p.size for p in b.asks) for b in pair_books),
                spread=max(b.asks[0].price - b.bids[0].price for b in pair_books),
                maximum_spread=0.05,
                source="experimental-actual-paired-books/v1",
            )
            self.latest.append(self.engine.observe(relationship, observations, now, context))
        return tuple(self.latest)

    def checkpoint(self):
        return {
            "engine": self.engine.checkpoint(),
            "definitions": [r.model_dump(mode="json") for r in self.definitions.values()],
        }

    def restore(self, data):
        self.engine.restore(data["engine"])
        definitions = [MarketRelationship.model_validate(r) for r in data["definitions"]]
        if len(definitions) > self.engine.policy.max_relationships:
            raise ValueError("relationship capacity exceeded")
        self.definitions = {r.id: r for r in definitions}
        if len(self.definitions) != len(definitions):
            raise ValueError("duplicate relationship definition")

    def status(self):
        return {
            "relationships": len(self.definitions),
            "evaluations": len(self.latest),
            "qualified_descriptive_findings": sum(e.qualified for e in self.latest),
            "logical_payoff_constraints_inferred": 0,
            "dependency_groups": len(self.dependency_groups),
            "independence_reviewed": False,
            "profitability_implication": False,
            "evidence": [e.model_dump(mode="json") for e in self.latest],
        }
