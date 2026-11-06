"""Bounded public operations; unknown fees and resolution semantics fail closed.

All outbound requests inherit the read-only base adapter. No wallet, signer or
order endpoint is imported. Statistical edges are hypotheses from shared event
membership, never verified logical constraints or probability forecasts.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from itertools import combinations

import httpx
from pydantic import Field

from neraium_poly.contracts import MarketRelationship, MarketSnapshot, Record
from neraium_poly.strategy import ProtocolFeeModel

from .polymarket import CLOB, DATA, GAMMA, PolymarketAdapter, normalize_market, stable_id, timestamp


@dataclass(frozen=True)
class DiscoveryBatch:
    markets: tuple[MarketSnapshot, ...]
    scanned_count: int
    truncated: bool
    errors: tuple[str, ...]
    next_offset: int


class SettlementObservation(Record):
    market_id: str
    event_id: str
    token_id: str
    condition_id: str
    payout: float = Field(ge=0, le=1)
    resolution_source: str
    resolution_rules: str
    transaction_hash: str
    outcome_index: int = Field(ge=0, le=1)
    reporter: str
    # This flag is intentionally false. The coordinator must bind an explicit
    # external settlement-rule review before posting a simulated settlement.
    rules_reviewed: bool = False


class OperationalPolymarketAdapter(PolymarketAdapter):
    """Pagination rotates between bounded calls instead of always scanning page0."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.discovery_offset = 0
        self.operational_errors: list[str] = []

    async def discover_bounded(
        self, *, max_markets: int = 50, page_size: int = 50, max_pages: int = 4
    ) -> DiscoveryBatch:
        if not 1 <= max_markets <= 500 or not 1 <= page_size <= 500 or not 1 <= max_pages <= 20:
            raise ValueError("bounded discovery policy required")
        records: list[MarketSnapshot] = []
        selected: set[str] = set()
        scanned: set[str] = set()
        errors = []
        complete = False
        offset = self.discovery_offset
        for _ in range(max_pages):
            remaining = max_markets - len(selected)
            limit = min(page_size, remaining)
            raw_rows = await self._get(
                GAMMA,
                "/markets",
                {"active": "true", "closed": "false", "limit": limit, "offset": offset},
            )
            if not isinstance(raw_rows, list):
                raise TypeError("invalid Gamma discovery page")
            offset += len(raw_rows)
            for raw in raw_rows:
                if not isinstance(raw, dict):
                    errors.append("invalid_market_row")
                    continue
                raw_id = str(raw.get("id", ""))
                if raw_id:
                    scanned.add(raw_id)
                if raw_id in selected:
                    continue
                try:
                    normalized = normalize_market(raw, self.clock())
                    if any(m.status != "active" for m in normalized):
                        raise ValueError("nonactive market in active discovery")
                except (ValueError, TypeError, KeyError) as exc:
                    errors.append(f"market {raw_id or '?'}: {type(exc).__name__}")
                    continue
                selected.add(raw_id)
                records.extend(normalized)
            if len(raw_rows) < limit:
                offset = 0
                complete = not errors
                break
            if len(selected) >= max_markets:
                break
        self.discovery_offset = offset
        self.discovery_complete = complete
        self.errors = list(errors)
        return DiscoveryBatch(tuple(records), len(scanned), not complete, tuple(errors), offset)

    async def fee_model(self, token_id: str) -> ProtocolFeeModel | None:
        """Read current curve parameters; legacy base_fee is not its coefficient.

        CLOB's documented curve details ``fd.r`` are decimal rate, ``fd.e``
        exponent, and ``fd.to`` taker-only. Only exponent1 is implemented by the
        existing ProtocolFeeModel. The base-fee BPS endpoint can disagree with
        the curve coefficient and is therefore never substituted or guessed.
        Callers must TTL-cache only explicitly known observations.
        """
        if not token_id:
            return None
        try:
            parent = await self._get(CLOB, f"/markets-by-token/{token_id}")
            if token_id not in {str(parent["primary_token_id"]), str(parent["secondary_token_id"])}:
                return None
            condition = parent["condition_id"]
            if not isinstance(condition, str) or not condition:
                return None
            details = await self._get(CLOB, f"/clob-markets/{condition}")
            if details.get("c", condition) != condition:
                return None
            tokens = details.get("t", [])
            if token_id not in {str(t.get("t")) for t in tokens if isinstance(t, dict)}:
                return None
            fee = details["fd"]
            if fee.get("to") is not True or isinstance(fee.get("r"), bool):
                return None
            rate = Decimal(str(fee["r"]))
            exponent = Decimal(str(fee["e"]))
            if not rate.is_finite() or not exponent.is_finite() or not 0 <= rate <= 1:
                return None
            if exponent != 1:
                return None
            return ProtocolFeeModel(protocol_rate=float(rate))
        except (httpx.HTTPError, KeyError, TypeError, ValueError, InvalidOperation):
            self.operational_errors.append("unknown_fee_curve")
            self.operational_errors = self.operational_errors[-100:]
            return None

    async def settlement(self, market: MarketSnapshot) -> SettlementObservation | None:
        """Only final, undisputed, identity/rule-matched binary payouts qualify.

        Closed flags, terminal prices and estimated settlement times never prove
        resolution. This observation still requires separate coordinator review
        before a paper ledger settlement is authorized.
        """
        try:
            raw = await self._get(GAMMA, f"/markets/{market.market_id}")
            records = normalize_market(raw, self.clock())
            matching = [r for r in records if r.token_id == market.token_id]
            if len(matching) != 1:
                return None
            current = matching[0]
            if (
                current.market_id != market.market_id
                or current.event_id != market.event_id
                or current.outcome != market.outcome
                or not current.resolution_rules
                or not current.resolution_source
                or current.resolution_rules != market.resolution_rules
                or current.resolution_source != market.resolution_source
                or current.status != "resolved"
                or raw.get("closed") is not True
            ):
                return None
            parent = await self._get(CLOB, f"/markets-by-token/{market.token_id}")
            condition = str(raw["conditionId"])
            if parent.get("condition_id") != condition:
                return None
            if market.token_id not in {str(parent["primary_token_id"]), str(parent["secondary_token_id"])}:
                return None
            result = await self._get(DATA, "/v2/resolutions", {"condition": condition})
            rows = result.get("data", [])
            if len(rows) != 1:
                return None
            row = rows[0]
            if (
                row.get("condition_id") != condition
                or row.get("status") != "resolved"
                or row.get("extended_review") is not False
                or row.get("was_disputed") is not False
                or row.get("new_version_q") is not False
                or row.get("was_arbitrated") is True
                or row.get("resolution_source") != "reported"
                or row.get("market_type") != "BINARY"
                or row.get("reporter") not in {"UMA_OO", "CHAINLINK", "EOA"}
                or not row.get("transaction_hash")
                or not row.get("resolved_at")
            ):
                return None
            payouts = row.get("payouts")
            if payouts not in ([1_000_000, 0], [0, 1_000_000]):
                return None
            if any(type(p) is not int for p in payouts):
                return None
            resolved = timestamp(row["resolved_at"])
            last_update = timestamp(row["last_update_timestamp"])
            received = self.clock()
            if resolved > received or last_update > received or last_update < resolved:
                return None
            # Payout array ordering follows the Gamma outcome/token array, not
            # the primary/secondary labels (which may be misleading on legacy
            # markets). Require exactly two tokens and one matching target.
            if len(records) != 2 or len({r.token_id for r in records}) != 2:
                return None
            outcome_index = next(i for i, r in enumerate(records) if r.token_id == market.token_id)
            values = {
                "timestamp": resolved,
                "available_at": received,
                "source": f"{DATA}/v2/resolutions",
                "market_id": market.market_id,
                "event_id": market.event_id,
                "token_id": market.token_id,
                "condition_id": condition,
                "payout": payouts[outcome_index] / 1_000_000,
                "resolution_source": current.resolution_source,
                "resolution_rules": current.resolution_rules,
                "transaction_hash": row["transaction_hash"],
                "outcome_index": outcome_index,
                "reporter": row["reporter"],
                "rules_reviewed": False,
            }
            return SettlementObservation(id=stable_id("settlement", values), **values)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, StopIteration):
            self.operational_errors.append("unverified_settlement")
            self.operational_errors = self.operational_errors[-100:]
            return None


def build_statistical_relationships(
    markets: tuple[MarketSnapshot, ...] | list[MarketSnapshot], now: datetime, *, max_pairs: int = 200
) -> tuple[tuple[MarketRelationship, ...], dict[str, str]]:
    """Create explicit research hypotheses from same-event YES membership.

    ``confidence=.7`` is a conservative *policy prior* for candidate relevance,
    not empirical statistical confidence or estimated outcome probability.
    The temporal engine must independently establish baseline and persistence.
    Stable IDs permit callers to retain the first edge definition across scans;
    callers must not append newly timed redefinitions under the same ID.
    """
    if now.tzinfo is None or not 1 <= max_pairs <= 1000:
        raise ValueError("aware time and bounded pair count required")
    groups = defaultdict(list)
    by_market = defaultdict(list)
    for market in markets:
        if market.available_at <= now and market.status == "active" and market.outcome.casefold() == "yes":
            by_market[(market.exchange, market.market_id)].append(market)
    tokens = {}
    for records in by_market.values():
        token_ids = {m.token_id for m in records}
        if len(token_ids) != 1:
            continue
        selected = max(records, key=lambda m: (m.available_at, m.id))
        groups[(selected.exchange, selected.event_id)].append(selected)
        tokens[selected.market_id] = selected.token_id
    relationships = []
    for (exchange, event), members in sorted(groups.items()):
        for left, right in combinations(sorted(members, key=lambda m: m.market_id), 2):
            material = (exchange, event, left.market_id, right.market_id, left.token_id, right.token_id)
            rid = hashlib.sha256(json.dumps(material).encode()).hexdigest()
            relationships.append(
                MarketRelationship(
                    id=rid,
                    timestamp=now,
                    available_at=now,
                    source=f"{GAMMA}/event-membership-hypothesis/v1",
                    market_ids=(left.market_id, right.market_id),
                    kind="statistical",
                    confidence=0.7,
                    rule_verified=False,
                    rule_description="Same-event YES association hypothesis; no logical pricing constraint inferred",
                )
            )
            if len(relationships) >= max_pairs:
                return tuple(relationships), tokens
    return tuple(relationships), tokens
