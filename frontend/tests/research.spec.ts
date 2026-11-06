import {test,expect} from '@playwright/test';
// Controlled presentation contract; never evidence of real-market validation.
test('research deficits and null performance remain visible',async({page})=>{
 const state={mode:'live_market_paper',generated_at:'2026-11-06T00:00:00Z',scenario:'Controlled presentation contract',bankroll:500,cash:500,exposure:0,simulated_pnl:0,realized_pnl:0,suspended:false,markets:[],relationships:[],evidence:[],opportunities:[],positions:[],orders:[],risk_decisions:[],models:[],performance:[],alerts:[],health:[],limits:{},backtests:[],research:{status:'research_only',coverage:{events:250,reported_verified_outcome_groups:51,independent_verified_events:0,train_events:0,heldout_events:0,books:0,independent_context:0},candidates:[{id:'controlled-candidate',status:'not_evaluable',certification_status:'blocked',required_data_deficits:['exact_settlement_time_required']}],models:[{id:'controlled-model',status:'not_evaluable',metrics:null,reasons:['no_causal_rows']}],uncertainty_basis:'Independence has not been reviewed.'}};
 await page.route('**/api/state',r=>r.fulfill({json:state}));
 await page.goto('/');await page.getByRole('button',{name:'Models & research',exact:true}).click();
 await expect(page.getByText('Historical evidence & research',{exact:true})).toBeVisible();
 await expect(page.getByText('controlled-candidate',{exact:true})).toBeVisible();
 await expect(page.getByText('exact_settlement_time_required',{exact:false})).toBeVisible();
 await expect(page.getByText('Research reports cannot authorize trading. Explicit owner approval is required after certification.',{exact:true})).toBeVisible();
 await expect(page.getByText('controlled-model',{exact:true})).toBeVisible();
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
});
