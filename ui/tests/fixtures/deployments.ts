/**
 * Deployment test helpers for Playwright tests.
 */
import { Page, expect } from '@playwright/test';

/**
 * Create a deployment via the UI form
 * Waits for modal to close after successful creation
 */
export async function createDeployment(
  page: Page,
  config: {
    name: string;
    image: string;
    type?: 'container' | 'stack';
  }
) {
  // Open form
  const newButton = page.locator('[data-testid="new-deployment-button"]').first();
  await newButton.click();

  // Wait for modal to be visible
  const modal = page.locator('[data-testid="deployment-form"]');
  await expect(modal).toBeVisible();

  // Fill form
  await page.fill('input[name="name"]', config.name);
  await page.fill('input[name="image"]', config.image);

  // Select host (required field!)
  // shadcn/ui Select is not a native <select>, need to click trigger and then option
  // Use #host since SelectTrigger has id="host"
  const hostSelect = page.locator('button#host');
  console.log('Looking for host select (button#host)...');

  if (await hostSelect.isVisible({ timeout: 2000 })) {
    console.log('Host select found, clicking...');
    // Click to open the dropdown
    await hostSelect.click();

    // Wait for the dropdown options to appear
    await page.waitForTimeout(500);

    // Debug: Log what's actually in the DOM
    const popoverContent = page.locator('[role="listbox"], [data-radix-select-content]');
    const popoverExists = await popoverContent.isVisible({ timeout: 1000 });
    console.log('Popover content visible?', popoverExists);

    if (popoverExists) {
      const html = await popoverContent.innerHTML();
      console.log('Popover HTML:', html.substring(0, 200));
    }

    // Click the first available host (not the placeholder)
    // The options appear in a popover, look for role=option
    const firstOption = page.locator('[role="option"]').first();
    const optionVisible = await firstOption.isVisible({ timeout: 2000 });
    console.log('First option visible?', optionVisible);

    if (optionVisible) {
      const optionText = await firstOption.textContent();
      console.log('Clicking option:', optionText);
      await firstOption.click();
      await page.waitForTimeout(300); // Let the selection register
      console.log('Host selected!');
    } else {
      console.error('NO OPTIONS FOUND - host dropdown empty or not rendered');
    }
  } else {
    console.error('HOST SELECT NOT FOUND');
  }

  if (config.type) {
    const typeSelect = page.locator('select[name="type"]');
    if (await typeSelect.isVisible()) {
      await typeSelect.selectOption(config.type);
    }
  }

  // Submit
  const submitButton = page.locator('button:has-text("Create")').first();
  await submitButton.click();

  // CRITICAL: Wait for modal to close (API call completes)
  // The modal closes after successful creation, but this is async
  await expect(modal).not.toBeVisible({ timeout: 15000 });

  // Also wait for the blocking overlay to disappear
  const overlay = page.locator('[data-state="open"][aria-hidden="true"]');
  await expect(overlay).not.toBeVisible({ timeout: 5000 });
}

/**
 * Wait for any modal/dialog to close
 * Useful when tests need to ensure modal is fully closed before proceeding
 */
export async function waitForModalClose(page: Page) {
  // Wait for dialog content to disappear
  const dialog = page.locator('[role="dialog"]').first();
  await expect(dialog).not.toBeVisible({ timeout: 10000 });

  // Wait for backdrop overlay to disappear
  const overlay = page.locator('[data-state="open"][aria-hidden="true"]').first();
  await expect(overlay).not.toBeVisible({ timeout: 5000 });
}
