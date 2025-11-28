"""
Network helper functions for deployment operations.

Contains IPAM configuration parsing and network reconciliation logic
extracted from executor.py for maintainability.
"""

import logging
from typing import Any, Dict, List, Optional

from docker.types import IPAMConfig, IPAMPool

from utils.async_docker import async_docker_call
from utils.network_validation import (
    validate_network_ipam_matches,
    format_existing_ipam,
    format_requested_ipam
)

logger = logging.getLogger(__name__)


def is_named_volume(path: str) -> bool:
    """
    Check if volume is a named volume (not a bind mount).

    Named volumes: 'my_volume', 'db_data'
    Bind mounts: '/host/path', './relative/path', '../parent/path'

    Args:
        path: Volume source path

    Returns:
        True if named volume, False if bind mount
    """
    return not (path.startswith('/') or path.startswith('.'))


def parse_ipam_config(ipam_dict: Dict[str, Any]) -> Optional[IPAMConfig]:
    """
    Convert Docker Compose IPAM config to Docker SDK IPAMConfig.

    Supports all IPAM fields from compose spec:
    - driver: IPAM driver (default: 'default')
    - config: List of subnet configurations
      - subnet: Network subnet (e.g., '172.20.0.0/16')
      - gateway: Gateway IP (optional)
      - ip_range: Range for dynamic IPs (optional)
      - aux_addresses: Reserved IPs (optional dict)
    - options: Driver-specific options (optional dict)

    Args:
        ipam_dict: IPAM configuration from compose file

    Returns:
        docker.types.IPAMConfig object or None if no config

    Example compose IPAM:
        ipam:
          driver: default
          config:
            - subnet: 172.20.0.0/16
              gateway: 172.20.0.1
              ip_range: 172.20.240.0/20
              aux_addresses:
                host1: 172.20.0.5
          options:
            foo: bar
    """
    if not ipam_dict:
        return None

    pool_configs = []
    if 'config' in ipam_dict and ipam_dict['config']:
        for pool in ipam_dict['config']:
            if not isinstance(pool, dict):
                continue

            pool_configs.append(IPAMPool(
                subnet=pool.get('subnet'),
                gateway=pool.get('gateway'),
                iprange=pool.get('ip_range'),
                aux_addresses=pool.get('aux_addresses')
            ))

    return IPAMConfig(
        driver=ipam_dict.get('driver'),
        pool_configs=pool_configs if pool_configs else None,
        options=ipam_dict.get('options')
    )


async def reconcile_existing_network(
    connector,
    network_name: str,
    driver: str,
    ipam_config: Optional[IPAMConfig],
    created_networks: List[str]
) -> None:
    """
    Reconcile existing network with requested configuration.

    Implements smart network reconciliation for deployment idempotency:
    1. If no IPAM requirements -> Use existing network (backward compatible)
    2. If IPAM matches -> Use existing network (idempotent)
    3. If IPAM mismatch + network empty -> Auto-recreate (dev/test UX)
    4. If IPAM mismatch + network in use -> Fail with clear error (safety)

    This prevents cryptic "invalid endpoint settings" errors when static IPs
    are configured but the network has incompatible IPAM configuration.

    Args:
        connector: Host connector instance
        network_name: Name of the network
        driver: Network driver (e.g., 'bridge')
        ipam_config: Requested IPAM configuration (docker.types.IPAMConfig)
        created_networks: List to append network name to on success

    Raises:
        RuntimeError: If network has incompatible config and is in use
    """
    # Get Docker client from connector
    client = connector._get_client()
    existing_network = await async_docker_call(client.networks.get, network_name)

    # Case 1: No IPAM requirements - existing network is acceptable
    if not ipam_config:
        logger.info(
            f"Network '{network_name}' already exists "
            f"(no IPAM config to validate)"
        )
        created_networks.append(network_name)
        return

    # Case 2: IPAM matches - idempotent success
    if validate_network_ipam_matches(existing_network, ipam_config):
        logger.info(
            f"Network '{network_name}' already exists with matching IPAM config"
        )
        created_networks.append(network_name)
        return

    # IPAM mismatch detected - determine if safe to recreate
    containers_on_network = existing_network.attrs.get('Containers', {})

    if containers_on_network:
        # Case 4: Network in use - unsafe to delete, fail with helpful error
        raise RuntimeError(
            f"Cannot deploy: Network '{network_name}' already exists with "
            f"incompatible IPAM configuration and has {len(containers_on_network)} "
            f"container(s) attached.\n\n"
            f"Existing IPAM:\n{format_existing_ipam(existing_network)}\n\n"
            f"Requested IPAM:\n{format_requested_ipam(ipam_config)}\n\n"
            f"To fix this issue:\n"
            f"  1. Stop/remove containers using this network, OR\n"
            f"  2. Delete the network manually:\n"
            f"       docker network rm {network_name}\n"
            f"  3. Use a different network name in your compose file\n\n"
            f"Then retry the deployment."
        )

    # Case 3: Network empty - safe to auto-recreate (dev/test UX)
    logger.warning(
        f"Network '{network_name}' exists with different IPAM configuration "
        f"but is empty. Auto-recreating with requested configuration."
    )

    try:
        # Delete orphaned network
        await async_docker_call(existing_network.remove)
        logger.info(f"Deleted orphaned network '{network_name}'")

        # Recreate with correct configuration
        await connector.create_network(network_name, driver=driver, ipam=ipam_config)
        logger.info(
            f"Recreated network '{network_name}' with correct IPAM configuration"
        )
        created_networks.append(network_name)

    except Exception as recreate_err:
        raise RuntimeError(
            f"Failed to recreate network '{network_name}': {recreate_err}. "
            f"You may need to manually delete it:\n"
            f"  docker network rm {network_name}"
        )
