"""Separate experimental process: public observations in, isolated paper capital out."""

import asyncio
import hashlib
import json
import logging
import shutil
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event, RLock

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
        from neraium_poly.research.phase28.memory import MemorySampler
        self.memory_sampler = MemorySampler()
        self.config = config
        from neraium_poly.research.phase31.operations import EventSummaryCache
        self.event_summary_cache=EventSummaryCache(clock=clock)
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
        self.archive_fault = None
        self.model_hash = strategy_code_hash()
        previous_hash = self.ledger.get("strategy_code_hash")
        if previous_hash is not None and previous_hash != self.model_hash:
            account.close()
            raise ValueError("Experimental model code changed; explicit research baseline migration required")
        if config.archive_management_enabled:
            from neraium_poly.data.segmented import ManagedEventStore

            try:
                self.events = ManagedEventStore(
                    config.data_dir / "events.sqlite",
                    segment_bytes=config.archive_segment_mb * 1024**2,
                    budget_bytes=config.archive_budget_mb * 1024**2,
                    min_free_bytes=max(8192, config.min_free_disk_mb, config.archive_reserve_disk_mb) * 1024**2,
                    compress=config.archive_compression_enabled,
                    cold_verification_enabled=config.archive_cold_verification_enabled,
                    clock=self.clock,
                )
            except BaseException:
                account.close()
                raise
        else:
            self.events = EventStore(config.data_dir / "events.sqlite")
        try:
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
                        sports_enabled=config.sports_research_enabled,
                        domains_enabled=config.domain_research_enabled,
                    )
                except Exception as error:
                    self.event_research_initialization_error = f"{type(error).__name__}:{str(error)[:160]}"
                    log.exception("event_research_startup_withheld")
            self.phase15_relationships = None
            if config.phase15_relationship_research_enabled:
                from neraium_poly.research.phase15.continuous import ContinuousRelationships

                self.phase15_relationships = ContinuousRelationships(self.events)
            self.last_phase16_checks = []
            self.phase16 = None
            self.phase16_error = None
            if config.phase16_research_enabled:
                from neraium_poly.research.phase16.continuous import ContinuousQualification

                try:
                    self.phase16 = ContinuousQualification(self.events)
                except Exception as error:  # Unavailable research has no order authority.
                    self.phase16_error = f"{type(error).__name__}:{str(error)[:160]}"
                    log.exception("phase16_recovery_withheld")
            self.phase17 = None
            self.phase17_error = None
            if config.phase17_research_enabled and self.phase16 is not None:
                from neraium_poly.research.phase17.continuous import EmpiricalResearch

                try:
                    self.phase17 = EmpiricalResearch(self.events, activation_at=self.clock())
                except Exception as error:  # Research cannot grant trading authority.
                    self.phase17_error = f"{type(error).__name__}:{str(error)[:160]}"
                    log.exception("phase17_recovery_withheld")
            self.phase18 = None
            self.phase18_error = None
            if config.phase18_event_research_enabled:
                from neraium_poly.research.phase18.continuous import IndependentEventResearch

                try:
                    self.phase18 = IndependentEventResearch(self.events, clock=self.clock, can_write=self._budget_ok)
                except Exception as error:
                    self.phase18_error = f"{type(error).__name__}:{str(error)[:160]}"
                    log.exception("phase18_recovery_withheld")
            self.phase20 = None
            self.phase20_error = None
            if config.phase20_ab_research_enabled:
                from neraium_poly.research.phase20.continuous import ProspectiveABResearch

                try:
                    if self.phase18 is None:
                        raise ValueError("existing independent research pipeline required")
                    hashes = {f["model_sha256"] for f in self.phase18.state["pending"].values()}
                    if len(hashes) > 1:
                        raise ValueError("one native replayable baseline model identity required")
                    self.phase20 = ProspectiveABResearch(self.events, baseline_model_sha256=hashes.pop() if hashes else None,
                        clock=self.clock, can_write=self._budget_ok)
                except Exception as error:
                    self.phase20_error = f"{type(error).__name__}:{str(error)[:160]}"
                    log.exception("phase20_recovery_withheld")
            self.phase21 = None
            self.phase21_error = None
            if config.phase21_early_outcomes_enabled:
                from neraium_poly.research.phase21.continuous import EarlyOutcomeResearch

                try:
                    if self.phase18 is None:
                        raise ValueError("existing independent forecast pipeline required")
                    self.phase21 = EarlyOutcomeResearch(self.events, config.data_dir/"phase18-resolution-evidence",
                        clock=self.clock, can_write=self._budget_ok)
                except Exception as error:
                    self.phase21_error = f"{type(error).__name__}:{str(error)[:160]}"
                    log.exception("phase21_outcome_recovery_withheld")
            self.phase23 = None
            self.phase23_competition = None
            self.phase23_outcomes = None
            self.phase23_error = None
            if config.phase23_research_enabled:
                from neraium_poly.research.phase23.continuous import ChallengerResearch
                from neraium_poly.research.phase23.operations import ContinuousCompetition
                from neraium_poly.research.phase23.outcomes import ChallengerOutcomes
                from neraium_poly.research.phase33.competition_storage import CompetitionStorageAdapter

                try:
                    self.phase23 = ChallengerResearch(self.events, clock=self.clock, can_write=self._budget_ok)
                    self.phase23_competition = ContinuousCompetition(CompetitionStorageAdapter(self.events, clock=self.clock, can_write=self._budget_ok), clock=self.clock, can_write=self._budget_ok, evidence_root=config.data_dir/"phase23-resolution-evidence")
                    self.phase23_outcomes = ChallengerOutcomes(self.events, config.data_dir/"phase23-resolution-evidence", clock=self.clock, can_write=self._budget_ok)
                except Exception as error:
                    self.phase23 = self.phase23_competition = self.phase23_outcomes = None
                    self.phase23_error = f"{type(error).__name__}:{str(error)[:160]}"
                    log.exception("phase23_research_recovery_withheld")
            self._research_source_lock = asyncio.Lock()
            self._research_report_lock = asyncio.Lock()
            self.phase24 = self.phase24_outcomes = None
            self.phase24_report = None
            self.phase24_error = None
            if config.phase24_research_enabled:
                from neraium_poly.research.phase24.continuous import DomainResearch
                from neraium_poly.research.phase24.outcomes import DomainOutcomes

                try:
                    self.phase24 = DomainResearch(self.events, clock=self.clock, can_write=self._budget_ok)
                    self.phase24_outcomes = DomainOutcomes(self.events, config.data_dir/"phase24-resolution-evidence",
                        clock=self.clock, can_write=self._budget_ok)
                except Exception as error:
                    self.phase24 = self.phase24_outcomes = None
                    self.phase24_error = f"{type(error).__name__}:{str(error)[:160]}"
                    log.exception("phase24_recovery_withheld")
            self.phase25 = self.phase25_outcomes = self.phase25_universe = None
            self.phase25_report = self.phase25_error = None
            if config.phase25_research_enabled:
                from neraium_poly.research.phase25.continuous import ExpansionOutcomes, ExpansionResearch
                from neraium_poly.research.phase30.coverage import WeatherUniverse as Universe

                try:
                    self.phase25 = ExpansionResearch(self.events, clock=self.clock, can_write=self._budget_ok)
                    self.phase25_outcomes = ExpansionOutcomes(self.events, config.data_dir/"phase25-resolution-evidence",
                        clock=self.clock, can_write=self._budget_ok)
                    self.phase25_universe = Universe(self.events, clock=self.clock, can_write=self._budget_ok)
                except Exception as error:
                    self.phase25 = self.phase25_outcomes = self.phase25_universe = None
                    self.phase25_error = f"{type(error).__name__}:{str(error)[:160]}"
                    log.exception("phase25_recovery_withheld")
            self.phase35 = self.phase35_native = self.phase35_universe = self.phase35_outcomes = None
            self.phase35_error = self.phase35_native_error = None
            if config.phase25_research_enabled:
                from neraium_poly.research.phase35.continuous import WorldWeatherResearch
                from neraium_poly.research.phase35.discovery import WorldWeatherUniverse
                from neraium_poly.research.phase35.outcomes import WorldWeatherOutcomes
                from neraium_poly.research.phase35.persistence import NativeResearchPublisher
                try:
                    self.phase35 = WorldWeatherResearch(self.events, clock=self.clock, can_write=self._budget_ok)
                    self.phase35_universe = WorldWeatherUniverse(self.events, clock=self.clock, can_write=self._budget_ok)
                    self.phase35_native = NativeResearchPublisher(self.events, config.data_dir/'phase35-native',
                        clock=self.clock, can_write=self._budget_ok)
                    self.phase35_outcomes = WorldWeatherOutcomes(self.events, config.data_dir/'phase35-weather-outcomes',
                        clock=self.clock, can_write=self._budget_ok)
                except Exception as error:
                    self.phase35 = self.phase35_native = self.phase35_universe = self.phase35_outcomes = None
                    self.phase35_error = f"{type(error).__name__}:{str(error)[:160]}"
                    log.exception('phase35_research_recovery_withheld')
            self.phase26_enabled = config.phase26_intelligence_enabled
            self.phase26_index = self.phase26_inputs = None
            self.phase26_report = self.phase26_error = None
            if self.phase26_enabled:
                from neraium_poly.research.phase26.coordination import Inputs
                from neraium_poly.research.phase26.index import ResearchIndex
                from neraium_poly.research.phase26.routing import (
                    OfficialDomainOutcomes,
                    OfficialExpansionOutcomes,
                )
                try:
                    self.phase26_index = ResearchIndex(config.data_dir/"research-projection.sqlite", source_directory=config.data_dir)
                    self.phase26_inputs = Inputs(self.events, clock=self.clock, can_write=self._budget_ok)
                    if self.phase24 is not None:
                        self.phase24_outcomes = OfficialDomainOutcomes(self.events, config.data_dir/"phase24-resolution-evidence", clock=self.clock, can_write=self._budget_ok)
                    if self.phase25 is not None:
                        self.phase25_outcomes = OfficialExpansionOutcomes(self.events, config.data_dir/"phase25-resolution-evidence", clock=self.clock, can_write=self._budget_ok)
                except Exception as error:
                    self.phase26_error = f"{type(error).__name__}:{str(error)[:160]}"
                    log.exception("phase26_recovery_withheld")
            self.phase27 = None
            self.phase27_error = None
            if config.phase27_findings_enabled:
                try:
                    from neraium_poly.research.phase27.continuous import FindingsResearch
                    if self.phase26_index is None:
                        raise ValueError("findings require source-anchored research index")
                    self.phase27 = FindingsResearch(self.events, self.phase26_index, clock=self.clock, can_write=self._budget_ok)
                except Exception as error:
                    self.phase27_error = f"{type(error).__name__}:{str(error)[:160]}"
                    log.exception("phase27_recovery_withheld")
            self.official_event_scores = None
            self.phase28 = None
            self.phase28_error = None
            if config.phase28_economics_enabled:
                try:
                    from neraium_poly.research.phase28.continuous import VolumeResearch
                    from neraium_poly.research.phase28.shadow import ShadowResearch
                    if self.phase26_index is None:
                        raise ValueError("volume research requires anchored source projection")
                    shadow = ShadowResearch(self.events, clock=self.clock, can_write=self._budget_ok)
                    self.phase28 = VolumeResearch(self.events,self.phase26_index,clock=self.clock,can_write=self._budget_ok,shadow=shadow)
                    from neraium_poly.research.phase32.scoring import DomainEventScoring
                    self.official_event_scores = DomainEventScoring(self.events,self.phase26_index,
                        config.data_dir/"phase30-official-event-evidence",clock=self.clock,can_write=self._budget_ok)
                    self.cpi_input_qualification={"status":"pending","forecast_probability":None,"trading_authority":False}
                    from neraium_poly.research.phase31.scorecard import ScorecardPublisher
                    self.domain_scorecard=ScorecardPublisher(self.events,clock=self.clock,can_write=self._budget_ok,
                        official=lambda:self.official_event_scores.status(),macro=lambda:self.cpi_input_qualification,
                        shadow=lambda:self.phase28.shadow.status())
                    from neraium_poly.research.phase32.pairs import PairResearch
                    self.pair_research=PairResearch(self.events,clock=self.clock,can_write=self._budget_ok)
                    from neraium_poly.research.phase33.continuous import FeeHeadroomResearch
                    self.fee_headroom_research=FeeHeadroomResearch(self.events,clock=self.clock,can_write=self._budget_ok,
                        observations=self._causal_research_fee_observations)
                    self.phase28.on_report=self._publish_research_scorecards
                except Exception as error:
                    self.phase28_error = f"{type(error).__name__}:{str(error)[:160]}"
                    log.exception("phase28_recovery_withheld")
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
        except BaseException:
            self.events.close()
            self.account.close()
            raise

    def _budget_ok(self):
        if self.config.archive_management_enabled:
            if self.archive_fault:
                return False
            try:
                return self.events.can_write() if hasattr(self.events, "can_write") else self._archive_status()["health"] == "ok"
            except Exception as error:  # noqa: BLE001 - deny orders if archive accounting fails
                self.archive_fault = f"archive_budget:{type(error).__name__}:{str(error)[:160]}"
                return False
        size = sum(p.stat().st_size for p in self.config.data_dir.glob("*.sqlite*") if p.is_file())
        return (
            size < self.config.max_archive_mb * 1024 * 1024
            and shutil.disk_usage(self.config.data_dir).free >= self.config.min_free_disk_mb * 1024 * 1024
        )

    def _archive_status(self, *, for_operations=False):
        if not self.config.archive_management_enabled:
            return {"managed": False, "health": "legacy_budget", "budget_bytes": self.config.max_archive_mb * 1024**2,
                    "retention_policy": "append_only_no_rotation"}
        try:
            status = self.events.operations_status() if for_operations else self.events.status()
        except Exception as error:  # noqa: BLE001 - keep account state visible when archive health fails
            if for_operations:
                status = {"managed": True, "health": "unknown", "snapshot_only": True,
                    "admission_authority": False, "measurement_status": "unavailable", "measurement_at": None,
                    "last_error": f"archive_display:{type(error).__name__}:{str(error)[:160]}"}
            else:
                self.archive_fault = f"archive_status:{type(error).__name__}:{str(error)[:160]}"
                status = {"managed": True}
        if self.archive_fault:
            status.update(health="blocked", last_error=self.archive_fault)
        return status

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
        gate=getattr(self,"_cycle_gate",None)
        if gate is None:
            self._cycle_gate=gate=asyncio.Lock()
        async with gate:
            if self.stopping:return
            self._cycle_abort=Event()
            self._cycle_done=asyncio.get_running_loop().create_future()
            try:
                return await self._cycle_impl()
            finally:
                self._cycle_done.set_result(None)
                self._cycle_done=None

    async def _finish_cycle(self):
        done=getattr(self,"_cycle_done",None);interrupted=False
        if done is not None:
            while not done.done():
                try:await asyncio.shield(done)
                except asyncio.CancelledError:interrupted=True
        return interrupted

    def _admission_stopping(self):
        abort = getattr(self, "_cycle_abort", None)
        return self.stopping or (abort is not None and abort.is_set())

    async def _sync_io(self, function, *args, cycle=False, **kwargs):
        """One submitted synchronous job, no executor backlog; drain on cancel.

        Financial admission still reads the current locked ledger in the worker.
        This executor never authorizes from an operational/display snapshot.
        """
        gate = getattr(self, "_io_gate", None)
        if gate is None:
            self._io_gate = gate = asyncio.Lock()
        async with gate:
            if getattr(self, "_io_closed", False):
                raise RuntimeError("experimental synchronous I/O lane closed")
            executor = getattr(self, "_io_executor", None)
            if executor is None:
                self._io_executor = executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="paper-io")
            import functools
            worker = asyncio.get_running_loop().run_in_executor(executor, functools.partial(function, *args, **kwargs))
            interrupted = False
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    interrupted = True
                    if cycle:
                        self._cycle_abort.set()
                except Exception:  # noqa: BLE001 - propagate the completed worker result after draining
                    break
            if interrupted:
                # Consume a worker failure too; cancellation cannot abandon a
                # live SQLite write or release the serial gate prematurely.
                if worker.done() and not worker.cancelled():
                    worker.exception()
                raise asyncio.CancelledError
            return worker.result()

    async def _async_budget_ok(self):
        return await self._sync_io(self._budget_ok)

    def _observe_phase20(self):
        originals = self.events.latest("EventProbabilityStudy", limit=1)
        if originals:
            self.phase20.observe(originals[0])

    async def _research_io(self, factory, *args, **kwargs):
        if self.stopping:
            raise RuntimeError('research scheduling stopped')
        worker = getattr(self, '_research_worker', None)
        if worker is None:
            from neraium_poly.experimental.research_worker import ResearchWorker
            self._research_worker = worker = ResearchWorker()
        return await worker.run(factory, *args, **kwargs)

    def _select_weather_research(self, frame):
        from neraium_poly.research.phase14.relationships import digest
        from neraium_poly.research.phase34.selection import WeatherInputSelection, prepare_weather_frame

        selected, report = prepare_weather_frame(frame, as_of=self.clock())
        if report['preferred_tokens'] or report['deferred_tokens']:
            if not self._budget_ok():
                raise ValueError('weather_selection_archive_backpressure')
            now = self.clock()
            self.events.append(WeatherInputSelection(
                id=digest(['phase34-weather-input-selection', report]), timestamp=now, available_at=now,
                source='neraium-poly/weather-source-selection/v34',
                **{k:report[k] for k in ('source_frame_id','selected_frame_id','source_frame_sha256',
                    'selected_frame_sha256','policy_sha256','preferred_tokens','deferred_tokens','rejection_counts')}))
        self.weather_input_selection = report
        return selected

    async def _cycle_impl(self):
        if not await self._sync_io(self._cycle_preflight, cycle=True):
            if self.event_intelligence is not None and not self.config.archive_management_enabled:
                try:
                    frame = await getattr(self.feed, "read_research", self.feed.read)()
                    await self._sync_io(self._research_frame, frame, cycle=True)
                except Exception as error:  # noqa: BLE001 - unavailable research cannot admit orders
                    self.event_intelligence.sports_error = f"{type(error).__name__}:{str(error)[:120]}"
            return
        if self._admission_stopping():
            return
        frame = await self.feed.read()
        await self._sync_io(self._process_frame, frame, cycle=True)

    def _research_frame(self, frame):
        with self._lock:
            self.event_intelligence.on_research_frame(frame, self.clock())

    def _cycle_preflight(self):
        if getattr(self,"memory_sampler",None):self.memory_sampler.sample("experimental_cycle_start")
        Settings.from_env()
        now = self.clock()
        if self.config.archive_management_enabled:
            try:
                self.events.maintain()
            except Exception as error:  # noqa: BLE001 - storage faults preserve the risk suspension path
                self.archive_fault = f"archive_maintenance:{type(error).__name__}:{str(error)[:160]}"
        if not self._budget_ok():
            self.last_error = self._archive_status().get("last_error") if self.config.archive_management_enabled else "experimental_storage_budget_exhausted"
            if not self.account.snapshot(now=now)["kill_switch"]:
                status = self._archive_status()
                self.account.stop(now=now, reason=self.last_error or "archive_budget_unavailable",
                                  actor="experimental_storage_guard", evidence={
                                      "archive": {k: status.get(k) for k in (
                                          "health", "usage_bytes", "budget_bytes", "free_bytes", "global_floor_bytes")},
                                      "observed_at": now.isoformat()})
            self._cancel_and_checkpoint(now)
            return False
        return True

    def _process_frame(self, frame):
        now = self.clock()
        self.last_frame = frame
        if self.event_intelligence is not None:
            with self._lock:
                self.event_intelligence.on_research_frame(frame, self.clock())
        if self.phase15_relationships is not None:
            try:
                self.phase15_relationships.observe(frame.model_dump(mode="json"), now=now)
            except Exception as error:  # noqa: BLE001 - research cannot acquire trading authority
                log.warning("phase15_relationship_withheld:%s", type(error).__name__)
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
            # Archival time is not executable quote freshness. Keep financial
            # admission synchronous, but qualify against the actual decision time.
            now = self.clock()
            if self._admission_stopping():
                self._cancel_and_checkpoint(now)
                return
            signals = self.engine.evaluate_frame(selected, now)
            checks = []
            if self.config.phase16_execution_veto_enabled:
                from neraium_poly.research.phase16.admission import execution_veto

                signals, checks = execution_veto(signals, selected, now=now,
                                                 target_notional=self.config.position_notional, model_code_sha256=self.model_hash)
                self.last_phase16_checks = [r.model_dump(mode="json") for r in checks][-8:]
                for check in checks:
                    self.events.append(check)  # Durable evidence precedes any paper order.
            if self.phase16 is not None:
                try:
                    self.phase16.observe(selected.model_dump(mode="json"), now=now, signals=signals)
                    self.phase16_error = None
                except Exception as error:  # noqa: BLE001 - withhold the research component on failure
                    self.phase16_error = f"{type(error).__name__}:{str(error)[:160]}"
                    log.warning("phase16_study_withheld:%s", type(error).__name__)
            if self.phase17 is not None and self.phase16 is not None:
                try:
                    self.phase17.observe(self.phase16, now=self.clock())
                    self.phase17_error = None
                except Exception as error:  # noqa: BLE001 - research has no admission authority
                    self.phase17_error = f"{type(error).__name__}:{str(error)[:160]}"
                    log.warning("phase17_research_withheld:%s", type(error).__name__)
            self.trace.record_engine(
                selected, signals, self.engine.status(), now, details=getattr(self.engine, "last_trace", None)
            )
            definition_ids = []
            for relationship in self.engine.intelligence.definitions.values():
                definition = relationship.model_dump(mode="json")
                rid = hashlib.sha256(relationship.model_dump_json().encode()).hexdigest()
                existing = self.events.get(rid)
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
            # Reconciliation may follow slow source validation; never advance
            # pending fills using the pre-archive decision clock.
            if self._admission_stopping():
                self._cancel_and_checkpoint(self.clock())
                return
            self.account.advance(books, now=self.clock(), fees=selected.fees)
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
                    if self._admission_stopping():
                        self._cancel_and_checkpoint(self.clock())
                        return
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
                    self.event_intelligence.on_frame(selected, self.clock(), sports_frame=frame, include_research=False)
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
                decision_trace={**self._trace_cycle_summary(),
                    "qualification_scope": "legacy strategy gate before depth veto; includes duplicate evaluations",
                    "emitted_execution_checks": {"checked": len(checks),
                        "vetoed": sum(c.vetoed for c in checks),
                        "passed_check_not_risk_approved": sum(not c.vetoed for c in checks)}},
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

    def _publish_fee(self, token, result):
        with self._lock:
            self.fees[token] = result

    async def _fees_loop(self, should_exit):
        while not self.stopping and not should_exit():
            try:
                if self.last_frame and await self._sync_io(self._budget_ok):
                    now = self.clock()
                    # Exit fees get priority; no assumed zero fee for a held position.
                    held = await self._sync_io(lambda: [p["token_id"] for p in self.account.snapshot(now=self.clock())["positions"]])
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
                            await self._sync_io(self._publish_fee, token, result)

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
            if self.event_intelligence is not None and self.clock() >= next_check and (
                not self.config.archive_management_enabled or await self._sync_io(self._budget_ok)
            ):
                try:
                    await self._research_io(self.event_intelligence.resolve_pending)
                except Exception as error:
                    self.event_intelligence.resolution_status["last_error"] = type(error).__name__
                    log.exception("event_resolution_withheld")
                next_check = self.clock() + timedelta(seconds=300)
            await asyncio.sleep(2)

    async def _domain_research_loop(self, should_exit, family="phase24"):
        if family not in ("phase24", "phase25"):
            raise ValueError("unknown research enrollment")
        if family == "phase25":
            from neraium_poly.research.phase25.operations import unified_report as combined_report
        else:
            from neraium_poly.research.phase24.operations import combined_report
        engine = getattr(self, family, None)
        outcomes = getattr(self, family+"_outcomes", None)

        async def one_cycle():
            frame = self.last_frame
            if family == "phase25":
                async with self._research_source_lock:
                    frame = await self._research_io(self.phase25_universe.frame, frame)
                if getattr(self, "phase26_inputs", None) is not None:
                    raw = self.last_frame.model_dump(mode="json") if hasattr(self.last_frame, "model_dump") else self.last_frame
                    last = engine.state.get("last_attempt_at")
                    due = not last or (self.clock()-datetime.fromisoformat(last)).total_seconds() >= 300
                    frame = await self.phase26_inputs.prepare(frame, base_tokens={m["token_id"] for m in raw["markets"]}, wait=due, forecast_tokens=getattr(self.phase28,"forecast_tokens",()))
                last = engine.state.get("last_attempt_at")
                if not last or (self.clock()-datetime.fromisoformat(last)).total_seconds() >= 300:
                    frame = await self._sync_io(self._select_weather_research, frame)
            async with self._research_source_lock:
                await self._research_io(engine.step, frame)
                await self._research_io(outcomes.step)
            async with self._research_report_lock:
                if getattr(self, "phase26_enabled", False):
                    if self.phase26_index is None or not await self._sync_io(self._budget_ok):
                        raise ValueError("source-anchored projection unavailable or archive backpressure")
                    from neraium_poly.research.phase26.reporting import callbacks
                    verify_forecast, verify_outcome = callbacks(self.events, self.config.data_dir)
                    def evaluate():
                        self.phase26_index.step(self.events, as_of=self.clock(), forecast_verifier=verify_forecast, outcome_verifier=verify_outcome)
                        report = self.phase26_index.report(as_of=self.clock())
                        if family == "phase25" and getattr(self, "phase27", None) is not None:
                            try:
                                self.phase27.step(frame)
                            except Exception as error:
                                self.phase27.error = f"{type(error).__name__}:{str(error)[:160]}"
                                log.exception("phase27_findings_withheld")
                        return report
                    worker = asyncio.create_task(asyncio.to_thread(evaluate))
                else:
                    worker = asyncio.create_task(asyncio.to_thread(combined_report, self.events, as_of=self.clock(),
                        evidence_root=self.config.data_dir/(family+"-resolution-evidence")))
                try:
                    report = await asyncio.shield(worker)
                    setattr(self, family+"_report", report)
                    if getattr(self, "phase26_enabled", False):
                        self.phase26_report = report
                        self.phase26_error = None
                except asyncio.CancelledError:
                    await asyncio.gather(worker, return_exceptions=True)
                    raise
            setattr(self, family+"_error", None)

        while not self.stopping and not should_exit():
            job = None
            try:
                if engine is not None and self.last_frame is not None:
                    job = asyncio.create_task(one_cycle())
                    while not job.done() and not self.stopping and not should_exit():
                        await asyncio.wait({job}, timeout=1)
                    if self.stopping or should_exit():
                        job.cancel()
                    await job
            except asyncio.CancelledError:
                if self.stopping or should_exit():
                    return
                raise
            except Exception as error:
                setattr(self, family+"_error", f"{type(error).__name__}:{str(error)[:160]}")
                log.exception("%s_domain_research_withheld", family)
            finally:
                if job is not None and not job.done():
                    job.cancel()
                    await asyncio.gather(job, return_exceptions=True)
            for _ in range(30):
                if self.stopping or should_exit():
                    break
                await asyncio.sleep(1)

    async def _phase35_research_once(self):
        async with self._research_source_lock:
            if not await self._sync_io(self._budget_ok):
                return
            try:
                await self._research_io(self.phase35_native.step)
                self.phase35_native_error = None
            except Exception as error:
                # Native proof failure cannot qualify a payout or prevent a
                # separate source-qualified prospective research observation.
                self.phase35_native_error = f'{type(error).__name__}:{str(error)[:160]}'
                log.exception('phase35_native_evidence_withheld')
            frame = await self._research_io(self.phase35_universe.frame, self.last_frame)
            await self._research_io(self.phase35.step, frame)
            if getattr(self, 'phase35_outcomes', None) is not None:
                await self._research_io(self.phase35_outcomes.step)

    async def _phase35_research_loop(self, should_exit):
        # Existing serial research worker owns all archival writes. API reads
        # only cached status; no new executor, account or admission authority.
        while not self.stopping and not should_exit():
            if getattr(self, 'phase35', None) is not None and self.last_frame is not None:
                try:
                    await self._phase35_research_once()
                    self.phase35_error = None
                except Exception as error:
                    self.phase35_error = f'{type(error).__name__}:{str(error)[:160]}'
                    log.exception('phase35_research_withheld')
            for _ in range(30):
                if self.stopping or should_exit():
                    return
                await asyncio.sleep(1)

    async def _volume_research_loop(self, should_exit):
        # No external outcome/source-acquisition lock: fresh research observations
        # must not wait for unrelated unresolved-event provider timeouts.
        while not self.stopping and not should_exit():
            if getattr(self,"phase28",None) is not None and self.last_frame is not None:
                try:
                    from neraium_poly.research.phase28.inputs import current_frame
                    watcher = self.phase26_inputs.watcher if self.phase26_inputs else None
                    frame = current_frame(self.last_frame, extra_markets=tuple(watcher._markets.values()) if watcher else (),
                        extra_books=watcher.observations() if watcher else (), as_of=self.clock())
                    async with self._research_report_lock:
                        def evaluate(current=frame):
                            from neraium_poly.research.phase26.reporting import callbacks
                            vf,vo=callbacks(self.events,self.config.data_dir)
                            self.phase26_index.step(self.events,as_of=self.clock(),forecast_verifier=vf,outcome_verifier=vo)
                            self.phase26_report=self.phase26_index.report(as_of=self.clock())
                            cache=getattr(self,'research_fees',None)
                            proofs=cache.proofs(as_of=self.clock()) if cache else None
                            return self.phase28.step(current,**({'native_fee_observations':proofs} if proofs is not None else {}))
                        worker=asyncio.create_task(asyncio.to_thread(evaluate))
                        try:
                            await asyncio.shield(worker)
                        except asyncio.CancelledError:
                            await asyncio.gather(worker,return_exceptions=True)
                            raise
                except Exception as error:
                    self.phase28.error=f"{type(error).__name__}:{str(error)[:160]}"
                    log.exception("phase28_volume_research_withheld")
            for _ in range(10):
                if self.stopping or should_exit():return
                await asyncio.sleep(1)

    async def _research_fee_loop(self, should_exit):
        from neraium_poly.experimental.research_fee_cache import AsyncBudgetResearchFeeCache
        from neraium_poly.research.phase28.inputs import current_frame
        self.research_fees=AsyncBudgetResearchFeeCache(self.events,self.fee_adapter,clock=self.clock,can_write=self._async_budget_ok)
        while not self.stopping and not should_exit():
            if getattr(self,"phase28",None) is not None and self.last_frame is not None:
                try:
                    watcher=self.phase26_inputs.watcher if self.phase26_inputs else None
                    frame=current_frame(self.last_frame,extra_markets=tuple(watcher._markets.values()) if watcher else (),
                        extra_books=watcher.observations() if watcher and hasattr(watcher,'observations') else watcher.snapshot() if watcher else (),as_of=self.clock())
                    await self.research_fees.refresh(frame,forecast_tokens=getattr(self.phase28,'forecast_tokens',()))
                except (ValueError, TypeError, OSError, KeyError) as error:
                    self.research_fee_error=type(error).__name__
            for _ in range(10):
                if self.stopping or should_exit():return
                await asyncio.sleep(1)

    async def _official_event_score_loop(self, should_exit):
        while not self.stopping and not should_exit():
            scoring=getattr(self,"official_event_scores",None)
            if scoring is not None:
                try:
                    await self._research_io(scoring.step)
                except (ValueError,TypeError,KeyError,OSError) as error:
                    scoring.error=f"{type(error).__name__}:{str(error)[:160]}"
                    log.exception("official_event_research_withheld")
            for _ in range(5):
                if self.stopping or should_exit():return
                await asyncio.sleep(1)

    def _publish_research_scorecards(self,volume,frame,entries):
        try:
            self.domain_scorecard.observe(volume,frame,entries)
        finally:
            self.pair_research.observe(volume,frame)
            headroom=getattr(self,"fee_headroom_research",None)
            if headroom is not None:headroom.observe(volume,frame,self.pair_research.report if not self.pair_research.error else None)

    def _causal_research_fee_observations(self,as_of):
        from neraium_poly.experimental.fees import merge_fee_observations
        cache=getattr(self,"research_fees",None)
        return merge_fee_observations(dict(self.fees),dict(cache.observations) if cache else {},now=as_of)

    def event_operations_summary(self):
        cache=getattr(self,"event_summary_cache",None)
        return cache.snapshot() if cache else {"status":"pending","summary_status":"withheld","certification_authority":False}

    async def _event_summary_sampler(self,should_exit):
        from neraium_poly.research.phase30.scoring import _thread
        while not self.stopping and not should_exit():
            try:
                await _thread(self.event_summary_cache.refresh,self._event_summary)
            except (ValueError,TypeError,KeyError,OSError) as error:
                self.event_summary_cache.failed(error)
            for _ in range(60):
                if self.stopping or should_exit():return
                await asyncio.sleep(1)

    async def _cpi_input_probe_loop(self,should_exit):
        from neraium_poly.research.phase31.macro import collect_cpi_availability, cpi_qualification
        from neraium_poly.research.phase31.scorecard import CPIInputStudy
        next_check=None
        while not self.stopping and not should_exit():
            if getattr(self,"domain_scorecard",None) is not None and (next_check is None or self.clock()>=next_check) and await self._sync_io(self._budget_ok):
                try:
                    bundle=await collect_cpi_availability(clock=self.clock)
                    now=self.clock();target=now.replace(day=1)-timedelta(days=1)
                    result=cpi_qualification(bundle,target_year=target.year,target_month=target.month,as_of=now)
                    from neraium_poly.research.phase14.relationships import digest
                    if await self._sync_io(self._budget_ok):
                        await self._sync_io(self.events.append, CPIInputStudy(id=digest(['cpi-input-v31',bundle]),timestamp=now,available_at=now,source="neraium-poly/CPI-input/v31",bundle=bundle,qualification=result))
                        self.cpi_input_qualification=result
                except (ValueError,TypeError,KeyError,OSError,httpx.HTTPError) as error:
                    self.cpi_input_qualification={"status":"unavailable","reason":type(error).__name__,"forecast_probability":None,"trading_authority":False}
                next_check=self.clock()+timedelta(hours=5)
            for _ in range(30):
                if self.stopping or should_exit():return
                await asyncio.sleep(1)

    async def run(self, should_exit=lambda: False):
        async def independent_events():
            while not self.stopping and not should_exit():
                async with self._research_source_lock:
                    if self.phase18 is not None and self.last_frame is not None and await self._sync_io(self._budget_ok):
                        try:
                            committed = await self._research_io(self.phase18.step, self.last_frame)
                            self.phase18_error = None
                            if committed and self.phase20 is not None:
                                try:
                                    await self._sync_io(self._observe_phase20)
                                    self.phase20_error = None
                                except Exception as error:
                                    self.phase20_error = f"{type(error).__name__}:{str(error)[:160]}"
                                    log.exception("phase20_pairing_withheld")
                            await self._research_io(self.phase18.resolve_pending, self.config.data_dir / "phase18-resolution-evidence")
                            if self.phase21 is not None:
                                try:
                                    await self._research_io(self.phase21.step, self.phase18.state["pending"])
                                    self.phase21_error = None
                                except Exception as error:
                                    self.phase21_error = f"{type(error).__name__}:{str(error)[:160]}"
                                    log.exception("phase21_early_outcome_withheld")
                        except Exception as error:
                            self.phase18_error = f"{type(error).__name__}:{str(error)[:160]}"
                            log.exception("phase18_event_research_withheld")
                    if self.phase23 is not None and self.last_frame is not None and await self._sync_io(self._budget_ok):
                        try:
                            await self._research_io(self.phase23.step, self.last_frame)
                            await self._research_io(self.phase23_outcomes.step)
                            await asyncio.to_thread(self.phase23_competition.step, self.last_frame)
                            self.phase23_error = None
                        except Exception as error:
                            self.phase23_error = f"{type(error).__name__}:{str(error)[:160]}"
                            log.exception("phase23_research_withheld")
                await asyncio.sleep(10)

        async def cycles():
            while not self.stopping and not should_exit():
                try:
                    await self.cycle()
                except Exception as error:
                    self.last_error = f"cycle_failed:{type(error).__name__}"
                    log.exception("experimental_cycle_withheld")
                    await self._sync_io(self._cancel_and_checkpoint, self.clock())
                await asyncio.sleep(self.config.poll_seconds)

        await asyncio.gather(cycles(), self._fees_loop(should_exit), self._event_resolution_loop(should_exit), independent_events(), self._domain_research_loop(should_exit), self._domain_research_loop(should_exit, "phase25"), self._phase35_research_loop(should_exit), self._volume_research_loop(should_exit), self._research_fee_loop(should_exit), self._official_event_score_loop(should_exit), self._event_summary_sampler(should_exit), self._cpi_input_probe_loop(should_exit))

    def health(self):
        last_success = self.last_success
        now = self.clock()
        age = (now - last_success).total_seconds() if last_success else None
        return {
            "status": "ok"
            if age is not None and age < max(30, self.config.poll_seconds * 3) and self.last_error is None
            else "degraded",
            "account_id": "experimental-paper",
            "validation_status": "unvalidated",
            "paper_trading": True,
            "live_trading_enabled": False,
            "last_ingestion_at": last_success.isoformat() if last_success else None,
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

    def archive_state(self):
        """Keep storage/account health readable without copying research histories."""
        from neraium_poly.experimental.operations_ledger import operations_ledger

        capital, counts = operations_ledger(self.account.directory, clock=self.clock)
        return {**counts, "account_id": "experimental-paper", "cash": capital["cash"],
                "bankroll": capital["equity"], "kill_switch": capital["kill_switch"],
                "simulated_pnl": capital["equity"] - self.config.risk_limits.bankroll,
                "generated_at": self.clock().isoformat(), "service": self.health(),
                "archive": self._archive_status(for_operations=True), "experimental_totals": dict(self.totals),
                "scope": "archive health and current simulated capital; research histories remain in /api/state"}

    def phase16_execution_status(self, *, for_operations=False):
        vetoes = passes = None
        error = None
        counter_lock = None
        try:
            if for_operations:
                candidate = getattr(self.events, "_lock", None)
                if candidate is None or not candidate.acquire(blocking=False):
                    raise RuntimeError("archive_counter_measurement_busy")
                counter_lock = candidate
            vetoes = self.events.count(kind="ExecutionVeto")
            passes = self.events.count(kind="ExecutionPass")
        except (AttributeError, OSError, RuntimeError) as exc:
            error = str(exc) if for_operations else type(exc).__name__
        finally:
            if counter_lock is not None:
                counter_lock.release()
        return {"enabled": self.config.phase16_execution_veto_enabled,
                "committed_vetoes": vetoes,
                "committed_check_passes": passes, "counter_error": error,
                "scope": "Lifetime committed emitted-signal checks after signature dedup; pass is not risk approval",
                "legacy_trace_qualification_scope": "Original strategy gate before optional depth veto, including duplicate evaluations",
                "latest_cycle_checks": self.last_phase16_checks}

    def operations_state(self):
        from neraium_poly.research.phase15.operations import add_capacity, experimental_research

        state = add_capacity(self.archive_state(), service="experimental", now=self.clock())
        state["operations_research"] = experimental_research(self, for_operations=True)
        state["native_fee_headroom"] = self.fee_headroom_research.status() if getattr(self,"fee_headroom_research",None) else {"status":"disabled","trading_authority":False}
        state["cross_market_research"] = self.pair_research.status() if getattr(self,"pair_research",None) else {"status":"disabled","trading_authority":False}
        state["domain_scorecard"] = self.domain_scorecard.status() if getattr(self,"domain_scorecard",None) else {"status":"disabled"}
        state["official_event_research"] = self.official_event_scores.status() if getattr(self,"official_event_scores",None) else {"status":"disabled"}
        state["research_costs"] = self.research_fees.status() if getattr(self,"research_fees",None) else None
        state["weather_input_selection"] = getattr(self, "weather_input_selection", {"status":"not_yet_evaluated","trading_authority":False})
        state['independent_weather_research'] = {
            'forecasts': self.phase35.status() if getattr(self, 'phase35', None) else None,
            'native_evidence': self.phase35_native.status() if getattr(self, 'phase35_native', None) else None,
            'discovery': self.phase35_universe.status() if getattr(self, 'phase35_universe', None) else None,
            'official_outcomes': self.phase35_outcomes.status() if getattr(self, 'phase35_outcomes', None) else None,
            'last_error': getattr(self, 'phase35_error', None),
            'native_last_error': getattr(self, 'phase35_native_error', None), 'trading_authority': False}
        state["research_io"] = self._research_worker.status() if getattr(self, "_research_worker", None) else {"status":"not_started","trading_authority":False}
        state["execution_pools"] = getattr(self, "execution_pool_budget", {"status":"not_configured_by_service_entrypoint","trading_authority":False})
        state["memory"] = self.memory_sampler.status() if getattr(self,"memory_sampler",None) else None
        return state

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
                archive=self._archive_status(),
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
                decision_trace={**self.trace.status(),
                    "qualified_opportunities_scope": "legacy strategy gate before optional execution veto; includes duplicate evaluations",
                    "execution_veto": self.phase16_execution_status()},
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
        task = getattr(self, "_close_task", None)
        if task is None:
            self._close_task = task = asyncio.create_task(self._close_resources())
        interrupted = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                interrupted = True
            except Exception:  # noqa: BLE001 - propagate the completed worker result after draining
                break
        if interrupted:
            if not task.cancelled():
                task.exception()
            raise asyncio.CancelledError
        return task.result()

    async def _close_resources(self):
        await self._finish_cycle()
        await self._sync_io(self._cancel_and_checkpoint, self.clock())
        if getattr(self, "_research_worker", None) is not None:
            await self._research_worker.close()
        if getattr(self, "phase26_inputs", None) is not None:
            await self.phase26_inputs.close()
        if getattr(self, "phase26_index", None) is not None:
            self.phase26_index.close()
        await self.feed.close()
        await self.fee_adapter.close()
        # Late outcome/source work is drained before the final recovery image.
        await self._sync_io(self._cancel_and_checkpoint, self.clock())
        try:
            await self._sync_io(self._close_databases)
        finally:
            self._io_executor.shutdown(wait=True, cancel_futures=False)

    def _close_databases(self):
        self._io_closed = True
        if self.event_intelligence is not None:
            self.event_intelligence.close()
        self.events.close()
        self.account.close()


async def serve_experimental(config):
    import uvicorn

    from neraium_poly.ops.api import create_app

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    from neraium_poly.experimental.executors import configure_execution_pools
    pool_budget = await configure_execution_pools()
    runtime = ExperimentalRuntime(config)
    runtime.execution_pool_budget = pool_budget
    app = create_app(runtime=runtime, local_port=config.port)
    server = uvicorn.Server(uvicorn.Config(app, host=config.host, port=config.port, log_level="warning"))
    try:
        await asyncio.gather(server.serve(), runtime.run(lambda: server.should_exit))
    finally:
        await runtime.close()
