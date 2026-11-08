"""Bounded actual public fee acquisition with immutable raw-response provenance."""

import contextvars
import hashlib
import json
from datetime import UTC, datetime

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

    async def _get(self, base, path, params=None):
        result = await super()._get(base, path, params)
        if not isinstance(result, dict):
            raise TypeError("fee response must be an object")
        encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded) > 512 * 1024 or not self.can_write():
            raise ValueError("fee evidence budget exhausted")
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        received = datetime.now(UTC)
        rid = hashlib.sha256((base + path + digest).encode()).hexdigest()
        existing = self.store.get(rid)
        if existing:
            kind, payload, sha = existing
            if kind != "PublicFeeResponse" or hashlib.sha256(payload.encode()).hexdigest() != sha:
                raise ValueError("corrupt fee evidence")
        else:
            now = received
            self.store.append(
                PublicFeeResponse(
                    id=rid,
                    timestamp=now,
                    available_at=now,
                    source=base,
                    url=base + path,
                    content_sha256=digest,
                    payload=result,
                )
            )
        # Content-addressed responses remain deduplicated. Each real retrieval
        # additionally receives a causal receipt; reusing old content must not
        # silently erase the latest availability evidence.
        receipt = PublicFeeReceipt(id=hashlib.sha256((rid+received.isoformat()).encode()).hexdigest(),
            timestamp=received, available_at=received, source=base,
            raw_response_id=rid, content_sha256=digest, url=base+path)
        self.store.append(receipt)
        refs = _refs.get()
        if refs is not None:
            refs.append(rid)
        receipts = _receipts.get()
        if receipts is not None:
            receipts.append(receipt.id)
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
            if not self.can_write():
                return None
            self.store.append(observation)
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
