"""
Network helper utilities for DockMon.

Shared functions for manual network connection during container creation.
Used by both deployment (host_connector) and updates (update_executor).
"""

import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


async def manually_connect_networks(
    container: Any,
    manual_networks: Optional[List[str]],
    manual_networking_config: Optional[Dict[str, Any]],
    client: Any,
    async_docker_call: callable,
    container_id: Optional[str] = None
) -> None:
    """
    Manually connect container to networks with advanced configuration.

    Docker SDK's networking_config parameter doesn't work reliably, so we
    must create the container first, then manually connect it to networks.

    This handles:
    - Multiple networks
    - Static IP addresses (IPv4/IPv6)
    - Network aliases
    - Links (legacy)

    Args:
        container: Docker container object to connect
        manual_networks: Simple list of network names ['net1', 'net2']
        manual_networking_config: Advanced config with static IPs, aliases, etc.
        client: Docker client instance
        async_docker_call: Async wrapper function for Docker SDK calls
        container_id: Container ID for logging (optional, uses container.short_id if not provided)

    Raises:
        Exception: If network connection fails (container should be cleaned up by caller)
    """
    # Get container ID for logging
    if container_id is None:
        container_id = getattr(container, 'short_id', str(container))

    # Handle simple network list format
    if manual_networks:
        logger.info(f"Manually connecting container {container_id} to networks: {manual_networks}")
        for network_name in manual_networks:
            try:
                network = await async_docker_call(client.networks.get, network_name)
                await async_docker_call(network.connect, container)
                logger.debug(f"Connected to network: {network_name}")
            except Exception as e:
                logger.error(f"Failed to connect to network {network_name}: {e}")
                raise

    # Handle advanced networking config with static IPs, aliases, etc.
    if manual_networking_config:
        endpoints = manual_networking_config.get('EndpointsConfig', {})
        logger.info(f"Manually connecting container {container_id} with advanced network config")

        for network_name, endpoint_config in endpoints.items():
            try:
                network = await async_docker_call(client.networks.get, network_name)

                # Extract connection parameters
                connect_kwargs = {}

                # Static IP addresses (only if user-configured, not auto-assigned)
                if 'IPAMConfig' in endpoint_config:
                    ipam = endpoint_config['IPAMConfig']
                    if 'IPv4Address' in ipam:
                        connect_kwargs['ipv4_address'] = ipam['IPv4Address']
                        logger.debug(f"  Static IPv4: {ipam['IPv4Address']}")
                    if 'IPv6Address' in ipam:
                        connect_kwargs['ipv6_address'] = ipam['IPv6Address']
                        logger.debug(f"  Static IPv6: {ipam['IPv6Address']}")

                # Network aliases
                if 'Aliases' in endpoint_config:
                    connect_kwargs['aliases'] = endpoint_config['Aliases']
                    logger.debug(f"  Aliases: {endpoint_config['Aliases']}")

                # Links (legacy)
                if 'Links' in endpoint_config:
                    connect_kwargs['links'] = endpoint_config['Links']

                # Connect to network with all parameters
                await async_docker_call(network.connect, container, **connect_kwargs)
                logger.debug(f"Connected to network: {network_name}")

            except Exception as e:
                logger.error(f"Failed to connect to network {network_name}: {e}")
                raise
