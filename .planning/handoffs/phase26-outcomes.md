# Phase26 official NHL outcomes

Branch citadel/poly-p26-outcomes-20261108; base ec0c5df. No production writes, model edits, strategy authority, account/risk/archive changes.

API: async `verify_sport_outcome(f, *, directory, clock=None)`; pure `replay_sport_outcome(result, study, f, *, evidence_root, as_of)`. Route only `verification_protocol == official-sports-v26`, after original frozen replay. Native finalized settlement proof remains mandatory. Exact original identity/rules/prospectivity, original frozen model evidence replay, content hashes, official game+team IDs+explicit Final report, score agreement and minute bounds are independently checked. Results are research-only. Cache16 URLs/60s preserves actual receipt, preventing duplicate model source requests.

New legitimate official sources: api.nhle.com/stats/rest/en/game (season and exact Eastern gameDate), /team; www.nhl.com/scores/htmlreports/.../GS....HTM. Historical game2026020265 corroborated Capitals4–Panthers3, scheduled17:30Z, actualstart17:38–17:39Z, end20:12–20:13Z on2026-11-07. This source probe is NOT a forecast score. Raw files persist under this worktree data/phase26; hashes and receipt evidence in .planning/evidence/phase26-outcomes.

Actual original forecast4944da6a9d9f3c61804801b151e71f64d0adac29f1515bdae21207f204265ad6 / market5563968 / parent1171316, created00:18:34Z for01:00Z start: official game not final at01:34:50Z, correctly pending. No new verified outcome claimed. NBA alternate official data.nba.net fails TLS hostname verification; nba.com/games403; restrictions preserved. No CPI denominator imputation.

Validation:27 distinct fixture cases passed (17 initial +10 previously failing cases after correcting fixture selected outcome); ruff passed. Tests cover pending/native absent, foreign original, flag-only, corrupt/hash/path/URL mismatches, exact schedule/team/final clock, premature settlement and cache bounds. Root performs final integrated regression once. Hooks should delegate unchanged frozen model replay, overriding only outcome verify/replay. No source calcfile edits.
