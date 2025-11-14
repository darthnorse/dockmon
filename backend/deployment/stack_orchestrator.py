"""
Docker Compose stack orchestrator.

Orchestrates multi-service deployments from Docker Compose files.
Handles dependency resolution, network/volume creation, and service lifecycle.
"""

from .compose_validator import ComposeValidator


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
        service_config: dict
    ) -> dict:
        """
        Map Docker Compose service config to Docker container create() config.

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

        # Networks - convert to Docker SDK networking_config format
        if 'networks' in service_config:
            networks = service_config['networks']
            if isinstance(networks, list):
                config['networking_config'] = {
                    'EndpointsConfig': {
                        network: {} for network in networks
                    }
                }

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

        # Resource limits
        if 'mem_limit' in service_config:
            config['mem_limit'] = service_config['mem_limit']

        if 'cpus' in service_config:
            config['nano_cpus'] = int(float(service_config['cpus']) * 1e9)

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
