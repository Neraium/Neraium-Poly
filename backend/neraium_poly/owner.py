"""Owner approval is a detached Ed25519 signature, never an agent attestation.

The owner provisions the trusted public key independently. This module only
verifies signatures; it never creates a signing key or signs an approval.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

CONTEXT = "Neraium-Poly Phase8 owner-approved PAPER activation v1"


def canonical(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def owner_payload(report: dict, manifest: dict, request_id: str, created_at: datetime) -> dict:
    if created_at.tzinfo is None:
        raise ValueError("timezone required")
    return {
        "context": CONTEXT,
        "request_id": request_id,
        "report_id": report["id"],
        "dataset_hash": report["dataset_hash"],
        "manifest_hash": report["manifest_hash"],
        "model_id": report["model_id"],
        "mode": "paper",
        "live_trading_enabled": False,
        "created_at": created_at.astimezone(UTC).isoformat(),
        "expires_at": manifest["expires_at"],
        "report_sha256": hashlib.sha256(canonical(report)).hexdigest(),
    }


def verify_signature(payload: dict, signature: bytes, public_key: Path | None, now: datetime) -> str:
    if public_key is None or not public_key.is_file():
        raise ValueError("Owner must provision a trusted Ed25519 public key before approval")
    if len(signature) != 64 or len(public_key.read_bytes()) > 16384:
        raise ValueError("Invalid owner signature or public key")
    if now.tzinfo is None:
        raise ValueError("timezone required")
    created = datetime.fromisoformat(payload["created_at"])
    expires = datetime.fromisoformat(payload["expires_at"])
    if created.tzinfo is None or expires.tzinfo is None or not created <= now < expires:
        raise ValueError("Owner approval request expired or unavailable")
    if (
        payload.get("context") != CONTEXT
        or payload.get("mode") != "paper"
        or payload.get("live_trading_enabled") is not False
    ):
        raise ValueError("Owner approval context mismatch")
    key = public_key.resolve()
    try:
        details = subprocess.run(
            ["openssl", "pkey", "-pubin", "-in", str(key), "-text", "-noout"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        if details.returncode or b"ED25519" not in details.stdout:
            raise ValueError("Owner public key must be Ed25519")
        with tempfile.TemporaryDirectory(prefix="poly-owner-verify-") as directory:
            message = Path(directory) / "request.json"
            sig = Path(directory) / "signature.bin"
            message.write_bytes(canonical(payload))
            sig.write_bytes(signature)
            result = subprocess.run(
                [
                    "openssl",
                    "pkeyutl",
                    "-verify",
                    "-pubin",
                    "-inkey",
                    str(key),
                    "-rawin",
                    "-in",
                    str(message),
                    "-sigfile",
                    str(sig),
                ],
                capture_output=True,
                timeout=5,
                check=False,
            )
            if result.returncode:
                raise ValueError("Explicit owner signature verification failed")
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("Owner signature verification unavailable") from error
    return hashlib.sha256(key.read_bytes()).hexdigest()
