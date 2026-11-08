"""Append-only hypothetical sleeves; never an account or execution authority.

All sleeves share one $500 research pool and one persistent consumed-depth ledger.
A new public snapshot does not replenish hypothetical consumed liquidity. Missing
proofs never become entries, unfilled intents never become positions, and price
marks never become independently settled profits.
"""
import copy
import hashlib
import json
import math
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, Record
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase16.checkpoints import pack_checkpoint, unpack_checkpoint
from neraium_poly.research.phase24.archive import latest
from neraium_poly.research.phase25.dependencies import at

EPS = 1e-9
STRATEGIES = ('small_edge', 'high_conviction', 'cross_market', 'ensemble')


class ShadowEnrollment(Record):
    policy: dict
    research_only: Literal[True] = True
    trading_authority: Literal[False] = False


class ShadowStudy(Record):
    enrollment_id: str
    operation: str
    previous_record_id: str | None = None
    previous_record_sha256: str | None = None
    checkpoint: dict
    checkpoint_sha256: str
    events: list = Field(default_factory=list)
    decision_evidence: dict = Field(default_factory=dict)
    research_only: Literal[True] = True
    trading_authority: Literal[False] = False
    certification_authority: Literal[False] = False


def _value(record):
    return record if isinstance(record, dict) else json.loads(record[1])


def _finite(v, low=0, high=float('inf')):
    return type(v) in (int, float) and math.isfinite(v) and low <= v <= high


def _book_ok(book, now):
    return (book.complete and book.source in PUBLIC_BOOK_SOURCES and book.bids and book.asks
            and book.timestamp <= book.available_at <= now
            and 0 <= (now-book.timestamp).total_seconds() <= 15)


class ShadowResearch:
    def __init__(self, store, *, clock, can_write, candidate_verifier=None, outcome_verifier=None):
        self.store, self.clock, self.can_write = store, clock, can_write
        self.candidate_verifier, self.outcome_verifier = candidate_verifier, outcome_verifier
        self.error = None
        self.last_record = None
        policy = {'version': 'phase28-shadow-v1', 'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  'publication_namespace': digest(str(getattr(store, 'directory', getattr(store, 'path', 'controlled-store')))),
                  'strategies': list(STRATEGIES), 'capital_scope': 'one hypothetical500USD shared research pool; not a paper account',
                  'capital': 500., 'aggregate_exposure': 100., 'event_exposure': 50., 'correlation_exposure': 50.,
                  'standard_notional': 5., 'high_conviction_notional': 10., 'minimum_order_notional': 2.,
                  'latency_seconds': .25, 'expiry_seconds': 60, 'liquidity_participation': .1,
                  'minimum_research_edge': 0., 'daily_loss_limit': 25., 'drawdown_limit': 50.,
                  'maximum_seen_forecasts': 16384, 'maximum_depth_keys': 16384,
                  'shared_depth': 'cumulative hypothetical ask consumption; new snapshot alone never replenishes',
                  'fill_assumptions': 'next fresh native book after latency, limit/depth constrained; entry+known settlement costs charged at fill',
                  'promotions': False, 'actual_account_routing': False}
        self.enrollment_id = digest(['shadow-enrollment', policy])
        now = at(clock())
        existing = store.get(self.enrollment_id)
        if existing is None:
            if not can_write():raise ValueError('shadow enrollment archive unavailable')
            store.append(ShadowEnrollment(id=self.enrollment_id, timestamp=now, available_at=now,
                source='neraium-poly/shadow/v28', policy=policy))
        elif _value(existing).get('policy') != policy:
            raise ValueError('shadow enrollment identity mismatch')
        self.state = {'sequence': 0, 'last_at': None, 'last_input_key': None, 'cash': 500.,
                      'orders': {}, 'positions': {}, 'seen': [], 'depth_used': {}, 'settled_ids': [],
                      'settled_events': [], 'realized_pnl': 0., 'settlement_count': 0, 'fill_count': 0,
                      'order_count': 0, 'canceled': 0, 'expired': 0, 'evaluations': 0,
                      'day': now.date().isoformat(), 'day_realized': 0., 'peak_equity': 500.,
                      'unrealized_pnl': None, 'drawdown': None, 'mark_status': 'no_filled_positions',
                      'suspended': False, 'suspension_reason': None, 'rejections': {},
                      'strategies': {s: {'orders': 0, 'fills': 0, 'settlements': 0, 'realized_pnl': 0., 'suspended': False} for s in STRATEGIES}}
        rows = latest(store, 'ShadowStudy', limit=1)
        if rows and rows[0]['enrollment_id'] == self.enrollment_id:self._adopt(rows[0])

    def _adopt(self, value):
        record = ShadowStudy.model_validate(value)
        if record.enrollment_id != self.enrollment_id:raise ValueError('shadow recovery enrollment mismatch')
        if at(record.available_at) > at(self.clock()):raise ValueError('shadow recovery clock regression')
        state = unpack_checkpoint(record.checkpoint)
        if digest(state) != record.checkpoint_sha256:raise ValueError('shadow checkpoint checksum mismatch')
        if record.previous_record_id is not None:
            previous = self.store.get(record.previous_record_id)
            if previous is None or digest(_value(previous)) != record.previous_record_sha256:
                raise ValueError('shadow journal predecessor integrity mismatch')
        if not _finite(state['cash']) or len(state['seen']) > 16384 or len(state['depth_used']) > 16384:
            raise ValueError('shadow recovery state bounds violated')
        if len(state['orders']) > 128 or len(state['positions']) > 128:
            raise ValueError('shadow active state bounds violated')
        self.state, self.last_record = state, record.model_dump(mode='json')

    def _recover_ack(self, now):
        identity = f'shadow:{self.enrollment_id}:{self.state["sequence"]+1:012d}'
        previous = self.store.get(identity)
        if previous is None:return False
        value = _value(previous)
        if at(value['available_at']) > now:raise ValueError('shadow recovery clock regression')
        self._adopt(value)
        return True

    def _commit(self, state, events, evidence, now, operation):
        if not self.can_write():raise ValueError('shadow archive backpressure')
        state['sequence'] = self.state['sequence']+1;state['last_at'] = now.isoformat()
        if len(state['seen']) > 16384 or len(state['depth_used']) > 16384:
            raise ValueError('shadow retained evidence identity budget exhausted; no silent deletion')
        record = ShadowStudy(id=f'shadow:{self.enrollment_id}:{state["sequence"]:012d}', timestamp=now,
            available_at=now, source='neraium-poly/shadow/v28', enrollment_id=self.enrollment_id, operation=operation,
            previous_record_id=self.last_record['id'] if self.last_record else None,
            previous_record_sha256=digest(self.last_record) if self.last_record else None,
            checkpoint=pack_checkpoint(state), checkpoint_sha256=digest(state), events=events, decision_evidence=evidence)
        if len(record.model_dump_json().encode()) > 8*1024**2:
            raise ValueError('shadow journal byte budget exceeded; no partial publication')
        self.store.append(record)
        self.state, self.last_record = state, record.model_dump(mode='json');self.error = None

    @staticmethod
    def _exposure(state, *, event=None, clusters=None):
        total = 0.
        for x in [*state['orders'].values(), *state['positions'].values()]:
            if event is not None and x['event_id'] != event:continue
            if clusters is not None and not set(x['clusters']).intersection(clusters):continue
            total += x.get('reserved', 0.)+x.get('cost', 0.)
        return total

    def _proof(self, row, raw, book, now):
        if row.get('shadow_eligible') is not True or row.get('qualified_research') is not True:
            raise ValueError('candidate_not_conservative_evidence_qualified')
        if row.get('trading_authority') is not False or row.get('research_only') is not True:
            raise ValueError('research_authority_boundary')
        if not callable(self.candidate_verifier):raise TypeError('independent_candidate_proof_replay_unavailable')
        if (row.get('book_sha256') != digest(book.model_dump(mode='json'))
                or row.get('frame_sha256') != digest(raw) or at(row['decision_at']) != now):
            raise ValueError('current_decision_book_and_frame_binding_required')
        metadata = [MarketSnapshot.model_validate(x) for x in raw.get('markets', []) if x.get('token_id') == row['token_id']]
        if len(metadata) != 1 or metadata[0].market_id != row['market_id'] or metadata[0].event_id != row['event_id']:
            raise ValueError('exact_event_and_token_metadata_required')
        if metadata[0].status != 'active' or max(metadata[0].timestamp, metadata[0].available_at) > now:
            raise ValueError('active_point_in_time_metadata_required')
        proof = self.candidate_verifier(row, raw, as_of=now)
        if not isinstance(proof, dict) or proof.get('verified') is not True:
            raise ValueError('independent_candidate_proof_replay_failed')
        for key in ('forecast_id', 'event_id', 'market_id', 'token_id'):
            if proof.get(key) != row.get(key):raise ValueError('candidate_proof_identity_mismatch')
        if proof.get('finding_id') != row['id'] or proof.get('book_sha256') != digest(book.model_dump(mode='json')):
            raise ValueError('candidate_proof_book_or_finding_mismatch')
        if not all(proof.get(k) is True for k in ('calibration_verified', 'settlement_rules_verified', 'native_costs_verified')):
            raise ValueError('candidate_calibration_cost_or_rules_unverified')
        if not at(proof['evidence_available_at']) <= at(proof['forecast_at']) <= now:
            raise ValueError('candidate_evidence_availability_invalid')
        if (now-at(proof['forecast_at'])).total_seconds() > 300 or at(proof['event_end_time']) <= now:
            raise ValueError('candidate_forecast_stale_or_event_ended')
        if (not _finite(proof.get('lower_payout'), 0, 1) or not _finite(proof.get('expected_payout'), 0, 1)
                or not _finite(proof.get('upper_payout'), 0, 1)
                or not proof['lower_payout'] <= proof['expected_payout'] <= proof['upper_payout']):raise ValueError('supported_payout_interval_required')
        for k in ('fee_rate', 'slippage_per_share', 'settlement_cost_per_share'):
            if not _finite(proof.get(k), 0, 1):raise ValueError('known_finite_execution_costs_required')
        if not isinstance(proof.get('resolution_rules_sha256'), str) or len(proof['resolution_rules_sha256']) != 64:
            raise ValueError('exact_resolution_rules_required')
        if not _finite(proof.get('min_order_size'), EPS) or abs(proof['min_order_size']-metadata[0].min_order_size) > EPS:
            raise ValueError('exact_current_native_minimum_order_size_required')
        if any(abs(level.price/metadata[0].tick_size-round(level.price/metadata[0].tick_size)) > 1e-7 for level in (*book.bids,*book.asks)):
            raise ValueError('current_book_price_tick_mismatch')
        if hashlib.sha256(metadata[0].resolution_rules.encode()).hexdigest() != proof['resolution_rules_sha256']:
            raise ValueError('exact_resolution_rules_required')
        return {**proof, 'native_tick_size': metadata[0].tick_size}

    def _fills(self, state, books, markets, now, events, evidence):
        for oid, order in list(state['orders'].items()):
            if now >= at(order['expires_at']):
                events.append({'type': 'expired', 'order_id': oid});state['expired'] += 1;del state['orders'][oid];continue
            book = books.get(order['token_id']);metadata = markets.get(order['token_id'])
            if (metadata is None or metadata.status != 'active' or metadata.event_id != order['event_id']
                    or metadata.tick_size != order['tick_size'] or metadata.min_order_size != order['min_order_size']
                    or hashlib.sha256(metadata.resolution_rules.encode()).hexdigest() != order['resolution_rules_sha256']):continue
            if book is None or book.market_id != order['market_id'] or not _book_ok(book, now):continue
            if book.timestamp < at(order['created_at'])+timedelta(seconds=.25):continue
            evidence['books'][book.id] = book.model_dump(mode='json')
            quantity, spent, principal, fees, slip, settlement = 0., 0., 0., 0., 0., 0.
            for level in book.asks:
                cost = level.price*(1+order['fee_rate'])+order['slippage_per_share']+order['settlement_cost_per_share']
                if level.price > order['limit_price']+EPS or cost >= order['lower_payout']-EPS:break
                key = digest([order['token_id'], level.price]);used = state['depth_used'].get(key, 0.)
                available = max(0., level.size*.1-used)
                amount = min(available, max(0., order['remaining_quantity']-quantity), max(0., order['reserved']-spent)/cost)
                if amount <= EPS:continue
                quantity += amount;spent += amount*cost;principal += amount*level.price
                fees += amount*level.price*order['fee_rate'];slip += amount*order['slippage_per_share'];settlement += amount*order['settlement_cost_per_share']
                state['depth_used'][key] = used+amount
            if quantity <= EPS:continue
            state['cash'] -= spent;order['reserved'] -= spent;order['remaining_quantity'] -= quantity
            position = state['positions'].setdefault(oid, {k: v for k, v in order.items() if k not in ('reserved', 'remaining_quantity', 'limit_price')})
            position.setdefault('quantity', 0.);position.setdefault('cost', 0.)
            position['quantity'] += quantity;position['cost'] += spent
            position.setdefault('first_fill_at', now.isoformat());position['last_fill_at'] = now.isoformat()
            state['fill_count'] += 1;state['strategies'][order['strategy']]['fills'] += 1
            events.append({'type': 'hypothetical_fill', 'order_id': oid, 'quantity': quantity, 'principal': principal,
                           'entry_fees': fees, 'slippage': slip, 'prepaid_settlement_cost': settlement,
                           'book_id': book.id, 'book_sha256': digest(book.model_dump(mode='json')),
                           'source_timestamp': book.timestamp.isoformat(), 'received_at': book.available_at.isoformat(),
                           'actual_fill': False, 'price_impact_scope': 'displayed asks consumed; unseen impact/future replenishment unavailable'})
            if order['remaining_quantity'] <= EPS or order['reserved'] <= EPS:del state['orders'][oid]

    @staticmethod
    def _mark(state, books, now):
        if not state['positions']:
            state['unrealized_pnl'] = None;state['mark_status'] = 'no_filled_positions';return
        used, pnl = {}, 0.
        for position in state['positions'].values():
            book = books.get(position['token_id']);rate = position.get('exit_fee_rate')
            if book is None or not _book_ok(book, now) or not _finite(rate, 0, 1):
                state['unrealized_pnl'] = None;state['drawdown'] = None;state['mark_status'] = 'fresh_exit_depth_and_verified_exit_fee_required';return
            remaining, proceeds = position['quantity'], 0.
            for level in book.bids:
                key = (book.token_id, level.price);available = max(0., level.size*.1-used.get(key, 0.))
                q = min(remaining, available);remaining -= q;used[key] = used.get(key, 0.)+q
                proceeds += q*max(0., level.price*(1-rate)-position['slippage_per_share'])
            if remaining > EPS:
                state['unrealized_pnl'] = None;state['drawdown'] = None;state['mark_status'] = 'incomplete_exit_liquidity';return
            pnl += proceeds-position['cost']
        state['unrealized_pnl'] = pnl;state['mark_status'] = 'full_displayed_bid_liquidation_model'
        equity = state['cash']+sum(p['cost'] for p in state['positions'].values())+pnl
        state['peak_equity'] = max(state['peak_equity'], equity);state['drawdown'] = max(0., state['peak_equity']-equity)
        if state['drawdown'] >= 50-EPS:state['suspended'] = True;state['suspension_reason'] = 'shadow_drawdown_limit'

    def step(self, report, frame):
        now = at(self.clock())
        if not self.can_write():return False
        if self._recover_ack(now):return False
        if self.state['last_at'] and now < at(self.state['last_at']):raise ValueError('shadow clock regression')
        raw = frame.model_dump(mode='json') if hasattr(frame, 'model_dump') else frame
        rows = report.get('findings', [])
        if not isinstance(rows, list) or len(rows) > 128:raise ValueError('bounded shadow findings required')
        input_key = digest([digest(report), digest(raw)])
        if input_key == self.state['last_input_key']:return False
        if report.get('research_only') is not True or report.get('trading_authority') is not False:
            raise ValueError('shadow input research boundary required')
        state = copy.deepcopy(self.state);state['last_input_key'] = input_key;state['evaluations'] += 1
        if state['day'] != now.date().isoformat():state['day'] = now.date().isoformat();state['day_realized'] = 0.
        events = [];evidence = {'frame_id': raw.get('id'), 'frame_sha256': digest(raw), 'report_sha256': digest(report), 'books': {}}
        books = {}
        if not isinstance(raw, dict) or len(raw.get('books', [])) > 2048 or len(raw.get('markets', [])) > 2048:
            raise ValueError('bounded shadow market frame required')
        markets = {}
        for value in raw.get('markets', []):
            m = MarketSnapshot.model_validate(value)
            if m.token_id in markets and digest(markets[m.token_id].model_dump(mode='json')) != digest(m.model_dump(mode='json')):
                raise ValueError('ambiguous shadow market identity')
            markets[m.token_id] = m
        total_levels = 0
        for value in raw.get('books', []):
            if len(value.get('asks', []))+len(value.get('bids', [])) > 4096:
                raise ValueError('shadow native book level budget exceeded')
            b = OrderBookSnapshot.model_validate(value)
            total_levels += len(b.asks)+len(b.bids)
            if total_levels > 100000:raise ValueError('shadow global book level budget exceeded')
            if b.token_id in books and digest(books[b.token_id].model_dump(mode='json')) != digest(b.model_dump(mode='json')):
                raise ValueError('ambiguous shadow native book identity')
            books[b.token_id] = b
        if state['suspended']:
            for oid in list(state['orders']):
                events.append({'type': 'suspension_cancel', 'order_id': oid});state['canceled'] += 1;del state['orders'][oid]
        self._fills(state, books, markets, now, events, evidence);self._mark(state, books, now)
        if state['suspended']:
            for oid in list(state['orders']):
                events.append({'type': 'suspension_cancel', 'order_id': oid});state['canceled'] += 1;del state['orders'][oid]
        rejected = Counter(state['rejections'])
        for row in sorted(rows, key=lambda r: (-(r.get('conservative_expected_net_profit') or 0), r['id'])):
            for strategy in STRATEGIES:
                reason = None
                try:
                    if strategy not in row.get('strategy_eligibility', []):raise ValueError('strategy_evidence_not_eligible')
                    if state['suspended'] or state['strategies'][strategy]['suspended']:raise ValueError('shadow_suspended')
                    if state['positions'] and state['unrealized_pnl'] is None:raise ValueError('portfolio_valuation_incomplete')
                    key = digest([self.enrollment_id, strategy, row['forecast_id']])
                    if key in state['seen']:raise ValueError('duplicate_forecast_strategy')
                    book = books.get(row['token_id'])
                    if book is None or book.market_id != row['market_id'] or not _book_ok(book, now):raise ValueError('fresh_exact_execution_book_required')
                    if not _finite(row.get('conservative_expected_net_profit'), EPS):raise ValueError('positive_conservative_dollar_profit_required')
                    proof = self._proof(row, raw, book, now)
                    if strategy == 'high_conviction' and (proof.get('independent_source_groups', 0) < 2 or proof.get('forecast_uncertainty', 1) > .1 or proof['upper_payout']-proof['lower_payout'] > .1):raise ValueError('independent_high_conviction_evidence_required')
                    if strategy == 'cross_market' and (not proof.get('cross_market_directional_edge_verified') or row.get('legs')):raise ValueError('verified_standalone_cross_market_edge_required')
                    if strategy == 'ensemble' and not proof.get('ensemble_chronological_validation_verified'):raise ValueError('chronological_ensemble_validation_required')
                    groups = sorted(set(row.get('correlation', {}).get('dependency_tags', [])) | {row.get('correlation', {}).get('canonical_group_id') or 'unknown-correlation'})
                    requested = 10. if strategy == 'high_conviction' else 5.
                    available = min(state['cash']-sum(x['reserved'] for x in state['orders'].values()),
                                    100.-self._exposure(state), 50.-self._exposure(state, event=row['event_id']),
                                    50.-self._exposure(state, clusters=groups), requested)
                    if available < 2-EPS:raise ValueError('shadow_capital_or_concentration_limit')
                    cost = book.asks[0].price*(1+proof['fee_rate'])+proof['slippage_per_share']+proof['settlement_cost_per_share']
                    if proof['lower_payout']-cost <= EPS:raise ValueError('nonpositive_conservative_unit_profit_after_costs')
                    quantity = available/cost;minimum = proof.get('min_order_size')
                    if not _finite(minimum, EPS) or quantity+EPS < minimum:raise ValueError('minimum_executable_order_quantity_unavailable')
                    state['seen'].append(key);state['orders'][key] = {'id': key, 'strategy': strategy, 'finding_id': row['id'],
                        'forecast_id': row['forecast_id'], 'market_id': row['market_id'], 'token_id': row['token_id'], 'event_id': row['event_id'],
                        'resolution_rules_sha256': proof['resolution_rules_sha256'], 'clusters': groups, 'created_at': now.isoformat(),
                        'forecast_at': proof['forecast_at'], 'event_end_time': proof['event_end_time'], 'expires_at': min(now+timedelta(seconds=60), at(proof['event_end_time'])).isoformat(),
                        'reserved': available, 'remaining_quantity': quantity,
                        'tick_size': proof['native_tick_size'], 'min_order_size': proof['min_order_size'],
                        'limit_price': min(.999999999, math.floor(((proof['lower_payout']-proof['slippage_per_share']-proof['settlement_cost_per_share'])/(1+proof['fee_rate'])-EPS)/proof['native_tick_size'])*proof['native_tick_size']),
                        'lower_payout': proof['lower_payout'], 'expected_payout': proof['expected_payout'], 'fee_rate': proof['fee_rate'],
                        'slippage_per_share': proof['slippage_per_share'], 'settlement_cost_per_share': proof['settlement_cost_per_share'], 'exit_fee_rate': proof.get('exit_fee_rate'),
                        'evidence_proof_sha256': digest(proof)}
                    evidence['books'][book.id] = book.model_dump(mode='json');events.append({'type': 'hypothetical_intent', 'order_id': key, 'strategy': strategy,
                        'finding': row, 'proof': proof, 'book_id': book.id, 'source_timestamp': book.timestamp.isoformat(), 'reserved': available, 'actual_order': False})
                    state['order_count'] += 1;state['strategies'][strategy]['orders'] += 1
                except (ValueError, KeyError, TypeError) as error:reason = str(error)[:160]
                if reason:
                    rejected[reason] += 1;events.append({'type': 'rejected', 'finding_id': row.get('id'), 'strategy': strategy, 'reason': reason})
        state['rejections'] = dict(rejected)
        self._commit(state, events, evidence, now, 'research_cycle');return True

    def cancel(self, order_id, *, reason='operator_research_cancel'):
        now = at(self.clock())
        if not self.can_write():return False
        if self._recover_ack(now):return False
        if self.state['last_at'] and now < at(self.state['last_at']):raise ValueError('shadow clock regression')
        if order_id not in self.state['orders']:return False
        state = copy.deepcopy(self.state);del state['orders'][order_id];state['canceled'] += 1
        self._commit(state, [{'type': 'canceled', 'order_id': order_id, 'reason': str(reason)[:160]}], {}, now, 'cancel');return True

    def settle(self, proof):
        now = at(self.clock())
        if not self.can_write():return False
        if self._recover_ack(now):return False
        if self.state['last_at'] and now < at(self.state['last_at']):raise ValueError('shadow clock regression')
        if not callable(self.outcome_verifier):raise TypeError('independent_final_outcome_replay_required')
        identity = proof.get('position_id');position = self.state['positions'].get(identity)
        if identity in self.state['settled_ids']:return False
        if position is None:raise ValueError('exact_open_shadow_position_required')
        verified = self.outcome_verifier(proof, position, as_of=now)
        if not isinstance(verified, dict) or verified.get('verified') is not True:raise ValueError('independent_outcome_replay_failed')
        if any(verified.get(k) != position[k] for k in ('market_id', 'token_id', 'event_id', 'forecast_id', 'resolution_rules_sha256')):
            raise ValueError('settlement_identity_or_rules_mismatch')
        if verified.get('final') is not True or verified.get('disputed') is not False:
            raise ValueError('final_undisputed_outcome_required')
        if not at(position['last_fill_at']) < at(verified['resolved_at']) <= at(verified['available_at']) <= now:
            raise ValueError('prospective_settlement_time_order_invalid')
        if not _finite(verified.get('payout_per_share'), 0, 1) or not isinstance(verified.get('source_sha256'), str) or len(verified['source_sha256']) != 64:
            raise ValueError('independent_exact_payout_provenance_required')
        state = copy.deepcopy(self.state)
        if state['day'] != now.date().isoformat():state['day'] = now.date().isoformat();state['day_realized'] = 0.
        payout = verified['payout_per_share']*position['quantity'];pnl = payout-position['cost']
        state['cash'] += payout;state['realized_pnl'] += pnl;state['day_realized'] += pnl;state['settlement_count'] += 1
        state['strategies'][position['strategy']]['settlements'] += 1;state['strategies'][position['strategy']]['realized_pnl'] += pnl
        if state['strategies'][position['strategy']]['realized_pnl'] <= -25:state['strategies'][position['strategy']]['suspended'] = True
        state['settled_ids'].append(identity);state['settled_events'] = sorted(set(state['settled_events']) | {position['event_id']});del state['positions'][identity]
        state['orders'].pop(identity, None)
        state['unrealized_pnl'] = None;state['drawdown'] = None;state['mark_status'] = 'awaiting_fresh_remaining_positions'
        if not state['positions']:
            state['peak_equity'] = max(state['peak_equity'], state['cash'])
            state['drawdown'] = max(0., state['peak_equity']-state['cash'])
            state['unrealized_pnl'] = 0.;state['mark_status'] = 'verified_settled_cash_only'
        if state['day_realized'] <= -25 or state['cash']+sum(x['cost'] for x in state['positions'].values()) <= 450:
            state['suspended'] = True;state['suspension_reason'] = 'shadow_loss_limit'
        self._commit(state, [{'type': 'independently_verified_hypothetical_settlement', 'position_id': identity, 'payout': payout, 'realized_simulated_pnl': pnl, 'proof': verified}], {}, now, 'settlement');return True

    def status(self):
        s = self.state
        strategies = copy.deepcopy(s['strategies'])
        for name, values in strategies.items():
            values['realized_pnl'] = values['realized_pnl'] if values['settlements'] else None
            values['positions'] = sum(p['strategy'] == name for p in s['positions'].values())
            values['reserved'] = sum(o['reserved'] for o in s['orders'].values() if o['strategy'] == name)
            values['exposure'] = values['reserved']+sum(p['cost'] for p in s['positions'].values() if p['strategy'] == name)
        return {'status': 'research_only', 'enrollment_id': self.enrollment_id, 'last_at': s['last_at'],
                'capital_scope': 'single hypothetical500USD shared pool, not certified/experimental account capital',
                'hypothetical_cash': s['cash'], 'capital_reserved': sum(o['reserved'] for o in s['orders'].values()),
                'positions': len(s['positions']), 'position_quantity': sum(p['quantity'] for p in s['positions'].values()),
                'exposure': self._exposure(s), 'capital_utilization': self._exposure(s)/500., 'orders_attempted': s['order_count'], 'pending_orders': len(s['orders']),
                'hypothetical_fills': s['fill_count'], 'canceled': s['canceled'], 'expired': s['expired'],
                'realized_simulated_pnl': s['realized_pnl'] if s['settlement_count'] else None,
                'unrealized_simulated_pnl': s['unrealized_pnl'], 'drawdown': s['drawdown'], 'mark_status': s['mark_status'],
                'verified_settled_parent_events': len(s['settled_events']), 'statistically_independent_events': None, 'settlements': s['settlement_count'],
                'suspended': s['suspended'], 'suspension_reason': s['suspension_reason'], 'strategies': strategies,
                'rejections': dict(s['rejections']), 'runtime_error': self.error, 'research_only': True,
                'trading_authority': False, 'certification_authority': False, 'actual_account_access': False}
