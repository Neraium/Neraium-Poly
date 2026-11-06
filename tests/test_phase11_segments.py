"""Controlled research fixtures; never actual profitable opportunities."""

import hashlib
import json
from datetime import UTC, datetime

import httpx
import pytest
from neraium_poly.research.phase11.historical import audit_historical
from neraium_poly.research.phase11.segments import acquire_event_metadata, run_segments
from test_experimental_account import book, market


@pytest.fixture
def frame():
    now = datetime(2026, 11, 6, 12, tzinfo=UTC)
    m, b = market(now), book(now)
    return {
        "id": "controlled-frame",
        "mode": "real_market_data",
        "available_at": now.isoformat(),
        "markets": [m.model_dump(mode="json")],
        "books": [b.model_dump(mode="json")],
    }


def tags(frame, labels):
    m = frame["markets"][0]
    return {
        "records": {
            m["event_id"]: {
                "market_ids": [m["market_id"]],
                "tags": labels,
                "available_at": "2026-11-06T13:00:00Z",
                "source": f"https://gamma-api.polymarket.com/events/{m['event_id']}",
                "raw_sha256": "0" * 64,
            }
        }
    }


def test_official_category_enrichment_is_not_backdated_feature(frame):
    result = run_segments(frame, official_tags=tags(frame, ["Sports", "NBA"]))
    assert result["segments"][0]["segment"] == "Sports"
    row = result["observations"][0]
    assert row["classification_available_at"] > row["receipt_timestamp"]
    assert row["classification_basis"] == "official tag mapping (descriptive)"
    assert result["certification_authority"] is False
    assert row["profitability"] is row["resolution_reliability"] is None
    assert result["segments"][0]["market_volume_usd"] is None


def test_absent_ambiguous_or_wrong_event_membership_stays_unknown(frame):
    assert run_segments(frame)["segments"][0]["segment"] == "Unknown"
    assert (
        run_segments(frame, official_tags=tags(frame, ["Sports", "Politics"]))["segments"][0]["segment"]
        == "Unknown"
    )
    t = tags(frame, ["Sports"])
    next(iter(t["records"].values()))["market_ids"] = ["unrelated"]
    assert run_segments(frame, official_tags=t)["segments"][0]["segment"] == "Unknown"


def test_stale_book_does_not_inflate_liquidity_or_quality(frame):
    frame["books"][0]["timestamp"] = "2026-11-06T11:59:00Z"
    r = run_segments(frame)
    assert r["segments"][0]["fresh_executable_quotes"] == 0
    assert r["segments"][0]["median_displayed_bid_depth_usd"] is None
    assert not r["observations"][0]["healthy_executable_quote"]


def test_missing_rules_and_depth_suppress_static_suitability(frame):
    frame["markets"][0]["resolution_rules"] = ""
    result = run_segments(frame)
    assert result["segments"][0]["static_research_suitable_tokens"] == 0
    assert result["segments"][0]["rules_present"] == 0
    frame["markets"][0]["resolution_rules"] = "controlled"
    frame["books"][0]["asks"] = []
    assert run_segments(frame)["segments"][0]["static_research_suitable_tokens"] == 0


def test_identity_and_synthetic_frame_reject_or_withhold(frame):
    frame["books"][0]["market_id"] = "unrelated"
    assert not run_segments(frame)["observations"][0]["healthy_executable_quote"]
    frame["mode"] = "synthetic"
    with pytest.raises(ValueError, match="real public frame"):
        run_segments(frame)


def test_metadata_acquisition_readonly_bounded_and_hash_bound(tmp_path, frame):
    frame["markets"][0]["event_id"] = "123"
    calls = []

    def handler(request):
        calls.append((request.method, str(request.url)))
        return httpx.Response(
            200,
            json={
                "id": "123",
                "tags": [{"label": "Sports"}],
                "markets": [{"id": frame["markets"][0]["market_id"]}],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = acquire_event_metadata(frame, tmp_path / "capture", max_requests=1, client=client)
    assert calls == [("GET", "https://gamma-api.polymarket.com/events/123")]
    record = result["records"]["123"]
    assert (
        hashlib.sha256((tmp_path / "capture" / record["raw_path"]).read_bytes()).hexdigest()
        == record["raw_sha256"]
    )
    assert result["certification_authority"] is False
    with pytest.raises(ValueError, match="new metadata"):
        acquire_event_metadata(frame, tmp_path / "capture")
    with pytest.raises(ValueError, match="bounded"):
        acquire_event_metadata(frame, tmp_path / "other", max_requests=61)


def historical_fixture(tmp_path):
    root = tmp_path / "history"
    root.mkdir()
    row = {
        "event_id": "controlled-event",
        "condition_id": "controlled-condition",
        "official_source_outcome_verified": True,
        "availability_basis": "collected_now",
        "dependency_group_reviewed": False,
        "historical_depth_qualified": False,
        "historical_rules_verified": False,
        "source_available_at": "2026-11-06T12:00:00Z",
        "deficiencies": ["independent_external_context_not_qualified"],
    }
    raw = (json.dumps(row) + "\n").encode()
    (root / "events.jsonl").write_bytes(raw)
    manifest = json.dumps(
        {"events_sha256": hashlib.sha256(raw).hexdigest(), "events_bytes": len(raw)}
    ).encode()
    (root / "manifest.json").write_bytes(manifest)
    (root / "report.json").write_text(
        json.dumps(
            {
                "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
                "required_training_events": 100,
                "required_heldout_events": 100,
            }
        )
    )
    return root


def test_historical_audit_does_not_certify_unqualified_or_current_labels(tmp_path):
    r = audit_historical(historical_fixture(tmp_path))
    assert r["events"] == r["official_verified_outcome_groups"] == 1
    assert r["chain_corroborated_exact_settlement_groups"] == 0
    assert r["certifiable_training_events"] == r["certifiable_heldout_events"] == 0
    assert r["deficiency_counts"]["historical_availability_not_certified"] == 1
    assert r["owner_approval_required"] and not r["strategy_promotion_authority"]


def test_historical_dataset_tampering_fails_closed(tmp_path):
    root = historical_fixture(tmp_path)
    with (root / "events.jsonl").open("a") as handle:
        handle.write("{}\n")
    with pytest.raises(ValueError, match="integrity"):
        audit_historical(root)


def test_untrusted_official_category_source_is_not_accepted(frame):
    t = tags(frame, ["Sports"])
    record = next(iter(t["records"].values()))
    record["source"] = "https://untrusted.invalid/events/123"
    assert run_segments(frame, official_tags=t)["segments"][0]["segment"] == "Unknown"


def test_historical_acquisition_forbids_transaction_methods(tmp_path):
    dataset = historical_fixture(tmp_path)
    acquisition = tmp_path / "acquisition"
    acquisition.mkdir()
    raw = json.dumps({"jsonrpc": "2.0", "id": 1, "result": None}).encode()
    (acquisition / "raw.json").write_bytes(raw)
    (acquisition / "manifest.json").write_text(
        json.dumps(
            {
                "responses": [
                    {
                        "request": {"method": "eth_sendRawTransaction", "id": 1},
                        "response_path": "raw.json",
                        "bytes": len(raw),
                        "response_sha256": hashlib.sha256(raw).hexdigest(),
                    }
                ]
            }
        )
    )
    with pytest.raises(ValueError, match="non-read-only"):
        audit_historical(dataset, acquisition_dirs=[acquisition])
