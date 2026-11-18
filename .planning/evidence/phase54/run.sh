#!/bin/bash
set -euo pipefail
e=$(cd "$(dirname "$0")" && pwd)
scratch=$(cat "$e/scratch.local")
live=/home/ubuntu/Neraium-Poly
if [ "$#" -eq 0 ]; then set -- a b; fi
for item in "$@"; do
  runner=replay.py
  case "$item" in
    a) sha=8d9756ff8a514ad87947646ffc330f0c3e10efc8 ;;
    b) sha=cf52778988d26e3d2016bb01cbfe85d212b3f64d ;;
    c) sha=cf52778988d26e3d2016bb01cbfe85d212b3f64d; runner=calibrate.py ;;
    d) sha=$(cat "$e/repair-sha.txt") ;;
    *) exit 64 ;;
  esac
  arm=$item
  src="$scratch/$arm/source"
  mkdir -p "$src" "$scratch/$arm"/{reference,experimental}
  git archive "$sha" backend | tar -x -C "$src"
  anchor=$(python3 -c 'import time;print(time.monotonic_ns()+18*10**9)')
  ref="phase54-replay-$arm-reference"
  exp="phase54-replay-$arm-experimental"
  common=(-p User=ubuntu -p CPUQuota=100% -p PrivateNetwork=yes -p ProtectSystem=strict
    -p "ReadWritePaths=$scratch/$arm" -p "InaccessiblePaths=$live/data"
    -p RuntimeMaxSec=345 -p TimeoutStopSec=8 --setenv "PYTHONPATH=$src/backend"
    --setenv PYTHONDONTWRITEBYTECODE=1 --setenv PAPER_TRADING=true
    --setenv LIVE_TRADING_ENABLED=false --setenv NERAIUM_SHADOW_RESEARCH=false)
  sudo -n systemd-run --unit="$ref" "${common[@]}" -p MemoryMax=1073741824 -p TasksMax=64 \
      "$live/.venv/bin/python" "$e/$runner" reference "$scratch/fixture.json.gz" "$anchor" "$scratch/$arm/reference"
  while ! test -s "$scratch/$arm/reference/workload.jsonl"; do
    systemctl is-active --quiet "$ref"
    sleep 1
  done
  sudo -n systemd-run --unit="$exp" "${common[@]}" -p MemoryMax=2147483648 -p TasksMax=32 -p "JoinsNamespaceOf=$ref.service" \
      "$live/.venv/bin/python" "$e/$runner" experimental "$scratch/fixture.json.gz" "$anchor" "$scratch/$arm/experimental"
  while systemctl is-active --quiet "$ref" || systemctl is-active --quiet "$exp"; do
    sleep 5
  done
  mkdir -p "$e/$arm"
  sudo -n journalctl -u "$ref" --no-pager -o cat > "$e/$arm/producer.log"
  sudo -n journalctl -u "$exp" --no-pager -o cat > "$e/$arm/experimental.log"
  for file in reference/workload.jsonl reference/resources.jsonl experimental/{requests,polls,resources}.jsonl; do
    cp "$scratch/$arm/$file" "$e/$arm/${file//\//-}"
  done
done
