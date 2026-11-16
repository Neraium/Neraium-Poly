"""Loopback read-only trader dashboard. No mutations, secrets or CDN calls."""
HTML='''<!doctype html><html><meta name="viewport" content="width=device-width,initial-scale=1"><title>Neraium shadow desk</title>
<style>body{font:15px system-ui;background:#101820;color:#e1eaf0;margin:20px}h1{font-size:22px}small{color:#a6bfcc}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}td,th{padding:9px;text-align:right;border-bottom:1px solid #304450}td:first-child,th:first-child{text-align:left}.card{background:#192832;padding:16px;margin:14px 0;border-radius:10px;overflow:auto}.bad{color:#ffb09c}button{background:#274653;color:white;border:0;padding:8px}pre{white-space:pre-wrap;font-size:12px}</style>
<h1>NERAIUM · Shadow strategy desk</h1><small>Hypothetical execution only. Three alternative $500 portfolios; strategies share each portfolio's budget. No live-order authority.</small><p id="status">Loading…</p><main id="desk"></main>
<script>
const text=x=>x==null?'unavailable':typeof x==='number'?x.toFixed(4):String(x);
function el(tag,value,parent){const n=document.createElement(tag);n.textContent=value;parent.append(n);return n}
async function refresh(){try{const r=await fetch('/api/shadow-research');if(!r.ok)throw Error('HTTP '+r.status);const d=await r.json();document.getElementById('status').textContent=d.status+' · as of '+text(d.as_of)+' · age '+text(d.age_seconds)+'s · '+text(d.markets_evaluated_unique)+' markets · '+text(d.forecasts)+' source forecasts · '+text(d.parent_events)+' parent events · '+text(d.verified_outcomes)+' verified labels';const root=document.getElementById('desk');root.replaceChildren();
for(const [name,p]of Object.entries(d.profiles||{})){const card=el('section','',root);card.className='card';el('h2',name,card);el('p','Exposure $'+text(p.exposure)+' · executable marked P/L $'+text(d.status==='fresh'?p.unrealized_net_pnl:null)+' · max drawdown $'+text(p.maximum_drawdown)+' · pending '+text(p.pending_orders),card);const table=el('table','',card);const head=el('tr','',table);['Strategy','Candidates','Orders','Fill events','Open','Exit net P/L','Verified settlement P/L','Marked P/L','Wins / losses'].forEach(x=>el('th',x,head));for(const[n,s]of Object.entries(p.strategies)){const row=el('tr','',table);[n,s.candidates,s.orders,s.fill_events,s.open_positions,s.modeled_exit_net_pnl,s.verified_settlement_net_pnl,d.status==='fresh'?s.unrealized_net_pnl:null,s.wins+' / '+s.losses].forEach(x=>el('td',text(x),row));}const details=el('details','',card);el('summary','Rejection reasons',details);el('pre',JSON.stringify(p.rejections,null,2),details);}
const c=el('section','',root);c.className='card';el('h2','Evidence and limitations',c);el('pre',JSON.stringify({scores:d.scores,calibration:d.calibration,source_withholding:d.source_withholding,runtime_error:d.runtime_error,hypotheses:d.hypotheses},null,2),c);
}catch(e){document.getElementById('status').textContent='UNAVAILABLE · '+e;document.getElementById('desk').replaceChildren();}}
refresh();setInterval(refresh,5000);
</script></html>'''


def snapshot(runtime,now):
    from neraium_poly.research.phase24.continuous import at
    report=getattr(runtime,'shadow_research_snapshot',None)
    if not report:return {'status':'withheld','reason':getattr(runtime,'shadow_research_error',None) or 'shadow research disabled or initializing','trading_authority':False}
    age=(now-at(report['as_of'])).total_seconds() if report.get('as_of') else None
    error=getattr(runtime,'shadow_research_error',None)
    return {**report,'age_seconds':age,'status':'fresh' if age is not None and 0<=age<=20 and not error else 'stale','runtime_error':error,'trading_authority':False}
