"""SQLite serializes capital decisions, including across independent engine instances.

The broker cannot spend an approval for a changed order, spend it twice, or exceed
its approved fees. Execution acknowledgements are cumulative and idempotent.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta
from threading import RLock
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from neraium_poly.contracts import (
    MarketSnapshot,
    ModelProvenance,
    OrderBookSnapshot,
    OrderIntent,
    PortfolioPosition,
    ProbabilityEstimate,
    RelationshipEvidence,
    RiskDecision,
    TradingOpportunity,
)

EPS = 1e-8


class RiskViolation(ValueError):
    """An execution attempted to violate an immutable approval."""


class RiskLimits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    bankroll: float = Field(default=500, gt=0)
    aggregate_fraction: float = Field(default=0.20, gt=0, le=1)
    market_fraction: float = Field(default=0.05, gt=0, le=1)
    event_fraction: float = Field(default=0.10, gt=0, le=1)
    correlation_fraction: float = Field(default=0.10, gt=0, le=1)
    daily_loss_fraction: float = Field(default=0.05, gt=0, le=1)
    drawdown_fraction: float = Field(default=0.10, gt=0, le=1)
    max_book_age_seconds: float = Field(default=15, gt=0)
    max_market_age_seconds: float = Field(default=3600, gt=0)
    max_estimate_age_seconds: float = Field(default=300, gt=0)
    max_evidence_age_seconds: float = Field(default=3600, gt=0)
    max_spread: float = Field(default=0.05, gt=0, lt=1)
    min_net_edge: float = Field(default=0.03, gt=0, lt=1)
    max_liquidity_participation: float = Field(default=0.25, gt=0, le=1)
    approval_ttl_seconds: float = Field(default=10, gt=0)
    standard_min: float = Field(default=2, gt=0)
    standard_max: float = Field(default=5, gt=0)
    high_min: float = Field(default=5, gt=0)
    high_max: float = Field(default=15, gt=0)
    exceptional_min: float = Field(default=15, gt=0)
    exceptional_max: float = Field(default=25, gt=0)
    kelly_fraction: float = Field(default=0.10, ge=0, le=0.25)

    @model_validator(mode="after")
    def ranges(self):
        for tier in ("standard", "high", "exceptional"):
            if getattr(self, tier + "_min") > getattr(self, tier + "_max"):
                raise ValueError("position minimum exceeds maximum")
        return self


def _digest(intent: OrderIntent) -> str:
    return hashlib.sha256(intent.model_dump_json().encode()).hexdigest()


def _time(now: datetime) -> str:
    if now.tzinfo is None:
        raise ValueError("timezone-aware clock required")
    return now.isoformat()


class RiskEngine:
    def __init__(self, path: str = ":memory:", limits: RiskLimits | None = None):
        if (
            os.getenv("LIVE_TRADING_ENABLED", "false").lower() != "false"
            or os.getenv("PAPER_TRADING", "true").lower() != "true"
        ):
            raise RiskViolation("paper mode required")
        self.limits = limits or RiskLimits()
        self._lock = RLock()
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS account (
          id INTEGER PRIMARY KEY CHECK(id=1), cash REAL NOT NULL, peak REAL NOT NULL,
          realized REAL NOT NULL DEFAULT 0, kill INTEGER NOT NULL DEFAULT 0,
          limits TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS reservations (
          id TEXT PRIMARY KEY, client_id TEXT UNIQUE NOT NULL, intent_id TEXT UNIQUE NOT NULL,
          digest TEXT NOT NULL, intent TEXT NOT NULL, opportunity TEXT NOT NULL,
          decision TEXT NOT NULL, market TEXT NOT NULL, token TEXT NOT NULL,
          event TEXT NOT NULL, cluster TEXT NOT NULL, expires TEXT NOT NULL,
          remaining REAL NOT NULL, quantity REAL NOT NULL DEFAULT 0,
          principal REAL NOT NULL DEFAULT 0, fees REAL NOT NULL DEFAULT 0,
          released INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS positions (
          token TEXT PRIMARY KEY, market TEXT NOT NULL, event TEXT NOT NULL,
          cluster TEXT NOT NULL, quantity REAL NOT NULL, principal REAL NOT NULL,
          fees REAL NOT NULL, mark REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS daily (day TEXT PRIMARY KEY, pnl REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS audit (
          seq INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, action TEXT NOT NULL,
          payload TEXT NOT NULL);
        """)
        with self._transaction():
            row = self.db.execute("SELECT limits FROM account WHERE id=1").fetchone()
            encoded = self.limits.model_dump_json()
            if row and row[0] != encoded:
                raise RiskViolation("persistent risk limits differ; explicit migration required")
            self.db.execute(
                "INSERT OR IGNORE INTO account(id,cash,peak,limits) VALUES(1,?,?,?)",
                (self.limits.bankroll, self.limits.bankroll, encoded),
            )

    @contextmanager
    def _transaction(self):
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def _audit(self, action: str, payload: dict, now: datetime):
        self.db.execute(
            "INSERT INTO audit(timestamp,action,payload) VALUES(?,?,?)",
            (_time(now), action, json.dumps(payload, sort_keys=True)),
        )

    def _expire(self, now: datetime):
        # Parse timestamps rather than compare strings containing differing UTC offsets.
        for row in self.db.execute("SELECT id,expires FROM reservations WHERE released=0"):
            if datetime.fromisoformat(row["expires"]) <= now:
                self.db.execute("UPDATE reservations SET released=1,remaining=0 WHERE id=?", (row["id"],))
                self._audit("expired", {"reservation_id": row["id"]}, now)

    def _state(self, now: datetime) -> dict:
        account = self.db.execute("SELECT * FROM account WHERE id=1").fetchone()
        positions = self.db.execute("SELECT * FROM positions").fetchall()
        reserved = self.db.execute("SELECT COALESCE(SUM(remaining),0) FROM reservations").fetchone()[0]
        invested = sum(p["principal"] + p["fees"] for p in positions)
        equity = account["cash"] + sum(p["quantity"] * p["mark"] for p in positions)
        daily = self.db.execute("SELECT pnl FROM daily WHERE day=?", (now.date().isoformat(),)).fetchone()
        return {
            "cash": account["cash"],
            "reserved": reserved,
            "invested": invested,
            "exposure": invested + reserved,
            "equity": equity,
            "peak": account["peak"],
            "realized_pnl": account["realized"],
            "daily_pnl": daily[0] if daily else 0,
            "kill_switch": bool(account["kill"]),
            "drawdown": max(0, account["peak"] - equity),
            "simulated": True,
        }

    def snapshot(self, *, now: datetime) -> dict:
        _time(now)
        with self._transaction():
            self._expire(now)
            return self._state(now)

    def _exposure(self, column: str, value: str) -> float:
        # Column comes only from internal constants.
        invested = self.db.execute(
            f"SELECT COALESCE(SUM(principal+fees),0) FROM positions WHERE {column}=?", (value,)
        ).fetchone()[0]
        reserved = self.db.execute(
            f"SELECT COALESCE(SUM(remaining),0) FROM reservations WHERE {column}=?", (value,)
        ).fetchone()[0]
        return invested + reserved

    def approve(
        self,
        intent: OrderIntent,
        opportunity: TradingOpportunity,
        market: MarketSnapshot,
        book: OrderBookSnapshot,
        evidence: Sequence[RelationshipEvidence],
        *,
        now: datetime,
        estimate: ProbabilityEstimate | None = None,
        model: ModelProvenance | None = None,
        correlation_group: str = "unclassified",
    ) -> RiskDecision:
        """Validate all supplied research inputs and reserve fees-inclusive capital atomically.

        Unknown correlation membership shares one conservative bucket. Assigning groups
        is an explicit research configuration decision, never inferred from confidence.
        Database failures propagate: callers MUST treat unavailable risk as rejection.
        """
        _time(now)
        with self._transaction():
            self._expire(now)
            old = self.db.execute(
                "SELECT * FROM reservations WHERE client_id=? OR intent_id=?",
                (intent.client_order_id, intent.id),
            ).fetchone()
            if old:
                if old["digest"] == _digest(intent) and not old["released"]:
                    return RiskDecision.model_validate_json(old["decision"])
                return self._reject(intent, ["duplicate_or_changed_order"], now)
            reasons = self._checks(intent, opportunity, market, book, evidence, now, estimate, model)
            state = self._state(now)
            if state["kill_switch"]:
                reasons.append("kill_switch")
            if state["daily_pnl"] <= -self.limits.bankroll * self.limits.daily_loss_fraction + EPS:
                reasons.append("daily_loss_limit")
            if state["drawdown"] >= state["peak"] * self.limits.drawdown_fraction - EPS:
                reasons.append("drawdown_circuit_breaker")
            cost = intent.limit_price * intent.quantity * (1 + opportunity.fee_rate)
            if cost > state["cash"] - state["reserved"] + EPS:
                reasons.append("insufficient_cash")
            if state["exposure"] + cost > self.limits.bankroll * self.limits.aggregate_fraction + EPS:
                reasons.append("aggregate_exposure")
            for column, value, fraction in (
                ("market", intent.market_id, self.limits.market_fraction),
                ("event", intent.event_id, self.limits.event_fraction),
                ("cluster", correlation_group, self.limits.correlation_fraction),
            ):
                if self._exposure(column, value) + cost > self.limits.bankroll * fraction + EPS:
                    reasons.append(column + "_exposure")
            if reasons:
                return self._reject(intent, reasons, now)
            expiry = min(intent.expires_at, now + timedelta(seconds=self.limits.approval_ttl_seconds))
            reservation = str(uuid4())
            decision = RiskDecision(
                timestamp=now,
                available_at=now,
                source="risk/v1",
                intent_id=intent.id,
                approved=True,
                reasons=("approved",),
                approved_notional=cost,
                reservation_id=reservation,
                expires_at=expiry,
            )
            self.db.execute(
                """INSERT INTO reservations
                (id,client_id,intent_id,digest,intent,opportunity,decision,market,token,event,cluster,expires,remaining)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    reservation,
                    intent.client_order_id,
                    intent.id,
                    _digest(intent),
                    intent.model_dump_json(),
                    opportunity.model_dump_json(),
                    decision.model_dump_json(),
                    intent.market_id,
                    intent.token_id,
                    intent.event_id,
                    correlation_group,
                    expiry.isoformat(),
                    cost,
                ),
            )
            self._audit(
                "approved",
                {"intent": intent.model_dump(mode="json"), "decision": decision.model_dump(mode="json")},
                now,
            )
            return decision

    def _reject(self, intent: OrderIntent, reasons: list[str], now: datetime) -> RiskDecision:
        decision = RiskDecision(
            timestamp=now,
            available_at=now,
            source="risk/v1",
            intent_id=intent.id,
            approved=False,
            reasons=tuple(sorted(set(reasons))),
            approved_notional=0,
            expires_at=now,
        )
        self._audit(
            "rejected",
            {"intent": intent.model_dump(mode="json"), "decision": decision.model_dump(mode="json")},
            now,
        )
        return decision

    def _checks(self, intent, opportunity, market, book, evidence, now, estimate, model):
        reasons = []
        if any(r.available_at > now for r in (intent, opportunity, market, book, *evidence)):
            reasons.append("future_information")
        if intent.expires_at.tzinfo is None or intent.expires_at <= now:
            reasons.append("expired_order")
        if intent.side != "BUY" or opportunity.side != "BUY":
            reasons.append("unsupported_side")
        if (
            intent.opportunity_id != opportunity.id
            or intent.market_id != market.market_id
            or intent.token_id != market.token_id
            or intent.event_id != market.event_id
            or opportunity.market_id != intent.market_id
            or opportunity.token_id != intent.token_id
            or opportunity.event_id != intent.event_id
            or book.market_id != intent.market_id
            or book.token_id != intent.token_id
            or book.exchange != market.exchange
            or intent.tier != opportunity.tier
        ):
            reasons.append("identity_mismatch")
        if (now - market.timestamp).total_seconds() > self.limits.max_market_age_seconds:
            reasons.append("stale_market")
        if estimate is None or model is None:
            reasons.append("missing_model_provenance")
        if not opportunity.calibrated or (estimate is not None and not estimate.calibrated):
            reasons.append("uncalibrated_probability")
        if (
            estimate is not None
            and (now - estimate.timestamp).total_seconds() > self.limits.max_estimate_age_seconds
        ):
            reasons.append("stale_estimate")
        if market.status != "active" or not market.resolution_rules or not market.resolution_source:
            reasons.append("unverified_market_rules")
        if market.end_time and (market.end_time.tzinfo is None or market.end_time <= now):
            reasons.append("market_ended")
        if not book.complete or not book.bids or not book.asks:
            reasons.append("missing_liquidity")
        if (now - book.timestamp).total_seconds() > self.limits.max_book_age_seconds:
            reasons.append("stale_book")
        if book.bids and book.asks and book.asks[0].price - book.bids[0].price > self.limits.max_spread:
            reasons.append("large_spread")
        if intent.quantity + EPS < market.min_order_size:
            reasons.append("minimum_order_size")
        ticks = intent.limit_price / market.tick_size
        if abs(ticks - round(ticks)) > EPS:
            reasons.append("tick_size")
        notional = intent.quantity * intent.limit_price
        if (
            not getattr(self.limits, intent.tier + "_min") - EPS
            <= notional
            <= getattr(self.limits, intent.tier + "_max") + EPS
        ):
            reasons.append("position_tier_limit")
        executable = sum(level.size for level in book.asks if level.price <= intent.limit_price + EPS)
        if intent.quantity > executable * self.limits.max_liquidity_participation + EPS:
            reasons.append("liquidity_participation")
        if not opportunity.evidence_ids or set(opportunity.evidence_ids) - {e.id for e in evidence}:
            reasons.append("missing_evidence")
        cited = [e for e in evidence if e.id in opportunity.evidence_ids]
        if any(not e.qualified or e.confidence < 0.7 or not e.observation_ids for e in cited):
            reasons.append("unqualified_evidence")
        if any((now - e.timestamp).total_seconds() > self.limits.max_evidence_age_seconds for e in cited):
            reasons.append("stale_evidence")
        # Independently recompute net EV at this order's worst execution price.
        edge = opportunity.conservative_probability - intent.limit_price * (1 + opportunity.fee_rate)
        edge -= opportunity.slippage
        if edge < self.limits.min_net_edge - EPS or opportunity.net_edge < self.limits.min_net_edge - EPS:
            reasons.append("insufficient_net_edge")
        if opportunity.conservative_probability > opportunity.estimated_probability + EPS:
            reasons.append("invalid_conservative_probability")
        if estimate is not None:
            # Bind the qualified evidence to this exact estimate. An opportunity
            # cannot retrofit later findings onto an unsupported old estimate.
            if (
                not estimate.evidence_ids
                or len(set(estimate.evidence_ids)) != len(estimate.evidence_ids)
                or set(estimate.evidence_ids) != set(opportunity.evidence_ids)
            ):
                reasons.append("estimate_evidence_mismatch")
            if (
                any(item.available_at > estimate.available_at for item in cited)
                or estimate.available_at > opportunity.available_at
                or opportunity.available_at > intent.available_at
                or (model is not None and model.available_at > estimate.available_at)
            ):
                reasons.append("noncausal_provenance")
        if estimate is not None and (
            estimate.id != opportunity.estimate_id
            or estimate.market_id != intent.market_id
            or estimate.token_id != intent.token_id
            or estimate.available_at > now
            or opportunity.conservative_probability > estimate.lower + EPS
            or abs(opportunity.estimated_probability - estimate.probability) > EPS
        ):
            reasons.append("estimate_mismatch")
        if model is not None and (
            not model.approved
            or model.available_at > now
            or model.training_end.tzinfo is None
            or model.training_end >= now
            or (estimate is not None and model.training_end >= estimate.timestamp)
            or not model.artifact_hash
            or estimate is None
            or estimate.model_id != model.id
        ):
            reasons.append("unapproved_model")
        if intent.tier == "exceptional":
            independent = len({e.source for e in cited})
            disjoint = len({oid for e in cited for oid in e.observation_ids}) == sum(
                len(e.observation_ids) for e in cited
            )
            if (
                not opportunity.calibrated
                or estimate is None
                or not estimate.calibrated
                or model is None
                or model.calibration_samples < 100
                or independent < 2
                or not disjoint
            ):
                reasons.append("exceptional_qualification")
        return reasons

    def _approval(self, intent, decision, now):
        row = self.db.execute("SELECT * FROM reservations WHERE id=?", (decision.reservation_id,)).fetchone()
        account = self.db.execute("SELECT kill FROM account WHERE id=1").fetchone()
        state = self._state(now)
        stopped = (
            state["daily_pnl"] <= -self.limits.bankroll * self.limits.daily_loss_fraction + EPS
            or state["drawdown"] >= state["peak"] * self.limits.drawdown_fraction - EPS
        )
        if (
            not decision.approved
            or row is None
            or row["released"]
            or account["kill"]
            or stopped
            or row["digest"] != _digest(intent)
            or row["decision"] != decision.model_dump_json()
            or decision.expires_at.tzinfo is None
            or intent.expires_at.tzinfo is None
            or decision.expires_at <= now
            or intent.expires_at <= now
        ):
            raise RiskViolation("missing, altered, suspended or expired approval")
        return row

    def validate_approval(self, intent: OrderIntent, decision: RiskDecision, *, now: datetime) -> bool:
        _time(now)
        try:
            with self._transaction():
                self._approval(intent, decision, now)
            return True
        except (RiskViolation, sqlite3.Error):
            return False

    def record_fill(
        self,
        intent: OrderIntent,
        decision: RiskDecision,
        cumulative_quantity: float,
        average_price: float,
        cumulative_fees: float,
        *,
        now: datetime,
    ) -> None:
        """Post cumulative fills once. Invalid execution costs leave all state unchanged."""
        _time(now)
        if not all(math.isfinite(v) for v in (cumulative_quantity, average_price, cumulative_fees)):
            raise RiskViolation("nonfinite fill")
        with self._transaction():
            row = self._approval(intent, decision, now)
            opportunity = TradingOpportunity.model_validate_json(row["opportunity"])
            principal = cumulative_quantity * average_price
            delta_qty = cumulative_quantity - row["quantity"]
            delta_principal = principal - row["principal"]
            delta_fees = cumulative_fees - row["fees"]
            if (
                delta_qty < -EPS
                or cumulative_quantity > intent.quantity + EPS
                or not 0 <= average_price <= intent.limit_price + EPS
                or delta_principal < -EPS
                or delta_fees < -EPS
                or cumulative_fees > principal * opportunity.fee_rate + EPS
                or delta_principal > delta_qty * intent.limit_price + EPS
            ):
                raise RiskViolation("fill exceeds approval or regresses")
            if abs(delta_qty) <= EPS:
                if abs(delta_principal) > EPS or abs(delta_fees) > EPS:
                    raise RiskViolation("duplicate cumulative quantity with changed economics")
                return
            existing = self.db.execute("SELECT * FROM positions WHERE token=?", (intent.token_id,)).fetchone()
            if existing and (
                existing["market"] != intent.market_id
                or existing["event"] != intent.event_id
                or existing["cluster"] != row["cluster"]
            ):
                raise RiskViolation("position identity changed")
            old_qty = existing["quantity"] if existing else 0
            old_principal = existing["principal"] if existing else 0
            old_fees = existing["fees"] if existing else 0
            self.db.execute(
                """INSERT OR REPLACE INTO positions
                (token,market,event,cluster,quantity,principal,fees,mark) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    intent.token_id,
                    intent.market_id,
                    intent.event_id,
                    row["cluster"],
                    old_qty + delta_qty,
                    old_principal + delta_principal,
                    old_fees + delta_fees,
                    existing["mark"] if existing else average_price,
                ),
            )
            self.db.execute("UPDATE account SET cash=cash-? WHERE id=1", (delta_principal + delta_fees,))
            remaining = (
                max(0, intent.quantity - cumulative_quantity)
                * intent.limit_price
                * (1 + opportunity.fee_rate)
            )
            self.db.execute(
                "UPDATE reservations SET quantity=?,principal=?,fees=?,remaining=? WHERE id=?",
                (cumulative_quantity, principal, cumulative_fees, remaining, row["id"]),
            )
            self._audit(
                "fill",
                {
                    "reservation_id": row["id"],
                    "quantity": cumulative_quantity,
                    "average_price": average_price,
                    "fees": cumulative_fees,
                },
                now,
            )

    def release(self, reservation_id: str, *, now: datetime) -> None:
        with self._transaction():
            self.db.execute("UPDATE reservations SET released=1,remaining=0 WHERE id=?", (reservation_id,))
            self._audit("release", {"reservation_id": reservation_id}, now)

    def kill_switch(self, active: bool, *, now: datetime) -> None:
        with self._transaction():
            self.db.execute("UPDATE account SET kill=? WHERE id=1", (int(active),))
            if active:
                self.db.execute("UPDATE reservations SET released=1,remaining=0 WHERE released=0")
            self._audit("kill_switch", {"active": active}, now)

    def mark(self, prices: dict[str, float], *, now: datetime) -> dict:
        if any(not math.isfinite(p) or not 0 <= p <= 1 for p in prices.values()):
            raise RiskViolation("invalid mark")
        with self._transaction():
            for token, price in prices.items():
                self.db.execute("UPDATE positions SET mark=? WHERE token=?", (price, token))
            state = self._state(now)
            self.db.execute("UPDATE account SET peak=MAX(peak,?) WHERE id=1", (state["equity"],))
            self._audit("mark", prices, now)
            return self._state(now)

    def settle(
        self, token_id: str, payout: float, *, now: datetime, rules_verified: bool, resolution_source: str
    ) -> float:
        """Simulation settlement only; uncertain resolution is explicitly withheld."""
        if not rules_verified or not resolution_source or payout not in (0, 1):
            raise RiskViolation("unsupported or unverified settlement")
        with self._transaction():
            row = self.db.execute("SELECT * FROM positions WHERE token=?", (token_id,)).fetchone()
            if row is None:
                return 0
            pnl = row["quantity"] * payout - row["principal"] - row["fees"]
            self.db.execute(
                "UPDATE account SET cash=cash+?,realized=realized+? WHERE id=1",
                (row["quantity"] * payout, pnl),
            )
            self.db.execute("DELETE FROM positions WHERE token=?", (token_id,))
            self.db.execute("UPDATE reservations SET released=1,remaining=0 WHERE token=?", (token_id,))
            self.db.execute(
                "INSERT INTO daily(day,pnl) VALUES(?,?) ON CONFLICT(day) DO UPDATE SET pnl=pnl+?",
                (now.date().isoformat(), pnl, pnl),
            )
            # Realized gains establish a new high-water mark just as marked
            # gains do. Keep this atomic with cash and position reconciliation.
            equity = self._state(now)["equity"]
            self.db.execute("UPDATE account SET peak=MAX(peak,?) WHERE id=1", (equity,))
            self._audit(
                "simulated_settlement",
                {"token_id": token_id, "payout": payout, "pnl": pnl, "source": resolution_source},
                now,
            )
            return pnl

    def positions(self, *, now: datetime) -> list[PortfolioPosition]:
        with self._lock:
            return [
                PortfolioPosition(
                    timestamp=now,
                    available_at=now,
                    source="risk-ledger/v1",
                    market_id=r["market"],
                    token_id=r["token"],
                    event_id=r["event"],
                    quantity=r["quantity"],
                    average_cost=r["principal"] / r["quantity"],
                    mark_price=r["mark"],
                    simulated=True,
                )
                for r in self.db.execute("SELECT * FROM positions ORDER BY token")
            ]

    def size(
        self, opportunity: TradingOpportunity, *, tier: str = "standard", fractional_kelly: bool = False
    ) -> float:
        """Research suggestion in USD, bounded by tier and visible liquidity; never approval."""
        if tier not in ("standard", "high", "exceptional"):
            raise ValueError("unknown tier")
        low, high = getattr(self.limits, tier + "_min"), getattr(self.limits, tier + "_max")
        budget = low
        if fractional_kelly:
            p, price = opportunity.conservative_probability, opportunity.market_probability
            budget = self.limits.bankroll * self.limits.kelly_fraction * max(0, (p - price) / (1 - price))
        budget = min(
            high,
            budget,
            opportunity.liquidity * opportunity.market_probability * self.limits.max_liquidity_participation,
        )
        return budget if budget >= low and opportunity.net_edge >= self.limits.min_net_edge else 0

    def stress(self, *, now: datetime) -> dict:
        """All contracts losing simultaneously is the conservative capital stress."""
        state = self.snapshot(now=now)
        return {
            "all_positions_lose": state["cash"],
            "all_positions_and_pending_lose": state["cash"] - state["reserved"],
            "worst_case_loss": state["exposure"],
            "simulated": True,
        }

    def audit(self) -> list[dict]:
        with self._lock:
            return [dict(row) for row in self.db.execute("SELECT * FROM audit ORDER BY seq")]

    def close(self):
        self.db.close()
