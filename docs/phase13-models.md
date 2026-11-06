# Independent sports models and prospective comparison

The Phase13 models use external historical game results only. Neither Polymarket
prices nor bookmaker odds are features. The source adapter must verify artifact
hashes, provider policy and entity mapping before a model can support a genuine
prospective forecast. Model functions cannot establish source authenticity from
self-asserted caller fields.

`predict_game(games, target, selected_team_id, cutoff, method=...)` strictly
revalidates records, selects only final results available by the aware cutoff,
checks that the target is still scheduled and starts after cutoff, rejects known
contradictory target status and duplicate/conflicting identities, and enforces at
least 50 league games and 10 games per participant. At most 25,000 input records
and a 30–1,095 day lookback are supported; the default lookback is 730 days.
Later observations cannot enter an earlier forecast. Retrieval today establishes
availability today, not an invented historical publication time.

NBA Elo starts ratings at 1500, uses K=20 and a 50-point home advantage. The
frequency challenger uses Beta(1,1) participant win rates and a log-odds matchup.
Tied NBA final scores are quarantined. These parameters are fixed research
baselines and have not been selected by fitting the same prospective outcomes
used to evaluate them. The code supports NBA forecasts, but software fixtures do
not provide a licensed authentic NBA corpus.

NFL Elo expected score cannot be called an unconditional win probability. The
NFL frequency baseline instead uses three outcomes: win, tie and loss. It averages
the participant's Dirichlet(1,1,1) historical outcome frequencies with the opposing
participant's reversed frequencies. The vector sums to one. `probability` is the
unconditional team-win probability, while `uncertainty.outcome_probabilities`
contains all three classes. For a contract paying 0.5 on a tie, expected payout is
`P(win)+0.5*P(tie)` and is explicitly distinct from win probability. Cancellations,
postponements and rule changes are not silently mapped to ties.

All outputs are uncalibrated, research-only challengers. Their broad bounds are
parameter-sensitivity envelopes plus a sample-size penalty, not calibrated
confidence intervals. They omit injury, lineup, rest, roster and coaching changes;
the two-year form window mixes seasons and does not guarantee stationarity.
Community publisher results are not mislabelled as independently official result
verification. Source selection, missingness and participant histories can bias
predictions. Model/version, feature version, source-code/config hash, ordered
training-data hash, game IDs, sample counts and observation cutoffs are recorded.
`verify_prediction` reruns the exact algorithm and compares the complete output;
old model versions can be retained for explicit rollback, never automatic promotion.

## Evaluation and estimands

The Phase12 binary ledger remains binary. Its evaluation routine rejects an NFL
unconditional-win probability against a fractional-payout quote. The separate
sports journal may preserve genuine ternary research predictions without
converting them to a binary forecast or granting order authority.

`evaluate_sports_forecasts` consumes the sports journal's original prediction,
mapping, book and contemporaneous expected-payout quote, plus verified sports and
Polymarket settlement evidence. Result callbacks deny by default. Exact game,
team, token, rules, timing and payout must agree. Canceled, postponed, disputed,
corrected-conflicting and unsupported tied settlements remain unresolved.

Multiclass Brier score and log loss measure outcome forecast accuracy. A single
fractional-payout market quote does not identify market P(win)/P(tie)/P(loss), so
market win-probability and multiclass scores stay null. Expected-payout MSE may be
compared with the original same-record midpoint as a separately labelled target.
It is not an execution-adjusted return or proof of superior win-probability skill.

All forecasts of the same real game and correlated reviewed group count only once
per exact model/feature identity. Primary scores require independently reviewed
groups and at least 20 genuine resolved events; descriptive individual scores are
separate and cannot claim skill. A bounded-loss paired confidence bound is shown
only with sufficient reviewed groups and an explicit independence assumption.
Shared-driver dependence may invalidate that assumption. These research thresholds
do not change the certified 100 training / 100 held-out event requirement.

## Relationship intelligence

`SportsRelationshipResearch` tracks temporal changes in the relationship between
external model strength and observed market probabilities. It requires 10 earlier
observations, three distinct persistent observations spanning at least 60 seconds,
fresh causal quotes, an unchanged model/rule identity and bounded state. Duplicate
evidence does not accumulate persistence. NFL comparisons use model expected
fractional payout, with an explicit label distinguishing this from win probability.
The checkpoint preserves baselines and persistence across restarts. Findings are
descriptive statistical relationships: no verified causal influence, enforceable
logical constraint, executable edge or trading authority is implied.
