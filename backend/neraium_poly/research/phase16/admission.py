"""Additional rejection-only execution checks for already-admitted strategies."""

from hashlib import sha256

from neraium_poly.contracts import Record
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.execution import assess_execution


class ExecutionQualification(Record):
    original_signal_id: str
    original_signal: dict
    original_signal_sha256: str
    legacy_model_code_sha256: str | None = None
    strategy_id: str
    assessment: dict
    vetoed: bool
    qualified: bool = False
    trading_authority: bool = False


class ExecutionVeto(ExecutionQualification):
    """Committed negative-only decision; not a risk order rejection."""


class ExecutionPass(ExecutionQualification):
    """An existing signal passed an additional check, without risk approval."""


def execution_veto(signals, frame, *, now, target_notional=2, model_code_sha256=None):
    markets = {m.token_id: m for m in frame.markets}
    books = {b.token_id: b for b in frame.books}
    result, records = [], []
    for signal in signals:
        if not signal.eligible:
            result.append(signal)
            continue
        assessment = assess_execution(markets.get(signal.token_id), books.get(signal.token_id),
            now=now, target_notional=target_notional, fee_observation=frame.fees.get(signal.token_id),
            forecast_lower_bid=signal.lower_value)
        vetoed = not (assessment["execution_checks_pass"] and assessment["cost_adjusted_edge_pass"])
        record_type = ExecutionVeto if vetoed else ExecutionPass
        record = record_type(id=digest(["phase16-execution-check", signal.id, assessment]),
            timestamp=now, available_at=now, source="phase16-conservative-execution-check",
            original_signal_id=signal.id, original_signal=signal.model_dump(mode="json"),
            original_signal_sha256=sha256(signal.model_dump_json().encode()).hexdigest(),
            legacy_model_code_sha256=model_code_sha256,
            strategy_id=signal.strategy_id, assessment=assessment, vetoed=vetoed)
        records.append(record)
        if vetoed:
            reasons = tuple(sorted(set(signal.reasons + tuple("phase16_"+r for r in assessment["reasons"]))))
            signal = signal.model_copy(update={"id": digest([signal.id, record.id, "veto"]),
                "eligible": False, "reasons": reasons,
                "diagnostics": {**signal.diagnostics, "phase16_execution_veto": record.id}})
        # A passing check leaves the original ID/payload and risk authority unchanged.
        result.append(signal)
    return result, records
