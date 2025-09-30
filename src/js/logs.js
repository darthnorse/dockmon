// logs.js - Container Logs Viewer with multi-container support

let selectedContainers = []; // Array of {hostId, containerId, name}
let logsPaused = false;
let logsPollingInterval = null;
let allLogs = []; // Consolidated logs from all containers
let containerColorMap = {}; // Map container IDs to color indices
let nextColorIndex = 0;
let logsSortOrder = 'desc'; // 'asc' or 'desc'
let isFetchingLogs = false; // Prevent concurrent fetch calls
let isRestoringSelection = false; // Prevent onchange during dropdown rebuild
let pendingSelectionChange = false; // Track if selection changed while dropdown was open

// Initialize logs page when switched to
function initLogsPage() {
    // Wait a bit for hosts data to load if needed
    if (!window.hosts || window.hosts.length === 0) {
        setTimeout(() => {
            populateContainerList();
        }, 500);
    } else {
        populateContainerList();
    }
    stopLogsPolling(); // Stop any existing polling
    loadLogsSortOrder();
}

// Load sort order from localStorage
function loadLogsSortOrder() {
    const saved = localStorage.getItem('logsSortOrder');
    if (saved) {
        logsSortOrder = saved;
        updateLogsSortButton();
    }
}

// Save sort order to localStorage
function saveLogsSortOrder() {
    localStorage.setItem('logsSortOrder', logsSortOrder);
}

// Populate container list for multi-select
function populateContainerList() {
    const dropdown = document.getElementById('logsContainerDropdown');
    if (!dropdown) {
        console.error('Dropdown element not found');
        return;
    }

    // Save current selection state before rebuilding
    const selectedKeys = selectedContainers.map(c => `${c.hostId}:${c.containerId}`);

    // Prevent onchange events during restoration
    isRestoringSelection = true;

    dropdown.innerHTML = '';

    // Get hosts and containers from global arrays (populated by core.js via WebSocket)
    if (!window.hosts || window.hosts.length === 0) {
        dropdown.innerHTML = '<div style="padding: 12px; color: var(--text-tertiary);">No hosts available. Make sure you have hosts configured.</div>';
        return;
    }

    if (!window.containers || window.containers.length === 0) {
        dropdown.innerHTML = '<div style="padding: 12px; color: var(--text-tertiary);">No containers available. Make sure your hosts have running containers.</div>';
        return;
    }

    // Group containers by host_id
    const containersByHost = {};
    window.containers.forEach(container => {
        if (!containersByHost[container.host_id]) {
            containersByHost[container.host_id] = [];
        }
        containersByHost[container.host_id].push(container);
    });

    let totalContainers = 0;

    // Sort hosts by dashboard widget position (left-to-right, top-to-bottom)
    // Get widget positions from GridStack if available
    let sortedHosts = [...window.hosts];
    if (typeof grid !== 'undefined' && grid) {
        const widgetPositions = {};
        grid.getGridItems().forEach(widget => {
            const widgetId = widget.getAttribute('data-widget-id');
            if (widgetId && widgetId.startsWith('host-')) {
                const hostId = widgetId.replace('host-', '');
                const gridData = widget.gridstackNode;
                if (gridData) {
                    widgetPositions[hostId] = { y: gridData.y, x: gridData.x };
                }
            }
        });

        // Sort by y (row) first, then x (column)
        sortedHosts.sort((a, b) => {
            const posA = widgetPositions[a.id];
            const posB = widgetPositions[b.id];

            // If no position data, put at end
            if (!posA && !posB) return 0;
            if (!posA) return 1;
            if (!posB) return -1;

            // Sort by row (y), then column (x)
            if (posA.y !== posB.y) {
                return posA.y - posB.y;
            }
            return posA.x - posB.x;
        });
    }

    // Iterate through hosts and show their containers
    sortedHosts.forEach(host => {
        const hostContainers = containersByHost[host.id] || [];
        if (hostContainers.length === 0) return;

        // Sort containers alphabetically by name (same as dashboard)
        hostContainers.sort((a, b) => a.name.localeCompare(b.name));

        totalContainers += hostContainers.length;

        // Add host header
        const hostHeader = document.createElement('div');
        hostHeader.style.padding = '8px 12px';
        hostHeader.style.fontWeight = '600';
        hostHeader.style.color = 'var(--text-secondary)';
        hostHeader.style.fontSize = '12px';
        hostHeader.style.borderBottom = '1px solid var(--border)';
        hostHeader.textContent = host.name;
        dropdown.appendChild(hostHeader);

        // Add containers for this host
        hostContainers.forEach(container => {
            const label = document.createElement('label');
            label.style.display = 'block';
            label.style.padding = '8px 12px';
            label.style.cursor = 'pointer';

            // Determine status color and symbol
            let statusColor, statusSymbol;
            if (container.state === 'running') {
                statusColor = '#22c55e'; // Green
                statusSymbol = '●';
            } else if (container.state === 'exited') {
                statusColor = '#ef4444'; // Red
                statusSymbol = '●';
            } else {
                statusColor = '#6b7280'; // Grey
                statusSymbol = '○';
            }

            const containerKey = `${host.id}:${container.id}`;
            const isSelected = selectedKeys.includes(containerKey);

            label.innerHTML = `
                <input type="checkbox"
                       value="${containerKey}"
                       ${isSelected ? 'checked' : ''}
                       onchange="updateContainerSelection()">
                <span style="margin-left: 8px;">${container.name}</span>
                <span style="margin-left: 8px; color: ${statusColor}; font-size: 11px;">
                    ${statusSymbol}
                </span>
            `;
            dropdown.appendChild(label);
        });
    });

    if (totalContainers === 0) {
        dropdown.innerHTML = '<div style="padding: 12px; color: var(--text-tertiary);">No containers available. Make sure your hosts have running containers.</div>';
    }

    // Re-enable onchange events after restoration is complete
    setTimeout(() => {
        isRestoringSelection = false;
    }, 0);
}

// Update selected containers and fetch logs immediately
function updateContainerSelection() {
    // Skip if we're just restoring selection during dropdown rebuild
    if (isRestoringSelection) {
        return;
    }

    // Update UI immediately (label and selection state)
    const dropdown = document.getElementById('logsContainerDropdown');
    const checkboxes = dropdown.querySelectorAll('input[type="checkbox"]:checked');

    // Enforce 15 container limit to protect API
    if (checkboxes.length > 15) {
        showToast('⚠️ Maximum 15 containers can be selected at once', 'warning');
        // Uncheck the last selected checkbox
        checkboxes[checkboxes.length - 1].checked = false;
        return;
    }

    selectedContainers = Array.from(checkboxes).map(cb => {
        const [hostId, containerId] = cb.value.split(':');
        const containersData = window.containers || [];
        const container = containersData.find(c => c.id === containerId && c.host_id === hostId);
        return {
            hostId,
            containerId,
            name: container?.name || 'Unknown'
        };
    });

    // Update label
    const label = document.querySelector('#logsContainerMultiselect .multiselect-label');
    if (selectedContainers.length === 0) {
        label.textContent = 'Select containers to view logs...';
    } else if (selectedContainers.length === 1) {
        label.textContent = selectedContainers[0].name;
    } else {
        label.textContent = `${selectedContainers.length} containers selected`;
    }

    // Assign colors to containers
    selectedContainers.forEach((container, index) => {
        const key = `${container.hostId}:${container.containerId}`;
        if (!(key in containerColorMap)) {
            containerColorMap[key] = nextColorIndex % 8;
            nextColorIndex++;
        }
    });

    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }

    // Reload logs immediately (no rate limiting on backend for authenticated users)
    reloadLogs();
}

// Reload logs from scratch
async function reloadLogs() {
    stopLogsPolling();
    allLogs = [];

    if (selectedContainers.length === 0) {
        showLogsPlaceholder();
        return;
    }

    await fetchLogs();
    startLogsPolling();
}

// Fetch logs from all selected containers
async function fetchLogs() {
    if (selectedContainers.length === 0 || logsPaused) return;

    // Prevent concurrent fetches
    if (isFetchingLogs) {
        console.log('[LOGS] Fetch already in progress, skipping...');
        return;
    }

    isFetchingLogs = true;
    console.log('[LOGS] Starting fetch for', selectedContainers.length, 'containers');

    const tailCount = document.getElementById('logsTailCount').value;
    const tail = tailCount === 'all' ? 10000 : parseInt(tailCount);
    let rateLimitHit = false;

    try {
        // Fetch logs from all containers with staggered delays to avoid rate limiting
        const promises = selectedContainers.map(async (container, index) => {
            // Add 100ms delay between each request to spread them out
            if (index > 0) {
                await new Promise(resolve => setTimeout(resolve, index * 100));
            }

            try {
                const response = await fetch(
                    `${API_BASE}/api/hosts/${container.hostId}/containers/${container.containerId}/logs?tail=${tail}`
                );

                if (response.status === 429) {
                    rateLimitHit = true;
                    return [];
                }

                if (!response.ok) return [];

                const data = await response.json();
                // Add container info to each log line
                return (data.logs || []).map(log => ({
                    ...log,
                    containerName: container.name,
                    containerKey: `${container.hostId}:${container.containerId}`
                }));
            } catch (error) {
                console.error(`Error fetching logs for ${container.name}:`, error);
                return [];
            }
        });

        const logsArrays = await Promise.all(promises);

        // If rate limit was hit, pause auto-refresh and notify user
        if (rateLimitHit) {
            stopLogsPolling();
            const autoRefreshCheckbox = document.getElementById('logsAutoRefresh');
            if (autoRefreshCheckbox) {
                autoRefreshCheckbox.checked = false;
            }
            showToast('⚠️ Rate limit reached. Auto-refresh paused. Try selecting fewer containers or wait a moment.', 'error');
        }

        // Merge all logs
        const newLogs = logsArrays.flat();

        // Sort by timestamp (based on sort order)
        newLogs.sort((a, b) => {
            const aTime = new Date(a.timestamp);
            const bTime = new Date(b.timestamp);
            return logsSortOrder === 'asc' ? aTime - bTime : bTime - aTime;
        });

        allLogs = newLogs;
        renderLogs();
    } catch (error) {
        console.error('[LOGS] Error fetching logs:', error);
    } finally {
        isFetchingLogs = false;
        console.log('[LOGS] Fetch completed');
    }
}

// Render logs to the container
function renderLogs() {
    const container = document.getElementById('logsContainer');
    if (!container) return;

    if (allLogs.length === 0) {
        container.innerHTML = '<div class="logs-placeholder"><p>No logs available</p></div>';
        return;
    }

    const showTimestamps = document.getElementById('logsTimestamps').checked;
    const searchTerm = document.getElementById('logsSearchInput').value.toLowerCase();

    // Filter logs by search term
    const filteredLogs = searchTerm
        ? allLogs.filter(log => log.log.toLowerCase().includes(searchTerm))
        : allLogs;

    // Build HTML
    let html = '';
    filteredLogs.forEach(log => {
        const colorIndex = containerColorMap[log.containerKey] || 0;
        const timestamp = new Date(log.timestamp).toLocaleString('en-US', {
            month: '2-digit',
            day: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: true
        });

        html += `<div class="log-line" data-container="${colorIndex}">`;
        if (showTimestamps) {
            html += `<span class="log-timestamp">${timestamp}</span>`;
        }
        if (selectedContainers.length > 1) {
            html += `<span class="log-container-name">${escapeHtml(log.containerName)}</span>`;
        }
        html += `<span class="log-text">${escapeHtml(log.log)}</span>`;
        html += `</div>`;
    });

    const shouldScroll = isScrolledToBottom(container);
    container.innerHTML = html;

    if (shouldScroll && !logsPaused) {
        scrollToBottom(container);
    }
}

// Helper functions
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function isScrolledToBottom(element) {
    return element.scrollHeight - element.scrollTop <= element.clientHeight + 100;
}

function scrollToBottom(element) {
    element.scrollTop = element.scrollHeight;
}

function showLogsPlaceholder() {
    const container = document.getElementById('logsContainer');
    if (container) {
        container.innerHTML = `
            <div class="logs-placeholder">
                <span data-lucide="file-text" style="width: 48px; height: 48px; opacity: 0.3;"></span>
                <p>Select one or more containers to view logs</p>
            </div>
        `;
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
    }
}

// Polling management
function startLogsPolling() {
    stopLogsPolling();
    const autoRefresh = document.getElementById('logsAutoRefresh')?.checked;
    if (selectedContainers.length > 0 && autoRefresh && !logsPaused) {
        console.log('[LOGS] Starting polling interval (2s)');
        logsPollingInterval = setInterval(fetchLogs, 2000); // Poll every 2 seconds (same as container modal)
    }
}

function stopLogsPolling() {
    if (logsPollingInterval) {
        console.log('[LOGS] Stopping polling interval');
        clearInterval(logsPollingInterval);
        logsPollingInterval = null;
    }
}

// Control functions
function toggleLogsAutoRefresh() {
    const autoRefresh = document.getElementById('logsAutoRefresh').checked;
    if (autoRefresh) {
        startLogsPolling();
    } else {
        stopLogsPolling();
    }
}

function toggleLogsSort() {
    logsSortOrder = logsSortOrder === 'asc' ? 'desc' : 'asc';
    saveLogsSortOrder();
    updateLogsSortButton();

    // Re-sort and re-render existing logs
    allLogs.sort((a, b) => {
        const aTime = new Date(a.timestamp);
        const bTime = new Date(b.timestamp);
        return logsSortOrder === 'asc' ? aTime - bTime : bTime - aTime;
    });
    renderLogs();
}

function updateLogsSortButton() {
    const btn = document.getElementById('logsSortBtn');
    if (!btn) return;

    if (logsSortOrder === 'desc') {
        btn.innerHTML = '<span data-lucide="arrow-down-wide-narrow"></span> Newest First';
    } else {
        btn.innerHTML = '<span data-lucide="arrow-up-narrow-wide"></span> Oldest First';
    }

    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

function clearLogs() {
    allLogs = [];
    renderLogs();
}

function downloadLogs() {
    if (allLogs.length === 0) return;

    const showTimestamps = document.getElementById('logsTimestamps').checked;
    let content = '';

    allLogs.forEach(log => {
        let line = '';
        if (showTimestamps) {
            const timestamp = new Date(log.timestamp).toISOString();
            line += `[${timestamp}] `;
        }
        if (selectedContainers.length > 1) {
            line += `[${log.containerName}] `;
        }
        line += log.log + '\n';
        content += line;
    });

    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `container-logs-${new Date().toISOString()}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function filterLogs() {
    renderLogs();
}

function toggleTimestamps() {
    renderLogs();
}

// Hook into page switching
document.addEventListener('DOMContentLoaded', function() {
    const originalSwitchPage = window.switchPage;
    if (originalSwitchPage) {
        window.switchPage = function(page) {
            originalSwitchPage(page);
            if (page === 'logs') {
                initLogsPage();
            } else {
                stopLogsPolling();
            }
        };
    }
});
