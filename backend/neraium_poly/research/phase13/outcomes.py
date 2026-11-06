"""Independent sports result corroboration never replaces exchange settlement."""

import hashlib

from neraium_poly.research.phase13.contracts import SourceArtifact, SportsGame, SportsMapping


def corroborate_sports_outcome(outcome, forecast, market, mapping, games, artifacts, *, now):
    """Require published final score AND caller-verified Phase12 exchange proof.

    This function does not independently verify the chain proof. The caller must
    first run Phase12's immutable native+finalized-CTF verifier. nflverse is a
    separately published result source, not represented as an official NFL API.
    Canceled, postponed, disputed, corrected/ambiguous and tied records withhold.
    """
    mapping = SportsMapping.model_validate(
        mapping.model_dump() if isinstance(mapping, SportsMapping) else mapping
    )
    games = [SportsGame.model_validate(g.model_dump() if isinstance(g, SportsGame) else g) for g in games]
    artifacts = [
        SourceArtifact.model_validate(a.model_dump() if isinstance(a, SourceArtifact) else a)
        for a in artifacts
    ]
    reasons = []
    if now.tzinfo is None or outcome.available_at > now or outcome.settled_at > now:
        reasons.append("future_or_naive_result_cutoff")
    if (mapping.event_id, mapping.market_id, mapping.token_id) != (
        forecast.event_id,
        forecast.market_id,
        forecast.token_id,
    ):
        reasons.append("original_sports_mapping_mismatch")
    if (outcome.event_id, outcome.market_id, outcome.token_id) != (
        forecast.event_id,
        forecast.market_id,
        forecast.token_id,
    ):
        reasons.append("exchange_outcome_identity_mismatch")
    rules_hash = hashlib.sha256(market.resolution_rules.encode()).hexdigest()
    if (
        rules_hash != mapping.rules_sha256
        or rules_hash != forecast.resolution_rules_sha256
        or rules_hash != outcome.resolution_rules_sha256
    ):
        reasons.append("resolution_rules_changed")
    if forecast.timestamp >= mapping.event_start or forecast.timestamp >= outcome.settled_at:
        reasons.append("forecast_not_pre_event_and_settlement")
    matches = [
        g
        for g in games
        if (g.provider, g.league, g.game_id) == (mapping.provider, mapping.league, mapping.game_id)
    ]
    if len(matches) != 1:
        reasons.append("ambiguous_or_corrected_external_result")
        game = None
    else:
        game = matches[0]
        if game.status != "final":
            reasons.append("external_result_" + game.status)
        if game.starts_at != mapping.event_start:
            reasons.append("event_rescheduled_requires_mapping_review")
        if {game.home_id, game.away_id} != {mapping.selected_team_id, mapping.opponent_team_id}:
            reasons.append("external_participants_changed")
        if game.available_at > now or game.result_observed_at is None or game.result_observed_at > now:
            reasons.append("qualified_final_result_unavailable")
        if not game.includes_overtime:
            reasons.append("final_overtime_scope_unverified")
        source = [
            a for a in artifacts if a.content_sha256 == game.artifact_sha256 and a.provider == game.provider
        ]
        if len(source) != 1 or source[0].quality != "qualified" or source[0].available_at > now:
            reasons.append("qualified_result_source_missing")
        if game.home_score is None or game.away_score is None:
            reasons.append("final_score_missing")
        elif game.home_score == game.away_score:
            reasons.append("tie_or_refund_not_binary_outcome")
        elif game.status == "final":
            winner = game.home_id if game.home_score > game.away_score else game.away_id
            if int(mapping.selected_team_id == winner) != outcome.payout:
                reasons.append("independent_result_exchange_payout_disagreement")
    return {
        "accepted": not reasons,
        "status": "corroborated" if not reasons else "unresolved",
        "reasons": sorted(set(reasons)),
        "game_id": mapping.game_id,
        "independent_result_source": game.provider if game else None,
        "independent_source_is_official_league_api": False,
        "result_artifact_sha256": game.artifact_sha256 if game else None,
        "market_id": forecast.market_id,
        "forecast_id": forecast.id,
        "no_account_settlement_authority": True,
    }


def score_ternary_forecast(probabilities, game, selected_team_id):
    """Descriptive multiclass score only; not an independence/calibration claim."""
    import math

    if (
        set(probabilities) != {"win", "tie", "loss"}
        or any(
            not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 < p < 1
            for p in probabilities.values()
        )
        or abs(sum(probabilities.values()) - 1) > 1e-10
    ):
        raise ValueError("normalized positive W/T/L probabilities required")
    if game.status != "final" or game.home_score is None or game.away_score is None:
        raise ValueError("verified final score required")
    if selected_team_id not in {game.home_id, game.away_id}:
        raise ValueError("selected result participant mismatch")
    if game.home_score == game.away_score:
        actual = "tie"
    else:
        winner = game.home_id if game.home_score > game.away_score else game.away_id
        actual = "win" if selected_team_id == winner else "loss"
    return {
        "actual": actual,
        "multiclass_brier": sum((p - int(k == actual)) ** 2 for k, p in probabilities.items()),
        "log_loss": -math.log(probabilities[actual]),
        "market_win_brier": None,
        "interpretation": "One-event descriptive score; no independent superiority or profitability claim",
    }
