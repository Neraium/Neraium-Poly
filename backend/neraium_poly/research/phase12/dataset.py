"""Canonical event evidence with original availability and reproducible finality proofs."""

import hashlib
import json
import shutil
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from neraium_poly.research.history import load_bundle
from neraium_poly.research.phase12.contracts import CanonicalEvent, EventEvidence, VerifiedEventOutcome
from neraium_poly.research.qualification import _load_proofs, _market
from neraium_poly.research.settlement_evidence import canonical

MAX_BYTES = 512 * 1024 * 1024


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _time(value):
    return datetime.fromisoformat(value) if value else None


def _array(value):
    value = json.loads(value) if isinstance(value, str) else value
    return tuple(str(v) for v in (value or ()))


def build_dataset(source_dir, qualification_dir, output, *, chain_dir=None, live_frame=None):
    """Create a new immutable dataset; no source files or paper accounts are changed.

    Historical chart timestamps remain distinct from their actual download times.
    Final outcomes are produced only from replayed finalized CTF payout proofs,
    with the original token mapping and API payout independently checked.
    """
    source, qualified, output = Path(source_dir), Path(qualification_dir), Path(output)
    if output.exists():
        raise ValueError("new event dataset directory required")
    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output.parent).free < 8 * 1024**3 + MAX_BYTES:
        raise ValueError("event research free-disk floor")
    bundle = load_bundle(source)
    qmanifest = json.loads((qualified / "manifest.json").read_text())
    qbytes = (qualified / "events.jsonl").read_bytes()
    if hashlib.sha256(qbytes).hexdigest() != qmanifest["events_sha256"]:
        raise ValueError("qualification rows checksum mismatch")
    if hashlib.sha256((source / "bundle.json").read_bytes()).hexdigest() != qmanifest["source_bundle_sha256"]:
        raise ValueError("qualification source bundle mismatch")
    qualification = {(r["event_id"], r["market_id"]): r for r in map(json.loads, qbytes.splitlines())}
    proofs, proof_digest = _load_proofs(chain_dir)
    if qmanifest.get("rpc_proofs_sha256") != proof_digest:
        raise ValueError("qualification proof dataset mismatch")
    events, evidence, outcomes = [], [], []
    parent_markets = defaultdict(list)
    by_key = {}

    def add_evidence(original, kind, market_id, *, independent=False, payload=None):
        data = original.model_dump(mode="json")
        value = EventEvidence(
            id=digest(["event-evidence-v1", original.id, kind, market_id]),
            timestamp=original.timestamp,
            available_at=original.available_at,
            source=original.source,
            event_id=original.event_id,
            market_id=market_id,
            kind=kind,
            content_sha256=digest(data if payload is None else payload),
            payload=data if payload is None else payload,
            independent_of_market_price=independent,
        )
        evidence.append(value)
        return value.id

    for event in bundle.events:
        key = (event.event_id, event.market_id)
        if key in by_key:
            raise ValueError("duplicate canonical market proposition")
        q = qualification.get(key)
        original = event.model_dump(mode="json")
        if not q or q["source_record_id"] != event.id or q["source_record_sha256"] != digest(original):
            raise ValueError("qualification does not bind exact original event")
        raw_file = source / event.raw_ref.split("#", 1)[0]
        raw = _market(json.loads(raw_file.read_bytes()), event.market_id)
        tokens = _array(raw.get("positionIds") if raw.get("version") == "v2" else raw.get("clobTokenIds"))
        names = _array(raw.get("outcomes"))
        if event.token_id not in tokens or len(tokens) != len(names):
            raise ValueError("canonical token/outcome mapping unavailable")
        condition = raw["conditionId"].lower()
        rules_hash = hashlib.sha256(event.resolution_rules.encode()).hexdigest()
        if q["resolution_rules_sha256"] != rules_hash:
            raise ValueError("resolution rule digest mismatch")
        ids = [
            add_evidence(event, "metadata", event.market_id),
            add_evidence(
                event,
                "resolution_rules",
                event.market_id,
                payload={
                    "resolution_rules": event.resolution_rules,
                    "resolution_source": event.resolution_source,
                    "historical_version_verified": False,
                },
            ),
        ]
        missing = [
            "historical_rule_version",
            "predecision_availability",
            "historical_executable_depth",
            "reviewed_independent_group",
            "qualified_external_context",
        ]
        if not event.created_at:
            missing.append("creation_time")
        if not event.closed_at:
            missing.append("actual_closing_time")
        proof = proofs.get(condition)
        if proof and q["chain_payout_matches_selected_outcome"]:
            payout = proof["payouts"][tokens.index(event.token_id)]
            if payout != event.outcome or not event.outcome_verified:
                raise ValueError("finalized payout disagrees with API-selected outcome")
            at = _time(proof["settlement_at"])
            available = max(_time(proof["available_at"]), event.available_at)
            verification = {
                **proof,
                "source_proofs_sha256": proof_digest,
                "official_source_outcome_verified": True,
                "rules_historical_version_reviewed": False,
            }
            outcomes.append(
                VerifiedEventOutcome(
                    id=digest(
                        ["event-final-outcome-v1", event.event_id, event.market_id, event.token_id, proof]
                    ),
                    timestamp=at,
                    available_at=available,
                    source="https://polygon-bor-rpc.publicnode.com",
                    event_id=event.event_id,
                    market_id=event.market_id,
                    token_id=event.token_id,
                    payout=payout,
                    resolution_rules_sha256=rules_hash,
                    settled_at=at,
                    verification_source="replayed_finalized_ctf_resolution_and_official_API_token_mapping",
                    proof_sha256=digest(verification),
                    verification=verification,
                )
            )
        else:
            missing.append("corroborated_final_settlement")
        row = CanonicalEvent(
            id=digest(["canonical-event-v1", event.id]),
            timestamp=event.timestamp,
            available_at=event.available_at,
            source=event.source,
            event_id=event.event_id,
            market_id=event.market_id,
            question=event.question,
            token_ids=tokens,
            outcomes=names,
            resolution_rules=event.resolution_rules,
            resolution_source=event.resolution_source,
            created_at=event.created_at,
            closes_at=event.closed_at,
            category=event.category,
            category_basis="archived official-source category mapping; descriptive, not past feature",
            dependency_group=q["dependency_group_proposal"],
            independence_reviewed=False,
            evidence_ids=tuple(ids),
            provenance={
                "original_record_id": event.id,
                "original_record_sha256": digest(original),
                "raw_sha256": event.raw_sha256,
                "raw_ref": event.raw_ref,
                "condition_id": condition,
                "selected_token_id": event.token_id,
                "official_api_outcome_verified": event.outcome_verified,
                "scheduled_end_time": raw.get("endDate"),
                "availability_basis": event.availability_basis,
                "source_qualification_deficiencies": q["deficiencies"],
            },
            missing_fields=tuple(missing),
        )
        events.append(row)
        by_key[key] = row
        parent_markets[event.event_id].append(row)
    for price in bundle.prices:
        if (price.event_id, price.market_id) not in by_key:
            raise ValueError("price refers to unknown event")
        add_evidence(price, "market_price", price.market_id)
    for book in bundle.books:
        rows = [e for e in events if e.market_id == book.market_id]
        if len(rows) != 1:
            raise ValueError("historical book event mapping unavailable")
        payload = book.model_dump(mode="json")
        evidence.append(
            EventEvidence(
                id=digest(["event-book-v1", book.id]),
                timestamp=book.timestamp,
                available_at=book.available_at,
                source=book.source,
                event_id=rows[0].event_id,
                market_id=book.market_id,
                kind="order_book",
                content_sha256=digest(payload),
                payload=payload,
            )
        )
    for context in bundle.context:
        for event in parent_markets.get(context.event_id, []):
            add_evidence(context, "external_context", event.market_id, independent=context.independent)
    if live_frame is not None:
        raise ValueError(
            "live observations require a separately timestamped prospective acquisition, not historical backfill"
        )
    # Reference every actual supporting item without changing its availability.
    links = defaultdict(list)
    for item in evidence:
        links[(item.event_id, item.market_id)].append(item.id)
    events = [e.model_copy(update={"evidence_ids": tuple(links[(e.event_id, e.market_id)])}) for e in events]
    by_kind = Counter(e.kind for e in evidence)
    by_category = Counter(e.category for e in events)
    before_settlement = 0
    for outcome in outcomes:
        if any(
            e.market_id == outcome.market_id
            and e.kind == "market_price"
            and e.available_at < outcome.settled_at
            for e in evidence
        ):
            before_settlement += 1
    funnel = {
        "canonical_market_propositions": len(events),
        "parent_event_groups": len({e.event_id for e in events}),
        "official_API_outcome_groups": sum(e.provenance["official_api_outcome_verified"] for e in events),
        "corroborated_finalized_outcome_groups": len(outcomes),
        "historical_market_price_rows": by_kind["market_price"],
        "actual_historical_book_rows": by_kind["order_book"],
        "external_context_rows": by_kind["external_context"],
        "resolved_events_with_predecision_available_price": before_settlement,
        "reviewed_independent_events": 0,
        "fully_qualified_training_events": 0,
        "fully_qualified_heldout_events": 0,
        "required_training_events": 100,
        "required_heldout_events": 100,
    }
    output.mkdir()
    hashes = {}
    total_bytes = 0
    for name, rows in [("events", events), ("evidence", evidence), ("outcomes", outcomes)]:
        encoded = b"".join((r.model_dump_json() + "\n").encode() for r in sorted(rows, key=lambda r: r.id))
        total_bytes += len(encoded)
        if total_bytes > MAX_BYTES:
            raise ValueError("event artifact budget exceeded")
        (output / (name + ".jsonl")).write_bytes(encoded)
        hashes[name + ".jsonl"] = hashlib.sha256(encoded).hexdigest()
    manifest = {
        "schema_version": "1.0",
        "dataset_version": "event-outcome-canonical-v1",
        "dataset_sha256": digest(hashes),
        "files": hashes,
        "qualification_funnel": funnel,
        "source_bundle_sha256": qmanifest["source_bundle_sha256"],
        "source_qualification_sha256": hashlib.sha256(qbytes).hexdigest(),
        "source_proofs_sha256": proof_digest,
        "categories": dict(by_category),
        "source_path": str(source.resolve()),
        "created_at": datetime.now(UTC).isoformat(),
        "missing_field_counts": dict(Counter(k for e in events for k in e.missing_fields)),
        "certification_authority": False,
        "automatic_promotion": False,
        "limitations": [
            "Historical observations downloaded after resolution retain collected-now availability",
            "Price history is not executable depth",
            "Parent/asset grouping proposals do not establish event independence",
            "No current rule text is asserted to be its historical version",
        ],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def load_dataset(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    if (
        manifest.get("schema_version") != "1.0"
        or manifest.get("certification_authority") is not False
        or manifest.get("automatic_promotion") is not False
    ):
        raise ValueError("invalid event dataset schema/authority")
    if digest(manifest["files"]) != manifest["dataset_sha256"]:
        raise ValueError("event dataset manifest identity mismatch")
    if (
        sum((directory / (name + ".jsonl")).stat().st_size for name in ("events", "evidence", "outcomes"))
        > MAX_BYTES
    ):
        raise ValueError("event dataset byte budget exceeded")
    result = {"manifest": manifest}
    for name, model in [
        ("events", CanonicalEvent),
        ("evidence", EventEvidence),
        ("outcomes", VerifiedEventOutcome),
    ]:
        p = directory / (name + ".jsonl")
        if p.stat().st_size > MAX_BYTES:
            raise ValueError("event dataset byte budget exceeded")
        content = p.read_bytes()
        if hashlib.sha256(content).hexdigest() != manifest["files"][name + ".jsonl"]:
            raise ValueError("event dataset file checksum mismatch")
        records = [model.model_validate_json(line) for line in content.splitlines()]
        if len(records) > 100000 or len({r.id for r in records}) != len(records):
            raise ValueError("event dataset record cardinality/identity invalid")
        result[name] = records
    keys = {(e.event_id, e.market_id) for e in result["events"]}
    evidence_ids = {e.id for e in result["evidence"]}
    evidence_by_id = {e.id: e for e in result["evidence"]}
    events_by_key = {(e.event_id, e.market_id): e for e in result["events"]}
    for row in result["events"]:
        if not set(row.evidence_ids) <= evidence_ids:
            raise ValueError("event refers to missing evidence")
        if any(
            (evidence_by_id[i].event_id, evidence_by_id[i].market_id) != (row.event_id, row.market_id)
            for i in row.evidence_ids
        ):
            raise ValueError("event refers to different proposition evidence")
    for row in result["evidence"]:
        if (row.event_id, row.market_id) not in keys or digest(row.payload) != row.content_sha256:
            raise ValueError("evidence identity/content mismatch")
    for row in result["outcomes"]:
        if (row.event_id, row.market_id) not in keys or digest(row.verification) != row.proof_sha256:
            raise ValueError("outcome proof binding mismatch")
        event = events_by_key[(row.event_id, row.market_id)]
        if (
            row.token_id not in event.token_ids
            or row.resolution_rules_sha256 != hashlib.sha256(event.resolution_rules.encode()).hexdigest()
            or row.verification.get("payouts", [])[event.token_ids.index(row.token_id)] != row.payout
        ):
            raise ValueError("outcome token/rules/payout mismatch")
    return result
