import { defineConfig, devices } from '@playwright/test';
import { resolve } from 'node:path';

const python = process.env.E2E_PYTHON ?? resolve('..', 'backend', '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');

export default defineConfig({
  testDir: './e2e', fullyParallel: false, workers: 1, timeout: 45_000,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL: 'http://127.0.0.1:14200', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }, { name: 'mobile', use: { ...devices['Pixel 7'] } }],
  webServer: [
    { command: `"${python}" ../scripts/e2e-server.py`, url: 'http://127.0.0.1:18001/api/health', timeout: 60_000, reuseExistingServer: false },
    { command: 'npx ng serve --host 127.0.0.1 --port 14200 --proxy-config proxy.e2e.json', url: 'http://127.0.0.1:14200', timeout: 120_000, reuseExistingServer: false },
  ],
});
