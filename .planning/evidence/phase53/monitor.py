"""Arm or resume a read-only experimental readiness observer. Never restarts a unit."""

import argparse
import json
import shutil
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phase52"))
from rollout import BASE, FLOOR, PAPER, UNIT, attest, continuity, flags, get, stamp, state, system

from neraium_poly.ops.readiness_monitor import RestartAnchor, active_feed, wait_for_paper_readiness


def run(args):
    if args.arm:
        experimental = system(UNIT)
        reference = system(PAPER)
        if experimental["ActiveState"] != "active" or reference["ActiveState"] != "active":
            raise ValueError("existing services are not active")
        RestartAnchor.record(
            args.anchor,
            source=args.arm,
            shadow_enabled=args.shadow,
            prior_pid=experimental["MainPID"],
            reference_pid=reference["MainPID"],
        )
        return
    baseline = json.loads(args.preflight.read_text())["state"]
    anchor = RestartAnchor.load(args.anchor)
    logs = args.anchor.with_name(args.anchor.name + ".polls.jsonl")

    with httpx.Client(timeout=3, trust_env=False) as client:

        def poll(armed):
            assert shutil.disk_usage(BASE).free > FLOOR
            assert system(PAPER)["MainPID"] == armed.reference_pid
            experimental = system(UNIT)
            assert experimental["ActiveState"] != "failed" and experimental["NRestarts"] == "0"
            if experimental["MainPID"] in (armed.prior_pid, "0"):
                return None
            env = flags(experimental["MainPID"])
            assert env["PAPER_TRADING"] == "true" and env["LIVE_TRADING_ENABLED"] == "false"
            assert env["NERAIUM_DEPLOYED_SOURCE"] == armed.source
            assert env["NERAIUM_SHADOW_RESEARCH"] == str(armed.shadow_enabled).lower()
            row = {"at": stamp(), "main_pid": experimental["MainPID"]}
            try:
                health = get(client, 18743, "health")
                row.update(
                    status=health["status"],
                    active_feed_ready=active_feed(health, shadow_enabled=armed.shadow_enabled),
                )
                if row["status"] != "ok" or not row["active_feed_ready"]:
                    return None
                assert health["paper_trading"] and not health["live_trading_enabled"]
                shadow = get(client, 18743, "shadow-research")
                assert shadow["trading_authority"] is False and shadow.get("actual_account_access") in (
                    None,
                    False,
                )
                if armed.shadow_enabled:
                    if not (shadow.get("phase45_explorer") and shadow.get("reference_feed")):
                        return None
                    assert shadow["actual_account_access"] is False
                else:
                    assert shadow["status"] == "withheld"
                reference = get(client, 18742, "health")
                assert reference["paper_trading"] and not reference["live_trading_enabled"]
                if reference["status"] != "ok":
                    return None
                verified = attest(UNIT, armed.source, armed.shadow_enabled)
                assert verified["service"]["MainPID"] == experimental["MainPID"]
                continuity(baseline, state())
                return {
                    "source": armed.source,
                    "shadow_enabled": armed.shadow_enabled,
                    "main_pid": experimental["MainPID"],
                    "reference_pid": armed.reference_pid,
                }
            except httpx.HTTPError as error:
                row["http_error"] = type(error).__name__
                return None
            finally:
                with logs.open("a") as stream:
                    stream.write(json.dumps(row) + "\n")

        print(json.dumps(wait_for_paper_readiness(anchor, poll), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("anchor", type=Path)
    parser.add_argument("--arm", metavar="SOURCE_SHA")
    parser.add_argument("--shadow", action="store_true")
    parser.add_argument("--preflight", type=Path)
    args = parser.parse_args()
    if not args.arm and (not args.preflight or args.shadow):
        parser.error("resume uses a saved mode and requires the original preflight")
    run(args)
