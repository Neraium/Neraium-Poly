"""Registered, unvalidated research strategies using causal public observations.

The horizon model estimates future executable bid marks, never independently
calibrated terminal probabilities. Registration cannot authorize certification.
"""

import json
from bisect import bisect_left
from collections import Counter, deque
from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
from itertools import pairwise
from math import isfinite
from statistics import median
from urllib.parse import urlparse

from neraium_poly.data import assess_book
from neraium_poly.experimental.contracts import ExperimentalSignal, SharedMarketFrame
from neraium_poly.experimental.intelligence import ExperimentalRelationshipIntelligence

PUBLIC_BOOK_SOURCES = {"https://clob.polymarket.com", "wss://ws-subscriptions-clob.polymarket.com/ws/market"}
STRATEGIES = {
    "cross_market_consistency": "Reviewed logical payoff constraints may expose executable complete-bundle inconsistencies.",
    "persistent_relationship": "Persistent contextual relationship changes may qualify a separately modeled repricing hypothesis.",
    "liquidity_spread": "Spread compensation may exceed inventory and adverse-selection costs when fill mechanics are supported.",
    "event_driven": "Independent predecision context may explain a subsequent, modeled probability adjustment.",
    "short_horizon": "A trailing bid-level reference may predict a temporary dislocation reversal over sixty seconds.",
    "calibrated_forecast": "Independent context and verified prior labels may support calibrated terminal forecasts.",
}


@dataclass(frozen=True)
class QuotePoint:
    id: str
    timestamp: str
    available_at: str
    bid: float
    ask: float

    @property
    def at(self):
        return datetime.fromisoformat(self.timestamp)


class ExperimentalStrategyEngine:
    def __init__(self, enabled=None, max_tokens=400, history_size=96, horizon_seconds=60):
        if not 1 <= max_tokens <= 1000 or not 60 <= history_size <= 240 or not 30 <= horizon_seconds <= 300:
            raise ValueError("bounded experimental history policy required")
        self.enabled = tuple(sorted(STRATEGIES if enabled is None else set(enabled)))
        if set(self.enabled) - STRATEGIES.keys():
            raise ValueError("unregistered experimental strategy")
        self.max_tokens, self.history_size, self.horizon_seconds = max_tokens, history_size, horizon_seconds
        self.history = {}
        self.seen = {}
        self.sequence = 0
        self.counts, self.rejections = Counter(), Counter()
        self.intelligence = ExperimentalRelationshipIntelligence()
        self.latest_signals = []

    @property
    def policy(self):
        return {
            "max_tokens": self.max_tokens,
            "history_size": self.history_size,
            "horizon_seconds": self.horizon_seconds,
            "enabled": list(self.enabled),
        }

    @staticmethod
    def _fee(raw, now):
        if not raw:
            return None, "unknown_fee_schedule"
        try:
            value = raw.get("fee_rate", raw.get("effective_notional_bound"))
            if isinstance(value, bool):
                raise TypeError("boolean fee")
            value = float(value)
            at = datetime.fromisoformat(
                raw.get("observed_at", raw.get("available_at", raw.get("timestamp", "")))
            )
            source = raw.get("source", "")
            if (
                not isfinite(value)
                or not 0 <= value <= 1
                or at.tzinfo is None
                or not 0 <= (now - at).total_seconds() <= 300
                or urlparse(source).scheme != "https"
                or urlparse(source).hostname != "clob.polymarket.com"
                or urlparse(source).port not in (None, 443)
            ):
                raise ValueError("unverified fee observation")
            return value, None
        except (TypeError, ValueError):
            return None, "unknown_or_stale_fee_schedule"

    def _data_reasons(self, frame, market, book, now):
        reasons = []
        if frame.available_at > now or frame.timestamp > now:
            reasons.append("future_frame")
        if frame.producer_health.get("status") != "ok":
            reasons.append("producer_not_healthy")
        if market.available_at > now or market.timestamp > now:
            reasons.append("future_market")
        if market.status != "active":
            reasons.append("inactive_market")
        if not market.resolution_rules or not market.resolution_source:
            reasons.append("unsupported_resolution_rules")
        if market.end_time and market.end_time <= now:
            reasons.append("market_ended")
        reasons.extend(assess_book(book, now, max_spread=0.05, expected_token=market.token_id).reasons)
        if book is not None:
            old = self.history.get(market.token_id)
            if old:
                previous = old[-1]
                if book.timestamp < previous.at:
                    reasons.append("out_of_order_book")
                if book.id == previous.id and (
                    book.timestamp != previous.at
                    or book.available_at.isoformat() != previous.available_at
                    or not book.bids
                    or not book.asks
                    or book.bids[0].price != previous.bid
                    or book.asks[0].price != previous.ask
                ):
                    reasons.append("changed_book_identity")
            if book.source not in PUBLIC_BOOK_SOURCES:
                reasons.append("unverified_public_book_source")
            if (book.market_id, book.exchange) != (market.market_id, market.exchange):
                reasons.append("book_market_identity_mismatch")
        return reasons

    def _remember(self, token, book):
        self._remember_point(
            token,
            QuotePoint(
                book.id,
                book.timestamp.isoformat(),
                book.available_at.isoformat(),
                book.bids[0].price,
                book.asks[0].price,
            ),
        )

    def _remember_point(self, token, point):
        history = self.history.setdefault(token, deque(maxlen=self.history_size))
        if history and point.at <= history[-1].at:
            return
        if history and (point.at - history[-1].at).total_seconds() > 120:
            history.clear()
        history.append(point)

    def _horizon(self, token, now):
        rows = list(self.history.get(token, ()))
        # The current quote is withheld from fitting both baseline and residuals.
        prior = rows[:-1]
        if len(prior) < 40:
            return None, ["insufficient_causal_bid_history"]
        times = [r.at.timestamp() for r in prior]
        errors, label_ids = [], []
        for i in range(20, len(prior)):
            decision_at = datetime.fromisoformat(prior[i].available_at)
            target = decision_at.timestamp() + self.horizon_seconds
            j = bisect_left(times, target)
            if j >= len(prior) or times[j] > target + 30:
                continue
            if any(datetime.fromisoformat(r.available_at) > decision_at for r in prior[i - 20 : i]):
                continue
            # Both prediction inputs and actual future label must be available now.
            if any(datetime.fromisoformat(r.available_at) > now for r in (prior[i], prior[j])):
                continue
            prediction = median(p.bid for p in prior[i - 20 : i])
            errors.append(prior[j].bid - prediction)
            label_ids.extend((prior[i].id, prior[j].id))
        if len(errors) < 20:
            return None, ["insufficient_matured_horizon_forecast_errors"]
        errors = errors[-60:]
        reference = median(p.bid for p in prior[-20:])
        bias = median(errors)
        centered = sorted(abs(e - bias) for e in errors)
        # Empirical 90th percentile envelope plus an explicit policy floor.
        # This is an unvalidated uncertainty band, not statistical coverage proof.
        envelope = max(0.01, centered[min(len(centered) - 1, int(0.9 * len(centered)))])
        forecast = min(1, max(0, reference + bias))
        lower, upper = max(0, forecast - envelope), min(1, forecast + envelope)
        ids = tuple(dict.fromkeys([p.id for p in prior[-20:]] + label_ids[-120:]))
        return {
            "forecast": forecast,
            "lower": lower,
            "upper": upper,
            "observations": len(prior),
            "matured_errors": len(errors),
            "empirical_error_envelope": envelope,
            "reference_bid": reference,
            "bias": bias,
            "evidence_ids": ids,
        }, []

    def evaluate_frame(self, frame: SharedMarketFrame, now: datetime) -> list[ExperimentalSignal]:
        if now.tzinfo is None:
            raise ValueError("aware decision time required")
        markets = {m.token_id: m for m in frame.markets}
        if len(markets) != len(frame.markets) or len(markets) > self.max_tokens:
            raise ValueError("ambiguous or oversized experimental universe")
        books = {b.token_id: b for b in frame.books}
        if len(books) != len(frame.books) or len(books) > self.max_tokens:
            raise ValueError("ambiguous or oversized book universe")
        self.history = {t: h for t, h in self.history.items() if t in markets}
        self.seen = {k: value for k, value in self.seen.items() if k.split(":", 1)[1] in markets}
        healthy = {}
        for token, market in markets.items():
            book = books.get(token)
            if book is not None and not self._data_reasons(frame, market, book, now):
                self._remember(token, book)
                healthy[token] = book
        findings = self.intelligence.observe(markets, healthy, now)
        results = []
        for token, market in sorted(markets.items()):
            book = books.get(token)
            common = self._data_reasons(frame, market, book, now)
            fee, fee_reason = self._fee(frame.fees.get(token), now)
            if fee_reason:
                common.append(fee_reason)
            horizon, horizon_reasons = self._horizon(token, now)
            for strategy in self.enabled:
                reasons = list(common)
                diagnostics = {"book_age_seconds": (now - book.timestamp).total_seconds() if book else None}
                if fee is not None:
                    diagnostics["fee_reference"] = frame.fees[token]["source"]
                    diagnostics["fee_observed_at"] = frame.fees[token].get(
                        "observed_at",
                        frame.fees[token].get("available_at", frame.fees[token].get("timestamp")),
                    )
                values = {}
                evidence_ids = (book.id,) if book else ()
                if strategy in {"short_horizon", "persistent_relationship"}:
                    reasons.extend(horizon_reasons)
                    if horizon:
                        diagnostics.update({k: v for k, v in horizon.items() if k != "evidence_ids"})
                        evidence_ids = tuple(dict.fromkeys(evidence_ids + horizon["evidence_ids"]))
                        values = {
                            "forecast_value": horizon["forecast"],
                            "lower_value": horizon["lower"],
                            "upper_value": horizon["upper"],
                        }
                        if horizon["upper"] - horizon["lower"] > 0.35:
                            reasons.append("excessive_model_uncertainty")
                        if book and book.asks and fee is not None:
                            edge = horizon["lower"] * (1 - fee) - book.asks[0].price * (1 + fee) - 0.02
                            values["estimated_net_edge"] = edge
                            if edge < 0.03:
                                reasons.append("conservative_roundtrip_edge_insufficient")
                    if strategy == "persistent_relationship":
                        relevant = [
                            e
                            for e in findings
                            if e.qualified
                            and market.market_id
                            in self.intelligence.definitions[e.relationship_id].market_ids
                        ]
                        if not relevant:
                            reasons.append("persistent_contextual_relationship_evidence_required")
                        else:
                            evidence_ids += tuple(e.id for e in relevant)
                elif strategy == "cross_market_consistency":
                    reasons.extend(
                        (
                            "independently_reviewed_exhaustive_payoff_scope_required",
                            "multi_leg_execution_and_hedging_not_supported",
                        )
                    )
                elif strategy == "liquidity_spread":
                    reasons.extend(
                        (
                            "validated_queue_and_adverse_selection_model_required",
                            "two_sided_inventory_execution_not_supported",
                        )
                    )
                elif strategy == "event_driven":
                    reasons.append("independent_predecision_context_and_response_model_required")
                else:
                    reasons.append("independent_context_verified_labels_and_calibration_required")
                signature = sha256(
                    json.dumps(
                        [book.id if book else frame.id, sorted(set(reasons)), values, list(evidence_ids)],
                        sort_keys=True,
                    ).encode()
                ).hexdigest()
                seen_key = strategy + ":" + token
                if self.seen.get(seen_key) == signature:
                    continue
                self.seen[seen_key] = signature
                self.sequence += 1
                signal = ExperimentalSignal(
                    id=sha256(
                        f"experimental-signal/v1:{strategy}:{token}:{signature}:{self.sequence}".encode()
                    ).hexdigest(),
                    timestamp=now,
                    available_at=now,
                    source="experimental-public-observation-model/v1",
                    strategy_id=strategy,
                    market_id=market.market_id,
                    token_id=token,
                    event_id=market.event_id,
                    eligible=not reasons,
                    fee_rate=fee if fee is not None else 0,
                    hypothesis=STRATEGIES[strategy],
                    uncertainty="Unvalidated empirical horizon-error envelope; no calibrated probability or guaranteed coverage",
                    evidence_ids=evidence_ids,
                    horizon_seconds=self.horizon_seconds,
                    assumptions=(
                        "Observed future bid target is a monetary mark, not terminal outcome probability",
                        "Trailing20 bid median plus median prior matured horizon residual",
                        "Prior90th-percentile absolute residual envelope with $.01 policy floor",
                        "Round-trip global fee bound and $.01/share slippage per leg",
                        "Actual execution requires separate current risk approval and observed liquidity",
                    ),
                    reasons=tuple(sorted(set(reasons))),
                    diagnostics=diagnostics,
                    **values,
                )
                results.append(signal)
                self.counts[strategy] += 1
                self.rejections.update(signal.reasons)
        self.latest_signals = results[-200:]
        return results

    def checkpoint(self):
        return {
            "version": "1.0",
            "policy": self.policy,
            "sequence": self.sequence,
            "history": {t: [asdict(p) for p in h] for t, h in self.history.items()},
            "seen": self.seen,
            "counts": dict(self.counts),
            "rejections": dict(self.rejections),
            "intelligence": self.intelligence.checkpoint(),
        }

    def restore(self, data):
        if data.get("version") != "1.0" or data.get("policy") != self.policy:
            raise ValueError("experimental strategy checkpoint mismatch")
        if len(data["history"]) > self.max_tokens or len(data["seen"]) > self.max_tokens * len(self.enabled):
            raise ValueError("oversized strategy checkpoint")
        history = {}
        for token, raw in data["history"].items():
            if len(raw) > self.history_size:
                raise ValueError("oversized quote history")
            points = [QuotePoint(**r) for r in raw]
            if any(
                p.at.tzinfo is None
                or datetime.fromisoformat(p.available_at).tzinfo is None
                or datetime.fromisoformat(p.available_at) < p.at
                or not 0 < p.bid < p.ask < 1
                for p in points
            ):
                raise ValueError("invalid restored quote")
            if any(right.at <= left.at for left, right in pairwise(points)):
                raise ValueError("unordered restored history")
            history[token] = deque(points, maxlen=self.history_size)
        if not isinstance(data["sequence"], int) or data["sequence"] < 0:
            raise ValueError("invalid signal sequence")
        self.history, self.seen, self.sequence = history, dict(data["seen"]), data["sequence"]
        self.counts, self.rejections = Counter(data["counts"]), Counter(data["rejections"])
        self.intelligence.restore(data["intelligence"])

    def status(self):
        return {
            "registered": list(STRATEGIES),
            "enabled": list(self.enabled),
            "validation_status": "unvalidated",
            "certified_approval_authority": False,
            "signal_counts": dict(self.counts),
            "rejection_counts": dict(self.rejections),
            "history_tokens": len(self.history),
            "history_observations": sum(map(len, self.history.values())),
            "intelligence": self.intelligence.status(),
        }
