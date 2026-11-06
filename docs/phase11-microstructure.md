# Phase 11 market microstructure and execution-cost research

This research reads authentic archived Polymarket observations. It never calls a
broker, risk account, order endpoint or settlement mutator. Its retrospective
quote-capacity scenarios are not operational orders, fills, positions or P/L.

## Dataset identity and reproducibility

Frozen dataset `data/phase11/dataset-v1` was extracted from the experimental
append-only event archive at source insertion high-water **77789**. It includes
**30,000 actual complete-book observations**, reconstructed losslessly from full
books, observed deltas and receipts; source quote row IDs **33487–77771**.

- Dataset SHA-256: `4bca310fb839d1f8a24ddaa334e71147f374bef83f3f8546014ee726f540c95d`.
- Observation bytes: **162,352,233**; artifact budget 512 MiB, free-disk floor 8 GiB.
- Source interval: **2026-11-06 03:34:59.236–04:41:30.222 UTC**.
- Availability interval: **03:35:04.111574–04:41:30.279472 UTC**.
- Coverage: **34 markets / 65 outcome tokens / 20 reported event IDs**.
- Independently reviewed events: **zero**. Repeated observations and related
  outcomes are never counted as independent training or held-out events.
- Metadata is the latest actually available matching record at each observation.
  Fee evidence uses only earlier observed records within the original 300-second
  TTL; **2,549 quotes lack such a fee**, which stays null.
- Every selected source payload digest, referenced original book and public fee
  response is checked. Raw fee payload canonical hashes and availability are
  verified; provenance bindings have their own SHA-256. Loading verifies both
  files, record counts, ordering, source/exchange identity, duplicates and causal
  context. Missing or corrupted provenance rejects the artifact.

```
uv run python -m neraium_poly.research.phase11.dataset \
  --database data/experimental-paper/events.sqlite \
  --output data/phase11/NEW-dataset --limit 30000
```

Reproduce the frozen selection with `--high-water 77789` while retaining the
original source archive. Use a new output directory. Output provenance bindings
may acquire additive fields between research versions; the observation bytes and
source records remain explicitly hashed. Never substitute current quotes or
current metadata for a historical row.

The library entry points are `extract_dataset`, `load_dataset`,
`causal_features`, `execution_scenarios` and
`run_microstructure(observations, manifest)`. The latter returns a versioned
`ExperimentSpec` plus descriptive findings for the root experiment runner.

## Hypothesis and causal features

Fixed exploratory hypothesis: top-five displayed depth imbalance and quote
persistence may precede 60-second bid repricing large enough to overcome costs.
No hyperparameter was selected using these scenarios. This is a descriptive
study rather than a fitted/train/validation/held-out strategy; those split
intervals remain null in its spec. The separate modeling workstream performs
chronological model comparison.

Features include actual spread, top-five share imbalance, depth concentration,
time since observed top-quote change, and mean/volatility of strictly prior bid
changes over at most 20 observations. Future quotes cannot change prior feature
rows. Source/receipt freshness, complete two-sided liquidity, source ordering and
identity are checked; gaps over 120 seconds reset feature history and persistence.

Actual run: **28,976 valid feature rows**. Nonexclusive rejected reasons:
**491 stale books**, **559 missing-liquidity observations**, **2 out-of-order
observations**. Median spread **$.01**, median absolute top-five imbalance
**.35954**, median top-quote persistence **512.965 seconds**. These statistics
measure sampled quotes, not actor identity, order flow or market-maker intent.

## Executable-price and cost assumptions

Each token's decision trials are spaced at least 90 seconds apart. Entry must
have a different actual book with source and receipt at least 100 ms after the
decision and within 15 seconds. Exit must have source and receipt at least
60 seconds after the decision, with receipt at most 90 seconds. Both must be
complete fresh valid books. Metadata must have active status, clear resolution
rules/source, an unexpired event and current observed minimum lot.

For nominal $2/$5/$15/$25 scenarios, shares derive from the observed entry best
ask. Displayed asks/bids are walked at **10% per-level participation**, entry
within best ask +$.01, exit within best bid −$.01. The scenario records partial
capacity and refuses a complete cost estimate when either leg lacks enough
depth or a verified fee schedule. A higher depth-walk entry cost may exceed the
nominal target: these are independent liquidity/cost scenarios, not risk-approved
wagers. There is no invented portfolio or reused-liquidity portfolio profit.

The operational conservative global notional fee bound is retained. A separate
research counterfactual applies `quantity × rate × price × (1-price)` per observed
level only when both archived fee assumptions explicitly specify exponent 1.
This is consistent with the [official fee formula](https://docs.polymarket.com/trading/fees),
checked 2026-11-06. It does not replace broker or risk fees. Unknown fee curves
remain null; category labels are not substituted for observed fee evidence.

Additional per-leg $.005/$.01/$.02 per-share costs are conservative stress
penalties applied separately from actual depth-walk prices, not invented market
prices. A flat per-share stress can exceed a small notional on very cheap shares;
it is a lower-bound stress calculation and must not be called an actual fill,
physical exit price or realized loss. Passive fills, queue rank, replenishment,
adverse selection and causal impact remain unobserved/null. The
[public stream](https://docs.polymarket.com/market-data/realtime-data) supplies
quoted depth, not proof of our hypothetical queue position.

## Actual results on the frozen dataset

The bounded run retained **6,000 nominal-wager scenarios** (at most 6,000), not
6,000 independent trades. Nonexclusive reasons: **513** missing post-latency or
horizon quotes; **976** minimum-lot failures; **1,008** insufficient-depth
scenarios; **505** missing point-in-time fee scenarios. Trial budget exhaustion
is explicit. Selection ends at the fixed budget rather than scanning indefinitely.

Median hypothetical liquidation difference in USD, **before additional slippage
stress**, with complete depth and both observed fee schedules:

| Nominal target | Scenarios | Known full-depth costs | Conservative bound | Protocol-curve counterfactual |
|---|---:|---:|---:|---:|
| $2 | 768 | 633 | −$.33027 | −$.27971 |
| $5 | 1,744 | 1,433 | −$.65626 | −$.26993 |
| $15 | 1,744 | 1,325 | −$1.94531 | −$.75912 |
| $25 | 1,744 | 1,286 | −$3.31897 | −$1.24944 |

**Zero** known-cost scenarios remain positive after additional $.01/share/leg
stress under either fee treatment. The fixed bid-heavy, ask-heavy and balanced
$2 groups also have negative mean stressed differences. This does not demonstrate
an advantage; nor does it establish that all strategies or longer horizons fail.
The sample, shared-event dependence, threshold choice and time interval limit
inference. Independent confidence intervals and false-positive rates stay null.

There are **zero operational orders/fills created by this module**. Portfolio
P/L, terminal Brier score/log loss and terminal probability calibration are null;
no independently verified terminal target dataset is supplied. No trading
strategy is enabled, certified or promoted by this research.

## Verification and remaining research

Eleven focused regressions pass: causal features, lossless delta reconstruction,
source/observation digest tampering, duplicate IDs, point-in-time metadata/fees,
TTL, unknown costs, depth participation, post-latency source/receipt alignment,
gap restart, and explicit protocol-curve support. Own-source Ruff passes.
Full actual dataset dry-runs were single-process validation, not claimed as
parallel work; the root runner owns bounded concurrent research evaluation.

The full real report is in ignored `data/phase11/microstructure-v3/report.json`;
a bounded summary and immutable dataset manifest are committed under
`.planning/evidence/phase11-micro/`. Earlier v1/v2 artifacts remain preserved
for debugging: v1 lacked the research adapter's archived-fee reference and has
no usable cost estimates; v2 uses the repaired fee bound; v3 adds the clearly
separate protocol-curve counterfactual. Never present an earlier null-cost run as
a successful execution or a profit result.

Further work requires longer causal windows, independent event/regime coverage,
trade/queue evidence for passive execution, independently timestamped external
context and evidence-qualified forward policies. Forecast sensitivity and
quote imbalance alone cannot establish causal or repeatable profit. All existing
operational bankroll, risk, certification and owner-approval rules remain intact.
