"""Exact participant/schedule/rule mapping. Unsupported contract forms quarantine."""

import hashlib
import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from neraium_poly.contracts import MarketSnapshot
from neraium_poly.research.phase13.contracts import SportsGame, SportsMapping
from neraium_poly.research.phase13.sources import TEAMS, digest


def normalize(value):
    return " ".join(value.casefold().strip().split())


def _aliases():
    result = {}
    for identity, name in TEAMS.items():
        aliases = {name, name.split()[-1], identity}
        if identity in {"SF", "GB", "TB", "NE", "NO", "LA", "LAC", "LV", "KC", "NYG", "NYJ"}:
            aliases.add(" ".join(name.split()[2:]))
        for alias in aliases:
            key = normalize(alias)
            if key in result and result[key] != identity:
                raise ValueError("ambiguous_team_alias")
            result[key] = identity
    return result


ALIASES = _aliases()


def map_market(market, games, *, now):
    """Map pre-event two-team NFL match winner only. No fuzzy names or time guesses.

    Scheduled time must match explicit rules' US Eastern month/day and time,
    market end time and provider schedule. A moved date/time therefore quarantines
    rather than silently applying cancellation/postponement rules.
    """
    market = MarketSnapshot.model_validate(
        market.model_dump() if isinstance(market, MarketSnapshot) else market
    )
    if now.tzinfo is None or market.timestamp > now or market.available_at > now or market.status != "active":
        raise ValueError("mapping_noncausal_or_inactive_market")
    if market.resolution_source.rstrip("/") != "https://www.nfl.com/scores":
        raise ValueError("mapping_unsupported_league_or_resolution_source")
    match = re.fullmatch(r"([^:()]+) vs\. ([^:()]+)", market.question)
    if not match:
        raise ValueError("mapping_unsupported_contract_question")
    sides = [ALIASES.get(normalize(s)) for s in match.groups()]
    selected = ALIASES.get(normalize(market.outcome))
    if None in sides or sides[0] == sides[1] or selected not in sides:
        raise ValueError("mapping_unknown_or_ambiguous_participant")
    rules = market.resolution_rules
    if not market.end_time:
        raise ValueError("mapping_explicit_market_start_required")
    # One explicitly recognized NFL-source rule template. Unknown variants
    # fail closed; names/timing appearing in unrelated prose do not qualify.
    old_header = re.fullmatch(
        r"In the upcoming NFL football game between "
        + re.escape(match.group(1))
        + r" and "
        + re.escape(match.group(2))
        + r", scheduled for ([A-Z][a-z]+ \d{1,2}) at (\d{1,2}:\d{2}[AP]M) ET:",
        rules.splitlines()[0] if rules else "",
    )
    if old_header:
        expected_lines = [
            f'This market will resolve to "{name}" if {name} win the game.' for name in match.groups()
        ] + [
            "Overtime is included if played.",
            "If the game ends in a tie, this market will resolve 50-50.",
            "If the game is postponed, this market will remain open until the game has been completed.",
            "If the game is canceled entirely, with no make-up game, this market will resolve 50-50.",
        ]
        if rules.splitlines()[1:] != expected_lines:
            raise ValueError("mapping_unsupported_resolution_rules")
        # The explicit market UTC timestamp supplies the year; do not guess a
        # missing year from now or select the nearest meeting between these teams.
        year = market.end_time.astimezone(ZoneInfo("America/New_York")).year
        local = datetime.strptime(
            str(year) + " " + old_header.group(1) + " " + old_header.group(2), "%Y %B %d %I:%M%p"
        )
    else:
        raise ValueError("mapping_unsupported_resolution_rules")
    start = local.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(UTC)
    if market.end_time != start:
        raise ValueError("mapping_market_rule_schedule_mismatch")
    if start <= now:
        raise ValueError("mapping_event_already_started")
    candidates = []
    for raw in games:
        game = SportsGame.model_validate(raw.model_dump() if isinstance(raw, SportsGame) else raw)
        if game.league == "NFL" and {game.home_id, game.away_id} == set(sides) and game.starts_at == start:
            candidates.append(game)
    if len(candidates) != 1:
        raise ValueError("mapping_absent_or_ambiguous_schedule_match")
    game = candidates[0]
    if (
        game.status != "scheduled"
        or game.available_at > now
        or not game.includes_overtime
        or (now - game.available_at).total_seconds() > 24 * 3600
    ):
        raise ValueError("mapping_unavailable_stale_or_non_scheduled_game")
    fields = {
        "event_id": market.event_id,
        "market_id": market.market_id,
        "token_id": market.token_id,
        "game_id": game.game_id,
        "league": "NFL",
        "provider": game.provider,
        "selected_team_id": selected,
        "opponent_team_id": next(s for s in sides if s != selected),
        "event_start": start,
        "rules_sha256": hashlib.sha256(rules.encode()).hexdigest(),
        "artifact_sha256": game.artifact_sha256,
    }
    return SportsMapping(**fields, mapping_sha256=digest({**fields, "event_start": start.isoformat()}))
