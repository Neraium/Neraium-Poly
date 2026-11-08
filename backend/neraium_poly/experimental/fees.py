"""Bounded actual public fee acquisition with immutable raw-response provenance."""

import asyncio
import contextvars
import hashlib
import json
from datetime import UTC, datetime
from threading import RLock

from pydantic import Field

from neraium_poly.contracts import Record
from neraium_poly.data.connectivity import ConcurrentPublicAdapter

_refs = contextvars.ContextVar("fee_response_refs", default=None)
_receipts = contextvars.ContextVar("fee_response_receipts", default=None)


class PublicFeeResponse(Record):
    url: str
    content_sha256: str
    hash_basis: str = "canonical_json_payload_not_HTTP_bytes"
    payload: dict


class PublicFeeReceipt(Record):
    raw_response_id: str
    content_sha256: str
    url: str


class FeeObservation(Record):
    token_id: str
    fee_rate: float = Field(ge=0, le=1)
    raw_response_ids: tuple[str, ...]
    retrieval_ids: tuple[str, ...] = ()
    assumption: str = "Current official exponent1 global notional fee bound; refreshed by receipt-time TTL"


class AuditedFeeAdapter(ConcurrentPublicAdapter):
    def __init__(self, store, can_write, **kwargs):
        super().__init__(rate=4, concurrency=2, retries=1, **kwargs)
        self.store, self.can_write = store, can_write
        self._audit_slots = asyncio.Semaphore(2)
        self._audit_lock = RLock()
        self._response_order = asyncio.Lock()
        self._closing = False
        self._audit_workers = set()

    async def _audit(self, function, *args):
        if self._closing:
            raise RuntimeError("fee adapter closing")
        async with self._audit_slots:
            if self._closing:
                raise RuntimeError("fee adapter closing")
            task = asyncio.create_task(asyncio.to_thread(function, *args))
            self._audit_workers.add(task)
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        continue
                    except Exception:  # noqa: BLE001 - consume failure after canceled caller drains worker
                        break
                if task.done() and not task.cancelled():
                    task.exception()
                raise
            finally:
                self._audit_workers.discard(task)

    async def close(self):
        self._closing = True
        drain = asyncio.gather(*tuple(self._audit_workers), return_exceptions=True)
        canceled = False
        while not drain.done():
            try:
                await asyncio.shield(drain)
            except asyncio.CancelledError:
                canceled = True
        await super().close()
        if canceled:
            raise asyncio.CancelledError

    def _record_response(self, base, path, result, encoded, received):
        # Keep get-or-append atomic when concurrent HTTP responses share content.
        with self._audit_lock:
            if not self.can_write():
                raise ValueError("fee evidence budget exhausted")
            digest = hashlib.sha256(encoded.encode()).hexdigest()
            rid = hashlib.sha256((base + path + digest).encode()).hexdigest()
            existing = self.store.get(rid)
            if existing:
                kind, payload, sha = existing
                if kind != "PublicFeeResponse" or hashlib.sha256(payload.encode()).hexdigest() != sha:
                    raise ValueError("corrupt fee evidence")
            else:
                self.store.append(PublicFeeResponse(id=rid,timestamp=received,available_at=received,
                    source=base,url=base+path,content_sha256=digest,payload=result))
            receipt = PublicFeeReceipt(id=hashlib.sha256((rid+received.isoformat()).encode()).hexdigest(),
                timestamp=received,available_at=received,source=base,raw_response_id=rid,content_sha256=digest,url=base+path)
            self.store.append(receipt)
            return rid, receipt.id

    def _record_observation(self, observation):
        with self._audit_lock:
            if not self.can_write():
                return False
            self.store.append(observation)
            return True

    async def _get(self, base, path, params=None):
        if self._closing:
            raise RuntimeError("fee adapter closing")
        result = await super()._get(base, path, params)
        if not isinstance(result, dict):
            raise TypeError("fee response must be an object")
        encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded) > 512 * 1024:
            raise ValueError("fee evidence budget exhausted")
        received = datetime.now(UTC)
        # Preserve HTTP-completion order: an earlier receipt cannot reference a
        # content record first timestamped by a later concurrent response.
        async with self._response_order:
            rid, receipt_id = await self._audit(self._record_response, base, path, result, encoded, received)
        refs = _refs.get()
        if refs is not None:
            refs.append(rid)
        receipts = _receipts.get()
        if receipts is not None:
            receipts.append(receipt_id)
        return result

    async def observed_fee(self, token):
        refs = []
        context = _refs.set(refs)
        receipt_refs = []
        receipt_context = _receipts.set(receipt_refs)
        try:
            model = await self.fee_model(token)
            if model is None or len(refs) < 2:
                return None
            now = datetime.now(UTC)
            observation = FeeObservation(
                timestamp=now,
                available_at=now,
                source="https://clob.polymarket.com",
                token_id=token,
                fee_rate=model.effective_notional_bound(),
                raw_response_ids=tuple(refs),
                retrieval_ids=tuple(receipt_refs),
            )
            if not await self._audit(self._record_observation, observation):
                return None
            return {
                "fee_rate": observation.fee_rate,
                "observed_at": now.isoformat(),
                "source": observation.source,
                "reference": f"/markets-by-token/{token}",
                "raw_response_ids": list(refs),
                "evidence_id": observation.id,
                "retrieval_ids": receipt_refs,
            }
        finally:
            _refs.reset(context)
            _receipts.reset(receipt_context)


def merge_fee_observations(*sources, now):
    """Keep the highest valid observed cost bound; break ties by latest receipt.

    A local cache must never hide a fresher, higher producer observation.
    This is conservative cost selection, not an assertion that fees stay fixed.
    """
    from neraium_poly.experimental.account import verified_fee_rate

    result = {}
    for values in sources:
        for token, raw in values.items():
            rate = verified_fee_rate(raw, now)
            if rate is None:
                continue
            prior = result.get(token)
            if prior is None or (rate, raw["observed_at"]) > (float(prior["fee_rate"]), prior["observed_at"]):
                result[token] = raw
    return result
