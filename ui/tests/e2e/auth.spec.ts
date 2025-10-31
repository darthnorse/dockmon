/**
 * Authentication E2E tests.
 * 
 * Tests critical auth workflows:
 * - Login with valid credentials
 * - Login with invalid credentials
 * - Logout
 * - Protected routes redirect to login
 */

import { test, expect } from '@playwright/test';
import { login, logout } from '../fixtures/auth';

test.describe('Authentication', () => {
  test('should login with valid credentials', async ({ page }) => {
    await page.goto('/login');
    
    // Fill login form
    await page.fill('input[name="username"]', 'admin');
    await page.fill('input[name="password"]', 'admin');
    await page.click('button[type="submit"]');

    // Should redirect to dashboard
    await page.waitForURL('/dashboard');
    expect(page.url()).toContain('/dashboard');
  });

  test('should reject invalid credentials', async ({ page }) => {
    await page.goto('/login');
    
    // Fill with wrong password
    await page.fill('input[name="username"]', 'admin');
    await page.fill('input[name="password"]', 'wrong-password');
    await page.click('button[type="submit"]');

    // Should show error message
    await expect(page.locator('text=/invalid|incorrect|wrong/i')).toBeVisible();
    
    // Should still be on login page
    expect(page.url()).toContain('/login');
  });

  test('should logout successfully', async ({ page }) => {
    // Login first
    await login(page);
    
    // Verify on dashboard
    expect(page.url()).toContain('/dashboard');

    // Logout
    await logout(page);

    // Should be back on login page
    expect(page.url()).toContain('/login');
  });

  test('should redirect to login when accessing protected route while unauthenticated', async ({ page }) => {
    // Try to access dashboard without logging in
    await page.goto('/dashboard');

    // Should redirect to login
    await page.waitForURL('/login');
    expect(page.url()).toContain('/login');
  });

  test('should maintain session after page refresh', async ({ page }) => {
    // Login
    await login(page);
    expect(page.url()).toContain('/dashboard');

    // Refresh page
    await page.reload();

    // Should still be authenticated
    await page.waitForURL('/dashboard');
    expect(page.url()).toContain('/dashboard');
  });
});
