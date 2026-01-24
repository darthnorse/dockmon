"""
Capability Definitions for Group-Based Permissions (v2.3.0 refactor)

This module defines ALL_CAPABILITIES and their metadata for the RBAC system.
Capabilities are assigned to groups, users get permissions from their groups.

Usage:
    from auth.capabilities import ALL_CAPABILITIES, CAPABILITY_INFO
    from auth.capabilities import ADMIN_CAPABILITIES, OPERATOR_CAPABILITIES, READONLY_CAPABILITIES
"""

from typing import Dict, Set


# =============================================================================
# Capability Definitions with Metadata
# =============================================================================

CAPABILITY_INFO: Dict[str, Dict[str, str]] = {
    # Hosts
    'hosts.manage': {
        'category': 'Hosts',
        'name': 'Manage Hosts',
        'description': 'Add, edit, and delete Docker hosts',
    },
    'hosts.view': {
        'category': 'Hosts',
        'name': 'View Hosts',
        'description': 'View host list and connection status',
    },

    # Stacks
    'stacks.edit': {
        'category': 'Stacks',
        'name': 'Edit Stacks',
        'description': 'Create, edit, and delete stack definitions',
    },
    'stacks.deploy': {
        'category': 'Stacks',
        'name': 'Deploy Stacks',
        'description': 'Deploy existing stacks to hosts',
    },
    'stacks.view': {
        'category': 'Stacks',
        'name': 'View Stacks',
        'description': 'View stack list and contents',
    },
    'stacks.view_env': {
        'category': 'Stacks',
        'name': 'View Stack Env Files',
        'description': 'View .env file contents (may contain secrets)',
    },

    # Containers
    'containers.operate': {
        'category': 'Containers',
        'name': 'Operate Containers',
        'description': 'Start, stop, and restart containers',
    },
    'containers.shell': {
        'category': 'Containers',
        'name': 'Shell Access',
        'description': 'Execute commands in containers (essentially root access)',
    },
    'containers.update': {
        'category': 'Containers',
        'name': 'Update Containers',
        'description': 'Trigger container image updates',
    },
    'containers.view': {
        'category': 'Containers',
        'name': 'View Containers',
        'description': 'View container list and details',
    },
    'containers.logs': {
        'category': 'Containers',
        'name': 'View Logs',
        'description': 'View container log output',
    },
    'containers.view_env': {
        'category': 'Containers',
        'name': 'View Container Env',
        'description': 'View container environment variables (may contain secrets)',
    },

    # Health Checks
    'healthchecks.manage': {
        'category': 'Health Checks',
        'name': 'Manage Health Checks',
        'description': 'Create, edit, and delete HTTP health checks',
    },
    'healthchecks.test': {
        'category': 'Health Checks',
        'name': 'Test Health Checks',
        'description': 'Manually trigger health check tests',
    },
    'healthchecks.view': {
        'category': 'Health Checks',
        'name': 'View Health Checks',
        'description': 'View health check configurations and results',
    },

    # Batch Operations
    'batch.create': {
        'category': 'Batch Operations',
        'name': 'Create Batch Jobs',
        'description': 'Create bulk container operation jobs',
    },
    'batch.view': {
        'category': 'Batch Operations',
        'name': 'View Batch Jobs',
        'description': 'View batch job list and status',
    },

    # Update Policies
    'policies.manage': {
        'category': 'Update Policies',
        'name': 'Manage Policies',
        'description': 'Create, edit, and delete auto-update policies',
    },
    'policies.view': {
        'category': 'Update Policies',
        'name': 'View Policies',
        'description': 'View auto-update policy configurations',
    },

    # Alerts
    'alerts.manage': {
        'category': 'Alerts',
        'name': 'Manage Alert Rules',
        'description': 'Create, edit, and delete alert rules',
    },
    'alerts.view': {
        'category': 'Alerts',
        'name': 'View Alerts',
        'description': 'View alert rules and history',
    },

    # Notifications
    'notifications.manage': {
        'category': 'Notifications',
        'name': 'Manage Channels',
        'description': 'Create, edit, and delete notification channels',
    },
    'notifications.view': {
        'category': 'Notifications',
        'name': 'View Channels',
        'description': 'View notification channel names (not configs)',
    },

    # Registry
    'registry.manage': {
        'category': 'Registry Credentials',
        'name': 'Manage Credentials',
        'description': 'Create, edit, and delete registry credentials',
    },
    'registry.view': {
        'category': 'Registry Credentials',
        'name': 'View Credentials',
        'description': 'View registry credential details (contains passwords)',
    },

    # Agents
    'agents.manage': {
        'category': 'Agents',
        'name': 'Manage Agents',
        'description': 'Register agents and trigger agent updates',
    },
    'agents.view': {
        'category': 'Agents',
        'name': 'View Agents',
        'description': 'View agent status and information',
    },

    # Settings
    'settings.manage': {
        'category': 'Settings',
        'name': 'Manage Settings',
        'description': 'Edit global application settings',
    },

    # Users
    'users.manage': {
        'category': 'Users',
        'name': 'Manage Users',
        'description': 'Create, edit, and delete users',
    },

    # Groups (new for v2.3.0 refactor)
    'groups.manage': {
        'category': 'Groups',
        'name': 'Manage Groups',
        'description': 'Create, edit, and delete groups and their permissions',
    },

    # Audit
    'audit.view': {
        'category': 'Audit',
        'name': 'View Audit Log',
        'description': 'View the security audit log',
    },

    # API Keys
    'apikeys.manage_own': {
        'category': 'API Keys',
        'name': 'Manage Own Keys',
        'description': 'Create and manage personal API keys',
    },
    'apikeys.manage_other': {
        'category': 'API Keys',
        'name': 'Manage Others Keys',
        'description': 'Manage API keys of other users',
    },

    # Tags
    'tags.manage': {
        'category': 'Tags',
        'name': 'Manage Tags',
        'description': 'Create, edit, and delete tags',
    },
    'tags.view': {
        'category': 'Tags',
        'name': 'View Tags',
        'description': 'View tag list',
    },

    # Events
    'events.view': {
        'category': 'Events',
        'name': 'View Events',
        'description': 'View container and system event log',
    },
}


# =============================================================================
# Capability Sets
# =============================================================================

# All capabilities (for reference and validation)
ALL_CAPABILITIES: Set[str] = set(CAPABILITY_INFO.keys())


# Administrators group - all capabilities
ADMIN_CAPABILITIES: Set[str] = ALL_CAPABILITIES.copy()


# Operators group - can use features but limited config access
OPERATOR_CAPABILITIES: Set[str] = {
    'hosts.view',
    'stacks.deploy',
    'stacks.view',
    'stacks.view_env',
    'containers.operate',
    'containers.view',
    'containers.logs',
    'containers.view_env',
    'healthchecks.test',
    'healthchecks.view',
    'batch.create',
    'batch.view',
    'policies.view',
    'alerts.view',
    'notifications.view',
    'agents.view',
    'apikeys.manage_own',
    'tags.manage',
    'tags.view',
    'events.view',
}


# Read Only group - view-only access
READONLY_CAPABILITIES: Set[str] = {
    'hosts.view',
    'stacks.view',
    'containers.view',
    'containers.logs',
    'healthchecks.view',
    'batch.view',
    'policies.view',
    'alerts.view',
    'notifications.view',
    'agents.view',
    'tags.view',
    'events.view',
}


# =============================================================================
# Helper Functions
# =============================================================================

def get_categories() -> list[str]:
    """Get unique list of capability categories in display order."""
    seen: Set[str] = set()
    categories: list[str] = []
    for info in CAPABILITY_INFO.values():
        category = info['category']
        if category not in seen:
            seen.add(category)
            categories.append(category)
    return categories


def get_capabilities_by_category() -> Dict[str, list[str]]:
    """Get capabilities grouped by category."""
    result: Dict[str, list[str]] = {}
    for capability, info in CAPABILITY_INFO.items():
        category = info['category']
        if category not in result:
            result[category] = []
        result[category].append(capability)
    return result


def is_valid_capability(capability: str) -> bool:
    """Check if a capability string is valid."""
    return capability in ALL_CAPABILITIES
