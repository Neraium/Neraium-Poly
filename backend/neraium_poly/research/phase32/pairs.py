"""Conditional complete-set price frontiers, not verified arbitrage or orders."""
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Literal

from neraium_poly.contracts import MarketSnapshot, OrderBookSnapshot, Record
from neraium_poly.data import assess_book
from neraium_poly.experimental.account import PUBLIC_BOOK_SOURCES
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase25.dependencies import at

CAPITALS=(500,1000,10000,100000,1000000)


def pair_frontier(yes,no,*,as_of,minimum_quantity=1.,participation=.1):
    """Sweep equal quantities at successive actual asks; stop at gross break-even.

    Ten-percent displayed participation is a hypothetical latency haircut, not
    empirical queue/fill evidence. Unknown fees/settlement/leg risk stay null.
    """
    now=at(as_of)
    if not 0<participation<=.1 or not math.isfinite(minimum_quantity) or minimum_quantity<=0:raise ValueError('bounded_quantity_assumptions_required')
    books=[OrderBookSnapshot.model_validate(b) for b in (yes,no)]
    if books[0].token_id==books[1].token_id or books[0].market_id!=books[1].market_id:raise ValueError('distinct_same_market_tokens_required')
    for b in books:
        if (b.source not in PUBLIC_BOOK_SOURCES or b.exchange!='polymarket' or not assess_book(b,now,max_spread=1).healthy
            or not 0<=(now-b.available_at).total_seconds()<=15 or len(b.asks)>2048
            or len({p.price for p in b.asks})!=len(b.asks)
            or any(not math.isfinite(p.size) or p.size>1e12 for p in b.asks)):
            raise ValueError('fresh_authentic_unique_complete_depth_required')
    if abs((books[0].timestamp-books[1].timestamp).total_seconds())>2:raise ValueError('paired_source_time_skew_exceeds_2s')
    levels=[[[p.price,p.size*participation] for p in b.asks] for b in books];i=j=0;segments=[]
    while i<len(levels[0]) and j<len(levels[1]):
        a,b=levels[0][i],levels[1][j];price=a[0]+b[0]
        if price>=1-1e-12:break
        q=min(a[1],b[1]);segments.append({'yes_ask':a[0],'no_ask':b[0],'quantity':q,'conditional_gross_profit':q*(1-price)})
        a[1]-=q;b[1]-=q
        if a[1]<=1e-10:i+=1
        if b[1]<=1e-10:j+=1
    def sweep(capital):
        q=cost=gross=0.
        for s in segments:
            price=s['yes_ask']+s['no_ask'];n=min(s['quantity'],max(0.,capital-cost)/price)
            q+=n;cost+=n*price;gross+=n*(1-price)
        lot=q+1e-9>=minimum_quantity
        return {'bankroll':capital/.2 if math.isfinite(capital) else None,'capital_ceiling':capital if math.isfinite(capital) else None,
            'paired_shares':q,'acquisition_principal':cost,'conditional_gross_profit':gross,'native_minimum_size_met':lot,
            'fees':None,'slippage_and_leg_risk':None,'conservative_net_profit':None,'return_on_capital':None,
            'worst_case_acquisition_loss':cost,'actual_fill':False}
    maximum=sweep(float('inf'));scenarios=[sweep(c*.2) for c in CAPITALS]
    return {'source_book_ids':[b.id for b in books],'source_timestamps':[b.timestamp.isoformat() for b in books],
        'receipt_timestamps':[b.available_at.isoformat() for b in books],'book_sha256':[digest(b.model_dump(mode='json')) for b in books],
        'participation_assumption':participation,'minimum_paired_quantity':minimum_quantity,'levels':segments[:64],'matched_level_segments':len(segments),'level_display_scope':'first64, complete source depth bound by volume frame hash','maximum':maximum,'capital_scenarios':scenarios,
        'payout_assumption':'conditional 1USD per complementary complete set; native payoff/merge/redemption proof not established',
        'capital_scope':'hypothetical20percent ceiling, no account or risk-limit change','qualified':False,'trading_authority':False,'research_only':True}


def scan_pairs(frame,*,as_of):
    raw=frame.model_dump(mode='json') if hasattr(frame,'model_dump') else frame;now=at(as_of)
    if raw.get('mode')!='real_market_data' or not at(raw['timestamp'])<=at(raw['available_at'])<=now or len(raw['markets'])>4096 or len(raw['books'])>4096:raise ValueError('bounded_genuine_causal_frame_required')
    markets=defaultdict(list);books={};rejected=Counter();rows=[]
    for b in raw['books']:
        if b['token_id'] in books:raise ValueError('ambiguous_duplicate_book_token')
        books[b['token_id']]=b
    for m in raw['markets']:markets[m['market_id']].append(MarketSnapshot.model_validate(m))
    for market_id,ms in sorted(markets.items()):
        if len(ms)!=2 or {m.outcome.casefold() for m in ms}!={'yes','no'}:rejected['exact_binary_yes_no_metadata_required']+=1;continue
        y=next(m for m in ms if m.outcome.casefold()=='yes');n=next(m for m in ms if m.outcome.casefold()=='no')
        if (y.token_id==n.token_id or any(getattr(y,k)!=getattr(n,k) for k in ['event_id','question','resolution_rules','resolution_source','end_time'])
            or any(m.exchange!='polymarket' or m.source!='https://gamma-api.polymarket.com' or not m.timestamp<=m.available_at<=now for m in ms)
            or not y.resolution_rules or not y.resolution_source or not y.end_time or y.end_time<=now or any(m.status!='active' for m in ms)):
            rejected['exact_compatible_active_settlement_metadata_required']+=1;continue
        if any(m.token_id not in books for m in ms):rejected['paired_current_book_missing']+=1;continue
        if any(books[m.token_id]['market_id']!=market_id for m in ms):rejected['book_market_metadata_identity_mismatch']+=1;continue
        try:r=pair_frontier(books[y.token_id],books[n.token_id],as_of=now,minimum_quantity=max(y.min_order_size,n.min_order_size))
        except (ValueError,TypeError,KeyError) as e:rejected[str(e)[:120]]+=1;continue
        r.update(market_id=market_id,event_id=y.event_id,token_ids=[y.token_id,n.token_id],rules_sha256=digest(y.resolution_rules),
            question=y.question,end_time=y.end_time.isoformat(),settlement_reference=y.resolution_source,
            blockers=['native_complete_set_payout_and_settlement_proof_required','all_in_cost_and_leg_risk_evidence_required','atomic_multi_leg_execution_not_authorized'])
        if r['maximum']['conditional_gross_profit']<=0:r['blockers'].append('paired_asks_do_not_clear_1USD_gross')
        if not r['maximum']['native_minimum_size_met']:r['blockers'].append('paired_native_minimum_order_size_not_met')
        rows.append(r)
    rows.sort(key=lambda r:(-r['maximum']['conditional_gross_profit'],r['market_id']))
    return {'schema_version':'phase32-paired-depth-v1','implementation_sha256':digest(Path(__file__).read_text()),'as_of':now.isoformat(),'frame_id':raw['id'],'frame_sha256':digest(raw),
        'markets_considered':len(markets),'paired_books_evaluated':len(rows),'positive_conditional_gross_pairs':sum(r['maximum']['conditional_gross_profit']>0 for r in rows),
        'qualified_opportunities':0,'rejections':dict(rejected),'findings':rows[:24],'ranking_scope':'conditional gross only; costs/native payoff unknown, not economically qualified or guaranteed profit',
        'independent_evidence_sources':0,'sii_incremental_value':None,'actual_orders':0,'actual_fills':0,'realized_pnl':None,'research_only':True,'trading_authority':False}


class PairStudy(Record):
    volume_study_id:str
    volume_sha256:str
    report:dict
    research_only:Literal[True]=True
    trading_authority:Literal[False]=False


class PairResearch:
    def __init__(self,store,*,clock,can_write):self.store,self.clock,self.can_write=store,clock,can_write;self.report=None;self.error=None
    def observe(self,volume,frame):
        try:
            if at(volume.timestamp)>at(self.clock()):raise ValueError('pair_future_decision_forbidden')
            report=scan_pairs(frame,as_of=volume.timestamp)
            if report['frame_sha256']!=volume.decision_frame_sha256:raise ValueError('pair_volume_frame_binding_mismatch')
            if not self.can_write():raise ValueError('pair_archive_backpressure')
            if len(json.dumps(report,allow_nan=False).encode())>512*1024:raise ValueError('bounded_pair_report_required')
            identity=digest(['pair-study-v32',volume.id,report]);existing=self.store.get(identity)
            sha=digest(volume.model_dump(mode='json'))
            if existing is not None:
                saved=existing if isinstance(existing,dict) else json.loads(existing[1])
                if saved['volume_sha256']!=sha or digest(saved['report'])!=digest(report):raise ValueError('paired_record_recovery_binding_mismatch')
            else:
                now=at(self.clock());self.store.append(PairStudy(id=identity,timestamp=now,available_at=now,
                    source='neraium-poly/paired-depth/v32',volume_study_id=volume.id,volume_sha256=sha,report=report))
            self.report=report;self.error=None
        except (ValueError,TypeError,KeyError,OSError) as e:self.error=f'{type(e).__name__}:{str(e)[:160]}'
    def status(self):
        if self.report is None or self.error:return {'status':'withheld','error':self.error,'trading_authority':False}
        age=(at(self.clock())-at(self.report['as_of'])).total_seconds()
        if not 0<=age<=120:return {'status':'stale','last_at':self.report['as_of'],'trading_authority':False}
        return {**self.report,'status':'conditional_research_only','age_seconds':age}
