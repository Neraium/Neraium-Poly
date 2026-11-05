"""Conservative market data quality and lifecycle state."""

from dataclasses import dataclass
from datetime import datetime

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot


@dataclass(frozen=True)
class DataHealth:
    healthy: bool
    reasons: tuple[str, ...]
    age_seconds: float | None
    spread: float | None


def assess_book(
    book: OrderBookSnapshot | None,
    now: datetime,
    *,
    max_age_seconds: float = 15,
    max_spread: float = 0.10,
    expected_token: str | None = None,
) -> DataHealth:
    if now.tzinfo is None or max_age_seconds < 0 or not 0 <= max_spread <= 1:
        raise ValueError("invalid quality parameters")
    if book is None:
        return DataHealth(False, ("missing_book",), None, None)
    reasons = []
    age = (now - book.timestamp).total_seconds()
    if age < 0 or book.available_at > now:
        reasons.append("future_data")
    if age > max_age_seconds:
        reasons.append("stale_book")
    if not book.complete:
        reasons.append("incomplete_book")
    if expected_token is not None and book.token_id != expected_token:
        reasons.append("wrong_token")
    spread = book.asks[0].price - book.bids[0].price if book.asks and book.bids else None
    if spread is None:
        reasons.append("missing_liquidity")
    elif spread > max_spread:
        reasons.append("large_spread")
    return DataHealth(not reasons, tuple(reasons), age, spread)


class LifecycleTracker:
    """No inferred settlement from closed status; rules/source must be supplied."""

    def __init__(self):
        self.latest: dict[tuple[str, str], MarketSnapshot] = {}

    def observe(self, market: MarketSnapshot) -> tuple[str, str]:
        key = (market.market_id, market.token_id)
        previous = self.latest.get(key)
        if previous and market.available_at < previous.available_at:
            raise ValueError("out-of-order lifecycle observation")
        if previous and previous.status == "resolved" and market.status != "resolved":
            raise ValueError("resolved market cannot reopen without explicit correction")
        self.latest[key] = market
        return previous.status if previous else "unknown", market.status

    def tradable(self, market_id: str, token_id: str) -> bool:
        market = self.latest.get((market_id, token_id))
        return bool(
            market and market.status == "active" and market.resolution_rules and market.resolution_source
        )
