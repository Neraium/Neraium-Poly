"""Reconcile already-viewed evidence and inventory later source coverage without scoring it."""
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase16.checkpoints import unpack_checkpoint
from neraium_poly.research.phase14.relationships import digest

HERE=Path(__file__).resolve().parent
EVIDENCE=HERE.parent
archive=ReadonlyArchive('/home/ubuntu/Neraium-Poly/data/experimental-paper')
legacy=json.loads((EVIDENCE/'phase43/trade-audit.json').read_text())
old=json.loads((EVIDENCE/'phase16/research/frozen-experiment.json').read_text())
groups=defaultdict(list)
for trade in legacy['trades']:
    groups[f"{trade['profile']}/{trade['strategy']}"].append(trade)
historical={}
for name,trades in groups.items():
    by_event=defaultdict(float)
    by_market=defaultdict(float)
    for trade in trades:
        by_event[trade['event_id']]+=trade['modeled_exit_pnl']
        by_market[trade['market_id']]+=trade['modeled_exit_pnl']
    net=sum(t['modeled_exit_pnl'] for t in trades)
    gross=sum(t['gross_price_pnl'] for t in trades)
    completed=[t for t in trades if t['remaining_quantity']<=1e-8 and t['exit_quantity']>0]
    historical[name]={
        'filled_orders':len(trades),'completed_orders':len(completed),
        'closed_net_dollars':net,'gross_executable_price_dollars':gross,'execution_cost_dollars':gross-net,
        'net_per_completed_order':sum(t['modeled_exit_pnl'] for t in completed)/len(completed) if completed else None,
        'allocated_entry_basis':sum(t['allocated_entry_cost'] for t in trades),
        'open_position_count':sum(t['remaining_quantity']>1e-8 for t in trades),
        'net_by_market':dict(by_market),'net_by_event':dict(by_event),
        'net_without_best_event':net-max(by_event.values()) if by_event else None,
        'signal_and_opportunity_counts':None,'strategy_maximum_drawdown':None,
    }
latest={}
design_markets=set()
design_events=set()
cohorts={}
prior_dataset=Path('/home/ubuntu/Neraium-Poly/data/phase16/prepared-core/frames.jsonl')
source_hash=hashlib.sha256()
depth_universe={}
with prior_dataset.open('rb') as stream:
    for line in stream:
        source_hash.update(line)
        row=json.loads(line)
        for market in row['frame']['markets']:
            depth_universe[market['token_id']]={k:market.get(k) for k in ('market_id','event_id','question')}
assert source_hash.hexdigest()==old['dataset_sha256']
for market in depth_universe.values():
    design_markets.add(market['market_id'])
    design_events.add(market['event_id'])
for kind in ('StrategyCycle','StrategyCycle44','StrategyCycle45','ProfileStudy'):
    records=archive._catalog_rows("SELECT id,available_at,digest FROM records WHERE kind=? ORDER BY available_at DESC,id DESC LIMIT 1",(kind,))
    if records:
        latest[kind]=dict(records[0])
        if kind=='ProfileStudy':
            continue
        original=archive.get(records[0]['id'])
        value=json.loads(original[1])
        checkpoint=unpack_checkpoint(value['checkpoint'])
        assert digest(checkpoint)==value['state_sha256']
        markets=sorted(checkpoint['markets_seen'])
        design_markets.update(markets)
        design_events.update(row['event_id'] for row in checkpoint['forecasts'].values())
        profiles={}
        for profile, state in checkpoint['profiles'].items():
            realized={}
            for trade in state['closed']:
                key=trade['strategy']
                entry=realized.setdefault(key,{'exit_records':0,'settlement_records':0,'exit_net':0.,'settlement_net':0.,'net_by_event':{}})
                lane='settlement' if trade['native_settled'] else 'exit'
                entry[lane+'_records']+=1
                entry[lane+'_net']+=trade['pnl']
                parent=trade['event_id']
                entry['net_by_event'][parent]=entry['net_by_event'].get(parent,0.)+trade['pnl']
            for entry in realized.values():
                groups=entry['net_by_event']
                entry['net_without_best_event']=sum(groups.values())-max(groups.values())
            profiles[profile]={
                'counts':state['counts'], 'rejections':state['rejects'],
                'closed_records':len(state['closed']),
                'open_basis':sum(position['cost'] for position in state['positions'].values()),
                'open_positions':len(state['positions']),
                'portfolio_max_drawdown':state['drawdown'], 'realized_by_strategy':realized,
            }
        cohorts[kind]={'previously_seen_market_ids':markets,'profiles':profiles,
                       'policy_definition':value['policy']['definitions_sha256'],
                       'closed_totals':{
                           name:sum(t['pnl'] for t in profile['closed'])
                           for name,profile in checkpoint['profiles'].items()
                       }}
late={}
for kind in ('OrderBookSnapshot','BookDelta','BookReceipt','MarketSnapshot','SharedMarketFrame','ReferenceMarketFrame','StrategyCycle45'):
    rows=archive._catalog_rows("SELECT count(*) AS n,max(available_at) AS last_at FROM records WHERE kind=? AND available_at>=? AND available_at<?",
                              (kind,'2026-11-18T03:07:00+00:00','2026-11-18T04:07:00+00:00'))
    late[kind]=dict(rows[0])
result={
    'new_heldout_trades':None,'new_heldout_net_dollars':None,'decision':'no strategy advancement; holdout source completeness unestablished',
    'legacy_descriptive':historical,
    'prior_research_checkpoint':legacy['snapshot_end'],
    'prior_portfolio_drawdown_dollars':{'aggressive':26.6026709,'balanced':7.09915394},
    'prior_phase16':{k:old[k] for k in ('created_at','training_interval','heldout_interval','forecast_accuracy','cost_adjusted_quote_marks')},
    'phase16_exact_design_tokens':depth_universe,
    'known_prior_market_ids':sorted(design_markets),
    'known_prior_events':sorted(design_events),
    'descriptive_strategy_checkpoints':cohorts,
    'archive_latest_checkpoints_metadata_only':latest,'later_source_counts_metadata_only':late,
}
(HERE/'historical-scorecard.json').write_text(json.dumps(result,indent=2)+'\n')
