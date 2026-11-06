"""Controlled stop events; never alters the persistent experimental latch."""

import hashlib
import json

import pytest
from neraium_poly.risk import RiskEngine


def test_stop_context_atomic_and_old_audit_preserved(now):
    r = RiskEngine()
    try:
        r.kill_switch(True, now=now)
        first = r.audit()[-1]
        r.kill_switch(True, now=now, reason="controlled_storage_floor", actor="CONTROLLED guard",
                      evidence={"free_bytes": 123, "fixture": True})
        event = r.audit()[-1]
        assert r.audit()[-2] == first
        payload = json.loads(event["payload"])
        assert payload["actor"] == "CONTROLLED guard"
        encoded = json.dumps(payload["evidence"], sort_keys=True, separators=(",", ":"))
        assert payload["evidence_sha256"] == hashlib.sha256(encoded.encode()).hexdigest()
        assert r.snapshot(now=now)["kill_switch"] is True
        r.kill_switch(True, now=now, reason="", actor=None, evidence={"bad": float("nan")})
        assert r.snapshot(now=now)["kill_switch"] is True
        assert json.loads(r.audit()[-1]["payload"])["reason"] == "stop_context_invalid"
        assert r.snapshot(now=now)["cash"] == 500
        with pytest.raises(ValueError):
            r.kill_switch(False, now=now, reason="", actor="unknown")
        assert r.snapshot(now=now)["kill_switch"] is True
    finally:
        r.close()
