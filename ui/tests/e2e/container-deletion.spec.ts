/**
 * E2E tests for container deletion feature
 */

import { test, expect } from '@playwright/test';

test.describe('Container Deletion', () => {
  test.beforeEach(async ({ page }) => {
    // Login and navigate to containers list page
    await page.goto('/login');
    await page.fill('input[name="username"]', 'admin');
    await page.fill('input[name="password"]', 'admin');
    await page.click('button[type="submit"]');
    await page.waitForURL('/');

    // Navigate to containers page
    await page.goto('/containers');
    await page.waitForLoadState('networkidle');
  });

  test('User can delete normal container', async ({ page }) => {
    // Find a non-DockMon container row and click to open modal
    const containerRow = page.locator('table tbody tr').filter({ hasNotText: /dockmon/i }).first();
    await containerRow.click();

    // Wait for ContainerDetailsModal to open
    await expect(page.locator('div[role="dialog"]')).toBeVisible();

    // Find and click Delete button in modal header
    const deleteButton = page.locator('div[role="dialog"] button:has-text("Delete")');
    await expect(deleteButton).toBeVisible();
    await expect(deleteButton).toBeEnabled();
    await deleteButton.click();

    // Confirm deletion dialog appears
    await expect(page.locator('[data-testid="delete-container-dialog"]')).toBeVisible();
    await expect(page.locator('text=/Are you sure you want to delete/i')).toBeVisible();

    // Confirm deletion (click the Delete button in the dialog, not the modal)
    const confirmButton = page.locator('[data-testid="delete-container-dialog"] button:has-text("Delete")');
    await confirmButton.click();

    // Verify success notification
    await expect(page.locator('text=/deleted successfully/i')).toBeVisible({ timeout: 5000 });

    // Modal should close after successful deletion
    await expect(page.locator('div[role="dialog"]')).not.toBeVisible({ timeout: 3000 });
  });

  test('User sees enhanced warning for protected container', async ({ page }) => {
    // Find a database container (postgres, mysql, etc.)
    const dbContainerRow = page.locator('table tbody tr').filter({ hasText: /postgres|mysql|mariadb|mongodb|redis/i }).first();

    const count = await dbContainerRow.count();
    if (count === 0) {
      test.skip('No database containers found to test protected deletion');
      return;
    }

    // Open modal
    await dbContainerRow.click();
    await expect(page.locator('div[role="dialog"]')).toBeVisible();

    // Click Delete button
    const deleteButton = page.locator('div[role="dialog"] button:has-text("Delete")');
    await deleteButton.click();

    // Enhanced warning should appear in dialog
    await expect(page.locator('[data-testid="delete-container-dialog"]')).toBeVisible();
    await expect(page.locator('text=/appears to be a/i')).toBeVisible();
    await expect(page.locator('text=/database|proxy|monitoring/i')).toBeVisible();
  });

  test('User cannot delete DockMon container', async ({ page }) => {
    // Find DockMon container row
    const dockmonRow = page.locator('table tbody tr').filter({ hasText: /^dockmon$/i }).first();

    const count = await dockmonRow.count();
    if (count === 0) {
      test.skip('DockMon container not found');
      return;
    }

    // Open modal
    await dockmonRow.click();
    await expect(page.locator('div[role="dialog"]')).toBeVisible();

    // Delete button should be disabled
    const deleteButton = page.locator('div[role="dialog"] button:has-text("Delete")');
    await expect(deleteButton).toBeVisible();
    await expect(deleteButton).toBeDisabled();
  });

  test('User can choose to remove volumes', async ({ page }) => {
    const containerRow = page.locator('table tbody tr').filter({ hasNotText: /dockmon/i }).first();
    await containerRow.click();

    // Wait for modal
    await expect(page.locator('div[role="dialog"]')).toBeVisible();

    // Click Delete
    const deleteButton = page.locator('div[role="dialog"] button:has-text("Delete")');
    await deleteButton.click();

    // Dialog appears with volume checkbox
    await expect(page.locator('[data-testid="delete-container-dialog"]')).toBeVisible();

    const volumeCheckbox = page.locator('[data-testid="delete-container-dialog"] input[type="checkbox"]');
    await expect(volumeCheckbox).toBeVisible();

    // Should be unchecked by default (safe default)
    await expect(volumeCheckbox).not.toBeChecked();

    // Check the checkbox
    await volumeCheckbox.check();
    await expect(volumeCheckbox).toBeChecked();

    // Cancel instead of actually deleting
    const cancelButton = page.locator('[data-testid="delete-container-dialog"] button:has-text("Cancel")');
    await cancelButton.click();

    // Dialog closes
    await expect(page.locator('[data-testid="delete-container-dialog"]')).not.toBeVisible();
  });

  test('User can choose to keep volumes', async ({ page }) => {
    const containerRow = page.locator('table tbody tr').filter({ hasNotText: /dockmon/i }).first();
    await containerRow.click();

    await expect(page.locator('div[role="dialog"]')).toBeVisible();

    const deleteButton = page.locator('div[role="dialog"] button:has-text("Delete")');
    await deleteButton.click();

    // Dialog appears
    await expect(page.locator('[data-testid="delete-container-dialog"]')).toBeVisible();

    const volumeCheckbox = page.locator('[data-testid="delete-container-dialog"] input[type="checkbox"]');

    // Leave unchecked (keep volumes)
    await expect(volumeCheckbox).not.toBeChecked();

    // Cancel instead of actually deleting
    const cancelButton = page.locator('[data-testid="delete-container-dialog"] button:has-text("Cancel")');
    await cancelButton.click();

    await expect(page.locator('[data-testid="delete-container-dialog"]')).not.toBeVisible();
  });

  test('Cancel button works', async ({ page }) => {
    const containerRow = page.locator('table tbody tr').filter({ hasNotText: /dockmon/i }).first();
    await containerRow.click();

    await expect(page.locator('div[role="dialog"]')).toBeVisible();

    const deleteButton = page.locator('div[role="dialog"] button:has-text("Delete")');
    await deleteButton.click();

    // Dialog appears
    await expect(page.locator('[data-testid="delete-container-dialog"]')).toBeVisible();

    // Click cancel
    const cancelButton = page.locator('[data-testid="delete-container-dialog"] button:has-text("Cancel")');
    await cancelButton.click();

    // Dialog closes
    await expect(page.locator('[data-testid="delete-container-dialog"]')).not.toBeVisible();

    // Modal should still be open
    await expect(page.locator('div[role="dialog"]')).toBeVisible();
  });

  test('Stop button has less prominent styling than Delete', async ({ page }) => {
    // Find a running container
    const runningContainerRow = page.locator('table tbody tr').filter({ hasText: /running/i }).filter({ hasNotText: /dockmon/i }).first();

    const count = await runningContainerRow.count();
    if (count === 0) {
      test.skip('No running non-DockMon containers found');
      return;
    }

    await runningContainerRow.click();
    await expect(page.locator('div[role="dialog"]')).toBeVisible();

    const stopButton = page.locator('div[role="dialog"] button:has-text("Stop")');
    const deleteButton = page.locator('div[role="dialog"] button:has-text("Delete")');

    // Both buttons should exist
    await expect(stopButton).toBeVisible();
    await expect(deleteButton).toBeVisible();

    // Delete button should have bg-red-600 class (solid background)
    const deleteClasses = await deleteButton.getAttribute('class');
    expect(deleteClasses).toMatch(/bg-red-600/);

    // Stop button should have border-red variant (less prominent)
    const stopClasses = await stopButton.getAttribute('class');
    expect(stopClasses).toMatch(/border-red/);
    expect(stopClasses).not.toMatch(/bg-red-6/); // Should NOT have solid red background
  });
});
