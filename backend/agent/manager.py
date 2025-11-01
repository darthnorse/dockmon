"""
Agent manager for registration, authentication, and lifecycle management.

Handles:
- Registration token generation and validation (15-minute expiry)
- Agent registration with token-based authentication
- Agent reconnection with agent_id validation
- Host creation for agent-based connections
"""
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from database import RegistrationToken, Agent, DockerHostDB, DatabaseManager

logger = logging.getLogger(__name__)


class AgentManager:
    """Manages agent registration and lifecycle"""

    def __init__(self):
        """
        Initialize AgentManager.

        Creates short-lived database sessions for each operation instead of
        using a persistent session (following the pattern used throughout DockMon).
        """
        self.db_manager = DatabaseManager()  # Creates sessions as needed

    def generate_registration_token(self, user_id: int) -> RegistrationToken:
        """
        Generate a single-use registration token with 15-minute expiry.

        Args:
            user_id: ID of user creating the token

        Returns:
            RegistrationToken: Created token record
        """
        now = datetime.utcnow()  # Naive UTC datetime (SQLite compatible)
        token = str(uuid.uuid4())  # 36 characters with hyphens (e.g., 550e8400-e29b-41d4-a716-446655440000)

        logger.info(f"Generating registration token for user {user_id}: {token[:8]}...")

        with self.db_manager.get_session() as session:
            token_record = RegistrationToken(
                token=token,
                created_by_user_id=user_id,
                created_at=now,
                expires_at=now + timedelta(minutes=15),
                used=False,
                used_at=None
            )

            session.add(token_record)
            session.commit()
            session.refresh(token_record)

            logger.info(f"Successfully created registration token {token[:8]}... (expires: {token_record.expires_at})")

            return token_record

    def validate_registration_token(self, token: str) -> bool:
        """
        Validate registration token is valid, unused, and not expired.

        Args:
            token: Token string to validate

        Returns:
            bool: True if valid, False otherwise
        """
        logger.info(f"Validating registration token {token[:8]}...")

        with self.db_manager.get_session() as session:
            token_record = session.query(RegistrationToken).filter_by(token=token).first()

            if not token_record:
                logger.warning(f"Token {token[:8]}... not found in database")
                return False

            if token_record.used:
                logger.warning(f"Token {token[:8]}... already used")
                return False

            now = datetime.utcnow()  # Naive UTC datetime for comparison with SQLite datetime
            if token_record.expires_at <= now:
                logger.warning(f"Token {token[:8]}... expired at {token_record.expires_at}")
                return False

            logger.info(f"Token {token[:8]}... is valid")
            return True

    def validate_permanent_token(self, token: str) -> bool:
        """
        Validate permanent token (agent_id) exists.

        Args:
            token: Permanent token (agent_id)

        Returns:
            bool: True if valid agent_id exists, False otherwise
        """
        with self.db_manager.get_session() as session:
            agent = session.query(Agent).filter_by(id=token).first()
            return agent is not None

    def register_agent(self, registration_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Register a new agent with token-based authentication.

        Creates:
        - Agent record with provided metadata
        - DockerHost record with connection_type='agent'
        - Marks registration token as used

        Args:
            registration_data: Dict containing:
                - token: Registration token
                - engine_id: Docker engine ID
                - version: Agent version
                - proto_version: Protocol version
                - capabilities: Dict of agent capabilities

        Returns:
            Dict with:
                - success: bool
                - agent_id: str (on success)
                - host_id: str (on success)
                - error: str (on failure)
        """
        token = registration_data.get("token")
        engine_id = registration_data.get("engine_id")
        hostname = registration_data.get("hostname")
        version = registration_data.get("version")
        proto_version = registration_data.get("proto_version")
        capabilities = registration_data.get("capabilities", {})

        # Log what we received for debugging
        logger.info(f"Registration data keys: {list(registration_data.keys())}")
        logger.info(f"Full registration data: {registration_data}")
        logger.info(f"Hostname: {hostname}, Engine ID: {engine_id[:12]}...")

        # Check if token is a permanent token (agent_id for reconnection)
        is_permanent_token = self.validate_permanent_token(token)

        # Validate token (either registration token or permanent token)
        if not is_permanent_token and not self.validate_registration_token(token):
            with self.db_manager.get_session() as session:
                token_record = session.query(RegistrationToken).filter_by(token=token).first()
                if token_record and token_record.expires_at <= datetime.utcnow():
                    return {"success": False, "error": "Registration token has expired"}
                elif token_record and token_record.used:
                    return {"success": False, "error": "Registration token has already been used"}
                else:
                    return {"success": False, "error": "Invalid registration token"}

        # If using permanent token, find existing agent
        if is_permanent_token:
            with self.db_manager.get_session() as session:
                existing_agent = session.query(Agent).filter_by(id=token).first()
                if existing_agent and existing_agent.engine_id == engine_id:
                    # Update existing agent with new version/capabilities
                    existing_agent.version = version
                    existing_agent.proto_version = proto_version
                    existing_agent.capabilities = json.dumps(capabilities)
                    existing_agent.status = "online"
                    existing_agent.last_seen_at = datetime.utcnow()

                    # Update host record with fresh system information
                    host = session.query(DockerHostDB).filter_by(id=existing_agent.host_id).first()
                    if host:
                        host.updated_at = datetime.utcnow()
                        # Update hostname if provided (agent may have been updated)
                        if hostname:
                            host.name = hostname
                        # Update system information (keep data fresh on reconnection)
                        if registration_data.get("os_type"):
                            host.os_type = registration_data.get("os_type")
                        if registration_data.get("os_version"):
                            host.os_version = registration_data.get("os_version")
                        if registration_data.get("kernel_version"):
                            host.kernel_version = registration_data.get("kernel_version")
                        if registration_data.get("docker_version"):
                            host.docker_version = registration_data.get("docker_version")
                        if registration_data.get("daemon_started_at"):
                            host.daemon_started_at = registration_data.get("daemon_started_at")
                        if registration_data.get("total_memory"):
                            host.total_memory = registration_data.get("total_memory")
                        if registration_data.get("num_cpus"):
                            host.num_cpus = registration_data.get("num_cpus")

                    session.commit()

                    return {
                        "success": True,
                        "agent_id": existing_agent.id,
                        "host_id": existing_agent.host_id,
                        "permanent_token": existing_agent.id
                    }
                else:
                    return {"success": False, "error": "Permanent token does not match engine_id"}

        # Check if engine_id already registered
        with self.db_manager.get_session() as session:
            existing_agent = session.query(Agent).filter_by(engine_id=engine_id).first()
            if existing_agent:
                return {"success": False, "error": "Agent with this engine_id is already registered"}

        # Generate IDs
        agent_id = str(uuid.uuid4())
        host_id = str(uuid.uuid4())
        now = datetime.utcnow()  # Naive UTC datetime

        logger.info(f"Registering new agent {agent_id[:8]}... with engine_id {engine_id[:12]}...")
        logger.info(f"System info - OS: {registration_data.get('os_type')} {registration_data.get('os_version')}, "
                    f"Docker: {registration_data.get('docker_version')}, "
                    f"Memory: {registration_data.get('total_memory')}, CPUs: {registration_data.get('num_cpus')}")

        # Use a NEW dedicated session for registration to ensure immediate commit
        # The WebSocket session stays open for the connection lifetime, preventing visibility
        with self.db_manager.get_session() as reg_session:
            try:
                # Create host record with hostname (fallback to engine_id if not provided)
                agent_name = hostname if hostname else f"Agent-{engine_id[:12]}"
                host = DockerHostDB(
                    id=host_id,
                    name=agent_name,
                    url="agent://",  # Placeholder URL for agent connections (not used for WebSocket)
                    connection_type="agent",
                    created_at=now,
                    updated_at=now,
                    # System information (aligned with legacy host schema)
                    os_type=registration_data.get("os_type"),
                    os_version=registration_data.get("os_version"),
                    kernel_version=registration_data.get("kernel_version"),
                    docker_version=registration_data.get("docker_version"),
                    daemon_started_at=registration_data.get("daemon_started_at"),
                    total_memory=registration_data.get("total_memory"),
                    num_cpus=registration_data.get("num_cpus")
                )
                reg_session.add(host)
                reg_session.flush()  # Ensure host exists before creating agent
                logger.info(f"Created host record: {agent_name} ({host_id[:8]}...)")

                # Create agent record
                agent = Agent(
                    id=agent_id,
                    host_id=host_id,
                    engine_id=engine_id,
                    version=version,
                    proto_version=proto_version,
                    capabilities=json.dumps(capabilities),  # Store as JSON string
                    status="online",
                    last_seen_at=now,
                    registered_at=now
                )
                reg_session.add(agent)
                logger.info(f"Created agent record: {agent_id[:8]}...")

                # Mark token as used
                token_record = reg_session.query(RegistrationToken).filter_by(token=token).first()
                if token_record:
                    token_record.used = True
                    token_record.used_at = now

                # Commit in the dedicated session (context manager will close it)
                reg_session.commit()
                logger.info(f"Successfully registered agent {agent_id[:8]}... (host: {agent_name}, host_id: {host_id[:8]}...)")

                return {
                    "success": True,
                    "agent_id": agent_id,
                    "host_id": host_id,
                    "permanent_token": agent_id  # Use agent_id as permanent token for reconnection
                }

            except IntegrityError as e:
                reg_session.rollback()
                return {"success": False, "error": f"Database integrity error: {str(e)}"}
            except Exception as e:
                reg_session.rollback()
                return {"success": False, "error": f"Registration failed: {str(e)}"}

    def reconnect_agent(self, reconnect_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Reconnect an existing agent.

        Validates agent_id exists and engine_id matches stored value.

        Args:
            reconnect_data: Dict containing:
                - agent_id: Agent ID
                - engine_id: Docker engine ID (must match stored value)

        Returns:
            Dict with:
                - success: bool
                - agent_id: str (on success)
                - error: str (on failure)
        """
        agent_id = reconnect_data.get("agent_id")
        engine_id = reconnect_data.get("engine_id")

        with self.db_manager.get_session() as session:
            # Find agent
            agent = session.query(Agent).filter_by(id=agent_id).first()

            if not agent:
                return {"success": False, "error": "Agent not found"}

            # Validate engine_id matches
            if agent.engine_id != engine_id:
                return {"success": False, "error": "Engine_id mismatch: agent verification failed"}

            # Update last_seen_at
            agent.last_seen_at = datetime.utcnow()  # Naive UTC datetime
            agent.status = "online"
            session.commit()

            return {
                "success": True,
                "agent_id": agent_id
            }

    def get_agent_for_host(self, host_id: str) -> str:
        """
        Get the agent ID for a given host ID.

        Args:
            host_id: Docker host ID

        Returns:
            Agent ID (str) if agent exists for this host, None otherwise
        """
        with self.db_manager.get_session() as session:
            agent = session.query(Agent).filter_by(host_id=host_id).first()
            return agent.id if agent else None
