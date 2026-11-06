"""Controlled chain/transport contracts, never actual validation evidence."""

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from neraium_poly.research.history import HistoryPipeline
from neraium_poly.research.qualification import _load_proofs, qualify_history
from neraium_poly.research.settlement_evidence import (
    CONDITION_RESOLUTION,
    CTF,
    ReadOnlySettlementClient,
    binary_payout,
    canonical,
    corroborate_resolution,
)
from test_research_history import raw_market, transport

CONDITION = "0x" + "1" * 64
TX = "0x" + "2" * 64
BLOCK = "0x" + "3" * 64
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def fixtures():
    log = {
        "address": CTF,
        "topics": [CONDITION_RESOLUTION, CONDITION, "0x" + "4" * 64, "0x" + "5" * 64],
        "data": "0x" + "".join(f"{n:064x}" for n in [2, 64, 2, 1, 0]),
        "removed": False,
        "blockNumber": "0x10",
        "blockHash": BLOCK,
        "transactionHash": TX,
        "logIndex": "0x1",
    }
    receipt = {
        "status": "0x1",
        "transactionHash": TX,
        "blockHash": BLOCK,
        "blockNumber": "0x10",
        "logs": [log],
    }
    block = {"hash": BLOCK, "number": "0x10", "timestamp": hex(int(NOW.timestamp()) - 60)}
    return log, receipt, block, copy.deepcopy(block), {"number": "0x20"}


def test_exact_finalized_binary_log_is_required():
    log, *rest = fixtures()
    assert binary_payout(log, CONDITION) == (1, 0)
    proof = corroborate_resolution(CONDITION, log, *rest, available_at=NOW)
    assert proof["settlement_at"] == (NOW - timedelta(minutes=1)).isoformat()
    assert proof["available_at"] == NOW.isoformat() and proof["availability_basis"] == "collected_now"


@pytest.mark.parametrize("mutation", ["removed", "contract", "condition", "topic", "split_payout", "offset"])
def test_unsupported_or_false_resolution_log_rejects(mutation):
    log, *_ = fixtures()
    if mutation == "removed":
        log["removed"] = True
    elif mutation == "contract":
        log["address"] = "0x" + "0" * 40
    elif mutation == "condition":
        log["topics"][1] = TX
    elif mutation == "topic":
        log["topics"][0] = TX
    elif mutation == "split_payout":
        log["data"] = "0x" + "".join(f"{n:064x}" for n in [2, 64, 2, 1, 1])
    else:
        log["data"] = "0x" + "".join(f"{n:064x}" for n in [2, 96, 2, 1, 0])
    with pytest.raises(ValueError):
        binary_payout(log, CONDITION)


@pytest.mark.parametrize(
    "mutation", ["revert", "receipt_tx", "block_hash", "canonical", "inclusion", "finality", "future"]
)
def test_receipt_canonical_block_and_finality_reject_mismatch(mutation):
    log, receipt, block, canonical_block, finalized = fixtures()
    if mutation == "revert":
        receipt["status"] = "0x0"
    elif mutation == "receipt_tx":
        receipt["transactionHash"] = CONDITION
    elif mutation == "block_hash":
        block["hash"] = TX
    elif mutation == "canonical":
        canonical_block["hash"] = TX
    elif mutation == "inclusion":
        receipt["logs"] = []
    elif mutation == "finality":
        finalized["number"] = "0xf"
    else:
        block["timestamp"] = hex(int(NOW.timestamp()) + 60)
    with pytest.raises(ValueError):
        corroborate_resolution(CONDITION, log, receipt, block, canonical_block, finalized, available_at=NOW)


def test_no_transaction_method_or_unbounded_log_range(tmp_path):
    client = ReadOnlySettlementClient(
        tmp_path / "chain", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    )
    try:
        with pytest.raises(ValueError, match="read-only"):
            client.request("eth_sendRawTransaction", ["0x0"])
        with pytest.raises(ValueError, match="bounded reviewed"):
            client.request(
                "eth_getLogs",
                [
                    {
                        "address": CTF,
                        "topics": [CONDITION_RESOLUTION],
                        "fromBlock": "0x0",
                        "toBlock": "0x10000",
                    }
                ],
            )
        assert client.requests == 0
    finally:
        client.close()


def test_rpc_budget_hashes_and_new_directory_guard(tmp_path):
    def response(request):
        body = json.loads(request.content)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": "0x89"})

    target = tmp_path / "chain"
    client = ReadOnlySettlementClient(
        target, client=httpx.Client(transport=httpx.MockTransport(response)), max_requests=1, interval=0
    )
    assert client.request("eth_chainId", []) == "0x89"
    with pytest.raises(ValueError, match="budget"):
        client.request("eth_chainId", [])
    row = json.loads((target / "manifest.json").read_bytes())["responses"][0]
    assert hashlib.sha256((target / row["response_path"]).read_bytes()).hexdigest() == row["response_sha256"]
    with pytest.raises(ValueError, match="never overwrite"):
        ReadOnlySettlementClient(target)
    client.close()


def test_raw_replay_does_not_trust_normalized_proofs(tmp_path):
    directory = tmp_path / "chain"
    directory.mkdir()
    (directory / "manifest.json").write_bytes(canonical({"responses": []}))
    (directory / "proofs.json").write_bytes(canonical({"manifest_sha256": "changed", "proofs": []}))
    with pytest.raises(ValueError, match="manifest changed"):
        _load_proofs(directory)


async def test_versioned_qualification_uses_two_workers_without_certifying_ids(tmp_path, now):
    # Substantial rule strings test source integrity and worker overlap on two CPUs.
    markets = [raw_market(now, i) for i in range(1, 11)]
    for market in markets:
        market["description"] = "Controlled fixture rule text. " * 10000
    pipeline = HistoryPipeline(
        tmp_path / "source",
        client=httpx.AsyncClient(transport=transport(now, markets=markets)),
        min_interval=0,
    )
    try:
        await pipeline.acquire(max_events=10, max_history_requests=0, max_context_requests=0)
    finally:
        await pipeline.close()
    source_manifest = (tmp_path / "source" / "manifest.json").read_bytes()
    report = qualify_history(tmp_path / "source", tmp_path / "qualified")
    manifest = json.loads((tmp_path / "qualified" / "manifest.json").read_bytes())
    assert report["events"] == 10 and report["certification_status"] == "blocked"
    assert report["certifiable_training_events"] == report["certifiable_heldout_events"] == 0
    assert report["cpu_worker_processes"] == 2 and report["worker_overlap_observed"]
    assert len({worker["pid"] for worker in manifest["workers"]}) == 2
    assert (tmp_path / "source" / "manifest.json").read_bytes() == source_manifest
    with pytest.raises(ValueError, match="new versioned"):
        qualify_history(tmp_path / "source", tmp_path / "qualified")
    with pytest.raises(ValueError, match="must not modify"):
        qualify_history(tmp_path / "source", tmp_path / "source" / "derived")
    with pytest.raises(ValueError, match="exactly two"):
        qualify_history(tmp_path / "source", tmp_path / "other", workers=1)


def acquired_fixture(tmp_path):
    log, receipt, block, _, finalized = fixtures()

    def response(request):
        body = json.loads(request.content)
        result = {
            "eth_chainId": "0x89",
            "eth_getLogs": [log],
            "eth_getTransactionReceipt": receipt,
            "eth_getBlockByHash": block,
        }.get(body["method"])
        if body["method"] == "eth_getBlockByNumber":
            result = finalized if body["params"][0] == "finalized" else block
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    directory = tmp_path / "chain"
    client = ReadOnlySettlementClient(
        directory, client=httpx.Client(transport=httpx.MockTransport(response)), interval=0
    )
    try:
        assert len(client.acquire([CONDITION], 16, 16)["proofs"]) == 1
    finally:
        client.close()
    return directory


def test_acquisition_replays_exact_raw_proofs(tmp_path):
    directory = acquired_fixture(tmp_path)
    proofs, digest = _load_proofs(directory)
    assert proofs[CONDITION]["payouts"] == [1, 0] and len(digest) == 64
    path = directory / "proofs.json"
    report = json.loads(path.read_bytes())
    report["proofs"][0]["available_at"] = NOW.isoformat()
    path.write_bytes(canonical(report))
    with pytest.raises(ValueError, match="backdated"):
        _load_proofs(directory)


def test_acquired_raw_tamper_is_not_normalized_away(tmp_path):
    directory = acquired_fixture(tmp_path)
    manifest = json.loads((directory / "manifest.json").read_bytes())
    (directory / manifest["responses"][0]["response_path"]).write_text("tampered")
    with pytest.raises(ValueError, match="checksum"):
        _load_proofs(directory)
