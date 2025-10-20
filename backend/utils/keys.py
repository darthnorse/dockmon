"""
Utility functions for container and host key management.

Provides centralized functions for creating and parsing composite keys
used throughout the DockMon system.
"""


def make_composite_key(host_id: str, container_id: str) -> str:
    """
    Create composite key in format: host_id:container_id

    Args:
        host_id: Host UUID (full UUID format)
        container_id: Container SHORT ID (12 characters)

    Returns:
        Composite key string (e.g., "7be442c9-24bc-4047-b33a-41bbf51ea2f9:67c5d2141338")

    Example:
        >>> make_composite_key("7be442c9-24bc-4047-b33a-41bbf51ea2f9", "67c5d2141338")
        "7be442c9-24bc-4047-b33a-41bbf51ea2f9:67c5d2141338"
    """
    if not host_id:
        raise ValueError("host_id cannot be empty")
    if not container_id:
        raise ValueError("container_id cannot be empty")

    # Validate container_id is SHORT (12 chars)
    if len(container_id) != 12:
        raise ValueError(f"container_id must be 12 characters (SHORT ID), got {len(container_id)}: {container_id}")

    return f"{host_id}:{container_id}"


def parse_composite_key(composite_key: str) -> tuple[str, str]:
    """
    Parse composite key into (host_id, container_id) tuple.

    Args:
        composite_key: Composite key string (format: "host_id:container_id")

    Returns:
        Tuple of (host_id, container_id)

    Raises:
        ValueError: If composite_key format is invalid

    Example:
        >>> parse_composite_key("7be442c9-24bc-4047-b33a-41bbf51ea2f9:67c5d2141338")
        ("7be442c9-24bc-4047-b33a-41bbf51ea2f9", "67c5d2141338")
    """
    if not composite_key:
        raise ValueError("composite_key cannot be empty")

    parts = composite_key.split(":", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid composite key format (expected 'host_id:container_id'): {composite_key}")

    host_id, container_id = parts

    # Validate parts are not empty
    if not host_id:
        raise ValueError(f"host_id part is empty in composite key: {composite_key}")
    if not container_id:
        raise ValueError(f"container_id part is empty in composite key: {composite_key}")

    # Validate container_id is SHORT (12 chars)
    if len(container_id) != 12:
        raise ValueError(f"container_id must be 12 characters (SHORT ID), got {len(container_id)}: {container_id}")

    return host_id, container_id
