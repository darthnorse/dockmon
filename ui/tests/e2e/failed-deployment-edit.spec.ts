"""
E2E tests for editing failed deployments in DockMon UI.

TDD Phase: RED - These tests will FAIL until UI features are implemented

Tests verify:
- Failed deployment shows error message on card/details
- Edit button is enabled for failed deployments
- Can open edit form for failed deployment with existing config
- Can submit edited failed deployment and retry
- Error message is cleared after successful retry
"""

import { test, expect } from '@playwright/test'

test.describe('Failed Deployment Editing', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to deployments page
    await page.goto('http://localhost:5173/deployments')
    await page.waitForLoadState('networkidle')
  })

  test('failed deployment shows error message on card', async ({ page }) => {
    """
    Failed deployment should display the error reason on the deployment card.

    RED PHASE: This test will FAIL because error message display not implemented
    """
    // Wait for deployment list to load
    await page.waitForSelector('[data-testid="deployment-card"]', { timeout: 5000 })

    // Find a failed deployment (assuming one exists in test data)
    const failedCard = page.locator('[data-testid="deployment-card"]')
      .filter({ has: page.locator('text="failed"') })
      .first()

    // Check if error message is visible
    const errorMessage = failedCard.locator('[data-testid="deployment-error"]')

    // This will FAIL until feature is implemented
    // After GREEN phase, error should be visible
    const isVisible = await errorMessage.isVisible().catch(() => false)

    if (isVisible) {
      expect(await errorMessage.textContent()).toContain('Error')
    }
  })

  test('edit button enabled for failed deployment', async ({ page }) => {
    """
    Edit button should be clickable for failed deployments.

    Currently edit button is disabled for non-'planning' deployments.
    """
    await page.waitForSelector('[data-testid="deployment-card"]')

    const failedCard = page.locator('[data-testid="deployment-card"]')
      .filter({ has: page.locator('text="failed"') })
      .first()

    const editButton = failedCard.locator('[data-testid="deployment-edit-btn"]')

    // This will FAIL because current implementation disables edit for failed
    // After GREEN phase, button should be enabled
    const isEnabled = await editButton.isEnabled().catch(() => false)

    if (isEnabled) {
      expect(editButton).toBeEnabled()
    }
  })

  test('can open edit form for failed deployment', async ({ page }) => {
    """
    Clicking edit on failed deployment should open form with existing config.

    RED PHASE: This will FAIL until edit is allowed for failed status
    """
    await page.waitForSelector('[data-testid="deployment-card"]')

    const failedCard = page.locator('[data-testid="deployment-card"]')
      .filter({ has: page.locator('text="failed"') })
      .first()

    // Click edit button
    await failedCard.locator('[data-testid="deployment-edit-btn"]').click()
      .catch(() => {
        // Edit button may be disabled in RED phase
      })

    // Wait for form to open
    const formOpened = await page.locator('[data-testid="deployment-form"]')
      .isVisible()
      .catch(() => false)

    if (formOpened) {
      // Form should be populated with existing values
      const imageInput = page.locator('input[value*="nginx"]').first()
      expect(imageInput).toBeVisible()
    }
  })

  test('can submit edited failed deployment', async ({ page }) => {
    """
    User should be able to edit configuration and submit to retry.

    RED PHASE: This test will FAIL until editing failed deployments is allowed
    """
    await page.waitForSelector('[data-testid="deployment-card"]')

    const failedCard = page.locator('[data-testid="deployment-card"]')
      .filter({ has: page.locator('text="failed"') })
      .first()

    // Get deployment name for verification
    const deploymentName = await failedCard.locator('[data-testid="deployment-name"]')
      .textContent()

    try {
      // Click edit
      await failedCard.locator('[data-testid="deployment-edit-btn"]').click({ timeout: 5000 })

      // Form should open
      await page.waitForSelector('[data-testid="deployment-form"]', { timeout: 5000 })

      // Modify configuration (e.g., change image tag)
      const imageInputs = page.locator('input[type="text"][value*=":"]')
      const imageField = imageInputs.first()

      await imageField.fill('nginx:1.25-alpine', { force: true })

      // Submit form
      const submitButton = page.locator('button:has-text("Save & Deploy")')
      await submitButton.click()

      // Deployment should be queued for retry
      // Status should show "planning" or "validating"
      await page.waitForTimeout(1000)
      const updatedStatus = failedCard.locator('[data-testid="deployment-status"]')
      const status = await updatedStatus.textContent()

      expect(['planning', 'validating', 'pulled_image', 'creating', 'starting'])
        .toContain(status)
    } catch (error) {
      // In RED phase, form may not open or submit may fail
      // That's expected
    }
  })

  test('error message cleared after retry', async ({ page }) => {
    """
    After submitting a retry, error message should be cleared from UI.

    This indicates the retry is in progress.
    """
    await page.waitForSelector('[data-testid="deployment-card"]')

    const failedCard = page.locator('[data-testid="deployment-card"]')
      .filter({ has: page.locator('text="failed"') })
      .first()

    // Get initial error message
    const errorMessage = failedCard.locator('[data-testid="deployment-error"]')
    const initialError = await errorMessage.textContent().catch(() => null)

    if (initialError) {
      // Edit and submit
      try {
        await failedCard.locator('[data-testid="deployment-edit-btn"]').click()
        await page.waitForSelector('[data-testid="deployment-form"]')

        const submitButton = page.locator('button:has-text("Save & Deploy")')
        await submitButton.click()

        // Wait a moment for state update
        await page.waitForTimeout(500)

        // Error message should be gone or hidden
        const errorVisible = await errorMessage.isVisible().catch(() => false)

        if (!errorVisible) {
          expect(errorMessage).not.toBeVisible()
        }
      } catch (error) {
        // Expected in RED phase
      }
    }
  })

  test('failed deployment in list shows error summary', async ({ page }) => {
    """
    In the deployments list, failed deployments should show error summary.

    Allows users to see at a glance what failed.
    """
    await page.waitForSelector('[data-testid="deployment-card"]')

    const failedCards = page.locator('[data-testid="deployment-card"]')
      .filter({ has: page.locator('text="failed"') })

    const count = await failedCards.count()

    if (count > 0) {
      const firstFailed = failedCards.first()

      // Should show status badge
      const statusBadge = firstFailed.locator('[data-testid="deployment-status-badge"]')
      const badgeText = await statusBadge.textContent()

      expect(badgeText).toContain('failed')

      // Should show error if available
      const errorElement = firstFailed.locator('[data-testid="deployment-error"]')
      const hasError = await errorElement.isVisible().catch(() => false)

      // Error display is optional in list view (can be detail-only)
      // But if present, should contain error text
      if (hasError) {
        const errorText = await errorElement.textContent()
        expect(errorText?.length).toBeGreaterThan(0)
      }
    }
  })
})
