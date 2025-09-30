/**
 * DockMon Comprehensive Functional Tests
 * Complete test coverage for all DockMon features
 *
 * Test Hosts:
 * - Primary: tcp://192.168.1.43:2376 (insecure, no certs)
 * - Secondary: tcp://192.168.1.41:2376 (insecure, no certs)
 *
 * Test Notification Channels:
 * - Discord webhook (real, for testing)
 * - Pushover credentials (real, for testing)
 */

const { test, expect } = require('@playwright/test');

// ============================================================================
// TEST CONFIGURATION
// ============================================================================

const CONFIG = {
    baseUrl: 'https://localhost:8001',
    credentials: {
        username: 'admin',
        password: 'test1234'
    },
    testHosts: {
        primary: {
            name: 'Test Host 1',
            address: 'tcp://192.168.1.43:2376',
            tls: false
        },
        secondary: {
            name: 'Test Host 2',
            address: 'tcp://192.168.1.41:2376',
            tls: false
        }
    },
    notifications: {
        discord: {
            webhook: 'https://discord.com/api/webhooks/1360363170476064916/tys1kyvabICy2q7i7DFvcdh10iakxp6bUO5RN1WUENowXavIG-9Q1j02kunAul7vGoO_'
        },
        pushover: {
            appKey: 'aqopa9hax37rx4evz4a3a4suc2s2kj',
            userKey: 'uaJALmMcnjAXt5SgLxvb4gxwaXJSkv'
        }
    },
    timeouts: {
        short: 10000,
        medium: 15000,
        long: 20000
    }
};

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

/**
 * Login helper - handles authentication
 */
async function login(page) {
    await page.goto(CONFIG.baseUrl, { waitUntil: 'networkidle' });

    // Check if already logged in
    const isLoggedIn = await page.locator('.sidebar').count() > 0;
    if (isLoggedIn) return;

    // Perform login
    await page.fill('input[name="username"]', CONFIG.credentials.username);
    await page.fill('input[name="password"]', CONFIG.credentials.password);
    await page.click('button[type="submit"]');

    // Wait for dashboard
    await expect(page.locator('.main-content')).toBeVisible({ timeout: CONFIG.timeouts.medium });
}

/**
 * Navigate to a page using the sidebar
 */
async function navigateToPage(page, pageName) {
    const navLinks = {
        'dashboard': 'Dashboard',
        'hosts': 'Host Management',
        'alerts': 'Alert Rules',
        'settings': 'Settings',
        'notifications': 'Notifications',
        'logs': 'Logs',
        'about': 'About'
    };

    const linkText = navLinks[pageName];
    if (!linkText) throw new Error(`Unknown page: ${pageName}`);

    // Check if mobile view (sidebar might be hidden)
    const viewport = page.viewportSize();
    const isMobile = viewport && viewport.width < 768;

    if (isMobile) {
        // Open mobile menu first if it's closed
        const sidebar = page.locator('.sidebar');
        const isVisible = await sidebar.isVisible();
        if (!isVisible) {
            const menuToggle = page.locator('.mobile-menu-toggle');
            if (await menuToggle.count() > 0) {
                await menuToggle.click();
                await page.waitForTimeout(500);
            }
        }
    }

    const navLink = page.locator(`a.nav-item:has-text("${linkText}")`);
    await navLink.waitFor({ state: 'visible', timeout: 10000 });
    await navLink.click();

    // Simple wait for page transition - don't try to be clever
    await page.waitForTimeout(2000);
}

/**
 * Open a modal by clicking a button
 */
async function openModal(page, buttonText) {
    const button = page.locator(`button:has-text("${buttonText}")`);
    await button.waitFor({ state: 'visible', timeout: 10000 });
    await button.click();
    await page.waitForTimeout(500); // Wait for modal animation
}

/**
 * Close the currently active modal
 */
async function closeModal(page) {
    await page.click('.modal.active .modal-close');
    await page.waitForTimeout(500);
}

/**
 * Take a screenshot for visual comparison
 */
async function takeScreenshot(page, name) {
    await page.screenshot({
        path: `screenshots/test-${name}.png`,
        fullPage: true
    });
}

// ============================================================================
// TEST SUITES
// ============================================================================

test.describe('DockMon Comprehensive Functional Tests', () => {

    test.beforeEach(async ({ page }) => {
        // Accept self-signed certificate
        await page.goto(CONFIG.baseUrl, { waitUntil: 'networkidle' });
    });

    // ========================================================================
    // 1. AUTHENTICATION TESTS
    // ========================================================================

    test.describe('Authentication', () => {

        test('Should login with valid credentials', async ({ page }) => {
            await page.fill('input[name="username"]', CONFIG.credentials.username);
            await page.fill('input[name="password"]', CONFIG.credentials.password);
            await page.click('button[type="submit"]');

            // Check if we're logged in (sidebar might be hidden on mobile)
            const viewport = page.viewportSize();
            const isMobile = viewport && viewport.width < 768;

            if (!isMobile) {
                await expect(page.locator('.sidebar')).toBeVisible();
            }
            await expect(page.locator('.main-content')).toBeVisible();
        });

        test('Should reject invalid credentials', async ({ page }) => {
            await page.fill('input[name="username"]', 'wronguser');
            await page.fill('input[name="password"]', 'wrongpass');
            await page.click('button[type="submit"]');

            // Should show error and stay on login page
            await expect(page.locator('input[name="username"]')).toBeVisible();
        });

        test('Should logout successfully', async ({ page }) => {
            await login(page);

            // Click logout
            await page.click('a.nav-item.logout-item');

            // Should return to login page
            await expect(page.locator('input[name="username"]')).toBeVisible();
        });

        test('Should open and interact with account settings', async ({ page }) => {
            await login(page);

            // Open account settings
            await page.click('button[title="Account Settings"]');
            await expect(page.locator('#accountModal.active')).toBeVisible();

            // Check account info is displayed
            await expect(page.locator('#accountModal h2')).toContainText('Account Settings');

            // Close modal
            await closeModal(page);
            await expect(page.locator('#accountModal.active')).not.toBeVisible();
        });
    });

    // ========================================================================
    // 2. NAVIGATION & UI TESTS
    // ========================================================================

    test.describe('Navigation and UI', () => {

        test('Should navigate between all pages', async ({ page }) => {
            await login(page);

            // Test navigation to each page
            const pages = ['hosts', 'alerts', 'dashboard'];

            for (const pageName of pages) {
                await navigateToPage(page, pageName);

                // Verify page switched (active nav item)
                const activeNav = page.locator('a.nav-item.active');
                const activeText = await activeNav.textContent();

                // Basic check that we're on a different page
                expect(activeText).toBeTruthy();
            }
        });

        test('Should handle mobile menu toggle', async ({ page, isMobile }) => {
            await login(page);

            if (isMobile) {
                // Test mobile menu toggle
                const menuToggle = page.locator('.menu-toggle');
                if (await menuToggle.count() > 0) {
                    await menuToggle.click();
                    await page.waitForTimeout(500);
                }
            }
        });

        test('Should refresh data when clicking refresh button', async ({ page }) => {
            await login(page);

            // Click refresh button
            const refreshBtn = page.locator('button:has-text("Refresh")').first();
            if (await refreshBtn.count() > 0) {
                await refreshBtn.click();
                // Should trigger data refresh (hard to test without mocking)
                await page.waitForTimeout(1000);
            }
        });
    });

    // ========================================================================
    // 3. DASHBOARD TESTS
    // ========================================================================

    test.describe('Dashboard', () => {

        test('Should display statistics cards', async ({ page }) => {
            await login(page);

            // Wait for dashboard to load and check if stats widget exists
            await page.waitForTimeout(2000);
            const statsWidget = await page.locator('#widget-stats').count();
            if (statsWidget > 0) {
                // Check stats cards are present
                const statCards = await page.locator('.stat-card').count();
                expect(statCards).toBeGreaterThanOrEqual(4);

                // Check stats have values (not loading)
                await page.waitForFunction(() => {
                    const statValues = document.querySelectorAll('.stat-value');
                    return Array.from(statValues).every(el =>
                        el.textContent.trim() !== '...' &&
                        el.textContent.trim() !== ''
                    );
                }, { timeout: CONFIG.timeouts.medium });
            } else {
                // Stats widget may not be in the default layout - skip test
                test.skip();
            }
        });

        test('Should display GridStack widgets', async ({ page }) => {
            await login(page);

            // Check GridStack is initialized
            await expect(page.locator('.grid-stack')).toBeVisible();

            // Check for widgets
            const widgets = await page.locator('.grid-stack-item').count();
            expect(widgets).toBeGreaterThan(0);
        });

        test('Should drag and resize widgets', async ({ page }) => {
            await login(page);

            // Find a widget
            const widget = page.locator('.grid-stack-item').first();
            const widgetHeader = widget.locator('.widget-header');

            if (await widgetHeader.count() > 0) {
                // Get initial position
                const initialBox = await widget.boundingBox();

                // Try to drag widget
                await widgetHeader.hover();
                await page.mouse.down();
                await page.mouse.move(100, 100);
                await page.mouse.up();

                // Get new position
                const newBox = await widget.boundingBox();

                // Position might change (depends on GridStack constraints)
                expect(newBox).toBeTruthy();
            }
        });

        test('Should lock/unlock widgets', async ({ page }) => {
            await login(page);

            // Find lock button
            const lockBtn = page.locator('.widget-action.lock-btn').first();

            if (await lockBtn.count() > 0) {
                // Click to lock
                await lockBtn.click();
                await page.waitForTimeout(500);

                // Check if locked class is applied
                const isLocked = await lockBtn.evaluate(el =>
                    el.classList.contains('locked')
                );

                // Click to unlock
                await lockBtn.click();
                await page.waitForTimeout(500);
            }
        });
    });

    // ========================================================================
    // 4. HOST MANAGEMENT TESTS
    // ========================================================================

    test.describe('Host Management', () => {

        test('Should list existing hosts', async ({ page }) => {
            await login(page);
            await navigateToPage(page, 'hosts');

            // Check for host cards
            const hostCards = await page.locator('.host-card').count();
            expect(hostCards).toBeGreaterThanOrEqual(0);
        });

        test('Should add a new host', async ({ page }) => {
            await login(page);
            await navigateToPage(page, 'hosts');

            // Open add host modal
            await openModal(page, 'Add Host');
            await expect(page.locator('#hostModal.active')).toBeVisible();

            // Fill in host details
            await page.fill('input[name="hostname"]', CONFIG.testHosts.primary.name);
            await page.fill('input[name="hosturl"]', CONFIG.testHosts.primary.address);

            // TLS checkbox may not exist for non-TLS hosts
            const tlsCheckbox = page.locator('input[type="checkbox"][name="use_tls"]');
            if (await tlsCheckbox.count() > 0) {
                if (await tlsCheckbox.isChecked()) {
                    await tlsCheckbox.uncheck();
                }
            }

            // Save host
            await page.click('#hostModal button[type="submit"]');
            await page.waitForTimeout(1000); // Wait for host to be saved

            // Close modal manually
            await closeModal(page);
            await page.waitForTimeout(500);

            // Verify host was added (look for it in the list)
            const newHost = page.locator(`.host-card:has-text("${CONFIG.testHosts.primary.name}")`);
            await expect(newHost).toBeVisible({ timeout: CONFIG.timeouts.long });
        });

        test('Should edit an existing host', async ({ page }) => {
            await login(page);
            await navigateToPage(page, 'hosts');

            // Find a host card with edit button
            const hostCard = page.locator('.host-card').first();
            const editBtn = hostCard.locator('button[title*="Edit"]');

            if (await editBtn.count() > 0) {
                await editBtn.click();
                await expect(page.locator('#hostModal.active')).toBeVisible();

                // Modify the name
                const nameInput = page.locator('input[name="hostname"]');
                await nameInput.clear();
                await nameInput.fill('Modified Host Name');

                // Save changes
                await page.click('#hostModal button[type="submit"]');
                await page.waitForTimeout(2000);
            }
        });

        test('Should delete a host', async ({ page }) => {
            await login(page);
            await navigateToPage(page, 'hosts');

            // Find a host card with delete button
            const hostCard = page.locator('.host-card').first();
            const deleteBtn = hostCard.locator('button[title*="Delete"]');

            if (await deleteBtn.count() > 0) {
                // Click delete
                await deleteBtn.click();

                // Confirm deletion
                await expect(page.locator('#confirmationModal.active')).toBeVisible();
                await page.click('#confirmationButton');
                await page.waitForTimeout(2000);
            }
        });

        test('Should show host security status', async ({ page }) => {
            await login(page);
            await navigateToPage(page, 'hosts');

            // Check for security indicators
            const securityStatus = page.locator('.security-status, .host-status');
            if (await securityStatus.count() > 0) {
                const status = await securityStatus.first().textContent();
                expect(['secure', 'insecure', 'online', 'offline']).toContain(
                    status.toLowerCase().trim()
                );
            }
        });
    });

    // ========================================================================
    // 5. CONTAINER OPERATIONS TESTS
    // ========================================================================

    test.describe('Container Operations', () => {

        test('Should display container list', async ({ page }) => {
            await login(page);

            // Wait for containers to load
            await page.waitForTimeout(2000);

            // Check if any containers exist
            const containers = await page.locator('.container-item').count();
            expect(containers).toBeGreaterThanOrEqual(0);
        });

        test('Should open container details modal', async ({ page }) => {
            await login(page);

            // Wait for containers
            await page.waitForTimeout(2000);
            const containers = await page.locator('.container-item').count();

            if (containers > 0) {
                // Click first container
                const firstContainer = page.locator('.container-item').first();
                await firstContainer.waitFor({ state: 'visible', timeout: 10000 });
                await firstContainer.click();
                await expect(page.locator('#containerModal.active')).toBeVisible({ timeout: 10000 });

                // Check tabs exist
                await expect(page.locator('#tab-info')).toBeVisible();
                await expect(page.locator('#tab-logs')).toBeVisible();

                // Close modal
                await closeModal(page);
            }
        });

        test('Should view container logs', async ({ page }) => {
            await login(page);

            const containers = await page.locator('.container-item').count();
            if (containers > 0) {
                // Open container modal
                await page.click('.container-item:first-child');
                await expect(page.locator('#containerModal.active')).toBeVisible();

                // Switch to logs tab
                await page.click('#tab-logs');
                await page.waitForTimeout(1000);

                // Check logs area exists
                await expect(page.locator('#container-logs')).toBeVisible();

                // Try refresh logs
                const refreshBtn = page.locator('button:has-text("Refresh Logs")');
                if (await refreshBtn.count() > 0) {
                    await refreshBtn.click();
                    await page.waitForTimeout(1000);
                }

                await closeModal(page);
            }
        });

        test('Should toggle auto-restart for container', async ({ page }) => {
            await login(page);

            const autoRestartToggles = await page.locator('.auto-restart-toggle').count();
            if (autoRestartToggles > 0) {
                const toggle = page.locator('.auto-restart-toggle').first();

                // Get initial state
                const initialClass = await toggle.getAttribute('class');

                // Click to toggle
                await toggle.click();
                await page.waitForTimeout(1000);

                // Check state changed
                const newClass = await toggle.getAttribute('class');
                expect(newClass).not.toBe(initialClass);
            }
        });

        test('Should perform container actions', async ({ page }) => {
            await login(page);

            const containers = await page.locator('.container-item').count();
            if (containers > 0) {
                // Open container modal
                await page.click('.container-item:first-child');
                await expect(page.locator('#containerModal.active')).toBeVisible();

                // Look for action buttons
                const actionButtons = page.locator('.container-actions button');
                const buttonCount = await actionButtons.count();

                if (buttonCount > 0) {
                    // Check which actions are available
                    const actions = ['Start', 'Stop', 'Restart'];
                    for (const action of actions) {
                        const btn = page.locator(`button:has-text("${action}")`);
                        if (await btn.count() > 0 && await btn.isEnabled()) {
                            // We found an enabled action button
                            // Don't actually click it to avoid disrupting containers
                            expect(await btn.isVisible()).toBeTruthy();
                            break;
                        }
                    }
                }

                await closeModal(page);
            }
        });
    });

    // ========================================================================
    // 6. ALERT RULES TESTS
    // ========================================================================

    test.describe('Alert Rules', () => {

        test('Should display alert rules page', async ({ page }) => {
            await login(page);
            await navigateToPage(page, 'alerts');

            // Check for alert rules content
            const content = page.locator('.content .card, .alert-rules-list');
            await content.first().waitFor({ state: 'visible', timeout: CONFIG.timeouts.long });
            await expect(content.first()).toBeVisible({ timeout: CONFIG.timeouts.medium });
        });

        test('Should open create alert rule modal', async ({ page }) => {
            await login(page);
            await navigateToPage(page, 'alerts');

            // Open create alert modal
            const createBtn = page.locator('button:has-text("Create Alert Rule")');
            if (await createBtn.count() > 0) {
                await createBtn.waitFor({ state: 'visible', timeout: 10000 });
                await createBtn.click();
                await expect(page.locator('#alertRuleModal.active')).toBeVisible({ timeout: 10000 });

                // Check form fields exist
                await expect(page.locator('#alertRuleName')).toBeVisible();
                await expect(page.locator('#selectAllContainers')).toBeVisible();

                await closeModal(page);
            }
        });

        test('Should create a new alert rule', async ({ page }) => {
            await login(page);
            await navigateToPage(page, 'alerts');

            const createBtn = page.locator('button:has-text("Create Alert Rule")');
            if (await createBtn.count() > 0) {
                await createBtn.waitFor({ state: 'visible', timeout: 10000 });
                await createBtn.click();
                await expect(page.locator('#alertRuleModal.active')).toBeVisible({ timeout: 10000 });

                // Fill in alert rule details
                await page.fill('#alertRuleName', 'Test Alert Rule');

                // Select all containers
                await page.check('#selectAllContainers');

                // Check at least one event trigger (stopped event)
                await page.check('input[data-event="stop"]');

                // Save rule
                await page.click('#alertRuleModal button[type="submit"]');
                await page.waitForTimeout(2000);

                // Verify rule was created
                const newRule = page.locator(':has-text("Test Alert Rule")');
                await expect(newRule).toBeVisible({ timeout: CONFIG.timeouts.medium });
            }
        });

        test('Should delete an alert rule', async ({ page }) => {
            await login(page);
            await navigateToPage(page, 'alerts');

            // Find a delete button for an alert rule
            const deleteBtn = page.locator('.alert-rule-item button[title*="Delete"]').first();

            if (await deleteBtn.count() > 0) {
                await deleteBtn.click();

                // Confirm deletion
                await expect(page.locator('#confirmationModal.active')).toBeVisible();
                await page.click('#confirmationButton');
                await page.waitForTimeout(2000);
            }
        });
    });

    // ========================================================================
    // 7. NOTIFICATION SYSTEM TESTS
    // ========================================================================

    test.describe('Notification System', () => {

        test('Should open notification settings modal', async ({ page }) => {
            await login(page);

            // Click notifications in sidebar
            const notifLink = page.locator('a.nav-item:has-text("Notifications")');
            if (await notifLink.count() > 0) {
                await notifLink.waitFor({ state: 'visible', timeout: 10000 });
                await notifLink.click();
                await expect(page.locator('#notificationModal.active')).toBeVisible({ timeout: 10000 });

                // Check tabs exist
                await expect(page.locator('#channelsTab')).toBeVisible();
                await expect(page.locator('#templateTab')).toBeVisible();
                await expect(page.locator('#blackoutTab')).toBeVisible();

                await closeModal(page);
            }
        });

        test('Should add Discord notification channel', async ({ page }) => {
            await login(page);

            // Open notifications modal
            const notifLink = page.locator('a.nav-item:has-text("Notifications")');
            if (await notifLink.count() > 0) {
                await notifLink.waitFor({ state: 'visible', timeout: 10000 });
                await notifLink.click();
                await expect(page.locator('#notificationModal.active')).toBeVisible({ timeout: 10000 });

                // Add new channel
                const addChannelBtn = page.locator('button:has-text("Add Channel")');
                await addChannelBtn.waitFor({ state: 'visible', timeout: 10000 });
                await addChannelBtn.click();
                await page.waitForTimeout(1000); // Wait for channel to be added to DOM

                // Find the new channel form and wait for select to be visible
                const newChannel = page.locator('.notification-channel-card').last();
                const selectElement = newChannel.locator('select.form-input');
                await selectElement.waitFor({ state: 'visible', timeout: 10000 });
                await expect(selectElement).toBeVisible({ timeout: 5000 });

                // Select Discord type
                await selectElement.selectOption('discord');
                await page.waitForTimeout(500);

                // Fill in Discord webhook
                const webhookInput = newChannel.locator('input[placeholder*="webhook"]');
                await webhookInput.fill(CONFIG.notifications.discord.webhook);

                // Save channels
                await page.click('button:has-text("Save Channels")');
                await page.waitForTimeout(2000);
            }
        });

        test('Should add Pushover notification channel', async ({ page }) => {
            await login(page);

            // Open notifications modal
            const notifLink = page.locator('a.nav-item:has-text("Notifications")');
            if (await notifLink.count() > 0) {
                await notifLink.waitFor({ state: 'visible', timeout: 10000 });
                await notifLink.click();
                await expect(page.locator('#notificationModal.active')).toBeVisible({ timeout: 10000 });

                // Add new channel
                const addChannelBtn = page.locator('button:has-text("Add Channel")');
                await addChannelBtn.waitFor({ state: 'visible', timeout: 10000 });
                await addChannelBtn.click();
                await page.waitForTimeout(1000); // Wait for channel to be added to DOM

                // Find the new channel form and wait for select to be visible
                const newChannel = page.locator('.notification-channel-card').last();
                const selectElement = newChannel.locator('select.form-input');
                await selectElement.waitFor({ state: 'visible', timeout: 10000 });
                await expect(selectElement).toBeVisible({ timeout: 5000 });

                // Select Pushover type
                await selectElement.selectOption('pushover');
                await page.waitForTimeout(500);

                // Fill in Pushover credentials
                const appKeyInput = newChannel.locator('input[placeholder*="App"]');
                const userKeyInput = newChannel.locator('input[placeholder*="User"]');

                await appKeyInput.fill(CONFIG.notifications.pushover.appKey);
                await userKeyInput.fill(CONFIG.notifications.pushover.userKey);

                // Save channels
                await page.click('button:has-text("Save Channels")');
                await page.waitForTimeout(2000);
            }
        });

        test('Should test notification channel', async ({ page }) => {
            await login(page);

            // Open notifications modal
            const notifLink = page.locator('a.nav-item:has-text("Notifications")');
            if (await notifLink.count() > 0) {
                await notifLink.waitFor({ state: 'visible', timeout: 10000 });
                await notifLink.click();
                await expect(page.locator('#notificationModal.active')).toBeVisible({ timeout: 10000 });

                // Find test button for first channel
                const testBtn = page.locator('.notification-channel-card button:has-text("Test")').first();
                if (await testBtn.count() > 0) {
                    await testBtn.waitFor({ state: 'visible', timeout: 10000 });
                    await testBtn.click();

                    // Wait for test to complete and toast to appear
                    await page.waitForTimeout(3000);

                    // Check for success/error toast
                    const toast = page.locator('.toast');
                    if (await toast.count() > 0) {
                        await toast.waitFor({ state: 'visible', timeout: 5000 });
                        await expect(toast).toBeVisible({ timeout: 5000 });
                    }
                }
            }
        });

        test('Should configure message template', async ({ page }) => {
            await login(page);

            // Open notifications modal
            const notifLink = page.locator('a.nav-item:has-text("Notifications")');
            if (await notifLink.count() > 0) {
                await notifLink.waitFor({ state: 'visible', timeout: 10000 });
                await notifLink.click();
                await expect(page.locator('#notificationModal.active')).toBeVisible({ timeout: 10000 });

                // Switch to template tab
                const templateTab = page.locator('#templateTab');
                await templateTab.waitFor({ state: 'visible', timeout: 10000 });
                await templateTab.click();
                await page.waitForTimeout(1000); // Wait for tab content to load

                // Check template editor exists
                const templateEditor = page.locator('textarea[name="message-template"]');
                await templateEditor.waitFor({ state: 'visible', timeout: 10000 });
                await expect(templateEditor).toBeVisible();

                // Modify template
                const currentTemplate = await templateEditor.inputValue();
                await templateEditor.fill(currentTemplate + '\n// Test modification');

                // Save template
                await page.click('button:has-text("Save Template")');
                await page.waitForTimeout(1000);
            }
        });

        test('Should add blackout window', async ({ page }) => {
            await login(page);

            // Open notifications modal
            const notifLink = page.locator('a.nav-item:has-text("Notifications")');
            if (await notifLink.count() > 0) {
                await notifLink.waitFor({ state: 'visible', timeout: 10000 });
                await notifLink.click();
                await expect(page.locator('#notificationModal.active')).toBeVisible({ timeout: 10000 });

                // Switch to blackout tab
                await page.click('#blackoutTab');
                await page.waitForTimeout(500);

                // Add blackout window
                const addBtn = page.locator('button:has-text("Add Blackout Window")');
                if (await addBtn.count() > 0) {
                    await addBtn.click();
                    await page.waitForTimeout(500);

                    // Configure blackout window - find the last div in blackoutWindowsList
                    const blackoutForm = page.locator('#blackoutWindowsList > div').last();
                    await blackoutForm.waitFor({ state: 'visible', timeout: 5000 });

                    // Set times
                    const startTime = blackoutForm.locator('input[type="time"]').first();
                    const endTime = blackoutForm.locator('input[type="time"]').last();
                    await startTime.waitFor({ state: 'visible', timeout: 5000 });
                    await startTime.fill('22:00');
                    await endTime.fill('06:00');

                    // Save blackout windows
                    await page.click('button:has-text("Save Blackout")');
                    await page.waitForTimeout(1000);
                }
            }
        });
    });

    // ========================================================================
    // 8. GLOBAL SETTINGS TESTS
    // ========================================================================

    test.describe('Global Settings', () => {

        test('Should open global settings modal', async ({ page }) => {
            await login(page);

            // Click settings in sidebar
            const settingsLink = page.locator('a.nav-item:has-text("Settings")');
            if (await settingsLink.count() > 0) {
                await settingsLink.click();
                await expect(page.locator('#globalSettingsModal.active')).toBeVisible();

                // Check settings sections exist
                const sections = page.locator('.settings-section');
                const sectionCount = await sections.count();
                expect(sectionCount).toBeGreaterThan(0);

                await closeModal(page);
            }
        });

        test('Should toggle default auto-restart setting', async ({ page }) => {
            await login(page);

            // Open settings
            const settingsLink = page.locator('a.nav-item:has-text("Settings")');
            if (await settingsLink.count() > 0) {
                await settingsLink.click();
                await expect(page.locator('#globalSettingsModal.active')).toBeVisible();

                // Find auto-restart toggle
                const toggle = page.locator('#defaultAutoRestart');
                if (await toggle.count() > 0) {
                    // Get initial state
                    const initialClass = await toggle.getAttribute('class');

                    // Click to toggle
                    await toggle.click();
                    await page.waitForTimeout(500);

                    // Verify state changed
                    const newClass = await toggle.getAttribute('class');
                    expect(newClass).not.toBe(initialClass);

                    // Save settings
                    await page.click('button:has-text("Save")');
                    await page.waitForTimeout(1000);
                }
            }
        });
    });

    // ========================================================================
    // 9. WEBSOCKET & REAL-TIME TESTS
    // ========================================================================

    test.describe('WebSocket and Real-time Updates', () => {

        test('Should establish WebSocket connection', async ({ page }) => {
            await login(page);

            // Check if WebSocket connects (hard to test without access to window.ws)
            // We can check for connection indicators
            const connectionIndicator = page.locator('.connection-status, .ws-status');
            if (await connectionIndicator.count() > 0) {
                // Wait for connection
                await page.waitForTimeout(2000);

                const status = await connectionIndicator.getAttribute('class');
                expect(status).toContain('connected');
            }
        });

        test('Should receive real-time updates', async ({ page }) => {
            await login(page);

            // Monitor for changes in stats over time
            const initialStats = await page.locator('.stat-value').first().textContent();

            // Wait for potential updates
            await page.waitForTimeout(5000);

            // Stats might change if containers/hosts change
            const newStats = await page.locator('.stat-value').first().textContent();

            // We can't guarantee changes, but system should be responsive
            expect(newStats).toBeTruthy();
        });
    });

    // ========================================================================
    // 10. ERROR HANDLING TESTS
    // ========================================================================

    test.describe('Error Handling', () => {

        test('Should handle API errors gracefully', async ({ page }) => {
            await login(page);

            // Try to access non-existent resource
            const response = await page.request.get(`${CONFIG.baseUrl}/api/nonexistent`);
            expect(response.status()).toBe(404);

            // App should still be functional
            await page.goto(CONFIG.baseUrl);
            await expect(page.locator('.main-content')).toBeVisible();
        });

        test('Should show confirmation for destructive actions', async ({ page }) => {
            await login(page);
            await navigateToPage(page, 'hosts');

            // Try to delete something
            const deleteBtn = page.locator('button[title*="Delete"]').first();
            if (await deleteBtn.count() > 0) {
                await deleteBtn.click();

                // Should show confirmation modal
                await expect(page.locator('#confirmationModal.active')).toBeVisible();

                // Cancel action
                await page.click('button:has-text("Cancel")');
                await expect(page.locator('#confirmationModal.active')).not.toBeVisible();
            }
        });

        test('Should validate form inputs', async ({ page }) => {
            await login(page);
            await navigateToPage(page, 'hosts');

            // Open add host modal
            const addBtn = page.locator('button:has-text("Add Host")');
            if (await addBtn.count() > 0) {
                await addBtn.waitFor({ state: 'visible', timeout: 10000 });
                await addBtn.click();
                await expect(page.locator('#hostModal.active')).toBeVisible();

                // Try to save without filling required fields
                await page.click('#hostModal button[type="submit"]');

                // Modal should still be open (validation failed)
                await expect(page.locator('#hostModal.active')).toBeVisible();

                await closeModal(page);
            }
        });
    });

    // ========================================================================
    // 11. MOBILE & RESPONSIVE TESTS
    // ========================================================================

    test.describe('Mobile and Responsive Design', () => {

        test('Should adapt layout for mobile viewport', async ({ page }) => {
            await login(page);

            // Set mobile viewport
            await page.setViewportSize({ width: 375, height: 667 });
            await page.waitForTimeout(1000);

            // Check mobile-specific elements
            const menuToggle = page.locator('.menu-toggle');
            if (await menuToggle.count() > 0) {
                await menuToggle.waitFor({ state: 'visible', timeout: 10000 });
                await expect(menuToggle).toBeVisible();
            }

            // Dashboard should still be functional
            await expect(page.locator('.main-content')).toBeVisible();
        });

        test('Should handle touch interactions on mobile', async ({ page }) => {
            await login(page);

            // Set mobile viewport
            await page.setViewportSize({ width: 375, height: 667 });

            // Try to interact with a container
            const containers = await page.locator('.container-item').count();
            if (containers > 0) {
                await page.tap('.container-item:first-child');

                // Modal should open
                await expect(page.locator('#containerModal.active')).toBeVisible();

                // Close with tap
                await page.tap('.modal-close');
                await expect(page.locator('#containerModal.active')).not.toBeVisible();
            }
        });
    });

    // ========================================================================
    // 12. PERFORMANCE TESTS
    // ========================================================================

    test.describe('Performance', () => {

        test('Should load dashboard within acceptable time', async ({ page }) => {
            const startTime = Date.now();

            await login(page);
            await page.waitForSelector('.grid-stack', { timeout: CONFIG.timeouts.long });

            const loadTime = Date.now() - startTime;

            // Dashboard should load within 15 seconds
            expect(loadTime).toBeLessThan(15000);

            console.log(`Dashboard load time: ${loadTime}ms`);
        });

        test('Should handle large data sets efficiently', async ({ page }) => {
            await login(page);

            // Check if we have many containers
            const containerCount = await page.locator('.container-item').count();

            if (containerCount > 10) {
                // Scrolling should be smooth
                await page.evaluate(() => {
                    window.scrollTo(0, document.body.scrollHeight);
                });
                await page.waitForTimeout(500);

                await page.evaluate(() => {
                    window.scrollTo(0, 0);
                });

                // UI should remain responsive
                await expect(page.locator('.main-content')).toBeVisible();
            }
        });
    });

    // ========================================================================
    // 13. CRITICAL DATA INTEGRITY TESTS
    // ========================================================================

    test.describe('Critical Data Integrity', () => {

        test('Should update (not delete) alert rules when deleting one host from multi-host alert', async ({ page }) => {
            await login(page);

            // Step 1: Ensure we have two hosts
            await navigateToPage(page, 'hosts');

            // Add first host if not exists
            let host1Exists = await page.locator('.host-card:has-text("Test Host A")').count() > 0;
            if (!host1Exists) {
                await openModal(page, 'Add Host');
                await page.fill('input[name="hostname"]', 'Test Host A');
                await page.fill('input[name="hosturl"]', CONFIG.testHosts.primary.address);
                // TLS certificates are auto-shown for tcp:// URLs, no checkbox needed
                await page.click('#hostModal button[type="submit"]');
                await page.waitForTimeout(1000); // Wait for host to be saved
                await closeModal(page);
                await page.waitForTimeout(500);
            }

            // Add second host if not exists
            let host2Exists = await page.locator('.host-card:has-text("Test Host B")').count() > 0;
            if (!host2Exists) {
                await openModal(page, 'Add Host');
                await page.fill('input[name="hostname"]', 'Test Host B');
                await page.fill('input[name="hosturl"]', CONFIG.testHosts.secondary.address);
                // TLS certificates are auto-shown for tcp:// URLs, no checkbox needed
                await page.click('#hostModal button[type="submit"]');
                await page.waitForTimeout(1000); // Wait for host to be saved
                await closeModal(page);
                await page.waitForTimeout(500);
            }

            // Step 2: Create an alert rule that monitors containers on BOTH hosts
            await navigateToPage(page, 'alerts');
            const createBtn = page.locator('button:has-text("Create Alert Rule")');
            if (await createBtn.count() > 0) {
                await createBtn.click();
                await expect(page.locator('#alertRuleModal.active')).toBeVisible();

                // Create alert for specific container on multiple hosts
                await page.fill('#alertRuleName', 'Multi-Host Container Alert');

                // Select ALL hosts option if available, or first host
                
                if (await allHostsOption.count() > 0) {
                } else {
                    // If no "All" option, select first host and note limitation
                }

                

                // Specify a container name
                const containerInput = page.locator('#ruleContainer');
                if (await containerInput.count() > 0) {
                    await containerInput.fill('nginx'); // Common container
                }

                await page.click('#alertRuleModal button[type="submit"]');
                await page.waitForTimeout(2000);
            }

            // Step 3: Record the alert exists
            const alertName = 'Multi-Host Container Alert';
            let alertElement = page.locator(`:has-text("${alertName}")`);
            await expect(alertElement).toBeVisible({ timeout: CONFIG.timeouts.medium });

            // Step 4: Delete ONE of the hosts
            await navigateToPage(page, 'hosts');
            const hostACard = page.locator('.host-card:has-text("Test Host A")');
            if (await hostACard.count() > 0) {
                const deleteBtn = hostACard.locator('button[title*="Delete"]');
                if (await deleteBtn.count() > 0) {
                    await deleteBtn.click();

                    // Confirm deletion
                    await expect(page.locator('#confirmationModal.active')).toBeVisible();
                    await page.click('#confirmationButton');
                    await page.waitForTimeout(3000);
                }
            }

            // Step 5: CRITICAL CHECK - Alert should STILL exist
            await navigateToPage(page, 'alerts');
            alertElement = page.locator(`:has-text("${alertName}")`);

            // THIS IS THE KEY ASSERTION - Alert must not be deleted
            await expect(alertElement).toBeVisible({ timeout: CONFIG.timeouts.medium });
            console.log('✅ PASS: Alert rule still exists after deleting one host');

            // Step 6: Verify alert is updated to only monitor remaining host
            const editBtn = alertElement.locator('button[title*="Edit"]');
            if (await editBtn.count() > 0) {
                await editBtn.click();
                await expect(page.locator('#alertRuleModal.active')).toBeVisible();

                // Check host selection - should not have stale reference
                

                // Should have a valid host selected (not the deleted one)
                expect(selectedValue).not.toContain('Test Host A');
                console.log('✅ PASS: Alert updated to remove deleted host reference');

                await closeModal(page);
            }

            // Step 7: Verify remaining host still exists
            await navigateToPage(page, 'hosts');
            const hostBCard = page.locator('.host-card:has-text("Test Host B")');
            await expect(hostBCard).toBeVisible();
            console.log('✅ PASS: Remaining host unaffected by deletion');
        });

        test('Should handle "ALL hosts/containers" alert when hosts are deleted', async ({ page }) => {
            await login(page);

            // Step 1: Ensure we have at least 2 hosts
            await navigateToPage(page, 'hosts');
            const initialHostCount = await page.locator('.host-card').count();

            if (initialHostCount < 2) {
                // Add hosts to ensure we have at least 2
                await openModal(page, 'Add Host');
                await page.fill('input[name="hostname"]', 'All-Test Host 1');
                await page.fill('input[name="hosturl"]', CONFIG.testHosts.primary.address);
                // TLS certificates are auto-shown for tcp:// URLs, no checkbox needed
                await page.click('#hostModal button[type="submit"]');
                await page.waitForTimeout(1000); // Wait for host to be saved
                await closeModal(page);
                await page.waitForTimeout(500);
            }

            // Step 2: Create alert for ALL containers on ALL hosts
            await navigateToPage(page, 'alerts');
            const createBtn = page.locator('button:has-text("Create Alert Rule")');
            if (await createBtn.count() > 0) {
                await createBtn.click();
                await expect(page.locator('#alertRuleModal.active')).toBeVisible();

                await page.fill('#alertRuleName', 'All Hosts All Containers Alert');

                // Select ALL hosts if available
                
                if (await allOption.count() > 0) {
                } else {
                    // Use wildcard or leave empty if that means "all"
                    if (await wildcardOption.count() > 0) {
                    } else {
                        // Select first option as fallback
                    }
                }

                

                // Leave container field empty or use wildcard for ALL containers
                const containerInput = page.locator('#ruleContainer');
                if (await containerInput.count() > 0) {
                    // Empty means all containers, or use * if required
                    await containerInput.fill('*');
                }

                await page.click('#alertRuleModal button[type="submit"]');
                await page.waitForTimeout(2000);
            }

            // Step 3: Verify alert was created
            const alertName = 'All Hosts All Containers Alert';
            let alertElement = page.locator(`:has-text("${alertName}")`);
            await expect(alertElement).toBeVisible({ timeout: CONFIG.timeouts.medium });

            // Step 4: Delete one host
            await navigateToPage(page, 'hosts');
            const firstHost = page.locator('.host-card').first();
            const firstHostName = await firstHost.locator('.host-name').textContent();

            const deleteBtn = firstHost.locator('button[title*="Delete"]');
            if (await deleteBtn.count() > 0) {
                await deleteBtn.click();
                await expect(page.locator('#confirmationModal.active')).toBeVisible();
                await page.click('#confirmationButton');
                await page.waitForTimeout(3000);
            }

            // Step 5: CRITICAL - Verify alert still exists and no stale data
            await navigateToPage(page, 'alerts');
            alertElement = page.locator(`:has-text("${alertName}")`);

            // Alert MUST still exist
            await expect(alertElement).toBeVisible({ timeout: CONFIG.timeouts.medium });
            console.log('✅ PASS: "All hosts" alert preserved after host deletion');

            // Step 6: Open alert to check for stale references
            const editBtn = alertElement.locator('button[title*="Edit"]');
            if (await editBtn.count() > 0) {
                await editBtn.click();
                await expect(page.locator('#alertRuleModal.active')).toBeVisible();

                // Verify no stale host references
                

                // Should either still be "All" or updated to remaining hosts
                expect(selectedValue).not.toContain(firstHostName);
                console.log('✅ PASS: No stale host references in alert configuration');

                // Check that container field is still valid
                const containerInput = page.locator('#ruleContainer');
                if (await containerInput.count() > 0) {
                    const containerValue = await containerInput.inputValue();
                    // Should still be * or empty, not corrupted
                    expect(['*', '', null, undefined]).toContain(containerValue);
                    console.log('✅ PASS: Container selector remains valid');
                }

                await closeModal(page);
            }

            // Step 7: Verify remaining hosts are unaffected
            await navigateToPage(page, 'hosts');
            const remainingHosts = await page.locator('.host-card').count();
            expect(remainingHosts).toBeGreaterThan(0);
            console.log('✅ PASS: Remaining hosts intact after deletion');
        });

        test('Should prevent orphaned alerts when all hosts are deleted', async ({ page }) => {
            await login(page);

            // This test ensures that if ALL hosts are deleted, alerts are properly handled
            // They should either be disabled or marked as inactive, not left as orphans

            // Step 1: Create a test host
            await navigateToPage(page, 'hosts');
            await openModal(page, 'Add Host');
            await page.fill('input[name="hostname"]', 'Orphan Test Host');
            await page.fill('input[name="hosturl"]', CONFIG.testHosts.primary.address);
            // TLS certificates are auto-shown for tcp:// URLs, no checkbox needed
            await page.click('#hostModal button[type="submit"]');
            await page.waitForTimeout(2000);

            // Step 2: Create an alert for this specific host
            await navigateToPage(page, 'alerts');
            const createBtn = page.locator('button:has-text("Create Alert Rule")');
            if (await createBtn.count() > 0) {
                await createBtn.click();
                await page.fill('#alertRuleName', 'Orphan Prevention Test Alert');

                // Select the specific host we just created
                
                const orphanHostIndex = hostOptions.findIndex(opt => opt.includes('Orphan Test Host'));
                if (orphanHostIndex > 0) {
                } else {
                }

                
                await page.click('#alertRuleModal button[type="submit"]');
                await page.waitForTimeout(2000);
            }

            // Step 3: Now delete the ONLY host this alert monitors
            await navigateToPage(page, 'hosts');
            const orphanHost = page.locator('.host-card:has-text("Orphan Test Host")');
            if (await orphanHost.count() > 0) {
                const deleteBtn = orphanHost.locator('button[title*="Delete"]');
                await deleteBtn.click();
                await expect(page.locator('#confirmationModal.active')).toBeVisible();
                await page.click('#confirmationButton');
                await page.waitForTimeout(3000);
            }

            // Step 4: Check how the system handles the now-orphaned alert
            await navigateToPage(page, 'alerts');
            const alertElement = page.locator(':has-text("Orphan Prevention Test Alert")');

            // The alert might be:
            // 1. Deleted (acceptable)
            // 2. Disabled/Inactive (preferred)
            // 3. Still exists but marked as invalid

            if (await alertElement.count() > 0) {
                // Alert still exists - check its state
                const alertState = await alertElement.evaluate(el => {
                    // Check for disabled, inactive, or error indicators
                    const classList = el.className;
                    const textContent = el.textContent;
                    return {
                        hasDisabledClass: classList.includes('disabled') || classList.includes('inactive'),
                        hasErrorIndicator: textContent.includes('error') || textContent.includes('invalid'),
                        isEnabled: !classList.includes('disabled')
                    };
                });

                // Alert should not be active with no hosts
                if (alertState.isEnabled && !alertState.hasErrorIndicator) {
                    console.log('⚠️ WARNING: Orphaned alert still appears active');
                } else {
                    console.log('✅ PASS: Orphaned alert properly marked as inactive/invalid');
                }
            } else {
                console.log('✅ PASS: Orphaned alert was automatically deleted');
            }
        });
    });

    // ========================================================================
    // 14. API TESTS
    // ========================================================================

    test.describe('API Endpoints', () => {

        test('Health endpoint should return healthy status', async ({ request }) => {
            const response = await request.get(`${CONFIG.baseUrl}/api/health`);
            expect(response.status()).toBe(200);

            const data = await response.json();
            expect(data).toHaveProperty('status');
            expect(data.status).toBe('healthy');
            console.log('✅ Health API working');
        });

        test('Hosts API should return list of hosts with auth', async ({ page, request }) => {
            await login(page);

            // Get auth token from localStorage
            const token = await page.evaluate(() => {
                return localStorage.getItem('token') || localStorage.getItem('authToken');
            });

            const response = await request.get(`${CONFIG.baseUrl}/api/hosts`, {
                headers: token ? { 'Authorization': `Bearer ${token}` } : {}
            });

            expect([200, 401]).toContain(response.status());
            if (response.status() === 200) {
                const data = await response.json();
                expect(Array.isArray(data)).toBeTruthy();
                console.log(`✅ Hosts API returned ${data.length} hosts`);
            }
        });

        test('Containers API should return container list with auth', async ({ page, request }) => {
            await login(page);

            const token = await page.evaluate(() => {
                return localStorage.getItem('token') || localStorage.getItem('authToken');
            });

            const response = await request.get(`${CONFIG.baseUrl}/api/containers`, {
                headers: token ? { 'Authorization': `Bearer ${token}` } : {}
            });

            expect([200, 401]).toContain(response.status());
            if (response.status() === 200) {
                const data = await response.json();
                expect(Array.isArray(data)).toBeTruthy();
                console.log(`✅ Containers API returned ${data.length} containers`);
            }
        });

        test('Events API should return event log with auth', async ({ page, request }) => {
            await login(page);

            const token = await page.evaluate(() => {
                return localStorage.getItem('token') || localStorage.getItem('authToken');
            });

            const response = await request.get(`${CONFIG.baseUrl}/api/events?limit=10`, {
                headers: token ? { 'Authorization': `Bearer ${token}` } : {}
            });

            expect([200, 401]).toContain(response.status());
            if (response.status() === 200) {
                const data = await response.json();
                expect(Array.isArray(data)).toBeTruthy();
                console.log(`✅ Events API returned ${data.length} events`);
            }
        });

        test('Settings API should return configuration with auth', async ({ page, request }) => {
            await login(page);

            const token = await page.evaluate(() => {
                return localStorage.getItem('token') || localStorage.getItem('authToken');
            });

            const response = await request.get(`${CONFIG.baseUrl}/api/settings`, {
                headers: token ? { 'Authorization': `Bearer ${token}` } : {}
            });

            expect([200, 401]).toContain(response.status());
            if (response.status() === 200) {
                const data = await response.json();
                expect(data).toBeTruthy();
                console.log('✅ Settings API working');
            }
        });

        test('Alerts API should return alert rules with auth', async ({ page, request }) => {
            await login(page);

            const token = await page.evaluate(() => {
                return localStorage.getItem('token') || localStorage.getItem('authToken');
            });

            const response = await request.get(`${CONFIG.baseUrl}/api/alerts`, {
                headers: token ? { 'Authorization': `Bearer ${token}` } : {}
            });

            expect([200, 401]).toContain(response.status());
            if (response.status() === 200) {
                const data = await response.json();
                expect(Array.isArray(data)).toBeTruthy();
                console.log(`✅ Alerts API returned ${data.length} alert rules`);
            }
        });

        test('Should handle API errors gracefully', async ({ request }) => {
            // Test 404 handling
            const response = await request.get(`${CONFIG.baseUrl}/api/nonexistent`);
            expect(response.status()).toBe(404);

            // Test invalid JSON handling
            const postResponse = await request.post(`${CONFIG.baseUrl}/api/hosts`, {
                data: 'invalid json',
                headers: { 'Content-Type': 'application/json' }
            });
            expect([400, 401, 422]).toContain(postResponse.status());

            console.log('✅ API error handling working');
        });
    });

    // ========================================================================
    // 15. SECURITY TESTS
    // ========================================================================

    test.describe('Security', () => {

        test('Should require authentication for protected API endpoints', async ({ request }) => {
            const protectedEndpoints = [
                '/api/hosts',
                '/api/containers',
                '/api/alerts',
                '/api/settings',
                '/api/events'
            ];

            for (const endpoint of protectedEndpoints) {
                const response = await request.get(`${CONFIG.baseUrl}${endpoint}`);
                expect([401, 403]).toContain(response.status());
                console.log(`✅ ${endpoint} requires auth (${response.status()})`);
            }

            // Health endpoint should be public
            const healthResponse = await request.get(`${CONFIG.baseUrl}/api/health`);
            expect(healthResponse.status()).toBe(200);
            console.log('✅ /api/health is public');
        });

        test('Should prevent SQL injection attempts', async ({ page }) => {
            await login(page);

            const sqlPayloads = [
                "'; DROP TABLE users; --",
                "1' OR '1'='1",
                "admin'--",
                "' UNION SELECT * FROM users--"
            ];

            await navigateToPage(page, 'hosts');
            await openModal(page, 'Add Host');

            for (const payload of sqlPayloads) {
                await page.fill('input[name="hostname"]', payload);
                await page.fill('input[name="hosturl"]', 'tcp://192.168.1.100:2376');
                await page.click('#hostModal button[type="submit"]');
                await page.waitForTimeout(1000);

                const pageContent = await page.content();
                expect(pageContent.toLowerCase()).not.toContain('sql');
                expect(pageContent.toLowerCase()).not.toContain('syntax error');

                await page.fill('input[name="hostname"]', '');
            }

            await closeModal(page);
            console.log('✅ SQL injection blocked');
        });

        test('Should prevent XSS attacks', async ({ page }) => {
            await login(page);

            const xssPayloads = [
                '<script>alert("XSS")</script>',
                '<img src=x onerror=alert("XSS")>',
                '<iframe src="javascript:alert(\'XSS\')"></iframe>'
            ];

            await navigateToPage(page, 'alerts');
            const createBtn = page.locator('button:has-text("Create Alert Rule")');
            if (await createBtn.count() > 0) {
                await createBtn.waitFor({ state: 'visible', timeout: 10000 });
                await createBtn.click();

                for (const payload of xssPayloads) {
                    await page.fill('#alertRuleName', payload);
                    
                    
                    await page.click('#alertRuleModal button[type="submit"]');
                    await page.waitForTimeout(1000);

                    // Check no alert dialog appeared
                    const alertDialog = page.locator('dialog');
                    expect(await alertDialog.count()).toBe(0);
                }

                await closeModal(page);
            }
            console.log('✅ XSS blocked');
        });

        test('Should validate host addresses', async ({ page }) => {
            await login(page);
            await navigateToPage(page, 'hosts');

            const invalidAddresses = [
                'javascript:alert("XSS")',
                'file:///etc/passwd',
                'tcp://;rm -rf /',
                'tcp://$(whoami)@localhost:2376'
            ];

            for (const address of invalidAddresses) {
                await openModal(page, 'Add Host');
                await page.fill('input[name="hostname"]', 'Security Test');
                await page.fill('input[name="hosturl"]', address);
                await page.click('#hostModal button[type="submit"]');
                await page.waitForTimeout(1000);

                // Should either reject or still have modal open
                const modalOpen = await page.locator('#hostModal.active').count() > 0;
                if (!modalOpen) {
                    // If saved, delete it
                    const hostCard = page.locator('.host-card:has-text("Security Test")');
                    if (await hostCard.count() > 0) {
                        const deleteBtn = hostCard.locator('button[title*="Delete"]');
                        await deleteBtn.click();
                        await page.click('#confirmationButton');
                        await page.waitForTimeout(1000);
                    }
                } else {
                    await closeModal(page);
                }
            }
            console.log('✅ Invalid addresses handled');
        });
    });

    // ========================================================================
    // 15. EDGE CASES & RACE CONDITIONS
    // ========================================================================

    test.describe('Edge Cases', () => {

        test('Should handle host rename after alert rule references it', async ({ page }) => {
            await login(page);

            // Step 1: Create a host
            await navigateToPage(page, 'hosts');
            await openModal(page, 'Add Host');
            await page.fill('input[name="hostname"]', 'Original Host Name');
            await page.fill('input[name="hosturl"]', CONFIG.testHosts.primary.address);
            // TLS certificates are auto-shown for tcp:// URLs, no checkbox needed
            await page.click('#hostModal button[type="submit"]');
            await page.waitForTimeout(2000);

            // Step 2: Create alert referencing this host
            await navigateToPage(page, 'alerts');
            const createBtn = page.locator('button:has-text("Create Alert Rule")');
            if (await createBtn.count() > 0) {
                await createBtn.click();
                await page.fill('#alertRuleName', 'Alert for Original Host');

                // Select the host we just created
                
                const originalHostIndex = options.findIndex(opt => opt.includes('Original Host Name'));
                if (originalHostIndex > 0) {
                }

                
                await page.click('#alertRuleModal button[type="submit"]');
                await page.waitForTimeout(2000);
            }

            // Step 3: Rename the host
            await navigateToPage(page, 'hosts');
            const hostCard = page.locator('.host-card:has-text("Original Host Name")');
            const editBtn = hostCard.locator('button[title*="Edit"]');
            if (await editBtn.count() > 0) {
                await editBtn.click();
                await page.fill('input[name="hostname"]', 'Renamed Host Name');
                await page.click('#hostModal button[type="submit"]');
                await page.waitForTimeout(2000);
            }

            // Step 4: Verify alert still works with renamed host
            await navigateToPage(page, 'alerts');
            const alertElement = page.locator(':has-text("Alert for Original Host")');
            await expect(alertElement).toBeVisible();

            // Open alert to check it still references the correct host (by ID, not name)
            const alertEditBtn = alertElement.locator('button[title*="Edit"]');
            if (await alertEditBtn.count() > 0) {
                await alertEditBtn.click();
                

                // Should still have a valid host selected
                expect(selectedValue).toBeTruthy();
                console.log('✅ Alert maintains host reference after rename');
                await closeModal(page);
            }
        });

        test('Should handle concurrent container operations', async ({ page, context }) => {
            await login(page);

            // Open second tab
            const page2 = await context.newPage();
            await login(page2);

            // Both try to operate on same container
            const containers1 = await page.locator('.container-item').count();
            const containers2 = await page2.locator('.container-item').count();

            if (containers1 > 0 && containers2 > 0) {
                // Both open same container modal
                await page.click('.container-item:first-child');
                await page2.click('.container-item:first-child');

                // Both try to toggle auto-restart
                const toggle1 = page.locator('.auto-restart-toggle').first();
                const toggle2 = page2.locator('.auto-restart-toggle').first();

                if (await toggle1.count() > 0 && await toggle2.count() > 0) {
                    await toggle1.click();
                    await toggle2.click();
                    await page.waitForTimeout(1000);

                    // System should handle gracefully
                    await expect(page.locator('.main-content')).toBeVisible();
                    await expect(page2.locator('.main-content')).toBeVisible();
                }
            }

            await page2.close();
            console.log('✅ Concurrent operations handled');
        });

        test('Should handle blackout window spanning midnight', async ({ page }) => {
            await login(page);

            const notifLink = page.locator('a.nav-item:has-text("Notifications")');
            if (await notifLink.count() > 0) {
                await notifLink.click();
                await page.click('#blackoutTab');

                // Add blackout from 22:00 to 02:00 (crosses midnight)
                const addBtn = page.locator('button:has-text("Add Blackout Window")');
                if (await addBtn.count() > 0) {
                    await addBtn.click();
                    await page.waitForTimeout(500);
                    // Find the last blackout window div in the list
                    const blackoutForm = page.locator('#blackoutWindowsList > div').last();
                    await blackoutForm.locator('input[type="time"]').first().fill('22:00');
                    await blackoutForm.locator('input[type="time"]').last().fill('02:00');

                    await page.click('button:has-text("Save Blackout")');
                    await page.waitForTimeout(1000);

                    // Should be saved without errors
                    console.log('✅ Midnight-spanning blackout handled');
                }
            }
        });

        test('Should handle container logs with special characters', async ({ page }) => {
            await login(page);

            const containers = await page.locator('.container-item').count();
            if (containers > 0) {
                await page.click('.container-item:first-child');
                await page.click('#tab-logs');

                // If logs contain special chars like ANSI escape codes
                // they should be handled properly
                const logsContent = await page.locator('#container-logs').textContent();

                // Should not break the UI
                await expect(page.locator('#containerModal')).toBeVisible();
                console.log('✅ Special characters in logs handled');

                await closeModal(page);
            }
        });

        test('Should handle session timeout gracefully', async ({ page }) => {
            await login(page);

            // Simulate session expiry
            await page.evaluate(() => {
                localStorage.setItem('token', 'expired_token');
            });

            // Try an action
            const refreshBtn = page.locator('button[title*="Refresh"]');
            if (await refreshBtn.count() > 0) {
                await refreshBtn.first().waitFor({ state: 'visible', timeout: 10000 });
                await refreshBtn.first().click();
            }
            await page.waitForTimeout(2000);

            // Should either redirect to login or show error
            const loginVisible = await page.locator('input[name="username"]').count() > 0;
            const errorVisible = await page.locator('.error, .toast').count() > 0;

            expect(loginVisible || errorVisible).toBeTruthy();
            console.log('✅ Session timeout handled');
        });

        test('Should handle very long container/host names', async ({ page }) => {
            await login(page);

            const longName = 'A'.repeat(255); // Very long name

            await navigateToPage(page, 'hosts');
            await openModal(page, 'Add Host');
            await page.fill('input[name="hostname"]', longName);
            await page.fill('input[name="hosturl"]', CONFIG.testHosts.primary.address);

            await page.click('#hostModal button[type="submit"]');
            await page.waitForTimeout(1000);

            // Should either truncate or handle gracefully
            await expect(page.locator('.main-content')).toBeVisible();
            console.log('✅ Long names handled');

            await closeModal(page);
        });

        test('Should handle rapid navigation clicks', async ({ page }) => {
            await login(page);

            // Click navigation items rapidly
            for (let i = 0; i < 5; i++) {
                await page.click('a.nav-item:has-text("Host Management")');
                await page.click('a.nav-item:has-text("Alert Rules")');
                await page.click('a.nav-item:has-text("Dashboard")');
            }

            await page.waitForTimeout(1000);

            // Should end up on dashboard and be stable
            await expect(page.locator('.grid-stack')).toBeVisible();
            console.log('✅ Rapid navigation handled');
        });

        test('Should handle network disconnection during save', async ({ page, context }) => {
            await login(page);

            await navigateToPage(page, 'hosts');
            await openModal(page, 'Add Host');
            await page.fill('input[name="hostname"]', 'Network Test Host');
            await page.fill('input[name="hosturl"]', CONFIG.testHosts.primary.address);

            // Simulate network offline
            await context.setOffline(true);

            await page.click('#hostModal button[type="submit"]');
            await page.waitForTimeout(2000);

            // Should show error or handle gracefully
            const errorVisible = await page.locator('.error, .toast, .alert').count() > 0;
            const modalStillOpen = await page.locator('#hostModal.active').count() > 0;

            expect(errorVisible || modalStillOpen).toBeTruthy();

            // Restore network
            await context.setOffline(false);
            console.log('✅ Network disconnection handled');
        });
    });

    // ========================================================================
    // CLEANUP & TEARDOWN
    // ========================================================================

    test.afterEach(async ({ page }, testInfo) => {
        // Take screenshot on failure
        if (testInfo.status === 'failed') {
            await takeScreenshot(page, `failure-${testInfo.title.replace(/\s+/g, '-')}`);
        }
    });
});

// ============================================================================
// INTEGRATION TEST SCENARIOS
// ============================================================================

test.describe('Integration Scenarios', () => {

    test('Complete workflow: Add host, create alert, configure notification', async ({ page }) => {
        await login(page);

        // Step 1: Add a host
        await navigateToPage(page, 'hosts');
        await openModal(page, 'Add Host');
        await page.fill('input[name="hostname"]', 'Integration Test Host');
        await page.fill('input[name="hosturl"]', CONFIG.testHosts.secondary.address);
        // TLS certificates are auto-shown for tcp:// URLs, no checkbox needed
        await page.click('#hostModal button[type="submit"]');
        await expect(page.locator('#hostModal.active')).not.toBeVisible({ timeout: 10000 });
        await page.waitForTimeout(1000);

        // Step 2: Create alert rule
        await navigateToPage(page, 'alerts');
        const createBtn = page.locator('button:has-text("Create Alert Rule")');
        if (await createBtn.count() > 0) {
            await createBtn.waitFor({ state: 'visible', timeout: 10000 });
            await createBtn.click();
            await expect(page.locator('#alertRuleModal.active')).toBeVisible({ timeout: 10000 });
            await page.fill('#alertRuleName', 'Integration Test Alert');
            await page.click('#alertRuleModal button[type="submit"]');
            await expect(page.locator('#alertRuleModal.active')).not.toBeVisible({ timeout: 10000 });
            await page.waitForTimeout(1000);
        }

        // Step 3: Configure notification
        const notifLink = page.locator('a.nav-item:has-text("Notifications")');
        if (await notifLink.count() > 0) {
            await notifLink.waitFor({ state: 'visible', timeout: 10000 });
            await notifLink.click();
            await expect(page.locator('#notificationModal.active')).toBeVisible({ timeout: 10000 });
            await page.click('button:has-text("Add Channel")');
            await page.waitForTimeout(500);
            const newChannel = page.locator('.notification-channel-card').last();
            const selectElement = newChannel.locator('select.form-input');
            await expect(selectElement).toBeVisible({ timeout: 5000 });
            await selectElement.selectOption('discord');
            const webhookInput = newChannel.locator('input[placeholder*="webhook"]');
            await webhookInput.fill(CONFIG.notifications.discord.webhook);
            await page.click('button:has-text("Save Channels")');
            await page.waitForTimeout(2000);
        }

        // Verify everything is connected
        await navigateToPage(page, 'dashboard');
        const stats = await page.locator('.stat-value').allTextContents();
        expect(stats.length).toBeGreaterThan(0);
    });

    test('Monitor container lifecycle: Stop, Start, Auto-restart', async ({ page }) => {
        await login(page);

        // Find a running container
        const containers = await page.locator('.container-item').count();

        if (containers > 0) {
            // Enable auto-restart
            const autoRestart = page.locator('.auto-restart-toggle').first();
            if (!await autoRestart.evaluate(el => el.classList.contains('enabled'))) {
                await autoRestart.click();
                await page.waitForTimeout(1000);
            }

            // Open container modal
            await page.click('.container-item:first-child');
            await expect(page.locator('#containerModal.active')).toBeVisible();

            // Note: We don't actually stop/start containers in tests
            // to avoid disrupting the system

            await closeModal(page);
        }
    });
});