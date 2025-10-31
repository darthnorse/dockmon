"""
Agent manager for registration, authentication, and lifecycle management.

Handles:
- Registration token generation and validation (15-minute expiry)
- Agent registration with token-based authentication
- Agent reconnection with agent_id validation
- Host creation for agent-based connections
"""
import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from database import RegistrationToken, Agent, DockerHostDB


class AgentManager:
    """Manages agent registration and lifecycle"""

    def __init__(self, db_session: Session):
        """
        Initialize AgentManager.

        Args:
            db_session: SQLAlchemy database session
        """
        self.db = db_session

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

        token_record = RegistrationToken(
            token=token,
            created_by_user_id=user_id,
            created_at=now,
            expires_at=now + timedelta(minutes=15),
            used=False,
            used_at=None
        )

        self.db.add(token_record)
        self.db.commit()
        self.db.refresh(token_record)

        return token_record

    def validate_registration_token(self, token: str) -> bool:
        """
        Validate registration token is valid, unused, and not expired.

        Args:
            token: Token string to validate

        Returns:
            bool: True if valid, False otherwise
        """
        token_record = self.db.query(RegistrationToken).filter_by(token=token).first()

        if not token_record:
            return False

        if token_record.used:
            return False

        now = datetime.utcnow()  # Naive UTC datetime for comparison with SQLite datetime
        if token_record.expires_at <= now:
            return False

        return True

    def validate_permanent_token(self, token: str) -> bool:
        """
        Validate permanent token (agent_id) exists.

        Args:
            token: Permanent token (agent_id)

        Returns:
            bool: True if valid agent_id exists, False otherwise
        """
        agent = self.db.query(Agent).filter_by(id=token).first()
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
        version = registration_data.get("version")
        proto_version = registration_data.get("proto_version")
        capabilities = registration_data.get("capabilities", {})

        # Check if token is a permanent token (agent_id for reconnection)
        is_permanent_token = self.validate_permanent_token(token)

        # Validate token (either registration token or permanent token)
        if not is_permanent_token and not self.validate_registration_token(token):
            token_record = self.db.query(RegistrationToken).filter_by(token=token).first()
            if token_record and token_record.expires_at <= datetime.utcnow():
                return {"success": False, "error": "Registration token has expired"}
            elif token_record and token_record.used:
                return {"success": False, "error": "Registration token has already been used"}
            else:
                return {"success": False, "error": "Invalid registration token"}

        # If using permanent token, find existing agent
        if is_permanent_token:
            existing_agent = self.db.query(Agent).filter_by(id=token).first()
            if existing_agent and existing_agent.engine_id == engine_id:
                # Update existing agent with new version/capabilities
                existing_agent.version = version
                existing_agent.proto_version = proto_version
                existing_agent.capabilities = json.dumps(capabilities)
                existing_agent.status = "online"
                existing_agent.last_seen_at = datetime.utcnow()
                self.db.commit()

                return {
                    "success": True,
                    "agent_id": existing_agent.id,
                    "host_id": existing_agent.host_id,
                    "permanent_token": existing_agent.id
                }
            else:
                return {"success": False, "error": "Permanent token does not match engine_id"}

        # Check if engine_id already registered
        existing_agent = self.db.query(Agent).filter_by(engine_id=engine_id).first()
        if existing_agent:
            return {"success": False, "error": "Agent with this engine_id is already registered"}

        try:
            # Generate IDs
            agent_id = str(uuid.uuid4())
            host_id = str(uuid.uuid4())
            now = datetime.utcnow()  # Naive UTC datetime

            # Create host record
            host = DockerHostDB(
                id=host_id,
                name=f"Agent-{engine_id[:12]}",  # Use short engine ID
                url="agent://",  # Placeholder URL for agent connections (not used for WebSocket)
                connection_type="agent",
                created_at=now,
                updated_at=now
            )
            self.db.add(host)
            self.db.flush()  # Ensure host exists before creating agent

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
            self.db.add(agent)

            # Mark token as used
            token_record = self.db.query(RegistrationToken).filter_by(token=token).first()
            token_record.used = True
            token_record.used_at = now

            self.db.commit()

            return {
                "success": True,
                "agent_id": agent_id,
                "host_id": host_id,
                "permanent_token": agent_id  # Use agent_id as permanent token for reconnection
            }

        except IntegrityError as e:
            self.db.rollback()
            return {"success": False, "error": f"Database integrity error: {str(e)}"}
        except Exception as e:
            self.db.rollback()
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

        # Find agent
        agent = self.db.query(Agent).filter_by(id=agent_id).first()

        if not agent:
            return {"success": False, "error": "Agent not found"}

        # Validate engine_id matches
        if agent.engine_id != engine_id:
            return {"success": False, "error": "Engine_id mismatch: agent verification failed"}

        # Update last_seen_at
        agent.last_seen_at = datetime.utcnow()  # Naive UTC datetime
        agent.status = "online"
        self.db.commit()

        return {
            "success": True,
            "agent_id": agent_id
        }
