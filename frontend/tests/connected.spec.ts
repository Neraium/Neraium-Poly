import { test, expect } from '@playwright/test';
test('connected paper workflow exposes audited fills and latches emergency stop',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/');
 await expect(page.getByRole('heading',{name:'See beyond the signals.'})).toBeVisible();
 await expect(page.getByText('Synthetic research data; no claim of real-market profitability.')).toBeVisible();
 await page.getByRole('button',{name:'Orders',exact:true}).click();
 await expect(page.getByText('fixture-paper-order',{exact:true})).toBeVisible();
 await expect(page.getByText('filled',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Portfolio',exact:true}).click();
 await expect(page.getByText('fixture-a',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Run deterministic replay'}).click();
 await page.getByRole('button',{name:'Emergency stop'}).click();
 await expect(page.getByRole('button',{name:'Trading suspended'})).toBeDisabled();
 const response=await page.request.post('http://127.0.0.1:18740/api/scenario');
 expect(response.status()).toBe(409);expect(errors).toEqual([]);
});
