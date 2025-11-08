import os
import re
from typing import Optional


def sanitize_base_path(path: Optional[str]) -> str:
    """
    Sanitize a base path to ensure it has leading and trailing slashes.

    This function ensures:
    - Path always starts with /
    - Path always ends with /
    - Multiple consecutive slashes are normalized to single slashes
    - Empty, None, or whitespace-only inputs return "/"

    Args:
        path: The base path to sanitize (can be None, empty, or invalid)

    Returns:
        A sanitized base path string (always has leading and trailing slashes)

    Examples:
        >>> sanitize_base_path("/dockmon/")
        '/dockmon/'
        >>> sanitize_base_path("dockmon")
        '/dockmon/'
        >>> sanitize_base_path("")
        '/'
        >>> sanitize_base_path(None)
        '/'
    """
    # Handle None, empty string, or whitespace-only string
    if not path or not path.strip():
        return "/"

    # Strip whitespace
    path = path.strip()

    # Normalize multiple consecutive slashes to single slashes
    path = re.sub(r'/+', '/', path)

    # Ensure leading slash
    if not path.startswith('/'):
        path = '/' + path

    # Ensure trailing slash
    if not path.endswith('/'):
        path = path + '/'

    return path


def get_base_path() -> str:
    """
    Get the base path from environment variable BASE_PATH.

    Reads the BASE_PATH environment variable and sanitizes it.
    If not set or empty, returns "/" (root path).

    Returns:
        Sanitized base path from environment or "/" if not set

    Examples:
        >>> os.environ['BASE_PATH'] = '/dockmon/'
        >>> get_base_path()
        '/dockmon/'
        >>> os.environ['BASE_PATH'] = ''
        >>> get_base_path()
        '/'
    """
    base_path = os.environ.get('BASE_PATH', '/')
    return sanitize_base_path(base_path)
