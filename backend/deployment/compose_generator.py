"""
Compose Generator for DockMon

Generates docker-compose.yaml content from running containers by inspecting
their configuration. Used for "recreate from containers" repair action.

LIMITATIONS:
- depends_on: Not recoverable from container state
- build: Build context not available, only image preserved
- secrets/configs: Docker Swarm features not recoverable
- Some advanced options may be lost
"""

import logging
from typing import Tuple, List, Dict, Any, Optional

import yaml
from sqlalchemy.orm import Session

from database import DeploymentMetadata
from utils.keys import parse_composite_key

logger = logging.getLogger(__name__)


async def generate_compose_from_deployment(
    deployment_id: str,
    host_id: str,
    session: Session,
    monitor,
) -> Tuple[str, List[str]]:
    """
    Generate compose.yaml from containers linked to a deployment.

    Args:
        deployment_id: Deployment ID
        host_id: Host ID where containers run
        session: Database session
        monitor: DockerMonitor instance for container inspection

    Returns:
        Tuple of (compose_yaml string, list of warnings)
    """
    warnings = []

    # Get container IDs from deployment metadata
    metadata_records = (
        session.query(DeploymentMetadata)
        .filter(DeploymentMetadata.deployment_id == deployment_id)
        .all()
    )

    if not metadata_records:
        warnings.append("No containers found linked to this deployment")
        return _empty_compose(), warnings

    services = {}

    for record in metadata_records:
        try:
            _, container_id = parse_composite_key(record.container_id)
        except ValueError:
            logger.warning(f"Invalid composite key: {record.container_id}")
            continue

        # Inspect container
        try:
            inspect_data = await monitor.operations.inspect_container(host_id, container_id)
        except Exception as e:
            logger.error(f"Failed to inspect container {container_id}: {e}")
            warnings.append(f"Could not inspect container {container_id}")
            continue

        # Extract service configuration
        service_name = record.service_name or _get_service_name(inspect_data)
        service_config = _extract_service_config(inspect_data)

        if service_config:
            services[service_name] = service_config

    if not services:
        warnings.append("No service configurations could be extracted")
        return _empty_compose(), warnings

    # Add standard warnings about limitations
    warnings.extend([
        "depends_on relationships cannot be recovered from container state",
        "build context is not available - using image only",
    ])

    compose: Dict[str, Any] = {
        "services": services,
    }

    # Add networks if containers use custom networks
    networks = _extract_networks(services)
    if networks:
        compose["networks"] = networks

    # Add volumes if named volumes are used
    volumes = _extract_named_volumes(services)
    if volumes:
        compose["volumes"] = volumes

    return yaml.dump(compose, default_flow_style=False, sort_keys=False), warnings


async def generate_compose_from_containers(
    project_name: str,
    host_id: str,
    containers: List[Any],
    monitor,
) -> Tuple[str, List[str]]:
    """
    Generate compose.yaml from a list of running containers.

    Used to "adopt" existing docker-compose stacks into DockMon.

    Args:
        project_name: Docker Compose project name
        host_id: Host ID where containers run
        containers: List of container objects from DockerMonitor
        monitor: DockerMonitor instance for container inspection

    Returns:
        Tuple of (compose_yaml string, list of warnings)
    """
    warnings = []
    services = {}

    for container in containers:
        container_id = getattr(container, 'id', None) or getattr(container, 'short_id', None)
        if not container_id:
            continue

        # Ensure short ID
        container_id = container_id[:12]

        # Inspect container for full details
        try:
            inspect_data = await monitor.operations.inspect_container(host_id, container_id)
        except Exception as e:
            logger.error(f"Failed to inspect container {container_id}: {e}")
            warnings.append(f"Could not inspect container {container_id}")
            continue

        # Extract service configuration
        service_name = _get_service_name(inspect_data)
        service_config = _extract_service_config(inspect_data)

        if service_config:
            services[service_name] = service_config

    if not services:
        warnings.append("No service configurations could be extracted")
        return _empty_compose(), warnings

    # Add standard warnings about limitations
    warnings.extend([
        "depends_on relationships cannot be recovered from container state",
        "build context is not available - using image only",
    ])

    compose: Dict[str, Any] = {
        "name": project_name,
        "services": services,
    }

    # Add networks if containers use custom networks
    networks = _extract_networks(services)
    if networks:
        compose["networks"] = networks

    # Add volumes if named volumes are used
    volumes = _extract_named_volumes(services)
    if volumes:
        compose["volumes"] = volumes

    return yaml.dump(compose, default_flow_style=False, sort_keys=False), warnings


def _empty_compose() -> str:
    """Return empty compose file."""
    return yaml.dump({"services": {}}, default_flow_style=False)


def _get_service_name(inspect_data: dict) -> str:
    """Extract service name from container labels or name."""
    labels = inspect_data.get("Config", {}).get("Labels", {}) or {}

    # Try compose label first
    if "com.docker.compose.service" in labels:
        return labels["com.docker.compose.service"]

    # Fall back to container name (strip leading /)
    name = inspect_data.get("Name", "").lstrip("/")
    return name or "unknown"


def _extract_service_config(inspect_data: dict) -> Optional[Dict[str, Any]]:
    """Extract compose service configuration from container inspect data."""
    config = inspect_data.get("Config", {})
    host_config = inspect_data.get("HostConfig", {})
    labels = config.get("Labels", {}) or {}

    service: Dict[str, Any] = {}

    # Image (required)
    image = config.get("Image")
    if not image:
        return None
    service["image"] = image

    # Container name (only if not auto-generated by compose)
    if "com.docker.compose.container-number" not in labels:
        name = inspect_data.get("Name", "").lstrip("/")
        if name:
            service["container_name"] = name

    # Command (if set)
    cmd = config.get("Cmd")
    if cmd:
        service["command"] = cmd

    # Entrypoint (if set)
    entrypoint = config.get("Entrypoint")
    if entrypoint:
        service["entrypoint"] = entrypoint

    # Environment variables
    env = config.get("Env", [])
    if env:
        filtered_env = [e for e in env if not _is_docker_injected_env(e)]
        if filtered_env:
            service["environment"] = filtered_env

    # Ports
    port_bindings = host_config.get("PortBindings", {})
    if port_bindings:
        ports = _extract_ports(port_bindings)
        if ports:
            service["ports"] = ports

    # Volumes
    mounts = inspect_data.get("Mounts", [])
    if mounts:
        volumes = _extract_volumes(mounts)
        if volumes:
            service["volumes"] = volumes

    # Restart policy
    restart_policy = host_config.get("RestartPolicy", {})
    if restart_policy:
        restart = _parse_restart_policy(restart_policy)
        if restart:
            service["restart"] = restart

    # Network mode
    network_mode = host_config.get("NetworkMode", "")
    if network_mode and network_mode not in ("default", "bridge"):
        if network_mode.startswith("container:"):
            service["network_mode"] = network_mode
        elif network_mode == "host":
            service["network_mode"] = "host"
        elif network_mode == "none":
            service["network_mode"] = "none"
        else:
            # Custom network
            service["networks"] = [network_mode]

    # User labels (filter out internal Docker/Compose labels)
    user_labels = {k: v for k, v in labels.items() if not _is_internal_label(k)}
    if user_labels:
        service["labels"] = user_labels

    # Healthcheck
    healthcheck = config.get("Healthcheck")
    if healthcheck:
        hc = _extract_healthcheck(healthcheck)
        if hc:
            service["healthcheck"] = hc

    # Resource limits
    memory = host_config.get("Memory")
    if memory and memory > 0:
        if "deploy" not in service:
            service["deploy"] = {"resources": {"limits": {}}}
        service["deploy"]["resources"]["limits"]["memory"] = _bytes_to_human(memory)

    cpu_quota = host_config.get("CpuQuota")
    cpu_period = host_config.get("CpuPeriod")
    if cpu_quota and cpu_period and cpu_period > 0:
        cpus = cpu_quota / cpu_period
        if "deploy" not in service:
            service["deploy"] = {"resources": {"limits": {}}}
        service["deploy"]["resources"]["limits"]["cpus"] = str(cpus)

    return service


def _extract_ports(port_bindings: dict) -> List[str]:
    """Extract port mappings from PortBindings."""
    ports = []
    for container_port, bindings in port_bindings.items():
        if not bindings:
            continue
        for binding in bindings:
            host_ip = binding.get("HostIp", "")
            host_port = binding.get("HostPort", "")
            if host_ip and host_ip not in ("0.0.0.0", "::"):
                ports.append(f"{host_ip}:{host_port}:{container_port}")
            elif host_port:
                ports.append(f"{host_port}:{container_port}")
    return ports


def _extract_volumes(mounts: list) -> List[str]:
    """Extract volume mounts from Mounts array."""
    volumes = []
    for mount in mounts:
        mount_type = mount.get("Type", "")
        source = mount.get("Source", "")
        destination = mount.get("Destination", "")
        read_only = mount.get("RW", True) is False

        if mount_type == "bind" and source and destination:
            vol = f"{source}:{destination}"
            if read_only:
                vol += ":ro"
            volumes.append(vol)
        elif mount_type == "volume" and destination:
            name = mount.get("Name", source)
            vol = f"{name}:{destination}"
            if read_only:
                vol += ":ro"
            volumes.append(vol)

    return volumes


def _parse_restart_policy(policy: dict) -> Optional[str]:
    """Parse restart policy to compose format."""
    name = policy.get("Name", "")
    if name == "always":
        return "always"
    elif name == "unless-stopped":
        return "unless-stopped"
    elif name == "on-failure":
        max_retries = policy.get("MaximumRetryCount", 0)
        if max_retries:
            return f"on-failure:{max_retries}"
        return "on-failure"
    return None


def _extract_healthcheck(healthcheck: dict) -> Optional[Dict[str, Any]]:
    """Extract healthcheck configuration."""
    hc: Dict[str, Any] = {}

    test = healthcheck.get("Test", [])
    if test:
        hc["test"] = test

    interval = healthcheck.get("Interval")
    if interval:
        hc["interval"] = _nanoseconds_to_duration(interval)

    timeout = healthcheck.get("Timeout")
    if timeout:
        hc["timeout"] = _nanoseconds_to_duration(timeout)

    retries = healthcheck.get("Retries")
    if retries:
        hc["retries"] = retries

    start_period = healthcheck.get("StartPeriod")
    if start_period:
        hc["start_period"] = _nanoseconds_to_duration(start_period)

    return hc if hc else None


def _is_docker_injected_env(env_var: str) -> bool:
    """Check if env var is typically injected by Docker."""
    key = env_var.split("=", 1)[0] if "=" in env_var else env_var
    docker_vars = {"PATH", "HOME", "HOSTNAME"}
    return key in docker_vars


def _is_internal_label(key: str) -> bool:
    """Check if label is Docker/Compose internal or DockMon internal."""
    internal_prefixes = [
        "com.docker.",
        "org.opencontainers.",
        "desktop.docker.",
        "dockmon.",  # DockMon internal labels (deployment_id, etc.)
    ]
    return any(key.startswith(prefix) for prefix in internal_prefixes) or key == "maintainer"


def _nanoseconds_to_duration(ns: int) -> str:
    """Convert nanoseconds to Docker duration string."""
    seconds = ns / 1_000_000_000
    if seconds >= 60:
        minutes = int(seconds / 60)
        remaining_seconds = int(seconds % 60)
        if remaining_seconds:
            return f"{minutes}m{remaining_seconds}s"
        return f"{minutes}m"
    return f"{int(seconds)}s"


def _bytes_to_human(bytes_val: int) -> str:
    """Convert bytes to human-readable memory string."""
    if bytes_val >= 1024 * 1024 * 1024:
        return f"{bytes_val // (1024 * 1024 * 1024)}g"
    if bytes_val >= 1024 * 1024:
        return f"{bytes_val // (1024 * 1024)}m"
    return f"{bytes_val // 1024}k"


def _extract_networks(services: Dict[str, Any]) -> Dict[str, Any]:
    """Extract network definitions from services."""
    networks: Dict[str, Any] = {}
    for service in services.values():
        service_networks = service.get("networks", [])
        for net in service_networks:
            if isinstance(net, str) and net not in ("default", "bridge", "host", "none"):
                networks[net] = {"external": True}
    return networks


def _extract_named_volumes(services: Dict[str, Any]) -> Dict[str, Any]:
    """Extract named volume definitions from services."""
    volumes: Dict[str, Any] = {}
    for service in services.values():
        service_volumes = service.get("volumes", [])
        for vol in service_volumes:
            if isinstance(vol, str) and ":" in vol:
                source = vol.split(":")[0]
                # Named volumes don't start with / or .
                if source and not source.startswith("/") and not source.startswith("."):
                    volumes[source] = {}
    return volumes
