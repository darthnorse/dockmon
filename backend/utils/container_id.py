"""
Container ID Normalization Utilities

CRITICAL: Backend always uses 12-char short container IDs for consistency.
Frontend may send either 12-char or 64-char IDs depending on data source.

This module provides defensive normalization to accept both formats.
"""


def normalize_container_id(container_id: str) -> str:
    """
    Normalize container ID to 12-char short format.

    Accepts both 12-char short IDs and 64-char full IDs for resilience.
    Frontend sends either format depending on data source:
    - React Query cache: 12-char (from /containers endpoint)
    - StatsProvider WebSocket: Could be 64-char (from agent stats)
    - Modal fallback state: Could be either

    Args:
        container_id: Container ID (12 or 64 chars)

    Returns:
        12-char short container ID

    Examples:
        >>> normalize_container_id("abc123def456")
        "abc123def456"
        >>> normalize_container_id("abc123def456789...full64chars")
        "abc123def456"
    """
    return container_id[:12]
