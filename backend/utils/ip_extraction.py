"""
IP address extraction utilities for containers
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def extract_container_ips(network_settings: dict) -> tuple[Optional[str], dict[str, str]]:
    """
    Extract container IP addresses from NetworkSettings.

    Args:
        network_settings: Container's NetworkSettings dict

    Returns:
        Tuple of (primary_ip, all_ips_dict)
        - primary_ip: First network IP found (or legacy IPAddress)
        - all_ips_dict: {network_name: ip_address} for all networks

    Examples:
        Single network:
            network_settings = {
                'Networks': {
                    'bridge': {'IPAddress': '172.17.0.5'}
                }
            }
            Returns: ('172.17.0.5', {'bridge': '172.17.0.5'})

        Multiple networks:
            network_settings = {
                'Networks': {
                    'bridge': {'IPAddress': '172.17.0.5'},
                    'my-network': {'IPAddress': '192.168.100.10'}
                }
            }
            Returns: ('172.17.0.5', {'bridge': '172.17.0.5', 'my-network': '192.168.100.10'})

        No networks:
            network_settings = {'Networks': {}}
            Returns: (None, {})
    """
    docker_ips = {}
    primary_ip = None

    # Get all network IPs
    networks = network_settings.get('Networks', {})
    for network_name, network_data in networks.items():
        ip = network_data.get('IPAddress')
        if ip:
            docker_ips[network_name] = ip
            if not primary_ip:  # Use first IP as primary
                primary_ip = ip

    # Fallback to legacy IPAddress field (for old Docker versions)
    if not primary_ip:
        legacy_ip = network_settings.get('IPAddress')
        if legacy_ip:
            primary_ip = legacy_ip
            docker_ips['bridge'] = legacy_ip

    return primary_ip, docker_ips
