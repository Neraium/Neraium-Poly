# Reproducible multi-domain observation studies

`run_domain_research(output, workers=2, capture_root=..., baseline_frame=...)`
executes two independent, bounded CPU studies against frozen authentic captures.
It records exact file/response/payload hashes, source availability, actual worker
PIDs/intervals/RSS/CPU time and output hashes. All numerical study results exclude
worker timing, permitting byte-identical replay. There is no network access in
these analyses and no new forecast, order, outcome or qualification authority.

The discovery study replays all15 original Gamma response objects, rebuilds339
candidate classifications and the same category-aware selected200. It compares
those IDs with the actual cached200-market paper universe. In this capture,
169selected IDs are new to the cached universe, not new WebSocket subscriptions.
Source rules, classification bases, missing liquidity/source fields and candidate
categories are explicit. Metadata does not establish executable spread/depth.
The bounded selection is not claimed as the whole Polymarket universe.

The source study independently verifies original raw bytes and canonical evidence
hashes, first-observed availability, completed contiguous Binance candles, exact
NOAA station observations and official Fed calendar context. It replays1000closed
crypto minutes and36qualified RKSI observations. Economic vintage qualification
remains0. A current calendar is not a historical first-release vintage; completed
underlying candles are not independent resolved prediction-market events.

These are observation/qualification experiments, **not forecasting backtests**.
There is no training/validation/held-out event cohort or independently resolved
probability forecast in these captures. Candle feature-window bounds are recorded,
but Brier, log loss, calibration, confidence intervals, superiority and profitability
remain null. The preserved NFL research forecasts belong to their existing journal;
they are not generated or counted by these experiments. Hypotheses of independent
forecasting skill remain untested.

## Actual concurrent processing

First run: **2026-11-06 09:30:53UTC**, workerPIDs**3124977/3124980**.
The discovery task consumed0.142CPU seconds, the independent source replay0.012CPU
seconds; their measured intervals overlap. Peak RSS was79,652/79,396KiB, with one
numerical thread per worker. A second bounded two-worker run was launched after
the first completed. Both discovery and source report files were **byte-identical**.
Four CPU worker launches are not four simultaneously active workers.

Source and output artifacts reside under `/dev/shm/neraium-poly-phase14/` and are
explicitly **volatile tmpfs**. They are not a durable research dataset, and their
existence does not bypass the8GiB persistent-storage floor. The original cached
baseline frame is a separately hashed persistent capture. Small summaries and
reproducibility manifests are committed; original source responses are not.

## Safety and invocation

Inputs are bounded to32MiB aggregate, individual paths reject aliases/hardlinks,
source bodies and timestamps are replayed, and output must be a new directory.
A persistent output path below8GiB free rejects. RAM output is labeled volatile;
no original is overwritten or deleted. If any study fails, no success manifest is
published. Worker counts are restricted to1or2 and actual overlap is measured;
a serial job cannot claim concurrency.

```python
from pathlib import Path
from neraium_poly.research.phase14.framework import run_domain_research

# Call from a script protected by if __name__ == "__main__" for spawned workers.
manifest = run_domain_research(
    Path("/dev/shm/neraium-poly-phase14/NEW_RUN"), workers=2,
    capture_root=Path("/dev/shm/neraium-poly-phase14"),
    baseline_frame=Path("data/phase14-operations/frame-baseline.json"),
)
```

Six focused controlled tests cover worker limits, storage refusal, input hashes,
size/alias rejection, nested source-byte integrity, failed-study output and truthful
serial/volatile manifests. Controlled fixture results are never research evidence.
