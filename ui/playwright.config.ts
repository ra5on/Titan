import { defineConfig } from '@playwright/test';

// End-to-end checks run the committed build through the real Python server in
// demo mode, so they cover the same code path a NAS serves.
const port = Number(process.env.TITAN_E2E_PORT || 5099);
const python = process.env.TITAN_PYTHON || 'python3';

export default defineConfig({
  testDir: 'e2e',
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 30_000,
  reporter: [['list']],
  use: { baseURL: `http://127.0.0.1:${port}`, trace: 'retain-on-failure' },
  webServer: {
    command: `${python} -m titan.server --demo --host 127.0.0.1 --port ${port} --data ${process.env.TITAN_E2E_DATA || '.demo/e2e'}`,
    cwd: '..',
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
