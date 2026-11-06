# Real-market strategy approval

The live coordinator must use `ValidationStore`; registering a model or finding a
relationship does not approve it. There is no bundled real-market dataset,
passing report, approval or claimed profitable strategy. Without an active,
verified approval, `load_active(now)` returns `None` and collection continues.

After a real report passes, `strategy-package --report-id ID --output request.json`
prepares an immutable canonical approval request. The owner independently reviews
the report, raw provenance, dependency groups, model and deployment scope, then
signs those exact bytes using an owner-controlled Ed25519 private key kept outside
this service. The owner provisions only its public key in `owner_public_key`.
`strategy-approve` requires `--owner-public-key`, `--owner-request-id`,
`--owner-signature` and a named `--actor`; an actor string alone cannot approve.
No production owner key or approval has been provisioned. Agents must not create
an owner trust root or sign on the owner's behalf. Test keys stay test-only.

The request binds report, dataset, manifest and model hashes, request identity,
expiry and paper-only mode. Restart revalidates the detached signature and current
public-key identity. Missing, changed, expired or invalid signatures fail closed.


`revoke(actor, now, reason)` immediately removes active approval and records its
reason. `status(now)` reports active status, exact blockers, report counts,
latest report and research requirements. Root operational CLI commands expose
these methods; calling validation never calls approval.

## Dataset contract

Supply a JSON array validated as `ValidationObservation`. Every row contains the
existing `LabeledForecast` contract (UTC event/availability time, source, market,
event, historical market probability, actual binary outcome, separately timed
label availability, executable price/quantity and protocol fee rate) plus:

- `partition`: `train` or `heldout`.
- `book`: complete `OrderBookSnapshot`, with actual CLOB source time and receipt
  time, bid/ask levels, token and market identity. It must have been available at
  the historical decision, no older than 15 seconds. Executable price must equal
  the observed best ask, and supplied executable size cannot exceed its depth.
- `independent_evidence_source`, `independent_evidence_ref` and
  `independent_evidence_available_at`: externally reviewed point-in-time context.
  The source must be HTTPS and outside Polymarket; exchange prices are not an
  independent evidence source. Empty references and future context reject.
- `settlement_source`, `settlement_ref`, `settlement_verified`: separately
  verified final resolution evidence. Market prices cannot substitute for an
  outcome. Unverified or unavailable labels reject.

An explicit dependency review and dependency-group assignment are required. Repeated groups across distinct event IDs reject rather than counting correlated windows as independent. Only one observation per distinct event is accepted across the entire dataset,
so train and heldout events cannot overlap or inflate counts. Training decisions
and available labels must precede `train_cutoff`; heldout decisions must follow
it, and their outcomes must be available before validation. No historical book
depth is inferred or manufactured when a historical quote is missing.

## Manifest contract

A JSON `ValidationManifest` contains `data_origin="real"`, `exchange="polymarket"`,
the exact raw dataset SHA256 in `dataset_sha256`, timezone-aware `train_cutoff`
and `expires_at`, a separate `provenance_reviewed` attestation and named
`provenance_reviewer`, collection and independent-signal descriptions, and
`label_method="verified_final_resolution"`.

It also binds explicit `relationships`, `relationship_tokens`,
`settlement_reviews`, `correlation_groups` and `allowed_tiers`. The default tier
is standard. Logical relationships require reviewed rules and explicit
settlement-review flags; descriptive statistical associations are never silently
converted to enforceable constraints. Settlement mechanics and target-market
applicability must be part of the research review. These settings are immutable
inputs to the validation hash; changed strategy scope needs a new validation.

## Default quantitative gate

Defaults cannot be weakened below the initial safety floor through
`ValidationPolicy`: at least **100 independent training events**, **100 heldout
events**, **30 training examples per used probability bin**, heldout Brier score
at most **0.20**, expected calibration error at most **0.08**, and probability
interval width at most **0.35**. The paired heldout Brier improvement over raw
market prices must have a 95% lower confidence bound above **0.005**.

The fitted histogram uses historical market prices as a feature and independently
verified outcomes as labels. A contemporaneous quote is never presented as an
independently estimated probability. Independent context and a material
relationship finding remain separately required by the operational workflow;
empirically successful outcome calibration is not proof of a structural cause.

A fixed $2 target BUY rule is also evaluated only against supplied point-in-time
best-ask depth, capped to 10% participation. Costs use the same global conservative
notional fee bound as the paper broker plus a per-share latency/slippage buffer.
At least **20 heldout trades** and a strictly positive lower 95% confidence bound
on heldout per-trade simulated net P/L are required. This is an isolated strategy
screen, not integrated portfolio or future-profitability certification. The live
risk engine still approves every order, including exceptional evidence and hard
capital limits. Different candidate-selection or feature research needs its own
review for multiple testing, sealed holdout selection and deployment relevance.

## Persistence and trust boundary

SQLite stores exact input bytes, policy, reports and actor review records. On
approval the exact stored inputs are revalidated. On restart the registry and
model artifact are reconstructed from training records, their model hash is
checked, and the approval audit identity/time must match. Expired, changed,
revoked or unreadable approvals fail closed. Data files are bounded to 20 MB by
default. No API keys or wallets are used. Owner signatures authorize paper strategy scope only; the application verifies signatures and has no owner signing function.

These mechanical checks cannot establish whether an externally supplied file or
provenance attestation tells the truth. A named review must inspect the actual
point-in-time archive, independent sources and final resolutions; source strings
and hashes alone do not authenticate a real observation. SHA256 integrity detects
uncoordinated modification, not an attacker controlling and rewriting the entire
local database and audit trail.

Tests construct controlled input assertions, including a passing statistical
case, to verify the gate. They are not actual Polymarket research, are not written
into the operational approval database, and do not authorize live-data trading.
Until authentic, reviewed data meets every gate, collection and explicit
suppression are the correct operational result.
