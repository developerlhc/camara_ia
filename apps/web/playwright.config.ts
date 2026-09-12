import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  timeout: 90000,
  expect: { timeout: 20000 },
  use: { channel: process.env.PLAYWRIGHT_CHANNEL || undefined, baseURL: process.env.VIGILAY_E2E_URL || 'http://localhost:3000', viewport: { width: 1440, height: 1000 }, screenshot: 'only-on-failure', trace: 'off' }
});
