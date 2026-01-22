"""
Image ID Normalization Utilities

Docker image IDs come in multiple formats:
- Full SHA256: "sha256:abc123def456..." (71+ chars)
- Short ID: "abc123def456" (12 chars)
- short_id property: Sometimes includes "sha256:" prefix

This module provides consistent normalization to 12-char short format.
"""


def normalize_image_id(image_id: str) -> str:
    """
    Normalize image ID to 12-char short format without sha256: prefix.

    Handles all Docker image ID formats:
    - "sha256:abc123def456..." → "abc123def456"
    - "abc123def456" → "abc123def456"
    - "abc123def456789..." (64 chars) → "abc123def456"

    Args:
        image_id: Image ID in any format

    Returns:
        12-char short image ID

    Examples:
        >>> normalize_image_id("sha256:abc123def456")
        "abc123def456"
        >>> normalize_image_id("abc123def456789012345...")
        "abc123def456"
    """
    return image_id.replace('sha256:', '')[:12]
