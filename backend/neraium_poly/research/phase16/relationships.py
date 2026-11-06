"""Causal shared-parent graph selection and versioned retirement; research only."""
from collections import Counter, defaultdict, deque
from copy import deepcopy
from itertools import combinations

from neraium_poly.contracts import MarketSnapshot
from neraium_poly.research.phase14.relationships import _time, digest
from neraium_poly.research.phase15.relationships import RelationshipResearch, _semantic

VERSION = "phase16-relationship-history-v1"


class RelationshipHistory:
    """Preserve temporal baselines while allowing inactive graph slots to retire.

    Source validation and unchanged10-observation warmup/3-observation/60second
    persistence are inherited. Selection requires three causal quote observations
    spanning60seconds per side. Shared parent establishes statistical eligibility
    only. Retirements are bounded cache entries; caller archives every checkpoint.
    """

    def __init__(self, *, max_pairs=3, missing_seconds=120):
        if type(max_pairs) is not int or not 1 <= max_pairs <= 20 or missing_seconds != 120:
            raise ValueError("bounded conservative graph configuration required")
        self.config = {"max_pairs": max_pairs, "missing_seconds": missing_seconds,
                       "selection_observations": 3, "selection_span_seconds": 60}
        self.engine = RelationshipResearch(max_pairs=max_pairs)
        self.coverage, self.absent_since = {}, {}
        self.retired = deque(maxlen=32)
        self.version = self.retirements_total = 0
        self.last_at = None
        self.rejections = Counter()

    def _retire(self, identity, reason, now):
        definition = self.engine.definitions[identity]
        state = self.engine.engine.states.get(identity)
        archived = {"definition": definition, "proofs": self.engine.proofs[identity], "state": state}
        self.version += 1
        self.retirements_total += 1
        self.retired.append({"graph_version": self.version, "relationship_id": identity,
                             "retired_at": now.isoformat(), "reason": reason,
                             "prior_state_sha256": digest(archived), "archived_state": deepcopy(archived),
                             "trading_authority": False})
        self.engine.definitions.pop(identity)
        self.engine.proofs.pop(identity)
        self.engine.engine.states.pop(identity, None)
        self.absent_since.pop(identity, None)

    def observe(self, frame, *, now):
        now = _time(now)
        if self.last_at and now <= _time(self.last_at):
            self.rejections["non_increasing_graph_cutoff"] += 1
            return {"status": "withheld", **self.summary()}
        self.last_at = now.isoformat()
        probe = RelationshipResearch(max_pairs=1)
        probe.observe(frame, observed_at=now)  # Same source/context verifier; no authority.
        raw_markets = {}
        for raw in frame.get("markets", []):
            try:
                market = MarketSnapshot.model_validate(raw)
                raw_markets[market.token_id] = market
            except (ValueError, TypeError):
                continue
        for identity, definition in list(self.engine.definitions.items()):
            pairs = [(side, raw_markets.get(definition[side + "_id"])) for side in ("left", "right")]
            reason = None
            if any(m and (m.status != "active" or (m.end_time and m.end_time <= now)) for _, m in pairs):
                reason = "contract_inactive_or_ended"
            elif any(m and digest(_semantic(m)) != definition["semantic_sha256"][0 if side == "left" else 1]
                     for side, m in pairs):
                reason = "contract_semantics_changed"
            elif any(m is None for _, m in pairs):
                since = self.absent_since.setdefault(identity, now.isoformat())
                if (now-_time(since)).total_seconds() >= 120:
                    reason = "pair_absent_from_observed_universe_for120s"
            else:
                self.absent_since.pop(identity, None)
            if reason:
                self._retire(identity, reason, now)
        eligible = {}
        for token, (market, book) in probe.current.items():
            if market.end_time and market.end_time <= now:
                continue
            previous = self.coverage.get(token)
            semantics = digest(_semantic(market))
            if previous is None or previous["semantics"] != semantics or (book.timestamp-_time(previous["source_at"])).total_seconds() > 120:
                previous = {"first_at": book.timestamp.isoformat(), "count": 0, "book_id": None,
                            "semantics": semantics, "source_at": book.timestamp.isoformat()}
            if previous["book_id"] != book.id and (previous["count"] == 0 or book.timestamp > _time(previous["source_at"])):
                previous["count"] += 1
                previous["book_id"] = book.id
                previous["source_at"] = book.timestamp.isoformat()
            previous["seen_at"] = now.isoformat()
            self.coverage[token] = previous
            if previous["count"] >= 3 and (book.timestamp-_time(previous["first_at"])).total_seconds() >= 60:
                eligible[token] = (market, book)
        # Coverage is a bounded causal cache, not a persistent independent-event count.
        live = set(eligible) | {d[side+"_id"] for d in self.engine.definitions.values() for side in ("left", "right")}
        self.coverage = {token: row for token, row in self.coverage.items()
                         if token in live or (now-_time(row["seen_at"])).total_seconds() <= 120}
        if len(self.coverage) > 512:
            self.coverage = dict(sorted(self.coverage.items(), key=lambda item: (-_time(item[1]["seen_at"]).timestamp(), item[0]))[:512])
        tokens = {d[side+"_id"] for d in self.engine.definitions.values() for side in ("left", "right")}
        registered_parents = {d["parent_event_id"] for d in self.engine.definitions.values()}
        groups = defaultdict(list)
        for token, (market, book) in eligible.items():
            if market.event_id not in registered_parents:
                groups[market.event_id].append((market, book))
        ranked = []
        for parent, members in groups.items():
            pairs = []
            for left, right in combinations(sorted(members, key=lambda row: row[0].market_id), 2):
                depth = min(sum(p.size for p in side.bids[:3]) + sum(p.size for p in side.asks[:3])
                            for _, side in (left, right))
                observations = min(self.coverage[left[0].token_id]["count"], self.coverage[right[0].token_id]["count"])
                pairs.append((-observations, -depth, left[0].market_id, right[0].market_id, left[0].token_id, right[0].token_id))
            if pairs:
                best = min(pairs)
                ranked.append((best[:2], parent, best[-2:]))
        slots = self.config["max_pairs"]-len(self.engine.definitions)
        for _rank, _parent, pair in sorted(ranked)[:slots]:
            tokens.update(pair)
        before = set(self.engine.definitions)
        selected = {"markets": [raw for raw in frame["markets"] if raw.get("token_id") in tokens],
                    "books": [raw for raw in frame["books"] if raw.get("token_id") in tokens]}
        result = self.engine.observe(selected, observed_at=now)
        self.version += len(set(self.engine.definitions)-before)
        return {"results": result.get("results", []), "selected_source_tokens": sorted(tokens), **self.summary()}

    def summary(self):
        return {**self.engine.summary(), "graph_version": self.version,
                "retirements_total": self.retirements_total, "retirements_retained": len(self.retired),
                "selection": {**self.config, "observed_tokens": len(self.coverage),
                              "policy": "existing stable pairs first; causal coverage then observed two-sided depth; one pair per parent"},
                "graph_rejections": dict(self.rejections), "last_observation_at": self.last_at,
                "retirement_storage": "bounded memory cache; caller must archive all study checkpoints",
                "logical_constraints_verified": 0, "predictive_advantage_verified": False,
                "trading_authority": False, "certification_authority": False}

    def checkpoint(self):
        return deepcopy({"schema_version": VERSION, "config": self.config, "engine": self.engine.checkpoint(),
                         "coverage": self.coverage, "absent_since": self.absent_since,
                         "retired": list(self.retired), "version": self.version,
                         "retirements_total": self.retirements_total, "last_at": self.last_at,
                         "rejections": dict(self.rejections)})

    def restore(self, value):
        import json

        if (not isinstance(value, dict) or len(json.dumps(value, allow_nan=False)) > 8 * 1024**2
            or value.get("schema_version") != VERSION or value.get("config") != self.config
            or len(value["coverage"]) > 512 or len(value["retired"]) > 32):
            raise ValueError("invalid relationship history checkpoint bounds")
        candidate = RelationshipHistory(max_pairs=self.config["max_pairs"])
        candidate.engine.restore(value["engine"])
        for name in ("version", "retirements_total"):
            if type(value.get(name)) is not int or value[name] < 0:
                raise ValueError("invalid relationship history version")
        for row in value["retired"]:
            if (row["prior_state_sha256"] != digest(row["archived_state"])
                or row["trading_authority"] is not False or _time(row["retired_at"]) > _time(value["last_at"])):
                raise ValueError("invalid relationship retirement provenance")
        for row in value["coverage"].values():
            if (type(row["count"]) is not int or row["count"] < 0 or _time(row["source_at"]) > _time(row["seen_at"])
                or _time(row["first_at"]) > _time(row["source_at"]) or _time(row["seen_at"]) > _time(value["last_at"])):
                raise ValueError("invalid relationship selection chronology")
        candidate.coverage, candidate.absent_since = deepcopy(value["coverage"]), deepcopy(value["absent_since"])
        if not set(candidate.absent_since).issubset(candidate.engine.definitions):
            raise ValueError("invalid relationship absence binding")
        candidate.retired = deque(deepcopy(value["retired"]), maxlen=32)
        candidate.version, candidate.retirements_total = value["version"], value["retirements_total"]
        candidate.last_at, candidate.rejections = value["last_at"], Counter(value["rejections"])
        self.__dict__.update(candidate.__dict__)
