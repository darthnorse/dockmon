async function init() {
            console.log('Starting initialization...');

            // Check authentication first
            const isAuthenticated = await checkAuthentication();
            if (!isAuthenticated) {
                return; // Stop initialization if not authenticated
            }


            // First establish WebSocket connection with a small delay
            connectWebSocket();

            // Set up cleanup function for modal close
            window.cleanupLogStream = function() {
                stopAutoRefresh();
            };

            // Give WebSocket a moment to connect, then fetch data as fallback
            await new Promise(resolve => setTimeout(resolve, 1000));

            // Fetch initial data with fallback handling
            console.log('Fetching initial data...');
            const results = await Promise.allSettled([
                fetchHosts(),
                fetchContainers(),
                fetchSettings(),
                loadNotificationChannels(),
                fetchAlertRules()
            ]);

            // Check results but don't fail initialization
            results.forEach((result, index) => {
                const names = ['hosts', 'containers', 'settings', 'notificationChannels', 'alertRules'];
                if (result.status === 'rejected') {
                    console.warn(`Failed to fetch ${names[index]}:`, result.reason);
                } else {
                    console.log(`Successfully fetched ${names[index]}`);
                }
            });

            // Save timezone offset to database on initial load (silent, no toast)
            try {
                await fetch(`${API_BASE}/api/settings`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify(globalSettings)
                });
            } catch (error) {
                console.error('Failed to save timezone offset:', error);
            }

            console.log('Rendering initial UI...');
            renderAll();

            // Update quiet hours indicator on dashboard
            updateBlackoutStatus();

            // Initialize dashboard if we're on the dashboard page
            // This handles the case when fetch completes before WebSocket
            if (currentPage === 'dashboard' && grid === null && hosts.length > 0) {
                console.log('Initializing dashboard after fetch data load...');
                // Small delay to ensure DOM is ready, but data is already loaded
                setTimeout(() => {
                    if (grid === null) {
                        initDashboard();
                    }
                }, 100);
            }

            console.log('Initialization completed successfully');
        }

        function renderAll() {
            renderHosts();
            renderAlertRules();
            updateStats();
            updateNavBadges();
        }

        // Page switching
        function switchPage(page, event) {
            // Update active nav item
            document.querySelectorAll('.nav-item').forEach(item => {
                item.classList.remove('active');
            });
            if (event && event.currentTarget) {
                event.currentTarget.classList.add('active');
            }

            // Hide all pages
            document.querySelectorAll('.page-section').forEach(section => {
                section.classList.remove('active');
            });

            // Show selected page
            const pageElement = document.getElementById(`${page}-page`);
            if (!pageElement) {
                console.error(`Page element not found: ${page}-page`);
                showToast(`Page "${page}" not yet available`);
                return;
            }
            pageElement.classList.add('active');
            currentPage = page;

            // Initialize dashboard when switching to it
            if (page === 'dashboard') {
                if (grid === null) {
                    // Wait for hosts data before initializing dashboard
                    if (hosts.length === 0) {
                        console.log('Waiting for hosts data before initializing dashboard...');
                        let checkData = null;
                        let timeoutId = null;

                        checkData = setInterval(() => {
                            if (hosts.length > 0) {
                                clearInterval(checkData);
                                if (timeoutId) clearTimeout(timeoutId);
                                setTimeout(() => initDashboard(), 100);
                            }
                        }, 100);

                        // Timeout after 5 seconds and initialize anyway
                        timeoutId = setTimeout(() => {
                            if (checkData) clearInterval(checkData);
                            if (grid === null) {
                                console.log('Initializing dashboard after timeout');
                                initDashboard();
                            }
                        }, 5000);
                    } else {
                        setTimeout(() => initDashboard(), 100); // Delay to ensure DOM is ready
                    }
                } else {
                    renderDashboardWidgets(); // Refresh existing widgets
                }
            }

            // Update page title
            const titles = {
                'dashboard': 'Dashboard',
                'hosts': 'Host Management',
                'alerts': 'Alert Rules',
                'logs': 'Events',
                'about': 'About'
            };
            document.getElementById('pageTitle').textContent = titles[page] || 'Dashboard';
            
            // Render page-specific content
            if (page === 'hosts') {
                renderHostsPage();
            } else if (page === 'alerts') {
                renderAlertsPage();
            }
        }

        // Render functions
        function renderHosts() {
            // If on dashboard page, update widgets
            if (currentPage === 'dashboard') {
                renderDashboardWidgets();
                return;
            }

            const hostsGrid = document.getElementById('hostsGrid');
            if (!hostsGrid) return;
            hostsGrid.innerHTML = '';

            // Group containers by host
            const containersByHost = {};
            hosts.forEach(host => {
                containersByHost[host.id] = [];
            });
            
            containers.forEach(container => {
                if (containersByHost[container.host_id]) {
                    containersByHost[container.host_id].push(container);
                }
            });
            
            hosts.forEach(host => {
                const hostCard = document.createElement('div');
                hostCard.className = 'host-card';
                
                const hostContainers = (containersByHost[host.id] || []).sort((a, b) => a.name.localeCompare(b.name));
                const containersList = hostContainers.map(container => `
                    <div class="container-item" data-status="${escapeHtml(container.state)}">
                        <div class="container-info" onclick="showContainerDetails('${escapeHtml(container.host_id)}', '${escapeHtml(container.short_id)}')">
                            <div class="container-icon container-${escapeHtml(container.state)}">
                                ${getContainerIcon(container.state)}
                            </div>
                            <div class="container-details">
                                <div class="container-name">${escapeHtml(container.name)}</div>
                                <div class="container-id">${escapeHtml(container.short_id)}</div>
                            </div>
                        </div>
                        <div class="container-actions">
                            <div class="auto-restart-toggle ${container.auto_restart ? 'enabled' : ''}"
                                 onclick="event.stopPropagation()">
                                <span>🔄 Auto</span>
                                <div class="toggle-switch ${container.auto_restart ? 'active' : ''}"
                                     onclick="toggleAutoRestart('${escapeHtml(container.host_id)}', '${escapeHtml(container.short_id)}', event)"></div>
                            </div>
                            <span class="container-state ${getStateClass(container.state)}">
                                ${escapeHtml(container.state)}
                            </span>
                        </div>
                    </div>
                `).join('');
                
                hostCard.innerHTML = `
                    <div class="host-header">
                        <div class="host-name">
                            <span>🖥️</span> ${host.name}
                            ${getSecurityStatusBadge(host)}
                        </div>
                        <span class="host-status status-${host.status}">${host.status}</span>
                    </div>
                    <div class="container-list">
                        ${containersList || '<div style="padding: 12px; color: var(--text-tertiary); text-align: center;">No containers</div>'}
                    </div>
                `;
                
                hostsGrid.appendChild(hostCard);
            });
        }

        function renderHostsPage() {
            const hostsList = document.getElementById('hostsList');
            hostsList.innerHTML = hosts.map(host => {
                const hostContainers = containers.filter(c => c.host_id === host.id);
                return `
                    <div class="alert-rule-card">
                        <div class="alert-rule-info">
                            <div class="alert-rule-title">${host.name} ${getSecurityStatusBadge(host)}</div>
                            <div class="alert-rule-details">${host.url} • ${hostContainers.length} containers</div>
                            <div class="alert-rule-details" style="margin-top: 4px;">
                                Status: <span class="status-${host.status}">${host.status}</span>
                                ${host.error ? `• Error: ${host.error}` : ''}
                            </div>
                        </div>
                        <div style="display: flex; gap: var(--spacing-sm);">
                            <button class="btn-icon" onclick="editHost('${host.id}')" title="Edit Host"><i data-lucide="edit"></i></button>
                            <button class="btn-icon" onclick="deleteHost('${host.id}')" title="Delete Host"><i data-lucide="trash-2"></i></button>
                        </div>
                    </div>
                `;
            }).join('');
            initIcons();
        }

        function renderAlertsPage() {
            renderAlertRules();
        }

        function renderAlertRules() {
            try {
                const alertRulesList = document.getElementById('alertRulesList');
                if (!alertRulesList) return;

                alertRulesList.innerHTML = '';

                if (!alertRules || !Array.isArray(alertRules)) {
                    console.warn('alertRules is not an array:', alertRules);
                    return;
                }

                alertRules.forEach(rule => {
                const ruleCard = document.createElement('div');
                ruleCard.className = 'alert-rule-card';

                // Map channel IDs to channel names
                const channelBadges = (rule.notification_channels || []).map(channelId => {
                    const channel = notificationChannels.find(ch => ch.id === channelId);
                    const channelName = channel ? channel.name : `Channel ${channelId}`;
                    return `<span class="channel-badge">${channelName}</span>`;
                }).join('');

                // Display container information
                let containerInfo = '';
                if (rule.containers && rule.containers.length > 0) {
                    // Group containers by name to count hosts per container
                    const containerHostCount = {};
                    rule.containers.forEach(c => {
                        if (!containerHostCount[c.container_name]) {
                            containerHostCount[c.container_name] = new Set();
                        }
                        containerHostCount[c.container_name].add(c.host_id);
                    });

                    // Build display string showing container names with host counts
                    const containerParts = Object.entries(containerHostCount).map(([name, hosts]) => {
                        if (hosts.size > 1) {
                            return `${name} (${hosts.size} hosts)`;
                        }
                        return name;
                    });

                    containerInfo = containerParts.join(', ');
                } else {
                    containerInfo = 'All containers';
                }

                // Display trigger information
                let triggerInfo = [];
                if (rule.trigger_states && rule.trigger_states.length > 0) {
                    triggerInfo.push(`States: ${rule.trigger_states.join(', ')}`);
                }
                if (rule.trigger_events && rule.trigger_events.length > 0) {
                    triggerInfo.push(`Events: ${rule.trigger_events.join(', ')}`);
                }
                const triggerText = triggerInfo.length > 0 ? triggerInfo.join(' | ') : 'No triggers';

                // Check if rule has orphaned containers
                const isOrphaned = rule.is_orphaned || false;
                const orphanedContainers = rule.orphaned_containers || [];
                let orphanWarning = '';
                if (isOrphaned && orphanedContainers.length > 0) {
                    const orphanNames = orphanedContainers.map(c => `${c.container_name} (${c.host_name})`).join(', ');
                    orphanWarning = `
                        <div class="alert-warning" style="margin-top: 8px; padding: 8px; background: var(--warning); color: var(--dark); border-radius: 4px; font-size: 12px;">
                            <i data-lucide="alert-triangle" style="width:14px;height:14px;vertical-align:middle;"></i>
                            <strong>Warning:</strong> Container(s) not found: ${orphanNames}
                        </div>
                    `;
                }

                ruleCard.innerHTML = `
                    <div class="alert-rule-info">
                        <div class="alert-rule-title">
                            ${rule.name}
                            ${isOrphaned ? '<span style="margin-left: 8px; padding: 2px 6px; background: var(--warning); color: var(--dark); border-radius: 3px; font-size: 11px; font-weight: bold;">⚠ BROKEN</span>' : ''}
                        </div>
                        <div class="alert-rule-details">Containers: ${containerInfo} | ${triggerText}</div>
                        <div class="alert-channels">${channelBadges}</div>
                        ${orphanWarning}
                    </div>
                    <div class="alert-rule-actions">
                        <button class="btn-icon" onclick="editAlertRule('${rule.id}')" title="Edit Alert Rule">
                            <i data-lucide="edit"></i>
                        </button>
                        <button class="btn-icon" onclick="deleteAlertRule('${rule.id}')" title="Delete Alert Rule">
                            <i data-lucide="trash-2"></i>
                        </button>
                    </div>
                `;
                
                alertRulesList.appendChild(ruleCard);
                });
            } catch (error) {
                console.error('Error rendering alert rules:', error);
            }
            initIcons();
        }

        // Update functions
        function updateStats() {
            // Stats are now handled by dashboard widgets
            // Only update if we're not on the dashboard page (for backward compatibility)
            if (currentPage !== 'dashboard') {
                const totalHostsEl = document.getElementById('totalHosts');
                const totalContainersEl = document.getElementById('totalContainers');
                const runningContainersEl = document.getElementById('runningContainers');
                const alertRulesEl = document.getElementById('alertRules');

                if (totalHostsEl) totalHostsEl.textContent = hosts.length;
                if (totalContainersEl) totalContainersEl.textContent = containers.length;
                if (runningContainersEl) runningContainersEl.textContent = containers.filter(c => c.state === 'running').length;
                if (alertRulesEl) alertRulesEl.textContent = alertRules.length;
            }
        }

        function updateNavBadges() {
            // Navigation badges removed - stats are shown in dashboard widget instead
        }

        // Helper functions
        function getContainerIcon(state) {
            switch(state) {
                case 'running': return '▶';
                case 'exited': return '■';
                case 'paused': return '⏸';
                default: return '?';
            }
        }

        function getStateClass(state) {
            switch(state) {
                case 'running': return 'status-online';
                case 'exited': return 'status-offline';
                case 'paused': return 'channel-pushover';
                default: return '';
            }
        }

        // Modal functions
        function openHostModal() {
            // Reset form for adding new host
            const modalTitle = document.querySelector('#hostModal .modal-title');
            const submitButton = document.querySelector('#hostModal button[type="submit"]');

            modalTitle.textContent = 'Add Docker Host';
            submitButton.textContent = 'Add Host';

            // Clear the form
            document.querySelector('input[name="hostname"]').value = '';
            document.querySelector('input[name="hosturl"]').value = '';

            // Clear editing state
            window.editingHost = null;

            // Hide security warning and certificates
            checkHostSecurity('');

            document.getElementById('hostModal').classList.add('active');
            // Certificate paste mode is already visible
        }

        function checkHostSecurity(url) {
            const securityWarning = document.getElementById('security-warning');
            const tlsCertificates = document.getElementById('tls-certificates');

            // Show warning and certificate fields for TCP connections
            if (url && url.toLowerCase().startsWith('tcp://')) {
                // Check if we're editing an existing secure host
                const isEditingSecureHost = window.editingHost && window.editingHost.security_status === 'secure';

                if (isEditingSecureHost) {
                    // Host is already configured as secure, no warning needed
                    securityWarning.style.display = 'none';
                } else {
                    // New host or insecure host, show warning
                    securityWarning.style.display = 'flex';
                }

                // Always show certificate fields for TCP connections
                tlsCertificates.style.display = 'block';
            } else {
                securityWarning.style.display = 'none';
                tlsCertificates.style.display = 'none';
            }
        }


        async function getCertificateData(formData, certType) {
            // Get from text input (copy/paste mode only)
            const textData = formData.get(`${certType}-text`);
            if (textData && textData.trim()) {
                return textData.trim();
            }
            return null;
        }

        // Removed regex pattern mode - now only using checkbox selection

        function toggleAllContainers(checkbox) {
            const containerCheckboxes = document.querySelectorAll('#containerSelectionCheckboxes input[type="checkbox"]');
            const containerList = document.getElementById('containerSelectionCheckboxes');

            if (checkbox.checked) {
                containerList.style.display = 'none';
                containerCheckboxes.forEach(cb => cb.checked = false);
            } else {
                containerList.style.display = 'block';
            }
        }

        function populateContainerCheckboxes() {
            const container = document.getElementById('containerSelectionCheckboxes');
            container.innerHTML = '';

            // Group containers by host
            const containersByHost = {};
            containers.forEach(cont => {
                const hostName = cont.host_name || 'Unknown Host';
                if (!containersByHost[hostName]) {
                    containersByHost[hostName] = [];
                }
                containersByHost[hostName].push(cont);
            });

            // Create checkboxes grouped by host
            Object.keys(containersByHost).sort().forEach(hostName => {
                // Host header
                const hostDiv = document.createElement('div');
                hostDiv.style.marginBottom = '15px';

                const hostHeader = document.createElement('div');
                hostHeader.style.fontWeight = 'bold';
                hostHeader.style.marginBottom = '8px';
                hostHeader.style.color = 'var(--primary)';
                hostHeader.textContent = hostName;
                hostDiv.appendChild(hostHeader);

                // Container checkboxes for this host
                const containersDiv = document.createElement('div');
                containersDiv.style.paddingLeft = '20px';

                containersByHost[hostName].sort((a, b) => a.name.localeCompare(b.name)).forEach(cont => {
                    const label = document.createElement('label');
                    label.className = 'checkbox-item';
                    label.style.display = 'flex';
                    label.style.alignItems = 'center';
                    label.style.gap = '8px';
                    label.style.marginBottom = '5px';

                    const checkbox = document.createElement('input');
                    checkbox.type = 'checkbox';
                    checkbox.value = cont.name;
                    checkbox.dataset.hostId = cont.host_id;
                    checkbox.dataset.containerId = cont.id;

                    const stateIndicator = document.createElement('span');
                    stateIndicator.style.display = 'inline-block';
                    stateIndicator.style.width = '8px';
                    stateIndicator.style.height = '8px';
                    stateIndicator.style.borderRadius = '50%';
                    stateIndicator.style.backgroundColor = cont.state === 'running' ? '#00c48c' : '#ff647c';

                    const text = document.createElement('span');
                    text.textContent = cont.name;

                    label.appendChild(checkbox);
                    label.appendChild(stateIndicator);
                    label.appendChild(text);
                    containersDiv.appendChild(label);
                });

                hostDiv.appendChild(containersDiv);
                container.appendChild(hostDiv);
            });

            // If no containers, show message
            if (Object.keys(containersByHost).length === 0) {
                container.innerHTML = '<p style="color: var(--text-tertiary); text-align: center;">No containers available</p>';
            }
        }

        function openAlertRuleModal(preselectedContainer = null, editRule = null) {
            // Update modal title and button text based on mode
            const modalTitle = document.querySelector('#alertRuleModal .modal-title');
            const submitButton = document.querySelector('#alertRuleModal button[type="submit"]');

            if (editRule) {
                modalTitle.textContent = 'Edit Alert Rule';
                submitButton.textContent = 'Update Alert Rule';
                // Store the rule being edited
                editingAlertRule = editRule;
                // Populate form with existing rule data
                document.getElementById('alertRuleName').value = editRule.name || '';

                // We'll populate other fields after the form is built
                setTimeout(() => {
                    // Select trigger states - handled individually below for better control

                    // Select notification channels
                    if (editRule.notification_channels) {
                        editRule.notification_channels.forEach(channelId => {
                            const checkbox = document.querySelector(`input[value="${channelId}"]`);
                            if (checkbox) checkbox.checked = true;
                        });
                    }

                    // Set cooldown
                    const cooldownInput = document.getElementById('cooldownMinutes');
                    if (cooldownInput && editRule.cooldown_minutes) {
                        cooldownInput.value = editRule.cooldown_minutes;
                    }
                }, 100);
            } else {
                modalTitle.textContent = 'Create Alert Rule';
                submitButton.textContent = 'Create Alert Rule';
                // Clear the form completely
                document.getElementById('alertRuleName').value = '';
                editingAlertRule = null;

                // Clear all checkboxes (events, states, containers, channels)
                document.querySelectorAll('#alertRuleModal input[type="checkbox"]').forEach(cb => cb.checked = false);

                // Set default selections for new alerts
                setTimeout(() => {
                    // Default events: OOM, Die (non-zero), Health: Unhealthy
                    const defaultEvents = ['oom', 'die-nonzero', 'health_status:unhealthy'];
                    defaultEvents.forEach(event => {
                        const checkbox = document.querySelector(`input[type="checkbox"][data-event="${event}"]`);
                        if (checkbox) checkbox.checked = true;
                    });

                    // Default states: Exited, Dead
                    const defaultStates = ['exited', 'dead'];
                    defaultStates.forEach(state => {
                        const checkbox = document.querySelector(`input[type="checkbox"][data-state="${state}"]`);
                        if (checkbox) checkbox.checked = true;
                    });
                }, 50);
            }

            // Populate container checkboxes
            populateContainerCheckboxes();

            // If editing a rule, restore the selected containers
            if (editRule) {
                // First, check if the rule has the new container+host pairs format
                if (editRule.containers && editRule.containers.length > 0) {
                    // New format: use specific container+host pairs
                    document.getElementById('selectAllContainers').checked = false;
                    document.getElementById('containerSelectionCheckboxes').style.display = 'block';
                    document.querySelectorAll('#containerSelectionCheckboxes input[type="checkbox"]').forEach(cb => {
                        cb.checked = false; // Clear all first
                    });

                    editRule.containers.forEach(containerPair => {
                        document.querySelectorAll('#containerSelectionCheckboxes input[type="checkbox"]').forEach(cb => {
                            if (cb.value === containerPair.container_name &&
                                cb.dataset.hostId === containerPair.host_id) {
                                cb.checked = true;
                            }
                        });
                    });
                } else {
                    // Empty containers array means "all containers"
                    document.getElementById('selectAllContainers').checked = true;
                    document.getElementById('containerSelectionCheckboxes').style.display = 'none';
                }
            }

            // Pre-select container if one was specified (must match both container name AND host)
            if (preselectedContainer && !editRule) {
                document.querySelectorAll('#containerSelectionCheckboxes input[type="checkbox"]').forEach(cb => {
                    if (cb.value === preselectedContainer.name && cb.dataset.hostId === preselectedContainer.host_id) {
                        cb.checked = true;
                    }
                });
            }

            // Populate notification channels
            populateNotificationChannels();

            // If editing, populate form fields
            if (editRule) {
                // Clear and set trigger checkboxes immediately (no setTimeout needed here)
                // Clear only trigger state and event checkboxes first (not container or notification checkboxes)
                document.querySelectorAll('#alertRuleModal input[type="checkbox"][data-state]').forEach(cb => cb.checked = false);
                document.querySelectorAll('#alertRuleModal input[type="checkbox"][data-event]').forEach(cb => cb.checked = false);

                // Check appropriate boxes based on trigger events
                if (editRule.trigger_events) {
                    editRule.trigger_events.forEach(event => {
                        const checkbox = document.querySelector(`input[type="checkbox"][data-event="${event}"]`);
                        if (checkbox) checkbox.checked = true;
                    });
                }

                // Check appropriate boxes based on trigger states
                if (editRule.trigger_states) {
                    editRule.trigger_states.forEach(state => {
                        const checkbox = document.querySelector(`input[type="checkbox"][data-state="${state}"]`);
                        if (checkbox) checkbox.checked = true;
                    });
                }

                // Set notification channels - with small delay to ensure they're loaded
                setTimeout(() => {
                    if (editRule.notification_channels) {
                        editRule.notification_channels.forEach(channelId => {
                            const channelCheckbox = document.querySelector(`input[type="checkbox"][data-channel-id="${channelId}"]`);
                            if (channelCheckbox) channelCheckbox.checked = true;
                        });
                    }
                }, 100); // Small delay to ensure notification channels are loaded
            }

            document.getElementById('alertRuleModal').classList.add('active');
        }



        async function deleteHost(hostId) {
            const host = hosts.find(h => h.id === hostId);
            const hostName = host ? host.name : 'Unknown Host';

            const message = `Are you sure you want to delete the host <strong>"${hostName}"</strong>?<br><br>
                This will:<br>
                • Remove the host and all its containers<br>
                • Remove this host's containers from alert rules<br>
                • Delete alerts that only monitor this host's containers<br>
                • Stop all monitoring for this host<br><br>
                <strong>This action cannot be undone.</strong>`;

            showConfirmation('Delete Host', message, 'Delete Host', async () => {
                try {
                    const response = await fetch(`${API_BASE}/api/hosts/${hostId}`, {
                        method: 'DELETE'
                    });

                    if (response.ok) {
                        showToast('Host removed');
                        // Fetch fresh data from server
                        await fetchHosts();
                        await fetchContainers();
                        await fetchAlertRules();
                        renderHostsPage();
                        renderHosts();
                        updateStats();
                        updateNavBadges();
                    }
                } catch (error) {
                    console.error('Error deleting host:', error);
                    showToast('❌ Failed to delete host');
                }
            });
        }

        function editHost(hostId) {
            // Find the host to edit
            const host = hosts.find(h => h.id === hostId);
            if (!host) {
                showToast('❌ Host not found');
                return;
            }

            // Populate the form with existing host data
            document.querySelector('input[name="hostname"]').value = host.name;
            document.querySelector('input[name="hosturl"]').value = host.url;

            // Set up the modal for editing
            const modalTitle = document.querySelector('#hostModal .modal-title');
            const submitButton = document.querySelector('#hostModal button[type="submit"]');

            modalTitle.textContent = 'Edit Docker Host';
            submitButton.textContent = 'Update Host';

            // Store the host being edited
            window.editingHost = host;

            // Check security and show certificate fields if needed
            checkHostSecurity(host.url);

            // Show the modal
            document.getElementById('hostModal').classList.add('active');
        }

        async function refreshAll() {
            showToast('🔄 Refreshing...');
            await Promise.all([
                fetchHosts(),
                fetchContainers(),
                fetchAlertRules()
            ]);
            renderHosts();

            // Refresh logs dropdown if on logs page
            if (currentPage === 'logs' && typeof populateContainerList === 'function') {
                populateContainerList();
            }
        }

        function showContainerDetails(hostId, containerId, preserveTab = null) {
            const container = containers.find(c => c.host_id === hostId && c.short_id === containerId);
            if (container) {
                // Only reset logs if we're switching to a different container
                if (!window.currentContainer || window.currentContainer.host_id !== container.host_id || window.currentContainer.short_id !== container.short_id) {
                    // Stop any existing log polling when switching containers
                    stopAutoRefresh();

                    // Clear logs from previous container
                    const logsDiv = document.getElementById('container-logs');
                    if (logsDiv) {
                        logsDiv.innerHTML = '<div style="color: var(--text-tertiary);">Loading logs...</div>';
                    }
                    // Reset log state and filter
                    lastLogTimestamp = null;
                    accumulatedLogs = [];
                    const filterInput = document.getElementById('logSearchFilter');
                    if (filterInput) {
                        filterInput.value = '';
                    }
                    const matchCount = document.getElementById('logMatchCount');
                    if (matchCount) {
                        matchCount.textContent = '';
                    }
                }

                // Store current container info globally for modal functions
                window.currentContainer = container;

                // Check if there's an alert rule for this container on this specific host
                const hasAlert = alertRules.some(rule => {
                    // Check new container+host pairs format first
                    if (rule.containers && rule.containers.length > 0) {
                        return rule.containers.some(c =>
                            c.container_name === container.name && c.host_id === container.host_id
                        );
                    }
                    return false;
                });
                
                // Populate container details
                const detailsHtml = `
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 20px;">
                        <div>
                            <strong>Name:</strong> ${container.name}<br>
                            <strong>ID:</strong> ${container.short_id}<br>
                            <strong>Image:</strong> ${container.image}<br>
                        </div>
                        <div>
                            <strong>State:</strong> <span class="${getStateClass(container.state)}">${container.state}</span><br>
                            <strong>Host:</strong> ${container.host_name}<br>
                            <strong>Created:</strong> ${new Date(container.created).toLocaleString()}<br>
                        </div>
                    </div>
                    <div class="container-actions" style="display: flex; gap: 10px; flex-wrap: wrap;" id="container-actions-${container.short_id}">
                        ${container.state === 'running' ? `
                            <button class="btn btn-danger" id="container-state-btn-${container.short_id}" onclick="stopContainer('${container.host_id}', '${container.id}')">
                                <i data-lucide="square"></i> Stop Container
                            </button>
                        ` : `
                            <button class="btn btn-primary" id="container-state-btn-${container.short_id}" onclick="startContainer('${container.host_id}', '${container.id}')">
                                <i data-lucide="play"></i> Start Container
                            </button>
                        `}
                        <button class="btn btn-secondary" onclick="restartContainer('${container.host_id}', '${container.id}')">
                            <i data-lucide="rotate-cw"></i> Restart Container
                        </button>
                        <button class="btn btn-secondary" onclick="createAlertForContainer('${container.id}')">
                            <i data-lucide="zap"></i> ${hasAlert ? 'Edit Alert' : 'Create Alert'}
                        </button>
                        <div class="auto-restart-toggle ${container.auto_restart ? 'enabled' : ''}"
                             onclick="toggleAutoRestart('${container.host_id}', '${container.id}', event)">
                            <span><i data-lucide="rotate-cw" style="width:14px;height:14px;"></i> Auto-restart: ${container.auto_restart ? 'ON' : 'OFF'}</span>
                        </div>
                    </div>
                    <div id="container-recent-events" style="margin-top: 20px;">
                        <div style="color: var(--text-tertiary); font-size: 14px;">Loading recent events...</div>
                    </div>
                `;

                document.getElementById('container-info-content').innerHTML = detailsHtml;

                // Load recent events for this container
                loadContainerRecentEvents(container.name, container.host_id);

                // Initialize Lucide icons after content is added
                initIcons();

                // Show modal
                const modal = document.getElementById('containerModal');
                modal.classList.add('active');

                // Load saved preferences or reset modal position
                const modalContent = modal.querySelector('.modal-content');
                if (modalContent) {
                    const savedPrefs = loadModalPreferences();
                    if (!savedPrefs) {
                        // No saved preferences, use defaults
                        modalContent.style.width = '900px';
                        modalContent.style.height = '600px';
                        modalContent.style.transform = 'translate(0, 0)';
                    }
                }

                // Make modal draggable
                makeModalDraggable('containerModal');

                // Add resize observer to adjust logs height and save preferences when modal is resized
                const resizeObserver = new ResizeObserver(entries => {
                    for (let entry of entries) {
                        if (entry.target.classList.contains('modal-content')) {
                            adjustLogsHeight();
                            // Save size after resize (debounced)
                            clearTimeout(window.resizeSaveTimeout);
                            window.resizeSaveTimeout = setTimeout(saveModalPreferences, 500);
                        }
                    }
                });
                resizeObserver.observe(modalContent);

                // Store observer for cleanup
                if (!window.modalResizeObserver) {
                    window.modalResizeObserver = resizeObserver;
                } else {
                    // Disconnect previous observer if it exists
                    window.modalResizeObserver.disconnect();
                    window.modalResizeObserver = resizeObserver;
                }

                // Show the appropriate tab
                if (preserveTab) {
                    // Preserve the current tab selection
                    showTab(preserveTab);
                } else {
                    // Show info tab by default for new modal opens
                    showTab('info');
                }
            }
        }

        // Container Modal Functions
        function showTab(tab) {
            // Hide all tabs
            document.querySelectorAll('.tab-content').forEach(content => {
                content.style.display = 'none';
            });

            // Remove active class from all tab buttons
            document.querySelectorAll('[id^="tab-"]').forEach(btn => {
                btn.classList.remove('btn-primary');
                btn.classList.add('btn-secondary');
            });

            // Show selected tab
            document.getElementById(`${tab}-tab`).style.display = 'block';
            document.getElementById(`tab-${tab}`).classList.remove('btn-secondary');
            document.getElementById(`tab-${tab}`).classList.add('btn-primary');

            // Adjust logs height when switching to logs tab
            if (tab === 'logs') {
                // Check for saved logs height preference
                const saved = localStorage.getItem('containerModalPrefs');
                if (saved) {
                    try {
                        const prefs = JSON.parse(saved);
                        const logsDiv = document.getElementById('container-logs');
                        if (prefs.logsHeight && logsDiv) {
                            logsDiv.style.height = prefs.logsHeight;
                        } else {
                            adjustLogsHeight();
                        }
                    } catch (e) {
                        adjustLogsHeight();
                    }
                } else {
                    adjustLogsHeight();
                }
            }

            // Auto-fetch logs when logs tab is opened
            if (tab === 'logs' && window.currentContainer) {
                fetchContainerLogs();
                // Start auto-refresh if checkbox is checked
                const autoRefresh = document.getElementById('autoRefreshLogs');
                if (autoRefresh && autoRefresh.checked && !logPollInterval) {
                    startAutoRefresh();
                }

                // Add keyboard shortcut for filter (Ctrl/Cmd + F)
                if (!window.logFilterKeyHandler) {
                    window.logFilterKeyHandler = function(e) {
                        const logsTabVisible = document.getElementById('logs-tab').style.display !== 'none';
                        const modalActive = document.getElementById('containerModal').classList.contains('active');

                        if (modalActive && logsTabVisible && (e.ctrlKey || e.metaKey) && e.key === 'f') {
                            e.preventDefault();
                            const filterInput = document.getElementById('logSearchFilter');
                            if (filterInput) {
                                filterInput.focus();
                                filterInput.select();
                            }
                        }
                    };
                    document.addEventListener('keydown', window.logFilterKeyHandler);
                }
            } else if (tab !== 'logs') {
                // Stop auto-refresh when leaving logs tab
                stopAutoRefresh();
            }
            
            // Clear log stream if switching away from logs
            if (tab !== 'logs' && window.logStreamWs) {
                window.logStreamWs.close();
                window.logStreamWs = null;
                document.getElementById('streamLogsBtn').textContent = 'Start Live Stream';
            }
        }

        async function fetchContainerLogs(incremental = false) {
            if (!window.currentContainer) return;

            const tailCount = document.getElementById('logTailCount').value || 100;
            const logsDiv = document.getElementById('container-logs');

            // Only show loading on first fetch
            if (!incremental || !accumulatedLogs.length) {
                logsDiv.innerHTML = '<div style="color: var(--text-secondary);">Loading logs...</div>';
                lastLogTimestamp = null;
                accumulatedLogs = [];
            }

            try {
                // Build URL with optional since parameter for incremental updates
                let url = `${API_BASE}/api/hosts/${window.currentContainer.host_id}/containers/${window.currentContainer.id}/logs?tail=${tailCount}`;
                if (incremental && lastLogTimestamp) {
                    url += `&since=${encodeURIComponent(lastLogTimestamp)}`;
                }

                // Increase timeout for large log fetches
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), 30000); // 30 second timeout

                const response = await fetch(url, { signal: controller.signal });

                clearTimeout(timeoutId);

                if (response.ok) {
                    const data = await response.json();

                    // Update timestamp for next incremental fetch
                    if (data.last_timestamp) {
                        lastLogTimestamp = data.last_timestamp;
                    }

                    if (data.logs && Array.isArray(data.logs)) {
                        // Always replace logs for simplicity and to avoid duplicates
                        // Auto-refresh will just keep fetching the latest N logs
                        // API returns array of {timestamp, log} objects
                        accumulatedLogs = data.logs
                            .filter(entry => entry && entry.log && entry.log.trim())
                            .map(entry => entry.log);

                        updateLogDisplay();
                        // Auto-scroll to bottom only if no filter is active
                        const filterText = document.getElementById('logSearchFilter')?.value || '';
                        if (!filterText) {
                            logsDiv.scrollTop = logsDiv.scrollHeight;
                        }
                    } else {
                        logsDiv.innerHTML = '<div style="color: var(--text-tertiary);">No logs available</div>';
                    }
                } else {
                    logsDiv.innerHTML = '<div style="color: var(--danger);">Failed to fetch logs</div>';
                    stopAutoRefresh();
                }
            } catch (error) {
                console.error('Error fetching logs:', error);
                if (error.name === 'AbortError') {
                    logsDiv.innerHTML = '<div style="color: var(--danger);">Log fetch timeout - try reducing the log count</div>';
                } else {
                    logsDiv.innerHTML = '<div style="color: var(--danger);">Error loading logs</div>';
                }
                stopAutoRefresh();
            }
        }

        // Portainer-style HTTP polling for logs (more reliable than WebSocket)
        let logPollInterval = null;
        let lastLogTimestamp = null;
        let accumulatedLogs = [];

        function toggleAutoRefresh() {
            const checkbox = document.getElementById('autoRefreshLogs');
            if (checkbox.checked) {
                startAutoRefresh();
            } else {
                stopAutoRefresh();
            }
        }

        function startAutoRefresh() {
            if (logPollInterval || !window.currentContainer) return;

            // Poll every 2 seconds
            logPollInterval = setInterval(() => {
                // Don't use incremental updates - just refresh with the same tail count
                // This avoids duplicate/accumulation issues
                fetchContainerLogs(false);
            }, 2000);
        }

        function stopAutoRefresh() {
            if (logPollInterval) {
                clearInterval(logPollInterval);
                logPollInterval = null;
            }
        }

        function updateLogDisplay() {
            const logsDiv = document.getElementById('container-logs');
            if (!logsDiv || !accumulatedLogs.length) {
                const matchCount = document.getElementById('logMatchCount');
                if (matchCount) matchCount.textContent = '';
                return;
            }

            const showTimestamps = document.getElementById('showTimestamps').checked;
            const filterText = document.getElementById('logSearchFilter')?.value.toLowerCase() || '';
            let displayLogs = accumulatedLogs;

            // Remove timestamps if needed
            if (!showTimestamps) {
                displayLogs = displayLogs.map(line => {
                    // Match various timestamp formats at the beginning of the line
                    return line.replace(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?\s*/, '');
                });
            }

            // Apply filter
            let filteredLogs = displayLogs;
            let matchCount = 0;
            if (filterText) {
                filteredLogs = displayLogs.filter(line => {
                    const matches = line.toLowerCase().includes(filterText);
                    if (matches) matchCount++;
                    return matches;
                });
            } else {
                matchCount = displayLogs.length;
            }

            // Update match count - only show when filtering
            const matchCountElem = document.getElementById('logMatchCount');
            if (matchCountElem) {
                if (filterText) {
                    matchCountElem.textContent = `${matchCount} matches`;
                } else {
                    matchCountElem.textContent = ''; // Don't show count when not filtering
                }
            }

            // Display logs with optional highlighting
            if (filterText && filteredLogs.length > 0) {
                // Escape special regex characters in search text
                const escapedFilter = filterText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                const regex = new RegExp(`(${escapedFilter})`, 'gi');

                const highlightedLogs = filteredLogs.map(line => {
                    // HTML escape the line first
                    const escaped = line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                    // Then add highlighting
                    return escaped.replace(regex, '<mark style="background: #ffeb3b; color: #000; padding: 2px;">$1</mark>');
                });
                logsDiv.innerHTML = highlightedLogs.join('\n') || '<div style="color: var(--text-tertiary);">No matching logs found</div>';
            } else if (filterText && filteredLogs.length === 0) {
                logsDiv.innerHTML = '<div style="color: var(--text-tertiary);">No logs match the filter</div>';
            } else {
                // HTML escape for safety
                const escapedLogs = filteredLogs.map(line =>
                    line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                );
                logsDiv.innerHTML = escapedLogs.join('\n') || '<div style="color: var(--text-tertiary);">No logs available</div>';
            }

            // Keep scroll at bottom if we were already at bottom
            if (logsDiv.scrollHeight - logsDiv.scrollTop <= logsDiv.clientHeight + 50) {
                logsDiv.scrollTop = logsDiv.scrollHeight;
            }
        }

        function clearLogFilter() {
            const filterInput = document.getElementById('logSearchFilter');
            if (filterInput) {
                filterInput.value = '';
                updateLogDisplay();
                filterInput.focus();
            }
        }

        function adjustLogsHeight() {
            const modal = document.querySelector('#containerModal .modal-content');
            const logsDiv = document.getElementById('container-logs');
            const logsTab = document.getElementById('logs-tab');

            if (modal && logsDiv && logsTab && logsTab.style.display !== 'none') {
                // Calculate available height for logs
                const modalHeight = modal.offsetHeight;
                const headerHeight = modal.querySelector('.modal-header').offsetHeight || 60;
                const tabsHeight = 120; // Approximate height of tabs and controls
                const padding = 120; // Extra padding

                const availableHeight = modalHeight - headerHeight - tabsHeight - padding;
                if (availableHeight > 200) {
                    logsDiv.style.height = `${Math.min(availableHeight, 600)}px`;
                }
            }
        }

        // Old toggleLogStream function removed - replaced with auto-refresh checkbox

        // Container exec functionality removed for security reasons
        // Users should use direct SSH, Docker CLI, or other appropriate tools for container access

        async function restartContainer(hostId, containerId) {
            try {
                const response = await fetch(`${API_BASE}/api/hosts/${hostId}/containers/${containerId}/restart`, {
                    method: 'POST'
                });
                
                if (response.ok) {
                    showToast('🔄 Container restarting...');
                } else {
                    showToast('❌ Failed to restart container');
                }
            } catch (error) {
                console.error('Error restarting container:', error);
                showToast('❌ Failed to restart container');
            }
        }

        async function startContainer(hostId, containerId) {
            // Find container to update UI immediately
            const container = containers.find(c => c.id === containerId);
            if (container) {
                // Update button immediately to show transitional state
                const btn = document.getElementById(`container-state-btn-${container.short_id}`);
                if (btn) {
                    btn.innerHTML = '<i data-lucide="rotate-cw"></i> Starting...';
                    btn.className = 'btn';
                    btn.style.backgroundColor = '#90ee90';
                    btn.style.color = '#333';
                    btn.disabled = true;
                    initIcons();
                }
            }

            try {
                const response = await fetch(`${API_BASE}/api/hosts/${hostId}/containers/${containerId}/start`, {
                    method: 'POST'
                });

                if (response.ok) {
                    showToast('▶️ Container starting...');
                } else {
                    showToast('❌ Failed to start container');
                    // Revert button state on failure
                    if (container) {
                        const btn = document.getElementById(`container-state-btn-${container.short_id}`);
                        if (btn) {
                            btn.innerHTML = '<i data-lucide="play"></i> Start Container';
                            btn.className = 'btn btn-primary';
                            btn.style.backgroundColor = '';
                            btn.style.color = '';
                            btn.disabled = false;
                        }
                    }
                }
            } catch (error) {
                console.error('Error starting container:', error);
                showToast('❌ Failed to start container');
                // Revert button state on error
                if (container) {
                    const btn = document.getElementById(`container-state-btn-${container.short_id}`);
                    if (btn) {
                        btn.innerHTML = '<i data-lucide="play"></i> Start Container';
                        btn.className = 'btn btn-primary';
                        btn.style.backgroundColor = '';
                        btn.style.color = '';
                        btn.disabled = false;
                        initIcons();
                    }
                }
            }
        }

        async function loadContainerRecentEvents(containerName, hostId) {
            try {
                // Fetch last 7 events for this container
                const response = await fetch(`${API_BASE}/api/events?limit=7&container_name=${encodeURIComponent(containerName)}&host_id=${hostId}&hours=168`);
                const data = await response.json();

                const eventsDiv = document.getElementById('container-recent-events');
                if (!eventsDiv) return;

                if (!data.events || data.events.length === 0) {
                    eventsDiv.innerHTML = `
                        <div style="border-top: 1px solid var(--border); padding-top: 15px; margin-top: 15px;">
                            <strong style="color: var(--text-primary); font-size: 14px;">Recent Events</strong>
                            <div style="color: var(--text-tertiary); font-size: 13px; margin-top: 8px;">No recent events</div>
                        </div>
                    `;
                    return;
                }

                // Build events list
                let eventsHtml = `
                    <div style="border-top: 1px solid var(--border); padding-top: 15px; margin-top: 15px;">
                        <strong style="color: var(--text-primary); font-size: 14px; margin-bottom: 10px; display: block;">Recent Events</strong>
                        <div style="display: flex; flex-direction: column; gap: 4px;">
                `;

                data.events.forEach(event => {
                    // Ensure timestamp is treated as UTC if no timezone info
                    let timestampStr = event.timestamp;
                    if (!timestampStr.includes('+') && !timestampStr.endsWith('Z')) {
                        timestampStr += 'Z';  // Treat as UTC
                    }
                    const timestamp = new Date(timestampStr).toLocaleString('en-US', {
                        month: '2-digit',
                        day: '2-digit',
                        year: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit',
                        hour12: true
                    });

                    // Get severity color
                    let severityColor = 'var(--primary)';
                    if (event.severity === 'critical') severityColor = '#DC2626';
                    else if (event.severity === 'error') severityColor = 'var(--danger)';
                    else if (event.severity === 'warning') severityColor = 'var(--warning)';

                    // Build event message
                    let eventText = event.title || event.message;
                    if (event.message && event.message !== event.title) {
                        const stateChangeMatch = event.message.match(/state changed from (\w+) to (\w+)/i);
                        if (stateChangeMatch) {
                            const fromState = stateChangeMatch[1];
                            const toState = stateChangeMatch[2];
                            const userAction = event.message.includes('(user action)') ? ' <span style="color: var(--text-secondary);">(user action)</span>' : '';

                            // Get state colors
                            const getStateColor = (state) => {
                                switch(state.toLowerCase()) {
                                    case 'running': return '#10B981';
                                    case 'exited': return '#EF4444';
                                    case 'stopped': return '#F59E0B';
                                    case 'paused': return '#F59E0B';
                                    case 'restarting': return '#3B82F6';
                                    case 'dead': return '#DC2626';
                                    default: return 'var(--text-tertiary)';
                                }
                            };

                            eventText = `State changed from <span style="color: ${getStateColor(fromState)}; font-weight: 500;">${fromState}</span> to <span style="color: ${getStateColor(toState)}; font-weight: 500;">${toState}</span>${userAction}`;
                        }
                    }

                    eventsHtml += `
                        <div style="display: flex; align-items: flex-start; gap: 10px; font-size: 13px;">
                            <span style="color: var(--text-tertiary); flex-shrink: 0; font-size: 12px;">${timestamp}</span>
                            <span style="color: ${severityColor}; flex-shrink: 0; min-width: 80px; font-size: 12px;">level=${event.severity}</span>
                            <span style="color: var(--text-primary); flex: 1;">${eventText}</span>
                        </div>
                    `;
                });

                eventsHtml += `
                        </div>
                    </div>
                `;

                eventsDiv.innerHTML = eventsHtml;
            } catch (error) {
                console.error('Error loading container events:', error);
                const eventsDiv = document.getElementById('container-recent-events');
                if (eventsDiv) {
                    eventsDiv.innerHTML = `
                        <div style="border-top: 1px solid var(--border); padding-top: 15px; margin-top: 15px;">
                            <strong style="color: var(--text-primary); font-size: 14px;">Recent Events</strong>
                            <div style="color: var(--danger); font-size: 13px; margin-top: 8px;">Failed to load events</div>
                        </div>
                    `;
                }
            }
        }

        async function stopContainer(hostId, containerId) {
            // Find container to update UI immediately
            const container = containers.find(c => c.id === containerId);
            if (container) {
                // Update button immediately to show transitional state
                const btn = document.getElementById(`container-state-btn-${container.short_id}`);
                if (btn) {
                    btn.innerHTML = '<i data-lucide="rotate-cw"></i> Stopping...';
                    btn.className = 'btn';
                    btn.style.backgroundColor = '#ffa500';
                    btn.style.color = '#fff';
                    btn.disabled = true;
                    initIcons();
                }
            }

            try {
                const response = await fetch(`${API_BASE}/api/hosts/${hostId}/containers/${containerId}/stop`, {
                    method: 'POST'
                });

                if (response.ok) {
                    showToast('⏹️ Container stopping...');
                } else {
                    showToast('❌ Failed to stop container');
                    // Revert button state on failure
                    if (container) {
                        const btn = document.getElementById(`container-state-btn-${container.short_id}`);
                        if (btn) {
                            btn.innerHTML = '<i data-lucide="square"></i> Stop Container';
                            btn.className = 'btn btn-danger';
                            btn.style.backgroundColor = '';
                            btn.style.color = '';
                            btn.disabled = false;
                        }
                    }
                }
            } catch (error) {
                console.error('Error stopping container:', error);
                showToast('❌ Failed to stop container');
                // Revert button state on error
                if (container) {
                    const btn = document.getElementById(`container-state-btn-${container.short_id}`);
                    if (btn) {
                        btn.innerHTML = '<i data-lucide="square"></i> Stop Container';
                        btn.className = 'btn btn-danger';
                        btn.style.backgroundColor = '';
                        btn.style.color = '';
                        btn.disabled = false;
                        initIcons();
                    }
                }
            }
        }

        function showToast(message) {
            const toast = document.getElementById('toast');
            toast.textContent = message;
            toast.classList.add('show');
            setTimeout(() => {
                toast.classList.remove('show');
            }, 3000);
        }



        // Initialize on load
        window.addEventListener('DOMContentLoaded', async () => {
            try {
                // Initialize Lucide icons in static HTML
                initIcons();

                await init();
                // Check if password change is required
                checkPasswordChangeRequired();
                // Get current user info
                await getCurrentUser();
                // Dashboard will be initialized when WebSocket data arrives
                // or when user navigates to dashboard page
            } catch (error) {
                console.error('Failed to initialize application:', error);
                // Don't show error toast - WebSocket will handle data delivery
            }
        });

        // Mobile Bottom Navigation
        document.addEventListener('DOMContentLoaded', function() {
            const mobileNavItems = document.querySelectorAll('.mobile-nav-item');
            const moreMenu = document.querySelector('.more-menu');
            const moreNavItem = document.querySelector('.mobile-nav-item[data-page="more"]');

            // Handle navigation clicks
            mobileNavItems.forEach(item => {
                item.addEventListener('click', function(e) {
                    const page = this.dataset.page;

                    if (page === 'more') {
                        // Toggle more menu
                        e.stopPropagation();
                        moreMenu.classList.toggle('show');
                        return;
                    }

                    // Handle regular navigation
                    if (page) {
                        switchPage(page);
                    }

                    // Update active state
                    mobileNavItems.forEach(nav => nav.classList.remove('active'));
                    this.classList.add('active');

                    // Hide more menu if open
                    moreMenu.classList.remove('show');
                });
            });

            // Handle more menu clicks
            document.querySelectorAll('.more-menu-item').forEach(item => {
                item.addEventListener('click', function(e) {
                    const page = this.dataset.page;
                    if (page) {
                        setActivePage(page);
                        moreMenu.classList.remove('show');

                        // Update active state for the more button
                        mobileNavItems.forEach(nav => nav.classList.remove('active'));
                        moreNavItem.classList.add('active');
                    }
                });
            });

            // Close more menu when clicking outside
            document.addEventListener('click', function(e) {
                if (!moreNavItem.contains(e.target)) {
                    moreMenu.classList.remove('show');
                }
            });

            // Map mobile nav pages to existing navigation
            function setActivePage(page) {
                // Use the existing navigation system
                const navItem = document.querySelector(`.nav-item[data-page="${page}"]`);
                if (navItem) {
                    navItem.click();
                } else {
                    // Fallback for pages that might not have nav items
                    switch(page) {
                        case 'dashboard':
                            showSection('dashboard');
                            break;
                        case 'hosts':
                            showSection('hosts');
                            break;
                        case 'alerts':
                            showSection('alerts');
                            break;
                        case 'settings':
                            showSection('settings');
                            break;
                        case 'notifications':
                            showSection('notifications');
                            break;
                        case 'account':
                            showSection('account');
                            break;
                    }
                }
            }
        });
