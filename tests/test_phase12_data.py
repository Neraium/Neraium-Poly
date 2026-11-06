"""Controlled event evidence; fixtures never count as authentic historical records."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from neraium_poly.research.contracts import ResearchContext, ResearchEvent, ResearchPrice
from neraium_poly.research.phase12 import dataset as module
from neraium_poly.research.phase12.categories import acquire_weather_context, run_categories

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def controlled(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    qualification = tmp_path / "qualified"
    qualification.mkdir()
    condition = "0x" + "a" * 64
    raw = {
        "id": "m",
        "conditionId": condition,
        "clobTokenIds": ["t1", "t2"],
        "outcomes": ["Yes", "No"],
        "endDate": (NOW + timedelta(hours=12)).isoformat(),
    }
    rawbytes = json.dumps(raw).encode()
    (source / "raw.json").write_bytes(rawbytes)
    (source / "bundle.json").write_text("{}")
    event = ResearchEvent(
        id="controlled-event",
        timestamp=NOW,
        available_at=NOW + timedelta(days=1),
        source="https://gamma-api.polymarket.com",
        market_id="m",
        event_id="e",
        token_id="t1",
        question="CONTROLLED fixture?",
        category="Weather",
        created_at=NOW,
        closed_at=NOW + timedelta(hours=12),
        resolution_rules="CONTROLLED exact rule",
        resolution_source="https://controlled.invalid",
        outcome=1,
        outcome_verified=True,
        raw_sha256=hashlib.sha256(rawbytes).hexdigest(),
        raw_ref="raw.json#m",
    )
    price = ResearchPrice(
        timestamp=NOW + timedelta(hours=1),
        available_at=event.available_at,
        source="https://clob.polymarket.com",
        event_id="e",
        market_id="m",
        token_id="t1",
        probability=0.4,
        raw_sha256="b" * 64,
        raw_ref="controlled-price",
    )
    ctx = ResearchContext(
        timestamp=NOW + timedelta(minutes=1),
        available_at=event.available_at,
        source="https://aviationweather.gov/api/data/metar",
        event_id="e",
        kind="observed_temperature",
        value=4,
        reference="controlled-context",
        independent=True,
        raw_sha256="c" * 64,
    )
    q = {
        "event_id": "e",
        "market_id": "m",
        "source_record_id": event.id,
        "source_record_sha256": module.digest(event.model_dump(mode="json")),
        "resolution_rules_sha256": hashlib.sha256(event.resolution_rules.encode()).hexdigest(),
        "dependency_group_proposal": "parent:e",
        "deficiencies": ["controlled_missing_PIT"],
        "chain_payout_matches_selected_outcome": True,
    }
    encoded = (json.dumps(q) + "\n").encode()
    (qualification / "events.jsonl").write_bytes(encoded)
    (qualification / "manifest.json").write_text(
        json.dumps(
            {
                "events_sha256": hashlib.sha256(encoded).hexdigest(),
                "source_bundle_sha256": hashlib.sha256((source / "bundle.json").read_bytes()).hexdigest(),
                "rpc_proofs_sha256": "d" * 64,
            }
        )
    )
    proof = {
        "settlement_at": (NOW + timedelta(hours=12)).isoformat(),
        "available_at": (NOW + timedelta(days=1, hours=1)).isoformat(),
        "payouts": [1, 0],
        "condition_id": condition,
        "proof_status": "controlled_fixture",
    }
    monkeypatch.setattr(
        module,
        "load_bundle",
        lambda path: SimpleNamespace(events=[event], prices=[price], books=[], context=[ctx]),
    )
    monkeypatch.setattr(module, "_load_proofs", lambda path: ({condition: proof}, "d" * 64))
    return source, qualification, tmp_path / "output"


def test_dataset_preserves_point_in_time_gaps_and_verified_token_mapping(controlled):
    source, q, out = controlled
    manifest = module.build_dataset(source, q, out, chain_dir="controlled")
    loaded = module.load_dataset(out)
    assert manifest["qualification_funnel"]["corroborated_finalized_outcome_groups"] == 1
    assert manifest["qualification_funnel"]["resolved_events_with_predecision_available_price"] == 0
    assert manifest["qualification_funnel"]["fully_qualified_training_events"] == 0
    assert manifest["qualification_funnel"]["actual_historical_book_rows"] == 0
    final = loaded["outcomes"][0]
    assert final.available_at > final.settled_at
    assert final.proof_sha256 == module.digest(final.verification)
    assert final.payout == 1 and final.token_id == "t1"
    assert loaded["events"][0].independence_reviewed is False
    assert any(e.kind == "external_context" and e.independent_of_market_price for e in loaded["evidence"])


def test_event_source_qualification_mismatch_fails(controlled):
    source, q, out = controlled
    path = q / "events.jsonl"
    path.write_text("tampered")
    with pytest.raises(ValueError, match="checksum"):
        module.build_dataset(source, q, out, chain_dir="controlled")
    assert not out.exists()


def test_no_overwrite_or_historical_backfill(controlled):
    source, q, out = controlled
    with pytest.raises(ValueError, match="backfill"):
        module.build_dataset(source, q, out, chain_dir="controlled", live_frame={"controlled": True})
    assert not out.exists()
    module.build_dataset(source, q, out, chain_dir="controlled")
    with pytest.raises(ValueError, match="new event dataset"):
        module.build_dataset(source, q, out, chain_dir="controlled")


def test_file_corruption_and_manifest_authority_reject(controlled):
    source, q, out = controlled
    module.build_dataset(source, q, out, chain_dir="controlled")
    file = out / "manifest.json"
    manifest = json.loads(file.read_text())
    manifest["automatic_promotion"] = True
    file.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="schema/authority"):
        module.load_dataset(out)
    manifest["automatic_promotion"] = False
    file.write_text(json.dumps(manifest))
    (out / "evidence.jsonl").write_text("tampered")
    with pytest.raises(ValueError, match="checksum"):
        module.load_dataset(out)


def test_evidence_payload_digest_verified_beyond_file_hash(controlled):
    source, q, out = controlled
    module.build_dataset(source, q, out, chain_dir="controlled")
    file = out / "evidence.jsonl"
    rows = [json.loads(x) for x in file.read_text().splitlines()]
    rows[0]["payload"]["forged"] = True
    file.write_text("".join(json.dumps(r) + "\n" for r in rows))
    m = json.loads((out / "manifest.json").read_text())
    m["files"]["evidence.jsonl"] = hashlib.sha256(file.read_bytes()).hexdigest()
    m["dataset_sha256"] = module.digest(m["files"])
    (out / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(ValueError, match="content mismatch"):
        module.load_dataset(out)


def test_categories_are_suitability_not_independent_skill(controlled):
    source, q, out = controlled
    module.build_dataset(source, q, out, chain_dir="controlled")
    r = run_categories(out)
    assert r["selected_categories"] == ["Weather"]
    weather = next(row for row in r["categories"] if row["category"] == "Weather")
    assert weather["independent_external_observations"] == 1
    assert weather["reviewed_independent_events"] == 0 and weather["forecast_skill"] is None
    assert weather["historical_liquidity"] is None
    assert r["automatic_promotion"] is False


def test_weather_acquisition_preserves_source_receipt_and_null_probability(tmp_path):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=[{"icaoId": "EGLC", "obsTime": 1, "temp": 4}])
    )
    with httpx.Client(transport=transport) as client:
        r = acquire_weather_context(tmp_path / "weather", client=client)
    assert r["observations"] == 1 and r["source_observation_times"] == [1]
    assert r["availability_basis"] == "collected_now"
    assert r["probability_estimates"] is None and r["historical_predecision_qualified"] is False
    assert datetime.fromisoformat(r["received_at"]).tzinfo is not None
    with pytest.raises(ValueError, match="new external"):
        acquire_weather_context(tmp_path / "weather")


def test_duplicate_proposition_identity_rejected_even_with_rebound_file_hash(controlled):
    source, q, out = controlled
    module.build_dataset(source, q, out, chain_dir="controlled")
    file = out / "events.jsonl"
    row = json.loads(file.read_text().splitlines()[0])
    duplicate = {**row, "id": "controlled-duplicate-id"}
    file.write_text(json.dumps(row) + "\n" + json.dumps(duplicate) + "\n")
    manifest = json.loads((out / "manifest.json").read_text())
    manifest["files"]["events.jsonl"] = hashlib.sha256(file.read_bytes()).hexdigest()
    manifest["dataset_sha256"] = module.digest(manifest["files"])
    (out / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="duplicate event proposition"):
        module.load_dataset(out)
