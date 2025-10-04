// Host Metrics Management
// Handles visualization of host metrics received via WebSocket

// Configuration constants
const HOST_CHART_DATA_POINTS = 60;  // ~5 minutes of data at 5s intervals
const CONTAINER_CHART_DATA_POINTS = 20;  // ~1.5 minutes of data at 5s intervals
const CHART_LOAD_TIMEOUT = 5000;  // Timeout for Chart.js to load (ms)
const CHART_POLL_INTERVAL = 50;  // Polling interval for Chart.js availability (ms)
const METRICS_CLEANUP_INTERVAL = 60000;  // Cleanup stale metrics every 60 seconds

// Store chart instances for each host
const hostMetricsCharts = new Map(); // host_id -> { cpu: Chart, ram: Chart, net: Chart }

// Store previous network values for rate calculation
const networkHistory = new Map(); // host_id -> { lastRx: 0, lastTx: 0, lastTimestamp: 0 }

// Track pending updates for hosts whose charts aren't ready yet
const pendingHostUpdates = new Map(); // host_id -> metrics

/**
 * Create sparkline charts for a host widget
 * Called after the host widget DOM is rendered
 */
function createHostMetricsCharts(hostId) {
    // Wait for Chart.js to be loaded
    const waitForChart = setInterval(() => {
        if (typeof Chart === 'undefined') {
            return; // Chart.js not loaded yet
        }

        clearInterval(waitForChart);

        const cpuCanvas = document.getElementById(`cpu-chart-${hostId}`);
        const ramCanvas = document.getElementById(`ram-chart-${hostId}`);
        const netCanvas = document.getElementById(`net-chart-${hostId}`);

        if (!cpuCanvas || !ramCanvas || !netCanvas) {
            logger.warn(`Charts not found for host ${hostId}`);
            return;
        }

        // Destroy existing charts if they exist
        const existing = hostMetricsCharts.get(hostId);
        if (existing) {
            existing.cpu?.destroy();
            existing.ram?.destroy();
            existing.net?.destroy();
        }

        // Create charts with different colors
        const cpuChart = createSparkline(cpuCanvas, '#3b82f6', HOST_CHART_DATA_POINTS); // blue
        const ramChart = createSparkline(ramCanvas, '#10b981', HOST_CHART_DATA_POINTS); // green
        const netChart = createSparkline(netCanvas, '#8b5cf6', HOST_CHART_DATA_POINTS); // purple

        hostMetricsCharts.set(hostId, {
            cpu: cpuChart,
            ram: ramChart,
            net: netChart
        });

        // Initialize network history
        networkHistory.set(hostId, {
            lastRx: 0,
            lastTx: 0,
            lastTimestamp: 0
        });

        logger.debug(`Created metrics charts for host ${hostId}`);

        // Process any pending updates
        const pending = pendingHostUpdates.get(hostId);
        if (pending) {
            updateHostMetrics(hostId, pending);
            pendingHostUpdates.delete(hostId);
        }
    }, CHART_POLL_INTERVAL);

    // Timeout after configured duration
    setTimeout(() => clearInterval(waitForChart), CHART_LOAD_TIMEOUT);
}

/**
 * Update host metrics charts from WebSocket data
 * @param {string} hostId - Host ID
 * @param {object} metrics - Metrics data from WebSocket
 */
function updateHostMetrics(hostId, metrics) {
    const charts = hostMetricsCharts.get(hostId);
    if (!charts) {
        // Charts not created yet - store this update to apply when ready
        pendingHostUpdates.set(hostId, metrics);
        return;
    }

    // Update CPU chart
    if (charts.cpu && metrics.cpu_percent !== undefined) {
        updateSparkline(charts.cpu, metrics.cpu_percent);
    }

    // Update RAM chart
    if (charts.ram && metrics.memory_percent !== undefined) {
        updateSparkline(charts.ram, metrics.memory_percent);
    }

    // Calculate network rate (bytes/sec)
    const history = networkHistory.get(hostId);
    if (history && metrics.network_rx_bytes !== undefined && metrics.network_tx_bytes !== undefined) {
        const now = Date.now();
        if (history.lastTimestamp > 0) {
            const timeDelta = (now - history.lastTimestamp) / 1000; // seconds
            if (timeDelta > 0) {
                const rxDelta = metrics.network_rx_bytes - history.lastRx;
                const txDelta = metrics.network_tx_bytes - history.lastTx;
                const totalRate = (rxDelta + txDelta) / timeDelta; // bytes/sec

                // Convert to percentage (scale to 100, assuming 1 Gbps = 125 MB/s as max)
                const netPercent = Math.min((totalRate / (125 * 1024 * 1024)) * 100, 100);

                if (charts.net) {
                    updateSparkline(charts.net, netPercent);
                }

                // Update network value display
                const netValue = document.getElementById(`net-value-${hostId}`);
                if (netValue) {
                    netValue.textContent = formatBytes(totalRate) + '/s';
                }
            }
        }

        // Update history
        history.lastRx = metrics.network_rx_bytes;
        history.lastTx = metrics.network_tx_bytes;
        history.lastTimestamp = now;
    }

    // Update text values
    const cpuValue = document.getElementById(`cpu-value-${hostId}`);
    const ramValue = document.getElementById(`ram-value-${hostId}`);

    if (cpuValue && metrics.cpu_percent !== undefined) {
        cpuValue.textContent = `${metrics.cpu_percent}%`;
    }
    if (ramValue && metrics.memory_percent !== undefined) {
        ramValue.textContent = `${metrics.memory_percent}%`;
    }
}

/**
 * Cleanup metrics for a removed host
 */
function removeHostMetrics(hostId) {
    const charts = hostMetricsCharts.get(hostId);
    if (charts) {
        // Destroy charts
        if (charts.cpu) charts.cpu.destroy();
        if (charts.ram) charts.ram.destroy();
        if (charts.net) charts.net.destroy();

        hostMetricsCharts.delete(hostId);
    }

    networkHistory.delete(hostId);
    pendingHostUpdates.delete(hostId);
}

// Container Sparklines Management
const containerSparklineCharts = new Map(); // "hostId-containerId" -> { cpu: Chart, ram: Chart, net: Chart }
const containerNetworkHistory = new Map(); // Track previous network values for rate calculation
const containerChartsReady = new Map(); // Track Promise resolvers for when charts are ready
const pendingUpdates = new Map(); // Queue updates that arrive before charts are ready

/**
 * Remove container metrics and cleanup resources
 */
function removeContainerMetrics(hostId, containerId) {
    const key = `${hostId}-${containerId}`;
    const charts = containerSparklineCharts.get(key);

    if (charts) {
        // Destroy charts
        if (charts.cpu) charts.cpu.destroy();
        if (charts.ram) charts.ram.destroy();
        if (charts.net) charts.net.destroy();

        containerSparklineCharts.delete(key);
    }

    // Remove network history
    containerNetworkHistory.delete(key);

    // Remove ready promise
    containerChartsReady.delete(key);

    // Remove pending updates
    pendingUpdates.delete(key);
}

// Export for use in other modules
window.removeContainerMetrics = removeContainerMetrics;

/**
 * Create sparkline charts for a container
 * Returns a Promise that resolves when charts are created
 */
function createContainerSparklines(hostId, containerId) {
    const key = `${hostId}-${containerId}`;

    // Create a Promise that will resolve when charts are ready
    const readyPromise = new Promise((resolve) => {
        // Wait for Chart.js to be loaded
        const waitForChart = setInterval(() => {
            if (typeof Chart === 'undefined') {
                return; // Chart.js not loaded yet
            }

            clearInterval(waitForChart);

            const cpuCanvas = document.getElementById(`container-cpu-${key}`);
            const ramCanvas = document.getElementById(`container-ram-${key}`);
            const netCanvas = document.getElementById(`container-net-${key}`);

            if (!cpuCanvas || !ramCanvas || !netCanvas) {
                resolve(false); // Elements not found
                return;
            }

            // Destroy existing charts if they exist
            const existing = containerSparklineCharts.get(key);
            if (existing) {
                existing.cpu?.destroy();
                existing.ram?.destroy();
                existing.net?.destroy();
            }

            // Create mini sparklines
            const cpuChart = createSparkline(cpuCanvas, '#3b82f6', CONTAINER_CHART_DATA_POINTS); // blue
            const ramChart = createSparkline(ramCanvas, '#10b981', CONTAINER_CHART_DATA_POINTS); // green
            const netChart = createSparkline(netCanvas, '#a855f7', CONTAINER_CHART_DATA_POINTS); // purple

            containerSparklineCharts.set(key, {
                cpu: cpuChart,
                ram: ramChart,
                net: netChart
            });

            resolve(true); // Charts created successfully

            // Process any pending updates
            const pending = pendingUpdates.get(key);
            if (pending) {
                updateContainerSparklines(hostId, containerId, pending);
                pendingUpdates.delete(key);
            }
        }, CHART_POLL_INTERVAL);

        // Timeout after configured duration
        setTimeout(() => {
            clearInterval(waitForChart);
            resolve(false);
        }, CHART_LOAD_TIMEOUT);
    });

    containerChartsReady.set(key, readyPromise);
    return readyPromise;
}

/**
 * Update container sparklines from container data
 * If charts aren't ready yet, queue the update
 */
function updateContainerSparklines(hostId, containerId, containerData) {
    const key = `${hostId}-${containerId}`;
    const charts = containerSparklineCharts.get(key);

    if (!charts) {
        // Charts not created yet - store this update to apply when ready
        pendingUpdates.set(key, containerData);
        return;
    }

    // Update CPU sparkline
    if (charts.cpu && containerData.cpu_percent !== undefined && containerData.cpu_percent !== null) {
        updateSparkline(charts.cpu, containerData.cpu_percent);

        // Update CPU text value
        const cpuValueEl = document.querySelector(`#container-cpu-${key}`).closest('.container-stats').querySelector('.container-stats-values > div:nth-child(1)');
        if (cpuValueEl) {
            cpuValueEl.textContent = `CPU ${containerData.cpu_percent.toFixed(1)}%`;
        }
    }

    // Update RAM sparkline (convert bytes to percentage for visualization)
    if (charts.ram && containerData.memory_usage !== undefined && containerData.memory_usage !== null && containerData.memory_limit !== undefined && containerData.memory_limit > 0) {
        const ramPercent = (containerData.memory_usage / containerData.memory_limit) * 100;
        updateSparkline(charts.ram, ramPercent);

        // Update RAM text value
        const ramValueEl = document.querySelector(`#container-ram-${key}`).closest('.container-stats').querySelector('.container-stats-values > div:nth-child(2)');
        if (ramValueEl) {
            ramValueEl.textContent = `RAM ${formatBytes(containerData.memory_usage)}`;
        }
    }

    // Update Network sparkline (calculate rate from cumulative values)
    if (charts.net && containerData.network_tx !== undefined && containerData.network_rx !== undefined) {
        const now = Date.now();
        const history = containerNetworkHistory.get(key);

        if (history) {
            const timeDelta = (now - history.timestamp) / 1000; // seconds
            if (timeDelta >= 1) {
                const txRate = (containerData.network_tx - history.tx) / timeDelta;
                const rxRate = (containerData.network_rx - history.rx) / timeDelta;
                const totalRate = Math.max(0, txRate + rxRate);

                updateSparkline(charts.net, totalRate / 1024); // Convert to KB for better visualization

                // Update text value
                const valueEl = document.getElementById(`container-net-value-${key}`);
                if (valueEl) {
                    valueEl.textContent = `NET ${formatBytes(totalRate)}/s`;
                }

                // Update history
                containerNetworkHistory.set(key, {
                    tx: containerData.network_tx,
                    rx: containerData.network_rx,
                    timestamp: now
                });
            }
        } else {
            // Initialize history
            containerNetworkHistory.set(key, {
                tx: containerData.network_tx,
                rx: containerData.network_rx,
                timestamp: now
            });
        }
    }
}

/**
 * Cleanup stale container metrics
 * Call this periodically to remove metrics for containers that no longer exist
 */
function cleanupStaleContainerMetrics() {
    const currentContainers = new Set();

    // Collect all currently visible containers
    document.querySelectorAll('.container-item').forEach(item => {
        const cpuCanvas = item.querySelector('[id^="container-cpu-"]');
        if (cpuCanvas) {
            const key = cpuCanvas.id.replace('container-cpu-', '');
            currentContainers.add(key);
        }
    });

    // Remove metrics for containers that no longer exist
    for (const key of containerSparklineCharts.keys()) {
        if (!currentContainers.has(key)) {
            const [hostId, containerId] = key.split('-');
            removeContainerMetrics(hostId, containerId);
        }
    }

    // Also cleanup network history for containers that no longer exist
    for (const key of containerNetworkHistory.keys()) {
        if (!currentContainers.has(key)) {
            containerNetworkHistory.delete(key);
        }
    }
}

// Run cleanup periodically
const metricsCleanupInterval = setInterval(cleanupStaleContainerMetrics, METRICS_CLEANUP_INTERVAL);

// Stop cleanup when page is unloaded
window.addEventListener('beforeunload', () => {
    clearInterval(metricsCleanupInterval);
});
