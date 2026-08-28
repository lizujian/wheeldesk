import { defineConfig, devices } from '@playwright/test'

const apiPort = '18000'
const webPort = '15173'
const databasePath = process.env.WHEELDESK_DB_PATH || `/tmp/wheeldesk-e2e-${process.pid}-${Date.now()}.db`

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  workers: 1,
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: {
    command: '../scripts/dev.sh',
    url: `http://127.0.0.1:${webPort}`,
    timeout: 60_000,
    reuseExistingServer: false,
    env: {
      API_PORT: apiPort,
      WEB_PORT: webPort,
      WHEELDESK_DB_PATH: databasePath,
    },
  },
})
