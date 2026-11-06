"""Bounded causal quote/context history; matured monetary marks are not outcomes."""
from __future__ import annotations

import json
from collections import Counter, deque
from copy import deepcopy
from datetime import timedelta
from math import isfinite
from urllib.parse import urlparse

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot
from neraium_poly.data import assess_book
from neraium_poly.research.phase14.relationships import _time, digest
from neraium_poly.research.phase15.relationships import BOOK_SOURCES, METADATA_SOURCE

VERSION = "phase16-causal-history-v1"


def _vwap(levels, quantity=5.0):
    """Only 25% of each of the observed top three levels may support a mark."""
    remaining, total = quantity, 0.0
    for level in levels[:3]:
        take = min(remaining, float(level["size"]) * .25)
        total += take * float(level["price"])
        remaining -= take
    return total / quantity if remaining <= 1e-9 else None


def _semantic(market):
    return {key: market.model_dump(mode="json")[key] for key in (
        "exchange", "market_id", "token_id", "event_id", "question", "outcome",
        "resolution_rules", "resolution_source", "end_time", "min_order_size", "tick_size")}


def _fee(raw, now):
    if not isinstance(raw, dict) or len(json.dumps(raw, allow_nan=False)) > 8192:
        return None, None
    try:
        value = raw.get("fee_rate", raw.get("effective_notional_bound"))
        at = _time(raw.get("observed_at", raw.get("available_at", raw.get("timestamp", ""))))
        source = urlparse(raw.get("source", ""))
        if (isinstance(value, bool) or not isinstance(value, (float, int)) or not isfinite(value)
            or not 0 <= value <= 1 or not 0 <= (now-at).total_seconds() <= 300
            or source.scheme != "https" or source.hostname != "clob.polymarket.com"
            or source.port not in (None, 443) or not isinstance(raw.get("reference"), str)
            or not 1 <= len(raw["reference"]) <= 2048):
            return None, None
        return float(value), {k: deepcopy(raw[k]) for k in (
            "fee_rate", "effective_notional_bound", "observed_at", "available_at", "timestamp",
            "source", "reference", "id", "evidence_id", "raw_response_ids") if k in raw}
    except (ValueError, TypeError, AttributeError):
        return None, None


class CausalHistory:
    """Retain source-bound quote evidence with explicit point-in-time missingness.

    Unknown producer health does not erase authentic descriptive quotes, but it
    denies execution-evidence completeness. A 60-second label is first observed
    executable bid depth, never settlement, actual fill or independent event.
    Persist complete frames/checkpoints in the caller's append-only archive.
    """

    def __init__(self, *, max_tokens=8, history_size=240, max_labels=512):
        if (type(max_tokens) is not int or not 1 <= max_tokens <= 64
            or type(history_size) is not int or not 60 <= history_size <= 240
            or max_tokens * history_size > 4096
            or type(max_labels) is not int or not 1 <= max_labels <= 1024):
            raise ValueError("bounded causal history configuration required")
        self.config = {"max_tokens": max_tokens, "history_size": history_size, "max_labels": max_labels,
                       "horizon_seconds": 60, "maximum_label_lag_seconds": 30,
                       "maximum_source_age_seconds": 15, "maximum_gap_seconds": 120,
                       "quantity": 5.0, "depth_scope": "top3_observed", "participation": .25}
        self.history, self.contexts, self.resolved, self.last_seen = {}, {}, {}, {}
        self.labels = deque(maxlen=max_labels)
        self.rejections, self.missingness = Counter(), Counter()
        self.last_at = None
        self.cycles = self.accepted_total = self.matured_total = self.continuity_resets = 0

    def _reject(self, reason):
        key = reason if reason in self.rejections or len(self.rejections) < 48 else "other_bounded_rejection"
        self.rejections[key] += 1

    def observe(self, frame, *, now):
        now = _time(now)
        if self.last_at is not None and now <= _time(self.last_at):
            self._reject("non_increasing_observation_cutoff")
            return {"accepted": [], "matured": [], "status": "withheld", **self.summary()}
        if (not isinstance(frame, dict) or not isinstance(frame.get("markets"), list)
            or not isinstance(frame.get("books"), list) or len(frame["markets"]) > 1000
            or len(frame["books"]) > 2000 or len(json.dumps(frame, allow_nan=False)) > 8 * 1024**2):
            raise ValueError("bounded causal market frame required")
        self.last_at = now.isoformat()
        self.cycles += 1
        books, duplicate_books = {}, set()
        for raw in frame["books"]:
            try:
                book = OrderBookSnapshot.model_validate(raw)
                if book.token_id in books:
                    duplicate_books.add(book.token_id)
                books[book.token_id] = (book, raw)
            except (ValueError, TypeError):
                self._reject("invalid_book_contract")
        markets, duplicate_markets = {}, set()
        for raw in frame["markets"]:
            try:
                if len(json.dumps(raw, allow_nan=False)) > 65536:
                    raise ValueError("bounded_metadata_required")
                market = MarketSnapshot.model_validate(raw)
                if market.token_id in markets:
                    duplicate_markets.add(market.token_id)
                markets[market.token_id] = (market, raw)
            except (ValueError, TypeError):
                self._reject("invalid_market_contract")
        if (any(frame.get(key) is not None and _time(frame[key]) > now for key in ("timestamp", "available_at"))
            or (frame.get("timestamp") is not None and frame.get("available_at") is not None
                and _time(frame["timestamp"]) > _time(frame["available_at"]))):
            self._reject("future_frame")
            return {"accepted": [], "matured": [], "status": "withheld", **self.summary()}
        candidates = []
        for token, (market, raw_market) in markets.items():
            try:
                if token in duplicate_books or token in duplicate_markets:
                    raise ValueError("ambiguous_duplicate_token")
                book, raw_book = books.get(token, (None, None))
                if any(len(value) > 256 for value in (market.token_id, market.market_id, market.event_id)):
                    raise ValueError("bounded_market_identifiers_required")
                if book is not None and len(book.id) > 256:
                    raise ValueError("bounded_quote_identifier_required")
                if market.source != METADATA_SOURCE or market.exchange != "polymarket":
                    raise ValueError("unverified_metadata_source")
                if (market.timestamp > now or market.available_at > now or not market.event_id
                    or not market.resolution_rules or not market.resolution_source):
                    raise ValueError("missing_or_future_market_context")
                if market.status != "active" or (market.end_time and market.end_time <= now):
                    raise ValueError("inactive_or_ended_market")
                health = assess_book(book, now, max_spread=.05, expected_token=token)
                if not health.healthy:
                    for reason in health.reasons:
                        self._reject(reason)
                    continue
                if (book.market_id, book.exchange) != (market.market_id, market.exchange) or book.source not in BOOK_SOURCES:
                    raise ValueError("book_source_or_market_identity_mismatch")
                if not 0 <= (now-book.available_at).total_seconds() <= 15:
                    raise ValueError("stale_book_receipt")
                raw_bids = [p.model_dump() for p in book.bids[:3]]
                raw_asks = [p.model_dump() for p in book.asks[:3]]
                depth = min(sum(p["size"] for p in raw_bids), sum(p["size"] for p in raw_asks))
                candidates.append((token not in self.history, -depth, token, market, raw_market, book, raw_book))
            except (ValueError, TypeError) as error:
                self._reject(str(error) if len(str(error)) <= 100 else "invalid_causal_context")
        # Keep established histories where possible; select new tokens by current
        # observed two-sided depth, never future outcomes or hindsight P/L.
        selected = sorted(candidates, key=lambda row: row[:3])[:self.config["max_tokens"]]
        selected_tokens = {row[2] for row in selected}
        for token in list(self.history):
            if token not in selected_tokens and (now-_time(self.last_seen[token])).total_seconds() > 120:
                self.history.pop(token)
                self.contexts.pop(token, None)
                self.resolved.pop(token, None)
                self.last_seen.pop(token, None)
        accepted, matured = [], []
        for _old, _depth, token, market, raw_market, book, raw_book in selected:
            if token not in self.history and len(self.history) >= self.config["max_tokens"]:
                self._reject("history_capacity_waiting_for_inactive_retirement")
                continue
            context = digest(_semantic(market))
            history = self.history.setdefault(token, deque(maxlen=self.config["history_size"]))
            if history and self.contexts.get(token) != context:
                history.clear()
                self.resolved[token] = set()
                self.continuity_resets += 1
                self._reject("contract_context_changed_history_epoch")
            self.contexts[token] = context
            raw_sha = digest(raw_book)
            previous_id = next((p for p in history if p["book_id"] == book.id), None)
            if previous_id is not None:
                if previous_id["book_sha256"] != raw_sha:
                    self._reject("changed_book_identity")
                else:
                    self._reject("duplicate_quote_does_not_add_history")
                self.last_seen[token] = now.isoformat()
                continue
            if history and book.timestamp <= _time(history[-1]["source_at"]):
                self._reject("out_of_order_quote")
                continue
            if history and (book.timestamp-_time(history[-1]["source_at"])).total_seconds() > 120:
                history.clear()
                self.resolved[token] = set()
                self.continuity_resets += 1
                self._reject("source_gap_history_epoch")
            point = self._point(frame, market, raw_market, book, raw_book, context, now)
            done = self.resolved.setdefault(token, set())
            for decision in history:
                if decision["id"] in done:
                    continue
                target = _time(decision["observed_at"]) + timedelta(seconds=60)
                lag = (book.timestamp-target).total_seconds()
                if 0 <= lag <= 30:
                    done.add(decision["id"])
                    if (decision["bid_vwap"] is None or point["bid_vwap"] is None
                        or decision["ask_vwap"] is None):
                        self._reject("matured_mark_missing_observed_depth")
                        continue
                    pair = {"id": digest([decision["id"], point["id"], "60s-top3-bid-mark"]),
                            "decision": deepcopy(decision), "label": deepcopy(point),
                            "decision_at": decision["observed_at"], "forecast_cutoff": decision["observed_at"],
                            "target_at": target.isoformat(), "label_available_at": point["available_at"],
                            "label_observed_at": now.isoformat(), "label_lag_seconds": lag,
                            "unchanged_bid_baseline": decision["bid_vwap"], "actual_bid": point["bid_vwap"],
                            "event_id": market.event_id, "quantity": 5.0,
                            "label_semantics": "observed_top3_depth_bid_mark_not_fill_or_settlement",
                            "trading_authority": False, "independent_outcome": False}
                    self.labels.append(pair)
                    self.matured_total += 1
                    matured.append(deepcopy(pair))
                elif (now-target).total_seconds() > 45:
                    done.add(decision["id"])
                    self._reject("horizon_label_missed_not_interpolated")
            history.append(point)
            self.last_seen[token] = now.isoformat()
            self.resolved[token] = done.intersection(p["id"] for p in history)
            accepted.append(deepcopy(point))
            self.accepted_total += 1
        return {"status": "research_only", "accepted": accepted, "matured": matured, **self.summary()}

    def _point(self, frame, market, raw_market, book, raw_book, context, now):
        bids = [p.model_dump() for p in book.bids[:3]]
        asks = [p.model_dump() for p in book.asks[:3]]
        bid_depth, ask_depth = sum(p["size"] for p in bids), sum(p["size"] for p in asks)
        fees = frame.get("fees") if isinstance(frame.get("fees"), dict) else {}
        fee, fee_raw = _fee(fees.get(market.token_id), now)
        missing = []
        producer = frame.get("producer_health")
        if not isinstance(producer, dict) or producer.get("status") != "ok":
            missing.append("producer_health")
        if not frame.get("id"):
            missing.append("source_frame_identity")
        if fee is None:
            missing.append("qualified_fee_observation")
        bid_vwap, ask_vwap = _vwap(bids), _vwap(asks)
        if bid_vwap is None or ask_vwap is None:
            missing.append("top3_participating_depth")
        if market.min_order_size > 5:
            missing.append("exchange_minimum_quantity")
        self.missingness.update(missing)
        return {"id": digest(["phase16-point", book.id, context]), "book_id": book.id,
                "token_id": market.token_id, "market_id": market.market_id, "event_id": market.event_id,
                "timestamp": book.timestamp.isoformat(), "source_at": book.timestamp.isoformat(),
                "available_at": book.available_at.isoformat(), "observed_at": now.isoformat(),
                "bid": book.bids[0].price, "ask": book.asks[0].price,
                "bid_vwap": bid_vwap, "ask_vwap": ask_vwap, "quantity": 5.0,
                "bids": bids, "asks": asks, "bid_depth_shares": bid_depth, "ask_depth_shares": ask_depth,
                "imbalance": (bid_depth-ask_depth)/(bid_depth+ask_depth),
                "spread": book.asks[0].price-book.bids[0].price,
                "min_order_size": market.min_order_size, "tick_size": market.tick_size,
                "depth_scope": "top3_observed", "participation": .25,
                "source": book.source, "book_sha256": digest(raw_book), "metadata_sha256": digest(raw_market),
                "rules_sha256": context, "source_frame_id": frame.get("id"),
                "fee_rate": fee, "fee_observation": fee_raw,
                "fee_observation_valid": fee is not None,
                "fee_evidence_sha256": digest(fee_raw) if fee_raw else None,
                "missing_fields": missing, "execution_evidence_complete": not missing,
                "research_only": True, "trading_authority": False}

    def points(self, token=None):
        return deepcopy(list(self.history.get(token, ())) if token else
                        sorted((p for rows in self.history.values() for p in rows), key=lambda p: (p["observed_at"], p["id"])))

    def matured(self):
        return deepcopy(list(self.labels))

    def summary(self):
        rows = []
        for token, history in sorted(self.history.items()):
            if not history:
                continue
            gaps = [(_time(b["source_at"])-_time(a["source_at"])).total_seconds()
                    for a, b in zip(history, list(history)[1:], strict=False)]
            rows.append({"token_id": token, "market_id": history[-1]["market_id"], "event_id": history[-1]["event_id"],
                         "observations": len(history),
                         "matured_labels": sum(label["decision"]["token_id"] == token
                                               and label["decision"]["rules_sha256"] == self.contexts[token]
                                               and _time(label["decision"]["source_at"]) >= _time(history[0]["source_at"])
                                               for label in self.labels), "span_seconds": (_time(history[-1]["source_at"])-_time(history[0]["source_at"])).total_seconds(),
                         "max_gap_seconds": max(gaps, default=0),
                         "latest_source_at": history[-1]["source_at"], "latest_available_at": history[-1]["available_at"],
                         "execution_evidence_complete": history[-1]["execution_evidence_complete"],
                         "missing_fields": history[-1]["missing_fields"]})
        return {"schema_version": VERSION, "observed_at": self.last_at, "last_observation_at": self.last_at,
                "cycles": self.cycles, "tokens_tracked": len(rows), "valid_observations": self.accepted_total,
                "current_observations": sum(r["observations"] for r in rows),
                "span_seconds": max((r["span_seconds"] for r in rows), default=0),
                "max_gap_seconds": max((r["max_gap_seconds"] for r in rows), default=0),
                "matured_labels": self.matured_total, "current_matured_labels": len(self.labels),
                "unique_parent_events": len({r["event_id"] for r in rows}), "independent_outcome_events": 0,
                "continuity_resets": self.continuity_resets, "per_token": rows,
                "rejections": dict(self.rejections), "missingness": dict(self.missingness),
                "counter_scope": "cumulative since construction or verified checkpoint restore; bounded retained rows separate",
                "research_only": True, "trading_authority": False, "certification_authority": False}

    def checkpoint(self):
        value = deepcopy({"schema_version": VERSION, "config": self.config,
                         "history": {k: list(v) for k, v in self.history.items()}, "contexts": self.contexts,
                         "resolved": {k: sorted(v) for k, v in self.resolved.items()}, "last_seen": self.last_seen,
                         "labels": list(self.labels), "last_at": self.last_at, "cycles": self.cycles,
                         "accepted_total": self.accepted_total, "matured_total": self.matured_total,
                         "continuity_resets": self.continuity_resets,
                         "rejections": dict(self.rejections), "missingness": dict(self.missingness)})
        if len(json.dumps(value, allow_nan=False)) > 8 * 1024**2:
            raise ValueError("causal checkpoint byte budget exceeded")
        return value

    def restore(self, value):
        if (not isinstance(value, dict) or len(json.dumps(value, allow_nan=False)) > 8 * 1024**2
            or value.get("schema_version") != VERSION or value.get("config") != self.config):
            raise ValueError("causal checkpoint schema or bound mismatch")
        candidate = CausalHistory(max_tokens=self.config["max_tokens"], history_size=self.config["history_size"],
                                  max_labels=self.config["max_labels"])
        if len(value["history"]) > self.config["max_tokens"] or len(value["labels"]) > self.config["max_labels"]:
            raise ValueError("oversized causal checkpoint history")
        for token, history in value["history"].items():
            if len(history) > self.config["history_size"]:
                raise ValueError("oversized causal token history")
            previous = None
            for point in history:
                at, available, observed = (_time(point[k]) for k in ("source_at", "available_at", "observed_at"))
                bids, asks = point["bids"], point["asks"]
                fee, fee_raw = _fee(point["fee_observation"], observed)
                valid_levels = (1 <= len(bids) <= 3 and 1 <= len(asks) <= 3
                                and all(isinstance(level.get("price"), (int, float))
                                        and not isinstance(level["price"], bool) and isfinite(level["price"])
                                        and 0 < level["price"] < 1 and isinstance(level.get("size"), (int, float))
                                        and not isinstance(level["size"], bool) and isfinite(level["size"])
                                        and level["size"] > 0 for level in bids+asks))
                if (not valid_levels or point["bid"] != bids[0]["price"] or point["ask"] != asks[0]["price"]
                    or not 0 < point["bid"] < point["ask"] < 1
                    or point["quantity"] != 5.0 or point["depth_scope"] != "top3_observed" or point["participation"] != .25
                    or fee != point["fee_rate"] or point["fee_observation_valid"] != (fee is not None)
                    or point["fee_evidence_sha256"] != (digest(fee_raw) if fee_raw else None)
                    or point["execution_evidence_complete"] != (not point["missing_fields"])
                    or point["token_id"] != token or at > available or available > observed
                    or (observed-at).total_seconds() > 15 or point["source"] not in BOOK_SOURCES
                    or observed > _time(value["last_at"]) or (previous and at <= previous)
                    or point["rules_sha256"] != value["contexts"][token]
                    or point["id"] != digest(["phase16-point", point["book_id"], point["rules_sha256"]])
                    or point["bid_vwap"] != _vwap(point["bids"]) or point["ask_vwap"] != _vwap(point["asks"])
                    or point["trading_authority"] is not False or point["research_only"] is not True):
                    raise ValueError("invalid causal checkpoint point")
                previous = at
            candidate.history[token] = deque(deepcopy(history), maxlen=self.config["history_size"])
        for label in value["labels"]:
            decision, actual = label["decision"], label["label"]
            target = _time(decision["observed_at"]) + timedelta(seconds=60)
            if (decision["token_id"] != actual["token_id"] or decision["rules_sha256"] != actual["rules_sha256"]
                or label["target_at"] != target.isoformat() or not 0 <= (_time(actual["source_at"])-target).total_seconds() <= 30
                or _time(label["label_observed_at"]) > _time(value["last_at"])
                or _time(decision["source_at"]) > _time(decision["available_at"])
                or _time(decision["available_at"]) > _time(decision["observed_at"])
                or not _time(actual["source_at"]) <= _time(actual["available_at"]) <= _time(label["label_observed_at"])
                or actual["observed_at"] != label["label_observed_at"]
                or actual["bid_vwap"] != _vwap(actual["bids"])
                or decision["bid_vwap"] != _vwap(decision["bids"])
                or decision["quantity"] != 5.0 or actual["quantity"] != 5.0
                or label["id"] != digest([decision["id"], actual["id"], "60s-top3-bid-mark"])
                or label["actual_bid"] != actual["bid_vwap"] or label["unchanged_bid_baseline"] != decision["bid_vwap"]
                or label["independent_outcome"] is not False or label["trading_authority"] is not False):
                raise ValueError("invalid causal checkpoint matured label")
        if (value["accepted_total"] < sum(map(len, value["history"].values()))
            or value["matured_total"] < len(value["labels"])):
            raise ValueError("invalid causal retained/cumulative counts")
        for key in ("cycles", "accepted_total", "matured_total", "continuity_resets"):
            if type(value.get(key)) is not int or value[key] < 0:
                raise ValueError("invalid causal checkpoint counter")
            setattr(candidate, key, value[key])
        for key in ("rejections", "missingness"):
            if (not isinstance(value.get(key), dict) or len(value[key]) > 64
                or any(type(v) is not int or v < 0 for v in value[key].values())):
                raise ValueError("invalid causal checkpoint reasons")
            setattr(candidate, key, Counter(value[key]))
        candidate.labels = deque(deepcopy(value["labels"]), maxlen=self.config["max_labels"])
        candidate.contexts, candidate.last_seen = deepcopy(value["contexts"]), deepcopy(value["last_seen"])
        candidate.resolved = {k: set(v) for k, v in value["resolved"].items()}
        if (set(candidate.history) != set(candidate.contexts) or set(candidate.history) != set(candidate.last_seen)
            or set(candidate.history) != set(candidate.resolved)
            or any(not candidate.resolved[t].issubset({p["id"] for p in rows}) for t, rows in candidate.history.items())):
            raise ValueError("invalid causal checkpoint token binding")
        candidate.last_at = value["last_at"]
        if candidate.last_at is not None:
            _time(candidate.last_at)
        self.__dict__.update(candidate.__dict__)
