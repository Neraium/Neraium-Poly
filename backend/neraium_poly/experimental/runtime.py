"""Separate experimental process: public observations in, isolated paper capital out."""

import asyncio
import hashlib
import json
import logging
import shutil
from collections import Counter, deque
from datetime import UTC, datetime, timedelta
from threading import RLock

import httpx
from pydantic import Field

from neraium_poly.contracts import Record
from neraium_poly.data import EventStore, assess_book
from neraium_poly.experimental.config import ExperimentalConfig
from neraium_poly.experimental.contracts import ExperimentalSignal, SharedMarketFrame
from neraium_poly.experimental.feed import SharedFeedClient
from neraium_poly.experimental.fees import AuditedFeeAdapter, merge_fee_observations
from neraium_poly.experimental.migration import strategy_code_hash
from neraium_poly.experimental.strategies import ExperimentalStrategyEngine
from neraium_poly.experimental.trace import DecisionTrace
from neraium_poly.research.archive import QuoteArchive
from neraium_poly.research.phase11.framework import load_summary
from neraium_poly.settings import Settings

log = logging.getLogger(__name__)


class ExperimentalRelationshipDefinition(Record):
    relationship_id: str
    definition: dict


class ExperimentalCycle(Record):
    account_id: str = "experimental-paper"
    source_frame_id: str
    observed_book_ids: tuple[str, ...]
    market_record_ids: tuple[str, ...] = ()
    fee_evidence_ids: tuple[str, ...] = ()
    strategy_code_sha256: str = ""
    relationship_definition_ids: tuple[str, ...] = ()
    relationship_evidence_ids: tuple[str, ...] = ()
    signal_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    rejection_counts: dict[str, int]
    signal_digest: str
    representative_rejections: tuple[ExperimentalSignal, ...] = ()
    decision_trace: dict = Field(default_factory=dict)
    note: str = "Non-executable setup rejections aggregated; all eligible signals, risk decisions and trades retained individually"


class ExperimentalRuntime:
    def __init__(self, config: ExperimentalConfig, *, account=None, feed=None, clock=None, fee_adapter=None):
        Settings.from_env()
        self.config = config
        self.clock = clock or (lambda: datetime.now(UTC))
        self._lock = RLock()
        if account is None:
            from neraium_poly.experimental.account import ExperimentalAccount

            account = ExperimentalAccount(
                config.data_dir,
                config.certified_directory,
                limits=config.risk_limits,
                enabled_strategies=config.enabled_strategies,
                clock=self.clock,
            )
        self.account = account
        self.ledger = account.ledger
        self.model_hash = strategy_code_hash()
        previous_hash = self.ledger.get("strategy_code_hash")
        if previous_hash is not None and previous_hash != self.model_hash:
            account.close()
            raise ValueError("Experimental model code changed; explicit research baseline migration required")
        self.events = EventStore(config.data_dir / "events.sqlite")
        self.archive = QuoteArchive(self.events, self.ledger.get("quote_archive", {}))
        self.engine = ExperimentalStrategyEngine(
            enabled=config.enabled_strategies, max_tokens=config.max_tokens
        )
        checkpoint = self.ledger.get("strategy_engine")
        if checkpoint:
            self.engine.restore(checkpoint)
        self.trace = DecisionTrace(epoch_started_at=self.clock())
        trace_state = self.ledger.get("decision_trace", {})
        if trace_state:
            self.trace.restore(trace_state["checkpoint"])
        self.trace_cursors = trace_state.get(
            "cursors",
            {
                "risk": self.account.risk.db.execute("SELECT COALESCE(MAX(seq),0) FROM audit").fetchone()[0],
                "broker": self.account.broker.db.execute("SELECT COALESCE(MAX(seq),0) FROM audit").fetchone()[
                    0
                ],
            },
        )
        self.event_intelligence = None
        if config.event_research_enabled:
            from neraium_poly.research.phase12.runtime import EventResearchRuntime

            try:
                self.event_intelligence = EventResearchRuntime(
                    config.data_dir / "event-intelligence",
                    clock=self.clock,
                    dataset_path=config.event_dataset_path,
                    state=self.ledger.get("event_intelligence", {}),
                    interval=config.event_forecast_interval,
                    max_forecasts=config.event_forecasts_per_cycle,
                    max_bytes=config.event_ledger_mb * 1024 * 1024,
                )
            except Exception as error:
                self.event_research_initialization_error = f"{type(error).__name__}:{str(error)[:160]}"
                log.exception("event_research_startup_withheld")
        self.feed = feed or SharedFeedClient(config.source_url)
        self.fee_adapter = fee_adapter or AuditedFeeAdapter(
            self.events, self._budget_ok, client=httpx.AsyncClient(timeout=5, follow_redirects=False)
        )
        self.fees = self.ledger.get("observed_fees", {})
        self.fee_attempts = {}
        self.totals = self.ledger.get(
            "experimental_totals",
            {"cycles": 0, "signals": 0, "qualified_opportunities": 0, "observations": 0},
        )
        self.rejections = Counter(self.ledger.get("experimental_rejections", {}))
        self.activity = deque(self.ledger.get("experimental_activity", []), maxlen=15)
        self.selected = self.ledger.get("selected_tokens", [])
        self.mark_sources = self.ledger.get("mark_sources", {})
        self.last_frame = None
        self.last_cycle = None
        self.last_success = None
        self.last_error = None
        self.fee_error = None
        self.stopping = False
        self.started = self.clock()

    def _budget_ok(self):
        size = sum(p.stat().st_size for p in self.config.data_dir.glob("*.sqlite*") if p.is_file())
        return (
            size < self.config.max_archive_mb * 1024 * 1024
            and shutil.disk_usage(self.config.data_dir).free >= self.config.min_free_disk_mb * 1024 * 1024
        )

    def _save(self):
        if self.event_intelligence is not None:
            try:
                self.ledger.put("event_intelligence", self.event_intelligence.checkpoint())
            except Exception as error:
                self.event_intelligence.last_error = f"event_checkpoint_failed:{type(error).__name__}"
                log.exception("event_checkpoint_withheld")
        self.ledger.put(
            "decision_trace", {"checkpoint": self.trace.checkpoint(), "cursors": self.trace_cursors}
        )
        self.ledger.put("strategy_code_hash", self.model_hash)
        self.ledger.put("mark_sources", self.mark_sources)
        self.ledger.put("strategy_engine", self.engine.checkpoint())
        self.ledger.put("quote_archive", self.archive.state)
        self.ledger.put("observed_fees", self.fees)
        self.ledger.put("experimental_totals", self.totals)
        self.ledger.put("experimental_rejections", dict(self.rejections))
        self.ledger.put("experimental_activity", list(self.activity))
        self.ledger.put("selected_tokens", self.selected)

    @property
    def suspended(self):
        return self.account.snapshot(now=self.clock())["kill_switch"]

    def stop(self):
        with self._lock:
            self.account.stop(now=self.clock())
            self._trace_execution()
            self.activity.append(f"{self.clock().isoformat()} experimental emergency stop activated")
            self._save()

    def run_scenario(self):
        raise ValueError("Synthetic scenarios are unavailable in experimental real-data operation")

    def _cancel_pending(self, now):
        for report in self.account.broker.history():
            if report.status in {"open", "partial"}:
                self.account.cancel(report.client_order_id, now=now)

    def _cancel_and_checkpoint(self, now):
        with self._lock:
            self._cancel_pending(now)
            self._trace_execution()
            self._save()

    def _select(self, frame, now):
        markets = {m.token_id: m for m in frame.markets}
        books = {b.token_id: b for b in frame.books}
        # Stable volume-priority membership avoids selecting by future returns.
        valid = [
            m.token_id
            for m in frame.markets
            if m.status == "active"
            and m.resolution_rules
            and m.resolution_source
            and (m.end_time is None or m.end_time > now + timedelta(seconds=120))
        ]
        self.selected = [t for t in self.selected if t in valid][: self.config.max_tokens]
        for token in valid:
            if len(self.selected) >= self.config.max_tokens:
                break
            if (
                token not in self.selected
                and token in books
                and assess_book(books[token], now, max_spread=0.05).healthy
            ):
                self.selected.append(token)
        selected = set(self.selected)
        return SharedMarketFrame(
            id=frame.id,
            timestamp=frame.timestamp,
            available_at=frame.available_at,
            source=frame.source,
            producer_health=frame.producer_health,
            markets=tuple(markets[t] for t in self.selected),
            books=tuple(b for b in frame.books if b.token_id in selected),
            fees=merge_fee_observations(frame.fees, self.fees, now=now),
            relationships=frame.relationships,
            evidence=frame.evidence,
            connectivity=frame.connectivity,
        )

    async def cycle(self):
        Settings.from_env()
        now = self.clock()
        if not self._budget_ok():
            self.last_error = "experimental_storage_budget_exhausted"
            self.account.stop(now=now)
            self._cancel_and_checkpoint(now)
            return
        frame = await self.feed.read()
        now = self.clock()
        self.last_frame = frame
        selected = self._select(frame, now)
        books = {b.token_id: b for b in frame.books}
        markets = {m.token_id: m for m in selected.markets}
        with self._lock:
            for market in selected.markets:
                self.events.append(market)
            for book in selected.books:
                if not self._budget_ok():
                    raise ValueError("experimental_storage_budget_exhausted")
                if self.archive.record(book):
                    self.totals["observations"] += 1
            signals = self.engine.evaluate_frame(selected, now)
            self.trace.record_engine(
                selected, signals, self.engine.status(), now, details=getattr(self.engine, "last_trace", None)
            )
            definition_ids = []
            for relationship in self.engine.intelligence.definitions.values():
                definition = relationship.model_dump(mode="json")
                rid = hashlib.sha256(relationship.model_dump_json().encode()).hexdigest()
                existing = self.events.connection.execute(
                    "SELECT kind,payload,digest FROM events WHERE id=?", (rid,)
                ).fetchone()
                if existing is None:
                    self.events.append(
                        ExperimentalRelationshipDefinition(
                            id=rid,
                            timestamp=now,
                            available_at=now,
                            source="experimental-derived-relationship/v1",
                            relationship_id=relationship.id,
                            definition=definition,
                        )
                    )
                else:
                    kind, payload, digest = existing
                    if (
                        kind != "ExperimentalRelationshipDefinition"
                        or hashlib.sha256(payload.encode()).hexdigest() != digest
                        or ExperimentalRelationshipDefinition.model_validate_json(payload).definition
                        != definition
                    ):
                        raise ValueError("corrupt experimental relationship definition")
                definition_ids.append(rid)
            for evidence in self.engine.intelligence.latest:
                self.events.append(evidence)
            self.account.advance(books, now=now, fees=selected.fees)
            rejected = Counter()
            examples = {}
            qualified = 0
            held = self.account.snapshot(now=self.clock())["positions"]
            stale_marks = [
                p["token_id"]
                for p in held
                if p["token_id"] not in books
                or not assess_book(books[p["token_id"]], self.clock(), max_spread=0.05).healthy
            ]
            for signal in signals:
                if signal.eligible:
                    qualified += 1
                    self.events.append(signal)
                    if stale_marks:
                        rejected["held_position_marks_stale"] += 1
                        self.trace.record_admission(
                            signal, {"status": "withheld", "reasons": ["held_position_marks_stale"]}, now
                        )
                        self.activity.append(
                            f"{now.isoformat()} {signal.strategy_id}: entry withheld; held marks stale"
                        )
                        continue
                    market = markets.get(signal.token_id)
                    book = books.get(signal.token_id)
                    if market is None or book is None:
                        rejected["current_book_unavailable"] += 1
                        self.trace.record_admission(
                            signal, {"status": "withheld", "reasons": ["current_book_unavailable"]}, now
                        )
                        continue
                    # Fixed standard sizing respects observed exchange minimum lots.
                    target = min(
                        self.config.risk_limits.standard_max,
                        max(self.config.position_notional, market.min_order_size * book.asks[0].price),
                    )
                    result = self.account.submit(
                        signal,
                        market,
                        book,
                        now=self.clock(),
                        target_notional=target,
                        fee_schedule=selected.fees.get(signal.token_id),
                    )
                    self.trace.record_admission(signal, result, self.clock())
                    reasons = result.get("reasons", [])
                    rejected.update(reasons if result.get("status") != "submitted" else [])
                    self.activity.append(
                        f"{now.isoformat()} {signal.strategy_id}: {result.get('status', 'unknown')} {';'.join(reasons)[:100]}"
                    )
                else:
                    rejected.update(signal.reasons)
                    examples.setdefault(signal.strategy_id, signal)
            self.account.mark(books, now=self.clock())
            for position in self.account.snapshot(now=self.clock())["positions"]:
                book = books.get(position["token_id"])
                if book is not None and assess_book(book, self.clock(), max_spread=0.05).healthy:
                    self.mark_sources[book.token_id] = {
                        "book_id": book.id,
                        "source_timestamp": book.timestamp.isoformat(),
                        "available_at": book.available_at.isoformat(),
                        "source": book.source,
                    }
            self._trace_execution()
            if self.event_intelligence is not None:
                try:
                    self.event_intelligence.on_frame(selected, self.clock())
                except Exception as error:
                    self.event_intelligence.last_error = f"{type(error).__name__}:{str(error)[:160]}"
                    log.exception("event_research_withheld")
            self.totals["cycles"] += 1
            self.totals["signals"] += len(signals)
            self.totals["qualified_opportunities"] += qualified
            self.rejections.update(rejected)
            cycle = ExperimentalCycle(
                timestamp=now,
                available_at=now,
                source="experimental-real-market-coordinator/v1",
                source_frame_id=frame.id,
                observed_book_ids=tuple(b.id for b in selected.books),
                market_record_ids=tuple(m.id for m in selected.markets),
                fee_evidence_ids=tuple(
                    dict.fromkeys(
                        raw["evidence_id"] for raw in selected.fees.values() if "evidence_id" in raw
                    )
                ),
                strategy_code_sha256=self.model_hash,
                relationship_definition_ids=tuple(definition_ids),
                relationship_evidence_ids=tuple(e.id for e in self.engine.intelligence.latest),
                signal_count=len(signals),
                eligible_count=qualified,
                rejection_counts=dict(rejected),
                decision_trace=self._trace_cycle_summary(),
                signal_digest=hashlib.sha256(
                    "".join(s.model_dump_json() for s in signals).encode()
                ).hexdigest(),
                representative_rejections=tuple(examples.values()),
            )
            self.events.append(cycle)
            self.last_cycle = cycle.model_dump(mode="json")
            self.last_success = self.clock()
            self.last_error = None
            self._save()
        log.info(
            "experimental_cycle %s",
            json.dumps(
                {
                    "cycles": self.totals["cycles"],
                    "source_markets": len({m.market_id for m in frame.markets}),
                    "selected_tokens": len(self.selected),
                    "signals": len(signals),
                    "eligible": qualified,
                    "rejections": dict(rejected),
                }
            ),
        )

    def _trace_cycle_summary(self):
        # Keep every cycle's counters, but avoid duplicating bounded samples in
        # the append-only archive. Examples remain in the trace checkpoint and
        # representative_rejections, with actual book/market evidence IDs.
        rows = self.trace.status()["latest_cycle"]["strategies"]
        return {
            "strategies": {
                strategy: {
                    **row,
                    "reasons": {
                        reason: {k: v for k, v in detail.items() if k != "samples"}
                        for reason, detail in row["reasons"].items()
                    },
                }
                for strategy, row in rows.items()
            }
        }

    def _trace_execution(self):
        """Consume durable audit sequences once; never infer fills from a quote.

        Cursors and counters checkpoint together. At first deployment cursors
        start after legacy events, so no historical Phase10 counts are invented.
        Per-cycle work is bounded; remaining records resume next cycle.
        """
        for source, db in (("risk", self.account.risk.db), ("broker", self.account.broker.db)):
            rows = db.execute(
                "SELECT * FROM audit WHERE seq>? ORDER BY seq LIMIT 5000", (self.trace_cursors[source],)
            ).fetchall()
            for event in rows:
                payload = json.loads(event["payload"])
                strategy = None
                side, status, filled = "BUY", "observed", 0
                if source == "risk" and event["action"] == "fill":
                    reservation = db.execute(
                        "SELECT opportunity FROM reservations WHERE id=?", (payload["reservation_id"],)
                    ).fetchone()
                    if reservation:
                        strategy = json.loads(reservation[0])["strategy_id"]
                        # Count new fill events; quantity here is cumulative, not traded volume.
                        filled = payload["quantity"]
                elif source == "risk" and event["action"] in {
                    "experimental_exit_fill",
                    "experimental_exit_expired",
                    "experimental_exit_cancelled",
                }:
                    side = "SELL"
                    row = db.execute(
                        "SELECT strategy FROM experimental_exits WHERE id=?", (payload["id"],)
                    ).fetchone()
                    strategy = row[0] if row else None
                    filled = payload.get("quantity", 0)
                    status = event["action"].removeprefix("experimental_exit_")
                elif source == "broker" and event["action"] in {"cancelled", "expired"}:
                    row = self.account.risk.db.execute(
                        "SELECT opportunity FROM reservations WHERE client_id=?",
                        (payload["client_order_id"],),
                    ).fetchone()
                    strategy = json.loads(row[0])["strategy_id"] if row else None
                    status = event["action"]
                if strategy:
                    self.trace.record_execution(
                        strategy,
                        f"{source}:{event['seq']}",
                        status,
                        filled,
                        datetime.fromisoformat(event["timestamp"]),
                        side=side,
                    )
                self.trace_cursors[source] = event["seq"]

    async def _fees_loop(self, should_exit):
        while not self.stopping and not should_exit():
            try:
                if self.last_frame and self._budget_ok():
                    now = self.clock()
                    # Exit fees get priority; no assumed zero fee for a held position.
                    held = [p["token_id"] for p in self.account.snapshot(now=now)["positions"]]
                    tokens = list(dict.fromkeys(held + self.selected))
                    pending = []
                    for token in tokens:
                        raw = self.fees.get(token)
                        at = datetime.fromisoformat(raw["observed_at"]) if raw else None
                        attempted = self.fee_attempts.get(token)
                        if (
                            at is None or (now - at).total_seconds() > self.config.fee_ttl_seconds * 0.8
                        ) and (attempted is None or (now - attempted).total_seconds() > 30):
                            pending.append(token)

                    async def acquire(token):
                        self.fee_attempts[token] = self.clock()
                        result = await self.fee_adapter.observed_fee(token)
                        if result:
                            with self._lock:
                                self.fees[token] = result

                    await asyncio.gather(*(acquire(t) for t in pending[: self.config.fee_batch]))
                    keep = set(tokens)
                    self.fees = {t: v for t, v in self.fees.items() if t in keep}
                    self.fee_attempts = {t: v for t, v in self.fee_attempts.items() if t in keep}
                    self.fee_error = None
            except Exception as error:
                self.fee_error = type(error).__name__
                log.exception("experimental_fee_refresh_withheld")
            await asyncio.sleep(2)

    async def _event_resolution_loop(self, should_exit):
        next_check = self.clock()
        while not self.stopping and not should_exit():
            if self.event_intelligence is not None and self.clock() >= next_check:
                try:
                    await self.event_intelligence.resolve_pending()
                except Exception as error:
                    self.event_intelligence.resolution_status["last_error"] = type(error).__name__
                    log.exception("event_resolution_withheld")
                next_check = self.clock() + timedelta(seconds=300)
            await asyncio.sleep(2)

    async def run(self, should_exit=lambda: False):
        async def cycles():
            while not self.stopping and not should_exit():
                try:
                    await self.cycle()
                except Exception as error:
                    self.last_error = f"cycle_failed:{type(error).__name__}"
                    log.exception("experimental_cycle_withheld")
                    self._cancel_and_checkpoint(self.clock())
                await asyncio.sleep(self.config.poll_seconds)

        await asyncio.gather(cycles(), self._fees_loop(should_exit), self._event_resolution_loop(should_exit))

    def health(self):
        now = self.clock()
        age = (now - self.last_success).total_seconds() if self.last_success else None
        return {
            "status": "ok"
            if age is not None and age < max(30, self.config.poll_seconds * 3) and self.last_error is None
            else "degraded",
            "account_id": "experimental-paper",
            "validation_status": "unvalidated",
            "paper_trading": True,
            "live_trading_enabled": False,
            "last_ingestion_at": self.last_success.isoformat() if self.last_success else None,
            "last_ingestion_age_seconds": age,
            "last_error": self.last_error,
            "fee_error": self.fee_error,
            "timestamp": now.isoformat(),
        }

    def _qualification(self):
        path = self.config.qualification_report_path
        if path is None or not path.is_file() or path.stat().st_size > 1024 * 1024:
            return {"status": "unknown", "reason": "qualification report unavailable"}
        try:
            report = json.loads(path.read_text())
            if report.get("strategy_promotion_authority") is not False:
                return {"status": "unknown", "reason": "unexpected qualification authority"}
            return report
        except (ValueError, OSError):
            return {"status": "unknown", "reason": "unreadable qualification report"}

    def _event_summary(self):
        if self.event_intelligence is None:
            return {
                "status": "unavailable"
                if hasattr(self, "event_research_initialization_error")
                else "disabled",
                "research_status": "event research unavailable or disabled",
                "last_error": getattr(self, "event_research_initialization_error", None),
                "certification_authority": False,
                "independent_models_enabled": 0,
            }
        try:
            return {
                **self.event_intelligence.summary(),
                "model_research": load_summary(self.config.event_model_report_path)
                if self.config.event_model_report_path
                else {"status": "unavailable"},
            }
        except Exception as error:  # noqa: BLE001 - unavailable research never affects trading authority
            return {
                "status": "unavailable",
                "research_status": "unavailable",
                "last_error": type(error).__name__,
                "certification_authority": False,
                "independent_models_enabled": 0,
            }

    def state(self):
        with self._lock:
            now = self.clock()
            state = self.account.snapshot(now=now)
            frame = self.last_frame
            books = frame.books if frame else ()
            current = {b.token_id: b for b in books}
            stale_marks = [
                p["token_id"]
                for p in state["positions"]
                if p["token_id"] not in current
                or not assess_book(current[p["token_id"]], now, max_spread=0.05).healthy
            ]
            state.update(
                mark_sources={
                    p["token_id"]: self.mark_sources.get(p["token_id"]) for p in state["positions"]
                },
                stale_mark_tokens=stale_marks,
                pnl_valuation="stale_last_observed_marks"
                if stale_marks
                else "fresh_observed_bid_marks_or_cash",
                strategy_code_sha256=self.model_hash,
                generated_at=now.isoformat(),
                suspended=state["kill_switch"],
                service=self.health(),
                source_markets=len({m.market_id for m in frame.markets}) if frame else None,
                source_tokens=len(frame.markets) if frame else None,
                experimental_markets=len({m.market_id for m in frame.markets if m.token_id in self.selected})
                if frame
                else None,
                fresh_books=sum(assess_book(b, now).healthy for b in books),
                source_fresh_books=sum(assess_book(b, now).healthy for b in books),
                experimental_fresh_books=sum(
                    assess_book(b, now).healthy for b in books if b.token_id in self.selected
                ),
                selected_tokens=len(self.selected),
                qualified_opportunities=self.totals["qualified_opportunities"],
                experimental_totals=dict(self.totals),
                rejection_reasons=dict(self.rejections),
                latest_activity=list(self.activity),
                last_cycle=self.last_cycle,
                strategy_engine=self.engine.status(),
                decision_trace=self.trace.status(),
                data_source=self.config.source_url,
                certification_authority=False,
                historical_qualification=self._qualification(),
                event_intelligence=self._event_summary(),
                research=load_summary(self.config.research_report_path)
                if self.config.research_report_path
                else {"status": "unavailable", "reason": "Research report not configured"},
            )
            return state

    async def close(self):
        self.stopping = True
        self._cancel_and_checkpoint(self.clock())
        await self.feed.close()
        await self.fee_adapter.close()
        if self.event_intelligence is not None:
            self.event_intelligence.close()
        self.events.close()
        self.account.close()


async def serve_experimental(config):
    import uvicorn

    from neraium_poly.ops.api import create_app

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    runtime = ExperimentalRuntime(config)
    app = create_app(runtime=runtime, local_port=config.port)
    server = uvicorn.Server(uvicorn.Config(app, host=config.host, port=config.port, log_level="warning"))
    try:
        await asyncio.gather(server.serve(), runtime.run(lambda: server.should_exit))
    finally:
        await runtime.close()
