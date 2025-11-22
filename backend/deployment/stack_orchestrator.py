"""
Docker Compose stack orchestrator.

Orchestrates multi-service deployments from Docker Compose files.
Handles dependency resolution, network/volume creation, and service lifecycle.
"""

import logging
from .compose_validator import ComposeValidator


logger = logging.getLogger(__name__)

# Constants for internal DockMon metadata keys
# These keys are used to pass network connection instructions from orchestrator to host_connector
_MANUAL_NETWORKS_KEY = '_dockmon_manual_networks'
_MANUAL_NETWORKING_CONFIG_KEY = '_dockmon_manual_networking_config'

# Docker container ID length (short format)
CONTAINER_ID_SHORT_LENGTH = 12


class StackOrchestrationError(Exception):
    """Raised when stack orchestration fails"""
    pass


class StackOrchestrator:
    """Orchestrator for Docker Compose stack deployments"""

    def __init__(self):
        self.validator = ComposeValidator()

    def get_service_groups(self, compose_data: dict) -> list:
        """
        Get service groups for parallel deployment.

        Groups services by dependency level - services in same group can be deployed in parallel.
        Uses topological sort levels.

        Returns:
            List of lists, where each inner list contains service names that can be deployed in parallel
        """
        if 'services' not in compose_data:
            return []

        services = compose_data['services']

        # Build dependency graph
        in_degree = {service: 0 for service in services.keys()}
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
                adjacency[dep_name].append(service_name)
                in_degree[service_name] += 1

        # Topological sort by levels (groups)
        groups = []
        remaining = set(services.keys())

        while remaining:
            # Find all services with no dependencies (in_degree == 0)
            current_group = [s for s in remaining if in_degree[s] == 0]

            if not current_group:
                # Shouldn't happen if validator ran, but safety check
                break

            groups.append(sorted(current_group))  # Sort for deterministic order

            # Remove processed services
            for service in current_group:
                remaining.remove(service)
                # Reduce in_degree for dependents
                for dependent in adjacency[service]:
                    in_degree[dependent] -= 1

        return groups

    def plan_deployment(self, compose_data: dict) -> list:
        """
        Plan deployment operations in correct order.

        Returns:
            List of operation dicts with 'type' and relevant parameters
        """
        operations = []

        # Step 1: Create networks (if any)
        if 'networks' in compose_data:
            for network_name, network_config in compose_data['networks'].items():
                # Skip external networks
                if network_config and network_config.get('external'):
                    continue

                operations.append({
                    'type': 'create_network',
                    'name': network_name,
                    'config': network_config or {}
                })

        # Step 2: Create volumes (if any)
        if 'volumes' in compose_data:
            for volume_name, volume_config in compose_data['volumes'].items():
                # Only create named volumes (not bind mounts)
                if not volume_name.startswith('/'):
                    operations.append({
                        'type': 'create_volume',
                        'name': volume_name,
                        'config': volume_config or {}
                    })

        # Step 3: Create services in dependency order
        service_groups = self.get_service_groups(compose_data)
        services = compose_data.get('services', {})

        for group in service_groups:
            for service_name in group:
                operations.append({
                    'type': 'create_service',
                    'name': service_name,
                    'config': services[service_name]
                })

        return operations

    def calculate_progress(
        self,
        current_phase: str,
        phase_percent: int,
        total_services: int,
        completed_services: int
    ) -> int:
        """
        Calculate overall stack deployment progress.

        Phases per service: pull_image (40%), creating (20%), starting (20%), health_check (20%)

        Args:
            current_phase: Current deployment phase
            phase_percent: Progress within current phase (0-100)
            total_services: Total number of services in stack
            completed_services: Number of fully completed services

        Returns:
            Overall progress percentage (0-100)
        """
        if total_services == 0:
            return 100

        # Phase weights (as percentage of single service deployment)
        phase_weights = {
            'pull_image': 40,
            'creating': 20,
            'starting': 20,
            'health_check': 20
        }

        # Progress of completed services
        completed_progress = (completed_services / total_services) * 100

        # Progress of current service
        if current_phase in phase_weights:
            # Calculate how much the current phase contributes to single service (0-40, 0-20, etc.)
            phase_contribution = (phase_weights[current_phase] / 100) * phase_percent
            # Scale to single service as part of total
            current_service_progress = phase_contribution / total_services
        else:
            current_service_progress = 0

        total_progress = completed_progress + current_service_progress

        return min(100, int(total_progress))

    def plan_rollback(
        self,
        created_services: list,
        created_networks: list = None,
        external_networks: list = None
    ) -> list:
        """
        Plan rollback operations for failed deployment.

        Removes services in reverse order, then networks, then volumes.

        Returns:
            List of rollback operation dicts
        """
        operations = []

        # Remove services in reverse order
        for service_name in reversed(created_services):
            operations.append({
                'type': 'remove_service',
                'name': service_name
            })

        # Remove created networks (but not external ones)
        if created_networks:
            external_set = set(external_networks or [])
            for network_name in created_networks:
                if network_name not in external_set:
                    operations.append({
                        'type': 'remove_network',
                        'name': network_name
                    })

        return operations

    def get_stop_order(self, compose_data: dict) -> list:
        """
        Get service stop order (reverse dependency order).

        Services that depend on others stop first.

        Returns:
            List of service names in stop order
        """
        # Get startup order, then reverse it
        start_order = self.validator.get_startup_order(compose_data)
        return list(reversed(start_order))

    def get_start_order(self, compose_data: dict) -> list:
        """
        Get service start order (dependency order).

        Returns:
            List of service names in start order
        """
        return self.validator.get_startup_order(compose_data)

    def plan_stack_removal(self, compose_data: dict) -> list:
        """
        Plan complete stack removal.

        Removes all services, networks, and volumes.

        Returns:
            List of removal operation dicts
        """
        operations = []

        # Stop and remove services in reverse dependency order
        services = compose_data.get('services', {})
        stop_order = self.get_stop_order(compose_data)

        for service_name in stop_order:
            operations.append({
                'type': 'remove_service',
                'name': service_name
            })

        # Remove networks (except external)
        if 'networks' in compose_data:
            for network_name, network_config in compose_data['networks'].items():
                if not (network_config and network_config.get('external')):
                    operations.append({
                        'type': 'remove_network',
                        'name': network_name
                    })

        # Remove volumes
        if 'volumes' in compose_data:
            for volume_name in compose_data['volumes'].keys():
                if not volume_name.startswith('/'):
                    operations.append({
                        'type': 'remove_volume',
                        'name': volume_name
                    })

        return operations

    def map_service_to_container_config(
        self,
        service_name: str,
        service_config: dict,
        compose_data: dict = None
    ) -> dict:
        """
        Map Docker Compose service config to Docker container create() config.

        Args:
            service_name: Name of the service
            service_config: Service configuration from compose file
            compose_data: Full compose data (needed for resolving service references in network_mode)

        Raises:
            StackOrchestrationError: If service uses unsupported features
        """
        # Check for unsupported features
        if 'build' in service_config:
            raise StackOrchestrationError(
                f"Service '{service_name}' uses 'build' which is not supported in v2.1. "
                f"Please use pre-built images only."
            )

        config = {}

        # Required: image
        if 'image' in service_config:
            config['image'] = service_config['image']

        # Ports - convert compose format to Docker SDK format
        if 'ports' in service_config:
            config['ports'] = {}
            for port_spec in service_config['ports']:
                if isinstance(port_spec, str):
                    parts = port_spec.split(':')
                    if len(parts) == 2:
                        host_port, container_port = parts
                        config['ports'][f"{container_port}/tcp"] = int(host_port)

        # Environment
        if 'environment' in service_config:
            config['environment'] = service_config['environment']

        # Volumes
        if 'volumes' in service_config:
            config['volumes'] = service_config['volumes']

        # Networks - HYBRID APPROACH (Bug Fix: Docker SDK networking)
        # CRITICAL: Docker SDK doesn't auto-connect when networking_config is passed to containers.create()
        # Solution: Use 'network' parameter for simple cases, manual connection for advanced cases
        # IMPORTANT: Check that network_mode wasn't set (mutually exclusive)
        if 'networks' in service_config:
            # Defensive check (validator and network_mode code should prevent this)
            # Check service_config (input) not config (output) - order independent
            if 'network_mode' in service_config:
                logger.error(f"Service '{service_name}': Both network_mode and networks set")
                raise StackOrchestrationError(
                    f"Service '{service_name}': Cannot use both 'network_mode' and 'networks'. "
                    f"These are mutually exclusive."
                )

            networks = service_config['networks']

            if isinstance(networks, list):
                # Simple list format: networks: [network1, network2]
                if len(networks) == 1:
                    # Single network, no advanced config - use 'network' parameter (works with Docker SDK)
                    config['network'] = networks[0]
                    logger.debug(f"Service '{service_name}': Using network parameter for single network: {networks[0]}")
                else:
                    # Multiple networks - need manual connection (networking_config doesn't work)
                    # Store list for host_connector to handle
                    config[_MANUAL_NETWORKS_KEY] = networks
                    logger.debug(f"Service '{service_name}': Multiple networks - will connect manually: {networks}")

            elif isinstance(networks, dict):
                # Dict format with endpoint configuration - requires manual connection
                # Build endpoint config for manual connection by host_connector
                endpoints_config = {}

                for network_name, network_config in networks.items():
                    endpoint_config = {}

                    # Handle static IP addresses
                    if network_config and isinstance(network_config, dict):
                        ipam_config = {}

                        # IPv4 static address
                        if 'ipv4_address' in network_config:
                            ipam_config['IPv4Address'] = network_config['ipv4_address']

                        # IPv6 static address
                        if 'ipv6_address' in network_config:
                            ipam_config['IPv6Address'] = network_config['ipv6_address']

                        if ipam_config:
                            endpoint_config['IPAMConfig'] = ipam_config

                        # Network aliases
                        if 'aliases' in network_config:
                            endpoint_config['Aliases'] = network_config['aliases']

                        # Links (legacy, but preserve if present)
                        if 'link_local_ips' in network_config:
                            endpoint_config['LinkLocalIPs'] = network_config['link_local_ips']

                    endpoints_config[network_name] = endpoint_config

                # Store for manual connection (networking_config parameter doesn't work)
                if endpoints_config:
                    config[_MANUAL_NETWORKING_CONFIG_KEY] = {
                        'EndpointsConfig': endpoints_config
                    }
                    logger.debug(f"Service '{service_name}': Advanced network config - will connect manually")

        # Command
        if 'command' in service_config:
            config['command'] = service_config['command']

        # Entrypoint
        if 'entrypoint' in service_config:
            config['entrypoint'] = service_config['entrypoint']

        # Hostname
        if 'hostname' in service_config:
            config['hostname'] = service_config['hostname']

        # Restart policy
        if 'restart' in service_config:
            restart = service_config['restart']
            if restart in ['always', 'unless-stopped', 'on-failure']:
                config['restart_policy'] = {'Name': restart}

        # Resource limits (Compose v2 syntax - backward compatibility)
        if 'mem_limit' in service_config:
            config['mem_limit'] = service_config['mem_limit']

        if 'cpus' in service_config:
            config['nano_cpus'] = int(float(service_config['cpus']) * 1e9)

        # Resource limits (Compose v3 syntax - deploy.resources)
        # v3 takes precedence over v2 if both are specified
        if 'deploy' in service_config:
            deploy = service_config['deploy']
            if 'resources' in deploy:
                resources = deploy['resources']

                # Resource limits (hard limits)
                if 'limits' in resources:
                    limits = resources['limits']
                    if 'memory' in limits:
                        config['mem_limit'] = limits['memory']
                    if 'cpus' in limits:
                        config['nano_cpus'] = int(float(limits['cpus']) * 1e9)

                # Resource reservations (soft limits / guaranteed resources)
                if 'reservations' in resources:
                    reservations = resources['reservations']
                    if 'memory' in reservations:
                        config['mem_reservation'] = reservations['memory']
                    # Note: CPU reservations not supported in standalone Docker
                    # (Swarm-only feature, silently ignored like Docker Compose does)

        # Healthcheck (Docker Compose healthcheck directive)
        if 'healthcheck' in service_config:
            from utils.duration_parser import parse_docker_duration

            hc_source = service_config['healthcheck']

            # Handle disable: true (removes healthcheck)
            if hc_source and hc_source.get('disable'):
                config['healthcheck'] = None
            elif hc_source:
                healthcheck = {}

                # Test command (required field)
                if 'test' in hc_source:
                    test = hc_source['test']
                    if isinstance(test, str):
                        # String format - pass through, Docker wraps in CMD-SHELL
                        healthcheck['test'] = test
                    elif isinstance(test, list):
                        # Array format - pass through as-is
                        healthcheck['test'] = test

                # Timing parameters (convert compose time strings to nanoseconds)
                if 'interval' in hc_source:
                    healthcheck['interval'] = parse_docker_duration(hc_source['interval'])

                if 'timeout' in hc_source:
                    healthcheck['timeout'] = parse_docker_duration(hc_source['timeout'])

                if 'retries' in hc_source:
                    healthcheck['retries'] = hc_source['retries']

                if 'start_period' in hc_source:
                    healthcheck['start_period'] = parse_docker_duration(hc_source['start_period'])

                config['healthcheck'] = healthcheck

        # Privileged
        if 'privileged' in service_config:
            config['privileged'] = service_config['privileged']

        # Labels
        if 'labels' in service_config:
            config['labels'] = service_config['labels']

        # User
        if 'user' in service_config:
            config['user'] = service_config['user']

        # Working directory
        if 'working_dir' in service_config:
            config['working_dir'] = service_config['working_dir']

        # Devices - hardware device mapping (USB, GPU, storage) (v2.1.8 - Quick Wins)
        if 'devices' in service_config:
            devices = service_config['devices']

            # Handle null gracefully
            if devices is None:
                logger.debug(f"Service '{service_name}': devices is null, ignoring")
            # Type check
            elif not isinstance(devices, list):
                logger.error(f"Service '{service_name}': devices must be list, got {type(devices)}")
                raise StackOrchestrationError(
                    f"Service '{service_name}': devices must be a list"
                )
            # Empty list - don't add to config (consistent with other directives)
            elif len(devices) == 0:
                logger.debug(f"Service '{service_name}': devices is empty list, ignoring")
            else:
                # Validate all entries are strings
                for device in devices:
                    if not isinstance(device, str):
                        logger.error(f"Service '{service_name}': device must be string, got {type(device)}")
                        raise StackOrchestrationError(
                            f"Service '{service_name}': each device must be a string"
                        )

                # Docker SDK accepts device strings in Compose format
                # Format: '/host/path:/container/path:permissions'
                # Pass through to Docker - it validates the format
                config['devices'] = devices
                logger.debug(f"Service '{service_name}': parsed {len(devices)} device(s)")

        # Extra hosts - add entries to /etc/hosts (v2.1.8 - Quick Wins)
        if 'extra_hosts' in service_config:
            extra_hosts = service_config['extra_hosts']

            if extra_hosts is None:
                logger.debug(f"Service '{service_name}': extra_hosts is null, ignoring")
            elif isinstance(extra_hosts, list):
                # Empty list - don't add to config
                if len(extra_hosts) == 0:
                    logger.debug(f"Service '{service_name}': extra_hosts is empty list, ignoring")
                else:
                    # List format: ['hostname:ip', 'hostname2:ip2']
                    # Validate all entries are strings
                    for entry in extra_hosts:
                        if not isinstance(entry, str):
                            logger.error(f"Service '{service_name}': extra_hosts entry must be string")
                            raise StackOrchestrationError(
                                f"Service '{service_name}': extra_hosts entries must be strings"
                            )

                    config['extra_hosts'] = extra_hosts
                    logger.debug(f"Service '{service_name}': parsed {len(extra_hosts)} extra_hosts")

            elif isinstance(extra_hosts, dict):
                # Empty dict - don't add to config
                if len(extra_hosts) == 0:
                    logger.debug(f"Service '{service_name}': extra_hosts is empty dict, ignoring")
                else:
                    # Dict format: {hostname: ip, hostname2: ip2}
                    # Convert to list format for Docker SDK
                    host_list = []
                    # Sort keys for deterministic order
                    for hostname in sorted(extra_hosts.keys()):
                        ip = extra_hosts[hostname]
                        if not isinstance(hostname, str) or not isinstance(ip, str):
                            logger.error(f"Service '{service_name}': extra_hosts keys/values must be strings")
                            raise StackOrchestrationError(
                                f"Service '{service_name}': extra_hosts hostname and IP must be strings"
                            )
                        host_list.append(f"{hostname}:{ip}")

                    config['extra_hosts'] = host_list
                    logger.debug(f"Service '{service_name}': parsed {len(host_list)} extra_hosts from dict")
            else:
                logger.error(f"Service '{service_name}': extra_hosts must be list or dict")
                raise StackOrchestrationError(
                    f"Service '{service_name}': extra_hosts must be a list or dict"
                )

        # Linux capabilities - add capabilities (v2.1.8 - Quick Wins)
        if 'cap_add' in service_config:
            cap_add = service_config['cap_add']

            if cap_add is None:
                logger.debug(f"Service '{service_name}': cap_add is null, ignoring")
            elif not isinstance(cap_add, list):
                logger.error(f"Service '{service_name}': cap_add must be list")
                raise StackOrchestrationError(
                    f"Service '{service_name}': cap_add must be a list"
                )
            elif len(cap_add) == 0:
                # Empty list - don't add to config (consistent)
                logger.debug(f"Service '{service_name}': cap_add is empty list, ignoring")
            else:
                # Validate all entries are strings
                for cap in cap_add:
                    if not isinstance(cap, str):
                        logger.error(f"Service '{service_name}': cap_add entries must be strings")
                        raise StackOrchestrationError(
                            f"Service '{service_name}': cap_add entries must be strings"
                        )
                config['cap_add'] = cap_add
                logger.debug(f"Service '{service_name}': cap_add = {cap_add}")

        # Linux capabilities - drop capabilities (v2.1.8 - Quick Wins)
        if 'cap_drop' in service_config:
            cap_drop = service_config['cap_drop']

            if cap_drop is None:
                logger.debug(f"Service '{service_name}': cap_drop is null, ignoring")
            elif not isinstance(cap_drop, list):
                logger.error(f"Service '{service_name}': cap_drop must be list")
                raise StackOrchestrationError(
                    f"Service '{service_name}': cap_drop must be a list"
                )
            elif len(cap_drop) == 0:
                # Empty list - don't add to config (consistent)
                logger.debug(f"Service '{service_name}': cap_drop is empty list, ignoring")
            else:
                # Validate all entries are strings
                for cap in cap_drop:
                    if not isinstance(cap, str):
                        logger.error(f"Service '{service_name}': cap_drop entries must be strings")
                        raise StackOrchestrationError(
                            f"Service '{service_name}': cap_drop entries must be strings"
                        )
                config['cap_drop'] = cap_drop
                logger.debug(f"Service '{service_name}': cap_drop = {cap_drop}")

        # network_mode - host, bridge, none, or container:name (v2.1.8 - Quick Wins)
        # IMPORTANT: Must check for conflict with networks directive
        if 'network_mode' in service_config:
            network_mode = service_config['network_mode']

            # Defensive type check (validator should catch this, but be safe)
            if not isinstance(network_mode, str):
                logger.error(f"Service '{service_name}': network_mode must be string, got {type(network_mode)}")
                raise StackOrchestrationError(
                    f"Service '{service_name}': network_mode must be a string"
                )

            # Explicit check for empty string (better error message)
            if not network_mode or network_mode.strip() == "":
                logger.error(f"Service '{service_name}': network_mode is empty")
                raise StackOrchestrationError(
                    f"Service '{service_name}': network_mode cannot be empty"
                )

            # CRITICAL: Check for conflict with networks directive
            # Docker doesn't allow both network_mode and custom networks
            # Check service_config (input) not config (output) - order independent
            if 'networks' in service_config:
                logger.error(f"Service '{service_name}': Cannot use both network_mode and networks")
                raise StackOrchestrationError(
                    f"Service '{service_name}': Cannot use both 'network_mode' and 'networks'. "
                    f"These are mutually exclusive."
                )

            # Resolve service:X references to actual container names
            # Docker Compose allows 'network_mode: service:X' but Docker runtime needs 'container:X'
            if network_mode.startswith('service:'):
                target_service = network_mode[8:]  # Remove 'service:' prefix

                # Resolve target service name to container name using same logic as executor
                if compose_data:
                    services = compose_data.get('services', {})
                    target_service_config = services.get(target_service)

                    if not target_service_config:
                        raise StackOrchestrationError(
                            f"Service '{service_name}': network_mode references unknown service '{target_service}'"
                        )

                    # Apply same naming logic as executor:
                    # 1. Use explicit container_name if present
                    # 2. Use {compose_name}_{service} if compose has name field
                    # 3. Use just {service} as default
                    if 'container_name' in target_service_config:
                        target_container_name = target_service_config['container_name']
                    elif 'name' in compose_data:
                        target_container_name = f"{compose_data['name']}_{target_service}"
                    else:
                        target_container_name = target_service

                    # Replace service:X with container:actual_name
                    network_mode = f"container:{target_container_name}"
                    logger.debug(f"Service '{service_name}': Resolved service:{target_service} -> container:{target_container_name}")
                else:
                    logger.warning(f"Service '{service_name}': Cannot resolve service:{target_service} (no compose_data provided)")

            config['network_mode'] = network_mode
            logger.debug(f"Service '{service_name}': network_mode = {network_mode}")

        return config

    def create_stack_metadata(
        self,
        deployment_id: str,
        host_id: str,
        services: list,
        container_ids: dict
    ) -> list:
        """
        Create deployment metadata for each service in stack.

        Args:
            deployment_id: Stack deployment ID (composite key)
            host_id: Host UUID
            services: List of service names
            container_ids: Dict mapping service_name -> container_short_id (12 chars)

        Returns:
            List of metadata dicts
        """
        metadata_list = []

        for service_name in services:
            if service_name not in container_ids:
                continue

            container_short_id = container_ids[service_name]
            container_composite_key = f"{host_id}:{container_short_id}"

            metadata = {
                'container_id': container_composite_key,
                'host_id': host_id,
                'deployment_id': deployment_id,
                'service_name': service_name,
                'is_managed': True
            }

            metadata_list.append(metadata)

        return metadata_list
