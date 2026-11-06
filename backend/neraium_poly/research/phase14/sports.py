"""Read-only projection of existing sports forecasts into universal contracts.

This module contains no provider, journal writer, account or model activation.
A projected record is a view of historical evidence, never a new observation.
"""

from copy import deepcopy

from neraium_poly.research.phase12.ledger import content_sha256
from neraium_poly.research.phase13.runtime import TernarySportsForecast
from neraium_poly.research.phase14.contracts import DomainForecast


def project_sports_forecast(record):
    """Validate a complete original record and expose a non-admissible projection.

    Source/model replay remains the original research coordinator's job. Schema
    validation here does not certify authenticity, calibration or independence.
    Evidence IDs are original source-dataset references, not newly admitted
    universal-journal evidence records. Do not append or double-count this view.
    """
    raw = record.model_dump(mode="json") if isinstance(record, TernarySportsForecast) else deepcopy(record)
    original_hash = content_sha256(raw)
    original = TernarySportsForecast.model_validate(raw)
    prediction = original.prediction
    vector = deepcopy(prediction.uncertainty["outcome_probabilities"])
    forecast = DomainForecast(
        id=original.id,
        timestamp=original.timestamp,
        available_at=original.timestamp,
        source="neraium-poly/legacy-sports-journal/read-only-projection-v1",
        domain="sports",
        event_id=original.mapping.event_id,
        market_id=original.mapping.market_id,
        token_id=original.mapping.token_id,
        contract_type="match_winner_including_overtime",
        probability_semantics="outcome_distribution",
        probability=None,
        outcome_probabilities=vector,
        evidence_cutoff=original.evidence_cutoff,
        model_version=prediction.model_version,
        model_sha256=prediction.model_sha256,
        feature_version=prediction.feature_version,
        dataset_sha256=prediction.dataset_sha256,
        rules_sha256=original.mapping.rules_sha256,
        evidence_ids=(original.source_dataset_sha256,),
        uncertainty=deepcopy(prediction.uncertainty),
        calibration_status=prediction.calibration_status,
        independent_of_polymarket=True,  # Original declared estimand, not new source qualification.
        dependency_group=original.dependency_group,
        contemporaneous_market={
            "market": original.market.model_dump(mode="json"),
            "book": original.book.model_dump(mode="json"),
            "market_expected_payout_baseline": original.market_expected_payout_baseline,
            "market_win_probability": None,
            "baseline_comparison": original.baseline_comparison,
        },
    )
    return {
        "projection_only": True,
        "admissible_to_new_journal": False,
        "count_as_new_forecast": False,
        "original_record_sha256": original_hash,
        "original_record_id": original.id,
        "source_integrity_replayed": False,
        "qualification_scope": "Complete original schema validation only; independent source replay remains required",
        "forecast": forecast,
    }
