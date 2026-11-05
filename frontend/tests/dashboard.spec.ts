import { test, expect } from '@playwright/test';
const state={mode:'paper',generated_at:'2026-11-05T12:00:00Z',scenario:'Deterministic fixture replay',bankroll:500,cash:496,exposure:4,simulated_pnl:0,realized_pnl:0,suspended:false,markets:[],relationships:[],evidence:[],opportunities:[],positions:[],orders:[],risk_decisions:[],models:[],performance:[],alerts:['Synthetic research data'],health:[],limits:{aggregate:0.2},backtests:[]};
test('all workflows render, replay and emergency stop work',async({page})=>{
 await page.route('**/api/state',r=>r.fulfill({json:state}));
 await page.route('**/api/scenario',r=>r.fulfill({json:{ok:true}}));
 await page.route('**/api/kill-switch',r=>{state.suspended=true;return r.fulfill({json:{ok:true}})});
 await page.goto('/');await expect(page.getByRole('heading',{name:'See beyond the signals.'})).toBeVisible();
 await expect(page.getByText('PAPER TRADING',{exact:true})).toBeVisible();
 for(const name of ['Markets','Intelligence','Opportunities','Portfolio','Orders','Models & research','System']){await page.getByRole('button',{name,exact:true}).click();await expect(page.getByRole('heading',{name,exact:true,level:1})).toBeVisible();}
 await page.getByRole('button',{name:'Run deterministic replay'}).click();
 await page.getByRole('button',{name:'Emergency stop'}).click();await expect(page.getByRole('button',{name:'Trading suspended'})).toBeDisabled();
 await page.setViewportSize({width:390,height:844});await expect(page.getByRole('heading',{level:1})).toBeVisible();
});
test('service failure is visible',async({page})=>{await page.route('**/api/state',r=>r.fulfill({status:503}));await page.goto('/');await expect(page.getByRole('alert')).toContainText('API unavailable');});
