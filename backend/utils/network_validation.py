"""
Network validation utilities for DockMon deployments.

Provides IPAM configuration validation and comparison logic to ensure
network compatibility during deployments and updates.
"""

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


def _get_pool_field(pool: Dict[str, Any], field_name: str) -> Optional[str]:
    """
    Safely extract field from IPAMPool dict with case-insensitive fallback.

    Docker SDK uses capitalized keys (Subnet, Gateway, IPRange) but we check
    both cases for defensive programming.

    Args:
        pool: IPAMPool dict (or similar structure)
        field_name: Field name in lowercase (e.g., 'subnet', 'gateway')

    Returns:
        Field value or None
    """
    # Try capitalized first (Docker SDK standard)
    capitalized = field_name.capitalize()
    if capitalized in pool:
        return pool[capitalized]

    # Fallback to lowercase (defensive)
    if field_name in pool:
        return pool[field_name]

    # Special case: IPRange vs iprange
    if field_name == 'iprange':
        if 'IPRange' in pool:
            return pool['IPRange']

    return None


def validate_network_ipam_matches(
    existing_network: Any,
    requested_ipam_config: Any
) -> bool:
    """
    Check if existing network's IPAM config matches requested config.

    This validates that a pre-existing Docker network has compatible IPAM
    configuration for the deployment. Used to detect subnet mismatches that
    would cause static IP assignment failures.

    Args:
        existing_network: Docker network object with .attrs property
        requested_ipam_config: docker.types.IPAMConfig object or None

    Returns:
        True if configs match or no specific config requested
        False if configs don't match (incompatible subnets)

    Examples:
        >>> # Network exists with subnet 172.20.0.0/16
        >>> # User requests subnet 172.20.0.0/16
        >>> validate_network_ipam_matches(network, ipam_config)
        True

        >>> # Network exists with subnet 172.25.0.0/16
        >>> # User requests subnet 172.20.0.0/16
        >>> validate_network_ipam_matches(network, ipam_config)
        False
    """
    if not requested_ipam_config:
        # No IPAM requirements specified - any network is acceptable
        return True

    # Extract pool configs from requested IPAM
    # IPAMConfig is a dict with 'Config' key (capital C), not 'pool_configs' attribute
    if isinstance(requested_ipam_config, dict):
        requested_pools = requested_ipam_config.get('Config') or requested_ipam_config.get('config')
    else:
        requested_pools = getattr(requested_ipam_config, 'pool_configs', None)

    if not requested_pools:
        # No specific pool requirements
        return True

    # Get existing network's IPAM configuration
    existing_ipam = existing_network.attrs.get('IPAM', {})
    existing_configs = existing_ipam.get('Config', [])

    if not existing_configs:
        # Existing network has no IPAM config but user requires one
        logger.debug("Existing network has no IPAM config, user requires specific config")
        return False

    # Check each requested pool against existing configs
    for requested_pool in requested_pools:
        # Extract subnet from pool (case-insensitive for robustness)
        if isinstance(requested_pool, dict):
            requested_subnet = _get_pool_field(requested_pool, 'subnet')
        else:
            requested_subnet = getattr(requested_pool, 'subnet', None)

        if not requested_subnet:
            continue

        # Check if any existing config has matching subnet
        subnet_found = False
        existing_subnets = [c.get('Subnet') for c in existing_configs]

        for existing_config in existing_configs:
            existing_subnet = existing_config.get('Subnet')
            if existing_subnet == requested_subnet:
                subnet_found = True
                break

        if not subnet_found:
            logger.warning(
                f"Subnet mismatch: requested {requested_subnet}, "
                f"existing has {existing_subnets}"
            )
            return False
    return True


def format_existing_ipam(network: Any) -> str:
    """
    Format existing network's IPAM config for error messages.

    Args:
        network: Docker network object

    Returns:
        Human-readable string describing IPAM configuration

    Example:
        >>> format_existing_ipam(network)
        'Subnet: 172.25.0.0/16, Gateway: 172.25.0.1'
    """
    ipam = network.attrs.get('IPAM', {})
    configs = ipam.get('Config', [])

    if not configs:
        return "No IPAM configuration (auto-assigned)"

    lines = []
    for idx, config in enumerate(configs):
        parts = []
        if config.get('Subnet'):
            parts.append(f"Subnet: {config['Subnet']}")
        if config.get('Gateway'):
            parts.append(f"Gateway: {config['Gateway']}")
        if config.get('IPRange'):
            parts.append(f"IPRange: {config['IPRange']}")

        if parts:
            prefix = f"  Pool {idx + 1}: " if len(configs) > 1 else "  "
            lines.append(prefix + ", ".join(parts))

    return "\n".join(lines) if lines else "No IPAM configuration"


def format_requested_ipam(ipam_config: Any) -> str:
    """
    Format requested IPAM config for error messages.

    Args:
        ipam_config: docker.types.IPAMConfig object

    Returns:
        Human-readable string describing requested IPAM configuration

    Example:
        >>> format_requested_ipam(ipam_config)
        'Subnet: 172.20.0.0/16, Gateway: 172.20.0.1'
    """
    if not ipam_config:
        return "No IPAM configuration"

    # IPAMConfig is a dict with 'Config' key, not 'pool_configs' attribute
    if isinstance(ipam_config, dict):
        pools = ipam_config.get('Config') or ipam_config.get('config')
    else:
        pools = getattr(ipam_config, 'pool_configs', None)

    if not pools:
        return "No pool configuration"

    lines = []
    for idx, pool in enumerate(pools):
        parts = []

        # Handle both dict and IPAMPool object (case-insensitive)
        if isinstance(pool, dict):
            subnet = _get_pool_field(pool, 'subnet')
            gateway = _get_pool_field(pool, 'gateway')
            iprange = _get_pool_field(pool, 'iprange')
        else:
            subnet = getattr(pool, 'subnet', None)
            gateway = getattr(pool, 'gateway', None)
            iprange = getattr(pool, 'iprange', None)

        if subnet:
            parts.append(f"Subnet: {subnet}")
        if gateway:
            parts.append(f"Gateway: {gateway}")
        if iprange:
            parts.append(f"IPRange: {iprange}")

        if parts:
            prefix = f"  Pool {idx + 1}: " if len(pools) > 1 else "  "
            lines.append(prefix + ", ".join(parts))

    return "\n".join(lines) if lines else "No pool configuration"
