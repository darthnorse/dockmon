// GridStack Dashboard
let grid = null;
let dashboardLocked = false;

async function initDashboard() {
    logger.debug('initDashboard called');

    // Initialize search and sort filters
    initializeContainerFilters();

    // Show search/sort controls on dashboard
    const searchContainer = document.getElementById('dashboardSearchContainer');
    const sortSelect = document.getElementById('containerSort');
    if (searchContainer) searchContainer.style.display = '';
    if (sortSelect) sortSelect.style.display = '';

    // Check if dashboard grid container exists
    const dashboardGridElement = document.getElementById('dashboard-grid');
    if (!dashboardGridElement) {
        logger.error('Dashboard grid element not found!');
        return;
    }

    // Destroy existing GridStack instance if it exists
    if (grid) {
        grid.destroy(false); // false = don't remove DOM elements
        grid = null;
        logger.debug('Destroyed existing GridStack instance');
    }

    // Initialize GridStack with better flexibility
    try {
        grid = GridStack.init({
            column: 48,      // 48 columns for maximum flexibility
            cellHeight: 20,  // Smaller cells for finer vertical control
            margin: 4,       // Keep margins at 4px
            animate: true,
            float: true,     // Allow floating for desktop editing
            draggable: {
                handle: '.widget-header'
            },
            resizable: {
                handles: 'e, se, s, sw, w'
            }
        }, '#dashboard-grid');

        logger.debug('GridStack initialized successfully');

        // Load saved layout from API or use default
        try {
            const response = await fetch('/api/user/dashboard-layout', {
                method: 'GET',
                credentials: 'include'
            });

            if (response.ok) {
                const data = await response.json();
                if (data.layout) {
                    try {
                        const parsedLayout = JSON.parse(data.layout);
                        logger.debug('Loading saved dashboard layout from API - widgets:', parsedLayout.map(w => w.id));
                        loadDashboardLayout(parsedLayout);
                    } catch (parseError) {
                        logger.error('Failed to parse dashboard layout JSON:', parseError);
                        showToast('⚠️ Dashboard layout corrupted - using default', 'error');
                        createDefaultDashboard();
                    }
                } else {
                    logger.debug('No saved layout in API - creating default dashboard layout');
                    createDefaultDashboard();
                }
            } else {
                logger.error('Failed to load dashboard layout from API:', response.status);
                showToast('⚠️ Failed to load dashboard layout - using default', 'error');
                createDefaultDashboard();
            }
        } catch (error) {
            logger.error('Error loading dashboard layout:', error);
            showToast('⚠️ Failed to load dashboard layout - using default', 'error');
            createDefaultDashboard();
        }

        // Auto-save layout on any change
        grid.on('change', (event, items) => {
            saveDashboardLayout();
        });

        logger.debug('Dashboard initialization completed');

        // Now that grid exists, populate the widgets with data
        logger.debug('Rendering dashboard widgets after grid initialization...');
        renderDashboardWidgets();
    } catch (error) {
        logger.error('Failed to initialize dashboard:', error);
    }
}

function createDefaultDashboard() {
    // Stats Widget - taller to ensure content fits
    const statsWidget = createWidget('stats', 'Statistics', '<span data-lucide="bar-chart-3"></span>', {
        x: 0, y: 0, w: 48, h: 9,
        minW: 48, minH: 9, maxH: 9, maxW: 48,
        noResize: true,
        noMove: true
    });

    // Create individual widgets for each host
    createHostWidgets();

    // Use setTimeout to ensure widgets are fully created before rendering
    setTimeout(() => renderDashboardWidgets(), 50);
}

function createHostWidgets() {
    // Layout is loaded from API on startup, no need to check localStorage
    const layoutMap = {};

    // Get current host widget IDs
    const currentHostWidgetIds = hosts.map(host => `host-${host.id}`);

    // Remove host widgets that no longer exist OR duplicates
    const existingHostWidgets = grid.getGridItems().filter(item => {
        const widgetId = item.getAttribute('data-widget-id');
        return widgetId && widgetId.startsWith('host-');
    });
    logger.debug(`Checking for widgets to remove. Current: ${existingHostWidgets.length}, Expected: ${currentHostWidgetIds.length}`);

    // Track which widget IDs we've seen to detect duplicates
    const seenWidgetIds = new Set();

    existingHostWidgets.forEach(widget => {
        const widgetId = widget.getAttribute('data-widget-id');

        // Remove if widget ID is not in current host list
        if (!currentHostWidgetIds.includes(widgetId)) {
            logger.debug(`Removing widget ${widgetId} - not in current host list`);
            // Extract host ID from widget ID (format: "host-{hostId}")
            const hostId = widgetId.replace('host-', '');
            // Clean up metrics before removing widget
            if (typeof removeHostMetrics === 'function') {
                removeHostMetrics(hostId);
            }
            grid.removeWidget(widget);
        }
        // Remove if this is a duplicate (we've seen this ID before)
        else if (seenWidgetIds.has(widgetId)) {
            logger.debug(`Removing duplicate widget ${widgetId}`);
            // Extract host ID from widget ID (format: "host-{hostId}")
            const hostId = widgetId.replace('host-', '');
            // Clean up metrics before removing widget
            if (typeof removeHostMetrics === 'function') {
                removeHostMetrics(hostId);
            }
            grid.removeWidget(widget);
        } else {
            seenWidgetIds.add(widgetId);
        }
    });

    // Create a widget for each host with dynamic sizing and smart positioning
    let currentY = 10; // Start below stats widget (stats h=9, +1 for spacing)
    let leftColumnY = 10;
    let rightColumnY = 10;

    // FIRST: Scan ALL existing widgets to find the actual bottom of each column
    // This ensures new widgets are placed at the bottom regardless of host creation order
    const allExistingWidgets = grid.getGridItems();
    allExistingWidgets.forEach(widget => {
        const widgetId = widget.getAttribute('data-widget-id');
        // Only process host widgets, not stats widget
        if (!widgetId || !widgetId.startsWith('host-')) {
            return;
        }

        // Use GridStack node data instead of attributes
        const gridData = widget.gridstackNode;
        if (!gridData) {
            return;
        }

        const existingX = gridData.x;
        const existingY = gridData.y;
        const existingH = gridData.h;

        if (existingX === 0) {
            // Left column
            leftColumnY = Math.max(leftColumnY, existingY + existingH);
        } else {
            // Right column
            rightColumnY = Math.max(rightColumnY, existingY + existingH);
        }
    });

    hosts.forEach((host, index) => {
        const widgetId = `host-${host.id}`;

        // Check if widget already exists
        const existingWidget = document.querySelector(`[data-widget-id="${widgetId}"]`);
        if (existingWidget) {
            return; // Skip silently - widget already exists
        }
        logger.debug(`Creating new widget ${widgetId}`);

        const hostContainers = containers.filter(c => c.host_id === host.id);

        // Calculate height based on container count (adjusted for cellHeight=20)
        const containerRows = Math.max(1, hostContainers.length);
        const headerHeight = 4; // Widget header (doubled for smaller cells)
        const containerHeight = 3.6; // Each container row height (doubled)
        const dynamicHeight = headerHeight + containerRows * containerHeight + 1.2; // Add padding
        const widgetHeight = Math.max(12, Math.ceil(dynamicHeight)); // Minimum height of 12

        // Check if there's a saved position for this widget
        let x, y, w, h;
        if (layoutMap[widgetId]) {
            // Use saved position and size
            x = layoutMap[widgetId].x;
            y = layoutMap[widgetId].y;
            w = layoutMap[widgetId].w;
            h = layoutMap[widgetId].h;
            logger.debug(`Restoring widget ${widgetId} from saved layout: x=${x}, y=${y}, w=${w}, h=${h}`);
        } else {
            // Smart column placement - use the shorter column
            if (leftColumnY <= rightColumnY) {
                // Place in left column
                x = 0;
                y = leftColumnY;
                leftColumnY = y + widgetHeight; // Update tracker
            } else {
                // Place in right column
                x = 24;
                y = rightColumnY;
                rightColumnY = y + widgetHeight; // Update tracker
            }
            w = 24;
            h = widgetHeight;
        }

        const widget = createWidget(widgetId, host.name, '<span data-lucide="server"></span>', {
            x: x,
            y: y,
            w: w,
            h: h,
            minW: 3, minH: 3
        });
    });
}

function createWidget(id, title, icon, gridOptions) {
    // Create DOM element instead of HTML string (GridStack v12+ requirement)
    const widgetEl = document.createElement('div');
    widgetEl.className = 'grid-stack-item';
    widgetEl.setAttribute('data-widget-id', id);

    widgetEl.innerHTML = `
        <div class="grid-stack-item-content">
            <div class="widget-header">
                <div class="widget-title">
                    <span>${icon}</span>
                    <span>${title}</span>
                </div>
            </div>
            <div class="widget-body" id="widget-${id}">
                <!-- Content will be rendered here -->
            </div>
        </div>
    `;

    // GridStack v12+ API - use makeWidget with options
    grid.makeWidget(widgetEl, {
        x: gridOptions.x,
        y: gridOptions.y,
        w: gridOptions.w,
        h: gridOptions.h,
        minW: gridOptions.minW || 2,
        minH: gridOptions.minH || 2,
        maxH: gridOptions.maxH || undefined
    });

    initIcons();
    return document.querySelector(`[data-widget-id="${id}"]`);
}

function renderDashboardWidgets() {
    logger.debug('renderDashboardWidgets called - hosts:', hosts.length, 'grid:', !!grid);

    // Check if we need to create/remove host widgets (hosts added or removed)
    if (grid) {
        const existingHostWidgets = grid.getGridItems().filter(item =>
            item.getAttribute('data-widget-id')?.startsWith('host-')
        );

        // Call createHostWidgets if host count changed OR if we have hosts but no widgets
        if (existingHostWidgets.length !== hosts.length || (hosts.length > 0 && existingHostWidgets.length === 0)) {
            createHostWidgets();
        }
    }

    // Render stats widget - only update values, not rebuild HTML
    const statsWidget = document.getElementById('widget-stats');
    if (statsWidget) {
        // Check if stats grid exists, create if not
        let statsGrid = statsWidget.querySelector('.stats-grid');
        if (!statsGrid) {
            statsWidget.innerHTML = `
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-label">Total Hosts</div>
                        <div class="stat-value" data-stat="hosts">0</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Total Containers</div>
                        <div class="stat-value" data-stat="containers">0</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Running</div>
                        <div class="stat-value" data-stat="running">0</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Alert Rules</div>
                        <div class="stat-value" data-stat="alerts">0</div>
                    </div>
                </div>
            `;
            statsGrid = statsWidget.querySelector('.stats-grid');
        }

        // Update only the values
        const hostsValue = statsWidget.querySelector('[data-stat="hosts"]');
        const containersValue = statsWidget.querySelector('[data-stat="containers"]');
        const runningValue = statsWidget.querySelector('[data-stat="running"]');
        const alertsValue = statsWidget.querySelector('[data-stat="alerts"]');

        if (hostsValue) hostsValue.textContent = hosts.length;
        if (containersValue) containersValue.textContent = containers.length;
        if (runningValue) runningValue.textContent = containers.filter(c => c.state === 'running').length;
        if (alertsValue) alertsValue.textContent = alertRules.length;
    }

    // Render individual host widgets
    hosts.forEach(host => {
        const hostWidget = document.getElementById(`widget-host-${host.id}`);
        if (hostWidget) {
            // Get containers for this host
            let hostContainers = containers.filter(c => c.host_id === host.id);

            // Apply global search filter
            hostContainers = filterContainers(hostContainers);

            // Apply global sort
            hostContainers = sortContainers(hostContainers);
            const maxContainersToShow = hostContainers.length; // Show all containers now that widgets are dynamically sized

            // Check if container order or state has changed to avoid unnecessary re-renders
            const containerStateKey = hostContainers.map(c => `${c.short_id}:${c.auto_restart}:${c.state}`).join(',');
            const previousStateKey = hostWidget.dataset.containerState;

            const showContainerStats = globalSettings.show_container_stats !== false; // Default to true
            const containersList = hostContainers.slice(0, maxContainersToShow).map(container => `
                <div class="container-item" data-status="${container.state}">
                    <div class="container-info" onclick="showContainerDetails('${container.host_id}', '${container.short_id}')">
                        <div class="container-icon container-${container.state}">
                            ${getContainerIcon(container.state)}
                        </div>
                        <div class="container-details">
                            <div class="container-name"><span class="container-status-dot status-${container.state}"></span> ${escapeHtml(container.name)}</div>
                            <div class="container-id">${escapeHtml(container.short_id)}</div>
                        </div>
                    </div>
                    <div class="container-stats">
                        ${showContainerStats && container.state === 'running' ? `
                        <div class="container-stats-charts">
                            <canvas id="container-cpu-${container.host_id}-${container.short_id}" width="35" height="12"></canvas>
                            <canvas id="container-ram-${container.host_id}-${container.short_id}" width="35" height="12"></canvas>
                            <canvas id="container-net-${container.host_id}-${container.short_id}" width="35" height="12"></canvas>
                        </div>
                        <div class="container-stats-values">
                            <div>CPU ${container.cpu_percent ? container.cpu_percent.toFixed(1) : '0'}%</div>
                            <div>RAM ${container.memory_usage ? formatBytes(container.memory_usage) : '0 B'}</div>
                            <div id="container-net-value-${container.host_id}-${container.short_id}">NET 0 B/s</div>
                        </div>
                        ` : ''}
                    </div>
                    <div class="container-actions">
                        <div class="auto-restart-toggle ${container.auto_restart ? 'enabled' : ''}">
                            <i data-lucide="rotate-cw" style="width:14px;height:14px;"></i>
                            <div class="toggle-switch ${container.auto_restart ? 'active' : ''}"
                                 onclick="toggleAutoRestart('${container.host_id}', '${container.short_id}', event)"></div>
                        </div>
                        <span class="container-state ${getStateClass(container.state)}">
                            ${container.state}
                        </span>
                    </div>
                </div>
            `).join('');

            const moreCount = hostContainers.length > maxContainersToShow ? hostContainers.length - maxContainersToShow : 0;

            // Update widget title with status badge and metrics
            const widgetHeader = hostWidget.closest('.grid-stack-item').querySelector('.widget-header');
            if (widgetHeader) {
                const showMetrics = globalSettings.show_host_stats !== false; // Default to true
                const metricsExist = widgetHeader.querySelector('.host-metrics');

                // If metrics visibility changed, rebuild the entire header
                if ((showMetrics && !metricsExist) || (!showMetrics && metricsExist)) {
                    // If hiding metrics, clean up Chart.js instances first
                    if (!showMetrics && metricsExist) {
                        if (typeof removeHostMetrics === 'function') {
                            removeHostMetrics(host.id);
                        }
                    }

                    widgetHeader.innerHTML = `
                        <div class="widget-title">
                            <span><i data-lucide="server" style="width:16px;height:16px;"></i></span>
                            <span><span class="host-status-dot status-${host.status}" title="${host.status}"></span> ${host.name}</span>
                        </div>
                        ${showMetrics ? `
                        <div class="host-metrics">
                            <div class="metric-sparkline">
                                <canvas id="cpu-chart-${host.id}" width="60" height="20"></canvas>
                                <div class="metric-label">CPU: <span id="cpu-value-${host.id}">0%</span></div>
                            </div>
                            <div class="metric-sparkline">
                                <canvas id="ram-chart-${host.id}" width="60" height="20"></canvas>
                                <div class="metric-label">RAM: <span id="ram-value-${host.id}">0%</span></div>
                            </div>
                            <div class="metric-sparkline">
                                <canvas id="net-chart-${host.id}" width="60" height="20"></canvas>
                                <div class="metric-label">NET: <span id="net-value-${host.id}">0 B/s</span></div>
                            </div>
                        </div>
                        ` : ''}
                    `;

                    // Create charts after DOM is updated (only if showing metrics)
                    if (showMetrics) {
                        createHostMetricsCharts(host.id);
                    }
                } else if (metricsExist) {
                    // Metrics already exist and should stay - just update the title/status
                    const titleElement = widgetHeader.querySelector('.widget-title');
                    if (titleElement) {
                        titleElement.innerHTML = `
                            <span><i data-lucide="server" style="width:16px;height:16px;"></i></span>
                            <span><span class="host-status-dot status-${host.status}" title="${host.status}"></span> ${host.name}</span>
                        `;
                    }
                }
            }

            // Check if container stats visibility changed (independently of container state)
            const previousShowStats = hostWidget.dataset.showContainerStats !== 'false';
            const statsVisibilityChanged = previousShowStats !== showContainerStats;

            // Only update if the container state has changed, stats visibility changed, or it's the first render
            if (containerStateKey !== previousStateKey || statsVisibilityChanged) {
                hostWidget.dataset.containerState = containerStateKey;

                // Check if we're hiding container stats - cleanup charts for all containers on this host
                if (previousShowStats && !showContainerStats) {
                    // Clean up all container charts for this host
                    hostContainers.forEach(container => {
                        if (typeof removeContainerMetrics === 'function') {
                            removeContainerMetrics(container.host_id, container.short_id);
                        }
                    });
                }
                hostWidget.dataset.showContainerStats = showContainerStats;

                hostWidget.innerHTML = `
                    <div class="container-list">
                        ${containersList || '<div style="padding: 12px; color: var(--text-tertiary); text-align: center;">No containers</div>'}
                        ${moreCount > 0 ? `<div style="padding: 8px 12px; font-size: 12px; color: var(--text-tertiary); text-align: center; border-top: 1px solid var(--border);">+${moreCount} more containers</div>` : ''}
                    </div>
                `;

                // Create sparklines for running containers
                if (showContainerStats) {
                    hostContainers.slice(0, maxContainersToShow).forEach(container => {
                        if (container.state === 'running') {
                            createContainerSparklines(container.host_id, container.short_id);
                            // Update sparklines with current data
                            updateContainerSparklines(container.host_id, container.short_id, container);
                        }
                    });
                }
            } else {
                // Just update the sparkline data without re-rendering
                if (showContainerStats) {
                    hostContainers.slice(0, maxContainersToShow).forEach(container => {
                        if (container.state === 'running') {
                            updateContainerSparklines(container.host_id, container.short_id, container);
                        }
                    });
                }
            }
        }
    });
}

function saveDashboardLayoutManual() {
    saveDashboardLayout();
    showToast('✅ Dashboard layout saved');
}

function removeWidget(id) {
    const widget = document.querySelector(`[data-widget-id="${id}"]`);
    if (widget) {
        grid.removeWidget(widget);
    }
}

async function saveDashboardLayout() {
    const layout = grid.save(false);
    const gridItems = grid.getGridItems();

    // Create a map of grid items by their grid position to ensure correct mapping
    const layoutWithIds = [];

    for (const gridItem of gridItems) {
        const widgetId = gridItem.getAttribute('data-widget-id');
        const gridData = gridItem.gridstackNode;

        if (widgetId && gridData) {
            layoutWithIds.push({
                id: widgetId,
                x: gridData.x,
                y: gridData.y,
                w: gridData.w,
                h: gridData.h
            });
        }
    }

    // Ensure stats widget is always in the saved layout
    const hasStatsWidget = layoutWithIds.some(item => item.id === 'stats');
    if (!hasStatsWidget) {
        logger.debug('Adding missing stats widget to saved layout');
        layoutWithIds.unshift({
            id: 'stats',
            x: 0,
            y: 0,
            w: 48,
            h: 9
        });
    }

    logger.debug('Saving layout:', layoutWithIds.map(w => `${w.id} (${w.x},${w.y}) h=${w.h}`));

    // Save to API
    try {
        const response = await fetch('/api/user/dashboard-layout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ layout: JSON.stringify(layoutWithIds) })
        });

        if (!response.ok) {
            logger.error('Failed to save dashboard layout to API:', response.status);
            showToast('⚠️ Failed to save dashboard layout', 'error');
        }
    } catch (error) {
        logger.error('Error saving dashboard layout:', error);
        showToast('⚠️ Failed to save dashboard layout', 'error');
    }
}

function loadDashboardLayout(layout) {
    // Remove duplicate stats widgets from saved layout (keep only the first one)
    const seenIds = new Set();
    const dedupedLayout = layout.filter(item => {
        if (item.id === 'stats' && seenIds.has('stats')) {
            logger.debug('Removing duplicate stats widget from saved layout');
            return false;
        }
        seenIds.add(item.id);
        return true;
    });

    // Ensure stats widget is always present first
    const hasStatsWidget = dedupedLayout.some(item => item.id === 'stats');
    if (!hasStatsWidget) {
        logger.debug('Stats widget missing from layout - adding it back');
        createWidget('stats', 'Statistics', '<span data-lucide="bar-chart-3"></span>', {
            x: 0, y: 0, w: 48, h: 9,
            minW: 48, minH: 9, maxH: 9, maxW: 48,
            noResize: true,
            noMove: true
        });
    }

    // Sort layout for proper reading order (left-to-right, top-to-bottom)
    // This ensures mobile displays hosts in the same priority order as desktop
    const sortedLayout = [...dedupedLayout].sort((a, b) => {
        // Stats widget always first
        if (a.id === 'stats') return -1;
        if (b.id === 'stats') return 1;

        // Sort by Y position first (row), then X position (column)
        if (Math.abs(a.y - b.y) < 5) {  // Same row (within 5 units)
            return a.x - b.x;  // Left to right
        }
        return a.y - b.y;  // Top to bottom
    });

    sortedLayout.forEach(item => {
        const widgetConfig = getWidgetConfig(item.id);
        if (widgetConfig) {
            // Special handling for stats widget to ensure proper positioning
            if (item.id === 'stats') {
                createWidget(widgetConfig.id, widgetConfig.title, widgetConfig.icon, {
                    x: 0, y: 0, w: 48, h: 9,
                    minW: 48, minH: 9, maxH: 9, maxW: 48,
                    noResize: true,
                    noMove: true
                });
            } else {
                createWidget(widgetConfig.id, widgetConfig.title, widgetConfig.icon, {
                    x: item.x,
                    y: item.y,
                    w: item.w,
                    h: item.h,
                    minW: widgetConfig.minW,
                    minH: widgetConfig.minH,
                    maxH: widgetConfig.maxH
                });
            }
        } else {
            logger.debug(`Skipping widget ${item.id} - config not available yet (hosts data may not be loaded)`);
        }
    });
}

function getWidgetConfig(id) {
    const configs = {
        'stats': { id: 'stats', title: 'Statistics', icon: '<span data-lucide="bar-chart-3"></span>', minW: 48, minH: 9, maxH: 9, maxW: 48, noResize: true, noMove: true }
    };

    // Dynamic configs for host widgets
    if (id.startsWith('host-')) {
        const hostId = id.replace('host-', '');
        const host = hosts.find(h => h.id === hostId);
        if (host) {
            return { id: id, title: host.name, icon: '<i data-lucide="monitor" style="width:16px;height:16px;"></i>', minW: 3, minH: 3 };
        }
    }

    return configs[id];
}

async function resetDashboardLayout() {
    // Reload the saved layout from API, or use default if none exists
    try {
        const response = await fetch('/api/user/dashboard-layout', {
            method: 'GET',
            credentials: 'include'
        });

        if (response.ok) {
            const data = await response.json();
            if (data.layout) {
                // Revert to last saved layout
                grid.removeAll();
                loadDashboardLayout(JSON.parse(data.layout));
                showToast('🔄 Dashboard layout reset to last saved state');
            } else {
                // No saved layout, use default
                grid.removeAll();
                createDefaultDashboard();
                showToast('🔄 Dashboard layout reset to default');
            }
        } else {
            logger.error('Failed to load dashboard layout from API:', response.status);
            showToast('⚠️ Failed to load dashboard layout', 'error');
        }
    } catch (error) {
        logger.error('Error loading dashboard layout:', error);
        showToast('⚠️ Failed to load dashboard layout', 'error');
    }
}

// ============================================================================
// Container Search and Sorting
// ============================================================================

// Global filter state
let containerSearchTerm = '';
let containerSortOption = 'name-asc';

// Initialize search/sort from localStorage (search) and database (sort)
async function initializeContainerFilters() {
    // Search: from localStorage (session-specific)
    const savedSearch = localStorage.getItem('dockmon_container_search') || '';
    containerSearchTerm = savedSearch;

    const searchInput = document.getElementById('containerSearch');
    if (searchInput) searchInput.value = savedSearch;

    // Sort: from database (cross-browser preference)
    try {
        const response = await fetch(`${API_BASE}/api/user/container-sort-order`, {
            credentials: 'include'
        });
        if (response.ok) {
            const data = await response.json();
            containerSortOption = data.sort_order || 'name-asc';
        } else {
            containerSortOption = 'name-asc'; // Fallback
        }
    } catch (error) {
        logger.error('Error loading container sort preference:', error);
        containerSortOption = 'name-asc'; // Fallback
    }

    const sortSelect = document.getElementById('containerSort');
    if (sortSelect) sortSelect.value = containerSortOption;
}

// Apply search and sort filters to containers
async function applyContainerFilters() {
    const searchInput = document.getElementById('containerSearch');
    const sortSelect = document.getElementById('containerSort');

    // Update search term (localStorage)
    if (searchInput) {
        containerSearchTerm = searchInput.value;
        localStorage.setItem('dockmon_container_search', containerSearchTerm);
    }

    // Update sort option (database)
    if (sortSelect && sortSelect.value !== containerSortOption) {
        const newSortOption = sortSelect.value;

        try {
            const response = await fetch(`${API_BASE}/api/user/container-sort-order`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ sort_order: newSortOption })
            });

            if (response.ok) {
                containerSortOption = newSortOption;
            } else {
                logger.error('Failed to save container sort preference');
                // Revert dropdown to previous value
                sortSelect.value = containerSortOption;
                showToast('⚠️ Failed to save sort preference', 'error');
                return;
            }
        } catch (error) {
            logger.error('Error saving container sort preference:', error);
            // Revert dropdown to previous value
            sortSelect.value = containerSortOption;
            showToast('⚠️ Failed to save sort preference', 'error');
            return;
        }
    }

    // Re-render dashboard with filters applied
    renderDashboardWidgets();
}

// Filter containers by search term (supports regex)
function filterContainers(containersList) {
    if (!containerSearchTerm || containerSearchTerm.trim() === '') {
        return containersList;
    }

    const searchTerm = containerSearchTerm.trim();

    // Try to use as regex first, fall back to plain string search
    try {
        const regex = new RegExp(searchTerm, 'i');
        return containersList.filter(c =>
            regex.test(c.name) || regex.test(c.image)
        );
    } catch (e) {
        // Invalid regex, use plain string search
        const lowerSearch = searchTerm.toLowerCase();
        return containersList.filter(c =>
            c.name.toLowerCase().includes(lowerSearch) ||
            c.image.toLowerCase().includes(lowerSearch)
        );
    }
}

// Sort containers based on selected option
function sortContainers(containersList) {
    const sorted = [...containersList]; // Create copy to avoid mutating original

    switch (containerSortOption) {
        case 'name-asc':
            return sorted.sort((a, b) => a.name.localeCompare(b.name));

        case 'name-desc':
            return sorted.sort((a, b) => b.name.localeCompare(a.name));

        case 'status':
            // Running > paused > created > restarting > exited > dead
            const statusPriority = {
                'running': 1,
                'paused': 2,
                'created': 3,
                'restarting': 4,
                'exited': 5,
                'dead': 6
            };
            return sorted.sort((a, b) => {
                const priorityA = statusPriority[a.state] || 99;
                const priorityB = statusPriority[b.state] || 99;
                if (priorityA !== priorityB) {
                    return priorityA - priorityB;
                }
                // Same status, sort by name
                return a.name.localeCompare(b.name);
            });

        case 'memory-desc':
            return sorted.sort((a, b) => (b.memory_usage || 0) - (a.memory_usage || 0));

        case 'memory-asc':
            return sorted.sort((a, b) => (a.memory_usage || 0) - (b.memory_usage || 0));

        case 'cpu-desc':
            return sorted.sort((a, b) => (b.cpu_percent || 0) - (a.cpu_percent || 0));

        case 'cpu-asc':
            return sorted.sort((a, b) => (a.cpu_percent || 0) - (b.cpu_percent || 0));

        default:
            return sorted;
    }
}
