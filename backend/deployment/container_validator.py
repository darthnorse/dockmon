"""
Container deployment configuration validator.

Validates container definitions for:
- Required fields
- Correct field types
- Valid format for Docker SDK
- Resource limit constraints
- Port and volume mappings
"""

import re
from typing import Dict, Any, List


class ContainerValidationError(Exception):
    """Raised when container definition validation fails"""
    pass


class ContainerValidator:
    """Validator for container deployment definitions"""

    # Valid Docker restart policies
    VALID_RESTART_POLICIES = ['no', 'always', 'unless-stopped', 'on-failure']

    # Valid Docker log drivers
    VALID_LOG_DRIVERS = ['json-file', 'syslog', 'journald', 'gelf', 'awslogs', 'splunk', 'awsfirelens', 'gcplogs', 'sumologic', 'awsfirelens']

    def validate_definition(self, definition: Dict[str, Any]) -> None:
        """
        Validate container definition has correct types and formats.

        Args:
            definition: Container configuration dict

        Raises:
            ContainerValidationError: If validation fails
        """
        # Validate required fields
        self._validate_required_fields(definition)

        # Validate field types
        self._validate_field_types(definition)

        # Validate specific field formats
        self._validate_field_formats(definition)

    def _validate_required_fields(self, definition: Dict[str, Any]) -> None:
        """Validate required fields are present."""
        if 'image' not in definition:
            raise ContainerValidationError("Missing required field: 'image'")

        image = definition['image']
        if not isinstance(image, str) or not image.strip():
            raise ContainerValidationError("Field 'image' must be a non-empty string")

    def _validate_field_types(self, definition: Dict[str, Any]) -> None:
        """Validate field types are correct."""
        # String fields (from frontend form)
        string_fields = [
            'name', 'network_mode', 'cpu_limit', 'memory_limit'
        ]
        for field in string_fields:
            if field in definition and not isinstance(definition[field], str):
                raise ContainerValidationError(f"Field '{field}' must be a string, got {type(definition[field]).__name__}")

        # Boolean fields
        bool_fields = ['privileged']
        for field in bool_fields:
            if field in definition and not isinstance(definition[field], bool):
                raise ContainerValidationError(f"Field '{field}' must be a boolean, got {type(definition[field]).__name__}")

        # Dict fields (environment, labels)
        dict_fields = ['environment', 'labels']
        for field in dict_fields:
            if field in definition:
                if not isinstance(definition[field], dict):
                    raise ContainerValidationError(f"Field '{field}' must be a dict, got {type(definition[field]).__name__}")
                # Validate all keys and values are strings
                for key, value in definition[field].items():
                    if not isinstance(key, str):
                        raise ContainerValidationError(
                            f"Field '{field}': all keys must be strings, got {type(key).__name__}"
                        )
                    if not isinstance(value, str):
                        raise ContainerValidationError(
                            f"Field '{field}': all values must be strings, got {type(value).__name__} for key '{key}'"
                        )

        # List fields (from frontend form)
        list_fields = ['ports', 'volumes', 'cap_add']
        for field in list_fields:
            if field in definition:
                if not isinstance(definition[field], list):
                    raise ContainerValidationError(f"Field '{field}' must be a list, got {type(definition[field]).__name__}")
                # Validate all items are strings
                for idx, item in enumerate(definition[field]):
                    if not isinstance(item, str):
                        raise ContainerValidationError(
                            f"Field '{field}': all items must be strings, item {idx} is {type(item).__name__}"
                        )

    def _validate_field_formats(self, definition: Dict[str, Any]) -> None:
        """Validate field values are in correct format."""
        # Validate port mappings
        if 'ports' in definition:
            self._validate_ports(definition['ports'])

        # Validate volume mappings
        if 'volumes' in definition:
            self._validate_volumes(definition['volumes'])

        # Validate restart policy
        if 'restart_policy' in definition:
            self._validate_restart_policy(definition['restart_policy'])

        # Validate CPU/memory limits
        if 'cpus' in definition or 'cpu_limit' in definition:
            cpu_val = definition.get('cpus') or definition.get('cpu_limit')
            self._validate_cpu_limit(cpu_val)

        if 'mem_limit' in definition:
            self._validate_memory_limit(definition['mem_limit'])

    def _validate_ports(self, ports: List[str]) -> None:
        """
        Validate port mappings.

        Valid formats:
        - "80" (container port only)
        - "8080:80" (host_port:container_port)
        - "127.0.0.1:8080:80" (host:host_port:container_port)
        """
        if not ports:
            return

        for port_spec in ports:
            if not isinstance(port_spec, str):
                raise ContainerValidationError(f"Port mapping must be string, got {type(port_spec).__name__}")

            # Pattern: [ip:]host_port:container_port
            # or just: container_port
            pattern = r'^(\d{1,5}:)?(\d{1,5})(:(\d{1,5}))?$'

            # More detailed check
            if ':' in port_spec:
                parts = port_spec.split(':')
                if len(parts) == 2:
                    # host:container format
                    try:
                        host_port = int(parts[0])
                        container_port = int(parts[1])
                        if not (0 < host_port <= 65535 and 0 < container_port <= 65535):
                            raise ContainerValidationError(
                                f"Invalid port mapping '{port_spec}': ports must be 1-65535"
                            )
                    except ValueError:
                        raise ContainerValidationError(
                            f"Invalid port mapping '{port_spec}': ports must be numbers"
                        )
                elif len(parts) == 3:
                    # ip:host:container format
                    try:
                        host_port = int(parts[1])
                        container_port = int(parts[2])
                        if not (0 < host_port <= 65535 and 0 < container_port <= 65535):
                            raise ContainerValidationError(
                                f"Invalid port mapping '{port_spec}': ports must be 1-65535"
                            )
                    except ValueError:
                        raise ContainerValidationError(
                            f"Invalid port mapping '{port_spec}': ports must be numbers"
                        )
                else:
                    raise ContainerValidationError(
                        f"Invalid port mapping '{port_spec}': expected 'host:container' or 'ip:host:container'"
                    )
            else:
                # Just container port
                try:
                    container_port = int(port_spec)
                    if not (0 < container_port <= 65535):
                        raise ContainerValidationError(
                            f"Invalid port '{port_spec}': must be 1-65535"
                        )
                except ValueError:
                    raise ContainerValidationError(
                        f"Invalid port '{port_spec}': must be a number"
                    )

    def _validate_volumes(self, volumes: List[str]) -> None:
        """
        Validate volume mount strings.

        Valid formats:
        - "source:destination" (read-write)
        - "source:destination:ro" (read-only)
        - "source:destination:rw" (read-write)
        """
        if not volumes:
            return

        for vol_spec in volumes:
            if not isinstance(vol_spec, str):
                raise ContainerValidationError(f"Volume must be string, got {type(vol_spec).__name__}")

            parts = vol_spec.split(':')
            if len(parts) < 2 or len(parts) > 3:
                raise ContainerValidationError(
                    f"Invalid volume '{vol_spec}': expected 'source:dest' or 'source:dest:mode'"
                )

            if len(parts) == 3:
                mode = parts[2].lower()
                if mode not in ['ro', 'rw']:
                    raise ContainerValidationError(
                        f"Invalid volume mode '{mode}': must be 'ro' or 'rw'"
                    )

    def _validate_restart_policy(self, policy: str) -> None:
        """Validate restart policy value."""
        if not isinstance(policy, str):
            raise ContainerValidationError(
                f"Restart policy must be string, got {type(policy).__name__}"
            )

        if policy not in self.VALID_RESTART_POLICIES:
            raise ContainerValidationError(
                f"Invalid restart policy '{policy}': must be one of {self.VALID_RESTART_POLICIES}"
            )

    def _validate_cpu_limit(self, cpu_val: Any) -> None:
        """Validate CPU limit value."""
        try:
            cpu_float = float(cpu_val)
            if cpu_float <= 0:
                raise ContainerValidationError(
                    f"CPU limit must be positive, got {cpu_float}"
                )
            if cpu_float > 16:
                raise ContainerValidationError(
                    f"CPU limit seems too high: {cpu_float} (max recommended: 16)"
                )
        except (ValueError, TypeError):
            raise ContainerValidationError(
                f"CPU limit must be a valid number (e.g., 0.5, 1.0, 2), got '{cpu_val}'"
            )

    def _validate_memory_limit(self, mem_val: Any) -> None:
        """
        Validate memory limit value.

        Accepts: bytes, or strings like "512m", "1g"
        """
        if isinstance(mem_val, (int, float)):
            # Bytes
            if mem_val <= 0:
                raise ContainerValidationError(
                    f"Memory limit must be positive, got {mem_val}"
                )
            # Check if too large (> 1TB)
            if mem_val > 1_099_511_627_776:
                raise ContainerValidationError(
                    f"Memory limit seems too large: {mem_val} bytes"
                )
            return

        if isinstance(mem_val, str):
            mem_str = mem_val.strip().lower()
            # Pattern: number + unit
            pattern = r'^(\d+(?:\.\d+)?)(b|k|m|g|kb|mb|gb)?$'
            match = re.match(pattern, mem_str)
            if not match:
                raise ContainerValidationError(
                    f"Invalid memory format '{mem_val}': use format like '512m', '1g', or number of bytes"
                )
            return

        raise ContainerValidationError(
            f"Memory limit must be number or string, got {type(mem_val).__name__}"
        )
