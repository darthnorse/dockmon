function createAlertForContainer(containerId) {
    // Find the container
    const container = containers.find(c => c.id === containerId);
    if (container) {
        // Check if there's an existing alert rule for this container on this specific host
        const existingRule = alertRules.find(rule => {
            // Check new container+host pairs format first
            if (rule.containers && rule.containers.length > 0) {
                return rule.containers.some(c =>
                    c.container_name === container.name && c.host_id === container.host_id
                );
            }
            return false;
        });

        // Close current modal
        closeModal('containerModal');

        if (existingRule) {
            // Edit existing rule
            openAlertRuleModal(container, existingRule);
        } else {
            // Create new rule with container pre-selected
            openAlertRuleModal(container);
        }
    }
}

async function editAlertRule(ruleId) {
    try {
        // Find the rule in the current alertRules array
        const rule = alertRules.find(r => r.id === ruleId);
        if (!rule) {
            showToast('❌ Alert rule not found');
            return;
        }

        editingAlertRule = rule;
        openAlertRuleModal(null, rule);
    } catch (error) {
        logger.error('Error opening alert rule for editing:', error);
        showToast('❌ Failed to open alert rule for editing');
    }
}

function openGlobalSettings() {
    document.getElementById('maxRetries').value = globalSettings.max_retries;
    document.getElementById('retryDelay').value = globalSettings.retry_delay;
    document.getElementById('pollingInterval').value = globalSettings.polling_interval;
    document.getElementById('connectionTimeout').value = globalSettings.connection_timeout;

    const defaultToggle = document.getElementById('defaultAutoRestart');
    if (globalSettings.default_auto_restart) {
        defaultToggle.classList.add('active');
    } else {
        defaultToggle.classList.remove('active');
    }

    // Dashboard display settings
    const showHostStatsToggle = document.getElementById('showHostStats');
    if (globalSettings.show_host_stats !== false) { // Default to true
        showHostStatsToggle.classList.add('active');
    } else {
        showHostStatsToggle.classList.remove('active');
    }

    const showContainerStatsToggle = document.getElementById('showContainerStats');
    if (globalSettings.show_container_stats !== false) { // Default to true
        showContainerStatsToggle.classList.add('active');
    } else {
        showContainerStatsToggle.classList.remove('active');
    }

    document.getElementById('globalSettingsModal').classList.add('active');
}

function getSecurityStatusBadge(host) {
    if (!host.url || host.url.includes('unix://')) {
        return ''; // Local connections don't need security status
    }

    if (host.security_status === 'secure') {
        return '<span class="security-status secure">Secure</span>';
    } else if (host.security_status === 'insecure') {
        return '<span class="security-status insecure">Insecure</span>';
    }
    return ''; // Unknown status - don't show anything
}

function closeModal(modalId) {
    if (modalId === 'containerModal') {
        // Save preferences before closing
        saveModalPreferences();

        // Clean up resize observer
        if (window.modalResizeObserver) {
            window.modalResizeObserver.disconnect();
            window.modalResizeObserver = null;
        }

        // Use the cleanup function
        if (window.cleanupLogStream) {
            window.cleanupLogStream();
        }
        const streamBtn = document.getElementById('streamLogsBtn');
        if (streamBtn) {
            streamBtn.textContent = 'Start Live Stream';
        }

        // Remove keydown event listener if exists
        if (window.logFilterKeyHandler) {
            document.removeEventListener('keydown', window.logFilterKeyHandler);
        }

        // Remove drag event listeners
        if (window.cleanupModalDragListeners) {
            window.cleanupModalDragListeners();
        }

        // Clean up modal charts
        if (typeof cleanupModalCharts === 'function') {
            cleanupModalCharts();
        }

        // Notify backend to stop stats collection for this container
        if (window.currentContainer && ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                type: 'modal_closed',
                container_id: window.currentContainer.id,
                host_id: window.currentContainer.host_id
            }));
        }

        // Clear current container
        window.currentContainer = null;
    }

    document.getElementById(modalId).classList.remove('active');
}

// Account Settings Functions
let currentUserInfo = { username: 'admin' };

async function getCurrentUser() {
    try {
        const response = await fetch(`${API_BASE}/api/auth/status`, {
            credentials: 'include'
        });
        if (response.ok) {
            const data = await response.json();
            currentUserInfo = data;
            // Update UI with username
            const topbarUsername = document.getElementById('topbarUsername');
            const currentUsernameInput = document.getElementById('currentUsername');

            if (topbarUsername) topbarUsername.textContent = data.username;
            if (currentUsernameInput) currentUsernameInput.value = data.username;
        }
    } catch (error) {
        logger.error('Error fetching user info:', error);
    }
}

function openAccountSettings() {
    getCurrentUser();
    document.getElementById('accountModal').classList.add('active');

    // Clear form
    document.getElementById('newUsername').value = '';
    document.getElementById('newPassword').value = '';
    document.getElementById('confirmPassword').value = '';
    document.getElementById('accountError').style.display = 'none';
    document.getElementById('accountSuccess').style.display = 'none';

    // Check if we have a temporary password from first login
    const tempPassword = sessionStorage.getItem('temp_current_password');
    if (tempPassword) {
        document.getElementById('currentPassword').value = tempPassword;
        // Clear it immediately after use for security
        sessionStorage.removeItem('temp_current_password');
    } else {
        document.getElementById('currentPassword').value = '';
    }
}

async function saveAccountSettings(event) {
    event.preventDefault();

    const currentPassword = document.getElementById('currentPassword').value;
    const newUsername = document.getElementById('newUsername').value.trim();
    const newPassword = document.getElementById('newPassword').value;
    const confirmPassword = document.getElementById('confirmPassword').value;
    const errorDiv = document.getElementById('accountError');
    const successDiv = document.getElementById('accountSuccess');

    errorDiv.style.display = 'none';
    successDiv.style.display = 'none';

    // Validate passwords match
    if (newPassword && newPassword !== confirmPassword) {
        errorDiv.textContent = 'New passwords do not match';
        errorDiv.style.display = 'block';
        return;
    }

    // Validate password length
    if (newPassword && newPassword.length < 8) {
        errorDiv.textContent = 'Password must be at least 8 characters long';
        errorDiv.style.display = 'block';
        return;
    }

    try {
        // Change username if provided
        if (newUsername && newUsername !== currentUserInfo.username) {
            const usernameResponse = await fetch(`${API_BASE}/api/auth/change-username`, {
                method: 'POST',
                headers: getAuthHeaders(),
                credentials: 'include',
                body: JSON.stringify({
                    current_password: currentPassword,
                    new_username: newUsername
                })
            });

            if (!usernameResponse.ok) {
                const error = await usernameResponse.json();
                throw new Error(error.detail || 'Failed to change username');
            }
        }

        // Change password if provided
        if (newPassword) {
            const passwordResponse = await fetch(`${API_BASE}/api/auth/change-password`, {
                method: 'POST',
                headers: getAuthHeaders(),
                credentials: 'include',
                body: JSON.stringify({
                    current_password: currentPassword,
                    new_password: newPassword
                })
            });

            if (!passwordResponse.ok) {
                const error = await passwordResponse.json();
                throw new Error(error.detail || 'Failed to change password');
            }
        }

        successDiv.textContent = 'Account updated successfully';
        successDiv.style.display = 'block';

        // Clear password change requirement
        sessionStorage.removeItem('must_change_password');

        // Update username displays
        await getCurrentUser();

        // Clear form
        setTimeout(() => {
            closeModal('accountModal');
        }, 1500);

    } catch (error) {
        errorDiv.textContent = error.message;
        errorDiv.style.display = 'block';
    }
}

// logout() function removed - using the one from core.js instead

function checkPasswordChangeRequired() {
    const mustChange = sessionStorage.getItem('must_change_password');
    if (mustChange === 'true') {
        // Show password change modal
        setTimeout(() => {
            showToast('⚠️ Please change your default password for security');
            openAccountSettings();

            // Add a notice at the top of the form for first login
            const errorDiv = document.getElementById('accountError');
            const successDiv = document.getElementById('accountSuccess');
            errorDiv.style.display = 'block';
            errorDiv.style.background = 'rgba(255, 193, 7, 0.1)';
            errorDiv.style.borderColor = 'rgba(255, 193, 7, 0.3)';
            errorDiv.style.color = '#ffc107';
            errorDiv.textContent = '⚠️ First login detected. Please change your default password for security.';
        }, 1000);
    }
}

// Confirmation modal functions
let confirmationCallback = null;

function showConfirmation(title, message, buttonText, callback) {
    document.getElementById('confirmationTitle').textContent = title;
    document.getElementById('confirmationMessage').innerHTML = message;
    document.getElementById('confirmationButton').textContent = buttonText;
    confirmationCallback = callback;
    document.getElementById('confirmationModal').classList.add('active');
}

function closeConfirmation() {
    document.getElementById('confirmationModal').classList.remove('active');
    confirmationCallback = null;
}

function confirmAction() {
    if (confirmationCallback) {
        confirmationCallback();
    }
    closeConfirmation();
}

function refreshContainerModalIfOpen() {
    const containerModal = document.getElementById('containerModal');
    if (containerModal && containerModal.classList.contains('active') && window.currentContainer) {
        // Find the updated container data using the stored container ID
        const updatedContainer = containers.find(c => c.host_id === window.currentContainer.host_id && c.short_id === window.currentContainer.short_id);
        if (updatedContainer) {
            // Remember which tab is currently active
            let activeTab = 'info';
            if (document.getElementById('logs-tab').style.display !== 'none') {
                activeTab = 'logs';
            } else if (document.getElementById('stats-tab').style.display !== 'none') {
                activeTab = 'stats';
            }

            // Only refresh info tab if container state changed (not just stats update)
            if (activeTab === 'info') {
                // Check if this is just a stats update (state hasn't changed)
                const stateChanged = updatedContainer.state !== window.currentContainer.state;
                if (stateChanged) {
                    // Re-populate the modal with updated data (but preserve the tab)
                    showContainerDetails(updatedContainer.host_id, updatedContainer.short_id, activeTab);
                } else {
                    // Just update the reference - sparklines will update automatically
                    window.currentContainer = updatedContainer;

                    // Refresh recent events every 30 seconds without full re-render
                    if (!window.lastEventsRefresh || (Date.now() - window.lastEventsRefresh) > 30000) {
                        if (typeof loadContainerRecentEvents === 'function') {
                            loadContainerRecentEvents(updatedContainer.name, updatedContainer.host_id);
                            window.lastEventsRefresh = Date.now();
                        }
                    }
                }
            } else {
                // Just update the current container reference for stats/logs tabs
                window.currentContainer = updatedContainer;
            }
        }
    }
}

// Toggle functions
function toggleSwitch(element) {
    element.classList.toggle('active');
}

async function toggleAutoRestart(hostId, containerId, event) {
    event.stopPropagation();

    // Find the container to get current state (must match both container ID and host)
    const container = containers.find(c =>
        (c.short_id === containerId || c.id === containerId) && c.host_id === hostId
    );
    if (!container) {
        return;
    }

    const newState = !container.auto_restart;

    // Find the host name
    const host = hosts.find(h => h.id === hostId);
    const hostName = host ? host.name : 'Unknown Host';

    try {
        const response = await fetch(`${API_BASE}/api/containers/${container.short_id}/auto-restart`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                host_id: hostId,
                container_name: container.name,
                enabled: newState
            })
        });

        if (response.ok) {
            // Update local state for all matching containers (same name + host)
            containers.forEach(c => {
                if (c.host_id === hostId && c.id === container.id) {
                    c.auto_restart = newState;
                    c.restart_attempts = 0;
                }
            });

            renderHosts();
            renderDashboardWidgets();
            initIcons();

            // Update modal content if it's open and showing this container
            if (window.currentContainer && window.currentContainer.id === container.id && window.currentContainer.host_id === hostId) {
                // Preserve current tab when updating for auto-restart
                let activeTab = 'info';
                if (document.getElementById('logs-tab').style.display !== 'none') {
                    activeTab = 'logs';
                }
                showContainerDetails(container.host_id, container.short_id, activeTab);
            }

            const status = newState ? 'enabled' : 'disabled';
            showToast(`🔄 Auto-restart ${status} for ${container.name} on ${hostName}`);

            if (newState && container.state === 'exited') {
                // Trigger restart attempt
                restartContainer(hostId, container.id);
            }
        } else {
            showToast('❌ Failed to toggle auto-restart');
        }
    } catch (error) {
        logger.error('Error toggling auto-restart:', error);
        showToast('❌ Failed to toggle auto-restart');
    }
}

// Actions
async function addHost(event) {
    event.preventDefault();
    const formData = new FormData(event.target);

    const hostData = {
        name: formData.get('hostname'),
        url: formData.get('hosturl')
    };

    // Handle certificate data from either file upload or text input
    const tlsCertificate = await getCertificateData(formData, 'tlscert');
    const tlsKey = await getCertificateData(formData, 'tlskey');
    const tlsCa = await getCertificateData(formData, 'tlsca');

    if (tlsCertificate) hostData.tls_cert = tlsCertificate;
    if (tlsKey) hostData.tls_key = tlsKey;
    if (tlsCa) hostData.tls_ca = tlsCa;

    const isEditing = window.editingHost !== null;
    const url = isEditing ? `${API_BASE}/api/hosts/${window.editingHost.id}` : `${API_BASE}/api/hosts`;
    const method = isEditing ? 'PUT' : 'POST';

    try {
        const response = await fetch(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(hostData)
        });
        
        if (response.ok) {
            const updatedHost = await response.json();

            if (isEditing) {
                showToast('✅ Host updated successfully!');
            } else {
                showToast('✅ Host added successfully!');
            }

            // Refresh hosts and containers from server to ensure we have complete data
            await fetchHosts();
            await fetchContainers();

            // Explicitly refresh the host list on the Host Management page
            renderHosts();
            renderHostsPage(); // Make sure the Host Management page is updated too
            updateStats();
            updateNavBadges();
            closeModal('hostModal');
            event.target.reset();
            window.editingHost = null;
        } else {
            const action = isEditing ? 'update' : 'add';
            try {
                const errorData = await response.json();

                // Handle Pydantic validation errors (array format)
                if (errorData.detail && Array.isArray(errorData.detail)) {
                    const messages = errorData.detail.map(err => {
                        // Root validators have __root__ as location
                        if (err.loc && err.loc.includes('__root__')) {
                            return err.msg.replace('Value error, ', '');
                        }
                        // Field-specific errors
                        const field = err.loc ? err.loc[err.loc.length - 1] : 'field';
                        const fieldName = field === 'tls_ca' ? 'CA Certificate' :
                                         field === 'tls_cert' ? 'Client Certificate' :
                                         field === 'tls_key' ? 'Client Private Key' : field;
                        return `${fieldName}: ${err.msg.replace('Value error, ', '')}`;
                    });
                    showToast(`❌ Failed to ${action} host:\n${messages.join('\n')}`);
                }
                // Handle simple error messages (string format)
                else if (errorData.detail && typeof errorData.detail === 'string') {
                    showToast(`❌ Failed to ${action} host: ${errorData.detail}`);
                }
                else {
                    showToast(`❌ Failed to ${action} host`);
                }
            } catch (parseError) {
                // If JSON parsing fails, show raw text
                const errorText = await response.text();
                showToast(`❌ Failed to ${action} host: ${errorText}`);
            }
        }
    } catch (error) {
        const action = isEditing ? 'update' : 'add';
        logger.error(`Error ${action}ing host:`, error);
        showToast(`❌ Failed to ${action} host`);
    }
}

async function createAlertRule(event) {
    event.preventDefault();

    const states = [];
    const channels = [];
    let containerPattern = '';
    let hostId = null;
    let containerHostPairs = [];

    // Determine container selection
    // Get selected containers with their host IDs
    const allCheckboxes = document.querySelectorAll('#containerSelectionCheckboxes input[type="checkbox"]');
    const checkedCheckboxes = document.querySelectorAll('#containerSelectionCheckboxes input[type="checkbox"]:checked');

    // If all checkboxes are checked, treat it as "monitor all containers"
    if (allCheckboxes.length > 0 && allCheckboxes.length === checkedCheckboxes.length) {
        containerPattern = '.*';
        hostId = null;
        // Don't use container+host pairs for "all containers"
        containerHostPairs = []; // Clear any previously selected containers
    } else {
        // Get selected containers with their host IDs
        checkedCheckboxes.forEach(cb => {
            if (cb.dataset.hostId && cb.value) {
                containerHostPairs.push({
                    host_id: cb.dataset.hostId,
                    container_name: cb.value
                });
            }
        });

        if (containerHostPairs.length === 0) {
            showToast('❌ Please select at least one container');
            return;
        }

        // For the new system, we don't need to build patterns
        // The backend will handle the container+host pairs directly
        containerPattern = null; // Will be set to ".*" by backend as default
    }

    // Get selected events, states, and channels
    const events = [];
    event.target.querySelectorAll('input[type="checkbox"]:checked').forEach(cb => {
        if (cb.name === 'channels') {
            channels.push(parseInt(cb.value));
        } else if (cb.dataset.event) {
            events.push(cb.dataset.event);
        } else if (cb.dataset.state) {
            states.push(cb.dataset.state);
        }
    });

    const ruleName = document.getElementById('alertRuleName').value;
    const cooldownMinutes = parseInt(document.getElementById('cooldownMinutes').value) || 15;

    // Validate that at least one trigger is selected
    if (events.length === 0 && states.length === 0) {
        showToast('❌ Please select at least one Docker event or state to monitor');
        return;
    }

    if (channels.length === 0) {
        showToast('❌ Please select at least one notification channel');
        return;
    }

    const ruleData = {
        name: ruleName,
        containers: containerHostPairs.length > 0 ? containerHostPairs : null,
        trigger_events: events.length > 0 ? events : [],
        trigger_states: states.length > 0 ? states : [],
        notification_channels: channels,
        cooldown_minutes: cooldownMinutes,
        enabled: true
    };

    const isEditing = editingAlertRule !== null;
    const url = isEditing ? `${API_BASE}/api/alerts/${editingAlertRule.id}` : `${API_BASE}/api/alerts`;
    const method = isEditing ? 'PUT' : 'POST';
    
    try {
        const response = await fetch(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(ruleData)
        });
        
        if (response.ok) {
            const rule = await response.json();

            if (isEditing) {
                showToast('✅ Alert rule updated successfully!');
                editingAlertRule = null;
            } else {
                showToast('✅ Alert rule created successfully!');
            }

            // Fetch fresh data from server to ensure UI shows correct information
            await fetchAlertRules();
            renderAlertRules();
            updateStats();
            updateNavBadges();
            closeModal('alertRuleModal');
        } else {
            const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
            logger.error(`Alert ${isEditing ? 'update' : 'creation'} failed:`, errorData);
            const errorMessage = typeof errorData.detail === 'string'
                ? errorData.detail
                : JSON.stringify(errorData.detail) || response.statusText;
            showToast(`❌ Failed to ${isEditing ? 'update' : 'create'} alert: ${errorMessage}`);
        }
    } catch (error) {
        logger.error(`Error ${editingAlertRule ? 'updating' : 'creating'} alert rule:`, error);
        showToast(`❌ Failed to ${editingAlertRule ? 'update' : 'create'} alert rule`);
    }
}

async function checkDependentAlerts(channelId) {
    try {
        const response = await fetch(`${API_BASE}/api/notifications/channels/${channelId}/dependent-alerts`, {
            credentials: 'include'
        });
        const data = await response.json();
        return data.alerts || [];
    } catch (error) {
        logger.error('Error checking dependent alerts:', error);
        return [];
    }
}

// Blackout Windows Management
function renderBlackoutWindows() {
    const container = document.getElementById('blackoutWindowsList');
    if (!container) return;

    if (!globalSettings.blackout_windows || globalSettings.blackout_windows.length === 0) {
        container.innerHTML = '<div style="padding: var(--spacing-md); color: var(--text-secondary); text-align: center;">No blackout windows configured</div>';
        return;
    }

    container.innerHTML = globalSettings.blackout_windows.map((window, index) => `
        <div style="padding: var(--spacing-md); margin-bottom: var(--spacing-md); background: var(--surface); border: 1px solid var(--surface-light); border-radius: var(--radius-md);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--spacing-sm);">
                <input type="text" placeholder="Window name (e.g., Nightly Maintenance)"
                       value="${escapeHtml(window.name || '')}"
                       onchange="updateBlackoutWindow(${index}, 'name', this.value)"
                       style="background: transparent; border: none; color: var(--text-primary); font-size: 14px; flex: 1;">
                <button type="button" class="btn-icon" onclick="removeBlackoutWindow(${index})">
                    <i data-lucide="trash-2"></i>
                </button>
            </div>
            <div style="display: grid; grid-template-columns: 1fr 1fr auto; gap: var(--spacing-sm); align-items: center;">
                <div>
                    <label style="font-size: 12px; color: var(--text-secondary);">Start Time</label>
                    <input type="time" class="form-input" value="${window.start || '02:00'}"
                           onchange="updateBlackoutWindow(${index}, 'start', this.value)">
                </div>
                <div>
                    <label style="font-size: 12px; color: var(--text-secondary);">End Time</label>
                    <input type="time" class="form-input" value="${window.end || '04:00'}"
                           onchange="updateBlackoutWindow(${index}, 'end', this.value)">
                </div>
                <div style="padding-top: 18px;">
                    <label class="toggle-label">
                        <input type="checkbox" ${window.enabled !== false ? 'checked' : ''}
                               onchange="updateBlackoutWindow(${index}, 'enabled', this.checked)">
                        <span>Enabled</span>
                    </label>
                </div>
            </div>
            <div style="margin-top: var(--spacing-sm);">
                <label style="font-size: 12px; color: var(--text-secondary); display: block; margin-bottom: var(--spacing-xs);">Active Days</label>
                <div style="display: flex; gap: var(--spacing-xs); flex-wrap: wrap;">
                    ${['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((day, dayIndex) => `
                        <label class="day-checkbox" style="display: flex; align-items: center; gap: 4px; padding: 4px 8px; background: ${window.days && window.days.includes(dayIndex) ? 'var(--primary)' : 'var(--surface-light)'}; border-radius: var(--radius-sm); cursor: pointer;">
                            <input type="checkbox" ${window.days && window.days.includes(dayIndex) ? 'checked' : ''}
                                   onchange="toggleBlackoutDay(${index}, ${dayIndex}, this.checked)"
                                   style="display: none;">
                            <span style="font-size: 12px; color: ${window.days && window.days.includes(dayIndex) ? 'white' : 'var(--text-secondary)'};">${day}</span>
                        </label>
                    `).join('')}
                </div>
            </div>
        </div>
    `).join('');
    initIcons();
}

function addBlackoutWindow() {
    if (!globalSettings.blackout_windows) {
        globalSettings.blackout_windows = [];
    }
    // Find the next available window number
    const existingNumbers = globalSettings.blackout_windows
        .map(w => w.name.match(/Window (\d+)/))
        .filter(m => m)
        .map(m => parseInt(m[1]));
    const nextNumber = existingNumbers.length > 0 ? Math.max(...existingNumbers) + 1 : 1;

    globalSettings.blackout_windows.push({
        name: `Window ${nextNumber}`,
        start: '02:00',
        end: '04:00',
        days: [0, 1, 2, 3, 4, 5, 6], // All days by default
        enabled: true
    });
    renderBlackoutWindows();
}

function removeBlackoutWindow(index) {
    globalSettings.blackout_windows.splice(index, 1);
    renderBlackoutWindows();
}

function updateBlackoutWindow(index, field, value) {
    if (globalSettings.blackout_windows && globalSettings.blackout_windows[index]) {
        globalSettings.blackout_windows[index][field] = value;
    }
}

function toggleBlackoutDay(windowIndex, dayIndex, checked) {
    if (!globalSettings.blackout_windows[windowIndex].days) {
        globalSettings.blackout_windows[windowIndex].days = [];
    }

    const days = globalSettings.blackout_windows[windowIndex].days;
    if (checked && !days.includes(dayIndex)) {
        days.push(dayIndex);
    } else if (!checked) {
        const idx = days.indexOf(dayIndex);
        if (idx > -1) days.splice(idx, 1);
    }

    renderBlackoutWindows();
}

async function saveBlackoutWindows() {
    try {
        // Add timezone offset (in minutes, negative for timezones ahead of UTC)
        globalSettings.timezone_offset = -new Date().getTimezoneOffset();

        const response = await fetch(`${API_BASE}/api/settings`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(globalSettings)
        });

        if (response.ok) {
            showToast('✅ Blackout windows saved successfully!');
            await updateBlackoutStatus();
        }
    } catch (error) {
        logger.error('Error saving blackout windows:', error);
        showToast('❌ Failed to save blackout windows');
    }
}

async function updateBlackoutStatus() {
    try {
        const response = await fetch(`${API_BASE}/api/blackout/status`, {
            credentials: 'include'
        });
        const status = await response.json();

        const statusDiv = document.getElementById('blackoutStatus');
        if (statusDiv) {
            if (status.is_blackout) {
                statusDiv.innerHTML = `
                    <div style="display: flex; align-items: center; gap: var(--spacing-sm);">
                        <i data-lucide="moon" style="width:20px;height:20px;color:var(--warning);"></i>
                        <div>
                            <div style="color: var(--warning); font-weight: bold;">Currently in Blackout Window</div>
                            <div style="color: var(--text-secondary); font-size: 12px;">${status.current_window}</div>
                        </div>
                    </div>
                `;
                initIcons();
            } else {
                statusDiv.innerHTML = `
                    <div style="display: flex; align-items: center; gap: var(--spacing-sm);">
                        <i data-lucide="sun" style="width:20px;height:20px;color:var(--success);"></i>
                        <div>
                            <div style="color: var(--text-primary);">No active blackout window</div>
                            <div style="color: var(--text-secondary); font-size: 12px;">Alerts are being sent normally</div>
                        </div>
                    </div>
                `;
                initIcons();
            }

            // Update dashboard indicator
            const dashboardIndicator = document.getElementById('quietHoursIndicator');
            if (dashboardIndicator) {
                if (status.is_blackout) {
                    dashboardIndicator.style.display = 'flex';
                    dashboardIndicator.innerHTML = `
                        <i data-lucide="moon"></i>
                        <span>In Blackout Window</span>
                    `;
                    initIcons();
                } else {
                    dashboardIndicator.style.display = 'none';
                }
            }
        }
    } catch (error) {
        logger.error('Error fetching blackout status:', error);
    }
}

async function saveGlobalSettings() {
    globalSettings.max_retries = parseInt(document.getElementById('maxRetries').value);
    globalSettings.retry_delay = parseInt(document.getElementById('retryDelay').value);
    globalSettings.polling_interval = parseInt(document.getElementById('pollingInterval').value);
    globalSettings.connection_timeout = parseInt(document.getElementById('connectionTimeout').value);
    globalSettings.default_auto_restart = document.getElementById('defaultAutoRestart').classList.contains('active');
    globalSettings.show_host_stats = document.getElementById('showHostStats').classList.contains('active');
    globalSettings.show_container_stats = document.getElementById('showContainerStats').classList.contains('active');

    // Include blackout windows in the save

    try {
        const response = await fetch(`${API_BASE}/api/settings`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(globalSettings)
        });

        if (response.ok) {
            showToast('✅ Settings saved successfully!');
            closeModal('globalSettingsModal');
            // Re-render dashboard to apply show_host_stats and show_container_stats changes
            if (typeof renderHosts === 'function') {
                renderHosts();
            }
        }
    } catch (error) {
        logger.error('Error saving settings:', error);
        showToast('❌ Failed to save settings');
    }
}

async function deleteAlertRule(ruleId) {
    const rule = alertRules.find(r => r.id === ruleId);
    const ruleName = rule ? rule.name : 'Unknown Rule';

    const message = `Are you sure you want to delete the alert rule <strong>"${escapeHtml(ruleName)}"</strong>?<br><br>
        This will permanently remove the alert rule and you will no longer receive notifications for this container.<br><br>
        <strong>This action cannot be undone.</strong>`;

    showConfirmation('Delete Alert Rule', message, 'Delete Rule', async () => {
        try {
            const response = await fetch(`${API_BASE}/api/alerts/${ruleId}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                showToast('Alert rule deleted');
                // Fetch fresh data from server to ensure UI is up to date
                await fetchAlertRules();
                renderAlertRules();
                updateStats();
                updateNavBadges();
            }
        } catch (error) {
            logger.error('Error deleting alert rule:', error);
            showToast('❌ Failed to delete alert rule');
        }
    });
}
