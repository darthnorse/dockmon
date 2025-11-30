"""
Shared test helper functions.

Import these in tests via: from tests.test_helpers import create_composite_key
"""

from unittest.mock import Mock


def create_composite_key(host_id: str, container_id: str) -> str:
    """
    Create composite key for multi-host container identification.

    Format: {host_id}:{container_id}
    """
    return f"{host_id}:{container_id}"


def create_mock_container(
    container_id: str = "abc123def456",
    name: str = "test-container",
    image: str = "nginx:latest",
    state: str = "running",
    labels: dict = None
):
    """
    Create a mock container object for testing.

    Args:
        container_id: Container ID (12 chars, SHORT ID)
        name: Container name
        image: Container image
        state: Container state
        labels: Container labels dict (optional)

    Returns:
        Mock container with standard attributes
    """
    if labels is None:
        labels = {}

    container = Mock()
    container.short_id = container_id
    container.id = container_id + "0" * 52  # Pad to 64 chars for full ID
    container.name = name
    container.status = state
    container.labels = labels
    container.attrs = {
        'State': {'Status': state},
        'Config': {
            'Image': image,
            'Labels': labels
        }
    }
    return container
