"""
State Management Module for DockMon
Handles container state, auto-restart configuration, and tags
"""

import logging
from typing import Dict

import docker
from docker import DockerClient
from fastapi import HTTPException

from database import DatabaseManager
from utils.keys import make_composite_key
from models.docker_models import DockerHost, derive_container_tags
from models.settings_models import GlobalSettings

logger = logging.getLogger(__name__)


class StateManager:
    """Manages container state, auto-restart, and tags"""

    def __init__(self, db: DatabaseManager, hosts: Dict[str, DockerHost], clients: Dict[str, DockerClient], settings: GlobalSettings):
        self.db = db
        self.hosts = hosts
        self.clients = clients
        self.settings = settings

        # In-memory state tracking
        # Note: These get replaced with shared references from DockerMonitor
        self.auto_restart_status: Dict[str, bool] = {}
        self.restart_attempts: Dict[str, int] = {}
        self.restarting_containers: Dict[str, bool] = {}

    def get_auto_restart_status(self, host_id: str, container_id: str) -> bool:
        """
        Get auto-restart status for a container.

        Args:
            host_id: Docker host ID
            container_id: Container ID

        Returns:
            True if auto-restart is enabled, False otherwise
        """
        container_key = make_composite_key(host_id, container_id)

        # Check in-memory cache first
        if container_key in self.auto_restart_status:
            return self.auto_restart_status[container_key]

        # Check database for explicit configuration
        config = self.db.get_auto_restart_config(host_id, container_id)
        if config:
            self.auto_restart_status[container_key] = config.enabled
            return config.enabled

        # No explicit configuration - use global default setting
        self.auto_restart_status[container_key] = self.settings.default_auto_restart
        return self.settings.default_auto_restart

    def toggle_auto_restart(self, host_id: str, container_id: str, container_name: str, enabled: bool) -> None:
        """
        Toggle auto-restart for a container.

        Args:
            host_id: Docker host ID
            container_id: Container ID
            container_name: Container name
            enabled: True to enable auto-restart, False to disable
        """
        # Get host name for logging
        host = self.hosts.get(host_id)
        host_name = host.name if host else 'Unknown Host'

        # Use host_id:container_id as key to prevent collisions between hosts
        container_key = make_composite_key(host_id, container_id)
        self.auto_restart_status[container_key] = enabled
        if not enabled:
            self.restart_attempts[container_key] = 0
            self.restarting_containers[container_key] = False

        # Save to database
        self.db.set_auto_restart(host_id, container_id, container_name, enabled)
        logger.info(f"Auto-restart {'enabled' if enabled else 'disabled'} for container '{container_name}' on host '{host_name}'")

    def set_container_desired_state(self, host_id: str, container_id: str, container_name: str, desired_state: str, web_ui_url: str = None) -> None:
        """
        Set desired state for a container.

        Args:
            host_id: Docker host ID
            container_id: Container ID
            container_name: Container name
            desired_state: Desired state ('running' or 'stopped')
            web_ui_url: Optional URL to container's web interface
        """
        # Get host name for logging
        host = self.hosts.get(host_id)
        host_name = host.name if host else 'Unknown Host'

        # Save to database
        self.db.set_desired_state(host_id, container_id, container_name, desired_state, web_ui_url)
        logger.info(f"Desired state set to '{desired_state}' for container '{container_name}' on host '{host_name}'")

    def update_container_tags(self, host_id: str, container_id: str, container_name: str, tags_to_add: list[str], tags_to_remove: list[str]) -> dict:
        """
        Update container custom tags in database.

        Args:
            host_id: Docker host ID
            container_id: Container ID
            container_name: Container name
            tags_to_add: List of tags to add
            tags_to_remove: List of tags to remove

        Returns:
            dict with success status and updated tags list
        """
        if host_id not in self.clients:
            raise HTTPException(status_code=404, detail="Host not found")

        try:
            # Verify container exists
            client = self.clients[host_id]
            container = client.containers.get(container_id)

            # Get labels to derive compose/swarm tags
            labels = container.labels if container.labels else {}

            # Update custom tags in database
            container_key = make_composite_key(host_id, container_id)
            custom_tags = self.db.update_subject_tags(
                'container',
                container_key,
                tags_to_add,
                tags_to_remove,
                host_id_at_attach=host_id,
                container_name_at_attach=container_name
            )

            # Get all tags (compose, swarm, custom)
            derived_tags = derive_container_tags(labels)

            # Combine derived tags with custom tags (remove duplicates)
            all_tags_set = set(derived_tags + custom_tags)
            all_tags = sorted(list(all_tags_set))

            logger.info(f"Updated tags for container {container_name} on host {host_id}: +{tags_to_add}, -{tags_to_remove}")

            return {
                "success": True,
                "tags": all_tags,
                "custom_tags": custom_tags
            }

        except docker.errors.NotFound:
            raise HTTPException(status_code=404, detail="Container not found")
        except Exception as e:
            logger.error(f"Failed to update tags for container {container_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
