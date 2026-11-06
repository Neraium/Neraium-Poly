"""Source-bound shared-parent statistical research; never logical/trade authority."""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from copy import deepcopy
from itertools import combinations

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.research.phase14.discovery import classify_snapshot
from neraium_poly.research.phase14.relationships import (
    DOMAINS,
    UniversalRelationships,
    _time,
    digest,
)

METADATA_SOURCE = "https://gamma-api.polymarket.com"
BOOK_SOURCES = {"https://clob.polymarket.com", "wss://ws-subscriptions-clob.polymarket.com/ws/market"}
SEMANTICS = "order_book_midpoint_USD_per_outcome_share_not_independent_probability"


def _semantic(market):
    return {**{key: getattr(market, key) for key in (
        "exchange", "market_id", "event_id", "question", "token_id", "outcome",
        "resolution_rules", "resolution_source")},
        "end_time": market.end_time.isoformat() if market.end_time else None}


class RelationshipResearch:
    """Bounded explicit graph with source-replayed quote provenance.

    The machine reviewer proves ONLY distinct YES contracts share a metadata
    parent. It does not review payoff exhaustiveness, causality, economic value,
    independence, or human approval. Persist/replay source frames separately.
    """

    def __init__(self, *, max_pairs=3):
        if type(max_pairs) is not int or not 1 <= max_pairs <= 20:
            raise ValueError("bounded_relationship_pair_budget_required")
        self.max_pairs = max_pairs
        self.definitions, self.proofs, self.current, self.raw_current = {}, {}, {}, {}
        self.rejections, self.statuses = Counter(), Counter()
        self.cycles, self.candidate_pairs, self.last_at = 0, 0, None
        self.engine = UniversalRelationships(definition_validator=self._review_definition,
            observation_validator=self._review_observation, max_links=max_pairs)

    def _review_definition(self, definition):
        proof = self.proofs.get(definition.get("id"))
        if not proof or definition != self.definitions.get(definition["id"]):
            return False
        left, right = (MarketSnapshot.model_validate(raw) for raw in proof)
        return (definition.get("kind") == "statistical_relationship"
            and definition.get("review_actor") == "machine:shared-parent-source-proof-v1"
            and definition.get("review_scope") == "shared_parent_statistical_eligibility_only"
            and left.market_id != right.market_id and left.token_id != right.token_id
            and left.event_id == right.event_id == definition.get("parent_event_id")
            and left.outcome.casefold() == right.outcome.casefold() == "yes"
            and left.source == right.source == METADATA_SOURCE
            and definition.get("left_id") == left.token_id and definition.get("right_id") == right.token_id
            and definition.get("left_market_id") == left.market_id and definition.get("right_market_id") == right.market_id
            and definition.get("id") == digest(["shared-parent-statistical-v1", left.event_id, left.market_id, right.market_id])
            and definition.get("minimum_residual") == .01 and definition.get("relation_type") == "linear_dependency"
            and max(left.available_at, right.available_at) <= _time(definition["available_at"])
            and definition.get("left_domain") == classify_snapshot(left, now=_time(definition["available_at"])).domain
            and definition.get("right_domain") == classify_snapshot(right, now=_time(definition["available_at"])).domain
            and definition.get("metadata_sha256") == [digest(raw) for raw in proof]
            and definition.get("semantic_sha256") == [digest(_semantic(left)), digest(_semantic(right))])

    def _review_observation(self, observation):
        proof = self.current.get(observation.get("entity_id"))
        if not proof:
            return False
        market, book = proof
        raw_market, raw_book = self.raw_current[market.token_id]
        semantic_hash, quote_hash = digest(_semantic(market)), digest(raw_book)
        return (observation.get("semantics") == SEMANTICS
            and observation.get("evidence_sha256") == digest([quote_hash, semantic_hash])
            and observation.get("quote_sha256") == quote_hash
            and observation.get("metadata_sha256") == digest(raw_market)
            and observation.get("value") == (book.bids[0].price + book.asks[0].price)/2
            and observation.get("uncertainty") == {"absolute_error_bound": (book.asks[0].price-book.bids[0].price)/2}
            and observation.get("source") == book.source
            and observation.get("timestamp") == book.timestamp.isoformat()
            and observation.get("available_at") == book.available_at.isoformat())

    def _reject(self, reason):
        reason = reason if reason in self.rejections or len(self.rejections) < 32 else "other_bounded_rejection"
        self.rejections[reason] += 1

    def observe(self, frame, *, observed_at):
        now = _time(observed_at)
        if self.last_at is not None and now <= _time(self.last_at):
            self._reject("non_increasing_research_cycle")
            return {"status": "withheld", "reason": "non_increasing_research_cycle", **self.summary()}
        if (not isinstance(frame, dict) or not isinstance(frame.get("markets"), list)
                or not isinstance(frame.get("books"), list)
                or len(frame["markets"]) > 1000 or len(frame["books"]) > 2000
                or len(json.dumps(frame, allow_nan=False)) > 8 * 1024**2):
            raise ValueError("bounded_market_frame_required")
        self.cycles += 1
        self.last_at = now.isoformat()
        self.current, self.raw_current = {}, {}
        books, raw_books, duplicates = {}, {}, set()
        for raw in frame["books"]:
            try:
                book = OrderBookSnapshot.model_validate(raw)
                if book.token_id in books:
                    duplicates.add(book.token_id)
                books[book.token_id] = book
                raw_books[book.token_id] = deepcopy(raw)
            except (ValueError, TypeError):
                self._reject("invalid_order_book_contract")
        groups, seen_market_ids, seen_tokens = defaultdict(list), set(), set()
        for raw in frame["markets"]:
            try:
                if len(json.dumps(raw, allow_nan=False)) > 65536:
                    raise ValueError("bounded_metadata_record_required")
                market = MarketSnapshot.model_validate(raw)
                if market.outcome.casefold() != "yes":
                    continue  # A YES/NO token pair is never a cross-market graph edge.
                if market.market_id in seen_market_ids or market.token_id in seen_tokens:
                    self._reject("duplicate_market_or_token_identity")
                    continue
                seen_market_ids.add(market.market_id)
                seen_tokens.add(market.token_id)
                if market.source != METADATA_SOURCE or market.exchange != "polymarket" or market.status != "active":
                    raise ValueError("unsupported_market_metadata_source_or_status")
                if not market.event_id or not market.resolution_rules or market.available_at > now or market.timestamp > now:
                    raise ValueError("missing_rules_parent_or_future_metadata")
                book = books.get(market.token_id)
                if book is None:
                    raise ValueError("missing_order_book")
                if market.token_id in duplicates:
                    raise ValueError("ambiguous_duplicate_order_book")
                if book.market_id != market.market_id or book.exchange != market.exchange or book.source not in BOOK_SOURCES:
                    raise ValueError("source_quote_market_identity_mismatch")
                if not book.complete or not book.bids or not book.asks:
                    raise ValueError("incomplete_executable_quote")
                if not 0 <= (now-book.timestamp).total_seconds() <= 15 or not 0 <= (now-book.available_at).total_seconds() <= 15:
                    raise ValueError("stale_or_future_source_quote")
                groups[market.event_id].append(market)
                self.current[market.token_id] = (market, book)
                self.raw_current[market.token_id] = (deepcopy(raw), raw_books[market.token_id])
            except (ValueError, TypeError) as exc:
                self._reject(str(exc) if isinstance(exc, ValueError) and len(str(exc)) < 100 else "invalid_market_contract")
        # At most one candidate per parent; avoid overweighting an outcome grid.
        candidates = []
        for event_id, markets in sorted(groups.items()):
            pair = next(combinations(sorted(markets, key=lambda m: m.market_id), 2), None)
            if pair:
                candidates.append((event_id, pair))
        self.candidate_pairs += len(candidates)
        for event_id, (left, right) in candidates:
            identity = digest(["shared-parent-statistical-v1", event_id, left.market_id, right.market_id])
            if identity in self.definitions or len(self.definitions) >= self.max_pairs:
                continue
            raw = [deepcopy(self.raw_current[m.token_id][0]) for m in (left, right)]
            self.proofs[identity] = raw
            self.definitions[identity] = {"id": identity, "kind": "statistical_relationship",
                "left_id": left.token_id, "right_id": right.token_id,
                "left_market_id": left.market_id, "right_market_id": right.market_id,
                "left_domain": classify_snapshot(left, now=now).domain,
                "right_domain": classify_snapshot(right, now=now).domain,
                "relation_type": "linear_dependency", "minimum_residual": .01,
                "review_actor": "machine:shared-parent-source-proof-v1",
                "review_scope": "shared_parent_statistical_eligibility_only",
                "available_at": now.isoformat(), "parent_event_id": event_id,
                "metadata_sha256": [digest(row) for row in raw],
                "semantic_sha256": [digest(_semantic(m)) for m in (left, right)]}
        results = []
        for definition in self.definitions.values():
            observations = []
            for side in ("left", "right"):
                proof = self.current.get(definition[side+"_id"])
                if proof is None:
                    break
                market, book = proof
                if digest(_semantic(market)) != definition["semantic_sha256"][0 if side == "left" else 1]:
                    self._reject("contract_semantics_changed_requires_new_review")
                    break
                raw_market, raw_book = self.raw_current[market.token_id]
                quote_hash = digest(raw_book)
                observations.append({"entity_id": market.token_id, "domain": definition[side+"_domain"],
                    "kind": "market_quote", "source": book.source,
                    "timestamp": book.timestamp.isoformat(), "available_at": book.available_at.isoformat(),
                    "value": (book.bids[0].price+book.asks[0].price)/2,
                    "semantics": SEMANTICS,
                    "uncertainty": {"absolute_error_bound": (book.asks[0].price-book.bids[0].price)/2},
                    "quote_sha256": quote_hash, "metadata_sha256": digest(raw_market),
                    "evidence_sha256": digest([quote_hash, digest(_semantic(market))])})
            if len(observations) != 2:
                self._reject("registered_pair_missing_qualified_source_quotes")
                continue
            result = self.engine.observe(definition, observations, now=now)
            self.statuses[result.get("reason", result["status"])] += 1
            results.append({"relationship_id": definition["id"], **result})
        return {"evaluated_at": now.isoformat(), "results": results, **self.summary()}

    def summary(self):
        return {"cycles": self.cycles, "last_evaluation_at": self.last_at,
            "candidate_parent_pairs_cumulative": self.candidate_pairs,
            "registered_statistical_candidates": len(self.definitions),
            "parent_event_groups": len({d["parent_event_id"] for d in self.definitions.values()}),
            "current_qualified_market_tokens": len(self.current), "source_freshness_limit_seconds": 15,
            "statuses_cumulative": dict(self.statuses), "source_rejections_cumulative": dict(self.rejections),
            "engine": self.engine.summary(), "semantics": SEMANTICS,
            "cross_domain_reviewed_findings": 0, "reviewed_logical_constraints": 0,
            "research_only": True, "trading_authority": False, "certification_authority": False,
            "counter_scope": "cumulative_since_instance_creation_or_checkpoint_restore"}

    def checkpoint(self):
        return deepcopy({"schema_version": "phase15-source-relationship-v1", "max_pairs": self.max_pairs,
            "definitions": self.definitions, "proofs": self.proofs, "engine": self.engine.checkpoint(),
            "cycles": self.cycles, "candidate_pairs": self.candidate_pairs, "last_at": self.last_at,
            "rejections": dict(self.rejections), "statuses": dict(self.statuses)})

    def restore(self, checkpoint):
        """Restore only after whole-checkpoint integrity verification by caller."""
        if len(json.dumps(checkpoint, allow_nan=False)) > 8 * 1024**2:
            raise ValueError("source_relationship_checkpoint_byte_budget")
        value = deepcopy(checkpoint)
        if value.get("schema_version") != "phase15-source-relationship-v1" or value.get("max_pairs") != self.max_pairs:
            raise ValueError("source_relationship_checkpoint_schema")
        candidate = RelationshipResearch(max_pairs=self.max_pairs)
        candidate.definitions, candidate.proofs = value["definitions"], value["proofs"]
        if (len(candidate.definitions) > self.max_pairs or set(candidate.definitions) != set(candidate.proofs)
                or any(not candidate._review_definition(d) for d in candidate.definitions.values())):
            raise ValueError("source_relationship_checkpoint_definition_integrity")
        candidate.engine.restore(value["engine"])
        for key in ("cycles", "candidate_pairs"):
            if type(value.get(key)) is not int or value[key] < 0:
                raise ValueError("source_relationship_checkpoint_counter")
        for key in ("rejections", "statuses"):
            if not isinstance(value.get(key), dict) or len(value[key]) > 64 or any(type(v) is not int or v < 0 for v in value[key].values()):
                raise ValueError("source_relationship_checkpoint_rejections")
        if value["last_at"] is not None:
            _time(value["last_at"])
        self.definitions, self.proofs, self.engine = candidate.definitions, candidate.proofs, candidate.engine
        # Rebind callbacks: restored engine must use this instance's fresh proofs.
        self.engine.definition_validator, self.engine.observation_validator = self._review_definition, self._review_observation
        self.cycles, self.candidate_pairs, self.last_at = value["cycles"], value["candidate_pairs"], value["last_at"]
        self.rejections, self.statuses = Counter(value["rejections"]), Counter(value["statuses"])
        self.current, self.raw_current = {}, {}


def qualify_cross_domain_driver(definition, *, observed_at, review=None):
    """Source-bound driver interface, denied without explicit independent review.

    Caller review must verify raw external driver evidence and a documented
    relationship hypothesis. This interface never installs logical constraints or
    creates an operational engine link, even after a positive research review.
    """
    now = _time(observed_at)
    result = {"status": "withheld", "research_only": True, "trading_authority": False,
              "logical_constraint_reviewed": False, "executable_opportunity": False}
    try:
        if (definition.get("kind") != "statistical_relationship"
                or definition.get("left_domain") not in DOMAINS or definition.get("right_domain") not in DOMAINS
                or definition["left_domain"] == definition["right_domain"]):
            raise ValueError("explicit_cross_domain_statistical_hypothesis_required")
        if (not definition.get("hypothesis") or not isinstance(definition.get("raw_evidence_utf8"), str)
                or hashlib.sha256(definition["raw_evidence_utf8"].encode()).hexdigest() != definition.get("raw_evidence_sha256")
                or not str(definition.get("source", "")).startswith("https://")):
            raise ValueError("source_bound_driver_evidence_required")
        if not _time(definition["source_timestamp"]) <= _time(definition["retrieved_at"]) <= _time(definition["available_at"]) <= now:
            raise ValueError("future_driver_definition")
        if review is None or review(deepcopy(definition), digest(definition)) is not True:
            raise ValueError("independent_source_bound_driver_review_required")
        return {**result, "status": "research_candidate_only", "definition_sha256": digest(definition)}
    except Exception as exc:  # noqa: BLE001 - unavailable reviewers never qualify a driver
        return {**result, "reason": str(exc)[:120]}
