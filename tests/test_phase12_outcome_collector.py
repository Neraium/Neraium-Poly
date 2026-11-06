"""Controlled HTTP/RPC evidence only; never operational resolutions or scores."""

import asyncio
import copy
import hashlib
import json
from datetime import timedelta

import httpx
import pytest
from neraium_poly.data.polymarket import normalize_market
from neraium_poly.research.phase12.contracts import EventForecast
from neraium_poly.research.phase12.outcome_collector import acquire_verified_outcome, verify_collected_outcome
from test_operational_data import raw_market
from test_phase9_qualification import BLOCK, CONDITION, NOW, TX, fixtures


def controlled_clients(
    *, disputed=False, chain_payout_mismatch=False, preparation=False, variant=None, token_index=0
):
    raw = raw_market()
    raw["conditionId"] = CONDITION
    if variant == "v2":
        raw.update(version="v2", positionIds=["11", "12"])
    if variant == "future":
        raw["version"] = "v3-unreviewed"
    if variant == "negRisk":
        raw["negRisk"] = True
    market = normalize_market(raw, NOW - timedelta(seconds=180))[token_index]
    raw.update(closed=True, active=False, umaResolutionStatus="resolved")
    native = {
        "condition_id": CONDITION,
        "status": "resolved",
        "extended_review": False,
        "was_disputed": disputed,
        "new_version_q": False,
        "was_arbitrated": False,
        "resolution_source": "reported",
        "market_type": "BINARY",
        "reporter": "UMA_OO",
        "transaction_hash": TX,
        "resolved_at": (NOW - timedelta(seconds=60)).isoformat(),
        "last_update_timestamp": (NOW - timedelta(seconds=30)).isoformat(),
        "payouts": [0, 1000000] if chain_payout_mismatch else [1000000, 0],
    }

    def public(request):
        assert request.method == "GET"
        if request.url.path == "/markets/1":
            return httpx.Response(200, json=raw)
        if request.url.path.startswith("/markets-by-token/"):
            return httpx.Response(
                200, json={"condition_id": CONDITION, "primary_token_id": "12", "secondary_token_id": "11"}
            )
        if request.url.path == "/v2/resolutions":
            return httpx.Response(200, json={"data": [native]})
        raise AssertionError(str(request.url))

    log, receipt, block, canonical, final = fixtures()

    def rpc(request):
        body = json.loads(request.content)
        method = body["method"]
        params = body["params"]
        assert method in {
            "eth_chainId",
            "eth_getTransactionReceipt",
            "eth_getBlockByHash",
            "eth_getBlockByNumber",
            "eth_getLogs",
        }
        if method == "eth_chainId":
            value = "0x89"
        elif method == "eth_getTransactionReceipt":
            value = receipt
        elif method == "eth_getBlockByHash":
            assert params[0] == BLOCK
            value = block
        elif method == "eth_getBlockByNumber":
            value = final if params[0] == "finalized" else canonical
        else:
            value = [] if preparation else [log]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": value})

    forecast = EventForecast(
        id="controlled-forecast",
        timestamp=NOW - timedelta(seconds=120),
        available_at=NOW - timedelta(seconds=120),
        source="controlled-fixture",
        event_id=market.event_id,
        market_id=market.market_id,
        token_id=market.token_id,
        dependency_group=market.event_id,
        kind="market_baseline",
        probability=0.4,
        market_probability=0.4,
        evidence_cutoff=NOW - timedelta(seconds=120),
        model_version="controlled-only",
        feature_version="controlled-only",
        dataset_sha256="a" * 64,
        model_sha256="b" * 64,
        resolution_rules_sha256=hashlib.sha256(market.resolution_rules.encode()).hexdigest(),
        evidence_ids=("controlled-evidence",),
        uncertainty={"kind": "unvalidated controlled fixture"},
    )
    return (
        forecast,
        market,
        httpx.AsyncClient(transport=httpx.MockTransport(public)),
        httpx.Client(transport=httpx.MockTransport(rpc)),
    )


@pytest.fixture(autouse=True)
def no_sync_wait(monkeypatch):
    # Only transport retry delay is skipped; real archive/proof replay still runs.
    monkeypatch.setattr("neraium_poly.research.settlement_evidence.time.sleep", lambda _: None)


@pytest.mark.parametrize("token_index", [0, 1])
async def test_exact_future_resolution_replays_native_and_finalized_chain(tmp_path, token_index):
    f, m, public, rpc = controlled_clients(token_index=token_index)
    try:
        outcome = await acquire_verified_outcome(
            f, m, tmp_path / "proof", client=public, rpc_client=rpc, clock=lambda: NOW
        )
        assert outcome is not None
        assert outcome.payout == 1 - token_index
        assert f.timestamp < outcome.settled_at and outcome.available_at >= outcome.settled_at
        assert (
            outcome.proof_sha256
            == hashlib.sha256(
                json.dumps(outcome.verification, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        assert await asyncio.to_thread(verify_collected_outcome, outcome, m, f, tmp_path)
        assert (tmp_path / "proof/native/manifest.json").is_file()
        assert (tmp_path / "proof/chain/proofs.json").is_file()
    finally:
        await public.aclose()
        rpc.close()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"disputed": True},
        {"chain_payout_mismatch": True},
        {"preparation": True},
        {"variant": "v2"},
        {"variant": "negRisk"},
        {"variant": "future"},
    ],
)
async def test_disputes_preparation_and_unsupported_variants_never_become_outcomes(tmp_path, kwargs):
    f, m, public, rpc = controlled_clients(**kwargs)
    try:
        assert (
            await acquire_verified_outcome(
                f, m, tmp_path / "proof", client=public, rpc_client=rpc, clock=lambda: NOW
            )
            is None
        )
    finally:
        await public.aclose()
        rpc.close()


async def test_forecast_after_resolution_and_bad_rule_identity_decline(tmp_path):
    f, m, public, rpc = controlled_clients()
    try:
        bad = f.model_copy(update={"resolution_rules_sha256": "c" * 64})
        assert (
            await acquire_verified_outcome(
                bad, m, tmp_path / "bad", client=public, rpc_client=rpc, clock=lambda: NOW
            )
            is None
        )
        assert not (tmp_path / "bad").exists()
        late = f.model_copy(
            update={"timestamp": NOW - timedelta(seconds=10), "available_at": NOW - timedelta(seconds=10)}
        )
        assert (
            await acquire_verified_outcome(
                late, m, tmp_path / "late", client=public, rpc_client=rpc, clock=lambda: NOW
            )
            is None
        )
    finally:
        await public.aclose()
        rpc.close()


async def test_immutable_raw_and_forecast_bindings_reject_tampering(tmp_path):
    f, m, public, rpc = controlled_clients()
    try:
        o = await acquire_verified_outcome(
            f, m, tmp_path / "proof", client=public, rpc_client=rpc, clock=lambda: NOW
        )
        assert o is not None
        assert not await asyncio.to_thread(
            verify_collected_outcome, o, m, f.model_copy(update={"id": "different"}), tmp_path
        )
        manifest = json.loads((tmp_path / "proof/native/manifest.json").read_text())
        file = tmp_path / "proof/native" / manifest["responses"][0]["response_path"]
        file.write_text("{}")
        assert not await asyncio.to_thread(verify_collected_outcome, o, m, f, tmp_path)
    finally:
        await public.aclose()
        rpc.close()


async def test_new_directory_and_root_confinement(tmp_path):
    f, m, public, rpc = controlled_clients()
    try:
        o = await acquire_verified_outcome(
            f, m, tmp_path / "proof", client=public, rpc_client=rpc, clock=lambda: NOW
        )
        assert o is not None
        with pytest.raises(ValueError, match="new resolution evidence"):
            await acquire_verified_outcome(
                f, m, tmp_path / "proof", client=public, rpc_client=rpc, clock=lambda: NOW
            )
        forged = copy.deepcopy(o.verification)
        forged["acquisition_subdir"] = "../proof"
        changed = o.model_copy(
            update={
                "verification": forged,
                "proof_sha256": hashlib.sha256(
                    json.dumps(forged, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
            }
        )
        assert not await asyncio.to_thread(
            verify_collected_outcome, changed, m, f, tmp_path / "different-root"
        )
    finally:
        await public.aclose()
        rpc.close()


async def test_total_proof_storage_budget_rejects_before_network(tmp_path):
    f, m, public, rpc = controlled_clients()
    try:
        # Sparse controlled file exercises accounting without a large allocation.
        with (tmp_path / "retained-evidence.bin").open("wb") as handle:
            handle.truncate(25 * 1024 * 1024)
        with pytest.raises(ValueError, match="storage budget"):
            await acquire_verified_outcome(
                f, m, tmp_path / "next", client=public, rpc_client=rpc, clock=lambda: NOW
            )
        assert not (tmp_path / "next").exists()
    finally:
        await public.aclose()
        rpc.close()


def test_ambiguous_logs_reject_before_derived_proof_report(tmp_path):
    from neraium_poly.research.phase12.outcome_collector import _ForwardSettlementClient

    log, *_ = fixtures()

    def handler(request):
        body = json.loads(request.content)
        result = (
            "0x89"
            if body["method"] == "eth_chainId"
            else {"number": "0x20"}
            if body["method"] == "eth_getBlockByNumber"
            else [log, log]
        )
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = _ForwardSettlementClient(
            tmp_path / "chain", client=http, max_requests=15, max_bytes=5 * 1024 * 1024, interval=0
        )
        try:
            with pytest.raises(ValueError, match="ambiguous resolution logs"):
                client.acquire([CONDITION], 15, 17)
            assert not (tmp_path / "chain/proofs.json").exists()
        finally:
            client.close()


@pytest.mark.parametrize("field", ["blockNumber", "logIndex"])
def test_oversized_log_quantities_reject_before_proof_expansion(tmp_path, field):
    from neraium_poly.research.phase12.outcome_collector import _ForwardSettlementClient
    from neraium_poly.research.settlement_evidence import CONDITION_RESOLUTION, CTF

    log, *_ = fixtures()
    log[field] = "0x" + "f" * 17
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, json={"jsonrpc": "2.0", "id": json.loads(r.content)["id"], "result": [log]}
            )
        )
    ) as http:
        client = _ForwardSettlementClient(
            tmp_path / "chain", client=http, max_requests=15, max_bytes=5 * 1024 * 1024, interval=0
        )
        try:
            with pytest.raises(ValueError, match="bounded resolution log quantities"):
                client.request(
                    "eth_getLogs",
                    [
                        {
                            "address": CTF,
                            "topics": [CONDITION_RESOLUTION, [CONDITION]],
                            "fromBlock": "0xf",
                            "toBlock": "0x11",
                        }
                    ],
                )
        finally:
            client.close()


def test_unsupported_transaction_locator_never_starts_rpc(tmp_path):
    from types import SimpleNamespace

    from neraium_poly.research.phase12.outcome_collector import _chain_acquire

    def forbidden(request):
        raise AssertionError("RPC must not be invoked")

    with httpx.Client(transport=httpx.MockTransport(forbidden)) as http:
        assert (
            _chain_acquire(
                tmp_path / "chain",
                SimpleNamespace(transaction_hash="unbounded-unknown", condition_id=CONDITION),
                http,
            )
            is None
        )
        assert not (tmp_path / "chain").exists()
