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
