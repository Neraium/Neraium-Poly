"""Deterministic, external-result-only sports baselines for prospective research.

These methods have no market-price input. They are uncalibrated challengers,
not certified forecasts or estimates of executable trading profitability.
"""

import hashlib
import json
from collections import Counter
from datetime import timedelta
from math import log, sqrt
from pathlib import Path

from neraium_poly.research.phase13.contracts import SportsGame, SportsPrediction

FEATURE_VERSION = "causal-external-publisher-results-v1"
MODEL_VERSION = "sports-independent-baselines-v1"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _game(value):
    return SportsGame.model_validate(value.model_dump() if isinstance(value, SportsGame) else value)


def training_games(games, target, cutoff, *, max_age_days=730):
    """Select each provider's final game once using only observed causal results.

    First retrieval is an availability bound, not a claim that this historical
    record was available before its retrieval. Ambiguous identities fail closed.
    """
    target = _game(target)
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("aware forecast cutoff required")
    if target.status != "scheduled" or target.starts_at <= cutoff or target.available_at > cutoff:
        raise ValueError("qualified upcoming scheduled target required")
    if not target.includes_overtime:
        raise ValueError("only full-game results including overtime are supported")
    if type(max_age_days) is not int or not 30 <= max_age_days <= 1095:
        raise ValueError("bounded training lookback required")
    floor = cutoff - timedelta(days=max_age_days)
    eligible = {}
    seen_current = {}
    for index, value in enumerate(games):
        if index >= 25000:
            raise ValueError("bounded sports training corpus required")
        game = _game(value)
        if game.league != target.league or game.provider != target.provider:
            continue
        if game.available_at > cutoff:
            continue
        identity = (game.provider, game.league, game.game_id)
        if game.game_id == target.game_id:
            if game.status != "scheduled" or game.starts_at != target.starts_at:
                raise ValueError("target has contradictory known event status")
            continue
        old = seen_current.get(identity)
        if old is not None and (
            old.home_id, old.away_id, old.starts_at
        ) != (game.home_id, game.away_id, game.starts_at):
            raise ValueError("conflicting historical event identity")
        if old is None or old.available_at < game.available_at:
            seen_current[identity] = game
        elif old.available_at == game.available_at and old != game:
            raise ValueError("ambiguous historical event revision")
    for identity, game in seen_current.items():
        if (
            game.status != "final"
            or not game.includes_overtime
            or game.starts_at < floor
            or game.starts_at >= cutoff
            or game.result_observed_at is None
            or game.result_observed_at > cutoff
        ):
            continue
        if game.league == "NBA" and game.home_score == game.away_score:
            raise ValueError("tied NBA final result is unsupported")
        eligible[identity] = game
    return tuple(sorted(eligible.values(), key=lambda g: (g.starts_at, g.game_id)))


def _elo(games, home_id, away_id, *, k=20.0, home_advantage=50.0):
    ratings = {}
    for game in games:
        home = ratings.get(game.home_id, 1500.0)
        away = ratings.get(game.away_id, 1500.0)
        expectation = 1 / (1 + 10 ** ((away - home - home_advantage) / 400))
        outcome = float(game.home_score > game.away_score)
        update = k * (outcome - expectation)
        ratings[game.home_id], ratings[game.away_id] = home + update, away - update
    home = ratings.get(home_id, 1500.0)
    away = ratings.get(away_id, 1500.0)
    return 1 / (1 + 10 ** ((away - home - home_advantage) / 400)), {home_id: home, away_id: away}


def _frequency(games, home_id, away_id):
    counts, wins = Counter(), Counter()
    for game in games:
        counts.update((game.home_id, game.away_id))
        wins[game.home_id if game.home_score > game.away_score else game.away_id] += 1
    # Beta(1,1) posterior means represent independent historical strength, not
    # market odds. Log-odds difference yields a transparent paired baseline.
    a = (wins[home_id] + 1) / (counts[home_id] + 2)
    b = (wins[away_id] + 1) / (counts[away_id] + 2)
    p = a * (1 - b) / (a * (1 - b) + (1 - a) * b)
    return p, {home_id: a, away_id: b}


def _nfl_frequency(games, selected, opponent):
    counts, wins, ties, losses = Counter(), Counter(), Counter(), Counter()
    for game in games:
        counts.update((game.home_id, game.away_id))
        if game.home_score == game.away_score:
            ties.update((game.home_id, game.away_id))
        else:
            winner, loser = (game.home_id, game.away_id) if game.home_score > game.away_score else (
                game.away_id, game.home_id
            )
            wins[winner] += 1
            losses[loser] += 1
    # Equal-weight Dirichlet(1,1,1) participant form and opposing form.
    # The three probabilities sum to one; no conditional-on-no-tie shortcut.
    win = 0.5 * ((wins[selected] + 1) / (counts[selected] + 3)
                 + (losses[opponent] + 1) / (counts[opponent] + 3))
    tie = 0.5 * ((ties[selected] + 1) / (counts[selected] + 3)
                 + (ties[opponent] + 1) / (counts[opponent] + 3))
    loss = 1 - win - tie
    return win, {"win": win, "tie": tie, "loss": loss}


def predict_game(
    games, target, selected_team_id, cutoff, *, method="elo", min_training_games=50, min_team_games=10,
    max_age_days=730,
):
    """Produce a reproducible research probability or reject inadequate evidence.

    A caller must independently verify source artifacts and game mapping. This
    pure function cannot establish provider authenticity from caller assertions.
    Its uncertainty is a deliberately broad heuristic sensitivity envelope, not
    a confidence interval learned from held-out outcomes.
    """
    target = _game(target)
    if method not in {"elo", "frequency"}:
        raise ValueError("unsupported independent sports method")
    if (
        type(min_training_games) is not int or not 50 <= min_training_games <= 10000
        or type(min_team_games) is not int or not 10 <= min_team_games <= 1000
    ):
        raise ValueError("minimum research evidence is 50 league games and 10 per participant")
    if selected_team_id not in (target.home_id, target.away_id):
        raise ValueError("selected participant does not belong to target")
    if target.league == "NFL" and method != "frequency":
        raise ValueError("NFL Elo expected score cannot be advertised as unconditional win probability")
    data = training_games(games, target, cutoff, max_age_days=max_age_days)
    counts = Counter(team for g in data for team in (g.home_id, g.away_id))
    if len(data) < min_training_games:
        raise ValueError("insufficient causal league training games")
    if min(counts[target.home_id], counts[target.away_id]) < min_team_games:
        raise ValueError("insufficient causal participant training games")
    outcomes = None
    if target.league == "NFL":
        opponent = target.away_id if selected_team_id == target.home_id else target.home_id
        p, outcomes = _nfl_frequency(data, selected_team_id, opponent)
        strengths, sensitivities = {}, [p]
    elif method == "elo":
        p, strengths = _elo(data, target.home_id, target.away_id)
        sensitivities = [
            _elo(data, target.home_id, target.away_id, k=k, home_advantage=h)[0]
            for k in (10.0, 20.0, 30.0) for h in (0.0, 50.0, 100.0)
        ]
    else:
        p, strengths = _frequency(data, target.home_id, target.away_id)
        sensitivities = [p]
    if target.league != "NFL" and selected_team_id == target.away_id:
        p, sensitivities = 1 - p, [1 - x for x in sensitivities]
    p = max(0.001, min(0.999, p))
    penalty = min(0.45, 0.15 + 0.25 * sqrt(1 / counts[target.home_id] + 1 / counts[target.away_id]))
    lower = max(0.0, min(p, min(sensitivities)) - penalty)
    upper = min(1.0, max(p, max(sensitivities)) + penalty)
    config = {
        "method": method, "min_training_games": min_training_games, "min_team_games": min_team_games,
        "max_age_days": max_age_days, "initial_elo": 1500, "elo_k": 20, "home_advantage": 50,
        "frequency_prior": [1, 1, 1] if target.league == "NFL" else [1, 1],
        "probability_clip": [0.001, 0.999], "league": target.league,
    }
    return SportsPrediction(
        game_id=target.game_id,
        selected_team_id=selected_team_id,
        probability=p,
        lower_probability=lower,
        upper_probability=upper,
        cutoff=cutoff,
        model_version=MODEL_VERSION + "/" + method,
        model_sha256=digest({"source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                             "config": config}),
        feature_version=FEATURE_VERSION,
        dataset_sha256=digest([g.model_dump(mode="json") for g in data]),
        training_games=len(data),
        participant_games={target.home_id: counts[target.home_id], target.away_id: counts[target.away_id]},
        uncertainty={
            "type": "uncalibrated_parameter_sensitivity_plus_sample_penalty",
            "estimand": "unconditional_team_win_probability_including_overtime",
            "outcome_probabilities": outcomes,
            "fractional_tie_contract_market_comparison_supported": target.league != "NFL",
            "expected_payout": p + 0.5 * outcomes["tie"] if outcomes else p,
            "expected_payout_is_not_win_probability": target.league == "NFL",
            "confidence_interval": False, "coverage_guarantee": False, "config": config,
            "parameter_probability_min": min(sensitivities), "parameter_probability_max": max(sensitivities),
            "sample_penalty": penalty, "strengths": strengths,
            "missing_features": ["injuries", "lineups", "rest_adjustment", "roster_changes"],
            "source_authenticity": "must_be_verified_by_source_adapter",
            "historical_availability": "observed_retrieval_only; no retrospective PIT claim",
            "training_game_ids": [g.game_id for g in data],
            "latest_training_start": max(g.starts_at for g in data).isoformat(),
            "latest_result_observed_at": max(g.result_observed_at for g in data).isoformat(),
            "heldout_calibration_events": 0,
            "certification_authority": False, "trading_authority": False,
        },
    )


def verify_prediction(prediction, games, target):
    """Strict replay of the exact source version/config; never self-certification."""
    try:
        prediction = SportsPrediction.model_validate(
            prediction.model_dump() if isinstance(prediction, SportsPrediction) else prediction
        )
        config = prediction.uncertainty["config"]
        expected = predict_game(
            games, target, prediction.selected_team_id, prediction.cutoff,
            method=config["method"], min_training_games=config["min_training_games"],
            min_team_games=config["min_team_games"], max_age_days=config["max_age_days"],
        )
        return prediction.model_dump(mode="json") == expected.model_dump(mode="json")
    except (ValueError, KeyError, TypeError):
        return False


def historical_diagnostic(games, cutoff):
    """No retroactive backtest: report authentic evidence available today only."""
    parsed = tuple(_game(g) for g in games)
    if cutoff.tzinfo is None:
        raise ValueError("aware diagnostic cutoff required")
    available = [g for g in parsed if g.available_at <= cutoff and g.status == "final"]
    return {
        "schema_version": "1.0", "cutoff": cutoff.isoformat(),
        "observed_final_games": len({(g.provider, g.league, g.game_id) for g in available}),
        "qualified_historical_forecast_pairs": 0,
        "brier": None, "log_loss": None, "calibration": None,
        "market_brier": None, "confidence_interval": None,
        "reason": "Retrieved historical scores do not establish pregame historical feature/market availability",
        "future_use": "May train prospective models only after independently verified retrieval availability",
        "certification_authority": False,
    }


def log_loss(probability, outcome):
    """Finite binary proper score, with explicit numerical clipping."""
    p = max(1e-12, min(1 - 1e-12, probability))
    return -(outcome * log(p) + (1 - outcome) * log(1 - p))
