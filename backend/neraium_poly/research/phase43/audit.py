"""Bounded, read-only individual-trade audit over immutable strategy decisions."""
import argparse
import json
import time

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.checkpoints import unpack_checkpoint
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase43.economics import attribution, ledger


def audit(directory, *, max_cycles=1024, max_bytes=512*1024**2, seconds=120):
    archive = ReadonlyArchive(directory)
    rows = archive._catalog_rows('SELECT id,available_at FROM records WHERE kind=? ORDER BY available_at,id LIMIT ?', ('StrategyCycle', max_cycles+1))
    started = time.monotonic(); used = 0; state = None; coverage = []; previous = None
    for meta in rows[:max_cycles]:
        if time.monotonic()-started > seconds:
            raise ValueError('audit time budget reached; no complete-coverage claim')
        original = archive.get(meta['id'])
        used += len(original[1].encode())
        if used > max_bytes:
            raise ValueError('audit byte budget reached; no complete-coverage claim')
        row = json.loads(original[1])
        if row['previous_id'] != (previous['id'] if previous else None) or (previous and row['previous_sha256'] != previous['sha256']):
            raise ValueError('audit source lineage mismatch')
        batch = row['events'][0]
        events = unpack_checkpoint(batch['payload'])['decisions']
        if digest(events) != batch['sha256']:
            raise ValueError('audit decision integrity mismatch')
        state = ledger(events, state)
        previous = {'id': row['id'], 'sha256': digest(row), 'at': row['available_at']}
        coverage.append(previous)
    result = attribution(state or {'trades': {}, 'unmatched_exits': 0})
    result.update(coverage=coverage, original_bytes_verified=used, duration_seconds=time.monotonic()-started,
                  complete_at_snapshot=len(rows)<=max_cycles, snapshot_end=previous,
                  hold_comparison={'hold_native': 'unresolved: no native payout proof in these original decisions; realized P/L unavailable',
                    'legacy_exit': 'actual recorded executable modeled bid exits; no counterfactual missing books invented',
                    'other_exit_policies': 'new frozen prospective matched-entry tournament; historical path coverage insufficient for an uncensored comparison'})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('archive'); parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = audit(args.archive)
    with open(args.output, 'w') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps({k:result[k] for k in ('by_strategy','unmatched_exits','original_bytes_verified','duration_seconds','complete_at_snapshot','snapshot_end')}, indent=2))
