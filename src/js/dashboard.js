// GridStack Dashboard
let grid = null;
let dashboardLocked = false;

async function initDashboard() {
    console.log('initDashboard called');

    // Check if dashboard grid container exists
    const dashboardGridElement = document.getElementById('dashboard-grid');
    if (!dashboardGridElement) {
        console.error('Dashboard grid element not found!');
        return;
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

        console.log('GridStack initialized successfully');

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
                        console.log('Loading saved dashboard layout from API - widgets:', parsedLayout.map(w => w.id));
                        loadDashboardLayout(parsedLayout);
                    } catch (parseError) {
                        console.error('Failed to parse dashboard layout JSON:', parseError);
                        showToast('⚠️ Dashboard layout corrupted - using default', 'error');
                        createDefaultDashboard();
                    }
                } else {
                    console.log('No saved layout in API - creating default dashboard layout');
                    createDefaultDashboard();
                }
            } else {
                console.error('Failed to load dashboard layout from API:', response.status);
                showToast('⚠️ Failed to load dashboard layout - using default', 'error');
                createDefaultDashboard();
            }
        } catch (error) {
            console.error('Error loading dashboard layout:', error);
            showToast('⚠️ Failed to load dashboard layout - using default', 'error');
            createDefaultDashboard();
        }

        // Auto-save layout on any change
        grid.on('change', (event, items) => {
            saveDashboardLayout();
        });

        console.log('Dashboard initialization completed');

        // Now that grid exists, populate the widgets with data
        console.log('Rendering dashboard widgets after grid initialization...');
        renderDashboardWidgets();
    } catch (error) {
        console.error('Failed to initialize dashboard:', error);
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
    console.log(`Checking for widgets to remove. Current: ${existingHostWidgets.length}, Expected: ${currentHostWidgetIds.length}`);

    // Track which widget IDs we've seen to detect duplicates
    const seenWidgetIds = new Set();

    existingHostWidgets.forEach(widget => {
        const widgetId = widget.getAttribute('data-widget-id');

        // Remove if widget ID is not in current host list
        if (!currentHostWidgetIds.includes(widgetId)) {
            console.log(`Removing widget ${widgetId} - not in current host list`);
            grid.removeWidget(widget);
        }
        // Remove if this is a duplicate (we've seen this ID before)
        else if (seenWidgetIds.has(widgetId)) {
            console.log(`Removing duplicate widget ${widgetId}`);
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
        console.log(`Creating new widget ${widgetId}`);

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
            console.log(`Restoring widget ${widgetId} from saved layout: x=${x}, y=${y}, w=${w}, h=${h}`);
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
    console.log('renderDashboardWidgets called - hosts:', hosts.length, 'grid:', !!grid);

    // Check if we need to create/remove host widgets (hosts added or removed)
    if (grid) {
        const existingHostWidgets = grid.getGridItems().filter(item =>
            item.getAttribute('data-widget-id')?.startsWith('host-')
        );

        console.log('Existing host widgets:', existingHostWidgets.length, 'Expected:', hosts.length);

        // Call createHostWidgets if host count changed OR if we have hosts but no widgets
        if (existingHostWidgets.length !== hosts.length || (hosts.length > 0 && existingHostWidgets.length === 0)) {
            console.log('Creating host widgets...');
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
            const hostContainers = containers.filter(c => c.host_id === host.id).sort((a, b) => a.name.localeCompare(b.name));
            const maxContainersToShow = hostContainers.length; // Show all containers now that widgets are dynamically sized
            const containersList = hostContainers.slice(0, maxContainersToShow).map(container => `
                <div class="container-item" data-status="${container.state}">
                    <div class="container-info" onclick="showContainerDetails('${container.host_id}', '${container.short_id}')">
                        <div class="container-icon container-${container.state}">
                            ${getContainerIcon(container.state)}
                        </div>
                        <div class="container-details">
                            <div class="container-name">${container.name}</div>
                            <div class="container-id">${container.short_id}</div>
                        </div>
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

            // Update widget title with status badge
            const widgetTitle = hostWidget.closest('.grid-stack-item').querySelector('.widget-title');
            if (widgetTitle) {
                widgetTitle.innerHTML = `
                    <span><i data-lucide="server" style="width:16px;height:16px;"></i></span>
                    <span>${host.name}</span>
                    <span class="host-status status-${host.status}" style="margin-left: 8px;">${host.status}</span>
                `;
            }

            hostWidget.innerHTML = `
                <div class="container-list">
                    ${containersList || '<div style="padding: 12px; color: var(--text-tertiary); text-align: center;">No containers</div>'}
                    ${moreCount > 0 ? `<div style="padding: 8px 12px; font-size: 12px; color: var(--text-tertiary); text-align: center; border-top: 1px solid var(--border);">+${moreCount} more containers</div>` : ''}
                </div>
            `;
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
        console.log('Adding missing stats widget to saved layout');
        layoutWithIds.unshift({
            id: 'stats',
            x: 0,
            y: 0,
            w: 48,
            h: 9
        });
    }

    console.log('Saving layout:', layoutWithIds.map(w => `${w.id} (${w.x},${w.y}) h=${w.h}`));

    // Save to API
    try {
        const response = await fetch('/api/user/dashboard-layout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ layout: JSON.stringify(layoutWithIds) })
        });

        if (!response.ok) {
            console.error('Failed to save dashboard layout to API:', response.status);
            showToast('⚠️ Failed to save dashboard layout', 'error');
        }
    } catch (error) {
        console.error('Error saving dashboard layout:', error);
        showToast('⚠️ Failed to save dashboard layout', 'error');
    }
}

function loadDashboardLayout(layout) {
    // Ensure stats widget is always present first
    const hasStatsWidget = layout.some(item => item.id === 'stats');
    if (!hasStatsWidget) {
        console.log('Stats widget missing from layout - adding it back');
        createWidget('stats', 'Statistics', '<span data-lucide="bar-chart-3"></span>', {
            x: 0, y: 0, w: 48, h: 9,
            minW: 48, minH: 9, maxH: 9, maxW: 48,
            noResize: true,
            noMove: true
        });
    }

    // Sort layout for proper reading order (left-to-right, top-to-bottom)
    // This ensures mobile displays hosts in the same priority order as desktop
    const sortedLayout = [...layout].sort((a, b) => {
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
            console.log(`Skipping widget ${item.id} - config not available yet (hosts data may not be loaded)`);
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
            console.error('Failed to load dashboard layout from API:', response.status);
            showToast('⚠️ Failed to load dashboard layout', 'error');
        }
    } catch (error) {
        console.error('Error loading dashboard layout:', error);
        showToast('⚠️ Failed to load dashboard layout', 'error');
    }
}
