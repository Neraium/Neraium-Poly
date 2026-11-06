# Independent prospective sports operations

Phase13 attaches research to the existing experimental process. The adapter has
no account, broker, wallet, strategy-registry or promotion reference. The certified
account and existing binary Phase12 forecast records are unchanged. Root integration
owns the parent service hook and monitoring view.

## Independent estimates and the NFL estimand boundary

NFL winner rules can pay one half on ties, canceled games, or specified no-result
conditions. A market quote for this contract is an expected payout; it is not an
unconditional team-win probability. The independent frequency model explicitly
produces win/tie/loss probabilities. These are appended as
`independent_ternary_research` records in a separate `prospective.sqlite`, never
converted into a binary Phase12 `EventForecast` or a paper order. The record keeps
the actual contemporaneous book, its source and receipt times, the market midpoint
as an expected-payout comparator, and `market_win_probability: null`.

Before any append, the runtime reloads the original raw source snapshot, verifies
its hashes and normalization, repeats exact event mapping, and repeats the pure
external-only model. Artifact availability must precede the prediction cutoff;
the cutoff is current, timezone-aware and at least five minutes before the event
start. The full `SportsPrediction`, original market rules, deterministic mapping,
dataset hash, immutable source snapshot reference and uncertainty are retained.
No simulated market fixtures enter the operational acquisition path.

The independent model remains uncalibrated and research-only. There is no claim of
forecasting superiority, tradeability, profitability, independent event-group
review, or certification. Existing binary ledger admission also replays raw
source/mapping/model evidence and refuses to replace another review callback.

## Integrity, recovery and bounded collection

The sports journal uses typed forecast/outcome schemas, append-only SQLite triggers,
canonical SHA256 content hashes and a chained head. The coordinator checkpoints the
head separately, detecting valid-prefix rollback after restart. Deterministic daily
market/model IDs and durable journal-derived deduplication survive a crash between
append and checkpoint. Later forecasts are new records; earlier records are never
rewritten. Models and source data are versioned in each record.

Default source cadence is twelve hours; at most two forecasts are appended per
frame. Source snapshots are immutable. Sports storage has a 64MiB aggregate ceiling,
a 16MiB/10,000-record journal ceiling, a 256-file ceiling, and the existing 8GiB free
disk floor. Acquisition reserves the provider's full 12MiB snapshot ceiling; proof
attempts reserve 8MiB. All path, symlink and hardlink checks occur before source
replay. Budget exhaustion preserves evidence and withholds further acquisition.
No archive is deleted or threshold weakened to maintain activity.

Failures leave research unavailable with explicit bounded rejection categories.
They do not authorize orders. Counter scope is explicit: totals/rejections are
cumulative since Phase13 began; journal counts are durable; recent candidates and
mapped-event coverage describe the latest frame. Restart does not reset journals
or account history.

## Settlement and fair scoring

Scheduled checks begin no earlier than four hours after the mapped start. This
only schedules a check and never establishes an outcome. An original sports
journal reference binds the existing Phase12 native-resolution/finalized-CTF proof
acquirer to the original market, rule hash, token and pre-event cutoff. It is not
inserted as a synthetic binary forecast. A newly collected independent published
sports final score must match the original participants, event start, overtime
scope and exchange payout. nflverse is labeled a separately published result
source, not an official league API.

Canceled, postponed, in-progress, duplicate/corrected, rescheduled, disputed,
missing-source or payout-conflicting results remain unresolved. Current exchange
proof contracts support only binary payouts, so a tied game's fractional payout
also remains unresolved until a separately reviewed proof schema exists. We do not
force a binary result.

After restart, one saved outcome per background call is independently replayed
against original and result raw sources and the retained exchange proof before
its score becomes available again. Corrections in the newest sports snapshot
suspend scoring and require review; previous journal records remain intact.
The evaluation callback denies unverified results by default. Actual matched
records can expose descriptive multiclass Brier/log-loss values; headline scores,
calibration and confidence intervals require independently reviewed event groups.
The market does not provide a full win/tie/loss distribution here, so market-win
and multiclass baseline scores remain null. Expected-payout MSE is a separate,
explicitly labeled comparison to the original same-time quote, never profitability.

## Persistent relationship research

Every eligible model/book pair updates `SportsRelationshipResearch` before daily
forecast deduplication. Actual book evidence hashes prevent repeated observations
from inventing persistence. Team-strength expected-payout residuals are studied
against prior temporal baselines with warm-up, directional persistence and elapsed
time requirements. Checkpointed relationship state survives restarts. Descriptive
relationship changes grant neither logical-arbitrage status nor trading authority.

## Verification scope

Controlled unit fixtures exercise raw-evidence tampering, timestamp/mapping/quote
failure, unauthorized source identity, independent journal/account separation,
append-only triggers, hash anchoring, restart deduplication, cancellation,
postponement, ties, correction ambiguity and fair scoring. These fixture records
are not authentic research observations. Actual service counts, source hashes,
prospective forecasts and evidence deficiencies are reported by the coordinator
from separate operational captures.
