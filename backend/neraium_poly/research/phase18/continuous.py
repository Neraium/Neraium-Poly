"""Prospective independent event studies in the existing managed research archive."""

import asyncio
import hashlib
import json
import math
from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, Record
from neraium_poly.data import assess_book
from neraium_poly.research.phase12.contracts import SettlementProofReference
from neraium_poly.research.phase14.contracts import DomainContract, DomainForecast
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.checkpoints import pack_checkpoint, unpack_checkpoint
from neraium_poly.research.phase18.capacity import capacity_scenarios
from neraium_poly.research.phase18.convergence import qualify_convergence
from neraium_poly.research.phase18.forecasting import forecast_event, map_event_contract
from neraium_poly.research.phase18.sources import collect_event_evidence, completed_minutes


class EventProbabilityStudy(Record):
    parent_id: str | None = None
    operation: str = "forecast_scan"
    source_frame_id: str | None = None
    scan: dict = Field(default_factory=dict)
    market: dict | None = None
    book: dict | None = None
    contract: dict | None = None
    evidence: list[dict] = Field(default_factory=list)
    model_result: dict = Field(default_factory=dict)
    forecast: dict | None = None
    comparison: dict = Field(default_factory=dict)
    capacity: dict = Field(default_factory=dict)
    outcome: dict | None = None
    checkpoint: dict
    checkpoint_sha256: str
    trading_authority: bool = False
    certification_authority: bool = False


def _at(value):
    at = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if at.tzinfo is None:
        raise ValueError("aware event research time required")
    return at.astimezone(UTC)


class IndependentEventResearch:
    """One bounded external source refresh per five minutes; no account methods.

    New event probability models and old monetary-mark challengers remain distinct.
    Original Phase14/16/17 journals and model/checkpoint versions are not rewritten.
    """

    def __init__(self, store, *, clock=None, can_write=None, interval=300,
                 mapper=None, collector=None, forecaster=None):
        if not 300 <= interval <= 3600:
            raise ValueError("bounded event source refresh required")
        self.store, self.clock = store, clock or (lambda: datetime.now(UTC))
        self.can_write = can_write or (lambda: True)
        self.mapper, self.collector, self.forecaster = mapper or map_event_contract, collector or collect_event_evidence, forecaster or forecast_event
        self.interval, self.lock = interval, asyncio.Lock()
        self.code_sha256 = hashlib.sha256(b"".join(Path(__file__).with_name(n).read_bytes()
            for n in ("continuous.py", "forecasting.py", "sources.py", "convergence.py", "capacity.py", "validation.py"))).hexdigest()
        self.last_id = self.pending_commit = None
        self.last_error = None
        self.verified_this_process = set()
        self.state = {"version": "phase18-independent-event-v1", "code_sha256": self.code_sha256,
            "activated_at": _at(self.clock()).isoformat(), "last_at": None, "last_attempt_at": None,
            "last_outcome_check": None, "scans": 0, "markets_considered": 0, "source_attempts": 0,
            "source_successes": 0, "forecasts": 0, "outcomes": 0, "forecasts_by_domain": {},
            "parents": [], "pending": {}, "outcome_ids": [], "rejections": {}, "latest": {},
            "approaches": {name: {"evaluated": 0, "qualified": 0, "rejected": 0,
                "orders": 0, "fills": 0, "net_pnl": None, "net_return": None,
                "drawdown": None, "capital_turnover": None, "risk_adjusted_performance": None}
                for name in ("high_throughput", "high_conviction")}}
        rows = store.latest("EventProbabilityStudy", limit=1)
        if rows:
            row = EventProbabilityStudy.model_validate(rows[0]);state = unpack_checkpoint(row.checkpoint)
            if (digest(state) != row.checkpoint_sha256 or state.get("last_at") != row.available_at.isoformat()
                or row.trading_authority or row.certification_authority):
                raise ValueError("event research checkpoint integrity/time mismatch")
            self._restore(state)
            self.last_id = row.id

    def _restore(self, state):
        if state.get("version") != "phase18-independent-event-v1" or state.get("code_sha256") != self.code_sha256:
            raise ValueError("event model policy differs; no silent research reset")
        for key, limit in (("pending", 128), ("parents", 1024), ("outcome_ids", 1024), ("rejections", 128)):
            if not isinstance(state.get(key), (dict, list)) or len(state[key]) > limit:
                raise ValueError("bounded event research state required")
        self.state = deepcopy(state)

    def _ready(self):
        if not self.can_write():
            return False
        if hasattr(self.store, "status"):
            a = self.store.status();reserve = 16*1024**2
            return (a.get("health") == "ok" and a.get("free_bytes", 0) >= a.get("global_floor_bytes", 0)+reserve
                    and a.get("usage_bytes", 0)+reserve <= a.get("budget_bytes", 0))
        return True

    def _reconcile(self):
        if self.pending_commit:
            row, state = self.pending_commit
            self.store.append(row)
            self._restore(state)
            self.last_id, self.pending_commit = row.id, None

    def _commit(self, before, *, now, **fields):
        try:
            self.state["last_at"] = now.isoformat()
            state = json.loads(json.dumps(self.state, sort_keys=True, allow_nan=False))
            row = EventProbabilityStudy(id=digest(["phase18-event-study", self.last_id, digest(state), fields]),
                timestamp=now, available_at=now, source="phase18-independent-event-research",
                parent_id=self.last_id, checkpoint=pack_checkpoint(state), checkpoint_sha256=digest(state), **fields)
            self.pending_commit = row, state
            self.store.append(row)
        except Exception:
            self.state = before
            self.last_error = "event_study_not_committed"
            raise
        self.last_id, self.pending_commit, self.last_error = row.id, None, None
        return True

    async def step(self, frame):
        async with self.lock:
            self._reconcile();now = _at(self.clock())
            if not self._ready():
                self.last_error = "event_research_storage_backpressure"
                return False
            if self.state["last_attempt_at"] and (now-_at(self.state["last_attempt_at"])).total_seconds() < self.interval:
                return False
            raw = frame.model_dump(mode="json") if hasattr(frame, "model_dump") else frame
            if (not isinstance(raw, dict) or raw.get("producer_health", {}).get("status") != "ok"
                or not 0 <= (now-_at(raw["available_at"])).total_seconds() <= 15):
                self.last_error = "fresh_qualified_shared_market_frame_required"
                return False
            before = deepcopy(self.state);reasons=Counter();candidates=[]
            books = {b["token_id"]: b for b in raw["books"]}
            for value in raw["markets"][:1000]:
                market = MarketSnapshot.model_validate(value)
                c = self.mapper(market, now=now)
                if not c.compatible or c.review_required:
                    reasons.update(c.reasons or ("domain_contract_not_supported",));continue
                book = books.get(market.token_id)
                if book is None or not assess_book(OrderBookSnapshot.model_validate(book), now,
                    max_spread=.05, expected_token=market.token_id).healthy:
                    reasons["current_event_executable_book_unavailable"]+=1;continue
                candidates.append((market.outcome.casefold() != "yes", c.domain, market.event_id, market.market_id, market, book, c))
            self.state["last_attempt_at"] = now.isoformat();self.state["scans"]+=1
            self.state["markets_considered"]+=len(raw["markets"])
            scan={"considered_tokens":len(raw["markets"]),"compatible_tokens":len(candidates),"rejections":dict(reasons)}
            fields={"source_frame_id":raw.get("id"),"scan":scan}
            if candidates:
                _no,_domain,_parent,_market,market,book,c=min(candidates,key=lambda x:x[:4])
                self.state["source_attempts"]+=1
                evidence=();result={"status":"withheld","probability":None,"reasons":[]}
                try:
                    evidence=await self.collector(c,now=now)
                    after=_at(self.clock())
                    result=self.forecaster(c,evidence,cutoff=after)
                    self.state["source_successes"]+=1
                    f=None
                    if result.get("status")=="research_estimate" and result.get("probability") is not None:
                        b=OrderBookSnapshot.model_validate(book)
                        if not assess_book(b,after,max_spread=.05,expected_token=market.token_id).healthy:
                            raise ValueError("event_quote_stale_after_external_retrieval")
                        if len(self.state["pending"])>=128:
                            raise ValueError("pending_event_forecast_capacity_reached")
                        if c.event_id not in self.state["parents"] and len(self.state["parents"])>=1024:
                            raise ValueError("parent_event_capacity_reached")
                        f=DomainForecast(id=digest(["phase18-forecast",market.id,result,after.isoformat()]),
                            timestamp=after,available_at=after,source="phase18-independent-event-probability",
                            domain=c.domain,event_id=c.event_id,market_id=c.market_id,token_id=c.token_id,
                            contract_type=c.contract_type,probability_semantics=c.probability_semantics,
                            probability=result["probability"],evidence_cutoff=after,model_version=result["model_version"],
                            model_sha256=result["model_sha256"],feature_version=result["feature_version"],
                            dataset_sha256=result["dataset_sha256"],rules_sha256=c.rules_sha256,
                            evidence_ids=tuple(result["evidence_ids"]),uncertainty=result["uncertainty"],
                            calibration_status=result["calibration_status"],independent_of_polymarket=True,
                            dependency_group="unreviewed-parent:"+c.event_id,
                            contemporaneous_market={"contract":c.model_dump(mode="json"),"market":market.model_dump(mode="json"),"book":book})
                        self.state["forecasts"]+=1
                        self.state["forecasts_by_domain"][c.domain]=self.state["forecasts_by_domain"].get(c.domain,0)+1
                        if c.event_id not in self.state["parents"]:self.state["parents"].append(c.event_id)
                        self.state["pending"][f.id]=f.model_dump(mode="json")
                    else:reasons.update(result.get("reasons",["independent_event_probability_withheld"]))
                    convergence=qualify_convergence(f,market,book,evidence,now=after,risk_context=None)
                    capacity=capacity_scenarios(convergence,book)
                    for name,row in convergence["approaches"].items():
                        counter=self.state["approaches"][name];counter["evaluated"]+=1
                        qualified=row.get("research_qualified") is True
                        counter["qualified"]+=qualified;counter["rejected"]+=not qualified
                    fields.update(market=market.model_dump(mode="json"),book=book,contract=c.model_dump(mode="json"),
                        evidence=[e.model_dump(mode="json") for e in evidence],model_result=result,
                        forecast=f.model_dump(mode="json") if f else None,comparison=convergence,capacity=capacity)
                    self.state["latest"]={"domain":c.domain,"event_id":c.event_id,"market_id":c.market_id,
                        "forecast_id":f.id if f else None,"probability":f.probability if f else None,
                        "model_version":result.get("model_version"),"calibration_status":result.get("calibration_status"),
                        "rejections":convergence["reasons"],"research_qualified":False,"source_retrieved_at":after.isoformat()}
                except Exception as exc:  # noqa: BLE001 - withhold unsupported evidence, never admit a trade
                    # Incomplete downstream assessment cannot leave a hidden forecast in state.
                    self.state=deepcopy(before)
                    self.state["last_attempt_at"]=now.isoformat();self.state["scans"]+=1
                    self.state["markets_considered"]+=len(raw["markets"])
                    self.state["source_attempts"]+=1
                    reasons[type(exc).__name__+":"+str(exc)[:100]]+=1
                    fields.update(market=market.model_dump(mode="json"),book=book,contract=c.model_dump(mode="json"),
                        evidence=[e.model_dump(mode="json") for e in evidence],model_result={"status":"withheld","reasons":[str(exc)[:120]]})
            for reason,count in reasons.items():
                key=reason if reason in self.state["rejections"] or len(self.state["rejections"])<128 else "other_bounded_rejections"
                self.state["rejections"][key]=self.state["rejections"].get(key,0)+count
            if not self._ready():
                self.state=before;self.last_error="event_research_storage_backpressure";return False
            return self._commit(before,now=_at(self.clock()),**fields)

    async def resolve_pending(self, directory):
        """Native finalized settlement PLUS the exact independent reference window."""
        from neraium_poly.research.phase12.outcome_collector import (
            acquire_verified_outcome,
            verify_collected_outcome,
        )
        async with self.lock:
            self._reconcile();now=_at(self.clock())
            if not self._ready() or self.state["last_outcome_check"] and (now-_at(self.state["last_outcome_check"])).total_seconds()<300:return False
            for raw in self.state["pending"].values():
                f=DomainForecast.model_validate(raw);m=MarketSnapshot.model_validate(f.contemporaneous_market["market"])
                if not m.end_time or m.end_time>now:continue
                before=deepcopy(self.state);self.state["last_outcome_check"]=now.isoformat()
                reference=SettlementProofReference(id=f.id,event_id=f.event_id,market_id=f.market_id,token_id=f.token_id,
                    timestamp=f.timestamp,evidence_cutoff=f.evidence_cutoff,resolution_rules_sha256=f.rules_sha256,
                    original_record_sha256=digest(raw))
                output=Path(directory)/(now.strftime("%Y%m%dT%H%M%S%fZ")+"-"+f.id[:12])
                fields={"operation":"outcome_check","forecast":raw,"model_result":{"status":"withheld","reasons":[]}}
                try:
                    outcome=await acquire_verified_outcome(reference,m,output,clock=self.clock)
                    if outcome is None or not await asyncio.to_thread(verify_collected_outcome,outcome,m,reference,output.parent):
                        raise ValueError("native_finalized_settlement_proof_unavailable")
                    c=DomainContract.model_validate(f.contemporaneous_market["contract"])
                    evidence=await self.collector(c,now=_at(self.clock()))
                    rows=completed_minutes(evidence[0],cutoff=_at(self.clock()),symbol=c.parameters["symbol"])
                    start,end=map(_at,(c.parameters["period_start_utc"],c.parameters["period_end_utc"]))
                    window=[x for x in rows if int(start.timestamp()*1000)<=x["open_ms"]<int(end.timestamp()*1000)]
                    if (not window or window[0]["open_ms"]!=int(start.timestamp()*1000)
                        or window[-1]["close_ms"]!=int(end.timestamp()*1000)-1):raise ValueError("complete_final_reference_window_required")
                    yes=int(min(x["low"] for x in window)<=c.parameters["threshold"])
                    expected=yes if c.parameters["selected_outcome"]=="Yes" else 1-yes
                    if outcome.payout!=expected:raise ValueError("official_payout_and_independent_reference_disagree")
                    baseline_book=OrderBookSnapshot.model_validate(f.contemporaneous_market["book"])
                    baseline=(baseline_book.bids[0].price+baseline_book.asks[0].price)/2
                    probability=f.probability;likelihood=probability if expected else 1-probability
                    fields.update(outcome=outcome.model_dump(mode="json"),evidence=[e.model_dump(mode="json") for e in evidence],
                        model_result={"status":"native_and_reference_verified","reference_payout":expected,
                            "individual_score":{"brier":(probability-expected)**2,"market_brier":(baseline-expected)**2,
                                "log_loss":-math.log(likelihood) if likelihood>0 else None,
                                "log_loss_status":"finite" if likelihood>0 else "positive_infinity",
                                "independent_event_reviewed":False,"headline_performance_supported":False}})
                    self.state["outcomes"]+=1;self.state["outcome_ids"].append(outcome.id)
                    self.state["pending"].pop(f.id);self.verified_this_process.add(outcome.id)
                except Exception as exc:  # noqa: BLE001 - preserve unresolved forecasts and all attempts
                    fields["model_result"]["reasons"]=[str(exc)[:160]]
                return self._commit(before,now=_at(self.clock()),**fields)
            return False

    def summary(self):
        s=self.state
        return {"status":"research_only","last_evaluation_at":s["last_at"],"scans":s["scans"],
            "source_attempts":s["source_attempts"],"source_successes":s["source_successes"],
            "independent_research_forecasts":s["forecasts"],"forecasts_by_domain":dict(s["forecasts_by_domain"]),
            "unreviewed_parent_events":len(s["parents"]),"pending_forecasts":len(s["pending"]),
            "durable_outcome_records":s["outcomes"],"outcomes_reverified_this_process":len(self.verified_this_process.intersection(s["outcome_ids"])),
            "qualified_training_events":0,"qualified_heldout_events":0,"certification_requirements":{"training":100,"heldout":100},
            "calibration_status":"insufficient independent verified events","brier":None,"log_loss":None,
            "approaches":deepcopy(s["approaches"]),"latest":deepcopy(s["latest"]),"rejections":dict(s["rejections"]),
            "domain_support":{"crypto":"exact daily-low conditional uncalibrated research",
                "weather":"calibrated station/window predictive evidence required",
                "economics":"verified first-release vintages and outcome model required",
                "sports":"existing NFL prospective journal preserved"},
            "last_error":self.last_error,"model_code_sha256":self.code_sha256,
            "counter_scope":"durable research scans/forecasts; repeated parent forecasts are not independent events",
            "trading_authority":False,"certification_authority":False,"live_trading_enabled":False}
