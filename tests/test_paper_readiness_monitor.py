import pytest
from neraium_poly.ops import readiness_monitor as monitor


@pytest.mark.parametrize(
    ("shadow", "direct", "sampler", "expected"),
    [
        (False, "ok", "withheld", True),
        (False, "unavailable", "fresh", False),
        (True, "not_observed", "fresh", True),
        (True, "ok", "withheld", False),
        (True, "ok", None, False),
    ],
)
def test_readiness_uses_only_the_mode_active_feed(shadow, direct, sampler, expected):
    health = {
        "public_feed": {"status": direct},
        "research_reference": {"status": sampler} if sampler else None,
    }
    assert monitor.active_feed(health, shadow_enabled=shadow) is expected


def test_resumed_readiness_retains_original_deadline(tmp_path, monkeypatch):
    path = tmp_path / "restart.json"
    boot = tmp_path / "boot"
    boot.write_text("original-boot")
    clock = [5_000_000_000]
    monkeypatch.setattr(monitor, "_BOOT_ID", boot)
    monkeypatch.setattr(monitor, "monotonic_ns", lambda: clock[0])
    anchor = monitor.RestartAnchor.record(
        path, source="candidate", shadow_enabled=True, prior_pid="101", reference_pid="102"
    )
    kwargs = {"clock": lambda: clock[0], "pause": lambda delay: pytest.fail(f"unexpected wait: {delay}")}
    clock[0] += 850_000_000_000

    def interrupt(_):
        raise InterruptedError("observer lost")

    with pytest.raises(InterruptedError):
        monitor.wait_for_paper_readiness(anchor, interrupt, **kwargs)
    with pytest.raises(FileExistsError):
        monitor.RestartAnchor.record(
            path, source="candidate", shadow_enabled=True, prior_pid="101", reference_pid="102"
        )

    recovered = monitor.RestartAnchor.load(path)
    assert recovered == anchor
    clock[0] = anchor.started_ns + 899_000_000_000
    outcome = monitor.wait_for_paper_readiness(recovered, lambda _: {"accepted": True}, **kwargs)
    assert outcome == {"accepted": True, "readiness_seconds": 899.0, "margin_seconds": 1.0}

    def verification_crosses_deadline(_):
        clock[0] = anchor.started_ns + 900_001_000_000
        return {"accepted": True}

    with pytest.raises(TimeoutError, match="original 900-second"):
        monitor.wait_for_paper_readiness(recovered, verification_crosses_deadline, **kwargs)
    with pytest.raises(TimeoutError, match="original 900-second"):
        monitor.wait_for_paper_readiness(
            monitor.RestartAnchor.load(path), lambda _: pytest.fail("poll after deadline"), **kwargs
        )

    boot.write_text("rebooted")
    with pytest.raises(ValueError, match="different boot"):
        monitor.RestartAnchor.load(path)
