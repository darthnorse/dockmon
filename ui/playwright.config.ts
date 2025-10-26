import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright configuration for DockMon E2E tests.
 * 
 * These tests run against a real DockMon instance to verify:
 * - Critical user workflows (auth, container management, updates)
 * - UI integration with backend APIs
 * - Real-time WebSocket updates
 * 
 * Run with: npx playwright test
 */
export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,  // Run tests serially for DockMon (shared Docker state)
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,  // Single worker to avoid race conditions
  reporter: 'html',

  // Global setup: authenticate once and save session
  globalSetup: './tests/global-setup.ts',

  use: {
    baseURL: 'http://localhost:3001',  // Use 3001 to avoid conflicts
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    // Use saved authentication state from global setup
    storageState: './tests/.auth/user.json',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: {
    command: 'VITE_PORT=3001 npm run dev',  // Force Vite to use port 3001
    url: 'http://localhost:3001',
    reuseExistingServer: !process.env.CI,
    timeout: 120000,
  },
});
