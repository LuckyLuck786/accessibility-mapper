import { defineConfig, devices } from '@playwright/test'

/**
 * e2e test configuration for the accessibility-mapper frontend.
 *
 * Two projects:
 *  - mobile  : iPhone SE / 375×812 — guards the mobile layout fixes.
 *  - desktop : 1280×800 — sanity-checks the desktop rendering too.
 *
 * The Vite dev server is started automatically and API calls are mocked
 * in-test via page.route(), so no FastAPI backend is required.
 */
export default defineConfig({
  testDir: 'tests',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'mobile',
      use: { browserName: 'chromium', viewport: { width: 375, height: 812 }, userAgent: 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36' },
    },
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } },
    },
  ],
  webServer: {
    command: 'npx vite',
    url: 'http://localhost:5173',
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
  },
})
