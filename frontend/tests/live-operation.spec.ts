import {test,expect} from '@playwright/test';
test('live-market gate and observed books render without enabling synthetic replay',async({page})=>{
 const state={mode:'live_market_paper',generated_at:'2026-11-06T00:20:00Z',scenario:'Live Polymarket · paper execution gated by real-strategy validation',bankroll:500,cash:500,exposure:0,simulated_pnl:0,realized_pnl:0,suspended:false,markets:[{market_id:'controlled-test-market',question:'Controlled browser contract',best_bid:.39,best_ask:.4,ask_depth:100,book_timestamp:'2026-11-06T00:20:00Z',book_age_seconds:1,status:'active'}],relationships:[],evidence:[],opportunities:[],positions:[],orders:[],risk_decisions:[],models:[],performance:[],alerts:['Paper trading withheld: no approved real-market strategy.'],health:[],limits:{aggregate:0.2},backtests:[],operation:{cycles:2,books:200,evaluations:200,qualified_opportunities:0,orders:0,fresh_books:80,current_books:100,fills:0,settlements:0,scan:{discovered_markets:50},validation:{active:false,passing_reports:0,blockers:['no_explicit_real_strategy_approval'],requirements:['Actual heldout labels and books']},service:{trading_status:'validation_blocked'}}};
 await page.route('**/api/state',r=>r.fulfill({json:state}));
 await page.goto('/');
 await expect(page.getByText('LIVE MARKET DATA / PAPER EXECUTION',{exact:true})).toBeVisible();
 await expect(page.getByText('VALIDATION_BLOCKED',{exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'Run deterministic replay'})).toBeDisabled();
 await page.getByRole('button',{name:'Markets',exact:true}).click();
 await expect(page.getByText('controlled-test-market',{exact:true})).toBeVisible();
 await expect(page.getByRole('columnheader',{name:'Book source time'})).toBeVisible();
 await page.getByRole('button',{name:'Models & research',exact:true}).click();
 await expect(page.getByText('no_explicit_real_strategy_approval',{exact:false})).toBeVisible();
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
});
