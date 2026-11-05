"""Conservative depth-limited execution with durable cumulative acknowledgements.

A write-ahead pending fill bridges the broker and risk SQLite ledgers. Recovery
checks the risk audit before retrying so a crash cannot book a fill twice.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from threading import RLock
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from neraium_poly.contracts import ExecutionReport, OrderBookSnapshot, OrderIntent, RiskDecision
from neraium_poly.risk import RiskEngine, RiskViolation

EPS = 1e-8
TERMINAL = {"filled", "cancelled", "expired", "rejected"}


class ExecutionConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    latency_ms: float = Field(default=100, ge=0)
    max_book_age_seconds: float = Field(default=15, gt=0)
    max_spread: float = Field(default=0.05, gt=0, lt=1)
    participation_rate: float = Field(default=0.10, gt=0, le=1)
    taker_fee_rate: float = Field(default=0.02, ge=0, le=1)
    maker_fee_rate: float = Field(default=0, ge=0, le=1)
    maker_participation_rate: float = Field(default=0.02, ge=0, le=1)


class OrderBroker(Protocol):
    def submit(
        self,
        intent: OrderIntent,
        decision: RiskDecision,
        book: OrderBookSnapshot,
        *,
        now: datetime,
        fee_rate: float | None = None,
        maker: bool = False,
    ) -> ExecutionReport: ...
    def cancel(self, client_order_id: str, *, now: datetime) -> ExecutionReport: ...


class LiveBroker:
    def __init__(self, *args, **kwargs):
        raise RiskViolation("live execution is disabled; separate release authorization required")


class PaperBroker:
    def __init__(self, risk: RiskEngine, path: str = ":memory:", config: ExecutionConfig | None = None):
        if (
            os.getenv("LIVE_TRADING_ENABLED", "false").lower() != "false"
            or os.getenv("PAPER_TRADING", "true").lower() != "true"
        ):
            raise RiskViolation("paper-only execution required")
        if risk is None:
            raise RiskViolation("risk engine required")
        self.risk = risk
        self.config = config or ExecutionConfig()
        self._lock = RLock()
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS orders (
          client_id TEXT PRIMARY KEY, intent_id TEXT UNIQUE NOT NULL,
          intent TEXT NOT NULL, decision TEXT NOT NULL, report TEXT NOT NULL,
          fee_rate REAL NOT NULL, maker INTEGER NOT NULL, submitted TEXT NOT NULL,
          ready TEXT NOT NULL, pending TEXT);
        CREATE TABLE IF NOT EXISTS books (key TEXT PRIMARY KEY, digest TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS book_watermarks (
          exchange TEXT NOT NULL, token TEXT NOT NULL, timestamp TEXT NOT NULL,
          sequence INTEGER NOT NULL, PRIMARY KEY(exchange,token));
        CREATE TABLE IF NOT EXISTS liquidity (
          book TEXT NOT NULL, price REAL NOT NULL, remaining REAL NOT NULL,
          PRIMARY KEY(book,price));
        CREATE TABLE IF NOT EXISTS audit (
          seq INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, action TEXT NOT NULL, payload TEXT NOT NULL);
        """)

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

    def _audit(self, action, payload, now):
        if now.tzinfo is None:
            raise ValueError("timezone-aware clock required")
        self.db.execute(
            "INSERT INTO audit(timestamp,action,payload) VALUES(?,?,?)",
            (now.isoformat(), action, json.dumps(payload, sort_keys=True)),
        )

    def _row(self, client_id):
        row = self.db.execute("SELECT * FROM orders WHERE client_id=?", (client_id,)).fetchone()
        if row is None:
            raise KeyError(client_id)
        return row

    def _report(self, intent, now, *, status="open", filled=0, price=0, fees=0, reason=""):
        return ExecutionReport(
            timestamp=now,
            available_at=now,
            source="paper-broker/v1",
            intent_id=intent.id,
            client_order_id=intent.client_order_id,
            status=status,
            filled_quantity=filled,
            average_price=price,
            fees=fees,
            remaining_quantity=max(0, intent.quantity - filled),
            reason=reason,
        )

    def submit(
        self,
        intent: OrderIntent,
        decision: RiskDecision,
        book: OrderBookSnapshot,
        *,
        now: datetime,
        fee_rate: float | None = None,
        maker: bool = False,
    ) -> ExecutionReport:
        """Idempotently accept an immutable order; immediate matching respects configured latency."""
        if now.tzinfo is None:
            raise ValueError("timezone-aware clock required")
        effective_fee = (
            fee_rate
            if fee_rate is not None
            else (self.config.maker_fee_rate if maker else self.config.taker_fee_rate)
        )
        if not 0 <= effective_fee <= 1:
            raise ValueError("invalid effective fee rate")
        with self._transaction():
            old = self.db.execute(
                "SELECT * FROM orders WHERE client_id=? OR intent_id=?", (intent.client_order_id, intent.id)
            ).fetchone()
            if old:
                if (
                    old["intent"] != intent.model_dump_json()
                    or old["decision"] != decision.model_dump_json()
                    or old["fee_rate"] != effective_fee
                    or bool(old["maker"]) != maker
                ):
                    raise RiskViolation("duplicate identifier with changed order or execution terms")
                report = ExecutionReport.model_validate_json(old["report"])
                # Duplicate submit does not constitute a new market event.
                return report
            approved = False
            try:
                approved = self.risk.validate_approval(intent, decision, now=now)
            except Exception:  # noqa: BLE001 - unavailable risk must fail closed at the service boundary
                approved = False
            reason = ""
            if intent.side != "BUY":
                reason = "unsupported_side"
            elif not approved:
                reason = "risk_approval_unavailable"
            elif intent.available_at > now:
                reason = "future_order"
            elif maker and book.asks and intent.limit_price >= book.asks[0].price:
                reason = "maker_order_would_cross"
            report = self._report(intent, now, status="rejected" if reason else "open", reason=reason)
            self.db.execute(
                """INSERT INTO orders(client_id,intent_id,intent,decision,report,fee_rate,maker,submitted,ready)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    intent.client_order_id,
                    intent.id,
                    intent.model_dump_json(),
                    decision.model_dump_json(),
                    report.model_dump_json(),
                    effective_fee,
                    int(maker),
                    now.isoformat(),
                    (now + timedelta(milliseconds=self.config.latency_ms)).isoformat(),
                ),
            )
            self._audit("submit", {"intent": intent.model_dump(mode="json"), "reason": reason}, now)
        if reason:
            if decision.reservation_id:
                self.risk.release(decision.reservation_id, now=now)
            return report
        return self.process(intent.client_order_id, book, now=now)

    @staticmethod
    def _book_key(book):
        return hashlib.sha256(
            json.dumps(
                [book.exchange, book.token_id, book.sequence, book.timestamp.isoformat()],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    def _risk_ack(self, row, pending):
        decision = RiskDecision.model_validate_json(row["decision"])
        last = None
        for event in self.risk.audit():
            if event["action"] == "fill":
                payload = json.loads(event["payload"])
                if payload["reservation_id"] == decision.reservation_id:
                    last = payload
        return last is not None and all(
            abs(last[key] - pending[key]) <= EPS for key in ("quantity", "average_price", "fees")
        )

    def _finalize(self, row, pending, now):
        intent = OrderIntent.model_validate_json(row["intent"])
        report = self._report(
            intent,
            now,
            status="filled" if pending["quantity"] >= intent.quantity - EPS else "partial",
            filled=pending["quantity"],
            price=pending["average_price"],
            fees=pending["fees"],
        )
        self.db.execute(
            "UPDATE orders SET report=?,pending=NULL WHERE client_id=?",
            (report.model_dump_json(), intent.client_order_id),
        )
        self._audit("fill_ack", report.model_dump(mode="json"), now)
        return report

    def _recover(self, client_id, now):
        """Finish a durable pending fill before reading any new market event."""
        with self._transaction():
            row = self._row(client_id)
            if not row["pending"]:
                return ExecutionReport.model_validate_json(row["report"])
            pending = json.loads(row["pending"])
            intent = OrderIntent.model_validate_json(row["intent"])
            decision = RiskDecision.model_validate_json(row["decision"])
            try:
                if not self._risk_ack(row, pending):
                    self.risk.record_fill(
                        intent,
                        decision,
                        pending["quantity"],
                        pending["average_price"],
                        pending["fees"],
                        now=now,
                    )
            except Exception as exc:  # noqa: BLE001 - preserve a fail-closed risk boundary
                try:
                    if self._risk_ack(row, pending):
                        return self._finalize(row, pending, now)
                except Exception:  # noqa: BLE001 - acknowledgement is unknown until recoverable
                    self._audit("risk_ack_unavailable", {"client_order_id": client_id}, now)
                if not isinstance(exc, RiskViolation):
                    previous = ExecutionReport.model_validate_json(row["report"])
                    held = previous.model_copy(update={"reason": "risk_recovery_pending"})
                    self.db.execute(
                        "UPDATE orders SET report=? WHERE client_id=?", (held.model_dump_json(), client_id)
                    )
                    self._audit("risk_recovery_held", {"client_order_id": client_id}, now)
                    return held
                # Withheld liquidity stays consumed after uncertain acknowledgement.
                # Conservatively never re-offer it to another simulated order.
                previous = ExecutionReport.model_validate_json(row["report"])
                report = self._report(
                    intent,
                    now,
                    status="rejected",
                    filled=previous.filled_quantity,
                    price=previous.average_price,
                    fees=previous.fees,
                    reason="risk_fill_unavailable:" + type(exc).__name__,
                )
                self.db.execute(
                    "UPDATE orders SET report=?,pending=NULL WHERE client_id=?",
                    (report.model_dump_json(), client_id),
                )
                self._audit("risk_fill_rejected", report.model_dump(mode="json"), now)
                if decision.reservation_id:
                    self.risk.release(decision.reservation_id, now=now)
                return report
            return self._finalize(row, pending, now)

    def process(self, client_order_id: str, book: OrderBookSnapshot, *, now: datetime) -> ExecutionReport:
        """Consume displayed depth once per immutable snapshot; never assume hidden liquidity."""
        if now.tzinfo is None:
            raise ValueError("timezone-aware clock required")
        self._recover(client_order_id, now)
        with self._transaction():
            row = self._row(client_order_id)
            intent = OrderIntent.model_validate_json(row["intent"])
            decision = RiskDecision.model_validate_json(row["decision"])
            report = ExecutionReport.model_validate_json(row["report"])
            if report.status in TERMINAL or row["pending"]:
                return report
            if intent.expires_at <= now or decision.expires_at <= now:
                return self._terminal(row, "expired", "order_or_approval_expired", now)
            try:
                valid = self.risk.validate_approval(intent, decision, now=now)
            except Exception:  # noqa: BLE001 - unavailable risk must fail closed at the service boundary
                valid = False
            if not valid:
                return self._terminal(row, "rejected", "risk_approval_unavailable", now)
            if now < datetime.fromisoformat(row["ready"]):
                return report
            if (
                book.available_at > now
                or book.timestamp > now
                or not book.complete
                or (now - book.timestamp).total_seconds() > self.config.max_book_age_seconds
                or book.market_id != intent.market_id
                or book.token_id != intent.token_id
                or not book.asks
                or not book.bids
                or (
                    book.asks
                    and book.bids
                    and book.asks[0].price - book.bids[0].price > self.config.max_spread
                )
                or len({level.price for level in book.asks}) != len(book.asks)
            ):
                return self._terminal(row, "rejected", "invalid_or_stale_book", now)
            watermark = self.db.execute(
                "SELECT timestamp,sequence FROM book_watermarks WHERE exchange=? AND token=?",
                (book.exchange, book.token_id),
            ).fetchone()
            if watermark and (
                book.timestamp < datetime.fromisoformat(watermark["timestamp"])
                or (book.sequence > 0 and watermark["sequence"] > 0 and book.sequence < watermark["sequence"])
            ):
                return self._terminal(row, "rejected", "regressing_book_snapshot", now)
            self.db.execute(
                "INSERT INTO book_watermarks(exchange,token,timestamp,sequence) VALUES(?,?,?,?) "
                "ON CONFLICT(exchange,token) DO UPDATE SET timestamp=excluded.timestamp, "
                "sequence=MAX(sequence,excluded.sequence)",
                (book.exchange, book.token_id, book.timestamp.isoformat(), book.sequence),
            )
            if row["maker"] and book.timestamp <= datetime.fromisoformat(row["submitted"]):
                return report
            key = self._book_key(book)
            digest = hashlib.sha256(
                json.dumps(book.model_dump(mode="json") | {"id": ""}, sort_keys=True).encode()
            ).hexdigest()
            known = self.db.execute("SELECT digest FROM books WHERE key=?", (key,)).fetchone()
            if known and known[0] != digest:
                return self._terminal(row, "rejected", "conflicting_book_snapshot", now)
            if not known:
                self.db.execute("INSERT INTO books(key,digest) VALUES(?,?)", (key, digest))
                for level in book.asks:
                    self.db.execute(
                        "INSERT INTO liquidity(book,price,remaining) VALUES(?,?,?)",
                        (key, level.price, level.size * self.config.participation_rate),
                    )
            needed = intent.quantity - report.filled_quantity
            qty = 0
            principal = 0
            for level in self.db.execute(
                "SELECT price,remaining FROM liquidity WHERE book=? AND price<=? ORDER BY price",
                (key, intent.limit_price + EPS),
            ).fetchall():
                available = level["remaining"]
                if row["maker"]:
                    available = min(
                        available,
                        next(l.size for l in book.asks if l.price == level["price"])
                        * self.config.maker_participation_rate,
                    )
                take = min(needed - qty, available)
                if take > EPS:
                    qty += take
                    principal += take * level["price"]
                    self.db.execute(
                        "UPDATE liquidity SET remaining=remaining-? WHERE book=? AND price=?",
                        (take, key, level["price"]),
                    )
                if qty >= needed - EPS:
                    break
            if qty <= EPS:
                return report
            cumulative_qty = report.filled_quantity + qty
            cumulative_principal = report.filled_quantity * report.average_price + principal
            pending = {
                "quantity": cumulative_qty,
                "average_price": cumulative_principal / cumulative_qty,
                "fees": report.fees + principal * row["fee_rate"],
            }
            self.db.execute(
                "UPDATE orders SET pending=? WHERE client_id=?", (json.dumps(pending), client_order_id)
            )
            self._audit("fill_pending", {"client_order_id": client_order_id, **pending}, now)
        return self._recover(client_order_id, now)

    def _terminal(self, row, status, reason, now):
        intent = OrderIntent.model_validate_json(row["intent"])
        decision = RiskDecision.model_validate_json(row["decision"])
        old = ExecutionReport.model_validate_json(row["report"])
        report = self._report(
            intent,
            now,
            status=status,
            filled=old.filled_quantity,
            price=old.average_price,
            fees=old.fees,
            reason=reason,
        )
        self.db.execute(
            "UPDATE orders SET report=? WHERE client_id=?", (report.model_dump_json(), intent.client_order_id)
        )
        self._audit(status, report.model_dump(mode="json"), now)
        if decision.reservation_id:
            self.risk.release(decision.reservation_id, now=now)
        return report

    def cancel(self, client_order_id: str, *, now: datetime) -> ExecutionReport:
        self._recover(client_order_id, now)
        with self._transaction():
            row = self._row(client_order_id)
            report = ExecutionReport.model_validate_json(row["report"])
            return (
                report
                if report.status in TERMINAL or row["pending"]
                else self._terminal(row, "cancelled", "operator_cancel", now)
            )

    def expire(self, *, now: datetime) -> list[ExecutionReport]:
        results = []
        for row in self.db.execute("SELECT client_id FROM orders ORDER BY client_id").fetchall():
            self._recover(row[0], now)
            with self._transaction():
                order = self._row(row[0])
                intent = OrderIntent.model_validate_json(order["intent"])
                decision = RiskDecision.model_validate_json(order["decision"])
                report = ExecutionReport.model_validate_json(order["report"])
                if (
                    not order["pending"]
                    and report.status not in TERMINAL
                    and min(intent.expires_at, decision.expires_at) <= now
                ):
                    results.append(self._terminal(order, "expired", "order_or_approval_expired", now))
        return results

    def history(self) -> list[ExecutionReport]:
        with self._lock:
            return [
                ExecutionReport.model_validate_json(row[0])
                for row in self.db.execute("SELECT report FROM orders ORDER BY submitted,client_id")
            ]

    def reconcile(self, *, now: datetime) -> dict:
        """Compare both ledger directions; unresolved acknowledgements are never success."""
        for row in self.db.execute("SELECT client_id FROM orders ORDER BY client_id").fetchall():
            self._recover(row[0], now)
        mismatches = []
        pending_orders = []
        unavailable = []
        with self._transaction():
            rows = self.db.execute("SELECT * FROM orders ORDER BY client_id").fetchall()
            known = {}
            latest_fills = {}
            try:
                for event in self.risk.audit():
                    if event["action"] == "fill":
                        payload = json.loads(event["payload"])
                        latest_fills[payload["reservation_id"]] = payload
            except Exception:  # noqa: BLE001 - unknown audit state cannot certify reconciliation
                unavailable.append("risk_audit_unavailable")
            for row in rows:
                report = ExecutionReport.model_validate_json(row["report"])
                decision = RiskDecision.model_validate_json(row["decision"])
                known[decision.reservation_id] = row["client_id"]
                if row["pending"]:
                    pending_orders.append(row["client_id"])
                acknowledged = latest_fills.get(decision.reservation_id)
                if acknowledged is not None:
                    if any(
                        abs(actual - acknowledged[key]) > EPS
                        for actual, key in (
                            (report.filled_quantity, "quantity"),
                            (report.average_price, "average_price"),
                            (report.fees, "fees"),
                        )
                    ):
                        mismatches.append(row["client_id"])
                elif report.filled_quantity > EPS and not unavailable:
                    mismatches.append(row["client_id"])
            for reservation_id in latest_fills:
                if reservation_id not in known:
                    mismatches.append("orphan-risk-fill:" + reservation_id)
            try:
                positions = [p.model_dump(mode="json") for p in self.risk.positions(now=now)]
                portfolio = self.risk.snapshot(now=now)
            except Exception:  # noqa: BLE001 - unknown portfolio state cannot certify reconciliation
                unavailable.append("risk_portfolio_unavailable")
                positions, portfolio = [], None
        return {
            "consistent": not (mismatches or pending_orders or unavailable),
            "mismatches": sorted(set(mismatches)),
            "pending_orders": pending_orders,
            "unavailable": unavailable,
            "positions": positions,
            "portfolio": portfolio,
            "simulated": True,
        }

    def close(self):
        self.db.close()
