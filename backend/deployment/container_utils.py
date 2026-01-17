"""
Container utilities for deployment module.

Shared helpers for extracting information from container labels.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class HostInfo:
    """Host information for deployed stacks."""
    host_id: str
    host_name: str


@dataclass
class StackDeploymentInfo:
    """Information about where a stack is deployed, derived from container labels."""
    name: str
    hosts: List[HostInfo] = field(default_factory=list)
    services: List[str] = field(default_factory=list)
    container_count: int = 0


def get_container_compose_project(container) -> Optional[str]:
    """
    Extract the compose project name from container labels.

    Args:
        container: Container object with labels attribute

    Returns:
        Project name or None if not a compose container
    """
    labels = getattr(container, 'labels', {}) or {}
    return labels.get('com.docker.compose.project')


def get_container_compose_service(container) -> Optional[str]:
    """
    Extract the compose service name from container labels.

    Args:
        container: Container object with labels attribute

    Returns:
        Service name or None if not a compose container
    """
    labels = getattr(container, 'labels', {}) or {}
    return labels.get('com.docker.compose.service')


def scan_deployed_stacks(containers) -> Dict[str, StackDeploymentInfo]:
    """
    Scan containers and group by compose project to find deployed stacks.

    Args:
        containers: Iterable of container objects with labels, host_id, host_name

    Returns:
        Dict mapping stack name to StackDeploymentInfo
    """
    stacks: Dict[str, StackDeploymentInfo] = {}

    for container in containers:
        project = get_container_compose_project(container)
        if not project:
            continue

        host_id = getattr(container, 'host_id', None)
        host_name = getattr(container, 'host_name', None) or host_id
        service = get_container_compose_service(container)

        if project not in stacks:
            stacks[project] = StackDeploymentInfo(name=project)

        stack = stacks[project]
        stack.container_count += 1

        # Add host if not already tracked
        if host_id and not any(h.host_id == host_id for h in stack.hosts):
            stack.hosts.append(HostInfo(host_id=host_id, host_name=host_name))

        # Add service if not already tracked
        if service and service not in stack.services:
            stack.services.append(service)

    return stacks


def get_deployed_hosts_for_stack(containers, stack_name: str) -> List[HostInfo]:
    """
    Get list of hosts where a specific stack is deployed.

    Args:
        containers: Iterable of container objects
        stack_name: Name of the stack to find

    Returns:
        List of HostInfo for hosts running this stack
    """
    hosts: List[HostInfo] = []
    seen_host_ids = set()

    for container in containers:
        project = get_container_compose_project(container)
        if project != stack_name:
            continue

        host_id = getattr(container, 'host_id', None)
        if not host_id or host_id in seen_host_ids:
            continue

        seen_host_ids.add(host_id)
        host_name = getattr(container, 'host_name', None) or host_id
        hosts.append(HostInfo(host_id=host_id, host_name=host_name))

    return hosts
