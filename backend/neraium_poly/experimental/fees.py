"""Bounded actual public fee acquisition with immutable raw-response provenance."""

import contextvars
import hashlib
import json
from datetime import UTC, datetime

from pydantic import Field

from neraium_poly.contracts import Record
from neraium_poly.data.connectivity import ConcurrentPublicAdapter

_refs = contextvars.ContextVar("fee_response_refs", default=None)


class PublicFeeResponse(Record):
    url: str
    content_sha256: str
    payload: dict


class FeeObservation(Record):
    token_id: str
    fee_rate: float = Field(ge=0, le=1)
    raw_response_ids: tuple[str, ...]
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
        rid = hashlib.sha256((base + path + digest).encode()).hexdigest()
        existing = self.store.connection.execute(
            "SELECT kind,payload,digest FROM events WHERE id=?", (rid,)
        ).fetchone()
        if existing:
            kind, payload, sha = existing
            if kind != "PublicFeeResponse" or hashlib.sha256(payload.encode()).hexdigest() != sha:
                raise ValueError("corrupt fee evidence")
        else:
            now = datetime.now(UTC)
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
        refs = _refs.get()
        if refs is not None:
            refs.append(rid)
        return result

    async def observed_fee(self, token):
        refs = []
        context = _refs.set(refs)
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
            }
        finally:
            _refs.reset(context)
