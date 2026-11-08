"""Read-only replay of fixed canonical forecasts; never new live opportunities."""
import json
import sys
from pathlib import Path

from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase25.weather import replay
from neraium_poly.research.phase28.execution import analyze_depth

artifact = Path(__file__).with_name('canonical-forecast-reconciliation.json')
source = Path(sys.argv[1] if len(sys.argv) > 1 else '/home/ubuntu/Neraium-Poly/data/experimental-paper')
expected = json.loads(artifact.read_text())
selected = set(expected['new_since_phase31_start'])
results = []
with ReadonlyArchive(source, max_query_bytes=32*1024**2) as reader:
    for entry in expected['rows']:
        if entry['forecast_id'] not in selected:
            continue
        kind, payload, _sha = reader.get(entry['source_study_id'])
        assert kind == 'ExpansionResearchStudy'
        study = json.loads(payload)
        assert digest(study) == entry['source_study_sha256']
        f = next(f for f in study['forecasts'] if f['id'] == entry['forecast_id'])
        assert digest(f) == entry['forecast_sha256']
        proof = replay(f, study['evidence'], as_of=study['available_at'])
        assert proof['verified'] and not proof['trading_authority']
        analysis = analyze_depth(f['book'], as_of=f['timestamp'], expected_payout=f['probability'],
                                 lower_payout=f['lower_probability'], upper_payout=f['upper_probability'])
        results.append({'forecast_id': f['id'], 'market_id': f['market_id'], 'event_id': f['event_id'],
                        'model_id': f['model_id'], 'probability': f['probability'],
                        'forecast_timestamp': f['timestamp'], 'book_timestamp': f['book']['timestamp'],
                        'book_sha256': f['book_sha256'], 'original_model_replay': proof,
                        'native_minimum_order_size': f['market']['min_order_size'],
                        'gross_profit_maximum': analysis['maximum_gross_profit'],
                        'net_expected_profit': None, 'calibration_verified': False,
                        'all_in_costs_verified': False, 'qualified_opportunity': False,
                        'scope': 'as-recorded actual canonical prospective forecast; not current opportunity, fill or realized profit'})
print(json.dumps(results, indent=2))
