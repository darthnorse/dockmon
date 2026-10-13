"""
Health Check Config Sync for Agent-based health checks.

Provides utilities to push health check config changes to connected agents.
"""
import logging
from typing import Optional

from agent.connection_manager import agent_connection_manager
from agent.manager import AgentManager
from database import ContainerHttpHealthCheck, DatabaseManager

logger = logging.getLogger(__name__)


def _build_config_payload(config: ContainerHttpHealthCheck, container_id: str, host_id: str) -> dict:
    """Build the payload dict for a health check config message."""
    return {
        "container_id": container_id,
        "host_id": host_id,
        "enabled": config.enabled,
        "url": config.url,
        "method": config.method,
        "expected_status_codes": config.expected_status_codes,
        "timeout_seconds": config.timeout_seconds,
        "check_interval_seconds": config.check_interval_seconds,
        "follow_redirects": config.follow_redirects,
        "verify_ssl": config.verify_ssl,
        "headers_json": config.headers_json,
        "auth_config_json": config.auth_config_json,
    }


async def _send_to_host_agent(host_id: str, message: dict) -> bool:
    agent_id = AgentManager().get_agent_for_host(host_id)
    if not agent_id:
        logger.debug(f"No agent registered for host {host_id}")
        return False
    return await agent_connection_manager.send_command(agent_id, message)


async def push_health_check_config_to_agent(
    host_id: str,
    container_id: str,
    config: Optional[ContainerHttpHealthCheck] = None,
    db_manager: Optional[DatabaseManager] = None
) -> bool:
    """
    Push a health check config update to the host's agent.

    Args:
        host_id: Docker host ID (UUID)
        container_id: Container ID (12-char short ID, NOT composite key)
        config: Health check config object (if None, will query from DB)
        db_manager: DatabaseManager instance (optional, will create if not provided)

    Returns:
        bool: True if config was sent to agent, False otherwise
    """
    try:
        if config is None:
            if db_manager is None:
                db_manager = DatabaseManager()

            composite_key = f"{host_id}:{container_id}"
            with db_manager.get_session() as session:
                config = session.query(ContainerHttpHealthCheck).filter(
                    ContainerHttpHealthCheck.container_id == composite_key
                ).first()

                if not config:
                    logger.warning(f"No health check config found for {composite_key}")
                    return False

                if config.check_from != 'agent':
                    logger.debug(f"Health check for {composite_key} is not agent-based")
                    return False

                payload = _build_config_payload(config, container_id, host_id)
        else:
            if config.check_from != 'agent':
                logger.debug("Health check is not agent-based")
                return False
            payload = _build_config_payload(config, container_id, host_id)

        sent = await _send_to_host_agent(host_id, {
            "type": "health_check_config",
            "payload": payload
        })
        if sent:
            logger.info(f"Pushed health check config to agent for container {container_id}")
        return sent

    except Exception as e:
        logger.error(f"Error pushing health check config to agent: {e}", exc_info=True)
        return False


async def remove_health_check_config_from_agent(
    host_id: str,
    container_id: str
) -> bool:
    """
    Remove a health check config from the host's agent.

    Args:
        host_id: Docker host ID (UUID)
        container_id: Container ID (12-char short ID, NOT composite key)

    Returns:
        bool: True if removal was sent to agent, False otherwise
    """
    try:
        sent = await _send_to_host_agent(host_id, {
            "type": "health_check_config_remove",
            "payload": {
                "container_id": container_id
            }
        })
        if sent:
            logger.info(f"Removed health check config from agent for container {container_id}")
        return sent

    except Exception as e:
        logger.error(f"Error removing health check config from agent: {e}", exc_info=True)
        return False
