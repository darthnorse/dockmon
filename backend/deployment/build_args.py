"""
Container create arguments builder for deployment operations.

Converts DockMon definition format to Docker SDK parameters.
Extracted from executor.py for maintainability.
"""

import logging
from typing import Any, Dict

from .container_validator import ContainerValidator, ContainerValidationError

logger = logging.getLogger(__name__)


def build_container_create_args(definition: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build Docker SDK container.create() arguments from definition.

    Maps DockMon definition format to Docker SDK parameters.
    Validates all fields before building.

    Args:
        definition: Container configuration dictionary with fields like:
            - image (required): Docker image name
            - name: Container name
            - command: Command to run
            - environment: Environment variables dict
            - ports: Port mappings list ["8080:80"]
            - volumes: Volume mounts list ["source:dest:mode"]
            - network_mode: Network mode
            - privileged: Run privileged
            - restart_policy: Restart policy
            - memory_limit/mem_limit: Memory limit
            - cpu_limit/cpus: CPU limit

    Returns:
        Dict of arguments for Docker SDK container.create()

    Raises:
        ValueError: If definition validation fails
    """
    # Validate definition format
    validator = ContainerValidator()
    try:
        validator.validate_definition(definition)
    except ContainerValidationError as e:
        raise ValueError(f"Invalid container configuration: {str(e)}")

    args = {}

    # Required
    args['image'] = definition['image']

    # Optional - basic
    if 'name' in definition:
        args['name'] = definition['name']
    if 'command' in definition:
        args['command'] = definition['command']
    if 'entrypoint' in definition:
        args['entrypoint'] = definition['entrypoint']
    if 'hostname' in definition:
        args['hostname'] = definition['hostname']
    if 'user' in definition:
        args['user'] = definition['user']
    if 'working_dir' in definition:
        args['working_dir'] = definition['working_dir']

    # Environment variables - validate format and keys
    if 'environment' in definition:
        args['environment'] = _parse_environment(definition['environment'])

    # Ports - convert from list format ["8080:80"] to Docker SDK format
    if 'ports' in definition:
        args['ports'] = _parse_ports(definition['ports'])

    # Volumes - can be list of strings ["source:dest", "source:dest:ro"] or dict format
    if 'volumes' in definition:
        args['volumes'] = _parse_volumes(definition['volumes'])

    # Network
    if 'network_mode' in definition:
        args['network_mode'] = definition['network_mode']
    if 'networks' in definition:
        args['network'] = definition['networks']

    # Security
    if 'privileged' in definition:
        args['privileged'] = definition['privileged']
    if 'cap_add' in definition:
        args['cap_add'] = definition['cap_add']
    if 'cap_drop' in definition:
        args['cap_drop'] = definition['cap_drop']

    # Resource limits
    # Support both 'memory_limit' (frontend) and 'mem_limit' (Docker SDK)
    if 'memory_limit' in definition:
        args['mem_limit'] = definition['memory_limit']
    elif 'mem_limit' in definition:
        args['mem_limit'] = definition['mem_limit']

    if 'memswap_limit' in definition:
        args['memswap_limit'] = definition['memswap_limit']
    if 'cpu_shares' in definition:
        args['cpu_shares'] = definition['cpu_shares']
    if 'cpuset_cpus' in definition:
        args['cpuset_cpus'] = definition['cpuset_cpus']

    # Support both 'cpu_limit' (frontend) and 'cpus' (Docker SDK)
    if 'cpu_limit' in definition:
        args['nano_cpus'] = int(float(definition['cpu_limit']) * 1e9)
    elif 'cpus' in definition:
        args['nano_cpus'] = int(float(definition['cpus']) * 1e9)

    # Restart policy
    if 'restart_policy' in definition:
        args['restart_policy'] = definition['restart_policy']

    # Labels
    if 'labels' in definition:
        args['labels'] = definition['labels']

    # Detach (always True for daemon containers)
    args['detach'] = True

    return args


def _parse_environment(environment: Any) -> Dict[str, str]:
    """
    Parse and validate environment variables.

    Args:
        environment: Environment dict or other format

    Returns:
        Validated environment dict with string values
    """
    if not isinstance(environment, dict):
        logger.warning(
            f"Invalid environment format: expected dict, got {type(environment).__name__}, "
            "ignoring environment variables."
        )
        return None

    validated_env = {}
    for key, value in environment.items():
        # Validate environment variable key is valid
        # Keys should be alphanumeric + underscore, starting with letter or underscore
        if not key:
            logger.warning("Empty environment variable key, skipping.")
            continue

        # Check if key matches pattern: starts with letter/underscore, then alphanumeric/underscore
        if not (key[0].isalpha() or key[0] == '_'):
            logger.warning(
                f"Invalid environment variable key: '{key}'. "
                "Must start with letter or underscore, skipping."
            )
            continue

        if not all(c.isalnum() or c == '_' for c in key):
            logger.warning(
                f"Invalid environment variable key: '{key}'. "
                "Must contain only alphanumeric characters and underscores, skipping."
            )
            continue

        # Validate value is a string
        if not isinstance(value, (str, int, float, bool)):
            logger.warning(
                f"Invalid environment variable value for '{key}': "
                f"expected string/int/float/bool, got {type(value).__name__}, skipping."
            )
            continue

        # Convert to string
        validated_env[key] = str(value)

    return validated_env if validated_env else None


def _parse_ports(ports: Any) -> Dict[int, int]:
    """
    Parse port mappings from list format to Docker SDK format.

    Args:
        ports: List of port strings ["8080:80"] or dict/tuple format

    Returns:
        Dict of {container_port: host_port} for Docker SDK
    """
    if not isinstance(ports, list):
        # If it's already a dict or tuple format, use as-is
        return ports

    # Convert list of port strings to proper Docker SDK format
    # ["8080:80"] -> {80: 8080} (container_port: host_port)
    port_bindings = {}

    for port_spec in ports:
        try:
            if ':' in str(port_spec):
                # Handle "host:container" or "host:container/protocol" format
                parts = str(port_spec).split(':')
                if len(parts) != 2:
                    logger.warning(
                        f"Invalid port format: {port_spec}. Expected 'host:container', skipping."
                    )
                    continue

                host_port_str, container_port_str = parts
                # Remove protocol suffix if present (e.g., "80/tcp" -> "80")
                if '/' in container_port_str:
                    container_port_str = container_port_str.split('/')[0]

                container_port_int = int(container_port_str)
                host_port_int = int(host_port_str)

                # Validate port ranges (1-65535)
                if not (1 <= container_port_int <= 65535 and 1 <= host_port_int <= 65535):
                    logger.warning(
                        f"Port out of valid range (1-65535): {port_spec}, skipping."
                    )
                    continue

                # Docker SDK format: {container_port: host_port}
                port_bindings[container_port_int] = host_port_int
            else:
                # Just container port, expose without binding to host
                container_port_int = int(str(port_spec))

                # Validate port range
                if not (1 <= container_port_int <= 65535):
                    logger.warning(
                        f"Port out of valid range (1-65535): {port_spec}, skipping."
                    )
                    continue

                port_bindings[container_port_int] = None

        except (ValueError, AttributeError) as e:
            logger.warning(f"Failed to parse port '{port_spec}': {e}, skipping.")
            continue

    return port_bindings if port_bindings else None


def _parse_volumes(volumes: Any) -> Dict[str, Dict[str, str]]:
    """
    Parse volume mounts from list format to Docker SDK format.

    Args:
        volumes: List of volume strings ["source:dest:mode"] or dict format

    Returns:
        Dict of {source: {"bind": dest, "mode": mode}} for Docker SDK
    """
    if not isinstance(volumes, list):
        # If it's already a dict format, use as-is
        return volumes

    # Convert list to dict format that Docker SDK expects
    # ["source:dest"] -> {"source": {"bind": "dest", "mode": "rw"}}
    volume_dict = {}

    for vol_spec in volumes:
        try:
            vol_str = str(vol_spec).strip()
            if not vol_str:
                logger.warning("Empty volume specification, skipping.")
                continue

            if ':' not in vol_str:
                logger.warning(
                    f"Invalid volume format: '{vol_spec}'. "
                    "Expected 'source:dest' or 'source:dest:mode', skipping."
                )
                continue

            parts = vol_str.split(':')
            if len(parts) not in (2, 3):
                logger.warning(
                    f"Invalid volume format: '{vol_spec}'. "
                    f"Expected 'source:dest' (2 parts) or 'source:dest:mode' (3 parts), "
                    f"got {len(parts)}, skipping."
                )
                continue

            source, dest = parts[0], parts[1]
            mode = parts[2] if len(parts) == 3 else 'rw'

            # Validate source and dest are non-empty
            if not source or not dest:
                logger.warning(
                    f"Invalid volume specification: source and dest cannot be empty. "
                    f"Got '{vol_spec}', skipping."
                )
                continue

            # Validate mode is one of the valid Docker modes
            if mode not in ('rw', 'ro', 'z', 'Z', 'rprivate', 'shared', 'rslave'):
                logger.warning(
                    f"Invalid volume mode: '{mode}'. "
                    "Expected 'rw', 'ro', 'z', 'Z', 'rprivate', 'shared', or 'rslave', skipping."
                )
                continue

            volume_dict[source] = {'bind': dest, 'mode': mode}

        except (ValueError, AttributeError, IndexError) as e:
            logger.warning(f"Failed to parse volume '{vol_spec}': {e}, skipping.")
            continue

    return volume_dict if volume_dict else None
