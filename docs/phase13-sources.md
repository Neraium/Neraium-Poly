# Independent sports observations and deterministic mapping

Phase 13 uses the openly licensed **nflverse schedules release** as a prospective
research input. It is a community-maintained derivative dataset, not an official
NFL result oracle. No NBA, ATP, esports, injury, or lineup provider is enabled.
This source adapter has no account, order, settlement, or strategy authority.

## Source inventory and qualification

| Source | Intended input | Qualification / limitation |
|---|---|---|
| [nflverse-data schedules release](https://github.com/nflverse/nflverse-data/releases/tag/schedules) | NFL schedules, participants, reported results | Integrated under repository CC-BY-4.0; attribution retained. Community reports require additional finality corroboration for settlement. |
| [nflverse data license](https://github.com/nflverse/nflverse-data/blob/main/LICENSE.md) | Usage qualification | CC-BY-4.0 license bytes retained with each snapshot. License is limited to rights the publisher can grant and disclaims warranties. |
| [nflreadr schedule dictionary](https://raw.githubusercontent.com/nflverse/nflreadr/main/data-raw/dictionary_schedules.csv) | Field semantics | Kickoff time is US Eastern; scores/result/total are absent for unplayed games. Scores alone do not establish official finality. |
| [NBA official terms](https://www.nba.com/termsofuse) | NBA schedules/results | Withheld: statistics restrictions include gambling and regularly updated databases; no consent configured. |
| [NFL official terms](https://www.nfl.com/legal/terms/) | Independent official results | No licensed automated official-result provider configured; no scraping or access-control bypass. |
| ATP / esports | Other selected-universe events | No qualified provider configured; contracts remain quarantined. |

The source choice follows the observed Polymarket universe: actual NFL match
winner markets exist; NBA markets exist but provider terms prevent enabling the
proposed official adapter. Public accessibility alone is not a license. nflverse
is not represented as NFL-endorsed or independently official. Commercial or
real-money deployment remains separately gated and is outside this phase.

The release is self-described as automatically refreshed when its maintained
schedule file changes. The exact GitHub release asset ID, `updated_at`, declared
SHA-256 digest, original release metadata, license bytes, and downloaded CSV are
retained. Actual retrieval is the earliest availability proved by this system.
A current publisher timestamp is not evidence that a historical decision had the
same source contents. Dataset corrections remain new snapshots, not rewrites.

## Implementation API

`research.phase13.sources` exposes:

```python
await collect_sports(directory, clock=None, client=None, leagues=("NFL",))
load_sports(directory)
# dict: artifacts:list[SourceArtifact], games:list[SportsGame], report:dict,
#       manifest_sha256:str
```

A fresh directory contains `license.txt`, `release.json`, `games.csv`, and an
immutable `manifest.json`. Calling collection on a completed directory replays
it without HTTP requests. Partial snapshots require a new directory. Loading
verifies raw hashes, exact provider/source identities, release asset digest and
publication timestamp, and recomputes normalized games from the raw CSV. A
normalized-game digest catches parser/schema drift. `manifest_sha256` pins all
metadata and availability times for forecast replay.

Normalization retains only identities, source provenance, schedule, and reported
scores. The raw upstream CSV contains betting columns; **none are copied into
SportsGame or model features**. Result and total must agree with home/away scores.
Only 2024 and later seasons are retained at the November 2026 capture. Past blank
scores are `unknown`, never guessed final or canceled. Future blank scores are a
publisher schedule, not an official guarantee that a game will take place.
The schema cannot prove injury availability, lineup status, postponement or
cancellation from absent fields. Those limitations are explicit in missingness.

## Point-in-time semantics and bounded operation

Every artifact records provider, source ID and URL, source publication timestamp
when available, retrieval time, first verified availability, raw path/hash,
quality, and missingness. Every parsed game references the raw artifact hash and
availability. Reported past final results become available only when retrieved;
therefore this corpus can train a **future** forecast but cannot justify historical
point-in-time backtests at the original game dates. No historical market book or
independent feature vintage is invented.

Three initial HTTPS GETs acquire license, release metadata and CSV. Each has at
most four requests including redirects, and only explicit GitHub HTTPS hosts are
allowed; credentials and arbitrary redirect hosts are rejected. Initial requests
are separated by 250 ms. HTTP 403/429/5xx, oversized bodies, changed licensing,
asset races, unknown schemas and malformed timestamps withhold the snapshot.
There is no tight automatic retry loop. The caller schedules future collection.
No provider-published numeric SLA or rate limit is assumed; this adapter stays
far below usual unauthenticated GitHub API quotas and honors HTTP failures.

Bounds: 4 MiB per CSV response, 256 KiB release metadata, 64 KiB license, 12 MiB
per snapshot, at most 30,000 CSV rows and 100 stored entries, and 8 GiB minimum free
disk. Storage symlinks and hardlinks are rejected before writes. The coordinator
must bound the aggregate source archive across refreshes; reaching a limit
withholds further acquisition and preserves existing evidence.

## Event entity resolution

`map_market(market, games, now=...) -> SportsMapping` accepts only the audited NFL
match-winner rule template present in this universe. It requires:

- The exact NFL resolution-source URL and a two-team `X vs. Y` question.
- Exact aliases from an explicit NFL team table; no fuzzy or substring matches.
- The token outcome maps to one of those teams.
- Exact winner, overtime, tie, postponement and cancellation clauses.
- The rules' Eastern month/day/time matches the explicit market UTC timestamp.
  The market timestamp supplies the year; no nearest-event or current-year guess.
- Exactly one source game with the same participants and exact UTC kickoff.
- A fresh pre-event scheduled observation available by the mapping cutoff.

Spreads, totals, unsupported leagues/rule variants, unknown aliases, duplicate
schedule matches, started games, stale/future observations, postponements and
cancellations quarantine with structured reasons. A moved kickoff does not
silently inherit an old contract's interpretation. Every mapping includes parent,
market, token, source game ID, both participants, start time, rule hash, artifact
hash, method version, and mapping hash. Complementary tokens share the source
game; they never become independent observations.

The observed NFL rules pay 0.5 on ties or canceled games. Such cases must remain
unresolved in the existing binary ledger unless separately supported; they are
not rounded to a win/loss. Forecast model uncertainty must disclose these payoff
and result limitations. Mapping alone neither verifies an outcome nor authorizes
any experimental trade.

## Actual observed evidence

At the first source capture, November 6, 2026 06:00:30 UTC, the release asset was
updated at 05:06:25 UTC and yielded **842** retained games: **692** publisher-reported
score records and **150** future schedule records. Zero parse rows were rejected.
These counts are not independently verified settlement counts. Four outcome tokens
map to two actual upcoming source games:

- Polymarket `5920626`, parent `1217417`: `2026_09_DET_MIA`, November 8 18:00 UTC.
- Polymarket `5968098`, parent `1223454`: `2026_09_BUF_MIN`, November 10 01:15 UTC.

Exact capture hashes and mapping identities are in
`.planning/evidence/phase13-sources/source-capture.json`. Raw snapshots remain
ignored under the source agent's `data/phase13-source-capture-v1` and `v2`.
Controlled fixtures exercise failures and are never included in these counts.
