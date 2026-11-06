"""An explicitly unvalidated, isolated paper account using shared operational risk.

No certified approval, calibration flag or model provenance is manufactured.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from urllib.parse import urlparse

from neraium_poly.contracts import OrderIntent
from neraium_poly.data import assess_book
from neraium_poly.data.operational import SettlementObservation
from neraium_poly.execution import ExecutionConfig, PaperBroker
from neraium_poly.experimental.contracts import ExperimentalSignal
from neraium_poly.experimental.execution import HorizonExits
from neraium_poly.ops.live_ledger import LiveLedger
from neraium_poly.risk import RiskEngine, RiskLimits, RiskViolation

STRATEGIES = (
    "cross_market_consistency",
    "persistent_relationship",
    "liquidity_spread",
    "event_driven",
    "short_horizon",
    "calibrated_forecast",
)
PUBLIC_BOOK_SOURCES = {"https://clob.polymarket.com", "wss://ws-subscriptions-clob.polymarket.com/ws/market"}
EPS = 1e-8


def identity(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def _paper_only():
    if (
        os.getenv("PAPER_TRADING", "true").lower() != "true"
        or os.getenv("LIVE_TRADING_ENABLED", "false").lower() != "false"
    ):
        raise RiskViolation("experimental execution requires paper-only mode")


def verified_fee_rate(schedule, now):
    if not isinstance(schedule, dict):
        return None
    try:
        if isinstance(schedule["fee_rate"], bool):
            return None
        rate = float(schedule["fee_rate"])
        observed = datetime.fromisoformat(schedule["observed_at"])
        source = urlparse(schedule["source"])
        if (
            not math.isfinite(rate)
            or not 0 <= rate <= 1
            or observed.tzinfo is None
            or not 0 <= (now - observed).total_seconds() <= 300
            or source.scheme != "https"
            or source.hostname not in {"clob.polymarket.com", "gamma-api.polymarket.com"}
            or not schedule.get("reference")
        ):
            return None
        return rate
    except (KeyError, TypeError, ValueError):
        return None


def _isolated_directory(directory, certified_directory):
    directory, certified = Path(directory).resolve(), Path(certified_directory).resolve()
    if directory == certified or certified in directory.parents or directory in certified.parents:
        raise RiskViolation("experimental and certified directories must be disjoint")
    if directory.exists():
        for entry in directory.iterdir():
            if entry.is_symlink() or (entry.is_file() and entry.stat().st_nlink != 1):
                raise RiskViolation("experimental storage aliases are forbidden")
    marker = directory / "account.json"
    expected = {"account_id": "experimental-paper", "mode": "experimental_paper", "schema_version": "1.0"}
    if marker.exists():
        if marker.stat().st_size > 4096 or json.loads(marker.read_text()) != expected:
            raise RiskViolation("experimental account identity mismatch")
    else:
        if directory.exists() and any(directory.glob("*.sqlite*")):
            raise RiskViolation("refusing to adopt unidentified existing account databases")
        directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, (json.dumps(expected, sort_keys=True) + "\n").encode())
            os.fsync(fd)
        finally:
            os.close(fd)
    return directory


class ExperimentalRisk(RiskEngine):
    """Only this isolated account substitutes experimental valuation qualification.

    Certified RiskEngine._checks is still the default and unchanged in meaning.
    Atomic reservation, fee ceilings, fill acknowledgement and all portfolio
    checks are inherited, not emulated or skipped.
    """

    def __init__(self, path, limits=None, *, certified_directory):
        directory = _isolated_directory(Path(path).parent, certified_directory)
        if Path(path).name != "risk.sqlite":
            raise RiskViolation("experimental risk requires its marked account directory")
        super().__init__(str(directory / "risk.sqlite"), limits)

    @staticmethod
    def _decode_opportunity(payload):
        return ExperimentalSignal.model_validate_json(payload)

    def _checks(self, intent, signal, market, book, evidence, now, estimate, model):
        reasons = self._operational_checks(intent, signal, market, book, (), now)
        registered = self.db.execute(
            "SELECT active,suspended,version FROM experimental_registry WHERE strategy=?",
            (signal.strategy_id,),
        ).fetchone()
        if registered is None or not registered["active"] or registered["version"] != signal.strategy_version:
            reasons.append("experimental_strategy_not_registered")
        elif registered["suspended"]:
            reasons.append("experimental_strategy_suspended")
        if self.db.execute(
            "SELECT 1 FROM experimental_settlements WHERE token=?", (signal.token_id,)
        ).fetchone():
            reasons.append("verified_resolved_token")
        if not signal.eligible:
            reasons.append("experimental_signal_not_eligible")
        if signal.valuation_kind != "horizon_mark":
            reasons.append("experimental_execution_supports_horizon_marks_only")
        if not signal.hypothesis or not signal.uncertainty or not signal.assumptions:
            reasons.append("experimental_assumptions_missing")
        if book.id not in signal.evidence_ids or len(set(signal.evidence_ids)) != len(signal.evidence_ids):
            reasons.append("observed_entry_book_evidence_required")
        if book.source not in PUBLIC_BOOK_SOURCES or book.exchange != "polymarket":
            reasons.append("authentic_public_book_source_required")
        if (
            signal.timestamp > now
            or signal.available_at > intent.available_at
            or book.available_at > signal.available_at
        ):
            reasons.append("noncausal_experimental_signal")
        if (now - signal.timestamp).total_seconds() > self.limits.max_estimate_age_seconds:
            reasons.append("stale_experimental_signal")
        if signal.forecast_value is None or signal.lower_value is None or signal.upper_value is None:
            reasons.append("bounded_experimental_valuation_required")
        else:
            if signal.upper_value - signal.lower_value > 0.35 + EPS:
                reasons.append("experimental_uncertainty_limit")
            # A horizon mark is an exit BID target, not terminal settlement probability.
            edge = (
                signal.lower_value * (1 - signal.fee_rate)
                - intent.limit_price * (1 + signal.fee_rate)
                - 2 * signal.slippage_per_share
            )
            if (
                edge < self.limits.min_net_edge - EPS
                or signal.estimated_net_edge is None
                or signal.estimated_net_edge < self.limits.min_net_edge - EPS
                or signal.estimated_net_edge > edge + EPS
            ):
                reasons.append("insufficient_or_overstated_experimental_net_edge")
        if intent.tier == "exceptional":
            reasons.append("exceptional_requires_independently_calibrated_evidence")
        row = self.db.execute(
            "SELECT payload FROM experimental_fee_evidence WHERE signal=?", (signal.id,)
        ).fetchone()
        fee = verified_fee_rate(json.loads(row[0]), now) if row else None
        if fee is None or abs(fee - signal.fee_rate) > EPS:
            reasons.append("verified_current_fee_schedule_required")
        return reasons

    def _approval(self, intent, decision, now):
        row = super()._approval(intent, decision, now)
        signal = self._decode_opportunity(row["opportunity"])
        registered = self.db.execute(
            "SELECT active,suspended FROM experimental_registry WHERE strategy=?", (signal.strategy_id,)
        ).fetchone()
        if registered is None or not registered["active"] or registered["suspended"]:
            raise RiskViolation("experimental strategy inactive or suspended")
        schedule = self.db.execute(
            "SELECT payload FROM experimental_fee_evidence WHERE signal=?", (signal.id,)
        ).fetchone()
        fee = verified_fee_rate(json.loads(schedule[0]), now) if schedule else None
        if fee is None or abs(fee - signal.fee_rate) > EPS:
            raise RiskViolation("experimental fee evidence expired or changed")
        return row


class ExperimentalAccount:
    def __init__(
        self,
        directory,
        certified_directory,
        limits=None,
        enabled_strategies=None,
        execution_config=None,
        clock=None,
    ):
        _paper_only()
        self.directory = _isolated_directory(directory, certified_directory)
        self._lock = RLock()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.ledger = LiveLedger(self.directory)
        self.risk = None
        self.broker = None
        try:
            self.risk = ExperimentalRisk(
                str(self.directory / "risk.sqlite"),
                limits or RiskLimits(),
                certified_directory=certified_directory,
            )
            self.risk.db.executescript("""
            CREATE TABLE IF NOT EXISTS experimental_registry(
              strategy TEXT PRIMARY KEY,version TEXT NOT NULL,active INTEGER NOT NULL,
              suspended INTEGER NOT NULL DEFAULT 0,reason TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS experimental_signals(
              id TEXT PRIMARY KEY,payload TEXT NOT NULL,result TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS experimental_observations(id TEXT PRIMARY KEY,payload TEXT NOT NULL,digest TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS experimental_marks(token TEXT PRIMARY KEY,book TEXT NOT NULL,source_at TEXT NOT NULL,available_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS experimental_inputs(
              id TEXT PRIMARY KEY,book TEXT NOT NULL,market TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS experimental_strategy_peaks(strategy TEXT PRIMARY KEY,peak REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS experimental_settlements(
              id TEXT PRIMARY KEY,strategy TEXT NOT NULL,token TEXT NOT NULL,proof TEXT NOT NULL,pnl REAL NOT NULL,quantity REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS experimental_fee_evidence(signal TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS experimental_tokens(
              token TEXT PRIMARY KEY,strategy TEXT NOT NULL,signal TEXT NOT NULL,
              due TEXT NOT NULL,fee REAL NOT NULL,slippage REAL NOT NULL);
            """)
            enabled = tuple(enabled_strategies) if enabled_strategies is not None else STRATEGIES
            if not set(enabled) <= set(STRATEGIES):
                raise ValueError("unknown experimental strategy")
            for strategy in STRATEGIES:
                self.risk.db.execute(
                    "INSERT INTO experimental_registry(strategy,version,active) VALUES(?,?,?) "
                    "ON CONFLICT(strategy) DO UPDATE SET active=excluded.active",
                    (strategy, "1", int(strategy in enabled)),
                )
            self.config = execution_config or ExecutionConfig()
            self.broker = PaperBroker(self.risk, str(self.directory / "broker.sqlite"), self.config)
            self.exits = HorizonExits(self.risk, self.config)
            self._recover_submissions(self.clock())
            self.reconciliation = self.reconcile(now=self.clock())
            if not self.reconciliation["consistent"]:
                self.risk.kill_switch(True, now=self.clock())
        except BaseException:
            self.close()
            raise

    def _recover_submissions(self, now):
        # No cross-database transaction is assumed. Resolve interrupted submit
        # records conservatively before another strategy can use the capital.
        for row in self.risk.db.execute("SELECT * FROM reservations").fetchall():
            signal = ExperimentalSignal.model_validate_json(row["opportunity"])
            if self.risk.db.execute("SELECT 1 FROM experimental_signals WHERE id=?", (signal.id,)).fetchone():
                continue
            broker = self.broker.db.execute(
                "SELECT report FROM orders WHERE client_id=?", (row["client_id"],)
            ).fetchone()
            if broker is None:
                self.risk.release(row["id"], now=now)
                self._finish(
                    signal, {"status": "error", "reasons": ["restart_cancelled_unacknowledged_submission"]}
                )
            else:
                self._finish(
                    signal,
                    {
                        "status": "submitted",
                        "reasons": ["recovered_durable_broker_submission"],
                        "intent": json.loads(row["intent"]),
                        "risk_decision": json.loads(row["decision"]),
                        "execution": json.loads(broker[0]),
                    },
                )
        self._clean_tokens()

    def _archive_book(self, book):
        payload = book.model_dump_json()
        digest = hashlib.sha256(payload.encode()).hexdigest()
        old = self.risk.db.execute(
            "SELECT digest FROM experimental_observations WHERE id=?", (book.id,)
        ).fetchone()
        if old and old[0] != digest:
            raise RiskViolation("immutable experimental book ID collision")
        self.risk.db.execute(
            "INSERT OR IGNORE INTO experimental_observations VALUES(?,?,?)", (book.id, payload, digest)
        )

    def _finish(self, signal, result):
        result = {
            "account_id": "experimental-paper",
            "validation_status": "unvalidated",
            "signal_id": signal.id,
            "strategy_id": signal.strategy_id,
            **result,
        }
        payload = signal.model_dump_json()
        encoded = json.dumps(result, sort_keys=True)
        self.risk.db.execute(
            "INSERT INTO experimental_signals(id,payload,result) VALUES(?,?,?)", (signal.id, payload, encoded)
        )
        return result

    def submit(self, signal, market, book, *, now, target_notional=2, fee_schedule=None):
        _paper_only()
        if now.tzinfo is None:
            raise ValueError("timezone required")
        with self._lock:
            old = self.risk.db.execute(
                "SELECT payload,result FROM experimental_signals WHERE id=?", (signal.id,)
            ).fetchone()
            if old:
                if old["payload"] != signal.model_dump_json():
                    raise RiskViolation("signal ID reused with different payload")
                return json.loads(old["result"])
            if not signal.eligible:
                return self._finish(
                    signal, {"status": "rejected", "reasons": list(signal.reasons) or ["signal_not_eligible"]}
                )
            if not math.isfinite(target_notional) or target_notional <= 0 or not book.asks:
                return self._finish(
                    signal, {"status": "rejected", "reasons": ["invalid_position_or_missing_book"]}
                )
            existing = self.risk.db.execute(
                "SELECT strategy FROM experimental_tokens WHERE token=?", (book.token_id,)
            ).fetchone()
            if existing:
                return self._finish(
                    signal, {"status": "rejected", "reasons": ["token_position_or_order_already_owned"]}
                )
            price = book.asks[0].price
            quantity = max(target_notional / price, market.min_order_size)
            # Round only to the actual market minimum quantity; never exceed configured tier.
            intent = OrderIntent(
                id=identity("experimental-intent", signal.id),
                timestamp=now,
                available_at=now,
                source="experimental-paper/v1",
                client_order_id=identity("experimental-order", signal.id),
                market_id=market.market_id,
                token_id=market.token_id,
                event_id=market.event_id,
                opportunity_id=signal.id,
                limit_price=price,
                quantity=quantity,
                expires_at=now + timedelta(seconds=30),
                tier=signal.tier,
            )
            self._archive_book(book)
            self.risk.db.execute(
                "INSERT OR IGNORE INTO experimental_inputs VALUES(?,?,?)",
                (book.id, book.model_dump_json(), market.model_dump_json()),
            )
            self.risk.db.execute(
                "INSERT INTO experimental_fee_evidence VALUES(?,?)", (signal.id, json.dumps(fee_schedule))
            )
            try:
                decision = self.risk.approve(
                    intent, signal, market, book, (), now=now, correlation_group="unclassified"
                )
            except Exception as exc:  # noqa: BLE001 - unavailable risk/execution fails closed
                return self._finish(
                    signal, {"status": "error", "reasons": ["risk_unavailable:" + type(exc).__name__]}
                )
            if not decision.approved:
                return self._finish(
                    signal,
                    {
                        "status": "rejected",
                        "reasons": list(decision.reasons),
                        "intent": intent.model_dump(mode="json"),
                        "risk_decision": decision.model_dump(mode="json"),
                    },
                )
            self.risk.db.execute(
                "INSERT INTO experimental_tokens VALUES(?,?,?,?,?,?)",
                (
                    book.token_id,
                    signal.strategy_id,
                    signal.id,
                    (now + timedelta(seconds=signal.horizon_seconds)).isoformat(),
                    signal.fee_rate,
                    signal.slippage_per_share,
                ),
            )
            try:
                report = self.broker.submit(intent, decision, book, now=now, fee_rate=signal.fee_rate)
            except Exception as exc:  # noqa: BLE001 - unavailable risk/execution fails closed
                if decision.reservation_id:
                    self.risk.release(decision.reservation_id, now=now)
                return self._finish(
                    signal, {"status": "error", "reasons": ["broker_unavailable:" + type(exc).__name__]}
                )
            return self._finish(
                signal,
                {
                    "status": "submitted" if report.status != "rejected" else "rejected",
                    "reasons": [report.reason] if report.reason else [],
                    "intent": intent.model_dump(mode="json"),
                    "risk_decision": decision.model_dump(mode="json"),
                    "execution": report.model_dump(mode="json"),
                },
            )

    def cancel(self, client_id, *, now):
        with self._lock:
            result = self.broker.cancel(client_id, now=now)
            self._clean_tokens()
            return result.model_dump(mode="json")

    def _clean_tokens(self):
        for row in self.risk.db.execute("SELECT token FROM experimental_tokens").fetchall():
            held = self.risk.db.execute("SELECT 1 FROM positions WHERE token=?", (row["token"],)).fetchone()
            pending = self.risk.db.execute(
                "SELECT 1 FROM reservations WHERE token=? AND released=0 AND remaining>0", (row["token"],)
            ).fetchone()
            if not held and not pending:
                self.risk.db.execute("DELETE FROM experimental_tokens WHERE token=?", (row["token"],))

    def advance(self, books, *, now, fees=None):
        _paper_only()
        if not isinstance(books, dict):
            books = {b.token_id: b for b in books}
        result = []
        with self._lock:
            for report in self.broker.history():
                if report.status in {"open", "partial"}:
                    row = self.broker.db.execute(
                        "SELECT intent,ready FROM orders WHERE client_id=?", (report.client_order_id,)
                    ).fetchone()
                    intent = OrderIntent.model_validate_json(row["intent"])
                    book = books.get(intent.token_id)
                    if book is None:
                        result.append(self.cancel(report.client_order_id, now=now))
                        continue
                    if (
                        book.source not in PUBLIC_BOOK_SOURCES
                        or book.exchange != "polymarket"
                        or book.market_id != intent.market_id
                        or book.token_id != intent.token_id
                    ):
                        result.append(self.cancel(report.client_order_id, now=now))
                        self.risk._audit(
                            "experimental_execution_withheld",
                            {
                                "order": report.client_order_id,
                                "book_id": book.id,
                                "reason": "invalid_public_execution_source_or_identity",
                            },
                            now,
                        )
                        continue
                    ready = datetime.fromisoformat(row["ready"])
                    if book.available_at < ready or book.timestamp < ready:
                        result.append(
                            {
                                "client_order_id": report.client_order_id,
                                "status": "withheld",
                                "reasons": ["post_latency_source_observation_required"],
                            }
                        )
                        continue
                    self._archive_book(book)
                    reserved = self.risk.db.execute(
                        "SELECT opportunity FROM reservations WHERE client_id=?", (report.client_order_id,)
                    ).fetchone()
                    signal = ExperimentalSignal.model_validate_json(reserved[0])
                    provided = (fees or {}).get(intent.token_id)
                    if provided is not None:
                        current_fee = verified_fee_rate(provided, now)
                        if current_fee is None or current_fee > signal.fee_rate + EPS:
                            result.append(self.cancel(report.client_order_id, now=now))
                            continue
                    result.append(
                        self.broker.process(report.client_order_id, book, now=now).model_dump(mode="json")
                    )
            self.broker.expire(now=now)
            self.exits.expire(now)
            # Stop entry remainders before a horizon sale; no future fill can recreate inventory.
            for row in self.risk.db.execute("SELECT * FROM experimental_tokens").fetchall():
                if datetime.fromisoformat(row["due"]) > now:
                    continue
                for report in self.broker.history():
                    if report.status in {"open", "partial"}:
                        order = self.broker.db.execute(
                            "SELECT intent FROM orders WHERE client_id=?", (report.client_order_id,)
                        ).fetchone()
                        if OrderIntent.model_validate_json(order["intent"]).token_id == row["token"]:
                            result.append(self.cancel(report.client_order_id, now=now))
                self.exits.request(row["token"], row["strategy"], now)
            for exit_order in self.exits.pending():
                token = exit_order["token"]
                book = books.get(token)
                if book is None:
                    continue
                row = self.risk.db.execute(
                    "SELECT * FROM experimental_tokens WHERE token=?", (token,)
                ).fetchone()
                schedule = (fees or {}).get(token, {})
                fee = verified_fee_rate(schedule, now)
                if row:
                    self._archive_book(book)
                    result.append(
                        self.exits.process(
                            exit_order["id"], book, now, fee, row["slippage"], fee_evidence=schedule
                        )
                    )
            self._clean_tokens()
            self.mark(books, now=now)
            self.reconciliation = self.reconcile(now=now)
            if not self.reconciliation["consistent"]:
                self.risk.kill_switch(True, now=now)
        return result

    def mark(self, books, *, now):
        if not isinstance(books, dict):
            books = {b.token_id: b for b in books}
        with self._lock:
            positions = {p.token_id: p.market_id for p in self.risk.positions(now=now)}
            marks = {}
            sources = {}
            for token, book in books.items():
                previous = self.risk.db.execute(
                    "SELECT source_at FROM experimental_marks WHERE token=?", (token,)
                ).fetchone()
                if (
                    token != book.token_id
                    or book.market_id != positions.get(token)
                    or book.exchange != "polymarket"
                    or book.source not in PUBLIC_BOOK_SOURCES
                    or not assess_book(
                        book,
                        now,
                        max_age_seconds=self.risk.limits.max_book_age_seconds,
                        max_spread=self.risk.limits.max_spread,
                    ).healthy
                    or (previous and book.timestamp < datetime.fromisoformat(previous[0]))
                ):
                    continue
                self._archive_book(book)
                marks[token] = book.bids[0].price
                sources[token] = book
            with self.risk._transaction():
                for token, price in marks.items():
                    book = sources[token]
                    self.risk.db.execute("UPDATE positions SET mark=? WHERE token=?", (price, token))
                    self.risk.db.execute(
                        "INSERT INTO experimental_marks VALUES(?,?,?,?) ON CONFLICT(token) DO UPDATE SET book=excluded.book,source_at=excluded.source_at,available_at=excluded.available_at",
                        (token, book.id, book.timestamp.isoformat(), book.available_at.isoformat()),
                    )
                state = self.risk._state(now)
                self.risk.db.execute("UPDATE account SET peak=MAX(peak,?) WHERE id=1", (state["equity"],))
                self.risk._audit(
                    "experimental_mark",
                    {"prices": marks, "books": {token: book.id for token, book in sources.items()}},
                    now,
                )
            self._adaptive(now)
            state = self.risk.snapshot(now=now)
            if (
                state["daily_pnl"] <= -self.risk.limits.bankroll * self.risk.limits.daily_loss_fraction + EPS
                or state["drawdown"] >= state["peak"] * self.risk.limits.drawdown_fraction - EPS
            ):
                self.risk.kill_switch(True, now=now)
                self.risk.db.execute(
                    "UPDATE experimental_registry SET suspended=1,reason='account_loss_or_drawdown_limit'"
                )
            return self.snapshot(now=now)

    def _strategy_pnl(self, strategy):
        realized = self.risk.db.execute(
            "SELECT COALESCE(sum(pnl),0) FROM experimental_exits WHERE strategy=?", (strategy,)
        ).fetchone()[0]
        realized += self.risk.db.execute(
            "SELECT COALESCE(sum(pnl),0) FROM experimental_settlements WHERE strategy=?", (strategy,)
        ).fetchone()[0]
        unrealized = self.risk.db.execute(
            "SELECT COALESCE(sum(p.quantity*p.mark-p.principal-p.fees),0) FROM positions p "
            "JOIN experimental_tokens t ON t.token=p.token WHERE t.strategy=?",
            (strategy,),
        ).fetchone()[0]
        return realized, unrealized

    def _adaptive(self, now):
        for row in self.risk.db.execute("SELECT * FROM experimental_registry").fetchall():
            realized, unrealized = self._strategy_pnl(row["strategy"])
            total = realized + unrealized
            old = self.risk.db.execute(
                "SELECT peak FROM experimental_strategy_peaks WHERE strategy=?", (row["strategy"],)
            ).fetchone()
            peak = max(0, old[0] if old else 0, total)
            self.risk.db.execute(
                "INSERT INTO experimental_strategy_peaks VALUES(?,?) ON CONFLICT(strategy) DO UPDATE SET peak=excluded.peak",
                (row["strategy"], peak),
            )
            losses = self.risk.db.execute(
                "SELECT pnl FROM experimental_exits WHERE strategy=? AND status IN ('filled','expired') AND filled>0 ORDER BY submitted DESC LIMIT 5",
                (row["strategy"],),
            ).fetchall()
            reason = (
                "strategy_loss_limit"
                if total <= -self.risk.limits.bankroll * 0.02 + EPS
                else "strategy_drawdown_limit"
                if peak - total >= self.risk.limits.bankroll * 0.02 - EPS
                else "strategy_losing_streak"
                if len(losses) == 5 and all(r[0] < 0 for r in losses)
                else ""
            )
            if reason and not row["suspended"]:
                self.risk.db.execute(
                    "UPDATE experimental_registry SET suspended=1,reason=? WHERE strategy=?",
                    (reason, row["strategy"]),
                )
                self.risk._audit(
                    "experimental_strategy_suspended",
                    {
                        "strategy_id": row["strategy"],
                        "reason": reason,
                        "realized_pnl": realized,
                        "unrealized_pnl": unrealized,
                    },
                    now,
                )

    def stop(self, *, now):
        with self._lock:
            self.risk.kill_switch(True, now=now)
            for report in self.broker.history():
                if report.status in {"open", "partial"}:
                    self.broker.cancel(report.client_order_id, now=now)
            with self.risk._transaction():
                self.risk.db.execute(
                    "UPDATE experimental_exits SET status='cancelled' WHERE status IN ('open','partial')"
                )
            return self.snapshot(now=now)

    def settle(self, proof, market, *, now, rule_review_hash="", review_actor=""):
        if not isinstance(proof, SettlementObservation):
            raise RiskViolation("native settlement proof required")
        expected = identity(
            market.market_id,
            market.token_id,
            market.outcome,
            market.resolution_rules,
            market.resolution_source,
        )
        if (
            not review_actor
            or rule_review_hash != expected
            or not proof.rules_reviewed
            or proof.available_at > now
            or proof.source not in {"https://clob.polymarket.com", "https://gamma-api.polymarket.com"}
            or not proof.transaction_hash
            or not proof.reporter
            or not proof.condition_id
            or proof.payout not in (0, 1)
            or proof.market_id != market.market_id
            or proof.token_id != market.token_id
            or proof.event_id != market.event_id
            or proof.resolution_rules != market.resolution_rules
            or proof.resolution_source != market.resolution_source
        ):
            raise RiskViolation("verified matching outcome and explicit rule review required")
        with self._lock:
            for report in self.broker.history():
                if report.status in {"open", "partial"}:
                    stored = self.broker.db.execute(
                        "SELECT intent FROM orders WHERE client_id=?", (report.client_order_id,)
                    ).fetchone()
                    if OrderIntent.model_validate_json(stored[0]).token_id == proof.token_id:
                        self.broker.cancel(report.client_order_id, now=now)
            with self.risk._transaction():
                prior = self.risk.db.execute(
                    "SELECT proof,pnl FROM experimental_settlements WHERE id=?", (proof.id,)
                ).fetchone()
                if prior:
                    if prior["proof"] != proof.model_dump_json():
                        raise RiskViolation("settlement ID reused with different proof")
                    return prior["pnl"]
                owner = self.risk.db.execute(
                    "SELECT strategy FROM experimental_tokens WHERE token=?", (proof.token_id,)
                ).fetchone()
                position = self.risk.db.execute(
                    "SELECT * FROM positions WHERE token=?", (proof.token_id,)
                ).fetchone()
                pnl = 0.0
                settled_quantity = position["quantity"] if position is not None else 0.0
                if position is not None:
                    proceeds = position["quantity"] * proof.payout
                    pnl = proceeds - position["principal"] - position["fees"]
                    self.risk.db.execute(
                        "UPDATE account SET cash=cash+?,realized=realized+? WHERE id=1", (proceeds, pnl)
                    )
                    self.risk.db.execute("DELETE FROM positions WHERE token=?", (proof.token_id,))
                    self.risk.db.execute(
                        "UPDATE reservations SET released=1,remaining=0 WHERE token=?", (proof.token_id,)
                    )
                    self.risk.db.execute(
                        "INSERT INTO daily(day,pnl) VALUES(?,?) ON CONFLICT(day) DO UPDATE SET pnl=pnl+?",
                        (now.date().isoformat(), pnl, pnl),
                    )
                    equity = self.risk._state(now)["equity"]
                    self.risk.db.execute("UPDATE account SET peak=MAX(peak,?) WHERE id=1", (equity,))
                self.risk.db.execute(
                    "INSERT INTO experimental_settlements VALUES(?,?,?,?,?,?)",
                    (
                        proof.id,
                        owner[0] if owner else "unattributed",
                        proof.token_id,
                        proof.model_dump_json(),
                        pnl,
                        settled_quantity,
                    ),
                )
                self.risk._audit(
                    "experimental_verified_settlement",
                    {
                        "proof": proof.model_dump(mode="json"),
                        "review_actor": review_actor,
                        "rule_review_hash": rule_review_hash,
                        "pnl": pnl,
                    },
                    now,
                )
            self._clean_tokens()
            self._adaptive(now)
            return pnl

    def reconcile(self, *, now):
        result = self.broker.reconcile(now=now)
        mismatches = list(result["mismatches"])
        expected = {}
        entry_cost = 0.0
        for row in self.risk.db.execute("SELECT token,quantity,principal,fees FROM reservations"):
            expected[row["token"]] = expected.get(row["token"], 0) + row["quantity"]
            entry_cost += row["principal"] + row["fees"]
        returned = realized = removed_basis = 0.0
        for row in self.risk.db.execute("SELECT token,filled,proceeds,fees,pnl FROM experimental_exits"):
            expected[row["token"]] = expected.get(row["token"], 0) - row["filled"]
            returned += row["proceeds"] - row["fees"]
            realized += row["pnl"]
            removed_basis += row["proceeds"] - row["fees"] - row["pnl"]
        for row in self.risk.db.execute("SELECT token,proof,quantity,pnl FROM experimental_settlements"):
            expected[row["token"]] = expected.get(row["token"], 0) - row["quantity"]
            payout = json.loads(row["proof"])["payout"] * row["quantity"]
            returned += payout
            realized += row["pnl"]
            removed_basis += payout - row["pnl"]
        actual = {
            row["token"]: row["quantity"]
            for row in self.risk.db.execute("SELECT token,quantity FROM positions")
        }
        for token in set(expected) | set(actual):
            if abs(expected.get(token, 0) - actual.get(token, 0)) > EPS:
                mismatches.append("experimental_inventory:" + token)
        state = self.risk.snapshot(now=now)
        if abs(state["cash"] - (self.risk.limits.bankroll - entry_cost + returned)) > EPS:
            mismatches.append("experimental_cash")
        if abs(state["realized_pnl"] - realized) > EPS:
            mismatches.append("experimental_realized_pnl")
        if abs(state["invested"] - (entry_cost - removed_basis)) > EPS:
            mismatches.append("experimental_cost_basis")
        result.update(
            consistent=result["consistent"] and not mismatches,
            mismatches=sorted(set(mismatches)),
            experimental_inventory_reconciled=not any("experimental_inventory" in m for m in mismatches),
            experimental_cash_reconciled="experimental_cash" not in mismatches,
        )
        return result

    def snapshot(self, *, now):
        with self._lock:
            state = self.risk.snapshot(now=now)
            history = self.broker.history()
            buy_fill_events = self.risk.db.execute(
                "SELECT count(*) FROM audit WHERE action='fill'"
            ).fetchone()[0]
            exit_fill_events = self.risk.db.execute(
                "SELECT count(*) FROM audit WHERE action='experimental_exit_fill'"
            ).fetchone()[0]
            strategies = []
            for row in self.risk.db.execute("SELECT * FROM experimental_registry ORDER BY strategy"):
                counts = self.risk.db.execute(
                    "SELECT count(*) AS n,sum(json_extract(result,'$.status')='rejected') AS rejected, "
                    "sum(json_extract(result,'$.status')='submitted') AS submitted FROM experimental_signals "
                    "WHERE json_extract(payload,'$.strategy_id')=?",
                    (row["strategy"],),
                ).fetchone()
                pnl, unrealized = self._strategy_pnl(row["strategy"])
                peak = self.risk.db.execute(
                    "SELECT peak FROM experimental_strategy_peaks WHERE strategy=?", (row["strategy"],)
                ).fetchone()
                strategies.append(
                    {
                        "strategy_id": row["strategy"],
                        "registered": bool(row["active"]),
                        "suspended": bool(row["suspended"]),
                        "suspension_reason": row["reason"],
                        "signals": counts["n"],
                        "rejected": counts["rejected"] or 0,
                        "orders": counts["submitted"] or 0,
                        "simulated_realized_pnl": pnl,
                        "simulated_unrealized_pnl": unrealized,
                        "max_drawdown": max(0, (peak[0] if peak else 0) - pnl - unrealized),
                        "baseline": "cash_hold_no_trade",
                        "validation_status": "unvalidated",
                    }
                )
            return {
                "account_id": "experimental-paper",
                "mode": "experimental_paper",
                "validation_status": "unvalidated",
                "initial_bankroll": self.risk.limits.bankroll,
                "bankroll": state["equity"],
                **state,
                "simulated_pnl": state["equity"] - self.risk.limits.bankroll,
                "simulated_realized_pnl": state["realized_pnl"],
                "simulated_unrealized_pnl": state["equity"]
                - self.risk.limits.bankroll
                - state["realized_pnl"],
                "orders": [r.model_dump(mode="json") for r in history],
                "fills": buy_fill_events + exit_fill_events,
                "buy_fill_events": buy_fill_events,
                "exit_fill_events": exit_fill_events,
                "filled_orders": sum(r.filled_quantity > EPS for r in history),
                "orders_attempted": self.risk.db.execute(
                    "SELECT count(*) FROM experimental_signals WHERE json_extract(result,'$.intent') IS NOT NULL"
                ).fetchone()[0],
                "orders_submitted": len(history),
                "positions": [p.model_dump(mode="json") for p in self.risk.positions(now=now)],
                "exits": [
                    dict(r)
                    for r in self.risk.db.execute("SELECT * FROM experimental_exits ORDER BY submitted")
                ],
                "strategies": strategies,
                "reconciliation": getattr(self, "reconciliation", None),
            }

    def close(self):
        if self.broker:
            self.broker.close()
            self.broker = None
        if self.risk:
            self.risk.close()
            self.risk = None
        if getattr(self, "ledger", None):
            self.ledger.close()
            self.ledger = None
