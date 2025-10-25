/**
 * Authentication helpers for Playwright tests.
 */
import { Page } from '@playwright/test';

export async function login(page: Page, username = 'admin', password = 'admin') {
  await page.goto('/login');
  await page.fill('input[name="username"]', username);
  await page.fill('input[name="password"]', password);
  await page.click('button[type="submit"]');

  // Wait for redirect to dashboard
  await page.waitForURL('/dashboard');
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
