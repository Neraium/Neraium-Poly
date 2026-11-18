#!/usr/bin/env bash
set -euo pipefail

cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
phase=.planning/evidence/phase57
test "$(git branch --show-current)" = citadel/phase57-basket-frequency
test "$(git rev-parse HEAD)" = "$1"
test -z "$(git status --porcelain)"
scratch=$(cat "$phase/capture-location.txt")
export PYTHONDONTWRITEBYTECODE=1
python3 "$phase/score.py" "$scratch" "$phase"
git add -- "$phase/scorecard.json" "$phase/opportunity-ledger.json"
git diff --cached --check
git commit -m 'Report Phase 57 structural discrepancy frequency and paper execution'
git push origin HEAD:refs/heads/citadel/phase57-basket-frequency
