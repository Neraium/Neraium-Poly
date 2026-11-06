# Sports as one domain in universal prediction intelligence

The Phase13 NFL capability is preserved as a leaf adapter. It is not the platform
architecture, branding or default algorithm for other event types. No existing
forecast, sports data, model version, account, risk setting or audit record is
replaced by this change.

## Read-only universal projection

`project_sports_forecast(record)` validates the complete original
`TernarySportsForecast` schema and returns a wrapper with:

- `projection_only=true`, `admissible_to_new_journal=false`,
  `count_as_new_forecast=false`.
- The original immutable record ID and SHA256.
- A `DomainForecast` view tagged`sports`, with
  `probability_semantics=outcome_distribution`, `probability=null`, and the exact
  original win/tie/loss vector.
- Original forecast/cutoff timestamps, model and feature versions, model/training
  dataset hashes, uncertainty, rule hash, market snapshot and executable-book
  observation. The contemporaneous market value remains an expected-payout
  comparator; it is not relabeled as unconditional team-win probability.

The evidence reference is the original source-dataset SHA, not a newly created
universal-journal evidence ID. Projection validates structure only; original
source/model replay remains required. It grants no journal, strategy, calibration,
independence-review or trading authority. Mutable view dictionaries are deep
copies, so changing a caller's projection does not change historical records.
No provider or writer is instantiated by the projection function.

Two actual existing Phase13 records were projected as a verification observation:
Lions market5920626 and Bills market5968098. Their original evidence file hash was
unchanged. There were**zero new forecasts, zero journal appends and zero newly
activated providers**. The runtime continued to report two pending ternary
research forecasts, zero resolved,500cash and0P/L. Its budget-degraded service
state was reported honestly; projections do not restart collection or bypass the
8GiB floor. See`projection-observed.json` for exact timestamps and hashes.

## Additional league source investigation

Only documentation and access/rights qualification were investigated. No new
league statistics corpus was downloaded, no model was trained or enabled, and
no inaccessible historical availability was inferred. Provider accessibility is
not permission for automated collection, nor proof of final settlement.

|Sport|Primary source evaluated|Access/rights and current implementation|Mapping, labels and vintage requirements|
|---|---|---|---|
|NFL|Existing nflverse schedules release|Preserved CC-BY4.0 research ingestion and external-only W/T/L model; no trading authority|Exact team aliases, start/rules and scores; publisher results are not official finality; historical publication vintages missing|
|NBA|[NBA terms](https://www.nba.com/termsofuse)|Existing acquisition restriction remains; no new activation|Team/date/OT mapping; no licensed current training or finality feed acquired|
|NHL|[NHL terms](https://www.nhl.com/info/terms-of-service)|Terms reviewed; automated reuse qualification remains pending; no provider activated|Regulation/OT/shootout scope, participants, schedules, official results and causal availability require a separate adapter|
|MLB|[MLB terms](https://www.mlb.com/official-information/terms-of-use), [Retrosheet event files](https://www.retrosheet.org/gamenew.htm)|Official automated acquisition withheld pending permission. Retrosheet is a historical-data candidate, not an activated current result feed|Doubleheaders, game identity, suspended/postponed games, full-game rules, outcome corrections and retrieval/publication vintages require qualification|
|Soccer|[Hudl/StatsBomb Open Data README](https://github.com/hudl/open-data), [license](https://github.com/hudl/open-data/blob/master/LICENSE.pdf)|README offers selected competitions for research with attribution; complete license/use qualification and current-universe linkage remain pending; no corpus ingested|Competition/team IDs, regulation versus extra time/penalties, three-way draws, authoritative final scores and source vintages|
|Tennis|[ATP terms](https://www.atptour.com/en/terms-and-conditions)|Systematic score/ranking acquisition requires permission; no provider activation. The former JeffSackmann tennis_atp README URL returned404 during review; mirrors were not substituted|Player/tournament/round identities, retirements, walkovers, best-of format, finality and rankings available at cutoff|
|NCAA|[NCAA terms](https://www.ncaa.org/terms-of-service/)|Automated collection and reuse remain unqualified; no provider configured|College team identity, competition format, cancellations, official statistics/results and causal source vintages|
|Esports|[Riot developer policies](https://developer.riotgames.com/policies/general)|Betting/gambling functionality is disallowed by that policy; it is not adopted as this platform's data provider|Game/title, roster, series/map winner, forfeits and organizer-specific rules need exact independent mapping and result evidence|

NHL/MLB/NCAA/ATP website availability has not been presented as a successfully
operating sports API. Retrosheet and StatsBomb historical material would require
retained provenance, appropriate use authorization, exact event linkage and
publication-time handling before it could support research. Current downloads
cannot repair missing historical point-in-time availability. No injuries or
lineups were invented.

The existing watchlist primarily contains NFL, NBA, tennis and esports among
sports. That observation does not justify broad league downloads while storage
and evidence remain constrained. Multi-domain work therefore retains the
qualified NFL research capability and exposes it through shared semantics, while
weather, finance, economics and other adapters remain separate research domains.

## Validation and limitations

Seven controlled tests cover immutable-source projection, exact vectors and
identity/provenance, expected-payout versus win semantics, detached mutable views,
full-model validation, future quote timestamps, rules mismatch and missing depth.
Fixtures are not genuine forecasts. Actual projections are separately reported
as views of existing forecasts, not additional independent events. No forecasting
skill or profitability has been established by a schema projection.
