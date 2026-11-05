import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir:'./tests',workers:1,use:{baseURL:'http://127.0.0.1:18741'},
  webServer:[
    {command:'cd .. && uv run neraium-poly serve',url:'http://127.0.0.1:18740/api/health',reuseExistingServer:false},
    {command:'npm run dev -- --port 18741',url:'http://127.0.0.1:18741',reuseExistingServer:false},
  ],reporter:'list',
});
