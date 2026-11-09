"""Append verified native research proofs beside, never over, original forecasts.

Only locally collected, bounded proof directories are eligible. This publisher
has no broker, account, certification or redemption interface.
"""
import json
from pathlib import Path
from typing import Literal

from neraium_poly.contracts import Record
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase24.archive import latest
from neraium_poly.research.phase24.operations import original
from neraium_poly.research.phase25.dependencies import at
from neraium_poly.research.phase26.reporting import callbacks
from neraium_poly.research.phase35.native import replay_native_directory


class NativePayoutResearchStudy(Record):
    original_study_id: str
    original_study_sha256: str
    original_forecast_sha256: str
    forecast_id: str
    proof: dict
    bundle_sha256: str
    manifest_sha256: str
    evidence_directory: str
    research_only: Literal[True] = True
    trading_authority: Literal[False] = False
    certification_authority: Literal[False] = False


class NativeResearchPublisher:
    def __init__(self, store, directory, *, clock, can_write):
        self.store, self.directory = store, Path(directory)
        self.clock, self.can_write = clock, can_write
        self.rows = {r['id']: r for r in latest(store, 'NativePayoutResearchStudy', limit=64)}
        self.report = self._status()

    def _status(self):
        return {'status': 'research_only', 'native_verified_markets': len({r['proof']['market_id'] for r in self.rows.values()}),
            'native_parent_events': len({r['proof']['event_id'] for r in self.rows.values()}),
            'native_forecast_bindings': len(self.rows), 'market_relative_model_superiority': None,
            'certified_training_groups': 0, 'certified_heldout_groups': 0,
            'trust_limit': 'attributed finalized HTTPS RPC evidence; not independent node consensus',
            'trading_authority': False, 'certification_authority': False}

    def step(self):
        now = at(self.clock())
        # Exactly the reviewed inventory, not an unbounded recursive scan.
        inventory = self.directory / 'inventory.json'
        if not inventory.is_file():
            self.report = {**self._status(), 'last_checked_at': now.isoformat(), 'blocker': 'native_evidence_inventory_unavailable'}
            return self.report
        if inventory.stat().st_size > 64 * 1024:
            raise ValueError('bounded native proof inventory required')
        entries = json.loads(inventory.read_text())
        if not isinstance(entries, list) or len(entries) > 16:
            raise ValueError('bounded native proof inventory required')
        published = {(r['bundle_sha256'], r['manifest_sha256']) for r in self.rows.values()}
        labels = None
        for entry in entries:
            name = entry['directory']
            if Path(name).name != name or name in ('.', '..'):
                raise ValueError('local native proof directory required')
            pair = (entry['bundle_sha256'], entry['manifest_sha256'])
            if pair in published:
                continue  # Immutable archive/checkpoint recovery verifies published records.
            folder = self.directory / name
            if folder.is_symlink() or folder.resolve().parent != self.directory.resolve():
                raise ValueError('local native proof directory required')
            import hashlib
            for filename, expected in zip(('bundle.json', 'manifest.json'), pair, strict=True):
                path = folder / filename
                if path.stat().st_size > 8 * 1024**2 or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    raise ValueError('reviewed native evidence hash mismatch')
            proof = replay_native_directory(folder)
            bundle = json.loads((folder / 'bundle.json').read_text())
            forecast = bundle['forecast']
            if labels is None:
                labels = latest(self.store, 'OfficialEventLabelStudy', limit=128)
            matches = [r for r in labels if r['forecast_id'] == forecast['id'] and r['original_forecast_sha256'] == digest(forecast)]
            if not matches:
                raise ValueError('original source-anchored forecast required')
            label = matches[0]
            study = original(self.store, label['original_study_id'])
            if digest(study) != label['original_study_sha256'] or forecast not in study['forecasts']:
                raise ValueError('original native forecast binding mismatch')
            replay = callbacks(self.store, self.directory.parent)[0](study, forecast, as_of=now)
            if (replay.get('verified') is not True or replay.get('forecast_sha256') != digest(forecast)
                or replay.get('original_study_sha256') != digest(study)):
                raise ValueError('original native model/source replay required')
            if not at(forecast['timestamp']) < at(proof['settlement_at']) <= at(proof['available_at']) <= now:
                raise ValueError('prospective native settlement timing required')
            if not self.can_write():
                raise ValueError('native research archive backpressure')
            row = NativePayoutResearchStudy(id=digest(['native-payout-research-v35', *pair]), timestamp=now,
                available_at=now, source='neraium-poly/native-payout-research/v35',
                original_study_id=study['id'], original_study_sha256=digest(study),
                original_forecast_sha256=digest(forecast), forecast_id=forecast['id'], proof=proof,
                bundle_sha256=pair[0], manifest_sha256=pair[1], evidence_directory=str(folder))
            self.store.append(row)
            self.rows[row.id] = row.model_dump(mode='json')
            published.add(pair)
        self.report = {**self._status(), 'last_checked_at': now.isoformat(), 'blocker': 'conditional_forecasts_not_native_calibrated_probabilities'}
        return self.report

    def status(self):
        return dict(self.report)
