"""
Agent-based Update Executor

Handles container updates via the DockMon agent (for agent-based remote hosts).
This executor is used when the backend communicates with a remote host via WebSocket
agent connection.

Key responsibilities:
- Send update commands to agent with correct format
- Handle agent self-update (special binary swap flow)
- Monitor update progress via agent events
- Update database after successful update
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Callable, Awaitable

from database import (
    DatabaseManager,
    ContainerUpdate,
    Agent,
)
from utils.keys import make_composite_key
from agent.command_executor import CommandStatus
from updates.types import UpdateContext, UpdateResult, ProgressCallback
from updates.database_updater import update_container_records_after_update

logger = logging.getLogger(__name__)


class AgentUpdateExecutor:
    """
    Executes container updates via DockMon agent.

    Used for hosts where the backend connects via WebSocket agent:
    - Remote hosts with agents installed
    - Hosts behind firewalls (agent connects outbound)

    Two update modes:
    1. Standard container update - Agent handles full workflow autonomously
    2. Agent self-update - Special binary swap mechanism
    """

    def __init__(
        self,
        db: DatabaseManager,
        agent_manager=None,
        agent_command_executor=None,
        monitor=None,
        get_registry_credentials: Callable = None,
    ):
        """
        Initialize Agent update executor.

        Args:
            db: Database manager for record updates
            agent_manager: AgentManager for getting agent IDs
            agent_command_executor: AgentCommandExecutor for sending commands
            monitor: DockerMonitor instance (for container info)
            get_registry_credentials: Callback to get registry auth for an image
        """
        self.db = db
        self.agent_manager = agent_manager
        self.agent_command_executor = agent_command_executor
        self.monitor = monitor
        self.get_registry_credentials = get_registry_credentials

    async def execute(
        self,
        context: UpdateContext,
        progress_callback: ProgressCallback,
        update_record: ContainerUpdate,
    ) -> UpdateResult:
        """
        Execute agent-based container update.

        The agent handles the entire update workflow autonomously:
        1. Inspect old container to clone configuration
        2. Pull new image
        3. Create backup (stop + rename)
        4. Create new container with new image
        5. Start new container
        6. Wait for health check
        7. Remove backup on success / rollback on failure

        Args:
            context: Update context with container info
            progress_callback: Async callback for progress updates
            update_record: Database record with update info

        Returns:
            UpdateResult with success/failure and new container ID
        """
        old_container_id = context.container_id
        new_container_id = None

        try:
            # Get agent for this host
            agent_id = self.agent_manager.get_agent_for_host(context.host_id)
            if not agent_id:
                return UpdateResult.failure_result("No agent registered for this host")

            # Check for agent self-update (special handling)
            if 'dockmon-agent' in update_record.current_image.lower():
                logger.info(f"Routing to agent self-update for '{context.container_name}'")
                return await self.execute_self_update(
                    context, progress_callback, update_record, agent_id
                )

            logger.info(f"Executing agent-based update for container {context.container_name}")

            # Send update_container command to agent
            # Agent handles the full workflow autonomously (network resilient)
            await progress_callback("initiating", 5, "Sending update command to agent")

            # Look up registry credentials for the image
            registry_auth = None
            if self.get_registry_credentials:
                try:
                    creds = self.get_registry_credentials(context.new_image)
                    if creds:
                        registry_auth = {
                            "username": creds["username"],
                            "password": creds["password"]
                        }
                        logger.info(f"Including registry credentials for agent image pull")
                except Exception as e:
                    logger.warning(f"Failed to get registry credentials, continuing without auth: {e}")

            # CORRECT command format for agent
            # Agent expects: type="command", command="update_container", payload={...}
            command = {
                "type": "command",
                "command": "update_container",
                "payload": {
                    "container_id": context.container_id,
                    "new_image": context.new_image,
                    "stop_timeout": 30,
                    "health_timeout": 120,
                    "registry_auth": registry_auth,
                }
            }

            logger.info(f"Sending update_container command to agent {agent_id}")

            result = await self.agent_command_executor.execute_command(
                agent_id,
                command,
                timeout=180.0  # 3 minutes for command acknowledgment
            )

            if result.status != CommandStatus.SUCCESS:
                error_msg = f"Agent rejected update command: {result.error}"
                logger.error(error_msg)
                return UpdateResult.failure_result(error_msg)

            logger.info(f"Agent {agent_id} accepted update command, waiting for completion...")
            await progress_callback("agent_updating", 20, "Agent is performing update")

            # Wait for update completion via progress polling
            update_success = await self._wait_for_agent_update_completion(
                context.host_id,
                context.container_id,
                context.container_name,
                timeout=300.0  # 5 minutes for full update
            )

            if not update_success:
                logger.error(f"Agent update failed or timed out for {context.container_name}")
                return UpdateResult.failure_result("Agent update failed or timed out")

            # Get new container ID from monitor
            new_container_info = await self._get_container_info_by_name(
                context.host_id, context.container_name
            )
            if new_container_info:
                new_container_id = new_container_info.get("id", "")[:12]
                logger.info(f"New container ID: {new_container_id}")
            else:
                new_container_id = old_container_id  # Fallback

            # Update database
            update_container_records_after_update(
                db=self.db,
                host_id=context.host_id,
                old_container_id=old_container_id,
                new_container_id=new_container_id,
                new_image=update_record.latest_image,
                new_digest=update_record.latest_digest,
                old_image=update_record.current_image,
            )

            await progress_callback("completed", 100, "Update completed successfully")

            return UpdateResult.success_result(new_container_id)

        except Exception as e:
            logger.error(f"Error executing agent-based update: {e}", exc_info=True)
            return UpdateResult.failure_result(f"Update failed: {str(e)}")

    async def execute_self_update(
        self,
        context: UpdateContext,
        progress_callback: ProgressCallback,
        update_record: ContainerUpdate,
        agent_id: str,
    ) -> UpdateResult:
        """
        Execute agent self-update via self_update command.

        Agents update themselves in-place by swapping the binary, not by
        recreating the container. This ensures the agent container ID remains stable.

        Flow:
        1. Send self_update command to agent with new image
        2. Agent downloads new binary and prepares update
        3. Agent exits and Docker restarts it automatically
        4. On startup, agent detects update lock and swaps binaries
        5. Wait for agent to reconnect with new version
        6. Update database

        Args:
            context: Update context with container info
            progress_callback: Progress callback
            update_record: Database record with update info
            agent_id: Agent UUID

        Returns:
            UpdateResult with success/failure
        """
        logger.info(
            f"Executing agent self-update for {context.container_name}: "
            f"{update_record.current_image} -> {update_record.latest_image}"
        )

        try:
            await progress_callback("initiating", 10, "Sending self-update command to agent")

            # Get agent's platform info for binary URL construction
            agent_os = "linux"   # Default
            agent_arch = "amd64"  # Default
            with self.db.get_session() as session:
                agent = session.query(Agent).filter_by(id=agent_id).first()
                if agent:
                    agent_os = agent.agent_os or "linux"
                    agent_arch = agent.agent_arch or "amd64"

            # Command format for self_update - supports both container and native modes
            # Agent picks the right approach based on its deployment:
            # - Container mode: uses 'image' to update own container
            # - Native mode: uses 'binary_url' to download and swap binary
            version = self._extract_version_from_image(update_record.latest_image)
            binary_url = f"https://github.com/darthnorse/dockmon/releases/download/v{version}/dockmon-agent-{agent_os}-{agent_arch}"
            command = {
                "type": "command",
                "command": "self_update",
                "payload": {
                    "image": update_record.latest_image,
                    "version": version,
                    # Binary URL for native mode (systemd deployments)
                    # TODO: Make base URL configurable via settings for self-hosted binary distribution
                    "binary_url": binary_url,
                }
            }
            logger.info(f"Self-update binary URL: {binary_url} (os={agent_os}, arch={agent_arch})")

            logger.info(f"Sending self_update command to agent {agent_id}")

            result = await self.agent_command_executor.execute_command(
                agent_id,
                command,
                timeout=150.0  # 2.5 minutes for download + prep
            )

            if result.status != CommandStatus.SUCCESS:
                error_msg = f"Failed to send self-update command: {result.error}"
                logger.error(error_msg)
                return UpdateResult.failure_result(error_msg)

            logger.info(f"Agent {agent_id} acknowledged self-update, waiting for reconnection...")
            await progress_callback("agent_reconnecting", 50, "Agent is restarting with new version")

            # Wait for agent to reconnect (agent exits and Docker restarts it)
            reconnected = await self._wait_for_agent_reconnection(
                agent_id,
                timeout=300.0  # 5 minutes
            )

            if not reconnected:
                error_msg = "Agent did not reconnect after self-update (timeout: 5 minutes)"
                logger.error(error_msg)
                return UpdateResult.failure_result(error_msg)

            # Validate new version
            new_version = await self._get_agent_version(agent_id)
            expected_version = self._extract_version_from_image(update_record.latest_image)

            logger.info(f"Agent reconnected with version: {new_version} (expected: {expected_version})")

            # Update database (container ID doesn't change for self-update)
            composite_key = make_composite_key(context.host_id, context.container_id)
            with self.db.get_session() as session:
                db_update = session.query(ContainerUpdate).filter_by(
                    container_id=composite_key
                ).first()

                if db_update:
                    db_update.current_image = update_record.latest_image
                    db_update.update_available = False
                    db_update.last_updated_at = datetime.now(timezone.utc)
                    session.commit()

            await progress_callback("completed", 100, "Agent self-update completed")

            # Return same container ID (self-update doesn't recreate container)
            return UpdateResult.success_result(context.container_id)

        except Exception as e:
            error_msg = f"Agent self-update failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return UpdateResult.failure_result(error_msg)

    async def _wait_for_agent_update_completion(
        self,
        host_id: str,
        container_id: str,
        container_name: str,
        timeout: float = 300.0
    ) -> bool:
        """Wait for agent update to complete by polling container state."""
        start_time = time.time()
        poll_interval = 3.0

        logger.info(f"Waiting for agent update completion for {container_name}")

        while (time.time() - start_time) < timeout:
            try:
                container_info = await self._get_container_info_by_name(host_id, container_name)

                if container_info:
                    state = container_info.get("state", "").lower()
                    status = container_info.get("status", "").lower()

                    if state == "running" or "up" in status:
                        logger.info(f"Container {container_name} is running after agent update")
                        return True

                await asyncio.sleep(poll_interval)

            except Exception as e:
                logger.warning(f"Error checking container state: {e}")
                await asyncio.sleep(poll_interval)

        logger.warning(f"Agent update timed out for container {container_name}")
        return False

    async def _wait_for_agent_reconnection(
        self,
        agent_id: str,
        timeout: float = 300.0
    ) -> bool:
        """Wait for agent to reconnect after self-update."""
        start_time = time.time()
        poll_interval = 2.0

        logger.info(f"Waiting for agent {agent_id} to reconnect")

        while (time.time() - start_time) < timeout:
            try:
                with self.db.get_session() as session:
                    agent = session.query(Agent).filter_by(id=agent_id).first()

                    if agent and agent.status == "online":
                        if agent.last_seen_at:
                            # SQLite stores datetimes without timezone, but we know they're UTC
                            last_seen_utc = agent.last_seen_at.replace(tzinfo=timezone.utc)
                            elapsed = (datetime.now(timezone.utc) - last_seen_utc).total_seconds()
                            if elapsed < 10:
                                logger.info(f"Agent {agent_id} reconnected successfully")
                                return True

            except Exception as e:
                logger.warning(f"Error checking agent status: {e}")

            await asyncio.sleep(poll_interval)

        logger.warning(f"Agent {agent_id} did not reconnect within {timeout} seconds")
        return False

    async def _get_agent_version(self, agent_id: str) -> str:
        """Get agent version from database."""
        try:
            with self.db.get_session() as session:
                agent = session.query(Agent).filter_by(id=agent_id).first()
                if agent:
                    return agent.version or "unknown"
        except Exception as e:
            logger.warning(f"Could not get agent version: {e}")
        return "unknown"

    def _extract_version_from_image(self, image: str) -> str:
        """Extract version tag from Docker image string."""
        if ':' in image:
            return image.split(':')[-1]
        return "latest"

    async def _get_container_info_by_name(
        self,
        host_id: str,
        container_name: str
    ) -> Optional[Dict]:
        """Get container info by name from the monitor."""
        if not self.monitor:
            return None

        try:
            containers = await self.monitor.get_containers()
            target_name = container_name.lstrip('/')

            for container in containers:
                if container.host_id != host_id:
                    continue

                name = getattr(container, 'name', '').lstrip('/')
                if name == target_name:
                    return container.dict() if hasattr(container, 'dict') else vars(container)

        except Exception as e:
            logger.warning(f"Error getting container by name: {e}")

        return None
