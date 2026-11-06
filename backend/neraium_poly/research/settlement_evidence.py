"""Bounded read-only Polygon resolution corroboration; no transaction methods."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

RPC_ENDPOINT = "https://polygon-bor-rpc.publicnode.com"
CTF = "0x4d97dcd97ec945f40cf65f87097ace5ea0476045"
# Keccak-256 of the exact official Solidity ABI signature, not SHA3-256.
CONDITION_RESOLUTION = "0xb44d84d3289691f71497564b85d4233648d9dbae8cbdbb4329f301c3a0185894"
READ_METHODS = {
    "eth_chainId",
    "eth_getTransactionReceipt",
    "eth_getBlockByHash",
    "eth_getBlockByNumber",
    "eth_getLogs",
}
HEX32 = re.compile(r"^0x[0-9a-fA-F]{64}$")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def binary_payout(log, condition_id):
    """Decode only the reviewed CTF binary ConditionResolution ABI."""
    topics = log.get("topics", [])
    if (
        log.get("address", "").lower() != CTF
        or len(topics) != 4
        or topics[0].lower() != CONDITION_RESOLUTION
        or topics[1].lower() != condition_id.lower()
        or not HEX32.fullmatch(condition_id)
        or log.get("removed") is not False
    ):
        raise ValueError("resolution identity, ABI or canonical inclusion mismatch")
    data = log.get("data", "")
    if not re.fullmatch(r"0x[0-9a-fA-F]{320}", data):
        raise ValueError("unsupported resolution ABI length")
    words = [int(data[i : i + 64], 16) for i in range(2, len(data), 64)]
    if words[:3] != [2, 64, 2] or words[3:] not in ([1, 0], [0, 1]):
        raise ValueError("nonbinary or malformed resolution payout")
    return tuple(words[3:])


def corroborate_resolution(condition_id, log, receipt, block, canonical_block, finalized, *, available_at):
    """All required evidence is explicitly supplied, making verification replayable."""
    if not all(isinstance(value, dict) for value in (log, receipt, block, canonical_block, finalized)):
        raise ValueError("incomplete RPC inclusion evidence")
    payout = binary_payout(log, condition_id)
    if not HEX32.fullmatch(log.get("transactionHash", "")) or not HEX32.fullmatch(log.get("blockHash", "")):
        raise ValueError("missing inclusion identity")
    if (
        receipt.get("status") != "0x1"
        or receipt.get("transactionHash", "").lower() != log["transactionHash"].lower()
        or receipt.get("blockHash", "").lower() != log["blockHash"].lower()
        or receipt.get("blockNumber") != log.get("blockNumber")
        or block.get("hash", "").lower() != log["blockHash"].lower()
        or block.get("number") != log.get("blockNumber")
        or canonical_block.get("hash", "").lower() != log["blockHash"].lower()
        or not any(item == log for item in receipt.get("logs", []))
    ):
        raise ValueError("receipt or canonical block does not bind exact resolution log")
    if int(finalized["number"], 16) < int(block["number"], 16):
        raise ValueError("resolution block is not finalized")
    at = datetime.fromtimestamp(int(block["timestamp"], 16), UTC)
    if available_at.tzinfo is None or at > available_at:
        raise ValueError("resolution timestamp unavailable at acquisition")
    if "blockTimestamp" in log and int(log["blockTimestamp"], 16) != int(block["timestamp"], 16):
        raise ValueError("log/block timestamp mismatch")
    return {
        "condition_id": condition_id.lower(),
        "contract": CTF,
        "chain_id": 137,
        "settlement_at": at.isoformat(),
        "available_at": available_at.isoformat(),
        "availability_basis": "collected_now",
        "transaction_hash": log["transactionHash"],
        "log_index": log["logIndex"],
        "block_hash": block["hash"],
        "block_number": int(block["number"], 16),
        "payouts": list(payout),
        "finalized_height_at_acquisition": int(finalized["number"], 16),
        "proof_status": "rpc_corroborated_finalized_ctf_resolution",
        "trust_limit": "HTTPS RPC attribution and reproducible evidence, not independent node consensus verification",
    }


class ReadOnlySettlementClient:
    def __init__(
        self, directory, *, client=None, max_requests=100, max_bytes=100 * 1024 * 1024, interval=0.15
    ):
        if not 1 <= max_requests <= 100 or not 1024 <= max_bytes <= 100 * 1024 * 1024 or interval < 0:
            raise ValueError("bounded acquisition required")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        if any(self.directory.iterdir()):
            raise ValueError("new evidence directory required; never overwrite prior acquisition")
        if shutil.disk_usage(self.directory).free < 8 * 1024**3 + max_bytes:
            raise ValueError("research free-disk floor")
        self.raw = self.directory / "raw"
        self.raw.mkdir()
        self.client = client or httpx.Client(timeout=20, follow_redirects=False)
        self.owns_client = client is None
        self.max_requests, self.max_bytes, self.interval = max_requests, max_bytes, interval
        self.requests = self.bytes = 0
        self.manifest = []

    def request(self, method, params):
        if method not in READ_METHODS:
            raise ValueError("only explicit read-only chain methods are permitted")
        if method == "eth_getLogs":
            query = params[0]
            if (
                query.get("address", "").lower() != CTF
                or query.get("topics", [None])[0] != CONDITION_RESOLUTION
                or int(query["fromBlock"], 16) < 0
                or not 0 <= int(query["toBlock"], 16) - int(query["fromBlock"], 16) <= 5000
            ):
                raise ValueError("bounded reviewed resolution log query required")
        if self.requests >= self.max_requests:
            raise ValueError("request budget exhausted")
        self.requests += 1
        time.sleep(self.interval)
        body = {"jsonrpc": "2.0", "id": self.requests, "method": method, "params": params}
        data = bytearray()
        with self.client.stream("POST", RPC_ENDPOINT, json=body) as response:
            for chunk in response.iter_bytes():
                self.bytes += len(chunk)
                if self.bytes > self.max_bytes or len(data) + len(chunk) > 10 * 1024 * 1024:
                    raise ValueError("response byte budget exhausted")
                data.extend(chunk)
            received = datetime.now(UTC)
            digest = hashlib.sha256(data).hexdigest()
            path = f"raw/{digest}.json"
            (self.directory / path).write_bytes(data)
            self.manifest.append(
                {
                    "url": RPC_ENDPOINT,
                    "method": "POST",
                    "rpc_method": method,
                    "request": body,
                    "response_sha256": digest,
                    "response_path": path,
                    "bytes": len(data),
                    "status": response.status_code,
                    "received_at": received.isoformat(),
                }
            )
            self.save_manifest()
            response.raise_for_status()
        result = json.loads(data)
        if result.get("id") != body["id"] or result.get("jsonrpc") != "2.0" or "error" in result:
            raise ValueError("invalid or unsuccessful read-only RPC response")
        return result.get("result")

    def save_manifest(self):
        value = {
            "schema_version": "1.0",
            "source": RPC_ENDPOINT,
            "chain_id_required": 137,
            "requests": self.requests,
            "response_bytes": self.bytes,
            "max_requests": self.max_requests,
            "max_bytes": self.max_bytes,
            "read_only_methods": sorted(READ_METHODS),
            "responses": self.manifest,
        }
        (self.directory / "manifest.json").write_bytes(canonical(value))

    def acquire(self, condition_ids, block_start, block_end):
        if not 1 <= len(condition_ids) <= 250 or any(not HEX32.fullmatch(v) for v in condition_ids):
            raise ValueError("bounded explicit condition IDs required")
        if block_start < 0 or not 0 <= block_end - block_start <= 20000:
            raise ValueError("bounded block range required")
        if self.request("eth_chainId", []) != "0x89":
            raise ValueError("wrong chain")
        finalized = self.request("eth_getBlockByNumber", ["finalized", False])
        if not isinstance(finalized, dict):
            raise TypeError("finalized header unavailable")
        logs = []
        for start in range(block_start, block_end + 1, 5001):
            end = min(block_end, start + 5000)
            result = self.request(
                "eth_getLogs",
                [
                    {
                        "address": CTF,
                        "topics": [CONDITION_RESOLUTION, condition_ids],
                        "fromBlock": hex(start),
                        "toBlock": hex(end),
                    }
                ],
            )
            if not isinstance(result, list):
                raise TypeError("resolution logs unavailable")
            logs.extend(result)
        receipts, blocks, canonical_blocks = {}, {}, {}
        proofs, failures = [], []
        for log in sorted(logs, key=lambda l: (int(l["blockNumber"], 16), int(l["logIndex"], 16))):
            condition = log.get("topics", [None, ""])[1]
            try:
                if condition not in condition_ids:
                    raise ValueError("unrequested condition")
                tx, block_hash = log["transactionHash"], log["blockHash"]
                if tx not in receipts:
                    receipts[tx] = self.request("eth_getTransactionReceipt", [tx])
                if block_hash not in blocks:
                    blocks[block_hash] = self.request("eth_getBlockByHash", [block_hash, False])
                    canonical_blocks[block_hash] = self.request(
                        "eth_getBlockByNumber", [log["blockNumber"], False]
                    )
                proofs.append(
                    corroborate_resolution(
                        condition,
                        log,
                        receipts[tx],
                        blocks[block_hash],
                        canonical_blocks[block_hash],
                        finalized,
                        available_at=datetime.now(UTC),
                    )
                )
            except (ValueError, KeyError, TypeError) as error:
                failures.append({"condition_id": condition, "reason": str(error)})
                if self.requests >= self.max_requests:
                    break
        result = {
            "schema_version": "1.0",
            "proofs": proofs,
            "failures": failures,
            "requested_conditions": condition_ids,
            "searched_blocks": [block_start, block_end],
            "missing_conditions": sorted(set(condition_ids) - {p["condition_id"] for p in proofs}),
            "availability_policy": "resolution event-time is block time; evidence availability stays collected_now",
            "manifest_sha256": hashlib.sha256((self.directory / "manifest.json").read_bytes()).hexdigest(),
        }
        (self.directory / "proofs.json").write_bytes(canonical(result))
        return result

    def close(self):
        if self.owns_client:
            self.client.close()
