"""
Docker SDK Update Executor

Handles container updates via direct Docker SDK (for local and mTLS remote hosts).
This executor is used when the backend has direct access to the Docker socket.

Key responsibilities:
- Pull new image with progress tracking
- Extract and clone container configuration
- Create backup for rollback capability
- Create new container with updated image
- Health check verification
- Rollback on failure
- Dependent container recreation (network_mode: container:X)
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Any, Tuple, Callable, Awaitable

import docker
from sqlalchemy.exc import IntegrityError

from database import (
    DatabaseManager,
    ContainerUpdate,
    AutoRestartConfig,
    ContainerDesiredState,
    ContainerHttpHealthCheck,
    GlobalSettings,
    DeploymentMetadata,
    TagAssignment,
)
from utils.async_docker import async_docker_call
from utils.container_health import wait_for_container_health
from utils.image_pull_progress import ImagePullProgress
from utils.keys import make_composite_key
from utils.network_helpers import manually_connect_networks
from utils.cache import CACHE_REGISTRY
from updates.container_validator import ContainerValidator, ValidationResult
from updates.types import UpdateContext, UpdateResult, ProgressCallback

logger = logging.getLogger(__name__)

# Constants for internal DockMon metadata keys
_MANUAL_NETWORKS_KEY = '_dockmon_manual_networks'
_MANUAL_NETWORKING_CONFIG_KEY = '_dockmon_manual_networking_config'

# Docker container ID length (short format)
CONTAINER_ID_SHORT_LENGTH = 12


class DockerUpdateExecutor:
    """
    Executes container updates via Docker SDK.

    Used for hosts where the backend has direct Docker access:
    - Local host (unix socket)
    - Remote hosts with mTLS certificates

    The executor handles the full update workflow:
    1. Pull new image
    2. Extract container configuration
    3. Create backup (stop + rename)
    4. Create new container
    5. Start and health check
    6. Rollback on failure
    7. Cleanup backup on success
    """

    def __init__(
        self,
        db: DatabaseManager,
        monitor=None,
        image_pull_tracker: ImagePullProgress = None
    ):
        """
        Initialize Docker update executor.

        Args:
            db: Database manager for record updates
            monitor: DockerMonitor instance (for Docker clients and broadcasting)
            image_pull_tracker: Shared image pull progress tracker
        """
        self.db = db
        self.monitor = monitor
        self.image_pull_tracker = image_pull_tracker  # Can be None - will use fallback pull

    async def execute(
        self,
        context: UpdateContext,
        docker_client: docker.DockerClient,
        progress_callback: ProgressCallback,
        update_record: ContainerUpdate,
        is_podman: bool = False,
        emit_events: Callable = None,
        get_registry_credentials: Callable = None,
    ) -> UpdateResult:
        """
        Execute Docker SDK-based container update.

        Args:
            context: Update context with container info
            docker_client: Docker client for this host
            progress_callback: Async callback for progress updates
            update_record: Database record with update info
            is_podman: True if target host runs Podman
            emit_events: Callback dict for event emission (started, completed, failed, etc.)
            get_registry_credentials: Callback to get registry auth

        Returns:
            UpdateResult with success/failure and new container ID
        """
        backup_container = None
        backup_name = ''
        new_container = None
        new_container_id = None

        try:
            # Get container object from Docker
            try:
                old_container = await async_docker_call(
                    docker_client.containers.get, context.container_id
                )
            except docker.errors.NotFound:
                return UpdateResult.failure_result(
                    "Container not found"
                )
            except Exception as e:
                return UpdateResult.failure_result(
                    f"Error getting container: {e}"
                )

            # Step 1: Pull new image
            logger.info(f"Pulling new image: {context.new_image}")
            await progress_callback("pulling", 20, "Starting image pull")

            auth_config = None
            if get_registry_credentials:
                auth_config = get_registry_credentials(context.new_image)
                if auth_config:
                    logger.info(f"Using registry credentials for image pull")

            try:
                if self.image_pull_tracker:
                    await self.image_pull_tracker.pull_with_progress(
                        docker_client,
                        context.new_image,
                        context.host_id,
                        context.container_id,
                        auth_config=auth_config,
                        event_type="container_update_layer_progress"
                    )
                else:
                    await self._pull_image(docker_client, context.new_image, auth_config)
            except Exception as pull_error:
                logger.warning(f"Streaming pull failed, falling back: {pull_error}")
                await self._pull_image(docker_client, context.new_image, auth_config)

            # Step 2: Inspect images for label handling
            logger.info("Inspecting image labels")
            old_image_labels = await self._get_image_labels(docker_client, old_container.image.id)
            new_image_labels = await self._get_image_labels(docker_client, context.new_image)

            # Step 3: Find dependent containers (network_mode: container:X)
            dependent_containers = await self._get_dependent_containers(
                docker_client, old_container, context.container_name, context.container_id
            )
            if dependent_containers:
                logger.info(f"Found {len(dependent_containers)} dependent container(s)")

            # Step 4: Extract container configuration
            logger.info("Extracting container configuration")
            await progress_callback("configuring", 35, "Reading container configuration")

            container_config = await self._extract_container_config_v2(
                old_container,
                docker_client,
                old_image_labels=old_image_labels,
                new_image_labels=new_image_labels,
                is_podman=is_podman
            )

            # Step 5: Create backup (stop + rename)
            logger.info(f"Creating backup of {context.container_name}")
            await progress_callback("backup", 50, "Creating backup for rollback")

            backup_container, backup_name = await self._rename_container_to_backup(
                docker_client, old_container, context.container_name
            )

            if not backup_container:
                return UpdateResult.failure_result(
                    "Unable to create backup (container may be stuck)"
                )

            logger.info(f"Backup created: {backup_name}")

            # Step 6: Create new container
            logger.info(f"Creating new container with image {context.new_image}")
            await progress_callback("creating", 65, "Creating new container")

            new_container = await self._create_container_v2(
                docker_client,
                context.new_image,
                container_config,
                is_podman=is_podman
            )
            new_container_id = new_container.short_id

            # Step 7: Start new container
            logger.info(f"Starting new container {context.container_name}")
            await async_docker_call(new_container.start)
            await progress_callback("starting", 80, "Starting new container")

            # Step 8: Wait for health check
            health_check_timeout = self._get_health_check_timeout()
            logger.info(f"Waiting for health check (timeout: {health_check_timeout}s)")
            await progress_callback("health_check", 90, "Waiting for health check")

            is_healthy = await wait_for_container_health(
                docker_client,
                new_container_id,
                timeout=health_check_timeout
            )

            if not is_healthy:
                logger.error(f"Health check failed, initiating rollback")

                rollback_success = await self._rollback_container(
                    docker_client,
                    backup_container,
                    backup_name,
                    context.container_name,
                    new_container
                )

                error_msg = f"Health check timeout after {health_check_timeout}s"
                if rollback_success:
                    error_msg += " - Successfully rolled back"
                else:
                    error_msg += f" - CRITICAL: Rollback failed, backup: {backup_name}"

                return UpdateResult.failure_result(error_msg, rollback_performed=rollback_success)

            # Step 9: Recreate dependent containers (if any)
            if dependent_containers:
                logger.info(f"Recreating {len(dependent_containers)} dependent container(s)")
                failed_deps = await self._recreate_dependents(
                    docker_client, dependent_containers, new_container.id, is_podman
                )
                if failed_deps:
                    logger.warning(f"Failed to recreate dependents: {failed_deps}")

            # Step 10: Cleanup backup
            logger.info(f"Cleaning up backup container {backup_name}")
            await self._cleanup_backup_container(docker_client, backup_container, backup_name)

            # Invalidate caches
            for name, fn in CACHE_REGISTRY.items():
                fn.invalidate()
                logger.debug(f"Invalidated cache: {name}")

            await progress_callback("completed", 100, "Update completed successfully")

            return UpdateResult.success_result(new_container_id)

        except Exception as e:
            logger.error(f"Error executing Docker update: {e}", exc_info=True)

            # Attempt rollback if we have a backup
            if backup_container:
                logger.warning(f"Attempting rollback due to exception")
                rollback_success = await self._rollback_container(
                    docker_client,
                    backup_container,
                    backup_name,
                    context.container_name,
                    new_container
                )

                error_msg = f"Update failed: {str(e)}"
                if rollback_success:
                    error_msg += " - Successfully rolled back"
                else:
                    error_msg += f" - CRITICAL: Rollback failed, backup: {backup_name}"

                return UpdateResult.failure_result(error_msg, rollback_performed=rollback_success)

            return UpdateResult.failure_result(f"Update failed: {str(e)}")

    async def _pull_image(
        self,
        client: docker.DockerClient,
        image: str,
        auth_config: dict = None,
        timeout: int = 1800
    ):
        """Pull Docker image with timeout and optional authentication."""
        try:
            pull_kwargs = {}
            if auth_config:
                pull_kwargs['auth_config'] = auth_config

            await asyncio.wait_for(
                async_docker_call(client.images.pull, image, **pull_kwargs),
                timeout=timeout
            )
            logger.debug(f"Successfully pulled image {image}")
        except asyncio.TimeoutError:
            raise Exception(f"Image pull timed out after {timeout}s for {image}")
        except Exception as e:
            logger.error(f"Error pulling image {image}: {e}")
            raise

    async def _get_image_labels(
        self,
        client: docker.DockerClient,
        image_ref: str
    ) -> Dict[str, str]:
        """Get labels from an image."""
        try:
            image = await async_docker_call(client.images.get, image_ref)
            return image.attrs.get("Config", {}).get("Labels", {}) or {}
        except Exception as e:
            logger.warning(f"Failed to get image labels for {image_ref}: {e}")
            return {}

    def _extract_user_labels(
        self,
        old_container_labels: Dict[str, str],
        old_image_labels: Dict[str, str]
    ) -> Dict[str, str]:
        """
        Extract user-added labels by filtering out old image defaults.

        This preserves user customizations while allowing new image labels to take effect.
        """
        if old_container_labels is None:
            old_container_labels = {}
        if old_image_labels is None:
            old_image_labels = {}

        user_labels = old_container_labels.copy()

        for key, image_value in old_image_labels.items():
            container_value = user_labels.get(key)
            if container_value == image_value:
                user_labels.pop(key, None)

        logger.info(
            f"Label extraction: {len(old_container_labels)} container - "
            f"{len(old_image_labels)} image defaults = "
            f"{len(user_labels)} user labels to preserve"
        )

        return user_labels

    def _extract_network_config(self, attrs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract network configuration from container attributes."""
        networking = attrs.get("NetworkSettings", {})
        host_config = attrs.get("HostConfig", {})
        network_mode = host_config.get("NetworkMode")

        result = {
            "network": None,
            "network_mode": None,
        }

        def _extract_ipam_config(network_data):
            """Extract IPAM configuration only if user-configured."""
            ipam_config_raw = network_data.get("IPAMConfig")
            if not ipam_config_raw:
                return None

            ipam_config = {}
            if ipam_config_raw.get("IPv4Address"):
                ipam_config["IPv4Address"] = ipam_config_raw["IPv4Address"]
            if ipam_config_raw.get("IPv6Address"):
                ipam_config["IPv6Address"] = ipam_config_raw["IPv6Address"]

            return ipam_config if ipam_config else None

        networks = networking.get("Networks", {})
        if networks:
            custom_networks = {k: v for k, v in networks.items() if k not in ['bridge', 'host', 'none']}

            if not custom_networks:
                pass
            elif len(custom_networks) == 1:
                network_name, network_data = list(custom_networks.items())[0]
                has_static_ip = bool(network_data.get("IPAMConfig"))

                all_aliases = network_data.get("Aliases", []) or []
                preserved_aliases = [a for a in all_aliases if len(a) != CONTAINER_ID_SHORT_LENGTH]

                if has_static_ip or preserved_aliases:
                    result["network"] = network_name

                    endpoint_config = {}
                    ipam_config = _extract_ipam_config(network_data)
                    if ipam_config:
                        endpoint_config["IPAMConfig"] = ipam_config

                    if preserved_aliases:
                        endpoint_config["Aliases"] = preserved_aliases

                    if network_data.get("Links"):
                        endpoint_config["Links"] = network_data["Links"]

                    result[_MANUAL_NETWORKING_CONFIG_KEY] = {
                        "EndpointsConfig": {network_name: endpoint_config}
                    }
                else:
                    result["network"] = network_name

            else:
                endpoints_config = {}
                primary_network = list(custom_networks.keys())[0]
                result["network"] = primary_network

                for network_name, network_data in custom_networks.items():
                    endpoint_config = {}

                    ipam_config = _extract_ipam_config(network_data)
                    if ipam_config:
                        endpoint_config["IPAMConfig"] = ipam_config

                    if network_data.get("Aliases"):
                        preserved_aliases = [
                            a for a in network_data["Aliases"]
                            if len(a) != CONTAINER_ID_SHORT_LENGTH
                        ]
                        if preserved_aliases:
                            endpoint_config["Aliases"] = preserved_aliases

                    if network_data.get("Links"):
                        endpoint_config["Links"] = network_data["Links"]

                    endpoints_config[network_name] = endpoint_config

                result[_MANUAL_NETWORKING_CONFIG_KEY] = {
                    "EndpointsConfig": endpoints_config
                }

        if network_mode and network_mode not in ["default"]:
            if (_MANUAL_NETWORKING_CONFIG_KEY not in result and not result.get("network")):
                result["network_mode"] = network_mode

        return result

    async def _extract_container_config_v2(
        self,
        container,
        client: docker.DockerClient,
        old_image_labels: Dict[str, str] = None,
        new_image_labels: Dict[str, str] = None,
        is_podman: bool = False
    ) -> Dict[str, Any]:
        """
        Extract container configuration using passthrough approach (v2.2.0).

        Uses direct HostConfig passthrough to preserve ALL Docker fields including
        GPU support (DeviceRequests).
        """
        attrs = container.attrs
        config = attrs['Config']
        host_config = attrs['HostConfig'].copy()

        # Handle Podman compatibility
        if is_podman:
            nano_cpus = host_config.pop('NanoCpus', None)
            host_config.pop('MemorySwappiness', None)

            if nano_cpus and not host_config.get('CpuPeriod'):
                cpu_period = 100000
                cpu_quota = int(nano_cpus / 1e9 * cpu_period)
                host_config['CpuPeriod'] = cpu_period
                host_config['CpuQuota'] = cpu_quota

        # Resolve container:ID to container:name in NetworkMode
        if host_config.get('NetworkMode', '').startswith('container:'):
            ref_id = host_config['NetworkMode'].split(':')[1]
            try:
                ref_container = await async_docker_call(client.containers.get, ref_id)
                host_config['NetworkMode'] = f"container:{ref_container.name}"
            except Exception as e:
                logger.warning(f"Failed to resolve NetworkMode: {e}")

        # Extract user-added labels
        if old_image_labels is None:
            old_image_labels = {}
        labels = self._extract_user_labels(
            old_container_labels=config.get('Labels', {}),
            old_image_labels=old_image_labels
        )

        # Extract network configuration
        network_config = self._extract_network_config(attrs)

        return {
            'config': config,
            'host_config': host_config,
            'labels': labels,
            'network': network_config.get('network'),
            'network_mode_override': network_config.get('network_mode'),
            _MANUAL_NETWORKING_CONFIG_KEY: network_config.get(_MANUAL_NETWORKING_CONFIG_KEY),
            'container_name': attrs.get('Name', '').lstrip('/'),
        }

    async def _create_container_v2(
        self,
        client: docker.DockerClient,
        image: str,
        extracted_config: Dict[str, Any],
        is_podman: bool = False
    ) -> Any:
        """
        Create container using low-level API with passthrough (v2.2.0).

        Uses client.api.create_container for direct HostConfig passthrough.
        """
        try:
            config = extracted_config['config']
            host_config = extracted_config['host_config']
            network_mode = host_config.get('NetworkMode', '')

            if extracted_config.get('network_mode_override'):
                host_config['NetworkMode'] = extracted_config['network_mode_override']
                network_mode = extracted_config['network_mode_override']

            manual_networking_config = extracted_config.get(_MANUAL_NETWORKING_CONFIG_KEY)

            # Detect Docker API version for network handling
            from packaging import version
            api_version = version.parse(client.api.api_version)
            use_networking_config = api_version >= version.parse("1.44")

            networking_config = None
            if use_networking_config and manual_networking_config:
                networking_config = manual_networking_config
                logger.debug(f"Using networking_config at creation (API >= 1.44)")
            elif manual_networking_config:
                logger.debug(f"Will manually connect networks post-creation (API < 1.44)")

            container_name = extracted_config.get('container_name', '')
            response = await async_docker_call(
                client.api.create_container,
                image=image,
                name=container_name,
                hostname=config.get('Hostname') if not network_mode.startswith('container:') else None,
                user=config.get('User'),
                environment=config.get('Env'),
                command=config.get('Cmd'),
                entrypoint=config.get('Entrypoint'),
                working_dir=config.get('WorkingDir'),
                labels=extracted_config['labels'],
                host_config=host_config,
                networking_config=networking_config,
                healthcheck=config.get('Healthcheck'),
                stop_signal=config.get('StopSignal'),
                domainname=config.get('Domainname'),
                mac_address=config.get('MacAddress') if not network_mode.startswith('container:') else None,
                tty=config.get('Tty', False),
                stdin_open=config.get('OpenStdin', False),
            )

            container_id = response['Id']

            # Manual network connection for legacy API
            if not use_networking_config and manual_networking_config:
                try:
                    await manually_connect_networks(
                        container=client.containers.get(container_id),
                        manual_networks=None,
                        manual_networking_config=manual_networking_config,
                        client=client,
                        async_docker_call=async_docker_call
                    )
                except Exception:
                    try:
                        await async_docker_call(
                            client.containers.get(container_id).remove, force=True
                        )
                    except Exception:
                        pass
                    raise

            return client.containers.get(container_id)
        except Exception as e:
            logger.error(f"Error creating container: {e}")
            raise

    async def _rename_container_to_backup(
        self,
        client: docker.DockerClient,
        container,
        original_name: str
    ) -> Tuple[Optional[Any], str]:
        """Stop and rename container to backup name for rollback capability."""
        try:
            timestamp = int(time.time())
            backup_name = f"{original_name}-dockmon-backup-{timestamp}"

            logger.info(f"Creating backup: stopping and renaming {original_name} to {backup_name}")

            await async_docker_call(container.stop, timeout=30)
            logger.info(f"Stopped container {original_name}")

            await async_docker_call(container.rename, backup_name)
            logger.info(f"Renamed {original_name} to {backup_name}")

            return container, backup_name

        except Exception as e:
            logger.error(f"Error creating backup for {original_name}: {e}", exc_info=True)
            return None, ''

    async def _rollback_container(
        self,
        client: docker.DockerClient,
        backup_container,
        backup_name: str,
        original_name: str,
        new_container=None
    ) -> bool:
        """Rollback failed update by restoring backup container."""
        try:
            logger.warning(f"Starting rollback: restoring {backup_name} to {original_name}")

            await async_docker_call(backup_container.reload)
            backup_status = backup_container.status
            logger.info(f"Backup container {backup_name} status: {backup_status}")

            if backup_status == 'running':
                logger.warning(f"Backup is running (unexpected), stopping")
                try:
                    await async_docker_call(backup_container.stop, timeout=10)
                except Exception:
                    await async_docker_call(backup_container.kill)
            elif backup_status in ['restarting', 'dead']:
                try:
                    await async_docker_call(backup_container.kill)
                except Exception:
                    pass

            if new_container:
                try:
                    logger.info(f"Removing failed new container")
                    await async_docker_call(new_container.remove, force=True)
                except Exception as e:
                    logger.warning(f"Failed to cleanup new container: {e}")

            try:
                existing = await async_docker_call(client.containers.get, original_name)
                if existing:
                    await async_docker_call(existing.remove, force=True)
            except docker.errors.NotFound:
                pass
            except Exception as e:
                logger.warning(f"Error checking for existing container: {e}")

            logger.info(f"Renaming backup {backup_name} back to {original_name}")
            await async_docker_call(backup_container.rename, original_name)

            logger.info(f"Starting restored container {original_name}")
            await async_docker_call(backup_container.start)

            logger.warning(f"Rollback successful: {original_name} restored")
            return True

        except Exception as e:
            logger.critical(
                f"CRITICAL: Rollback failed for {original_name}: {e}. "
                f"Manual intervention required - backup: {backup_name}",
                exc_info=True
            )
            return False

    async def _cleanup_backup_container(
        self,
        client: docker.DockerClient,
        backup_container,
        backup_name: str
    ):
        """Remove backup container after successful update."""
        try:
            logger.info(f"Removing backup container: {backup_name}")
            await async_docker_call(backup_container.remove, force=True)
            logger.info(f"Successfully removed backup: {backup_name}")
        except Exception as e:
            logger.warning(f"Failed to remove backup {backup_name}: {e}")

    async def _get_dependent_containers(
        self,
        client: docker.DockerClient,
        container,
        container_name: str,
        container_id: str
    ) -> list:
        """Find containers that depend on this container via network_mode."""
        dependents = []

        try:
            all_containers = await async_docker_call(client.containers.list, all=True)

            for other in all_containers:
                if other.id == container.id:
                    continue

                network_mode = other.attrs.get('HostConfig', {}).get('NetworkMode', '')

                if network_mode in [f'container:{container_name}', f'container:{container.id}']:
                    logger.info(f"Found dependent container: {other.name}")

                    try:
                        image_name = (
                            other.image.tags[0] if other.image.tags
                            else other.attrs.get('Config', {}).get('Image', '')
                        )
                    except Exception:
                        image_name = other.attrs.get('Config', {}).get('Image', '')

                    dependents.append({
                        'container': other,
                        'name': other.name,
                        'id': other.short_id,
                        'image': image_name,
                        'old_network_mode': network_mode
                    })

        except Exception as e:
            logger.warning(f"Could not check for dependent containers: {e}")
            return []

        return dependents

    async def _recreate_dependents(
        self,
        client: docker.DockerClient,
        dependent_containers: list,
        new_parent_id: str,
        is_podman: bool
    ) -> list:
        """Recreate all dependent containers. Returns list of failed container names."""
        failed = []
        for dep in dependent_containers:
            try:
                success = await self._recreate_dependent_container(
                    client, dep, new_parent_id, is_podman
                )
                if not success:
                    failed.append(dep['name'])
            except Exception as e:
                logger.error(f"Failed to recreate dependent {dep['name']}: {e}")
                failed.append(dep['name'])
        return failed

    async def _recreate_dependent_container(
        self,
        client: docker.DockerClient,
        dep_info: dict,
        new_parent_container_id: str,
        is_podman: bool = False
    ) -> bool:
        """Recreate a dependent container with updated network_mode."""
        dep_container = dep_info['container']
        dep_name = dep_info['name']
        new_dep_container = None
        temp_name = None

        try:
            logger.info(f"Recreating dependent container: {dep_name}")

            config = await self._extract_container_config_v2(
                dep_container,
                client,
                new_image_labels=None,
                is_podman=is_podman
            )

            old_network_mode = config['host_config'].get('NetworkMode', '')
            config['host_config']['NetworkMode'] = f'container:{new_parent_container_id}'
            logger.info(f"Updated network_mode: {old_network_mode} → container:{new_parent_container_id}")

            logger.info(f"Stopping dependent container: {dep_name}")
            try:
                await async_docker_call(dep_container.stop, timeout=10)
            except Exception:
                await async_docker_call(dep_container.kill)

            temp_name = f"{dep_name}-temp-{int(time.time())}"
            await async_docker_call(dep_container.rename, temp_name)

            new_dep_container = await self._create_container_v2(
                client, dep_info['image'], config, is_podman
            )

            await async_docker_call(new_dep_container.start)

            await asyncio.sleep(3)
            await async_docker_call(new_dep_container.reload)

            if new_dep_container.status != 'running':
                raise Exception(f"Container failed to start (status: {new_dep_container.status})")

            temp_container = await async_docker_call(client.containers.get, temp_name)
            await async_docker_call(temp_container.remove, force=True)

            logger.info(f"Successfully recreated dependent container: {dep_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to recreate dependent {dep_name}: {e}", exc_info=True)

            try:
                if new_dep_container:
                    try:
                        await async_docker_call(new_dep_container.remove, force=True)
                    except Exception:
                        pass

                if temp_name:
                    temp_container = await async_docker_call(client.containers.get, temp_name)
                    await async_docker_call(temp_container.rename, dep_name)
                    await async_docker_call(temp_container.start)
                    logger.info(f"Rollback successful for dependent: {dep_name}")
            except Exception as rollback_error:
                logger.error(f"Rollback failed for dependent {dep_name}: {rollback_error}")

            return False

    def _get_health_check_timeout(self) -> int:
        """Get health check timeout from global settings."""
        try:
            with self.db.get_session() as session:
                settings = session.query(GlobalSettings).first()
                if settings:
                    return settings.health_check_timeout_seconds
        except Exception:
            pass
        return 120  # Default 2 minutes
