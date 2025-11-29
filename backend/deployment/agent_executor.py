"""
Agent-based deployment executor using native Docker Compose.

Routes deployment requests to agent and handles progress/completion events.
For agent hosts, deployments are executed via native `docker compose up`
on the agent instead of parsing compose files and creating containers individually.

Benefits:
- 100% Compose compatibility (all features work, current and future)
- Reduced maintenance (Docker Compose team maintains the complex logic)
- Network resilience (agent completes deployment in 1 round trip)
- Debugging (standard compose commands work for troubleshooting)
"""

import asyncio
import json
import logging
import yaml
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from database import (
    Deployment,
    DeploymentContainer,
    DeploymentMetadata,
    DatabaseManager,
)
from agent.command_executor import get_agent_command_executor, RetryPolicy

logger = logging.getLogger(__name__)


def validate_compose_for_agent(compose_content: str) -> tuple[bool, Optional[str]]:
    """
    Validate compose content before sending to agent.

    Returns (is_valid, error_message).
    Rejects compose files with build: directives - fail fast, don't waste round trip.

    Args:
        compose_content: Docker Compose YAML content

    Returns:
        Tuple of (is_valid, error_message). error_message is None if valid.
    """
    try:
        compose = yaml.safe_load(compose_content)
    except yaml.YAMLError as e:
        return False, f"Invalid YAML: {e}"

    if not compose or "services" not in compose:
        return False, "Compose file must contain 'services' section"

    # Check for build directives - reject with clear message
    for service_name, service_config in compose.get("services", {}).items():
        if isinstance(service_config, dict) and "build" in service_config:
            return False, (
                f"Service '{service_name}' uses 'build:' directive. "
                "Build directives are not supported for agent deployments. "
                "Please build your image and push to a registry, then use 'image:' instead."
            )

    return True, None


def container_params_to_compose(params: Dict[str, Any]) -> str:
    """
    Convert single container parameters to a docker-compose.yml format.

    This allows agent deployments to use the same compose pathway
    for both stack and single container deployments.

    Args:
        params: Container parameters dict with:
            - image (required): Image name with tag
            - name (required): Container name
            - ports (optional): List of port mappings ["8080:80", "443:443"]
            - volumes (optional): List of volume mounts ["/host:/container"]
            - environment (optional): Dict of environment variables {"KEY": "value"}
            - restart_policy (optional): Restart policy ("unless-stopped", etc.)
            - network_mode (optional): Network mode ("bridge", "host", etc.)
            - networks (optional): List of networks to connect to
            - labels (optional): Dict of labels
            - command (optional): Command to run
            - entrypoint (optional): Entrypoint
            - privileged (optional): Run in privileged mode
            - cap_add (optional): Capabilities to add
            - cap_drop (optional): Capabilities to drop
            - memory_limit (optional): Memory limit ("512m", "1g", etc.)
            - cpu_limit (optional): CPU limit (float, e.g., 1.5)

    Returns:
        Docker Compose YAML string
    """
    service_config = {
        "image": params["image"],
        "container_name": params.get("name", params.get("container_name")),
    }

    # Ports
    if params.get("ports"):
        service_config["ports"] = params["ports"]

    # Volumes
    if params.get("volumes"):
        service_config["volumes"] = params["volumes"]

    # Environment variables
    if params.get("environment"):
        env = params["environment"]
        # Convert dict to list format for compose
        if isinstance(env, dict):
            service_config["environment"] = env
        else:
            service_config["environment"] = env

    # Restart policy
    if params.get("restart_policy"):
        policy = params["restart_policy"]
        # Handle dict format {"Name": "unless-stopped"}
        if isinstance(policy, dict):
            service_config["restart"] = policy.get("Name", "no")
        else:
            service_config["restart"] = policy

    # Network mode
    if params.get("network_mode"):
        service_config["network_mode"] = params["network_mode"]

    # Networks (list format)
    if params.get("networks"):
        networks = params["networks"]
        if isinstance(networks, list):
            service_config["networks"] = networks

    # Labels
    if params.get("labels"):
        service_config["labels"] = params["labels"]

    # Command
    if params.get("command"):
        service_config["command"] = params["command"]

    # Entrypoint
    if params.get("entrypoint"):
        service_config["entrypoint"] = params["entrypoint"]

    # Security options
    if params.get("privileged"):
        service_config["privileged"] = params["privileged"]
    if params.get("cap_add"):
        service_config["cap_add"] = params["cap_add"]
    if params.get("cap_drop"):
        service_config["cap_drop"] = params["cap_drop"]

    # Resource limits (deploy section for compose v3)
    deploy_resources = {}
    if params.get("memory_limit") or params.get("mem_limit"):
        mem = params.get("memory_limit") or params.get("mem_limit")
        deploy_resources["limits"] = {"memory": mem}
    if params.get("cpu_limit") or params.get("cpus"):
        cpu = params.get("cpu_limit") or params.get("cpus")
        if "limits" not in deploy_resources:
            deploy_resources["limits"] = {}
        deploy_resources["limits"]["cpus"] = str(cpu)

    if deploy_resources:
        service_config["deploy"] = {"resources": deploy_resources}

    # Use container name as service name
    service_name = params.get("name", params.get("container_name", "app"))

    compose = {"services": {service_name: service_config}}
    return yaml.dump(compose, default_flow_style=False)


class AgentDeploymentExecutor:
    """
    Executes deployments via agent using native docker compose.

    For agent-based hosts, this executor sends the compose YAML to the agent
    which runs `docker compose up` natively. This provides 100% compose
    compatibility without reimplementing compose parsing logic.
    """

    def __init__(self, monitor=None, database_manager: Optional[DatabaseManager] = None):
        """
        Initialize agent deployment executor.

        Args:
            monitor: DockerMonitor instance for WebSocket broadcasting
            database_manager: DatabaseManager instance for database sessions
        """
        self.monitor = monitor
        self.db = database_manager or DatabaseManager()

        # Will be initialized lazily
        self._command_executor = None
        self._agent_manager = None

    def _get_command_executor(self):
        """Get or create AgentCommandExecutor instance."""
        if self._command_executor is None:
            self._command_executor = get_agent_command_executor()
        return self._command_executor

    def _get_agent_manager(self):
        """Get or create AgentManager instance."""
        if self._agent_manager is None:
            from agent.manager import AgentManager
            self._agent_manager = AgentManager()
        return self._agent_manager

    def _get_agent_id_for_host(self, host_id: str) -> str:
        """
        Get agent_id for a host.

        Args:
            host_id: Docker host ID

        Returns:
            Agent ID

        Raises:
            ValueError: If no agent registered for host
        """
        agent_manager = self._get_agent_manager()
        agent_id = agent_manager.get_agent_for_host(host_id)
        if not agent_id:
            raise ValueError(f"No agent registered for host {host_id}")
        return agent_id

    async def deploy(
        self,
        host_id: str,
        deployment_id: str,
        compose_content: str,
        project_name: str,
        environment: Optional[Dict[str, str]] = None,
        profiles: Optional[list[str]] = None,
        wait_for_healthy: bool = False,
        health_timeout: int = 60,
    ) -> bool:
        """
        Deploy via agent using native compose.

        1. Validate compose content (fail fast for build: directives)
        2. Send deploy_compose command to agent
        3. Wait for progress events (forward to UI via WebSocket)
        4. Wait for completion event
        5. Update database with container IDs

        Args:
            host_id: Docker host ID
            deployment_id: Deployment composite ID
            compose_content: Docker Compose YAML content
            project_name: Compose project name
            environment: Optional environment variables dict
            profiles: Optional list of compose profiles to activate (Phase 3)
            wait_for_healthy: Whether to wait for health checks (Phase 3)
            health_timeout: Health check timeout in seconds (default 60)

        Returns:
            True if deployment succeeded, False if it failed

        Raises:
            ValueError: If compose content is invalid (e.g., has build: directive)
        """
        # Validate compose content BEFORE sending to agent (fail fast)
        is_valid, error = validate_compose_for_agent(compose_content)
        if not is_valid:
            logger.error(f"Compose validation failed for deployment {deployment_id}: {error}")
            await self._update_deployment_status(
                deployment_id, "failed", error_message=error
            )
            return False

        # Get agent ID for this host
        try:
            agent_id = self._get_agent_id_for_host(host_id)
        except ValueError as e:
            logger.error(f"Failed to get agent for host {host_id}: {e}")
            await self._update_deployment_status(
                deployment_id, "failed", error_message=str(e)
            )
            return False

        # Get all registry credentials for compose deployment
        # We pass all stored credentials since we don't know which registries
        # the compose file might reference
        registry_credentials = []
        try:
            from utils.registry_credentials import get_all_registry_credentials
            registry_credentials = get_all_registry_credentials(self.db)
            if registry_credentials:
                logger.info(f"Including {len(registry_credentials)} registry credentials for compose deployment")
        except Exception as e:
            logger.warning(f"Failed to get registry credentials for compose deployment: {e}")

        # Build deploy_compose command
        command = {
            "type": "command",
            "command": "deploy_compose",
            "payload": {
                "deployment_id": deployment_id,
                "project_name": project_name,
                "compose_content": compose_content,
                "environment": environment or {},
                "action": "up",
                "profiles": profiles or [],
                "wait_for_healthy": wait_for_healthy,
                "health_timeout": health_timeout,
                "registry_credentials": registry_credentials,
            }
        }

        logger.info(
            f"Sending deploy_compose command for deployment {deployment_id} "
            f"to agent {agent_id} (project: {project_name})"
        )

        # Update deployment status to pulling/executing
        await self._update_deployment_status(
            deployment_id, "pulling_image", progress=10, stage="Sending to agent..."
        )

        # Execute command with retry policy
        # Compose deployments can take a long time (image pulls, etc.)
        executor = self._get_command_executor()
        retry_policy = RetryPolicy(
            max_attempts=1,  # No retry for deployments - let user retry manually
            initial_delay=1.0,
        )

        result = await executor.execute_command(
            agent_id,
            command,
            timeout=1800.0,  # 30 minutes timeout for compose up
            retry_policy=retry_policy
        )

        if not result.success:
            error_msg = result.error or "Unknown error during deployment"
            logger.error(f"Deployment {deployment_id} failed: {error_msg}")
            await self._update_deployment_status(
                deployment_id, "failed", error_message=error_msg
            )
            return False

        # Command was accepted - agent will send deploy_progress and deploy_complete events
        # The actual completion handling is done in handle_deploy_complete
        logger.info(f"Deployment {deployment_id} command accepted by agent")
        return True

    async def teardown(
        self,
        host_id: str,
        deployment_id: str,
        project_name: str,
        compose_content: str,
        remove_volumes: bool = False,
        profiles: Optional[list[str]] = None,
    ) -> bool:
        """
        Teardown deployment via agent using compose down.

        Args:
            host_id: Docker host ID
            deployment_id: Deployment composite ID
            project_name: Compose project name
            compose_content: Docker Compose YAML content (needed for compose down)
            remove_volumes: If True, also remove named volumes. Default False
                           to preserve database data, uploads, etc.
            profiles: Optional list of compose profiles (needed to teardown profile-specific services)

        Returns:
            True if teardown succeeded, False if it failed
        """
        # Get agent ID for this host
        try:
            agent_id = self._get_agent_id_for_host(host_id)
        except ValueError as e:
            logger.error(f"Failed to get agent for host {host_id}: {e}")
            return False

        # Build deploy_compose command for down
        command = {
            "type": "command",
            "command": "deploy_compose",
            "payload": {
                "deployment_id": deployment_id,
                "project_name": project_name,
                "compose_content": compose_content,
                "action": "down",
                "remove_volumes": remove_volumes,
                "profiles": profiles or [],
            }
        }

        logger.info(
            f"Sending compose down command for deployment {deployment_id} "
            f"to agent {agent_id} (remove_volumes={remove_volumes})"
        )

        # Execute command
        executor = self._get_command_executor()
        result = await executor.execute_command(
            agent_id,
            command,
            timeout=300.0,  # 5 minutes timeout for compose down
        )

        if not result.success:
            error_msg = result.error or "Unknown error during teardown"
            logger.error(f"Teardown {deployment_id} failed: {error_msg}")
            return False

        logger.info(f"Teardown {deployment_id} command accepted by agent")
        return True

    async def handle_deploy_progress(self, payload: Dict[str, Any]) -> None:
        """
        Handle deploy_progress event from agent.

        Updates deployment status and broadcasts to WebSocket clients.
        Supports both coarse progress and fine-grained per-service progress (Phase 3).

        Args:
            payload: Progress event payload from agent
                - deployment_id: Deployment composite ID
                - stage: Current stage (starting, executing, completed, failed, waiting_for_health)
                - message: Human-readable status message
                - services: Optional list of service statuses (Phase 3 fine-grained progress)
        """
        deployment_id = payload.get("deployment_id")
        stage = payload.get("stage", "executing")
        message = payload.get("message", "Deploying...")
        services = payload.get("services")  # Phase 3: per-service progress

        if not deployment_id:
            logger.warning("Received deploy_progress without deployment_id")
            return

        # Map agent stages to deployment statuses
        status_map = {
            "starting": "pulling_image",
            "executing": "creating",
            "waiting_for_health": "starting",  # Phase 3: health check waiting
            "completed": "running",
            "failed": "failed",
        }
        status = status_map.get(stage, "creating")

        # Estimate progress based on stage
        progress_map = {
            "starting": 20,
            "executing": 50,
            "waiting_for_health": 80,  # Phase 3: health check waiting
            "completed": 100,
            "failed": 100,
        }
        progress = progress_map.get(stage, 50)

        # If we have service-level progress, calculate more accurate progress
        if services and len(services) > 0:
            running_count = sum(1 for s in services if s.get("status") == "running")
            total_count = len(services)
            # Map 0-100% of services running to 50-90% overall progress
            service_progress = 50 + int((running_count / total_count) * 40)
            progress = service_progress
            logger.debug(
                f"Deploy progress for {deployment_id}: {running_count}/{total_count} services running"
            )

        logger.debug(f"Deploy progress for {deployment_id}: {stage} - {message}")

        # Update deployment status (only for intermediate stages)
        if stage not in ("completed", "failed"):
            await self._update_deployment_status(
                deployment_id, status, progress=progress, stage=message
            )

            # Emit service-level progress if available (Phase 3)
            if services:
                await self._emit_service_progress(deployment_id, services)

    async def handle_deploy_complete(self, payload: Dict[str, Any]) -> None:
        """
        Handle deploy_complete event from agent.

        Updates database with final status and container IDs.
        Supports partial success where some services are running but others failed.

        Args:
            payload: Completion event payload from agent
                - deployment_id: Deployment composite ID
                - success: Whether deployment fully succeeded
                - partial_success: Whether deployment partially succeeded (some services running)
                - services: Dict of service results (service_name -> ServiceResult)
                - failed_services: List of service names that failed
                - error: Error message if failed or partial
        """
        deployment_id = payload.get("deployment_id")
        success = payload.get("success", False)
        partial_success = payload.get("partial_success", False)
        services = payload.get("services", {})
        failed_services = payload.get("failed_services", [])
        error = payload.get("error")

        if not deployment_id:
            logger.warning("Received deploy_complete without deployment_id")
            return

        logger.info(
            f"Deploy complete for {deployment_id}: success={success}, "
            f"partial_success={partial_success}, services={len(services)}, "
            f"failed_services={failed_services}, error={error}"
        )

        if success:
            # Full success - all services running
            await self._link_containers_to_deployment(deployment_id, services)
            await self._update_deployment_status(
                deployment_id, "running", progress=100, stage="Deployment completed"
            )

        elif partial_success:
            # Partial success - some services running, others failed
            # Still link the successful containers (don't lose working services)
            running_services = {
                name: svc for name, svc in services.items()
                if name not in failed_services
            }
            if running_services:
                await self._link_containers_to_deployment(deployment_id, running_services)

            # Build detailed error message with per-service status
            error_details = self._build_partial_failure_message(
                services, failed_services, error
            )

            # Mark as partial (some services running but not complete)
            await self._update_deployment_status(
                deployment_id,
                "partial",
                progress=100,
                stage="Partial deployment - some services failed",
                error_message=error_details
            )

        else:
            # Full failure - no services running
            await self._update_deployment_status(
                deployment_id, "failed", error_message=error or "Deployment failed"
            )

    def _build_partial_failure_message(
        self,
        services: Dict[str, Any],
        failed_services: list,
        original_error: Optional[str]
    ) -> str:
        """
        Build detailed error message for partial deployment failures.

        Args:
            services: Dict of all service results
            failed_services: List of service names that failed
            original_error: Original error message from agent

        Returns:
            Formatted error message with per-service status
        """
        lines = []

        # Count running vs failed
        running_count = len(services) - len(failed_services)
        total_count = len(services)
        lines.append(f"Partial deployment: {running_count}/{total_count} services running")

        # List failed services with their status
        if failed_services:
            lines.append("")
            lines.append("Failed services:")
            for name in failed_services:
                svc = services.get(name, {})
                status = svc.get("status", "unknown")
                svc_error = svc.get("error", "")
                if svc_error:
                    lines.append(f"  - {name}: {status} ({svc_error})")
                else:
                    lines.append(f"  - {name}: {status}")

        # Include original error if present and not redundant
        if original_error and original_error not in "\n".join(lines):
            lines.append("")
            lines.append(f"Details: {original_error}")

        return "\n".join(lines)

    async def _link_containers_to_deployment(
        self,
        deployment_id: str,
        services: Dict[str, Any]
    ) -> None:
        """
        Link containers to deployment in database.

        Creates DeploymentContainer and DeploymentMetadata records
        for each service/container returned by the agent.

        Args:
            deployment_id: Deployment composite ID
            services: Dict of service results from agent
                - Each key is service name
                - Each value has: container_id, container_name, image, status
        """
        with self.db.get_session() as session:
            # Get deployment to find host_id
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            if not deployment:
                logger.error(f"Deployment {deployment_id} not found for container linking")
                return

            host_id = deployment.host_id

            # Remove old deployment_metadata records for this deployment (on redeploy)
            session.query(DeploymentMetadata).filter(
                DeploymentMetadata.deployment_id == deployment_id
            ).delete()

            # Remove old deployment_containers records
            session.query(DeploymentContainer).filter(
                DeploymentContainer.deployment_id == deployment_id
            ).delete()

            # Create new records with current container IDs
            utcnow = datetime.now(timezone.utc)
            for service_name, service_result in services.items():
                container_id = service_result.get("container_id", "")
                container_name = service_result.get("container_name", "")

                if not container_id:
                    logger.warning(f"Service {service_name} has no container_id")
                    continue

                # Ensure container_id is SHORT format (12 chars)
                short_id = container_id[:12] if len(container_id) > 12 else container_id
                composite_key = f"{host_id}:{short_id}"

                # Create DeploymentContainer record
                link = DeploymentContainer(
                    deployment_id=deployment_id,
                    container_id=short_id,
                    service_name=service_name,
                    created_at=utcnow
                )
                session.add(link)

                # Create DeploymentMetadata record
                metadata = DeploymentMetadata(
                    container_id=composite_key,
                    host_id=host_id,
                    deployment_id=deployment_id,
                    is_managed=True,
                    service_name=service_name,
                )
                session.add(metadata)

                logger.debug(
                    f"Linked container {short_id} ({container_name}) "
                    f"to deployment {deployment_id} as service {service_name}"
                )

            # Mark deployment as committed (containers exist in Docker)
            deployment.committed = True

            session.commit()
            logger.info(
                f"Linked {len(services)} containers to deployment {deployment_id}"
            )

    async def _update_deployment_status(
        self,
        deployment_id: str,
        status: str,
        progress: Optional[int] = None,
        stage: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """
        Update deployment status in database and broadcast to WebSocket.

        Args:
            deployment_id: Deployment composite ID
            status: New status (pulling_image, creating, starting, running, failed)
            progress: Progress percentage (0-100)
            stage: Human-readable stage description
            error_message: Error message if failed
        """
        with self.db.get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            if not deployment:
                logger.error(f"Deployment {deployment_id} not found for status update")
                return

            deployment.status = status
            deployment.updated_at = datetime.now(timezone.utc)

            if progress is not None:
                deployment.progress_percent = progress
            if stage is not None:
                deployment.current_stage = stage
            if error_message is not None:
                deployment.error_message = error_message
            if status in ("running", "partial", "failed", "rolled_back"):
                deployment.completed_at = datetime.now(timezone.utc)

            session.commit()

            # Broadcast progress event
            await self._emit_deployment_event(deployment)

    async def _emit_deployment_event(self, deployment: Deployment) -> None:
        """
        Emit deployment event for WebSocket broadcasting.

        Args:
            deployment: Deployment instance
        """
        # Build nested progress object (same format as DeploymentExecutor)
        progress = {
            "overall_percent": deployment.progress_percent or 0,
            "stage": deployment.current_stage or "",
        }

        # Map status to event type (must match frontend expectations)
        # Frontend expects: deployment_created, deployment_progress, deployment_completed,
        #                   deployment_failed, deployment_rolled_back
        status_to_event = {
            "running": "deployment_completed",
            "partial": "deployment_completed",  # Partial is still a completion state
            "failed": "deployment_failed",
            "rolled_back": "deployment_rolled_back",
        }
        event_type = status_to_event.get(deployment.status, "deployment_progress")

        # Base payload structure
        payload = {
            "type": event_type,
            "deployment_id": deployment.id,
            "host_id": deployment.host_id,
            "name": deployment.name,
            "status": deployment.status,
            "progress": progress,
            "created_at": deployment.created_at.isoformat() + "Z" if deployment.created_at else None,
            "completed_at": deployment.completed_at.isoformat() + "Z" if deployment.completed_at else None,
        }

        # Add error field only if present
        if deployment.error_message:
            payload["error"] = deployment.error_message

        # Broadcast via ConnectionManager (same as DeploymentExecutor)
        try:
            if self.monitor and hasattr(self.monitor, 'manager'):
                await self.monitor.manager.broadcast(payload)
        except Exception as e:
            logger.error(f"Error broadcasting deployment event: {e}")

    async def _emit_service_progress(
        self, deployment_id: str, services: list[Dict[str, Any]]
    ) -> None:
        """
        Emit per-service progress event for WebSocket broadcasting (Phase 3).

        This provides fine-grained progress updates showing which services
        are in which state during deployment.

        Args:
            deployment_id: Deployment composite ID
            services: List of service status dicts with name, status, image, message
        """
        payload = {
            "type": "deployment_service_progress",
            "deployment_id": deployment_id,
            "services": services,
        }

        try:
            if self.monitor and hasattr(self.monitor, 'manager'):
                await self.monitor.manager.broadcast(payload)
        except Exception as e:
            logger.debug(f"Error broadcasting service progress: {e}")


# Global singleton instance (lazy-initialized)
_agent_deployment_executor_instance: Optional[AgentDeploymentExecutor] = None


def get_agent_deployment_executor(monitor=None) -> AgentDeploymentExecutor:
    """
    Get the global AgentDeploymentExecutor singleton instance.

    Args:
        monitor: Optional DockerMonitor instance for WebSocket broadcasting.
                 If provided and singleton exists, updates the monitor reference.

    Returns:
        AgentDeploymentExecutor: Global instance
    """
    global _agent_deployment_executor_instance

    if _agent_deployment_executor_instance is None:
        from database import DatabaseManager
        _agent_deployment_executor_instance = AgentDeploymentExecutor(
            monitor=monitor,
            database_manager=DatabaseManager()
        )
        logger.info("AgentDeploymentExecutor singleton initialized")
    elif monitor is not None and _agent_deployment_executor_instance.monitor is None:
        # Update monitor if provided later (lazy initialization pattern)
        _agent_deployment_executor_instance.monitor = monitor

    return _agent_deployment_executor_instance
