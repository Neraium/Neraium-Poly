import { defineConfig } from '@playwright/test';
export default defineConfig({
 testDir:'./tests',workers:1,use:{baseURL:'http://127.0.0.1:18940'},
 webServer:{command:'cd .. && uv run neraium-poly serve --port 18940',url:'http://127.0.0.1:18940/api/health',reuseExistingServer:false},
 reporter:'list',
});
