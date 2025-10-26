/**
 * Authentication helpers for Playwright tests.
 */
import { Page } from '@playwright/test';

export async function login(page: Page, username = 'admin', password = 'test1234') {
  await page.goto('/login');
  await page.fill('[data-testid="login-username"]', username);
  await page.fill('[data-testid="login-password"]', password);
  await page.click('[data-testid="login-submit"]');

  // Wait for redirect away from login (will redirect to / by default)
  // Use a function check instead of regex for more reliability
  await page.waitForURL(url => !url.pathname.includes('/login'), { timeout: 15000 });
}

export async function logout(page: Page) {
  // Click user menu
  await page.click('[data-testid="user-menu"]');
  await page.click('text=Logout');

  // Should redirect to login
  await page.waitForURL('/login');
}

export async function isAuthenticated(page: Page): Promise<boolean> {
  // Check if we're on dashboard or have auth token
  return page.url().includes('/dashboard');
}
