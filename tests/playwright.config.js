/**
 * Playwright Configuration for DockMon Testing
 */

module.exports = {
  testDir: '.',
  testMatch: '**/*test*.js',
  timeout: 30000,
  expect: {
    timeout: 5000
  },
  fullyParallel: false, // Run tests sequentially to avoid conflicts
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : 1,
  reporter: [
    ['html'],
    ['json', { outputFile: 'test-results.json' }]
  ],
  use: {
    baseURL: 'https://localhost:8001',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    ignoreHTTPSErrors: true, // For self-signed certificates
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...require('@playwright/test').devices['Desktop Chrome'],
        viewport: { width: 1280, height: 720 }
      },
    },
    {
      name: 'mobile-chrome',
      use: {
        ...require('@playwright/test').devices['Pixel 5']
      },
    }
  ],
  webServer: {
    // Assume DockMon is already running
    command: 'echo "DockMon should be running on https://localhost:8001"',
    port: 8001,
    reuseExistingServer: true,
  },
};