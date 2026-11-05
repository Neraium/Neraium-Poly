from datetime import UTC, datetime

import pytest
from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, PriceLevel


@pytest.fixture
def now():
    return datetime(2026, 11, 5, 12, tzinfo=UTC)


@pytest.fixture
def market(now):
    return MarketSnapshot(
        id="market-record",
        timestamp=now,
        available_at=now,
        source="fixture",
        market_id="m1",
        token_id="t1",
        event_id="e1",
        question="Fixture outcome?",
        probability=0.4,
        status="active",
        resolution_rules="YES if independently verified fixture event occurs",
        resolution_source="fixture-oracle",
    )


@pytest.fixture
def book(now):
    return OrderBookSnapshot(
        id="book-record",
        timestamp=now,
        available_at=now,
        source="fixture",
        market_id="m1",
        token_id="t1",
        bids=(PriceLevel(price=0.39, size=100),),
        asks=(PriceLevel(price=0.4, size=100),),
        sequence=1,
    )
