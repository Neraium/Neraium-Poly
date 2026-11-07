"""Source-bound displayed-depth economics, never actual or guaranteed fills."""

from datetime import UTC, datetime, timedelta
from math import isfinite
from urllib.parse import urlparse

from neraium_poly.research.phase14.relationships import digest

BOOK_SOURCES = {"https://clob.polymarket.com", "wss://ws-subscriptions-clob.polymarket.com/ws/market"}


def _number(value, *, low=0, high=float("inf")):
    return type(value) in (int, float) and isfinite(value) and low <= value <= high


def _time(value):
    at = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if at.tzinfo is None:
        raise ValueError("aware_timestamp_required")
    return at.astimezone(UTC)


def _identity(value):
    return isinstance(value, str) and 0 < len(value) <= 256


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _point(point):
    if not isinstance(point, dict):
        raise TypeError("point_mapping_required")
    for key in ("id", "book_id", "market_id", "token_id", "event_id", "source_frame_id"):
        if not _identity(point.get(key)):
            raise ValueError("point_identity_required:"+key)
    for key in ("book_sha256", "metadata_sha256", "rules_sha256", "fee_evidence_sha256"):
        if not _sha(point.get(key)):
            raise ValueError("source_provenance_required:"+key)
    source, receipt, observed = (_time(point.get(k)) for k in ("source_at", "available_at", "observed_at"))
    if not source <= receipt <= observed:
        raise ValueError("source_receipt_cutoff_order_invalid")
    if (observed-source).total_seconds() > 15 or (observed-receipt).total_seconds() > 15:
        raise ValueError("source_or_receipt_stale")
    if (point.get("source") not in BOOK_SOURCES or point.get("depth_scope") != "top3_observed"
        or point.get("participation") != .25 or point.get("execution_evidence_complete") is not True
        or point.get("missing_fields")):
        raise ValueError("qualified_source_depth_context_required")
    if not _number(point.get("min_order_size"), low=1e-12) or not _number(point.get("tick_size"), low=1e-12, high=1):
        raise ValueError("minimum_lot_and_tick_required")
    for side, descending in (("bids", True), ("asks", False)):
        rows = point.get(side)
        if not isinstance(rows, list) or not 1 <= len(rows) <= 3:
            raise ValueError("bounded_top3_levels_required")
        if any(not isinstance(r, dict) or not _number(r.get("price"), high=1)
               or not _number(r.get("size"), low=1e-12) for r in rows):
            raise ValueError("invalid_depth_level")
        prices = [r["price"] for r in rows]
        tick = point["tick_size"]
        if any(abs(price/tick-round(price/tick)) > 1e-7 for price in prices):
            raise ValueError("price_off_tick_grid")
        if len(set(prices)) != len(prices) or sorted(prices, reverse=descending) != prices:
            raise ValueError("unordered_or_duplicate_depth_level")
    bid, ask = point["bids"][0]["price"], point["asks"][0]["price"]
    if (ask <= 0 or bid > ask or ask-bid > .05+1e-12
        or point.get("bid") != bid or point.get("ask") != ask):
        raise ValueError("invalid_spread_or_top_price_binding")
    fee = point.get("fee_observation")
    if (not isinstance(fee, dict) or point.get("fee_observation_valid") is not True
        or digest(fee) != point["fee_evidence_sha256"]):
        raise ValueError("qualified_fee_provenance_required")
    url = urlparse(fee.get("source", ""))
    rate = fee.get("fee_rate", fee.get("effective_notional_bound"))
    at = _time(fee.get("observed_at", fee.get("available_at", fee.get("timestamp"))))
    if any(_time(fee[key]) > observed for key in ("observed_at", "available_at", "timestamp") if key in fee):
        raise ValueError("future_fee_availability")
    if (url.scheme != "https" or url.hostname != "clob.polymarket.com" or url.port not in (None, 443)
        or not _number(rate, high=1) or point.get("fee_rate") != rate
        or not 0 <= (observed-at).total_seconds() <= 300
        or not isinstance(fee.get("reference"), str) or not 1 <= len(fee["reference"]) <= 2048):
        raise ValueError("fee_source_rate_or_cutoff_invalid")
    return source, receipt, observed, float(rate)


def _walk(rows, quantity):
    remaining, cost, levels = quantity, 0., []
    for row in rows:
        take = min(remaining, row["size"]*.25)
        if take > 0:
            cost += take*row["price"]
            levels.append({"price": row["price"], "quantity": take, "observed_size": row["size"]})
            remaining -= take
    return {"supported_quantity": quantity-remaining, "unsupported_quantity": max(0., remaining),
            "vwap": cost/quantity if remaining <= 1e-9 else None, "levels": levels,
            "total_observed_participating_capacity": sum(r["size"]*.25 for r in rows)}


def evaluate_roundtrip(decision, label, *, quantity=5, fee_multiplier=1,
                       slippage_per_leg=.01, latency_seconds=.1):
    """Retrospective 60-second depth-mark economics with explicit missingness.

    Both fee observations and future exit quotes are used ONLY to measure a
    matured outcome, never to select a historical entry. Entry quote is available
    at decision; its survival after submission latency cannot be established by
    this two-point API. Therefore even supported economics are not execution
    certification, a future liquidity guarantee or simulated account P/L.
    """
    result = {"schema_version": "phase17-depth-economics-v1", "status": "unexecutable",
              "depth_supported": False, "full_quantity_supported": False, "reasons": [],
              "gross_per_share": None, "net_per_share": None, "fees_per_share": None,
              "slippage_per_share": None, "gross_total": None, "net_total": None,
              "quantity": quantity, "execution_certified": False, "trading_authority": False,
              "certification_authority": False, "actual_fill": False, "account_pnl": None,
              "entry_post_latency_verified": False,
              "semantics": "retrospective participating displayed-depth quote marks, not broker fills or account P/L"}
    try:
        if (not _number(quantity, low=1e-9, high=1000000) or not _number(fee_multiplier, high=10)
            or not _number(slippage_per_leg, high=1) or not _number(latency_seconds, high=30)):
            raise ValueError("finite_bounded_execution_assumptions_required")
        ds, _dr, decision_at, entry_fee = _point(decision)
        ls, _lr, label_at, exit_fee = _point(label)
        for key in ("token_id", "market_id", "event_id", "rules_sha256"):
            if decision[key] != label[key]:
                raise ValueError("decision_label_identity_mismatch:"+key)
        if decision["id"] == label["id"] or decision["book_id"] == label["book_id"]:
            raise ValueError("duplicate_quote_cannot_label_itself")
        target = decision_at+timedelta(seconds=60)
        if not target+timedelta(seconds=latency_seconds) <= ls <= target+timedelta(seconds=30):
            raise ValueError("exit_source_not_in_post_latency_60_to90_second_window")
        if ls <= ds or label_at < target or quantity < max(decision["min_order_size"], label["min_order_size"])-1e-9:
            raise ValueError("causal_time_or_minimum_lot_invalid")
        entry, exit_ = _walk(decision["asks"], quantity), _walk(label["bids"], quantity)
        result.update(entry_depth=entry, exit_depth=exit_)
        if entry["vwap"] is None or exit_["vwap"] is None:
            raise ValueError("insufficient_participating_entry_or_exit_depth")
        entry_price, exit_price = entry["vwap"], exit_["vwap"]
        gross = exit_price-entry_price
        fees = fee_multiplier*(entry_price*entry_fee+exit_price*exit_fee)
        slippage = 2*slippage_per_leg
        net = gross-fees-slippage
        principal = quantity*entry_price
        result.update(status="depth_supported_research", depth_supported=True, full_quantity_supported=True,
            gross_per_share=gross, net_per_share=net, fees_per_share=fees, slippage_per_share=slippage,
            gross_total=quantity*gross, net_total=quantity*net, entry_price=entry_price, exit_price=exit_price,
            entry_principal=principal, entry_cash_with_modeled_fees=principal*(1+fee_multiplier*entry_fee),
            standard_notional_eligible=2-1e-9 <= principal <= 5+1e-9,
            best_limit_capacity_shares=decision["asks"][0]["size"]*.25,
            best_limit_full_quantity_supported=quantity <= decision["asks"][0]["size"]*.25+1e-9,
            spread_at_decision=decision["ask"]-decision["bid"],
            entry_sweep_impact=entry_price-decision["ask"], exit_sweep_impact=label["bid"]-exit_price,
            adverse_bid_move=decision["bid"]-label["bid"],
            target_at=target.isoformat(), actual_horizon_seconds=(ls-decision_at).total_seconds(),
            assumptions={"participation": .25, "depth_levels": 3, "fee_multiplier": fee_multiplier,
                         "slippage_per_leg": slippage_per_leg, "latency_seconds": latency_seconds,
                         "conservative_base_or_stricter": fee_multiplier >= 1 and slippage_per_leg >= .01 and latency_seconds >= .1},
            provenance={"decision_point_id": decision["id"], "label_point_id": label["id"],
                        "decision_point_sha256": digest(decision), "label_point_sha256": digest(label),
                        "event_id": decision["event_id"], "market_id": decision["market_id"],
                        "token_id": decision["token_id"], "rules_sha256": decision["rules_sha256"],
                        "decision_book_sha256": decision["book_sha256"], "label_book_sha256": label["book_sha256"],
                        "decision_fee_sha256": decision["fee_evidence_sha256"], "label_fee_sha256": label["fee_evidence_sha256"],
                        "decision_at": decision_at.isoformat(), "exit_observed_at": label_at.isoformat()},
            limitations=["Entry quote survival after configured latency is unverified by two-point depth marks",
                         "A hypothetical multi-level sweep cannot prove the existing best-limit broker would fill",
                         "Displayed liquidity is not queue priority, future executable depth or an actual exchange fill",
                         "Caller must independently replay source hashes; structural checks alone do not authenticate data",
                         "Future exit fee/depth are retrospective labels and cannot select historical trades"])
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        result["reasons"] = [str(error)[:160]]
    return result
