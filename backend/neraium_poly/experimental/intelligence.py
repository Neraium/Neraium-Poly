"""Descriptive persistent relationship evidence, separate from order authority."""

from datetime import datetime

from neraium_poly.contracts import MarketRelationship, MarketSnapshot, OrderBookSnapshot
from neraium_poly.data import assess_book
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
        # Metadata defines bounded pair membership only. A transient missing
        # quote must not delete an already observed temporal baseline.
        eligible = [
            market
            for token, market in markets.items()
            if token == market.token_id
            and market.timestamp <= now
            and market.available_at <= now
            and market.status == "active"
            and market.resolution_rules
            and market.resolution_source
            and (market.end_time is None or market.end_time > now)
        ]
        generated, selected = build_statistical_relationships(
            eligible, now, max_pairs=self.engine.policy.max_relationships
        )
        observations = {}
        self.dependency_groups = {}
        for market in eligible:
            self.dependency_groups.setdefault(market.event_id, []).append(market.market_id)
            token = market.token_id
            if selected.get(market.market_id) != token:
                continue
            book = books.get(token)
            if not assess_book(book, now, max_spread=0.05, expected_token=token).healthy:
                continue
            if (book.market_id, book.token_id, book.exchange) != (market.market_id, token, market.exchange):
                continue
            observations[market.market_id] = market.model_copy(
                update={
                    "id": book.id,
                    "timestamp": book.timestamp,
                    "available_at": max(book.available_at, market.available_at),
                    "source": book.source + ":observed-midpoint",
                    "probability": (book.bids[0].price + book.asks[0].price) / 2,
                }
            )
        active = {r.id for r in generated}
        self.engine.retain(active)
        self.definitions = {k: r for k, r in self.definitions.items() if k in active}
        self.latest = []
        for definition in generated:
            relationship = self.definitions.setdefault(definition.id, definition)
            # No metadata probability, cached finding, or partial pair can be
            # emitted as a new observation. On return the temporal engine still
            # enforces its existing 120-second persistence-gap reset.
            if any(mid not in observations for mid in relationship.market_ids):
                continue
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
