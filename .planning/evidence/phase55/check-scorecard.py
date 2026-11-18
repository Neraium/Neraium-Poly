"""Isolated smoke checks. Fixture observations are synthetic and never scored as evidence."""

import gzip
import importlib.util
import json
import tempfile
from datetime import timedelta
from pathlib import Path

from neraium_poly.research.phase14.relationships import digest

here = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("phase55_prospective", here / "prospective.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
start = module.at("2026-11-01T00:00:00+00:00")
end = start + timedelta(minutes=2)
module.LOCK = {**module.LOCK, "start": start.isoformat(), "end": end.isoformat()}
decision = start + timedelta(seconds=1)
raw = {
    "id": "phase55-synthetic-fixture",
    "timestamp": start.isoformat(),
    "available_at": start.isoformat(),
    "mode": "real_market_data",
    "source": "neraium-poly/public-market-frame/v1",
    "producer_health": {"status": "ok", "live_trading_enabled": False},
    "markets": [],
    "books": [],
}
archive = Path("/home/ubuntu/Neraium-Poly/data/experimental-paper")
with tempfile.TemporaryDirectory(prefix="phase55-scorecard-") as tmp:
    tmp = Path(tmp)
    tape = tmp / "fixture.gz"
    with gzip.open(tape, "wt") as f:
        for when in (decision, decision + timedelta(seconds=1), decision + timedelta(seconds=25)):
            f.write(json.dumps({"received_at": when.isoformat(), "frame": raw, "sha256": digest(raw)}) + "\n")
    module.run(tape, archive, tmp / "out")
    result = json.loads((tmp / "out/scorecard.json").read_text())
    assert result["funnel"]["stale_identity_or_producer_veto"] == 1
    assert result["funnel"]["repeated_frame"] == 1
    assert result["funnel"]["evaluated_frames"] == 1
    assert all(not profile["open_positions"] for profile in result["explorer"]["profiles"].values())
    assert result["baseline_net_dollars"] == 0
    with gzip.open(tape, "wt") as f:
        f.write(json.dumps({"received_at": end.isoformat(), "frame": raw, "sha256": digest(raw)}) + "\n")
    try:
        module.run(tape, archive, tmp / "reject")
    except ValueError as error:
        assert "out-of-window" in str(error)
    else:
        raise AssertionError("endpoint boundary accepted")
print("Offline controller smoke passed: fresh, repeated, stale and endpoint guards; no trades.")
