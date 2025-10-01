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
        function switchPage(page) {
            // Update active nav item
            document.querySelectorAll('.nav-item').forEach(item => {
                item.classList.remove('active');
            });
            event.currentTarget.classList.add('active');

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
                        const checkData = setInterval(() => {
                            if (hosts.length > 0) {
                                clearInterval(checkData);
                                setTimeout(() => initDashboard(), 100);
                            }
                        }, 100);
                        // Timeout after 5 seconds and initialize anyway
                        setTimeout(() => {
                            clearInterval(checkData);
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
            
            currentPage = page;
            
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
                            <div class="auto-restart-toggle ${container.auto_restart ? 'enabled' : ''}" 
                                 onclick="event.stopPropagation()">
                                <span>🔄 Auto</span>
                                <div class="toggle-switch ${container.auto_restart ? 'active' : ''}" 
                                     onclick="toggleAutoRestart('${container.host_id}', '${container.short_id}', event)"></div>
                            </div>
                            <span class="container-state ${getStateClass(container.state)}">
                                ${container.state}
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
                            <button class="btn-icon" onclick="editHost('${host.id}')"><i data-lucide="edit"></i></button>
                            <button class="btn-icon" onclick="deleteHost('${host.id}')"><i data-lucide="trash-2"></i></button>
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

        async function populateNotificationChannels() {
            try {
                const response = await fetch(`${API_BASE}/api/notifications/channels`, {
                    credentials: 'include'
                });
                const channels = await response.json();

                const channelsSection = document.getElementById('notificationChannelsSection');

                if (channels && channels.length > 0) {
                    // Show available channels as checkboxes
                    let channelsHtml = '<div class="checkbox-group">';
                    channels.forEach(channel => {
                        channelsHtml += `
                            <label class="checkbox-item">
                                <input type="checkbox" name="channels" value="${channel.id}" data-channel-id="${channel.id}">
                                ${channel.name}
                            </label>
                        `;
                    });
                    channelsHtml += '</div>';

                    channelsSection.innerHTML = channelsHtml;
                } else {
                    // No channels configured yet
                    channelsSection.innerHTML = `
                        <p style="color: var(--text-tertiary); font-size: 14px; margin-bottom: 15px;">
                            No notification channels configured yet. Set up Discord, Telegram, or Pushover to receive alerts.
                        </p>
                        <button type="button" class="btn btn-secondary" onclick="openNotificationSettings()">
                            Configure Channels
                        </button>
                    `;
                }
            } catch (error) {
                console.error('Error fetching notification channels:', error);
                const channelsSection = document.getElementById('notificationChannelsSection');
                channelsSection.innerHTML = `
                    <p style="color: var(--text-tertiary); font-size: 14px; margin-bottom: 15px;">
                        Configure notification channels first in Settings to enable alerts.
                    </p>
                    <button type="button" class="btn btn-secondary" onclick="openNotificationSettings()">
                        Configure Channels
                    </button>
                `;
            }
        }

        let notificationChannels = [];
        let templateVariables = {};

        async function openNotificationSettings() {
            try {
                await loadNotificationChannels();
                await loadNotificationTemplate();
                await loadTemplateVariables();
                await fetchSettings(); // Load settings including blackout windows
                document.getElementById('notificationModal').classList.add('active');
            } catch (error) {
                console.error('Error opening notification settings:', error);
                showToast('Failed to open notification settings', 'error');
            }
        }

        function switchNotificationTab(tab) {
            const channelsTab = document.getElementById('channelsTab');
            const templateTab = document.getElementById('templateTab');
            const blackoutTab = document.getElementById('blackoutTab');
            const channelsContent = document.getElementById('channelsTabContent');
            const templateContent = document.getElementById('templateTabContent');
            const blackoutContent = document.getElementById('blackoutTabContent');

            // Reset all tabs
            [channelsTab, templateTab, blackoutTab].forEach(btn => {
                btn.classList.remove('active');
                btn.style.borderBottom = 'none';
                btn.style.color = 'var(--text-secondary)';
            });

            // Hide all content
            [channelsContent, templateContent, blackoutContent].forEach(content => {
                if (content) content.style.display = 'none';
            });

            // Show selected tab
            if (tab === 'channels') {
                channelsTab.classList.add('active');
                channelsTab.style.borderBottom = '2px solid var(--primary)';
                channelsTab.style.color = 'var(--primary)';
                channelsContent.style.display = 'block';
            } else if (tab === 'template') {
                templateTab.classList.add('active');
                templateTab.style.borderBottom = '2px solid var(--primary)';
                templateTab.style.color = 'var(--primary)';
                templateContent.style.display = 'block';
            } else if (tab === 'blackout') {
                blackoutTab.classList.add('active');
                blackoutTab.style.borderBottom = '2px solid var(--primary)';
                blackoutTab.style.color = 'var(--primary)';
                blackoutContent.style.display = 'block';
                // Load blackout status and show timezone info when switching to this tab
                renderBlackoutWindows();
                updateBlackoutStatus();
                updateTimezoneInfo();
            }
        }

        function updateTimezoneInfo() {
            const offsetElement = document.getElementById('localTimezoneOffset');
            if (offsetElement) {
                const offsetMinutes = new Date().getTimezoneOffset();
                const offsetHours = Math.abs(offsetMinutes / 60);
                const offsetSign = offsetMinutes > 0 ? '-' : '+';
                offsetElement.textContent = `UTC${offsetSign}${offsetHours}`;
            }
        }

        async function loadNotificationChannels() {
            try {
                const response = await fetch(`${API_BASE}/api/notifications/channels`, {
                    credentials: 'include'
                });
                notificationChannels = await response.json();
                renderNotificationChannels();
            } catch (error) {
                console.error('Error loading notification channels:', error);
                notificationChannels = [];
            }
        }

        async function loadNotificationTemplate() {
            try {
                const response = await fetch(`${API_BASE}/api/settings`, {
                    credentials: 'include'
                });
                const settings = await response.json();
                const template = settings.alert_template || '';
                document.getElementById('alertTemplate').value = template;
            } catch (error) {
                console.error('Error loading template:', error);
            }
        }

        async function loadTemplateVariables() {
            try {
                const response = await fetch(`${API_BASE}/api/notifications/template-variables`, {
                    credentials: 'include'
                });
                templateVariables = await response.json();
            } catch (error) {
                console.error('Error loading template variables:', error);
            }
        }

        function renderNotificationChannels() {
            const container = document.getElementById('notificationChannelsList');
            if (!container) return;

            if (notificationChannels.length === 0) {
                container.innerHTML = `
                    <div style="text-align: center; padding: var(--spacing-lg); color: var(--text-secondary);">
                        No notification channels configured yet. Click "Add Channel" to get started.
                    </div>
                `;
                return;
            }

            container.innerHTML = notificationChannels.map((channel, index) => `
                <div class="notification-channel-card" style="padding: var(--spacing-md); margin-bottom: var(--spacing-md); background: var(--surface); border: 1px solid var(--surface-light); border-radius: var(--radius-md);">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--spacing-md);">
                        <h4 style="color: var(--text-primary); margin: 0;">${channel.name || 'Unnamed Channel'}</h4>
                        <div style="display: flex; gap: var(--spacing-sm);">
                            <button type="button" class="btn btn-small ${channel.enabled ? 'btn-success' : 'btn-secondary'}" onclick="toggleChannelStatus(${index})">
                                ${channel.enabled ? '✓ Enabled' : 'Disabled'}
                            </button>
                            <button type="button" class="btn-icon" onclick="removeChannel(${index})">
                                <i data-lucide="trash-2"></i>
                            </button>
                        </div>
                    </div>
                    <div style="display: grid; gap: var(--spacing-sm);">
                        <label class="form-label">Channel Type</label>
                        ${channel.id ?
                            `<input type="text" class="form-input" value="${channel.type.charAt(0).toUpperCase() + channel.type.slice(1)}" disabled style="background: var(--surface-light); cursor: not-allowed;">`
                            :
                            `<select class="form-input" onchange="updateChannelType(${index}, this.value)">
                                ${getAvailableChannelTypes(channel.type).map(type => `<option value="${type}" ${channel.type === type ? 'selected' : ''}>${type.charAt(0).toUpperCase() + type.slice(1)}</option>`).join('')}
                            </select>`
                        }
                        ${renderChannelConfig(channel, index)}
                    </div>
                    <div style="display: flex; gap: var(--spacing-sm); margin-top: var(--spacing-md);">
                        <button type="button" class="btn btn-primary btn-small" onclick="saveChannel(${index})">
                            <i data-lucide="save"></i> Save Channel
                        </button>
                        <button type="button" class="btn btn-secondary btn-small" onclick="testChannel(${index})">
                            <i data-lucide="bell"></i> Test Channel
                        </button>
                    </div>
                </div>
            `).join('');
            initIcons();
        }

        function renderChannelConfig(channel, index) {
            switch(channel.type) {
                case 'discord':
                    return `
                        <label class="form-label">Webhook URL</label>
                        <input type="text" class="form-input" placeholder="https://discord.com/api/webhooks/..."
                               value="${channel.config?.webhook_url || ''}"
                               onchange="updateChannelConfig(${index}, 'webhook_url', this.value)">
                    `;
                case 'slack':
                    return `
                        <label class="form-label">Webhook URL</label>
                        <input type="text" class="form-input" placeholder="https://hooks.slack.com/services/..."
                               value="${channel.config?.webhook_url || ''}"
                               onchange="updateChannelConfig(${index}, 'webhook_url', this.value)">
                    `;
                case 'telegram':
                    return `
                        <label class="form-label">Bot Token</label>
                        <input type="text" class="form-input" placeholder="Bot token from @BotFather"
                               value="${channel.config?.bot_token || ''}"
                               onchange="updateChannelConfig(${index}, 'bot_token', this.value)">
                        <label class="form-label">Chat ID</label>
                        <input type="text" class="form-input" placeholder="Chat ID"
                               value="${channel.config?.chat_id || ''}"
                               onchange="updateChannelConfig(${index}, 'chat_id', this.value)">
                    `;
                case 'pushover':
                    return `
                        <label class="form-label">App Token</label>
                        <input type="text" class="form-input" placeholder="Pushover app token"
                               value="${channel.config?.app_token || ''}"
                               onchange="updateChannelConfig(${index}, 'app_token', this.value)">
                        <label class="form-label">User Key</label>
                        <input type="text" class="form-input" placeholder="User key"
                               value="${channel.config?.user_key || ''}"
                               onchange="updateChannelConfig(${index}, 'user_key', this.value)">
                    `;
                default:
                    return '';
            }
        }

        function addNotificationChannel() {
            // Get available channel types (those not already in use)
            const usedTypes = notificationChannels.map(ch => ch.type);
            const availableTypes = ['discord', 'slack', 'telegram', 'pushover'].filter(type => !usedTypes.includes(type));

            if (availableTypes.length === 0) {
                showToast('❌ All notification channel types are already configured');
                return;
            }

            // Use the first available type
            const channelType = availableTypes[0];
            const channelName = channelType.charAt(0).toUpperCase() + channelType.slice(1);

            const newChannel = {
                name: channelName,
                type: channelType,
                config: {},
                enabled: true,
                isNew: true
            };
            notificationChannels.push(newChannel);
            renderNotificationChannels();

            // Scroll to the newly added channel
            setTimeout(() => {
                const cards = document.querySelectorAll('.notification-channel-card');
                if (cards.length > 0) {
                    const lastCard = cards[cards.length - 1];
                    lastCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }
            }, 100);
        }

        async function removeChannel(index) {
            const channel = notificationChannels[index];

            // If channel doesn't exist in backend, just remove from local array
            if (!channel.id) {
                notificationChannels.splice(index, 1);
                renderNotificationChannels();
                return;
            }

            // Check for dependent alerts first
            try {
                const dependentAlerts = await checkDependentAlerts(channel.id);

                let message = `Are you sure you want to delete the notification channel <strong>"${channel.name}"</strong>?<br><br>`;

                message += `Any alerts that only use this notification channel will also be deleted.<br><br>`;

                if (dependentAlerts.length > 0) {
                    message += `⚠️ <strong>Warning:</strong> The following alert rules will be deleted:<br>`;
                    message += '<ul style="margin: var(--spacing-sm) 0; padding-left: var(--spacing-lg);">';
                    dependentAlerts.forEach(alert => {
                        message += `<li>${alert.name}</li>`;
                    });
                    message += '</ul>';
                }

                message += `<strong>This action cannot be undone.</strong>`;

                showConfirmation('Delete Notification Channel', message, 'Delete Channel', async () => {
                    try {
                        // Delete from backend
                        const response = await fetch(`${API_BASE}/api/notifications/channels/${channel.id}`, {
                            method: 'DELETE',
                            credentials: 'include'
                        });

                        if (!response.ok) {
                            throw new Error('Failed to delete channel');
                        }

                        const result = await response.json();
                        if (result.deleted_alerts && result.deleted_alerts.length > 0) {
                            showToast(`✅ Channel deleted (${result.deleted_alerts.length} alert(s) also removed)`);
                        } else {
                            showToast('✅ Channel deleted');
                        }

                        // Remove from local array and re-render
                        notificationChannels.splice(index, 1);
                        renderNotificationChannels();

                        // Refresh alert modal if open
                        await populateNotificationChannels();

                        // Refresh alert rules list if it's currently displayed
                        await fetchAlertRules();
                        renderAlertRules();
                    } catch (error) {
                        console.error('Error deleting channel:', error);
                        showToast('❌ Failed to delete channel');
                    }
                });
            } catch (error) {
                console.error('Error checking dependent alerts:', error);
                showToast('❌ Failed to check dependent alerts');
            }
        }

        function toggleChannelStatus(index) {
            notificationChannels[index].enabled = !notificationChannels[index].enabled;
            renderNotificationChannels();
        }

        function getAvailableChannelTypes(currentType) {
            // Get all types that are either the current type or not already in use
            const usedTypes = notificationChannels.map(ch => ch.type);
            const allTypes = ['discord', 'slack', 'telegram', 'pushover'];
            return allTypes.filter(type => type === currentType || !usedTypes.includes(type));
        }

        function updateChannelType(index, type) {
            // Update the channel name to match the type
            notificationChannels[index].name = type.charAt(0).toUpperCase() + type.slice(1);
            notificationChannels[index].type = type;
            notificationChannels[index].config = {};
            renderNotificationChannels();
        }

        function updateChannelConfig(index, key, value) {
            if (!notificationChannels[index].config) {
                notificationChannels[index].config = {};
            }
            notificationChannels[index].config[key] = value;
        }

        async function saveAllChannels() {
            try {
                // Save each channel
                for (const channel of notificationChannels) {
                    if (channel.isNew) {
                        // Create new channel
                        await fetch(`${API_BASE}/api/notifications/channels`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            credentials: 'include',
                            body: JSON.stringify(channel)
                        });
                    } else if (channel.id) {
                        // Update existing channel
                        await fetch(`${API_BASE}/api/notifications/channels/${channel.id}`, {
                            method: 'PUT',
                            headers: { 'Content-Type': 'application/json' },
                            credentials: 'include',
                            body: JSON.stringify(channel)
                        });
                    }
                }
                showToast('✅ Notification channels saved successfully!');
                await loadNotificationChannels();

                // Refresh the alert modal's channel list if it's open
                await populateNotificationChannels();
            } catch (error) {
                console.error('Error saving channels:', error);
                showToast('❌ Failed to save notification channels');
            }
        }

        async function saveChannel(index) {
            try {
                const channel = notificationChannels[index];

                if (channel.isNew) {
                    // Create new channel
                    const response = await fetch(`${API_BASE}/api/notifications/channels`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'include',
                        body: JSON.stringify(channel)
                    });

                    if (response.ok) {
                        const savedChannel = await response.json();
                        // Update the channel with the returned ID and remove isNew flag
                        notificationChannels[index] = { ...savedChannel, isNew: false };
                        showToast('✅ Channel saved successfully!');
                    } else {
                        throw new Error('Failed to save channel');
                    }
                } else if (channel.id) {
                    // Update existing channel
                    const response = await fetch(`${API_BASE}/api/notifications/channels/${channel.id}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'include',
                        body: JSON.stringify(channel)
                    });

                    if (response.ok) {
                        showToast('✅ Channel updated successfully!');
                    } else {
                        throw new Error('Failed to update channel');
                    }
                }

                // Preserve unsaved channels (those with isNew flag)
                const unsavedChannels = notificationChannels.filter(ch => ch.isNew && ch !== channel);

                // Refresh the channels list from backend
                await loadNotificationChannels();

                // Re-add the unsaved channels
                notificationChannels.push(...unsavedChannels);
                renderNotificationChannels();

                // Refresh the alert modal's channel list if it's open
                await populateNotificationChannels();
            } catch (error) {
                console.error('Error saving channel:', error);
                showToast('❌ Failed to save channel');
            }
        }

        async function testChannel(index) {
            const channel = notificationChannels[index];
            if (!channel.id) {
                showToast('❌ Please save the channel first');
                return;
            }

            try {
                const response = await fetch(`${API_BASE}/api/notifications/channels/${channel.id}/test`, {
                    method: 'POST',
                    credentials: 'include'
                });

                if (response.ok) {
                    showToast('✅ Test notification sent!');
                } else {
                    showToast('❌ Failed to send test notification');
                }
            } catch (error) {
                console.error('Error testing channel:', error);
                showToast('❌ Failed to test channel');
            }
        }

        function applyTemplateExample(exampleKey) {
            if (!exampleKey || !templateVariables.examples) return;

            const examples = {
                'default': templateVariables.default_template,
                'simple': 'Alert: {CONTAINER_NAME} on {HOST_NAME} changed from {OLD_STATE} to {NEW_STATE}',
                'minimal': '{CONTAINER_NAME}: {NEW_STATE} at {TIME}',
                'emoji': '🔴 {CONTAINER_NAME} is {NEW_STATE}\\n📍 Host: {HOST_NAME}\\n🕐 Time: {TIMESTAMP}'
            };

            const template = examples[exampleKey];
            if (template) {
                document.getElementById('alertTemplate').value = template;
            }
        }

        async function saveNotificationTemplate() {
            try {
                const template = document.getElementById('alertTemplate').value;

                // Get current settings
                const response = await fetch(`${API_BASE}/api/settings`, {
                    credentials: 'include'
                });
                const settings = await response.json();

                // Update with new template
                settings.alert_template = template;

                const updateResponse = await fetch(`${API_BASE}/api/settings`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify(settings)
                });

                if (updateResponse.ok) {
                    showToast('✅ Notification template saved!');
                } else {
                    showToast('❌ Failed to save template');
                }
            } catch (error) {
                console.error('Error saving template:', error);
                showToast('❌ Failed to save notification template');
            }
        }

        async function loadNotificationSettings() {
            try {
                const response = await fetch(`${API_BASE}/api/notifications/channels`, {
                    credentials: 'include'
                });
                const channels = await response.json();

                // Clear existing values
                document.querySelectorAll('#notificationModal .form-input').forEach(input => {
                    input.value = '';
                });

                // Populate existing settings
                channels.forEach(channel => {
                    if (channel.type === 'telegram') {
                        const tokenInput = document.querySelector('#notificationModal .form-input[placeholder*="Telegram bot token"]');
                        const chatInput = document.querySelector('#notificationModal .form-input[placeholder*="chat ID"]');
                        if (tokenInput && chatInput && channel.config) {
                            tokenInput.value = channel.config.bot_token || '';
                            chatInput.value = channel.config.chat_id || '';
                        }
                    } else if (channel.type === 'discord') {
                        const webhookInput = document.querySelector('#notificationModal .form-input[placeholder*="Discord webhook"]');
                        if (webhookInput && channel.config) {
                            webhookInput.value = channel.config.webhook_url || '';
                        }
                    } else if (channel.type === 'pushover') {
                        const tokenInput = document.querySelector('#notificationModal .form-input[placeholder*="Pushover app token"]');
                        const userInput = document.querySelector('#notificationModal .form-input[placeholder*="user key"]');
                        if (tokenInput && userInput && channel.config) {
                            tokenInput.value = channel.config.app_token || '';
                            userInput.value = channel.config.user_key || '';
                        }
                    }
                });
            } catch (error) {
                console.error('Error loading notification settings:', error);
            }
        }

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
                console.error('Error opening alert rule for editing:', error);
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

                // Use the cleanup function
                if (window.cleanupLogStream) {
                    window.cleanupLogStream();
                }
                const streamBtn = document.getElementById('streamLogsBtn');
                if (streamBtn) {
                    streamBtn.textContent = 'Start Live Stream';
                }
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
                console.error('Error fetching user info:', error);
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

        async function logout() {
            try {
                const response = await fetch(`${API_BASE}/api/auth/logout`, {
                    method: 'POST',
                    credentials: 'include'
                });

                if (response.ok) {
                    window.location.href = '/login.html';
                }
            } catch (error) {
                console.error('Logout error:', error);
                showToast('❌ Failed to logout');
            }
        }

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
                    }

                    // Re-populate the modal with updated data (but preserve the tab)
                    showContainerDetails(updatedContainer.host_id, updatedContainer.short_id, activeTab);
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
                console.error('Error toggling auto-restart:', error);
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
                console.error(`Error ${action}ing host:`, error);
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
            // Check if "all containers" is selected
            if (document.getElementById('selectAllContainers').checked) {
                containerPattern = '.*';
                hostId = null;
                // Don't use container+host pairs for "all containers"
                containerHostPairs = []; // Clear any previously selected containers
            } else {
                // Get selected containers with their host IDs
                document.querySelectorAll('#containerSelectionCheckboxes input[type="checkbox"]:checked').forEach(cb => {
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
                    console.error(`Alert ${isEditing ? 'update' : 'creation'} failed:`, errorData);
                    const errorMessage = typeof errorData.detail === 'string'
                        ? errorData.detail
                        : JSON.stringify(errorData.detail) || response.statusText;
                    showToast(`❌ Failed to ${isEditing ? 'update' : 'create'} alert: ${errorMessage}`);
                }
            } catch (error) {
                console.error(`Error ${editingAlertRule ? 'updating' : 'creating'} alert rule:`, error);
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
                console.error('Error checking dependent alerts:', error);
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
                               value="${window.name || ''}"
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
                console.error('Error saving blackout windows:', error);
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
                console.error('Error fetching blackout status:', error);
            }
        }

        async function saveGlobalSettings() {
            globalSettings.max_retries = parseInt(document.getElementById('maxRetries').value);
            globalSettings.retry_delay = parseInt(document.getElementById('retryDelay').value);
            globalSettings.polling_interval = parseInt(document.getElementById('pollingInterval').value);
            globalSettings.connection_timeout = parseInt(document.getElementById('connectionTimeout').value);
            globalSettings.default_auto_restart = document.getElementById('defaultAutoRestart').classList.contains('active');

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
                }
            } catch (error) {
                console.error('Error saving settings:', error);
                showToast('❌ Failed to save settings');
            }
        }

        async function deleteAlertRule(ruleId) {
            const rule = alertRules.find(r => r.id === ruleId);
            const ruleName = rule ? rule.name : 'Unknown Rule';

            const message = `Are you sure you want to delete the alert rule <strong>"${ruleName}"</strong>?<br><br>
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
                    console.error('Error deleting alert rule:', error);
                    showToast('❌ Failed to delete alert rule');
                }
            });
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
