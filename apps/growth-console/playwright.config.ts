import {defineConfig} from '@playwright/test';
export default defineConfig({
  testDir:'./tests', fullyParallel:false, workers:1, timeout:45000,
  use:{baseURL:'http://127.0.0.1:3000', headless:true, viewport:{width:1440,height:1100},
    launchOptions:{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined,
      args:['--no-sandbox','--disable-dev-shm-usage']}},
  webServer:[
    {command:'.venv/bin/uvicorn growth.api:app --host 127.0.0.1 --port 8000 --no-access-log',
     cwd:'../..', url:'http://127.0.0.1:8000/healthz',reuseExistingServer:!process.env.CI,timeout:30000},
    {command:'npm run start',url:'http://127.0.0.1:3000',reuseExistingServer:!process.env.CI,timeout:30000},
  ],
});
