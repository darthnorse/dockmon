"""
Docker network helpers shared by the host network endpoints.

Keeping the response formatter here (instead of inline in main.py) guarantees
the list and create endpoints emit an identical network shape and keeps the
formatting independently unit-testable.
"""

import logging
from typing import Any, Dict, Optional

import docker
from docker.errors import APIError
from fastapi import HTTPException

from utils.async_docker import async_docker_call
from utils.timestamps import normalize_docker_timestamp

logger = logging.getLogger(__name__)

# Built-in Docker networks that cannot be deleted
BUILTIN_NETWORKS = frozenset(['bridge', 'host', 'none'])


def build_network_ipam(subnet: str, gateway: str) -> Optional[docker.types.IPAMConfig]:
    """
    Build a docker IPAMConfig from an optional subnet/gateway.

    Returns None when no subnet is given (Docker auto-assigns addressing).
    A gateway without a subnet is meaningless and is ignored.
    """
    if not subnet:
        return None

    pool = docker.types.IPAMPool(subnet=subnet, gateway=(gateway or None))
    return docker.types.IPAMConfig(pool_configs=[pool])


def format_network(network) -> Dict[str, Any]:
    """
    Format a Docker SDK Network object into the API response shape.

    Used by both the list and create endpoints so they stay in sync.
    """
    attrs = network.attrs or {}
    short_id = network.short_id if hasattr(network, 'short_id') and network.short_id else network.id[:12]

    created = normalize_docker_timestamp(attrs.get('Created', ''))

    containers_info = attrs.get('Containers') or {}
    containers = []
    for container_id, container_data in containers_info.items():
        containers.append({
            'id': container_id[:12],
            'name': container_data.get('Name', '').lstrip('/')
        })

    ipam = attrs.get('IPAM', {}) or {}
    ipam_config = ipam.get('Config', []) or []
    subnet = ipam_config[0].get('Subnet', '') if ipam_config else ''

    return {
        'id': short_id,
        'name': network.name,
        'driver': attrs.get('Driver', ''),
        'scope': attrs.get('Scope', 'local'),
        'created': created,
        'internal': attrs.get('Internal', False),
        'subnet': subnet,
        'containers': containers,
        'container_count': len(containers),
        'is_builtin': network.name in BUILTIN_NETWORKS,
    }


async def create_network_local(
    client,
    name: str,
    driver: str,
    subnet: str,
    gateway: str,
    internal: bool,
) -> Dict[str, Any]:
    """
    Create a network via the local/mTLS Docker SDK and return it formatted to
    match the list endpoint shape.

    Reloading the network after create is best-effort: once the network exists,
    a failure to refresh its attributes must NOT turn a successful create into
    an error (mirrors the agent path's inspect-failure fallback).

    Raises:
        HTTPException: 409 if a network with that name already exists,
            500 on any other create failure. The Docker daemon's message is
            surfaced for APIErrors so subnet/pool conflicts are actionable;
            unexpected (non-API) errors return a generic message.
    """
    ipam = build_network_ipam(subnet, gateway)

    # Create the network. An APIError carries the actionable Docker daemon
    # message; anything else is unexpected and returns a generic 500.
    try:
        network = await async_docker_call(
            client.networks.create,
            name,
            driver=driver,
            internal=internal,
            ipam=ipam,
        )
    except APIError as e:
        status = getattr(e, 'status_code', None)
        if status is None:
            status = getattr(getattr(e, 'response', None), 'status_code', None)
        if status == 409 or 'already exists' in str(e).lower():
            raise HTTPException(status_code=409, detail=f"A network named '{name}' already exists")
        raise HTTPException(status_code=500, detail=f"Failed to create network: {e}")
    except Exception as e:
        logger.error("Unexpected error creating network '%s': %s", name, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create network")

    # The network now exists; refreshing its attributes is best-effort.
    try:
        await async_docker_call(network.reload)
        return format_network(network)
    except Exception as e:
        logger.warning("Created network '%s' but failed to reload its attributes: %s", name, e)
        # Return minimal info from known inputs rather than failing a successful create.
        return {
            'id': network.id[:12],
            'name': name,
            'driver': driver or 'bridge',
            'scope': 'local',
            'created': '',
            'internal': internal,
            'subnet': subnet or '',
            'containers': [],
            'container_count': 0,
            'is_builtin': name in BUILTIN_NETWORKS,
        }
