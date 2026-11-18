#!/bin/bash
set -euo pipefail
e=$(cd "$(dirname "$0")" && pwd)
root=/home/ubuntu/Neraium-Poly
private=$1
action=$2
test -s "$e/ready.json"
refpid=$(systemctl show -p MainPID --value neraium-poly-paper.service)
exppid=$(systemctl show -p MainPID --value neraium-poly-experimental.service)
python3 - "$e" "$refpid" "$exppid" <<'PY'
import json,sqlite3,sys
from pathlib import Path
p,ref,exp=sys.argv[1:]
e=Path(p)
r=json.loads((e/'ready.json').read_text())
assert ref==r['reference']['service']['MainPID']
original=json.loads((e/'preflight.json').read_text())
assert exp==original['experimental']['service']['MainPID']
for pid,scope in ((ref,'paper-live'),(exp,'experimental-paper')):
    env=set(Path('/proc',pid,'environ').read_bytes().split(b'\0'))
    assert {b'PAPER_TRADING=true',b'LIVE_TRADING_ENABLED=false'}<=env
    if scope=='experimental-paper':
        assert b'NERAIUM_SHADOW_RESEARCH=false' in env
    with sqlite3.connect(f'file:/home/ubuntu/Neraium-Poly/data/{scope}/risk.sqlite?mode=ro',uri=True) as db:
        assert db.execute('select kill from account where id=1').fetchone()[0]==(scope=='experimental-paper')
PY
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$(cd "$e/../../.." && pwd)/backend"
archive="$root/data/experimental-paper"
case "$action" in
    capture) exec "$root/.venv/bin/python" "$e/capture-tape.py" "$private/forward-tape.jsonl.gz" "$archive" ;;
    score) exec "$root/.venv/bin/python" "$e/prospective.py" "$private/forward-tape.jsonl.gz" "$archive" "$private/score" ;;
    *) exit 64 ;;
esac
