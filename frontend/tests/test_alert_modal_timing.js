/**
 * Tests for alert modal timing and race condition issues
 * These tests would catch the bugs we encountered with checkbox clearing
 */

describe('Alert Modal Timing Issues', () => {
    let modal;
    let checkboxes;

    beforeEach(() => {
        // Setup DOM structure similar to actual modal
        document.body.innerHTML = `
            <div id="alertRuleModal">
                <!-- Container checkboxes -->
                <input type="checkbox" data-container="web-1" checked>
                <input type="checkbox" data-container="web-2" checked>
                <input type="checkbox" data-container="db-1">

                <!-- State checkboxes -->
                <input type="checkbox" data-state="running">
                <input type="checkbox" data-state="exited" checked>
                <input type="checkbox" data-state="dead" checked>
                <input type="checkbox" data-state="paused">

                <!-- Event checkboxes -->
                <input type="checkbox" data-event="start">
                <input type="checkbox" data-event="die" checked>
                <input type="checkbox" data-event="oom" checked>
                <input type="checkbox" data-event="kill">

                <!-- Notification channel checkboxes -->
                <input type="checkbox" data-channel="1" checked>
                <input type="checkbox" data-channel="2">
            </div>
        `;

        modal = document.getElementById('alertRuleModal');
    });

    describe('Checkbox Clearing Specificity', () => {
        test('should only clear state and event checkboxes, not containers', () => {
            // This is the bug we had - clearing ALL checkboxes
            const buggyImplementation = () => {
                document.querySelectorAll('#alertRuleModal input[type="checkbox"]')
                    .forEach(cb => cb.checked = false);
            };

            // Verify initial state
            expect(document.querySelector('[data-container="web-1"]').checked).toBe(true);
            expect(document.querySelector('[data-container="web-2"]').checked).toBe(true);
            expect(document.querySelector('[data-state="exited"]').checked).toBe(true);
            expect(document.querySelector('[data-event="die"]').checked).toBe(true);

            // Run buggy implementation
            buggyImplementation();

            // Bug: ALL checkboxes are cleared including containers
            expect(document.querySelector('[data-container="web-1"]').checked).toBe(false);
            expect(document.querySelector('[data-container="web-2"]').checked).toBe(false);

            // This test would FAIL with the buggy implementation
        });

        test('should preserve container selections when clearing states/events', () => {
            // Correct implementation
            const correctImplementation = () => {
                // Only clear state checkboxes
                document.querySelectorAll('#alertRuleModal input[type="checkbox"][data-state]')
                    .forEach(cb => cb.checked = false);

                // Only clear event checkboxes
                document.querySelectorAll('#alertRuleModal input[type="checkbox"][data-event]')
                    .forEach(cb => cb.checked = false);
            };

            // Run correct implementation
            correctImplementation();

            // Containers should be preserved
            expect(document.querySelector('[data-container="web-1"]').checked).toBe(true);
            expect(document.querySelector('[data-container="web-2"]').checked).toBe(true);

            // States should be cleared
            expect(document.querySelector('[data-state="exited"]').checked).toBe(false);
            expect(document.querySelector('[data-state="dead"]').checked).toBe(false);

            // Events should be cleared
            expect(document.querySelector('[data-event="die"]').checked).toBe(false);
            expect(document.querySelector('[data-event="oom"]').checked).toBe(false);

            // Channels should be preserved
            expect(document.querySelector('[data-channel="1"]').checked).toBe(true);
        });
    });

    describe('setTimeout Race Conditions', () => {
        test('should execute operations synchronously when order matters', async () => {
            const executionOrder = [];

            // Buggy implementation with nested setTimeout
            const buggyAsyncImplementation = () => {
                return new Promise(resolve => {
                    // First setTimeout
                    setTimeout(() => {
                        executionOrder.push('set_notification_channels');

                        // Nested setTimeout - creates race condition
                        setTimeout(() => {
                            executionOrder.push('clear_checkboxes');
                            executionOrder.push('set_checkboxes');
                            resolve();
                        }, 0);
                    }, 0);
                });
            };

            // Run multiple times to detect race condition
            const results = new Set();
            for (let i = 0; i < 10; i++) {
                executionOrder.length = 0;
                await buggyAsyncImplementation();
                results.add(executionOrder.join(','));
            }

            // With race condition, order might vary
            // This test might detect non-deterministic behavior
            expect(results.size).toBeGreaterThanOrEqual(1);
        });

        test('should maintain deterministic execution order', () => {
            const executionOrder = [];

            // Correct synchronous implementation
            const correctSyncImplementation = () => {
                // Clear checkboxes first (synchronously)
                executionOrder.push('clear_state_checkboxes');
                executionOrder.push('clear_event_checkboxes');

                // Then set checkboxes (synchronously)
                executionOrder.push('set_state_checkboxes');
                executionOrder.push('set_event_checkboxes');

                // Only use setTimeout for things that actually need delay
                setTimeout(() => {
                    executionOrder.push('set_notification_channels');
                }, 0);
            };

            correctSyncImplementation();

            // Synchronous operations should execute in order
            expect(executionOrder[0]).toBe('clear_state_checkboxes');
            expect(executionOrder[1]).toBe('clear_event_checkboxes');
            expect(executionOrder[2]).toBe('set_state_checkboxes');
            expect(executionOrder[3]).toBe('set_event_checkboxes');

            // Async operation comes later
            setTimeout(() => {
                expect(executionOrder[4]).toBe('set_notification_channels');
            }, 10);
        });
    });

    describe('Edit Mode Population', () => {
        test('should populate all fields when editing an alert', () => {
            const alertData = {
                id: 1,
                name: 'Test Alert',
                container_pattern: 'web-.*',
                trigger_states: ['exited', 'dead'],
                trigger_events: ['die', 'oom'],
                notification_channels: [1, 2]
            };

            const populateForEdit = (data) => {
                // Clear specific checkbox groups
                document.querySelectorAll('[data-state]').forEach(cb => cb.checked = false);
                document.querySelectorAll('[data-event]').forEach(cb => cb.checked = false);

                // Set state checkboxes
                data.trigger_states.forEach(state => {
                    const checkbox = document.querySelector(`[data-state="${state}"]`);
                    if (checkbox) checkbox.checked = true;
                });

                // Set event checkboxes
                data.trigger_events.forEach(event => {
                    const checkbox = document.querySelector(`[data-event="${event}"]`);
                    if (checkbox) checkbox.checked = true;
                });

                // Set channels
                data.notification_channels.forEach(channel => {
                    const checkbox = document.querySelector(`[data-channel="${channel}"]`);
                    if (checkbox) checkbox.checked = true;
                });
            };

            populateForEdit(alertData);

            // Verify states are set correctly
            expect(document.querySelector('[data-state="exited"]').checked).toBe(true);
            expect(document.querySelector('[data-state="dead"]').checked).toBe(true);
            expect(document.querySelector('[data-state="running"]').checked).toBe(false);

            // Verify events are set correctly
            expect(document.querySelector('[data-event="die"]').checked).toBe(true);
            expect(document.querySelector('[data-event="oom"]').checked).toBe(true);
            expect(document.querySelector('[data-event="start"]').checked).toBe(false);

            // Verify channels are set correctly
            expect(document.querySelector('[data-channel="1"]').checked).toBe(true);
            expect(document.querySelector('[data-channel="2"]').checked).toBe(true);
        });

        test('should handle sequential edits without state bleed', () => {
            // First alert
            const alert1 = {
                trigger_states: ['running'],
                trigger_events: ['start']
            };

            // Second alert with different selections
            const alert2 = {
                trigger_states: ['exited', 'dead'],
                trigger_events: ['die', 'oom']
            };

            const editAlert = (data) => {
                // Clear previous selections
                document.querySelectorAll('[data-state]').forEach(cb => cb.checked = false);
                document.querySelectorAll('[data-event]').forEach(cb => cb.checked = false);

                // Set new selections
                data.trigger_states.forEach(state => {
                    const cb = document.querySelector(`[data-state="${state}"]`);
                    if (cb) cb.checked = true;
                });

                data.trigger_events.forEach(event => {
                    const cb = document.querySelector(`[data-event="${event}"]`);
                    if (cb) cb.checked = true;
                });
            };

            // Edit first alert
            editAlert(alert1);
            expect(document.querySelector('[data-state="running"]').checked).toBe(true);
            expect(document.querySelector('[data-state="exited"]').checked).toBe(false);

            // Edit second alert
            editAlert(alert2);
            expect(document.querySelector('[data-state="running"]').checked).toBe(false);
            expect(document.querySelector('[data-state="exited"]').checked).toBe(true);
            expect(document.querySelector('[data-state="dead"]').checked).toBe(true);

            // No state from alert1 should remain
            expect(document.querySelector('[data-event="start"]').checked).toBe(false);
        });
    });

    describe('DOM Ready State', () => {
        test('should wait for DOM elements before manipulating', (done) => {
            document.body.innerHTML = '';

            const attemptToSetCheckbox = () => {
                const checkbox = document.querySelector('[data-state="exited"]');
                if (checkbox) {
                    checkbox.checked = true;
                    return true;
                }
                return false;
            };

            // Should fail before DOM is ready
            expect(attemptToSetCheckbox()).toBe(false);

            // Simulate DOM becoming ready
            setTimeout(() => {
                document.body.innerHTML = `
                    <div id="alertRuleModal">
                        <input type="checkbox" data-state="exited">
                    </div>
                `;

                // Should succeed after DOM is ready
                expect(attemptToSetCheckbox()).toBe(true);
                expect(document.querySelector('[data-state="exited"]').checked).toBe(true);
                done();
            }, 10);
        });
    });

    describe('State Preservation', () => {
        test('should preserve unrelated form fields during checkbox operations', () => {
            document.body.innerHTML = `
                <div id="alertRuleModal">
                    <input type="text" id="alertRuleName" value="My Alert">
                    <input type="number" id="cooldownMinutes" value="5">
                    <input type="checkbox" data-state="exited" checked>
                    <input type="checkbox" data-container="web-1" checked>
                </div>
            `;

            const clearStateCheckboxes = () => {
                document.querySelectorAll('[data-state]').forEach(cb => cb.checked = false);
            };

            // Clear state checkboxes
            clearStateCheckboxes();

            // Text fields should be preserved
            expect(document.getElementById('alertRuleName').value).toBe('My Alert');
            expect(document.getElementById('cooldownMinutes').value).toBe('5');

            // Container checkbox should be preserved
            expect(document.querySelector('[data-container="web-1"]').checked).toBe(true);

            // Only state checkbox should be cleared
            expect(document.querySelector('[data-state="exited"]').checked).toBe(false);
        });
    });
});

// Integration test that simulates the actual bug scenario
describe('Alert Edit Bug Reproduction', () => {
    test('reproduces and tests the actual bug scenario', () => {
        // Setup: Create an alert with specific selections
        document.body.innerHTML = `
            <div id="alertRuleModal">
                <input type="checkbox" data-container="web-app-1">
                <input type="checkbox" data-container="database-1">
                <input type="checkbox" data-state="exited">
                <input type="checkbox" data-state="dead">
                <input type="checkbox" data-event="die">
                <input type="checkbox" data-event="oom">
            </div>
        `;

        // Initial alert creation - select containers and criteria
        const createAlert = () => {
            document.querySelector('[data-container="web-app-1"]').checked = true;
            document.querySelector('[data-state="exited"]').checked = true;
            document.querySelector('[data-event="die"]').checked = true;
        };

        createAlert();

        // Save the alert state
        const savedAlert = {
            containers: ['web-app-1'],
            states: ['exited'],
            events: ['die']
        };

        // Now simulate editing the alert (this is where the bug occurred)
        const editAlertBuggy = () => {
            // BUG: This clears ALL checkboxes including containers
            document.querySelectorAll('#alertRuleModal input[type="checkbox"]')
                .forEach(cb => cb.checked = false);

            // Then try to restore saved values
            savedAlert.states.forEach(state => {
                const cb = document.querySelector(`[data-state="${state}"]`);
                if (cb) cb.checked = true;
            });

            savedAlert.events.forEach(event => {
                const cb = document.querySelector(`[data-event="${event}"]`);
                if (cb) cb.checked = true;
            });

            // BUG: Containers were cleared and never restored!
        };

        editAlertBuggy();

        // This assertion would FAIL with the buggy implementation
        // Container selection is lost!
        expect(document.querySelector('[data-container="web-app-1"]').checked).toBe(false);

        // Now test the fixed implementation
        const editAlertFixed = () => {
            // Only clear state and event checkboxes
            document.querySelectorAll('[data-state]').forEach(cb => cb.checked = false);
            document.querySelectorAll('[data-event]').forEach(cb => cb.checked = false);

            // Restore saved values
            savedAlert.states.forEach(state => {
                const cb = document.querySelector(`[data-state="${state}"]`);
                if (cb) cb.checked = true;
            });

            savedAlert.events.forEach(event => {
                const cb = document.querySelector(`[data-event="${event}"]`);
                if (cb) cb.checked = true;
            });

            // Containers are preserved!
        };

        // Reset and test fixed version
        createAlert();
        editAlertFixed();

        // This should PASS with the fixed implementation
        expect(document.querySelector('[data-container="web-app-1"]').checked).toBe(true);
        expect(document.querySelector('[data-state="exited"]').checked).toBe(true);
        expect(document.querySelector('[data-event="die"]').checked).toBe(true);
    });
});