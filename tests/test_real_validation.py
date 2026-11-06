"""Controlled assertions of gate behavior, never actual real-market evidence."""

import json
import subprocess
from datetime import timedelta
from hashlib import sha256

import pytest
from neraium_poly.contracts import MarketRelationship, OrderBookSnapshot, PriceLevel
from neraium_poly.owner import canonical
from neraium_poly.validation import ValidationStore


def documents(tmp_path, now, mutate=None):
    cutoff = now - timedelta(days=2)
    rows = []
    for i in range(400):
        partition = "train" if i < 200 else "heldout"
        at = (
            cutoff - timedelta(days=2) + timedelta(minutes=i)
            if i < 200
            else cutoff + timedelta(hours=1, minutes=i - 200)
        )
        book = OrderBookSnapshot(
            id=f"book-{i}",
            timestamp=at,
            available_at=at,
            source="https://clob.polymarket.com",
            market_id=f"m-{i}",
            token_id=f"t-{i}",
            bids=(PriceLevel(price=0.39, size=100),),
            asks=(PriceLevel(price=0.4, size=100),),
        )
        rows.append(
            {
                "id": f"forecast-{i}",
                "timestamp": at.isoformat(),
                "available_at": at.isoformat(),
                "source": "https://clob.polymarket.com",
                "market_id": f"m-{i}",
                "event_id": f"e-{i}",
                "probability": 0.4,
                "outcome": int(i % 20 < 17),
                "label_available_at": (at + timedelta(minutes=1)).isoformat(),
                "executable_price": 0.4,
                "executable_quantity": 100,
                "protocol_fee_rate": 0.02,
                "partition": partition,
                "book": book.model_dump(mode="json"),
                "independent_evidence_source": "https://evidence.example.org",
                "independent_evidence_ref": f"sha256:independent-record-{i}",
                "independent_evidence_available_at": at.isoformat(),
                "settlement_source": "https://gamma-api.polymarket.com",
                "settlement_ref": f"sha256:verified-resolution-{i}",
                "settlement_verified": True,
            }
        )
    relationship = MarketRelationship(
        id="reviewed-statistical",
        timestamp=cutoff,
        available_at=cutoff,
        source="https://research.example.org",
        market_ids=("live-a", "live-b"),
        kind="statistical",
        confidence=0.9,
    )
    manifest = {
        "data_origin": "real",
        "dataset_sha256": "pending",
        "train_cutoff": cutoff.isoformat(),
        "expires_at": (now + timedelta(days=2)).isoformat(),
        "provenance_reviewed": True,
        "provenance_reviewer": "controlled-test-reviewer",
        "collection_description": "Controlled assertions; this file is not empirical research.",
        "independent_signal_description": "Externally reviewed independent event evidence in point-in-time archive.",
        "label_method": "verified_final_resolution",
        "relationships": [relationship.model_dump(mode="json")],
        "relationship_tokens": {"live-a": "live-a-yes", "live-b": "live-b-yes"},
    }
    if mutate:
        mutate(rows, manifest)
    data = json.dumps(rows).encode()
    if manifest["dataset_sha256"] == "pending":
        manifest["dataset_sha256"] = sha256(data).hexdigest()
    dataset = tmp_path / "observations.json"
    dataset.write_bytes(data)
    meta = tmp_path / "manifest.json"
    meta.write_text(json.dumps(manifest))
    return dataset, meta


def owner_signing_fixture(store, report, now, directory):
    """Ephemeral TEST-ONLY approval keys; never provision production trust."""
    directory.mkdir(parents=True, exist_ok=True)
    private = directory / "test-owner-private.pem"
    public = directory / "test-owner-public.pem"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private)], check=True, capture_output=True
    )
    subprocess.run(
        ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
        check=True,
        capture_output=True,
    )
    store.owner_public_key = public
    request = store.prepare_owner_request(report.id, now)
    message = directory / "request.json"
    message.write_bytes(canonical(request))
    signature = directory / "owner.sig"
    subprocess.run(
        [
            "openssl",
            "pkeyutl",
            "-sign",
            "-inkey",
            str(private),
            "-rawin",
            "-in",
            str(message),
            "-out",
            str(signature),
        ],
        check=True,
        capture_output=True,
    )
    return public, {"owner_request_id": request["request_id"], "owner_signature": signature.read_bytes()}


def test_no_implicit_approval_and_durable_reconstruction(tmp_path, now):
    dataset, manifest = documents(tmp_path, now)
    path = tmp_path / "validation.sqlite"
    store = ValidationStore(path)
    assert store.load_active(now) is None
    assert not store.status(now)["active"]
    report = store.validate(dataset, manifest, now)
    assert report.passed, report.reasons
    assert report.train_events == report.heldout_events == 200
    assert report.brier_improvement_lower95 > 0.005
    assert store.load_active(now) is None
    public, owner = owner_signing_fixture(store, report, now, tmp_path / "owner")
    store.approve(report.id, "separate-explicit-reviewer", now, **owner)
    first = store.load_active(now)
    assert first and first.registry.active_id == first.model_id
    store.close()
    restored = ValidationStore(path, owner_public_key=public)
    again = restored.load_active(now + timedelta(minutes=1))
    assert again and first.model_id == again.model_id
    assert again.registry.approvals[again.model_id].available_at == now
    restored.revoke("research-reviewer", now + timedelta(minutes=2), "failed later monitoring review")
    assert restored.load_active(now + timedelta(minutes=3)) is None


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda rows, m: m.update(data_origin="synthetic"), "real_observations_required"),
        (lambda rows, m: m.update(provenance_reviewed=False), "independent_provenance_review_required"),
        (lambda rows, m: m.update(dataset_sha256="wrong"), "dataset_hash_mismatch"),
        (
            lambda rows, m: m.update(independent_signal_description=""),
            "independent_signal_and_collection_description_required",
        ),
        (lambda rows, m: m.update(label_method="market-price-proxy"), "verified_resolution_labels_required"),
        (
            lambda rows, m: rows[0].update(independent_evidence_source="https://clob.polymarket.com/book"),
            "market_prices_are_not_independent_evidence",
        ),
        (lambda rows, m: rows[0].update(source="synthetic-fixture"), "untrusted_or_synthetic_provenance"),
        (
            lambda rows, m: rows[0].update(settlement_verified=False),
            "missing_evidence_or_verified_settlement",
        ),
        (lambda rows, m: rows[200].update(event_id=rows[0]["event_id"]), "duplicate_or_correlated_events"),
        (
            lambda rows, m: rows[0].update(label_available_at=(now_placeholder()).isoformat()),
            "training_or_holdout_leakage",
        ),
        (lambda rows, m: rows[200].update(executable_quantity=1000), "unsupported_executable_depth"),
        (lambda rows, m: rows[200].update(protocol_fee_rate=None), "missing_executable_cost_inputs"),
    ],
)
def test_rejections(tmp_path, now, mutation, reason):
    dataset, manifest = documents(tmp_path, now, mutation)
    store = ValidationStore(":memory:")
    report = store.validate(dataset, manifest, now)
    assert not report.passed and reason in report.reasons, report.reasons
    with pytest.raises(ValueError, match="not passed"):
        store.approve(report.id, "reviewer", now)
    assert store.load_active(now) is None


def now_placeholder():
    from datetime import UTC, datetime

    return datetime(2026, 11, 5, 11, tzinfo=UTC)


def test_future_independent_context_and_stale_books(tmp_path, now):
    def mutate(rows, m):
        rows[201]["independent_evidence_available_at"] = now.isoformat()
        rows[202]["book"]["timestamp"] = (now - timedelta(days=10)).isoformat()

    dataset, manifest = documents(tmp_path, now, mutate)
    report = ValidationStore(":memory:").validate(dataset, manifest, now)
    assert "unavailable_independent_evidence_or_label" in report.reasons
    assert "stale_or_future_validation_book" in report.reasons


def test_uncalibrated_holdout_and_no_demonstrated_edge(tmp_path, now):
    def mutate(rows, m):
        for row in rows[200:]:
            row["probability"] = 0.9

    dataset, manifest = documents(tmp_path, now, mutate)
    report = ValidationStore(":memory:").validate(dataset, manifest, now)
    assert not report.passed
    assert "uncalibrated_or_uncertain_heldout_bin" in report.reasons
    assert "cost_adjusted_heldout_edge_not_supported" in report.reasons


def test_heldout_calibration_and_improvement_required(tmp_path, now):
    def mutate(rows, m):
        for i, row in enumerate(rows[200:]):
            row["outcome"] = int(i % 20 < 8)

    dataset, manifest = documents(tmp_path, now, mutate)
    report = ValidationStore(":memory:").validate(dataset, manifest, now)
    assert not report.passed
    assert "heldout_calibration_failed" in report.reasons
    assert "heldout_improvement_not_supported" in report.reasons


def test_missing_sample_counts(tmp_path, now):
    dataset, manifest = documents(tmp_path, now, lambda rows, m: rows.__delitem__(slice(50, 350)))
    report = ValidationStore(":memory:").validate(dataset, manifest, now)
    assert "insufficient_training_events" in report.reasons
    assert "insufficient_heldout_events" in report.reasons


def test_approval_expiry_and_integrity_fail_closed(tmp_path, now):
    dataset, manifest = documents(tmp_path, now)
    store = ValidationStore(tmp_path / "valid.sqlite")
    report = store.validate(dataset, manifest, now)
    with pytest.raises(ValueError, match="actor"):
        store.approve(report.id, "", now)
    _, owner = owner_signing_fixture(store, report, now, tmp_path / "owner")
    store.approve(report.id, "reviewer", now, **owner)
    assert store.load_active(now + timedelta(days=3)) is None
    assert not store.status(now + timedelta(days=3))["active"]
    store.db.execute("UPDATE validation_reports SET dataset=? WHERE id=?", (b"[]", report.id))
    assert store.load_active(now) is None
    assert store.status(now)["blockers"] == ["approval_integrity_expiry_or_storage_failure"]


def test_unreviewed_logical_scope_rejected(tmp_path, now):
    def mutate(rows, m):
        m["relationships"][0]["kind"] = "exhaustive"

    dataset, manifest = documents(tmp_path, now, mutate)
    report = ValidationStore(":memory:").validate(dataset, manifest, now)
    assert "unsupported_settlement_assumption" in report.reasons


def test_malformed_and_unknown_inputs_fail_closed(tmp_path, now):
    data = tmp_path / "data.json"
    data.write_text("not-json")
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    report = ValidationStore(":memory:").validate(data, manifest, now)
    assert not report.passed and "malformed_dataset_or_manifest" in report.reasons


def test_missing_review_audit_cannot_activate(tmp_path, now):
    dataset, manifest = documents(tmp_path, now)
    store = ValidationStore(":memory:")
    report = store.validate(dataset, manifest, now)
    store.db.execute(
        "INSERT INTO active_strategy VALUES(1,?,?,?)", (report.id, now.isoformat(), "invented-review")
    )
    assert store.load_active(now) is None
    assert store.status(now)["blockers"] == ["approval_integrity_expiry_or_storage_failure"]


def test_passing_report_and_actor_cannot_self_approve(tmp_path, now):
    dataset, manifest = documents(tmp_path, now)
    store = ValidationStore(tmp_path / "approval.sqlite")
    report = store.validate(dataset, manifest, now)
    assert report.passed
    with pytest.raises(ValueError, match="owner approval"):
        store.approve(report.id, "autonomous-agent", now)
    assert store.load_active(now) is None
    assert store.status(now)["owner_approval_required"]
    public, owner = owner_signing_fixture(store, report, now, tmp_path / "test-only-owner")
    wrong = bytes([owner["owner_signature"][0] ^ 1]) + owner["owner_signature"][1:]
    with pytest.raises(ValueError, match="signature"):
        store.approve(report.id, "operator", now, **{**owner, "owner_signature": wrong})
    store.owner_public_key = None
    with pytest.raises(ValueError, match="trusted"):
        store.approve(report.id, "operator", now, **owner)
    store.owner_public_key = public
    store.approve(report.id, "operator", now, **owner)
    assert store.load_active(now)
    store.owner_public_key = None
    assert store.load_active(now) is None


def test_owner_request_integrity_and_context_reject(tmp_path, now):
    dataset, manifest = documents(tmp_path, now)
    store = ValidationStore(tmp_path / "approval.sqlite")
    report = store.validate(dataset, manifest, now)
    _, owner = owner_signing_fixture(store, report, now, tmp_path / "owner")
    store.db.execute(
        "UPDATE owner_requests SET payload=? WHERE request_id=?", (b"{}", owner["owner_request_id"])
    )
    with pytest.raises(ValueError, match="changed"):
        store.approve(report.id, "operator", now, **owner)
    assert store.load_active(now) is None
