/**
 * Global setup for Playwright tests
 * Authenticates once and saves session state for reuse across all tests
 */
import { chromium, FullConfig } from '@playwright/test';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

async function globalSetup(config: FullConfig) {
  const browser = await chromium.launch();
  const page = await browser.newPage();

  // Get base URL from config
  const baseURL = config.projects[0]?.use?.baseURL || 'http://localhost:5173';

  // Login once
  await page.goto(`${baseURL}/login`);
  await page.fill('[data-testid="login-username"]', 'admin');
  await page.fill('[data-testid="login-password"]', 'test1234');
  await page.click('[data-testid="login-submit"]');

  // Wait for redirect (more lenient - just wait for any page load)
  await page.waitForLoadState('networkidle');

  // Save authenticated state
  const storageStatePath = join(__dirname, '.auth', 'user.json');
  await page.context().storageState({ path: storageStatePath });

  await browser.close();
}

export default globalSetup;
