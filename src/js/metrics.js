// Host Metrics Management
// Handles visualization of host metrics received via WebSocket

// Store chart instances for each host
const hostMetricsCharts = new Map(); // host_id -> { cpu: Chart, ram: Chart, net: Chart }

// Store previous network values for rate calculation
const networkHistory = new Map(); // host_id -> { lastRx: 0, lastTx: 0, lastTimestamp: 0 }

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
            console.warn(`Charts not found for host ${hostId}`);
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
        const cpuChart = createSparkline(cpuCanvas, '#3b82f6', 60); // blue
        const ramChart = createSparkline(ramCanvas, '#10b981', 60); // green
        const netChart = createSparkline(netCanvas, '#8b5cf6', 60); // purple

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

        console.log(`Created metrics charts for host ${hostId}`);
    }, 50);

    // Timeout after 5 seconds
    setTimeout(() => clearInterval(waitForChart), 5000);
}

/**
 * Update host metrics charts from WebSocket data
 * @param {string} hostId - Host ID
 * @param {object} metrics - Metrics data from WebSocket
 */
function updateHostMetrics(hostId, metrics) {
    const charts = hostMetricsCharts.get(hostId);
    if (!charts) {
        // Charts not created yet, skip
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
}
