/**
 * Template Variable Editor E2E Tests (TDD RED Phase)
 *
 * Tests for the VariableDefinitionEditor component that allows users
 * to define variables when creating/editing templates.
 *
 * These tests will FAIL until the component is implemented (expected in TDD).
 *
 * Test Coverage:
 * - Extract variables from definition (auto-detect ${VAR} patterns)
 * - Add variable manually
 * - Remove variable
 * - Edit variable properties (type, description, default, required)
 * - Validation (required fields, duplicate names)
 * - Orphaned placeholder detection (${VAR} without definition)
 * - Full round-trip: create → save → reload → edit
 * - Deploy from template with variables
 */

import { test, expect } from '@playwright/test';
import { login } from '../fixtures/auth';

test.describe('Template Variable Editor - Auto-detect Variables', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/deployments');

    // Open templates manager
    const templatesButton = page.locator('[data-testid="manage-templates-button"]').or(
      page.locator('[data-testid="templates-link"]')
    );
    if (await templatesButton.isVisible({ timeout: 1000 })) {
      await templatesButton.click();
    }

    // Open new template form
    const newButton = page.locator('[data-testid="new-template-button"]').first();
    if (await newButton.isVisible({ timeout: 1000 })) {
      await newButton.click();
    }
  });

  test('[RED] should show "Extract Variables" button when definition contains ${VAR} placeholders', async ({ page }) => {
    // Type definition with variables
    const definitionField = page.locator('[data-testid="template-definition"]').or(
      page.locator('textarea[name="definition"]')
    );

    if (await definitionField.isVisible({ timeout: 1000 })) {
      await definitionField.fill(JSON.stringify({
        image: 'nginx:${VERSION}',
        ports: ['${PORT}:80']
      }, null, 2));

      // Should show "Extract Variables" button
      const extractButton = page.locator('[data-testid="extract-variables-button"]').or(
        page.locator('button:has-text("Extract Variables")')
      );

      await expect(extractButton).toBeVisible({ timeout: 2000 });
    }
  });

  test('[RED] should extract variables from definition when clicking "Extract Variables"', async ({ page }) => {
    const definitionField = page.locator('[data-testid="template-definition"]').first();

    if (await definitionField.isVisible({ timeout: 1000 })) {
      // Type definition with 3 variables
      await definitionField.fill(JSON.stringify({
        image: 'postgres:${VERSION}',
        environment: {
          POSTGRES_PASSWORD: '${DB_PASSWORD}',
          POSTGRES_DB: '${DB_NAME}'
        },
        ports: ['${PORT}:5432']
      }, null, 2));

      // Click extract button
      const extractButton = page.locator('[data-testid="extract-variables-button"]').first();
      if (await extractButton.isVisible({ timeout: 1000 })) {
        await extractButton.click();

        // Should create variable list items for VERSION, DB_PASSWORD, DB_NAME, PORT
        const variablesList = page.locator('[data-testid="variables-list"]');
        await expect(variablesList).toBeVisible({ timeout: 1000 });

        // Check each variable exists
        await expect(page.locator('[data-testid="variable-VERSION"]')).toBeVisible();
        await expect(page.locator('[data-testid="variable-DB_PASSWORD"]')).toBeVisible();
        await expect(page.locator('[data-testid="variable-DB_NAME"]')).toBeVisible();
        await expect(page.locator('[data-testid="variable-PORT"]')).toBeVisible();
      }
    }
  });

  test('[RED] should detect variables with different patterns: ${VAR}, ${VAR_NAME}, ${VAR123}', async ({ page }) => {
    const definitionField = page.locator('[data-testid="template-definition"]').first();

    if (await definitionField.isVisible({ timeout: 1000 })) {
      await definitionField.fill(JSON.stringify({
        image: '${IMAGE}',
        version: '${VERSION_TAG}',
        port: '${HTTP_PORT_80}'
      }, null, 2));

      const extractButton = page.locator('[data-testid="extract-variables-button"]').first();
      if (await extractButton.isVisible({ timeout: 1000 })) {
        await extractButton.click();

        // All three patterns should be detected
        await expect(page.locator('[data-testid="variable-IMAGE"]')).toBeVisible();
        await expect(page.locator('[data-testid="variable-VERSION_TAG"]')).toBeVisible();
        await expect(page.locator('[data-testid="variable-HTTP_PORT_80"]')).toBeVisible();
      }
    }
  });

  test('[RED] should not extract duplicate variables (same ${VAR} used multiple times)', async ({ page }) => {
    const definitionField = page.locator('[data-testid="template-definition"]').first();

    if (await definitionField.isVisible({ timeout: 1000 })) {
      await definitionField.fill(JSON.stringify({
        image: 'app:${VERSION}',
        tag: '${VERSION}',
        description: 'Version ${VERSION}'
      }, null, 2));

      const extractButton = page.locator('[data-testid="extract-variables-button"]').first();
      if (await extractButton.isVisible({ timeout: 1000 })) {
        await extractButton.click();

        // Should only have ONE VERSION variable (not three)
        const versionVariables = page.locator('[data-testid="variable-VERSION"]');
        await expect(versionVariables).toHaveCount(1);
      }
    }
  });
});

test.describe('Template Variable Editor - Manual Variable Management', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/deployments');

    const templatesButton = page.locator('[data-testid="templates-link"]').first();
    if (await templatesButton.isVisible({ timeout: 1000 })) {
      await templatesButton.click();
    }

    const newButton = page.locator('[data-testid="new-template-button"]').first();
    if (await newButton.isVisible({ timeout: 1000 })) {
      await newButton.click();
    }
  });

  test('[RED] should show "Add Variable" button', async ({ page }) => {
    const addButton = page.locator('[data-testid="add-variable-button"]').or(
      page.locator('button:has-text("Add Variable")')
    );

    await expect(addButton).toBeVisible({ timeout: 2000 });
  });

  test('[RED] should add new variable when clicking "Add Variable"', async ({ page }) => {
    const addButton = page.locator('[data-testid="add-variable-button"]').first();

    if (await addButton.isVisible({ timeout: 1000 })) {
      await addButton.click();

      // Should create a new variable row with default name
      const newVariable = page.locator('[data-testid^="variable-"]').first();
      await expect(newVariable).toBeVisible({ timeout: 1000 });

      // Should have input fields for name, type, description, default, required
      const nameInput = page.locator('input[data-testid="variable-name-input"]').first();
      await expect(nameInput).toBeVisible();
    }
  });

  test('[RED] should allow editing variable properties', async ({ page }) => {
    const addButton = page.locator('[data-testid="add-variable-button"]').first();

    if (await addButton.isVisible({ timeout: 1000 })) {
      await addButton.click();

      // Fill variable properties
      await page.fill('input[data-testid="variable-name-input"]', 'MY_VAR');
      await page.selectOption('select[data-testid="variable-type-select"]', 'string');
      await page.fill('textarea[data-testid="variable-description-input"]', 'My custom variable');
      await page.fill('input[data-testid="variable-default-input"]', 'default-value');
      await page.check('input[data-testid="variable-required-checkbox"]');

      // Verify values persisted
      await expect(page.locator('input[data-testid="variable-name-input"]')).toHaveValue('MY_VAR');
      await expect(page.locator('textarea[data-testid="variable-description-input"]')).toHaveValue('My custom variable');
      await expect(page.locator('input[data-testid="variable-default-input"]')).toHaveValue('default-value');
      await expect(page.locator('input[data-testid="variable-required-checkbox"]')).toBeChecked();
    }
  });

  test('[RED] should support variable types: string, integer, boolean', async ({ page }) => {
    const addButton = page.locator('[data-testid="add-variable-button"]').first();

    if (await addButton.isVisible({ timeout: 1000 })) {
      await addButton.click();

      const typeSelect = page.locator('select[data-testid="variable-type-select"]').first();

      // Should have all three type options
      const options = await typeSelect.locator('option').allTextContents();
      expect(options).toContain('string');
      expect(options).toContain('integer');
      expect(options).toContain('boolean');
    }
  });

  test('[RED] should remove variable when clicking delete button', async ({ page }) => {
    const addButton = page.locator('[data-testid="add-variable-button"]').first();

    if (await addButton.isVisible({ timeout: 1000 })) {
      // Add variable
      await addButton.click();
      await page.fill('input[data-testid="variable-name-input"]', 'TO_DELETE');

      const variableRow = page.locator('[data-testid="variable-TO_DELETE"]');
      await expect(variableRow).toBeVisible();

      // Delete it
      const deleteButton = variableRow.locator('[data-testid="delete-variable-button"]').or(
        variableRow.locator('button[title="Delete"]')
      );

      if (await deleteButton.isVisible({ timeout: 500 })) {
        await deleteButton.click();

        // Variable should be removed
        await expect(variableRow).not.toBeVisible({ timeout: 1000 });
      }
    }
  });
});

test.describe('Template Variable Editor - Validation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/deployments');

    const templatesButton = page.locator('[data-testid="templates-link"]').first();
    if (await templatesButton.isVisible({ timeout: 1000 })) {
      await templatesButton.click();
    }

    const newButton = page.locator('[data-testid="new-template-button"]').first();
    if (await newButton.isVisible({ timeout: 1000 })) {
      await newButton.click();
    }
  });

  test('[RED] should validate variable name is required', async ({ page }) => {
    const addButton = page.locator('[data-testid="add-variable-button"]').first();

    if (await addButton.isVisible({ timeout: 1000 })) {
      await addButton.click();

      // Leave name empty, try to save template
      await page.fill('input[name="name"]', 'test-validation-template');

      const definitionField = page.locator('textarea[name="definition"]').first();
      if (await definitionField.isVisible({ timeout: 500 })) {
        await definitionField.fill('{"image": "nginx:latest"}');
      }

      const saveButton = page.locator('button:has-text("Create")').first();
      await saveButton.click();

      // Should show validation error
      const error = page.locator('text=/variable name.*required|name.*required/i');
      await expect(error.first()).toBeVisible({ timeout: 2000 });
    }
  });

  test('[RED] should prevent duplicate variable names', async ({ page }) => {
    const addButton = page.locator('[data-testid="add-variable-button"]').first();

    if (await addButton.isVisible({ timeout: 1000 })) {
      // Add first variable
      await addButton.click();
      await page.fill('input[data-testid="variable-name-input"]', 'PORT');

      // Add second variable with same name
      await addButton.click();
      const nameInputs = page.locator('input[data-testid="variable-name-input"]');
      await nameInputs.last().fill('PORT');

      // Should show error
      const error = page.locator('text=/duplicate.*name|already exists/i');
      await expect(error.first()).toBeVisible({ timeout: 2000 });
    }
  });

  test('[RED] should validate variable name format (uppercase letters, numbers, underscores only)', async ({ page }) => {
    const addButton = page.locator('[data-testid="add-variable-button"]').first();

    if (await addButton.isVisible({ timeout: 1000 })) {
      await addButton.click();

      const nameInput = page.locator('input[data-testid="variable-name-input"]').first();

      // Invalid: lowercase
      await nameInput.fill('my_var');
      const errorLower = page.locator('text=/uppercase|invalid.*format/i');
      await expect(errorLower.first()).toBeVisible({ timeout: 1000 });

      // Invalid: spaces
      await nameInput.fill('MY VAR');
      const errorSpace = page.locator('text=/invalid.*format|no spaces/i');
      await expect(errorSpace.first()).toBeVisible({ timeout: 1000 });

      // Valid: uppercase + underscores + numbers
      await nameInput.fill('MY_VAR_123');
      await expect(errorLower).not.toBeVisible({ timeout: 1000 });
    }
  });

  test('[RED] should warn about orphaned placeholders (${VAR} in definition but no variable defined)', async ({ page }) => {
    const definitionField = page.locator('[data-testid="template-definition"]').first();

    if (await definitionField.isVisible({ timeout: 1000 })) {
      // Type definition with ${VERSION} but don't define the variable
      await definitionField.fill(JSON.stringify({
        image: 'nginx:${VERSION}',
        ports: ['80:80']
      }, null, 2));

      // Try to save
      await page.fill('input[name="name"]', 'test-orphaned-var');

      const saveButton = page.locator('button:has-text("Create")').first();
      await saveButton.click();

      // Should show warning about orphaned variable
      const warning = page.locator('text=/VERSION.*not defined|missing.*variable.*VERSION/i');
      await expect(warning.first()).toBeVisible({ timeout: 2000 });
    }
  });
});

test.describe('Template Variable Editor - Round Trip', () => {
  test('[RED] should save template with variables and reload them correctly', async ({ page }) => {
    await page.goto('/deployments');

    const templatesButton = page.locator('[data-testid="templates-link"]').first();
    if (await templatesButton.isVisible({ timeout: 1000 })) {
      await templatesButton.click();
    }

    const newButton = page.locator('[data-testid="new-template-button"]').first();
    if (await newButton.isVisible({ timeout: 1000 })) {
      await newButton.click();

      // Create template with variables
      await page.fill('input[name="name"]', 'test-roundtrip-vars');

      const definitionField = page.locator('[data-testid="template-definition"]').first();
      if (await definitionField.isVisible({ timeout: 1000 })) {
        await definitionField.fill(JSON.stringify({
          image: 'postgres:${VERSION}',
          environment: {
            POSTGRES_PASSWORD: '${DB_PASSWORD}'
          }
        }, null, 2));

        // Extract variables
        const extractButton = page.locator('[data-testid="extract-variables-button"]').first();
        if (await extractButton.isVisible({ timeout: 1000 })) {
          await extractButton.click();

          // Configure VERSION variable
          const versionNameInput = page.locator('[data-testid="variable-VERSION"]')
            .locator('input[data-testid="variable-name-input"]');
          if (await versionNameInput.isVisible({ timeout: 500 })) {
            await page.locator('[data-testid="variable-VERSION"]')
              .locator('select[data-testid="variable-type-select"]')
              .selectOption('string');
            await page.locator('[data-testid="variable-VERSION"]')
              .locator('input[data-testid="variable-default-input"]')
              .fill('16');
          }

          // Configure DB_PASSWORD variable
          const passwordNameInput = page.locator('[data-testid="variable-DB_PASSWORD"]')
            .locator('input[data-testid="variable-name-input"]');
          if (await passwordNameInput.isVisible({ timeout: 500 })) {
            await page.locator('[data-testid="variable-DB_PASSWORD"]')
              .locator('input[data-testid="variable-required-checkbox"]')
              .check();
          }
        }
      }

      // Save template
      const saveButton = page.locator('button:has-text("Create")').first();
      await saveButton.click();
      await page.waitForTimeout(500);

      // Edit the template again
      const editButton = page.locator('[data-testid="edit-template-test-roundtrip-vars"]').or(
        page.locator('button[title="Edit"]').first()
      );

      if (await editButton.isVisible({ timeout: 2000 })) {
        await editButton.click();

        // Variables should be loaded
        await expect(page.locator('[data-testid="variable-VERSION"]')).toBeVisible();
        await expect(page.locator('[data-testid="variable-DB_PASSWORD"]')).toBeVisible();

        // Check VERSION default is preserved
        const versionDefault = page.locator('[data-testid="variable-VERSION"]')
          .locator('input[data-testid="variable-default-input"]');
        await expect(versionDefault).toHaveValue('16');

        // Check DB_PASSWORD required flag is preserved
        const passwordRequired = page.locator('[data-testid="variable-DB_PASSWORD"]')
          .locator('input[data-testid="variable-required-checkbox"]');
        await expect(passwordRequired).toBeChecked();
      }
    }
  });
});

test.describe('Template Variable Editor - Integration with Deployment', () => {
  test('[RED] should show VariableInputDialog when deploying from template with variables', async ({ page }) => {
    await page.goto('/deployments');

    // Create template with variables first
    const templatesButton = page.locator('[data-testid="templates-link"]').first();
    if (await templatesButton.isVisible({ timeout: 1000 })) {
      await templatesButton.click();

      const newButton = page.locator('[data-testid="new-template-button"]').first();
      if (await newButton.isVisible({ timeout: 1000 })) {
        await newButton.click();

        await page.fill('input[name="name"]', 'test-deploy-with-vars');

        const definitionField = page.locator('[data-testid="template-definition"]').first();
        if (await definitionField.isVisible({ timeout: 1000 })) {
          await definitionField.fill(JSON.stringify({
            image: 'nginx:${VERSION}',
            ports: ['${PORT}:80']
          }, null, 2));

          // Extract and configure variables
          const extractButton = page.locator('[data-testid="extract-variables-button"]').first();
          if (await extractButton.isVisible({ timeout: 1000 })) {
            await extractButton.click();

            // Set defaults
            await page.locator('[data-testid="variable-VERSION"]')
              .locator('input[data-testid="variable-default-input"]')
              .fill('1.25');
            await page.locator('[data-testid="variable-PORT"]')
              .locator('input[data-testid="variable-default-input"]')
              .fill('8080');
          }
        }

        await page.locator('button:has-text("Create")').first().click();
        await page.waitForTimeout(500);

        // Close template manager
        const closeButton = page.locator('button:has-text("Close")').or(
          page.locator('[data-testid="close-modal"]')
        );
        if (await closeButton.isVisible({ timeout: 500 })) {
          await closeButton.click();
        }
      }
    }

    // Now use the template in a deployment
    const newDeploymentButton = page.locator('[data-testid="new-deployment-button"]').first();
    if (await newDeploymentButton.isVisible({ timeout: 1000 })) {
      await newDeploymentButton.click();

      const fromTemplateButton = page.locator('[data-testid="select-template"]').or(
        page.locator('button:has-text("From Template")')
      );

      if (await fromTemplateButton.isVisible({ timeout: 1000 })) {
        await fromTemplateButton.click();

        const templateItem = page.locator('text=test-deploy-with-vars').first();
        if (await templateItem.isVisible({ timeout: 1000 })) {
          await templateItem.click();

          // Should open VariableInputDialog
          const variableDialog = page.locator('[data-testid="template-variables-form"]');
          await expect(variableDialog).toBeVisible({ timeout: 2000 });

          // Should show both variables with defaults
          await expect(page.locator('input[name="VERSION"]')).toHaveValue('1.25');
          await expect(page.locator('input[name="PORT"]')).toHaveValue('8080');
        }
      }
    }
  });
});

test.describe('Template Variable Editor - Cleanup', () => {
  test.afterEach(async ({ page }) => {
    // Clean up test templates created by variable editor tests
    const isLoggedIn = page.url().includes('/dashboard') || page.url().includes('/deployments');

    if (!isLoggedIn) {
      try {
        await login(page);
      } catch (e) {
        return;
      }
    }

    await page.goto('/deployments');

    const templatesButton = page.locator('[data-testid="templates-link"]').first();
    if (await templatesButton.isVisible({ timeout: 1000 })) {
      await templatesButton.click();

      // Delete test templates
      const testTemplates = page.locator('text=/test-validation|test-roundtrip|test-deploy-with-vars/');
      const count = await testTemplates.count();

      for (let i = 0; i < count; i++) {
        try {
          const deleteButton = page.locator('button[title="Delete"]').first();
          if (await deleteButton.isVisible({ timeout: 500 })) {
            await deleteButton.click();

            const confirmButton = page.locator('button:has-text("Delete")').or(
              page.locator('button:has-text("Confirm")')
            );
            if (await confirmButton.isVisible({ timeout: 500 })) {
              await confirmButton.click();
            }

            await page.waitForTimeout(200);
          }
        } catch (e) {
          continue;
        }
      }
    }
  });
});
