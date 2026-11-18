"""Read-only paper readiness checks on a durable same-boot restart clock."""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from time import monotonic_ns, sleep

GATE_SECONDS = 900
_BOOT_ID = Path("/proc/sys/kernel/random/boot_id")


def active_feed(health, *, shadow_enabled):
    if shadow_enabled:
        return (health.get("research_reference") or {}).get("status") == "fresh"
    return (health.get("public_feed") or {}).get("status") == "ok"


@dataclass(frozen=True)
class RestartAnchor:
    source: str
    shadow_enabled: bool
    prior_pid: str
    reference_pid: str
    boot_id: str
    started_ns: int

    @classmethod
    def record(cls, path, *, source, shadow_enabled, prior_pid, reference_pid):
        """Record immediately before issuing the authorized restart."""
        anchor = cls(
            source, shadow_enabled, prior_pid, reference_pid, _BOOT_ID.read_text().strip(), monotonic_ns()
        )
        # Never overwrite an armed deadline. A torn anchor fails closed on read.
        with Path(path).open("x") as stream:
            json.dump(asdict(anchor), stream)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        parent = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
        return anchor

    @classmethod
    def load(cls, path):
        anchor = cls(**json.loads(Path(path).read_text()))
        if anchor.boot_id != _BOOT_ID.read_text().strip():
            raise ValueError("restart anchor belongs to a different boot")
        if type(anchor.started_ns) is not int or not 0 < anchor.started_ns <= monotonic_ns():
            raise ValueError("invalid original restart clock")
        if type(anchor.shadow_enabled) is not bool:
            raise ValueError("invalid shadow mode")
        return anchor

    def elapsed(self, now_ns):
        return (now_ns - self.started_ns) / 1_000_000_000


def wait_for_paper_readiness(anchor, poll, *, clock=monotonic_ns, pause=sleep):
    """A resumed observer polls against the same start; postchecks use that gate."""
    while 0 <= anchor.elapsed(clock()) < GATE_SECONDS:
        evidence = poll(anchor)
        elapsed = anchor.elapsed(clock())
        if evidence is not None and elapsed <= GATE_SECONDS:
            return {**evidence, "readiness_seconds": elapsed, "margin_seconds": GATE_SECONDS - elapsed}
        if elapsed < GATE_SECONDS:
            pause(min(5, GATE_SECONDS - elapsed))
    raise TimeoutError("paper readiness missed original 900-second gate")
