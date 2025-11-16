"""
Registry Credentials Utility

Centralized credential lookup for Docker registries.
Used by both update checker (registry API) and update executor (Docker pulls).
"""

import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)


def get_registry_credentials(db, image_name: str) -> Optional[Dict[str, str]]:
    """
    Get credentials for registry from image name.

    Extracts registry URL from image and looks up stored credentials.

    Args:
        db: DatabaseManager instance
        image_name: Full image reference (e.g., "nginx:1.25", "ghcr.io/user/app:latest")

    Returns:
        Dict with {username, password} if credentials found, None otherwise

    Examples:
        nginx:1.25 → docker.io → lookup credentials for "docker.io"
        ghcr.io/user/app:latest → ghcr.io → lookup credentials for "ghcr.io"
        registry.example.com:5000/app:v1 → registry.example.com:5000 → lookup
    """
    try:
        from database import RegistryCredential
        from utils.encryption import decrypt_password

        # Extract registry URL using same logic as registry_adapter
        registry_url = "docker.io"  # Default for Docker Hub

        # Check for explicit registry
        if "/" in image_name:
            parts = image_name.split("/", 1)
            # If first part has dot or colon, it's likely a registry
            if "." in parts[0] or ":" in parts[0]:
                registry_url = parts[0]

        # Normalize (lowercase)
        registry_url = registry_url.lower()

        logger.info(f"Looking up credentials for registry_url='{registry_url}' (from image: {image_name})")

        # Query database for credentials
        with db.get_session() as session:
            cred = session.query(RegistryCredential).filter_by(
                registry_url=registry_url
            ).first()

            logger.info(f"Credential lookup result: {cred is not None} (registry_url='{registry_url}')")

            if cred:
                try:
                    plaintext = decrypt_password(cred.password_encrypted)
                    logger.debug(f"Using credentials for registry '{registry_url}'")
                    return {
                        "username": cred.username,
                        "password": plaintext
                    }
                except Exception as e:
                    logger.error(f"Failed to decrypt credentials for {registry_url}: {e}")
                    return None

            # No credentials found
            return None

    except Exception as e:
        logger.error(f"Error looking up registry credentials: {e}")
        return None
