"""Bounded public resolution acquisition with replayable native and chain corroboration.

No transaction method, account mutation, payout inference or settlement fallback.
"""

import asyncio
import hashlib
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

import httpx

from neraium_poly.contracts import MarketSnapshot
from neraium_poly.data.operational import OperationalPolymarketAdapter, SettlementObservation
from neraium_poly.data.polymarket import CLOB, DATA, GAMMA
from neraium_poly.research.phase12.contracts import (
    EventForecast,
    SettlementProofReference,
    VerifiedEventOutcome,
)
from neraium_poly.research.qualification import _load_proofs
from neraium_poly.research.settlement_evidence import HEX32, ReadOnlySettlementClient, canonical

NATIVE_BYTES = 2 * 1024 * 1024
RPC_BYTES = 5 * 1024 * 1024
ATTEMPT_BYTES = 8 * 1024 * 1024
TOTAL_BYTES = 32 * 1024 * 1024


def _sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()



def _forecast_reference(value):
    # Only an explicitly typed proof reference may omit binary forecast fields.
    # Full revalidation also rejects model_copy bypasses of shared contracts.
    if isinstance(value, SettlementProofReference):
        return SettlementProofReference.model_validate(value.model_dump())
    return EventForecast.model_validate(value.model_dump() if isinstance(value, EventForecast) else value)

def _inputs(forecast, market):
    return (
        len(market.resolution_rules.encode()) <= 65536
        and len(market.resolution_source) <= 2048
        and all(
            len(v) <= 256 for v in (forecast.id, forecast.event_id, forecast.market_id, forecast.token_id)
        )
        and forecast.event_id == market.event_id
        and forecast.market_id == market.market_id
        and forecast.token_id == market.token_id
        and market.exchange == "polymarket"
        and bool(market.resolution_rules and market.resolution_source)
        and hashlib.sha256(market.resolution_rules.encode()).hexdigest() == forecast.resolution_rules_sha256
        and market.available_at <= forecast.evidence_cutoff
    )


class _ArchivedNative(OperationalPolymarketAdapter):
    def __init__(self, directory, *, client=None, clock=None):
        super().__init__(
            client=client, retries=1, clock=clock or (lambda: datetime.now(UTC)), min_interval=0.25
        )
        self.directory = Path(directory)
        self.directory.mkdir()
        (self.directory / "raw").mkdir()
        self.responses = []
        self.received_bytes = 0

    async def _get(self, base, path, params=None):
        if base not in (GAMMA, CLOB, DATA) or len(self.responses) >= 3:
            raise ValueError("bounded native resolution sources only")
        await self.sleep(self.min_interval)
        async with self.client.stream("GET", base + path, params=params) as response:
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                self.received_bytes += len(chunk)
                if self.received_bytes > NATIVE_BYTES:
                    raise ValueError("native resolution byte budget exceeded")
                raw.extend(chunk)
            digest = hashlib.sha256(raw).hexdigest()
            file = "raw/" + digest + ".json"
            (self.directory / file).write_bytes(raw)
            self.responses.append(
                {
                    "base": base,
                    "path": path,
                    "params": params,
                    "status": response.status_code,
                    "received_at": self.clock().isoformat(),
                    "response_path": file,
                    "bytes": len(raw),
                    "sha256": digest,
                }
            )
            response.raise_for_status()
            parsed = json.loads(raw)
            if base == GAMMA and (
                parsed.get("version") not in (None, "v1", "legacy")
                or parsed.get("negRisk") not in (None, False)
            ):
                raise ValueError("unsupported v2 or negative-risk settlement")
            return parsed

    def save(self, market, native):
        manifest = {
            "schema_version": "1.0",
            "market": market.model_dump(mode="json"),
            "native_observation": native.model_dump(mode="json") if native else None,
            "responses": self.responses,
            "response_bytes": self.received_bytes,
        }
        encoded = canonical(manifest)
        if len(encoded) > 512 * 1024:
            raise ValueError("native manifest budget exceeded")
        (self.directory / "manifest.json").write_bytes(encoded)
        return manifest


class _ReplayNative(OperationalPolymarketAdapter):
    def __init__(self, directory, manifest, native):
        self.directory, self.manifest, self.native = directory, manifest, native
        self.index = 0
        self.operational_errors = []
        self.clock = lambda: native.available_at

    async def _get(self, base, path, params=None):
        if self.index >= len(self.manifest["responses"]):
            raise ValueError("missing native source response")
        item = self.manifest["responses"][self.index]
        self.index += 1
        if (item["base"], item["path"], item["params"]) != (base, path, params) or item["status"] != 200:
            raise ValueError("native source request binding mismatch")
        file = (self.directory / item["response_path"]).resolve()
        if not file.is_relative_to(self.directory.resolve()) or file.is_symlink():
            raise ValueError("native source path escapes evidence")
        if file.stat().st_size > NATIVE_BYTES:
            raise ValueError("native source file budget exceeded")
        raw = file.read_bytes()
        if len(raw) != item["bytes"] or hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("native source content mismatch")
        at = datetime.fromisoformat(item["received_at"])
        if at.tzinfo is None or at > self.native.available_at:
            raise ValueError("native response availability mismatch")
        parsed = json.loads(raw)
        if base == GAMMA and (
            parsed.get("version") not in (None, "v1", "legacy") or parsed.get("negRisk") not in (None, False)
        ):
            raise ValueError("unsupported native settlement variant")
        return parsed


UINT64_HEX = re.compile(r"^0x[0-9a-fA-F]{1,16}$")


class _ForwardSettlementClient(ReadOnlySettlementClient):
    """One binary condition: ambiguous logs never reach the derived proof writer."""

    def request(self, method, params):
        if method == "eth_getTransactionReceipt" and (
            len(params) != 1 or not isinstance(params[0], str) or not HEX32.fullmatch(params[0])
        ):
            raise ValueError("bounded transaction locator required")
        result = super().request(method, params)
        if method == "eth_getLogs":
            if not isinstance(result, list) or len(result) > 1:
                raise ValueError("ambiguous resolution logs for one binary condition")
            for log in result:
                if not isinstance(log, dict) or any(
                    not isinstance(log.get(key), str) or not UINT64_HEX.fullmatch(log[key])
                    for key in ("blockNumber", "logIndex")
                ):
                    raise ValueError("bounded resolution log quantities required")
                if any(
                    not isinstance(log.get(key), str) or not HEX32.fullmatch(log[key])
                    for key in ("transactionHash", "blockHash")
                ):
                    raise ValueError("bounded resolution log hashes required")
        elif method in {
            "eth_getTransactionReceipt",
            "eth_getBlockByHash",
            "eth_getBlockByNumber",
        } and isinstance(result, dict):
            fields = ("blockNumber",) if method == "eth_getTransactionReceipt" else ("number", "timestamp")
            # Finalized headers also provide a timestamp in the actual RPC schema;
            # only number enters proof metadata when querying finality.
            if method == "eth_getBlockByNumber" and params[0] == "finalized":
                fields = ("number",)
            if any(
                not isinstance(result.get(key), str) or not UINT64_HEX.fullmatch(result[key])
                for key in fields
            ):
                raise ValueError("bounded chain header quantities required")
        return result


def _chain_acquire(directory, native, client):
    if not HEX32.fullmatch(native.transaction_hash) or not HEX32.fullmatch(native.condition_id):
        return None
    rpc = _ForwardSettlementClient(
        directory, client=client, max_requests=15, max_bytes=RPC_BYTES, interval=0.25
    )
    try:
        receipt = rpc.request("eth_getTransactionReceipt", [native.transaction_hash])
        if (
            not isinstance(receipt, dict)
            or receipt.get("status") != "0x1"
            or receipt.get("transactionHash") != native.transaction_hash
        ):
            return None
        block = int(receipt["blockNumber"], 16)
        rpc.acquire([native.condition_id], max(0, block - 1), block + 1)
        proofs, _ = _load_proofs(directory)
        return proofs.get(native.condition_id)
    finally:
        rpc.save_manifest()
        rpc.close()


async def acquire_verified_outcome(
    forecast, market, output_new_dir, *, client=None, rpc_client=None, clock=None
):
    """Acquire one future outcome attempt. Unknown, disputed or mismatched data returns None.

    Network native requests are async; bounded chain reads run in a thread. Call
    only for an actual pending forecast whose scheduled event has ended. The
    caller controls cadence; this function does not create a service or trade.
    """
    forecast = _forecast_reference(forecast)
    market = market if isinstance(market, MarketSnapshot) else MarketSnapshot.model_validate(market)
    if not _inputs(forecast, market):
        return None
    output = Path(output_new_dir)
    if output.exists():
        raise ValueError("new resolution evidence directory required")
    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output.parent).free < 8 * 1024**3 + ATTEMPT_BYTES:
        raise ValueError("resolution evidence free-disk floor")
    if sum(p.stat().st_size for p in output.parent.rglob("*") if p.is_file()) + ATTEMPT_BYTES > TOTAL_BYTES:
        raise ValueError("resolution evidence storage budget exhausted")
    output.mkdir()
    adapter = _ArchivedNative(output / "native", client=client, clock=clock)
    try:
        native = await adapter.settlement(market)
        native_manifest = adapter.save(market, native)
        if native is None:
            return None
        proof = await asyncio.to_thread(_chain_acquire, output / "chain", native, rpc_client)
        if (
            proof is None
            or native.outcome_index not in (0, 1)
            or proof["payouts"][native.outcome_index] != native.payout
        ):
            return None
        settled = datetime.fromisoformat(proof["settlement_at"])
        if forecast.timestamp >= min(native.timestamp, settled):
            return None
        verification = {
            "acquisition_subdir": output.name,
            "native_manifest_sha256": _sha(native_manifest),
            "chain_proofs_sha256": hashlib.sha256((output / "chain/proofs.json").read_bytes()).hexdigest(),
            "native_observation": native.model_dump(mode="json"),
            "chain_proof": proof,
            "forecast_id": forecast.id,
            "forecast_sha256": _sha(forecast.model_dump(mode="json")),
            "market_sha256": _sha(market.model_dump(mode="json")),
        }
        at = max(native.available_at, datetime.fromisoformat(proof["available_at"]))
        outcome = VerifiedEventOutcome(
            id=_sha(["collected-event-outcome/v1", verification]),
            timestamp=settled,
            available_at=at,
            source="https://polygon-bor-rpc.publicnode.com",
            event_id=forecast.event_id,
            market_id=forecast.market_id,
            token_id=forecast.token_id,
            payout=int(native.payout),
            resolution_rules_sha256=forecast.resolution_rules_sha256,
            settled_at=settled,
            verification_source="native_final_resolution_plus_finalized_ctf_raw_replay",
            proof_sha256=_sha(verification),
            verification=verification,
        )
        encoded = canonical(outcome.model_dump(mode="json"))
        if len(encoded) > 256 * 1024:
            return None
        (output / "outcome.json").write_bytes(encoded)
        return outcome
    except (ValueError, TypeError, KeyError, httpx.HTTPError, OverflowError):
        return None
    finally:
        await adapter.close()


def verify_collected_outcome(outcome, market, forecast, rootdirectory):
    """Synchronous offline proof callback; use asyncio.to_thread in async callers."""
    try:
        outcome = (
            outcome
            if isinstance(outcome, VerifiedEventOutcome)
            else VerifiedEventOutcome.model_validate(outcome)
        )
        forecast = _forecast_reference(forecast)
        market = market if isinstance(market, MarketSnapshot) else MarketSnapshot.model_validate(market)
        if not _inputs(forecast, market) or outcome.proof_sha256 != _sha(outcome.verification):
            return False
        if (outcome.event_id, outcome.market_id, outcome.token_id) != (
            forecast.event_id,
            forecast.market_id,
            forecast.token_id,
        ):
            return False
        v = outcome.verification
        if (
            v["forecast_id"] != forecast.id
            or v["forecast_sha256"] != _sha(forecast.model_dump(mode="json"))
            or v["market_sha256"] != _sha(market.model_dump(mode="json"))
        ):
            return False
        root = Path(rootdirectory).resolve()
        directory = (root / v["acquisition_subdir"]).resolve()
        if not directory.is_relative_to(root) or directory == root:
            return False
        if sum(p.stat().st_size for p in directory.rglob("*") if p.is_file()) > ATTEMPT_BYTES:
            return False
        if outcome.id != _sha(["collected-event-outcome/v1", v]):
            return False
        native_file = directory / "native/manifest.json"
        if (
            native_file.stat().st_size > NATIVE_BYTES
            or hashlib.sha256(native_file.read_bytes()).hexdigest() != v["native_manifest_sha256"]
        ):
            return False
        manifest = json.loads(native_file.read_bytes())
        if (
            manifest["market"] != market.model_dump(mode="json")
            or manifest["native_observation"] != v["native_observation"]
        ):
            return False
        native = SettlementObservation.model_validate(v["native_observation"])
        replay = _ReplayNative(directory / "native", manifest, native)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            return False  # Async callers must use to_thread, avoiding nested loops.
        replayed = asyncio.run(replay.settlement(market))
        if replayed != native or replay.index != len(manifest["responses"]):
            return False
        proofs, digest = _load_proofs(directory / "chain")
        proof = proofs.get(native.condition_id)
        if proof is None or digest != v["chain_proofs_sha256"] or proof != v["chain_proof"]:
            return False
        settled = datetime.fromisoformat(proof["settlement_at"])
        return (
            forecast.timestamp < min(native.timestamp, settled)
            and outcome.payout == native.payout == proof["payouts"][native.outcome_index]
            and outcome.settled_at == outcome.timestamp == settled
            and outcome.resolution_rules_sha256 == forecast.resolution_rules_sha256
            and outcome.available_at
            == max(native.available_at, datetime.fromisoformat(proof["available_at"]))
        )
    except (ValueError, TypeError, KeyError, OSError, IndexError, RuntimeError, OverflowError):
        return False
