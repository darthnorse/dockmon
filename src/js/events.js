// ==================== Event Log Functions ====================

let currentEventsPage = 0;
const eventsPerPage = 50;
let eventSearchTimeout = null;
let currentSortOrder = 'desc'; // 'desc' = newest first, 'asc' = oldest first

// Multi-select dropdown functions
function toggleMultiselect(filterId) {
    const multiselect = document.getElementById(`${filterId}Multiselect`);
    const wasOpen = multiselect.classList.contains('open');

    // Close all other multiselects
    document.querySelectorAll('.multiselect').forEach(ms => ms.classList.remove('open'));

    // Toggle this one
    if (!wasOpen) {
        multiselect.classList.add('open');
    }

    // Re-create icons after DOM manipulation
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

function updateMultiselect(filterId) {
    const dropdown = document.getElementById(`${filterId}Dropdown`);
    const checkboxes = dropdown.querySelectorAll('input[type="checkbox"]:checked');
    const selected = Array.from(checkboxes).map(cb => cb.value);

    // Update the label
    const label = document.querySelector(`#${filterId}Multiselect .multiselect-label`);
    if (selected.length === 0) {
        if (filterId === 'eventCategory') label.textContent = 'All Categories';
        else if (filterId === 'eventSeverity') label.textContent = 'All Severities';
        else if (filterId === 'eventHost') label.textContent = 'All Hosts';
    } else if (selected.length === 1) {
        label.textContent = selected[0].charAt(0).toUpperCase() + selected[0].slice(1);
    } else {
        label.textContent = `${selected.length} selected`;
    }

    // Trigger filter update
    filterEvents();
}

function getMultiselectValues(filterId) {
    const dropdown = document.getElementById(`${filterId}Dropdown`);
    const checkboxes = dropdown.querySelectorAll('input[type="checkbox"]:checked');
    return Array.from(checkboxes).map(cb => cb.value);
}

// Close multiselects when clicking outside
document.addEventListener('click', function(event) {
    if (!event.target.closest('.multiselect')) {
        document.querySelectorAll('.multiselect').forEach(ms => ms.classList.remove('open'));
    }
});

async function loadEvents() {
    const eventsList = document.getElementById('eventsList');
    if (!eventsList) return;

    eventsList.innerHTML = '<div class="events-loading">Loading events...</div>';

    try {
        // Build query parameters
        const timeRange = document.getElementById('eventTimeRange').value;
        const categories = getMultiselectValues('eventCategory');
        const severities = getMultiselectValues('eventSeverity');
        const hostIds = getMultiselectValues('eventHost');
        const search = document.getElementById('eventSearch').value;

        const params = new URLSearchParams({
            limit: eventsPerPage,
            offset: currentEventsPage * eventsPerPage
        });

        if (timeRange !== 'all') {
            params.append('hours', timeRange);
        }

        // Append multiple values for multi-select filters
        categories.forEach(cat => params.append('category', cat));
        severities.forEach(sev => params.append('severity', sev));
        hostIds.forEach(host => params.append('host_id', host));

        if (search) params.append('search', search);

        const response = await fetch(`/api/events?${params}`, {
            credentials: 'include'
        });

        if (!response.ok) {
            throw new Error('Failed to load events');
        }

        const data = await response.json();
        renderEvents(data);
    } catch (error) {
        logger.error('Error loading events:', error);
        eventsList.innerHTML = '<div class="events-empty">Failed to load events. Please try again.</div>';
        showToast('Failed to load events', 'error');
    }
}

function renderEvents(data) {
    const eventsList = document.getElementById('eventsList');
    const eventsPagination = document.getElementById('eventsPagination');

    if (!data.events || data.events.length === 0) {
        eventsList.innerHTML = `
            <div class="events-empty">
                <span data-lucide="inbox"></span>
                <p>No events found</p>
            </div>
        `;
        lucide.createIcons();
        eventsPagination.innerHTML = '';
        return;
    }

    // Render events
    let html = '';
    data.events.forEach(event => {
        html += renderEventItem(event);
    });
    eventsList.innerHTML = html;
    lucide.createIcons();

    // Render pagination
    const start = currentEventsPage * eventsPerPage + 1;
    const end = Math.min((currentEventsPage + 1) * eventsPerPage, data.total_count);

    eventsPagination.innerHTML = `
        <div class="pagination-info">
            Showing ${start}-${end} of ${data.total_count} events
        </div>
        <div class="pagination-controls">
            <button class="pagination-btn" ${currentEventsPage === 0 ? 'disabled' : ''} onclick="previousEventsPage()">
                <span data-lucide="chevron-left"></span> Previous
            </button>
            <button class="pagination-btn" ${!data.has_more ? 'disabled' : ''} onclick="nextEventsPage()">
                Next <span data-lucide="chevron-right"></span>
            </button>
        </div>
    `;
    lucide.createIcons();
}

function renderEventItem(event) {
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

    // Build inline metadata
    let metaParts = [];

    if (event.container_name) {
        metaParts.push(`container=${escapeHtml(event.container_name)}`);
    }

    if (event.host_name) {
        metaParts.push(`host=${escapeHtml(event.host_name)}`);
    }

    // Don't show user=user since we already show (user action) in the event text
    // if (event.triggered_by && event.triggered_by !== 'system') {
    //     metaParts.push(`user=${escapeHtml(event.triggered_by)}`);
    // }

    const metaString = metaParts.length > 0 ? metaParts.join(' ') : '';

    // Build the event text - show message if it's different from title
    let eventText = escapeHtml(event.title);
    if (event.message && event.message !== event.title) {
        // Extract the useful part of the message (e.g., "from running to exited")
        const stateChangeMatch = event.message.match(/state changed from (\w+) to (\w+)/i);
        if (stateChangeMatch) {
            const fromState = stateChangeMatch[1];
            const toState = stateChangeMatch[2];
            const userAction = event.message.includes('(user action)') ? ' <span style="color: var(--text-secondary);">(user action)</span>' : '';
            eventText += ` from <span class="state-${fromState}">${escapeHtml(fromState)}</span> to <span class="state-${toState}">${escapeHtml(toState)}</span>${userAction}`;
        } else {
            // For other messages, show full message instead of title
            eventText = escapeHtml(event.message);
        }
    }

    return `
        <div class="event-line severity-${event.severity}">
            <span class="event-timestamp">${timestamp}</span>
            <span class="event-severity-dot"></span>
            <span class="event-level">level=${event.severity}</span>
            <span class="event-message-text">${eventText}</span>
            ${metaString ? `<span class="event-meta-inline">${metaString}</span>` : ''}
            <div class="event-mobile-content">
                <div class="event-mobile-header"><span class="event-severity-dot"></span><span class="event-mobile-time">${timestamp}</span></div>
                <div class="event-mobile-message">${eventText}</div>
            </div>
        </div>
    `;
}

// getCategoryIcon() removed - unused function

function formatEventTime(timestamp) {
    const date = new Date(timestamp);
    const now = new Date();
    const diff = now - date;
    const seconds = Math.floor(diff / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    if (seconds < 60) return 'Just now';
    if (minutes < 60) return `${minutes}m ago`;
    if (hours < 24) return `${hours}h ago`;
    if (days < 7) return `${days}d ago`;

    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
}

// showEventDetails() removed - unused function (TODO was never implemented)

function refreshEvents() {
    currentEventsPage = 0;
    loadEvents();
}

function filterEvents() {
    currentEventsPage = 0;
    loadEvents();
}

function debounceEventSearch() {
    clearTimeout(eventSearchTimeout);
    eventSearchTimeout = setTimeout(() => {
        filterEvents();
    }, 500);
}

function nextEventsPage() {
    currentEventsPage++;
    loadEvents();
}

function previousEventsPage() {
    if (currentEventsPage > 0) {
        currentEventsPage--;
        loadEvents();
    }
}

async function populateEventHostFilter() {
    const hostDropdown = document.getElementById('eventHostDropdown');
    if (!hostDropdown) return;

    // Clear existing checkboxes
    hostDropdown.innerHTML = '';

    // Add hosts from the global hosts array
    hosts.forEach(host => {
        const label = document.createElement('label');
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.value = host.id;
        checkbox.onchange = () => updateMultiselect('eventHost');

        label.appendChild(checkbox);
        label.appendChild(document.createTextNode(' ' + host.name));
        hostDropdown.appendChild(label);
    });
}

async function loadEventSortOrder() {
    try {
        const response = await fetch('/api/user/event-sort-order', {
            credentials: 'include'
        });
        if (response.ok) {
            const data = await response.json();
            currentSortOrder = data.sort_order || 'desc';
            updateSortOrderButton();
        }
    } catch (error) {
        logger.error('Failed to load sort order preference:', error);
    }
}

async function toggleEventSortOrder() {
    // Toggle between asc and desc
    currentSortOrder = currentSortOrder === 'desc' ? 'asc' : 'desc';

    // Save to backend
    try {
        await fetch('/api/user/event-sort-order', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ sort_order: currentSortOrder })
        });
    } catch (error) {
        logger.error('Failed to save sort order:', error);
        showToast('Failed to save sort order', 'error');
    }

    // Update button
    updateSortOrderButton();

    // Reload events with new sort order
    currentEventsPage = 0;
    loadEvents();
}

function updateSortOrderButton() {
    const btn = document.getElementById('sortOrderBtn');
    if (!btn) return;

    if (currentSortOrder === 'desc') {
        btn.innerHTML = '<span data-lucide="arrow-down-wide-narrow"></span> Newest First';
    } else {
        btn.innerHTML = '<span data-lucide="arrow-up-narrow-wide"></span> Oldest First';
    }
    lucide.createIcons();
}

// WebSocket handling for real-time event updates
let isOnEventsPage = false;

// Register a custom handler using the wsMessageHandlers array instead of overriding the function
if (!window.wsMessageHandlers) {
    window.wsMessageHandlers = [];
}

window.wsMessageHandlers.push(function(data) {
    // Only process new_event messages when on the events page
    if (data.type === 'new_event' && isOnEventsPage) {
        const event = data.event;

        // Check if event matches current filters
        if (shouldShowEvent(event)) {
            prependNewEvent(event);
        }
    }
});

function shouldShowEvent(event) {
    // Check if event matches current filters
    const categories = getMultiselectValues('eventCategory');
    const severities = getMultiselectValues('eventSeverity');
    const hostIds = getMultiselectValues('eventHost');
    const search = document.getElementById('eventSearch')?.value;

    // Category filter - if any categories selected, event must match one
    if (categories.length > 0 && !categories.includes(event.category)) return false;

    // Severity filter - if any severities selected, event must match one
    if (severities.length > 0 && !severities.includes(event.severity)) return false;

    // Host filter - if any hosts selected, event must match one
    if (hostIds.length > 0 && !hostIds.includes(event.host_id)) return false;

    // Search filter (supports regex)
    if (search) {
        const searchTerm = search.trim();

        // Try to use as regex first, fall back to plain string search
        try {
            const regex = new RegExp(searchTerm, 'i');
            const titleMatch = event.title && regex.test(event.title);
            const messageMatch = event.message && regex.test(event.message);
            const containerMatch = event.container_name && regex.test(event.container_name);
            if (!titleMatch && !messageMatch && !containerMatch) return false;
        } catch (e) {
            // Invalid regex, use plain string search
            const searchLower = searchTerm.toLowerCase();
            const titleMatch = event.title?.toLowerCase().includes(searchLower);
            const messageMatch = event.message?.toLowerCase().includes(searchLower);
            const containerMatch = event.container_name?.toLowerCase().includes(searchLower);
            if (!titleMatch && !messageMatch && !containerMatch) return false;
        }
    }

    return true;
}

function prependNewEvent(event) {
    const eventsList = document.getElementById('eventsList');
    if (!eventsList) return;

    // Check if we're showing empty state
    const emptyState = eventsList.querySelector('.events-empty');
    if (emptyState) {
        emptyState.remove();
    }

    // Create new event HTML
    const eventHtml = renderEventItem(event);

    // Add to top or bottom depending on sort order
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = eventHtml;
    const eventElement = tempDiv.firstElementChild;
    eventElement.style.opacity = '0';

    if (currentSortOrder === 'desc') {
        // Newest first - add to top
        eventElement.style.transform = 'translateY(-10px)';
        eventsList.insertBefore(eventElement, eventsList.firstChild);
    } else {
        // Oldest first - add to bottom
        eventElement.style.transform = 'translateY(10px)';
        eventsList.appendChild(eventElement);
    }

    // Trigger animation
    setTimeout(() => {
        eventElement.style.transition = 'all 0.3s ease';
        eventElement.style.opacity = '1';
        eventElement.style.transform = 'translateY(0)';
    }, 10);

    // Re-render icons
    lucide.createIcons();

    // Show a subtle notification
    const badge = document.createElement('div');
    badge.style.cssText = 'position: fixed; top: 80px; right: 20px; background: var(--primary); color: white; padding: 8px 16px; border-radius: 6px; font-size: 14px; z-index: 10000; box-shadow: 0 4px 12px rgba(0,0,0,0.3); animation: slideIn 0.3s ease;';
    badge.innerHTML = '<span data-lucide="bell"></span> New event';
    document.body.appendChild(badge);
    lucide.createIcons();

    setTimeout(() => {
        badge.style.opacity = '0';
        badge.style.transition = 'opacity 0.3s ease';
        setTimeout(() => badge.remove(), 300);
    }, 2000);
}

// Hook into the existing WebSocket connection
// The websocket is initialized in app.js and messages are handled globally
// Hook into page switching to load events
document.addEventListener('DOMContentLoaded', function() {
    const originalSwitchPage = window.switchPage;
    if (originalSwitchPage) {
        window.switchPage = function(page) {
            originalSwitchPage(page);
            if (page === 'events') {
                isOnEventsPage = true;
                loadEventSortOrder();
                populateEventHostFilter();
                loadEvents();
            } else {
                isOnEventsPage = false;
            }
        };
    }
});