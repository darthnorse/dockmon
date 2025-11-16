"""
Docker Compose security and configuration validator.

Validates compose files for:
- YAML safety (prevents code execution)
- Required fields
- Service configuration
- Dependency cycles
"""

import re
import yaml
from .compose_parser import ComposeParser, ComposeParseError


class ComposeValidationError(Exception):
    """Raised when compose file validation fails"""
    pass


class DependencyCycleError(ComposeValidationError):
    """Raised when circular dependencies detected in depends_on"""
    pass


class ComposeValidator:
    """Validator for Docker Compose files"""

    # Dangerous YAML tags that could execute code
    DANGEROUS_TAGS = [
        '!!python/object',
        '!!python/name',
        '!!python/module',
        '!!python/object/apply',
        '!!python/object/new',
    ]

    def validate_yaml_safety(self, compose_yaml: str):
        """
        Validate YAML doesn't contain dangerous tags.

        Args:
            compose_yaml: YAML content as string

        Raises:
            ComposeValidationError: If unsafe tags found
        """
        # Check for dangerous tags
        for tag in self.DANGEROUS_TAGS:
            if tag in compose_yaml:
                raise ComposeValidationError(
                    f"Unsafe YAML tag detected: {tag}. This could execute arbitrary code."
                )

    def validate_required_fields(self, compose_data: dict):
        """
        Validate required fields are present.

        Args:
            compose_data: Parsed compose dict

        Raises:
            ComposeValidationError: If required fields missing
        """
        # Note: 'version' is optional in Docker Compose Specification
        # (only required in legacy Compose file format v1/v2/v3)

        if 'services' not in compose_data:
            raise ComposeValidationError("Missing required field: services")

        if not compose_data['services']:
            raise ComposeValidationError("At least one service required")

    def validate_service_configuration(self, compose_data: dict):
        """
        Validate service configurations are valid.

        Args:
            compose_data: Parsed compose dict

        Raises:
            ComposeValidationError: If invalid service config
        """
        if 'services' not in compose_data:
            return

        for service_name, service_config in compose_data['services'].items():
            # Each service must have image or build
            if 'image' not in service_config and 'build' not in service_config:
                raise ComposeValidationError(
                    f"Service '{service_name}' must have 'image' or 'build'"
                )

            # Validate port mappings if present
            if 'ports' in service_config:
                for port in service_config['ports']:
                    if not self._is_valid_port_mapping(port):
                        raise ComposeValidationError(
                            f"Invalid port mapping in service '{service_name}': {port}"
                        )

            # Validate network_mode if present (v2.1.8 - Quick Wins)
            if 'network_mode' in service_config:
                network_mode = service_config['network_mode']

                # Must be a string
                if not isinstance(network_mode, str):
                    raise ComposeValidationError(
                        f"Service '{service_name}': network_mode must be a string, "
                        f"got {type(network_mode).__name__}"
                    )

                # Explicit check for empty string with clear message
                if not network_mode or network_mode.strip() == "":
                    raise ComposeValidationError(
                        f"Service '{service_name}': network_mode cannot be empty. "
                        f"Valid values: 'bridge', 'host', 'none', or 'container:<name>'"
                    )

                # Must be valid mode or container:<name>
                valid_modes = ['bridge', 'host', 'none']
                # Docker Compose accepts both 'container:name' and 'service:name' (service is alias for container in compose)
                if network_mode not in valid_modes and not network_mode.startswith('container:') and not network_mode.startswith('service:'):
                    raise ComposeValidationError(
                        f"Service '{service_name}': Invalid network_mode '{network_mode}'. "
                        f"Must be one of {valid_modes}, 'container:<name>', or 'service:<name>'"
                    )

                # Cannot use both network_mode and networks
                if 'networks' in service_config:
                    raise ComposeValidationError(
                        f"Service '{service_name}': Cannot use both 'network_mode' and 'networks'. "
                        f"These options are mutually exclusive. "
                        f"Remove one to fix this error."
                    )

            # Validate extra_hosts if present (v2.1.8 - Quick Wins)
            if 'extra_hosts' in service_config:
                extra_hosts = service_config['extra_hosts']

                if isinstance(extra_hosts, list):
                    # List format: validate 'hostname:ip' format
                    for entry in extra_hosts:
                        if not isinstance(entry, str):
                            raise ComposeValidationError(
                                f"Service '{service_name}': extra_hosts entries must be strings, "
                                f"got {type(entry).__name__}"
                            )
                        if ':' not in entry:
                            raise ComposeValidationError(
                                f"Service '{service_name}': Invalid extra_hosts format '{entry}'. "
                                f"Expected format: 'hostname:ip' (e.g., 'db:192.168.1.100')"
                            )
                elif isinstance(extra_hosts, dict):
                    # Dict format: validate keys and values are strings
                    for hostname, ip in extra_hosts.items():
                        if not isinstance(hostname, str):
                            raise ComposeValidationError(
                                f"Service '{service_name}': extra_hosts hostname must be string, "
                                f"got {type(hostname).__name__}"
                            )
                        if not isinstance(ip, str):
                            raise ComposeValidationError(
                                f"Service '{service_name}': extra_hosts IP must be string, "
                                f"got {type(ip).__name__}"
                            )
                else:
                    raise ComposeValidationError(
                        f"Service '{service_name}': extra_hosts must be a list or dict, "
                        f"got {type(extra_hosts).__name__}"
                    )

            # Validate devices if present (v2.1.8 - Quick Wins)
            if 'devices' in service_config:
                devices = service_config['devices']

                if not isinstance(devices, list):
                    raise ComposeValidationError(
                        f"Service '{service_name}': devices must be a list, "
                        f"got {type(devices).__name__}"
                    )

                for device in devices:
                    if not isinstance(device, str):
                        raise ComposeValidationError(
                            f"Service '{service_name}': device entries must be strings, "
                            f"got {type(device).__name__}"
                        )

            # Validate cap_add if present (v2.1.8 - Quick Wins)
            if 'cap_add' in service_config:
                cap_add = service_config['cap_add']

                if not isinstance(cap_add, list):
                    raise ComposeValidationError(
                        f"Service '{service_name}': cap_add must be a list, "
                        f"got {type(cap_add).__name__}"
                    )

                for cap in cap_add:
                    if not isinstance(cap, str):
                        raise ComposeValidationError(
                            f"Service '{service_name}': cap_add entries must be strings, "
                            f"got {type(cap).__name__}"
                        )

            # Validate cap_drop if present (v2.1.8 - Quick Wins)
            if 'cap_drop' in service_config:
                cap_drop = service_config['cap_drop']

                if not isinstance(cap_drop, list):
                    raise ComposeValidationError(
                        f"Service '{service_name}': cap_drop must be a list, "
                        f"got {type(cap_drop).__name__}"
                    )

                for cap in cap_drop:
                    if not isinstance(cap, str):
                        raise ComposeValidationError(
                            f"Service '{service_name}': cap_drop entries must be strings, "
                            f"got {type(cap).__name__}"
                        )

    def _is_valid_port_mapping(self, port_spec) -> bool:
        """
        Check if port mapping is valid.

        Valid formats:
        - "80:80"
        - "8080:80"
        - "8080:80/tcp"
        - "127.0.0.1:8080:80"
        """
        if not isinstance(port_spec, str):
            return False

        # Pattern: [host:]host_port:container_port[/protocol]
        pattern = r'^((\d{1,3}\.){3}\d{1,3}:)?\d+:\d+(/(tcp|udp))?$'
        return bool(re.match(pattern, port_spec))

    def validate_dependencies(self, compose_data: dict):
        """
        Validate service dependencies are valid and acyclic.

        Args:
            compose_data: Parsed compose dict

        Raises:
            ComposeValidationError: If dependency references missing service
            DependencyCycleError: If circular dependencies detected
        """
        if 'services' not in compose_data:
            return

        services = compose_data['services']

        # Check each service's dependencies
        for service_name, service_config in services.items():
            if 'depends_on' not in service_config:
                continue

            depends_on = service_config['depends_on']

            # depends_on can be a list or a dict (for healthchecks)
            if isinstance(depends_on, dict):
                dep_names = list(depends_on.keys())
            elif isinstance(depends_on, list):
                dep_names = depends_on
            else:
                continue

            # Check for self-dependency
            if service_name in dep_names:
                raise DependencyCycleError(f"Service '{service_name}' depends on itself")

            # Check that all dependencies exist
            for dep_name in dep_names:
                if dep_name not in services:
                    raise ComposeValidationError(
                        f"Service '{dep_name}' not found (required by '{service_name}')"
                    )

        # Check for cycles using DFS
        self._detect_cycles(services)

    def _detect_cycles(self, services: dict):
        """
        Detect circular dependencies using depth-first search.

        Raises:
            DependencyCycleError: If cycle detected
        """
        # Track visited nodes in current path
        visiting = set()
        # Track fully processed nodes
        visited = set()

        def visit(service_name: str, path: list):
            if service_name in visiting:
                # Found a cycle
                cycle_path = ' -> '.join(path + [service_name])
                raise DependencyCycleError(
                    f"Dependency cycle detected: {cycle_path}"
                )

            if service_name in visited:
                return

            visiting.add(service_name)

            # Get dependencies
            service_config = services.get(service_name, {})
            depends_on = service_config.get('depends_on', [])

            if isinstance(depends_on, dict):
                dep_names = list(depends_on.keys())
            elif isinstance(depends_on, list):
                dep_names = depends_on
            else:
                dep_names = []

            # Visit each dependency
            for dep_name in dep_names:
                visit(dep_name, path + [service_name])

            visiting.remove(service_name)
            visited.add(service_name)

        # Visit all services
        for service_name in services.keys():
            if service_name not in visited:
                visit(service_name, [])

    def get_startup_order(self, compose_data: dict) -> list:
        """
        Calculate service startup order based on dependencies.

        Uses topological sort (Kahn's algorithm).

        Args:
            compose_data: Parsed compose dict

        Returns:
            List of service names in startup order

        Raises:
            DependencyCycleError: If circular dependencies detected
        """
        if 'services' not in compose_data:
            return []

        services = compose_data['services']

        # Build dependency graph
        # in_degree[service] = number of services that depend on it
        in_degree = {service: 0 for service in services.keys()}
        # adjacency[service] = list of services that depend on this service
        adjacency = {service: [] for service in services.keys()}

        for service_name, service_config in services.items():
            depends_on = service_config.get('depends_on', [])

            if isinstance(depends_on, dict):
                dep_names = list(depends_on.keys())
            elif isinstance(depends_on, list):
                dep_names = depends_on
            else:
                dep_names = []

            for dep_name in dep_names:
                # service_name depends on dep_name
                # So dep_name must start before service_name
                adjacency[dep_name].append(service_name)
                in_degree[service_name] += 1

        # Topological sort using Kahn's algorithm
        queue = [service for service, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            # Sort to ensure deterministic order when multiple services have no dependencies
            queue.sort()
            service = queue.pop(0)
            result.append(service)

            # Remove this service from the graph
            for dependent in adjacency[service]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        # If we didn't process all services, there's a cycle
        if len(result) != len(services):
            raise DependencyCycleError("Dependency cycle detected")

        return result

    def validate(self, compose_yaml: str) -> dict:
        """
        Run all validation steps.

        Args:
            compose_yaml: YAML content as string

        Returns:
            Dict with 'valid' boolean and 'startup_order' list

        Raises:
            ComposeValidationError: If any validation fails
        """
        # Step 1: YAML safety check
        self.validate_yaml_safety(compose_yaml)

        # Step 2: Parse YAML
        parser = ComposeParser()
        try:
            compose_data = parser.parse(compose_yaml)
        except ComposeParseError as e:
            raise ComposeValidationError(f"Parse error: {e}")

        # Step 3: Validate required fields
        self.validate_required_fields(compose_data)

        # Step 4: Validate service configuration
        self.validate_service_configuration(compose_data)

        # Step 5: Validate dependencies
        self.validate_dependencies(compose_data)

        # Step 6: Calculate startup order
        startup_order = self.get_startup_order(compose_data)

        return {
            'valid': True,
            'startup_order': startup_order
        }
