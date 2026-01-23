"""
Response filtering utilities for multi-user support (v2.3.0+)

Centralizes role-based data filtering to eliminate duplication and ensure
consistent behavior across API endpoints and WebSocket broadcasts.
"""

import copy
from typing import Any, Dict, List, Optional, Union


def filter_container_env(
    containers: List[Any],
    can_view_env: bool
) -> List[Dict]:
    """
    Filter environment variables from container data for unauthorized users.

    Args:
        containers: List of container objects (dict, Pydantic model, or dataclass)
        can_view_env: True if user has containers.view_env capability

    Returns:
        List of container dicts with env filtered if unauthorized
    """
    if can_view_env:
        # Convert to dicts but preserve env
        return [container_to_dict(c) for c in containers]

    # Filter env from each container
    filtered = []
    for c in containers:
        c_dict = container_to_dict(c)
        c_dict.pop('env', None)
        filtered.append(c_dict)
    return filtered


def filter_container_inspect_env(
    inspect_result: Dict,
    can_view_env: bool
) -> Dict:
    """
    Filter environment variables from Docker inspect result.

    Args:
        inspect_result: Docker inspect API response dict
        can_view_env: True if user has containers.view_env capability

    Returns:
        Inspect result with Config.Env filtered if unauthorized
    """
    if can_view_env:
        return inspect_result

    # Deep copy to avoid mutating the original
    result = copy.deepcopy(inspect_result)
    if isinstance(result, dict) and "Config" in result:
        result["Config"]["Env"] = None
    return result


def filter_stack_env_content(
    env_content: Optional[str],
    can_view_env: bool
) -> Optional[str]:
    """
    Filter stack .env content for unauthorized users.

    Args:
        env_content: The .env file content
        can_view_env: True if user has stacks.view_env capability

    Returns:
        env_content if authorized, None otherwise
    """
    if can_view_env:
        return env_content
    return None


def filter_ws_container_message(
    message: Dict,
    can_view_env: bool
) -> Dict:
    """
    Filter container data in WebSocket messages for unauthorized users.

    Args:
        message: WebSocket message dict with type and data
        can_view_env: True if user has containers.view_env capability

    Returns:
        Message with container env filtered if unauthorized

    Note:
        Uses deep copy to prevent mutation of shared message data
        across multiple WebSocket connections.
    """
    if can_view_env:
        return message

    # Deep copy required because each connection may receive filtered version
    # while admin connections receive the original with env vars
    filtered_message = copy.deepcopy(message)

    if "data" in filtered_message and "containers" in filtered_message["data"]:
        for c_dict in filtered_message["data"]["containers"]:
            if isinstance(c_dict, dict):
                c_dict.pop("env", None)

    return filtered_message


def container_to_dict(container: Any) -> Dict:
    """
    Convert container object to dictionary, handling various types.

    Supports:
    - dict (returned as-is with copy)
    - Pydantic models (has .dict() method)
    - Dataclasses with to_dict() method
    - Objects with __dict__

    Args:
        container: Container object of various types

    Returns:
        Dictionary representation of the container
    """
    if isinstance(container, dict):
        return container.copy()
    if hasattr(container, 'dict'):
        # Pydantic model
        return container.dict()
    if hasattr(container, 'to_dict'):
        # Custom to_dict method
        return container.to_dict()
    # Fallback to __dict__
    return container.__dict__.copy()
