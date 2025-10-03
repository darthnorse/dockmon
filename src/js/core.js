        console.log('DockMon JavaScript loaded');
        // Global state
        let currentPage = 'dashboard';
        let globalSettings = {
            maxRetries: 3,
            retryDelay: 30,
            defaultAutoRestart: false,
            pollingInterval: 10,
            connectionTimeout: 10,
            blackout_windows: []
        };

        let hosts = [];
        let containers = [];
        let alertRules = [];

        // Make hosts and containers globally accessible for other modules (like logs.js)
        window.hosts = hosts;
        window.containers = containers;
        let ws = null;
        let reconnectInterval = null;

        // Auto-restart notification batching
        let restartNotificationBatch = [];
        let restartNotificationTimer = null;
        let editingAlertRule = null; // Track which rule is being edited
        let reconnectAttempts = 0;
        let isConnecting = false; // Prevent multiple simultaneous connections
        const MAX_RECONNECT_ATTEMPTS = 10;

        // API Base URL - backend always runs on port 8080
        const API_BASE = '';  // Use same origin - nginx will proxy /api/* to backend
        const WS_URL = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;

        // XSS protection: Escape HTML special characters
        function escapeHtml(unsafe) {
            if (unsafe === null || unsafe === undefined) return '';
            return String(unsafe)
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        }

        // Make escapeHtml globally available
        window.escapeHtml = escapeHtml;

        // Lucide icon helper function
        function icon(name, size = 16, className = '') {
            return `<i data-lucide="${name}" class="lucide-icon ${className}" style="width:${size}px;height:${size}px;"></i>`;
        }

        // Initialize Lucide icons after DOM updates
        function initIcons() {
            if (typeof lucide !== 'undefined') {
                lucide.createIcons();
            }
        }

        // Get authentication headers for API requests
        function getAuthHeaders() {
            const headers = {
                'Content-Type': 'application/json'
            };
            // Using session cookies for authentication
            return headers;
        }


        // Initialize WebSocket connection
        function connectWebSocket() {
            // Prevent multiple simultaneous connection attempts
            if (isConnecting) {
                console.log('Connection attempt already in progress, skipping...');
                return;
            }

            // Close existing connection if any
            if (ws && ws.readyState !== WebSocket.CLOSED) {
                ws.close();
            }

            console.log('Connecting to WebSocket:', WS_URL);
            isConnecting = true;

            ws = new WebSocket(WS_URL);

            ws.onopen = function() {
                console.log('WebSocket connected');
                showToast('✅ Connected to backend');
                reconnectAttempts = 0;
                isConnecting = false;
                if (reconnectInterval) {
                    clearInterval(reconnectInterval);
                    reconnectInterval = null;
                }
            };

            ws.onmessage = function(event) {
                try {
                    const message = JSON.parse(event.data);
                    handleWebSocketMessage(message);
                } catch (error) {
                    console.error('Error handling WebSocket message:', error);
                }
            };
            
            ws.onerror = function(error) {
                console.error('WebSocket error:', error);
                showToast('⚠️ Connection error');
                isConnecting = false; // Reset flag on error
            };

            ws.onclose = function() {
                console.log('WebSocket disconnected');
                showToast('🔌 Disconnected - attempting to reconnect...');
                isConnecting = false; // Reset flag on close
                attemptReconnect();
            };
        }

        // Handle batched restart notifications
        function handleRestartNotificationBatch() {
            if (restartNotificationBatch.length === 0) return;

            if (restartNotificationBatch.length === 1) {
                showToast(`✅ Successfully restarted ${restartNotificationBatch[0]}`);
            } else {
                const containerNames = restartNotificationBatch.slice(0, 3).join(', ');
                const remaining = restartNotificationBatch.length - 3;
                const message = remaining > 0
                    ? `✅ Successfully restarted ${containerNames} and ${remaining} more`
                    : `✅ Successfully restarted ${containerNames}`;
                showToast(message);
            }

            // Clear the batch
            restartNotificationBatch = [];
            restartNotificationTimer = null;
        }

        // Handle incoming WebSocket messages
        function handleWebSocketMessage(message) {
            switch(message.type) {
                case 'initial_state':
                    hosts = message.data.hosts || [];
                    window.hosts = hosts; // Keep window.hosts in sync
                    containers = message.data.containers || [];
                    window.containers = containers; // Keep window.containers in sync
                    globalSettings = message.data.settings || globalSettings;
                    alertRules = message.data.alerts || [];

                    renderAll();

                    // Initialize dashboard if we're on that page and grid doesn't exist yet
                    if (currentPage === 'dashboard' && grid === null) {
                        // Small delay to ensure renderAll() completes
                        setTimeout(() => {
                            if (grid === null) {  // Double check grid wasn't already initialized
                                initDashboard();
                            }
                        }, 100);
                    }
                    break;

                case 'containers_update':
                    containers = message.data.containers || [];
                    window.containers = containers; // Keep window.containers in sync
                    hosts = message.data.hosts || [];
                    window.hosts = hosts; // Keep window.hosts in sync
                    renderAll();

                    // Update host metrics charts
                    if (message.data.host_metrics && typeof updateHostMetrics === 'function') {
                        for (const [hostId, metrics] of Object.entries(message.data.host_metrics)) {
                            updateHostMetrics(hostId, metrics);
                        }
                    }

                    // Refresh container modal if open
                    refreshContainerModalIfOpen();

                    // Refresh logs dropdown if on logs page
                    if (currentPage === 'logs' && typeof populateContainerList === 'function') {
                        populateContainerList();
                    }
                    break;
                    
                case 'host_added':
                    fetchHosts();
                    showToast('✅ Host added successfully');
                    break;
                    
                case 'auto_restart_success':
                    // Add to batch instead of showing immediate toast
                    restartNotificationBatch.push(message.data.container_name);

                    // Clear any existing timer and set a new one
                    if (restartNotificationTimer) {
                        clearTimeout(restartNotificationTimer);
                    }

                    // Show batched notification after 2 seconds of no new restarts
                    restartNotificationTimer = setTimeout(handleRestartNotificationBatch, 2000);
                    break;
                    
                case 'auto_restart_failed':
                    showToast(`❌ Failed to restart ${message.data.container_name} after ${message.data.attempts} attempts`);
                    break;
                    
                case 'container_restarted':
                    showToast(`🔄 Container restarted`);
                    break;

                case 'docker_event':
                    // Handle Docker events (container start/stop/restart, etc.)
                    // These are real-time events from Docker daemon - no action needed
                    break;

                case 'blackout_status_changed':
                    // Update blackout status display if modal is open
                    updateBlackoutStatus();
                    break;

                default:
                    console.log('Unknown message type:', message.type);
            }

            // Call any registered custom message handlers
            if (window.wsMessageHandlers && Array.isArray(window.wsMessageHandlers)) {
                window.wsMessageHandlers.forEach(handler => {
                    try {
                        handler(message);
                    } catch (error) {
                        console.error('Error in custom WebSocket handler:', error);
                    }
                });
            }
        }

        // Core handler stays internal - extensions should use window.wsMessageHandlers array

        // Attempt to reconnect to WebSocket
        function attemptReconnect() {
            if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
                showToast('❌ Could not reconnect to backend');
                return;
            }

            // Clear any existing reconnect interval
            if (reconnectInterval) {
                clearInterval(reconnectInterval);
                reconnectInterval = null;
            }

            // Use exponential backoff: 2s, 4s, 8s, 16s, then 30s
            const delay = Math.min(2000 * Math.pow(2, reconnectAttempts), 30000);

            console.log(`Will attempt reconnect in ${delay}ms (attempt ${reconnectAttempts + 1}/${MAX_RECONNECT_ATTEMPTS})`);

            setTimeout(() => {
                reconnectAttempts++;
                console.log(`Reconnect attempt ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS}`);
                connectWebSocket();
            }, delay);
        }

        // API Functions
        async function fetchHosts() {
            try {
                const response = await fetch(`${API_BASE}/api/hosts`, {
                    headers: getAuthHeaders(),
                    credentials: 'include'
                });
                if (response.ok) {
                    hosts = await response.json();
                    window.hosts = hosts; // Keep window.hosts in sync
                    console.log('Fetched hosts:', hosts.length);
                } else {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
            } catch (error) {
                console.error('Error fetching hosts:', error);
                // Don't show toast during initial load, WebSocket will handle it
                if (hosts.length === 0) {
                    console.log('Will wait for WebSocket data...');
                } else {
                    showToast('❌ Failed to fetch hosts');
                }
            }
        }

        async function fetchContainers() {
            try {
                const response = await fetch(`${API_BASE}/api/containers`, {
                    headers: getAuthHeaders(),
                    credentials: 'include'
                });
                if (response.ok) {
                    containers = await response.json();
                    window.containers = containers; // Keep window.containers in sync
                    console.log('Fetched containers:', containers.length);
                } else {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
            } catch (error) {
                console.error('Error fetching containers:', error);
                // Don't show toast during initial load, WebSocket will handle it
                if (containers.length === 0) {
                    console.log('Will wait for WebSocket data...');
                } else {
                    showToast('❌ Failed to fetch containers');
                }
            }
        }

        async function fetchSettings() {
            try {
                const response = await fetch(`${API_BASE}/api/settings`, {
                    credentials: 'include'
                });
                globalSettings = await response.json();

                // Always update timezone offset from browser
                globalSettings.timezone_offset = -new Date().getTimezoneOffset();
            } catch (error) {
                console.error('Error fetching settings:', error);
            }
        }

        async function fetchAlertRules() {
            try {
                const response = await fetch(`${API_BASE}/api/alerts`, {
                    credentials: 'include'
                });
                if (response.ok) {
                    alertRules = await response.json() || [];
                    renderAlertRules();
                    updateNavBadges();
                } else {
                    console.warn('Failed to fetch alert rules:', response.status);
                    alertRules = [];
                }
            } catch (error) {
                console.error('Error fetching alert rules:', error);
                alertRules = [];
            }
        }

        // Check authentication status
        async function checkAuthentication() {
            console.log('Checking authentication status...');
            try {
                const response = await fetch(`${API_BASE}/api/auth/status`, {
                    credentials: 'include'
                });

                console.log('Auth response status:', response.status);

                if (response.ok) {
                    const data = await response.json();
                    console.log('Auth data:', data);

                    if (!data.authenticated) {
                        console.log('Not authenticated, redirecting to login');
                        // Redirect to login page
                        window.location.href = '/login.html';
                        return false;
                    }

                    // Store user info
                    if (data.username) {
                        currentUserInfo.username = data.username;
                    }

                    // Check if password change is required (from backend)
                    if (data.must_change_password || data.is_first_login) {
                        sessionStorage.setItem('must_change_password', 'true');
                    }

                    console.log('Authentication successful');
                    return true;
                } else {
                    console.log('Auth check returned non-OK status:', response.status);
                }
            } catch (error) {
                console.error('Auth check error:', error);
            }

            console.log('Auth check failed, redirecting to login');
            // If auth check fails, redirect to login
            window.location.href = '/login.html';
            return false;
        }

        // Logout function
        async function logout() {
            try {
                const response = await fetch(`${API_BASE}/api/auth/logout`, {
                    method: 'POST',
                    credentials: 'include'
                });

                if (response.ok) {
                    window.location.href = '/login.html';
                } else {
                    console.error('Logout failed');
                }
            } catch (error) {
                console.error('Logout error:', error);
                // Force redirect even if logout request fails
                window.location.href = '/login.html';
            }
        }

        // Save modal preferences to localStorage
        function saveModalPreferences() {
            const modal = document.querySelector('#containerModal .modal-content');
            if (modal) {
                const preferences = {
                    width: modal.style.width,
                    height: modal.style.height,
                    transform: modal.style.transform,
                    logsHeight: document.getElementById('container-logs')?.style.height
                };
                localStorage.setItem('containerModalPrefs', JSON.stringify(preferences));
            }
        }

        // Load modal preferences from localStorage
        function loadModalPreferences() {
            const saved = localStorage.getItem('containerModalPrefs');
            if (saved) {
                try {
                    const prefs = JSON.parse(saved);
                    const modal = document.querySelector('#containerModal .modal-content');
                    if (modal) {
                        if (prefs.width) modal.style.width = prefs.width;
                        if (prefs.height) modal.style.height = prefs.height;
                        // Reset transform on load (center the modal)
                        modal.style.transform = 'translate(0, 0)';
                    }
                    // Restore logs height will be done when logs tab is shown
                    return prefs;
                } catch (e) {
                    console.error('Failed to load modal preferences:', e);
                }
            }
            return null;
        }

        // Make modal draggable
        function makeModalDraggable(modalId) {
            const modal = document.getElementById(modalId);
            const modalContent = modal.querySelector('.modal-content');
            const header = modalContent.querySelector('.modal-header');

            let isDragging = false;
            let currentX;
            let currentY;
            let initialX;
            let initialY;
            let xOffset = 0;
            let yOffset = 0;

            header.addEventListener('mousedown', dragStart);
            document.addEventListener('mousemove', drag);
            document.addEventListener('mouseup', dragEnd);

            function dragStart(e) {
                if (e.target.classList.contains('modal-close')) return;

                initialX = e.clientX - xOffset;
                initialY = e.clientY - yOffset;

                if (e.target === header || header.contains(e.target)) {
                    isDragging = true;
                }
            }

            function drag(e) {
                if (isDragging) {
                    e.preventDefault();
                    currentX = e.clientX - initialX;
                    currentY = e.clientY - initialY;

                    xOffset = currentX;
                    yOffset = currentY;

                    modalContent.style.transform = `translate(${currentX}px, ${currentY}px)`;
                }
            }

            function dragEnd(e) {
                initialX = currentX;
                initialY = currentY;
                isDragging = false;
                // Save position after dragging
                saveModalPreferences();
            }
        }

        // ========================================
        // Chart.js Helper Functions
        // ========================================

        /**
         * Create a sparkline chart (small, minimal chart for trends)
         * @param {HTMLCanvasElement} canvas - Canvas element to render chart
         * @param {string} color - Line color
         * @param {number} maxDataPoints - Maximum number of data points to show
         * @returns {Chart} Chart.js instance
         */
        function createSparkline(canvas, color, maxDataPoints = 60) {
            const ctx = canvas.getContext('2d');

            return new Chart(ctx, {
                type: 'line',
                data: {
                    labels: new Array(maxDataPoints).fill(''),
                    datasets: [{
                        data: new Array(maxDataPoints).fill(0),
                        borderColor: color,
                        backgroundColor: 'transparent',
                        borderWidth: 1.5,
                        pointRadius: 0,
                        pointHoverRadius: 0,
                        tension: 0.4,
                        fill: false
                    }]
                },
                options: {
                    responsive: false,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: { enabled: false }
                    },
                    scales: {
                        x: { display: false },
                        y: {
                            display: false,
                            min: 0,
                            max: 100
                        }
                    },
                    animation: {
                        duration: 0
                    },
                    interaction: {
                        mode: 'index',
                        intersect: false
                    }
                }
            });
        }

        /**
         * Update sparkline chart with new data point
         * @param {Chart} chart - Chart.js instance
         * @param {number} newValue - New data value
         */
        function updateSparkline(chart, newValue) {
            const data = chart.data.datasets[0].data;
            data.shift();
            data.push(newValue);
            chart.update('none'); // Update without animation
        }

        /**
         * Format bytes to human-readable format
         * @param {number} bytes - Number of bytes
         * @returns {string} Formatted string (e.g., "1.2 MB/s")
         */
        function formatBytes(bytes) {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
        }

        // Initialize
        