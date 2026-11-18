#!/bin/bash
set -euo pipefail
e=$(cd "$(dirname "$0")" && pwd)
scratch=$(cat "$e/scratch-path.local")
mkdir -p "$e/runs"
for item in a1r:8d8c115d20fc86604cffc4af64657f967b499b63 b1r:8d9756ff8a514ad87947646ffc330f0c3e10efc8 b2r:8d9756ff8a514ad87947646ffc330f0c3e10efc8 a2r:8d8c115d20fc86604cffc4af64657f967b499b63; do
 name=${item%:*}
 sha=${item#*:}
 dest=$(cat "$e/source-$sha.local")
 unit="phase51-full-$name.service"
 if [ -s "$e/runs/$name-result.json" ]; then continue; fi
 if ! systemctl is-active --quiet "$unit"; then
  sudo -n test ! -e "$scratch/runs/$name" || { printf '%s\n' "Prior run $name needs inspection"; exit 74; }
  sudo -n python3 "$e/cache.py" "$scratch" > "$e/runs/$name-cache.json"
  sudo -n systemd-run --unit="${unit%.service}" -p CPUQuota=100% -p MemoryMax=2147483648 -p TasksMax=32 -p RuntimeMaxSec=1250 -p TimeoutStopSec=30 -p KillMode=control-group \
   /usr/bin/unshare -m --propagation private --pid --fork --mount-proc /bin/bash "$e/mount-run.sh" "$scratch" "$name" "$dest/backend" "$e/bench.py" "$sha"
 fi
 while systemctl is-active --quiet "$unit"; do
  if ! python3 -c 'import shutil,sys; assert shutil.disk_usage(sys.argv[1]).free>108*1024**3' "$scratch"; then
   sudo -n systemctl stop "$unit"
   exit 73
  fi
  sleep 5
 done
 sudo -n journalctl -u "$unit" --no-pager -n 100 > "$e/runs/$name.log"
 for field in started progress result post; do
  if sudo -n test -f "$scratch/runs/$name/out/$field.json"; then
   sudo -n cat "$scratch/runs/$name/out/$field.json" > "$e/runs/$name-$field.json"
  fi
 done
 sudo -n du -s -B1 "$scratch/runs/$name/upper" > "$e/runs/$name-upper-bytes.txt"
 test -s "$e/runs/$name-result.json" && test -s "$e/runs/$name-post.json" || exit 74
done
