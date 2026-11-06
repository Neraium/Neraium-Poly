# Phase 15 experimental stop and strategy readiness

This investigation is read-only. The assessment module has no reset operation or trading authority. Both native SQLite connections and service checkpoints are read with `mode=ro` and `query_only`; public loopback APIs are GET-only. No account owner is instantiated against production storage. Reports are bounded and content-hashed; they are review packages, not authorization tokens.

## Stop chronology and limits of attribution

Observed 2026-11-06 20:34:59 UTC:

* Native experimental risk audit contains one active stop, sequence **5249**, timestamp **2026-11-06T06:49:37.230323+00:00**, payload exactly `{"active":true}`. The original record has no actor, trigger reason or triggering evidence identifier. A manual actor cannot be excluded from that record alone.
* Preserved Phase 13 experimental baseline snapshot is healthy and unlatched at **05:56:55.000649 UTC**.
* Preserved Phase 14 snapshot at **08:25:51.974043 UTC** is latched and reports `experimental_storage_budget_exhausted`. Its last normal cycle is **06:49:26.180018 UTC** and last ingestion **06:49:26.473405 UTC**, approximately 10.76 seconds before the stop audit.
* The existing experimental runtime storage guard stops the account on budget exhaustion. Together, the original audit, earlier healthy snapshot and later storage-error snapshot strongly corroborate a storage-triggered automatic stop. They do not prove the original actor or rule out an independent manual intent.

At capture, experimental cash and peak were **$500**, realized P/L **$0**, with zero positions, pending reservations, orders and fills. Certified API capital was independently **$500** and P/L **$0**; source-bound assessment also reads its native account row. Six strategies were registered, active and unsuspended. Paper-only flags were verified and the certified strategy status remained `validation_blocked`.

At the same capture, collector and experimental archive health were `ok`, with 64 GiB and 16 GiB configured budgets respectively, more than 24 hours forecast capacity, and filesystem space above the configured global floor. This is one observation, not sustained recovery or permission to clear the latch. Actual machine-readable evidence, including hashes of the earlier snapshots, is retained locally under `data/phase15/risk/` and is not committed with repository code.

## Recovery requirements and exact approval

The existing documented procedure in `docs/live-paper-operation.md` requires resolving the cause and an explicitly reviewed operator action; restarts do not clear a stop. There is no documented automatic experimental reset allowance. Phase 15 therefore preserves the stop.

`capture_readiness(root)` gathers bounded native and API evidence. `assess_recovery(evidence, now=..., observation_window=...)` checks account identity and isolation, matching configured/stored limits, unchanged small-wager/20% limits, native zero-loss capital, no unreconciled inventory or reservations, no independent strategy suspension, fresh paper-only service observations, healthy archives above the disk floor with at least a 24-hour forecast horizon, live public fresh books, and the blocked certified gate. It requires a contemporaneous healthy observation window spanning at least 60 seconds and three observations, with its durable evidence hash. This is a minimum diagnostic window, not proof of indefinite operation.

The initial assessment passed all individual operational checks but withheld a reset recommendation because the sustained window had not yet been supplied. Every assessment expires after five minutes and requires immediate revalidation before any operator action. Changes to holdings or capital require a fuller manual reconciliation instead of automatically adopting this baseline-specific checklist.

If those conditions pass, the owner request is:

> Approve one operator-reviewed reset of experimental-paper stop audit seq 5249 under the newly generated assessment SHA-256, exclusively paper-only, with unchanged risk and strategy gates. Acknowledge that the original audit does not identify the actor. Do not replay expired signals.

The request must identify the actual fresh assessment hash; this document is not that approval. `reset_authorized`, `automatic_reset_authority` and `certified_strategy_authority` remain false even when the assessment is technically satisfactory. A future operator action must preserve the audit and independently confirm no manual stop intention remains. Improve future stop audit records with actor/reason/evidence fields in a separate reviewed change; this investigation does not rewrite the original audit.

## Six-strategy readiness

Counters below are the persisted decision-trace epoch at 20:34:59 UTC, not independent events or held-out results. Each strategy considered **279,744** market observations, of which **205,364** met observation validity. Counters accumulate across restarts from the trace epoch; latest-cycle counters replace the preceding cycle. Rejection reasons overlap and must not be summed as unique observations.

| Strategy | Candidate signals | Qualified | Risk attempts/rejections | Primary remaining prerequisites |
| --- | ---: | ---: | ---: | --- |
| Cross-market consistency | 0 | 0 | 0 / 0 | Independently reviewed exhaustive payoff scope; multi-leg execution and hedge support |
| Persistent relationship | 15,187 | 0 | 0 / 0 | Qualified persistent contextual relationship evidence; conservative cost-adjusted edge |
| Liquidity spread | 0 | 0 | 0 / 0 | Validated queue/adverse-selection assumptions and two-sided inventory execution |
| Event driven | 0 | 0 | 0 / 0 | Independent predecision context and qualified response model |
| Short horizon | 176,357 | 2 | 2 / 2 | Stop latch; fresh future signals must qualify again; empirical uncertainty remains unvalidated |
| Calibrated forecast | 0 | 0 | 0 / 0 | Independent context, verified event labels and held-out calibration |

Short-horizon and persistent-relationship paths are the only two current signal generators capable of order admission. Their target is a sixty-second executable bid mark, **not** a calibrated independent terminal event probability. They require at least 40 causal prior observations, 20 matured error observations and an unvalidated empirical mark-error envelope. Relationship signals additionally require persistent qualified evidence.

Both recompute conservative estimated edge as `lower_exit_bid*(1-fee) - entry_ask*(1+fee) - 0.02`, requiring at least $0.03 per share, current verified fees, fresh complete observed books, a spread no greater than $0.05, and all risk and participation limits. This represents a conditional research estimate; no measured forecasting or profitable advantage has been established.

Dominant epoch rejections for both mark paths were conservative round-trip edge (208,954), insufficient causal bid history (29,398), immature horizon errors (6,332), stale book (56,496), unknown fees (22,183) and missing liquidity (11,279). Persistent relationship also rejected 263,581 observations for missing qualified contextual evidence. Category and count dictionaries are retained in the structured report.

Two authentic short-horizon opportunities reached risk after archive recovery:

| Signal time UTC | Market / parent event | Entry ask | Estimated edge/share | Actual result |
| --- | --- | ---: | ---: | --- |
| 17:53:30.181453 | 6722815 / 1320893 | $0.18 | $0.038 | Rejected solely `kill_switch` |
| 19:18:13.585026 | 6736347 / 1322444 | $0.18 | $0.03325 | Rejected solely `kill_switch` |

Both requested approximately 11.111111 shares for a $2 notional. No capital reservation, paper order or fill was produced. Both signals expired within 30 seconds and must never be resubmitted after any reset. These are real observed research admissions, not evidence of realized or expected profitable performance. Unsupported current net-edge, calibration superiority and realized-advantage fields remain null.

## Controlled execution verification

The dedicated regression creates disposable fixture accounts and a certified sentinel; no production input is used. It confirms that a persisted stop rejects an otherwise qualifying fixture signal, survives restart, and only an explicit fixture owner action permits a **new** fresh signal to proceed through risk approval, reservation, simulated depth-aware fill and restart reconciliation. It verifies the certified sentinel remains byte-identical. Existing broker/risk tests separately cover partial fills, expiration, latency, duplicate prevention, losing streaks and exceptional rejection.

No new experimental strategy authorization, certified approval, threshold reduction or automatic model promotion is introduced. Certified historical requirements remain 100 independent training and 100 held-out events plus explicit owner approval. Real-money trading remains disabled.
