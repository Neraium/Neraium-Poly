"""Research-only finalized CTF proof, including negative-risk asset/state binding.

Gamma and Data API terminal prices are never payout evidence. RPC corroboration
is reproducible attribution to one HTTPS provider, not independent consensus.
The legacy certified gate and all trading authorities are deliberately unchanged.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from neraium_poly.research.settlement_evidence import (
    CTF,
    HEX32,
    ReadOnlySettlementClient,
    canonical,
    corroborate_resolution,
)

NEG_RISK = "0xd91e80cf2e7be2e162c6513ced06f1dd0da35296"
USDC = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"
ABI_SOURCES = (
    "https://raw.githubusercontent.com/gnosis/conditional-tokens-contracts/master/contracts/ConditionalTokens.sol",
    "https://raw.githubusercontent.com/Polymarket/neg-risk-ctf-adapter/main/src/NegRiskAdapter.sol",
    "https://docs.polymarket.com/resources/contracts",
)
# Keccak selectors of official Solidity signatures (not NIST SHA3).
SELECTORS = {
    "condition": "852c6ae2",  # getConditionId(address,bytes32,uint256)
    "collection": "856296f7",  # getCollectionId(bytes32,bytes32,uint256)
    "position": "39dd7530",  # getPositionId(address,bytes32)
    "denominator": "dd34de67",  # payoutDenominator(bytes32)
    "numerator": "0504c814",  # payoutNumerators(bytes32,uint256)
    "wrapped_collateral": "7e3b74c3",  # wcol()
}


def word(value):
    if isinstance(value, int):
        if value < 0 or value >= 2**256:
            raise ValueError("invalid ABI integer")
        return f"{value:064x}"
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{40}|0x[0-9a-fA-F]{64}", value):
        raise ValueError("invalid ABI word")
    return value[2:].lower().zfill(64)


def call_key(target, name, *args):
    return (target.lower(), "0x" + SELECTORS[name] + "".join(word(a) for a in args))


def _list(value):
    return json.loads(value) if isinstance(value, str) else value


def _iso(value):
    at = datetime.fromisoformat(value)
    if at.tzinfo is None:
        raise ValueError("UTC availability required")
    return at


def verify_native_bundle(bundle):
    """Replay exact identities, receipt finality, contract-computed assets/payouts."""
    f, g, c = (bundle[k] for k in ("forecast", "gamma", "clob"))
    market = f["market"]
    if any(str(f[key]) != str(market[key]) for key in ("market_id", "event_id", "token_id")):
        raise ValueError("forecast original market identity mismatch")
    condition = g["conditionId"].lower()
    if not HEX32.fullmatch(condition) or g.get("version") != "v1":
        raise ValueError("unsupported native contract generation")
    outcomes = _list(g["outcomes"])
    tokens = _list(g["clobTokenIds"])
    original_token = str(market["token_id"])
    original_outcome = market["outcome"]
    rules = g.get("description", "")
    if (
        str(g["id"]) != str(market["market_id"])
        or g["question"] != market["question"]
        or hashlib.sha256(rules.encode()).hexdigest() != f["rules_sha256"]
        or outcomes != ["Yes", "No"]
        or len(tokens) != 2
        or original_outcome not in outcomes
        or original_token != str(tokens[outcomes.index(original_outcome)])
        or c["condition_id"].lower() != condition
        or {str(c["primary_token_id"]), str(c["secondary_token_id"])} != set(map(str, tokens))
        or market["resolution_rules"] != rules
        or market["resolution_source"] != g.get("resolutionSource")
        or g.get("closed") is not True
        or g.get("umaResolutionStatus") != "resolved"
    ):
        raise ValueError("original rules, market or outcome asset identity mismatch")
    parent = bundle["parent_event"]
    if str(parent["id"]) != str(market["event_id"]) or str(g["id"]) not in [
        str(m["id"]) for m in parent.get("markets", [])
    ]:
        raise ValueError("parent event identity mismatch")
    log = bundle["log"]
    oracle = "0x" + log["topics"][2][-40:].lower()
    if (
        g.get("negRisk") is not True
        or oracle != NEG_RISK
        or log["topics"][3].lower() != g["questionID"].lower()
    ):
        raise ValueError("unreviewed oracle or question identity")
    proof = corroborate_resolution(
        condition,
        log,
        bundle["receipt"],
        bundle["block"],
        bundle["canonical_block"],
        bundle["finalized"],
        available_at=_iso(bundle["available_at"]),
    )
    if _iso(f["timestamp"]) >= _iso(proof["settlement_at"]) or _iso(f["evidence_cutoff"]) > _iso(
        f["timestamp"]
    ):
        raise ValueError("forecast temporal identity invalid")
    state = {(r["to"].lower(), r["data"]): r["result"] for r in bundle["state"]}

    def read(target, name, *args):
        result = state[call_key(target, name, *args)]
        if not HEX32.fullmatch(result):
            raise ValueError("invalid contract return word")
        return result.lower()

    if read(CTF, "condition", oracle, g["questionID"], 2) != condition:
        raise ValueError("on-chain condition identity mismatch")
    collateral = "0x" + read(NEG_RISK, "wrapped_collateral")[-40:]
    for i, token in enumerate(tokens):
        collection = read(CTF, "collection", "0x" + "00" * 32, condition, 1 << i)
        if int(read(CTF, "position", collateral, collection), 16) != int(token):
            raise ValueError("on-chain outcome token mismatch")
    if int(read(CTF, "denominator", condition), 16) != sum(proof["payouts"]):
        raise ValueError("on-chain payout denominator mismatch")
    if [int(read(CTF, "numerator", condition, i), 16) for i in range(2)] != proof["payouts"]:
        raise ValueError("on-chain payout vector mismatch")
    if any(r.get("block_hash") != bundle["finalized"]["hash"] for r in bundle["state"]):
        raise ValueError("state not bound to finalized canonical header")
    proof.update(
        {
            "market_id": str(g["id"]),
            "event_id": str(market["event_id"]),
            "token_ids": tokens,
            "question_id": g["questionID"],
            "rules_sha256": f["rules_sha256"],
            "collateral": collateral,
            "forecast_sha256": hashlib.sha256(canonical(f)).hexdigest(),
            "oracle": oracle,
            "native_payout_verified": True,
            "research_only": True,
            "trading_authority": False,
            "certification_authority": False,
            "conditional_forecast": not f.get("unconditional_contract_probability", False),
        }
    )
    return proof


class NativeResearchClient(ReadOnlySettlementClient):
    """Extends existing bounded evidence capture with allowlisted eth_call only."""

    def __init__(self, directory, **kwargs):
        super().__init__(directory, **kwargs)
        if shutil.disk_usage(self.directory).free < 100 * 1024**3 + self.max_bytes:
            self.client.close()
            raise ValueError("protected 100 GiB filesystem reserve")

    def call(self, target, name, block_hash, *args):
        target, data = call_key(target, name, *args)
        if target not in (CTF, NEG_RISK) or (target == NEG_RISK and name != "wrapped_collateral"):
            raise ValueError("unreviewed read-only contract call")
        if not HEX32.fullmatch(block_hash) or self.requests >= self.max_requests:
            raise ValueError("bounded canonical block required")
        self.requests += 1
        body = {
            "jsonrpc": "2.0",
            "id": self.requests,
            "method": "eth_call",
            "params": [{"to": target, "data": data}, {"blockHash": block_hash, "requireCanonical": True}],
        }
        raw = bytearray()
        with self.client.stream("POST", "https://polygon-bor-rpc.publicnode.com", json=body) as response:
            for part in response.iter_bytes():
                self.bytes += len(part)
                if self.bytes > self.max_bytes or len(raw) + len(part) > 1024 * 1024:
                    raise ValueError("response byte budget exhausted")
                raw.extend(part)
            digest = hashlib.sha256(raw).hexdigest()
            path = f"raw/{digest}.json"
            (self.directory / path).write_bytes(raw)
            self.manifest.append(
                {
                    "url": "https://polygon-bor-rpc.publicnode.com",
                    "method": "POST",
                    "rpc_method": "eth_call",
                    "request": body,
                    "response_sha256": digest,
                    "response_path": path,
                    "bytes": len(raw),
                    "status": response.status_code,
                    "received_at": datetime.now(UTC).isoformat(),
                }
            )
            self.save_manifest()
            response.raise_for_status()
        result = json.loads(raw)
        if (
            result.get("id") != self.requests
            or "error" in result
            or not HEX32.fullmatch(result.get("result", ""))
        ):
            raise ValueError("invalid contract read response")
        return {"to": target, "data": data, "result": result["result"], "block_hash": block_hash}

    def native_get(self, url):
        if (
            not re.fullmatch(
                r"https://gamma-api\.polymarket\.com/(markets|events)/[0-9]+|https://clob\.polymarket\.com/markets-by-token/[0-9]+",
                url,
            )
            or self.requests >= self.max_requests
        ):
            raise ValueError("unreviewed official source")
        self.requests += 1
        raw = bytearray()
        with self.client.stream("GET", url) as response:
            for part in response.iter_bytes():
                self.bytes += len(part)
                if self.bytes > self.max_bytes or len(raw) + len(part) > 2 * 1024 * 1024:
                    raise ValueError("response byte budget exhausted")
                raw.extend(part)
            digest = hashlib.sha256(raw).hexdigest()
            path = f"raw/{digest}.json"
            (self.directory / path).write_bytes(raw)
            self.manifest.append(
                {
                    "url": url,
                    "method": "GET",
                    "response_sha256": digest,
                    "response_path": path,
                    "bytes": len(raw),
                    "status": response.status_code,
                    "received_at": datetime.now(UTC).isoformat(),
                }
            )
            self.save_manifest()
            response.raise_for_status()
        return json.loads(raw)

    def acquire_bound(self, forecast, gamma, clob, log):
        gamma = self.native_get(f"https://gamma-api.polymarket.com/markets/{forecast['market_id']}")
        clob = self.native_get(f"https://clob.polymarket.com/markets-by-token/{forecast['token_id']}")
        parent = self.native_get(f"https://gamma-api.polymarket.com/events/{forecast['market']['event_id']}")
        if self.request("eth_chainId", []) != "0x89":
            raise ValueError("wrong chain")
        block_hash = log["blockHash"]
        bundle = {
            "forecast": forecast,
            "gamma": gamma,
            "clob": clob,
            "parent_event": parent,
            "log": log,
            "receipt": self.request("eth_getTransactionReceipt", [log["transactionHash"]]),
            "block": self.request("eth_getBlockByHash", [block_hash, False]),
            "canonical_block": self.request("eth_getBlockByNumber", [log["blockNumber"], False]),
            "finalized": self.request("eth_getBlockByNumber", ["finalized", False]),
            "state": [],
        }
        block_hash = bundle["finalized"]["hash"]
        state = bundle["state"]
        condition, question = gamma["conditionId"], gamma["questionID"]
        state.append(self.call(CTF, "condition", block_hash, NEG_RISK, question, 2))
        state.append(self.call(NEG_RISK, "wrapped_collateral", block_hash))
        collateral = "0x" + state[-1]["result"][-40:]
        for i in range(2):
            state.append(self.call(CTF, "collection", block_hash, "0x" + "00" * 32, condition, 1 << i))
            state.append(self.call(CTF, "position", block_hash, collateral, state[-1]["result"]))
        state.append(self.call(CTF, "denominator", block_hash, condition))
        for i in range(2):
            state.append(self.call(CTF, "numerator", block_hash, condition, i))
        bundle["available_at"] = datetime.now(UTC).isoformat()
        # Save even failed acquisitions; verification must never discard failure evidence.
        (self.directory / "bundle.json").write_bytes(canonical(bundle))
        proof = verify_native_bundle(bundle)
        (self.directory / "proof.json").write_bytes(canonical(proof))
        return proof


def replay_native_directory(directory):
    """Validate raw RPC hashes, exact eth_call requests and receipt inputs offline."""
    directory = Path(directory)
    bundle = json.loads((directory / "bundle.json").read_bytes())
    manifest = json.loads((directory / "manifest.json").read_bytes())
    calls, results, native = {}, [], {}
    for entry in manifest["responses"]:
        path = directory / entry["response_path"]
        if path.parent != directory / "raw":
            raise ValueError("unsafe evidence path")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["response_sha256"]:
            raise ValueError("RPC evidence hash mismatch")
        result = json.loads(raw)
        if entry.get("status") != 200:
            raise ValueError("unsuccessful evidence HTTP response")
        if entry["method"] == "GET":
            native[entry["url"]] = result
            continue
        if result.get("id") != entry["request"]["id"] or "error" in result:
            raise ValueError("unsuccessful evidence response")
        method, params = entry["request"]["method"], entry["request"]["params"]
        results.append((method, params, result["result"]))
        if method == "eth_call":
            calls[(params[0]["to"], params[0]["data"], params[1]["blockHash"])] = result["result"]
    for key, url in (
        ("gamma", f"https://gamma-api.polymarket.com/markets/{bundle['forecast']['market_id']}"),
        ("clob", f"https://clob.polymarket.com/markets-by-token/{bundle['forecast']['token_id']}"),
        (
            "parent_event",
            f"https://gamma-api.polymarket.com/events/{bundle['forecast']['market']['event_id']}",
        ),
    ):
        if native.get(url) != bundle[key]:
            raise ValueError("native source evidence mismatch")
    for row in bundle["state"]:
        if calls[(row["to"], row["data"], row["block_hash"])] != row["result"]:
            raise ValueError("state evidence mismatch")
    for field, method, params in (
        ("receipt", "eth_getTransactionReceipt", [bundle["log"]["transactionHash"]]),
        ("block", "eth_getBlockByHash", [bundle["log"]["blockHash"], False]),
        ("canonical_block", "eth_getBlockByNumber", [bundle["log"]["blockNumber"], False]),
        ("finalized", "eth_getBlockByNumber", ["finalized", False]),
    ):
        if (method, params, bundle[field]) not in results:
            raise ValueError("inclusion evidence mismatch")
    return verify_native_bundle(bundle)


def acquire_native_research(forecast, directory, *, block_start, block_end):
    """Bounded authentic log search; no Data API tx-as-resolution assumption.

    The caller must select an evidence-backed time bracket, not scan the chain.
    No log, ambiguous logs or unavailable archive/state remain explicit blockers.
    """
    if (
        type(block_start) is not int
        or type(block_end) is not int
        or not 0 <= block_end - block_start <= 5000
        or block_start < 0
    ):
        raise ValueError("bounded resolution search required")
    from neraium_poly.research.settlement_evidence import CONDITION_RESOLUTION

    client = NativeResearchClient(directory, max_requests=30, max_bytes=8 * 1024**2)
    try:
        gamma = client.native_get(f"https://gamma-api.polymarket.com/markets/{forecast['market_id']}")
        logs = client.request(
            "eth_getLogs",
            [
                {
                    "address": CTF,
                    "topics": [CONDITION_RESOLUTION, gamma["conditionId"]],
                    "fromBlock": hex(block_start),
                    "toBlock": hex(block_end),
                }
            ],
        )
        if not isinstance(logs, list) or len(logs) != 1:
            raise ValueError("unique native resolution log unavailable in reviewed bracket")
        return client.acquire_bound(forecast, gamma, None, logs[0])
    finally:
        client.client.close()
