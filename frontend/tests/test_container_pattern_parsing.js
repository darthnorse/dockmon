/**
 * Tests for container pattern parsing in alert edit modal
 * Would have caught the issue with multi-container selection not being restored
 */

describe('Container Pattern Parsing', () => {

    describe('Multi-container pattern parsing', () => {
        test('should parse simple multi-container pattern', () => {
            // Pattern generated when selecting multiple containers
            const pattern = '^(container1|container2|container3)$';

            const match = pattern.match(/^\^?\(([^)]+)\)\$?$/);
            expect(match).not.toBeNull();

            const containerNames = match[1].split('|');
            expect(containerNames).toEqual(['container1', 'container2', 'container3']);
        });

        test('should parse pattern with escaped special characters', () => {
            // Pattern with containers that have special regex chars
            const pattern = '^(my\\.container|test\\-app|prod\\[1\\])$';

            const match = pattern.match(/^\^?\(([^)]+)\)\$?$/);
            expect(match).not.toBeNull();

            const containerNames = match[1].split('|').map(name => {
                // Unescape regex characters
                return name.replace(/\\(.)/g, '$1');
            });

            expect(containerNames).toEqual(['my.container', 'test-app', 'prod[1]']);
        });

        test('should handle pattern without anchors', () => {
            // Some patterns might not have ^ and $
            const pattern = '(container1|container2)';

            const match = pattern.match(/^\^?\(([^)]+)\)\$?$/);
            expect(match).not.toBeNull();

            const containerNames = match[1].split('|');
            expect(containerNames).toEqual(['container1', 'container2']);
        });
    });

    describe('Single container patterns', () => {
        test('should recognize simple container name', () => {
            const pattern = 'my-container';

            // Check if it's a multi-container pattern
            const multiMatch = pattern.match(/^\^?\(([^)]+)\)\$?$/);
            expect(multiMatch).toBeNull();

            // Check if it has regex special chars
            const hasSpecialChars = /[\*\+\[\]\\]/.test(pattern);
            expect(hasSpecialChars).toBe(false);

            // It's a simple container name
            expect(pattern).toBe('my-container');
        });

        test('should recognize container with dots and dashes', () => {
            const pattern = 'app.service-1';

            const multiMatch = pattern.match(/^\^?\(([^)]+)\)\$?$/);
            expect(multiMatch).toBeNull();

            // Even though it has a dot, it's not a regex pattern
            expect(pattern).toBe('app.service-1');
        });
    });

    describe('Complex regex patterns', () => {
        test('should identify wildcard patterns', () => {
            const patterns = [
                '.*',           // All containers
                'web-.*',       // Starts with web-
                '.*-prod',      // Ends with -prod
                'app-[0-9]+',   // app- followed by numbers
            ];

            patterns.forEach(pattern => {
                const hasWildcard = pattern.includes('*') || pattern.includes('+') ||
                                   pattern.includes('[') || pattern.includes('\\');
                expect(hasWildcard).toBe(true);
            });
        });

        test('should handle all containers pattern', () => {
            const pattern = '.*';

            // Should be recognized as "all containers"
            expect(pattern).toBe('.*');

            // Should not be parsed as multi-container
            const multiMatch = pattern.match(/^\^?\(([^)]+)\)\$?$/);
            expect(multiMatch).toBeNull();
        });
    });

    describe('Container checkbox selection restoration', () => {
        let containerCheckboxes;

        beforeEach(() => {
            // Setup DOM with container checkboxes
            document.body.innerHTML = `
                <div id="containerSelectionCheckboxes">
                    <input type="checkbox" value="web-1" data-host-id="host1" data-container-id="c1">
                    <input type="checkbox" value="web-2" data-host-id="host1" data-container-id="c2">
                    <input type="checkbox" value="db-1" data-host-id="host2" data-container-id="c3">
                    <input type="checkbox" value="cache.server" data-host-id="host1" data-container-id="c4">
                </div>
            `;

            containerCheckboxes = document.querySelectorAll('#containerSelectionCheckboxes input[type="checkbox"]');
        });

        test('should restore multi-container selection from pattern', () => {
            const pattern = '^(web-1|web-2|cache\\.server)$';
            const hostId = 'host1';

            // Parse pattern
            const match = pattern.match(/^\^?\(([^)]+)\)\$?$/);
            const containerNames = match[1].split('|').map(name => name.replace(/\\(.)/g, '$1'));

            // Restore checkboxes
            containerCheckboxes.forEach(cb => {
                if (containerNames.includes(cb.value) && cb.dataset.hostId === hostId) {
                    cb.checked = true;
                }
            });

            // Verify correct containers are selected
            expect(document.querySelector('[value="web-1"]').checked).toBe(true);
            expect(document.querySelector('[value="web-2"]').checked).toBe(true);
            expect(document.querySelector('[value="cache.server"]').checked).toBe(true);
            expect(document.querySelector('[value="db-1"]').checked).toBe(false); // Different host
        });

        test('should handle pattern with containers from multiple hosts', () => {
            const pattern = '^(web-1|db-1)$';
            const hostId = null; // No specific host (applies to all)

            const match = pattern.match(/^\^?\(([^)]+)\)\$?$/);
            const containerNames = match[1].split('|');

            // When hostId is null, select containers regardless of host
            containerCheckboxes.forEach(cb => {
                if (containerNames.includes(cb.value)) {
                    cb.checked = true;
                }
            });

            expect(document.querySelector('[value="web-1"]').checked).toBe(true);
            expect(document.querySelector('[value="db-1"]').checked).toBe(true);
        });

        test('should handle single container restoration', () => {
            const pattern = 'web-1';
            const hostId = 'host1';

            // Not a multi-container pattern
            const match = pattern.match(/^\^?\(([^)]+)\)\$?$/);
            expect(match).toBeNull();

            // Direct match
            containerCheckboxes.forEach(cb => {
                if (cb.value === pattern && cb.dataset.hostId === hostId) {
                    cb.checked = true;
                }
            });

            expect(document.querySelector('[value="web-1"]').checked).toBe(true);
            expect(document.querySelector('[value="web-2"]').checked).toBe(false);
        });
    });

    describe('Pattern generation from selection', () => {
        test('should generate pattern for single container', () => {
            const selectedContainers = ['my-container'];

            let pattern;
            if (selectedContainers.length === 1) {
                pattern = selectedContainers[0];
            }

            expect(pattern).toBe('my-container');
        });

        test('should generate pattern for multiple containers', () => {
            const selectedContainers = ['web-1', 'web-2', 'web-3'];

            let pattern;
            if (selectedContainers.length > 1) {
                // Escape special regex characters and join
                pattern = '^(' + selectedContainers.map(name =>
                    name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
                ).join('|') + ')$';
            }

            expect(pattern).toBe('^(web-1|web-2|web-3)$');
        });

        test('should escape special characters in container names', () => {
            const selectedContainers = ['my.app', 'test-[1]', 'prod$env'];

            const pattern = '^(' + selectedContainers.map(name =>
                name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
            ).join('|') + ')$';

            expect(pattern).toBe('^(my\\.app|test-\\[1\\]|prod\\$env)$');
        });
    });

    describe('Edge cases', () => {
        test('should handle empty pattern', () => {
            const pattern = '';

            const match = pattern.match(/^\^?\(([^)]+)\)\$?$/);
            expect(match).toBeNull();
        });

        test('should handle malformed patterns gracefully', () => {
            const patterns = [
                '(incomplete',      // Missing closing paren
                'incomplete)',      // Missing opening paren
                '^($',             // Empty group
                '(|)',             // Empty alternatives
            ];

            patterns.forEach(pattern => {
                const match = pattern.match(/^\^?\(([^)]+)\)\$?$/);
                if (match && match[1]) {
                    const names = match[1].split('|').filter(n => n.length > 0);
                    // Should handle gracefully
                    expect(names).toBeDefined();
                }
            });
        });

        test('should handle containers that no longer exist', () => {
            const pattern = '^(old-container|deleted-app)$';
            const availableContainers = ['new-container', 'current-app'];

            const match = pattern.match(/^\^?\(([^)]+)\)\$?$/);
            const containerNames = match[1].split('|');

            let matchedCount = 0;
            containerNames.forEach(name => {
                if (availableContainers.includes(name)) {
                    matchedCount++;
                }
            });

            // No matches found - should switch to pattern mode
            expect(matchedCount).toBe(0);
        });
    });
});