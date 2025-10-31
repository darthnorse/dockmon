"""
Unit tests for agent registration functionality.

Tests the agent registration token generation, validation, and agent registration flow.
"""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base, RegistrationToken, Agent, DockerHostDB


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing"""
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestRegistrationTokenGeneration:
    """Test registration token generation"""

    def test_generate_registration_token(self, db_session):
        """Should generate a valid registration token"""
        from agent.manager import AgentManager

        manager = AgentManager(db_session)
        user_id = 1

        token_record = manager.generate_registration_token(user_id)

        assert token_record is not None
        assert token_record.token is not None
        assert len(token_record.token) == 36  # UUID format
        assert token_record.created_by_user_id == user_id
        assert token_record.used is False
        assert token_record.expires_at > datetime.utcnow()

    def test_token_expires_after_15_minutes(self, db_session):
        """Token should expire after 15 minutes"""
        from agent.manager import AgentManager

        manager = AgentManager(db_session)
        token_record = manager.generate_registration_token(user_id=1)

        expected_expiry = token_record.created_at + timedelta(minutes=15)

        # Allow 1 second tolerance for test execution time
        assert abs((token_record.expires_at - expected_expiry).total_seconds()) < 1

    def test_multiple_tokens_can_exist(self, db_session):
        """Multiple unused tokens can exist for a user"""
        from agent.manager import AgentManager

        manager = AgentManager(db_session)
        user_id = 1

        token1 = manager.generate_registration_token(user_id)
        token2 = manager.generate_registration_token(user_id)

        assert token1.token != token2.token

        # Both should be in database
        tokens = db_session.query(RegistrationToken).filter_by(created_by_user_id=user_id).all()
        assert len(tokens) == 2


class TestTokenValidation:
    """Test registration token validation"""

    def test_validate_valid_token(self, db_session):
        """Should validate a valid, unused, non-expired token"""
        from agent.manager import AgentManager

        manager = AgentManager(db_session)
        token_record = manager.generate_registration_token(user_id=1)

        is_valid = manager.validate_registration_token(token_record.token)

        assert is_valid is True

    def test_validate_expired_token(self, db_session):
        """Should reject expired token"""
        from agent.manager import AgentManager

        manager = AgentManager(db_session)

        # Create token that expired 1 minute ago
        expired_token = RegistrationToken(
            token="expired-token-uuid",
            created_by_user_id=1,
            created_at=datetime.utcnow() - timedelta(minutes=20),
            expires_at=datetime.utcnow() - timedelta(minutes=1),
            used=False
        )
        db_session.add(expired_token)
        db_session.commit()

        is_valid = manager.validate_registration_token("expired-token-uuid")

        assert is_valid is False

    def test_validate_used_token(self, db_session):
        """Should reject already-used token"""
        from agent.manager import AgentManager

        manager = AgentManager(db_session)

        # Create used token
        used_token = RegistrationToken(
            token="used-token-uuid",
            created_by_user_id=1,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(minutes=15),
            used=True,
            used_at=datetime.utcnow()
        )
        db_session.add(used_token)
        db_session.commit()

        is_valid = manager.validate_registration_token("used-token-uuid")

        assert is_valid is False

    def test_validate_nonexistent_token(self, db_session):
        """Should reject token that doesn't exist"""
        from agent.manager import AgentManager

        manager = AgentManager(db_session)

        is_valid = manager.validate_registration_token("nonexistent-token")

        assert is_valid is False


class TestAgentRegistration:
    """Test agent registration with tokens"""

    def test_register_agent_with_valid_token(self, db_session):
        """Should register agent with valid token and create host"""
        from agent.manager import AgentManager

        manager = AgentManager(db_session)
        token_record = manager.generate_registration_token(user_id=1)

        registration_data = {
            "token": token_record.token,
            "engine_id": "docker-engine-123",
            "version": "2.2.0",
            "proto_version": "1.0",
            "capabilities": {
                "stats_collection": True,
                "container_updates": True,
                "self_update": True
            }
        }

        result = manager.register_agent(registration_data)

        assert result["success"] is True
        assert "agent_id" in result
        assert "host_id" in result

        # Verify agent created in database
        agent = db_session.query(Agent).filter_by(id=result["agent_id"]).first()
        assert agent is not None
        assert agent.engine_id == "docker-engine-123"
        assert agent.version == "2.2.0"
        assert agent.status == "online"

        # Verify host created
        host = db_session.query(DockerHostDB).filter_by(id=result["host_id"]).first()
        assert host is not None
        assert host.connection_type == "agent"
        assert host.agent.id == result["agent_id"]

        # Verify token marked as used
        token = db_session.query(RegistrationToken).filter_by(token=token_record.token).first()
        assert token.used is True
        assert token.used_at is not None

    def test_register_agent_with_expired_token(self, db_session):
        """Should reject registration with expired token"""
        from agent.manager import AgentManager

        manager = AgentManager(db_session)

        # Create expired token
        expired_token = RegistrationToken(
            token="expired-token",
            created_by_user_id=1,
            created_at=datetime.utcnow() - timedelta(minutes=20),
            expires_at=datetime.utcnow() - timedelta(minutes=1),
            used=False
        )
        db_session.add(expired_token)
        db_session.commit()

        registration_data = {
            "token": "expired-token",
            "engine_id": "docker-engine-123",
            "version": "2.2.0",
            "proto_version": "1.0",
            "capabilities": {}
        }

        result = manager.register_agent(registration_data)

        assert result["success"] is False
        assert "error" in result
        assert "expired" in result["error"].lower()

    def test_register_agent_with_duplicate_engine_id(self, db_session):
        """Should reject registration if engine_id already registered"""
        from agent.manager import AgentManager

        manager = AgentManager(db_session)

        # Register first agent
        token1 = manager.generate_registration_token(user_id=1)
        registration_data1 = {
            "token": token1.token,
            "engine_id": "docker-engine-123",
            "version": "2.2.0",
            "proto_version": "1.0",
            "capabilities": {}
        }
        manager.register_agent(registration_data1)

        # Try to register second agent with same engine_id
        token2 = manager.generate_registration_token(user_id=1)
        registration_data2 = {
            "token": token2.token,
            "engine_id": "docker-engine-123",  # DUPLICATE
            "version": "2.2.0",
            "proto_version": "1.0",
            "capabilities": {}
        }

        result = manager.register_agent(registration_data2)

        assert result["success"] is False
        assert "already registered" in result["error"].lower()


class TestAgentReconnection:
    """Test agent reconnection with agent_id"""

    def test_reconnect_with_valid_agent_id(self, db_session):
        """Should allow reconnection with valid agent_id"""
        from agent.manager import AgentManager

        manager = AgentManager(db_session)

        # First, register an agent
        token = manager.generate_registration_token(user_id=1)
        registration_data = {
            "token": token.token,
            "engine_id": "docker-engine-123",
            "version": "2.2.0",
            "proto_version": "1.0",
            "capabilities": {}
        }
        reg_result = manager.register_agent(registration_data)
        agent_id = reg_result["agent_id"]

        # Now reconnect
        reconnect_data = {
            "agent_id": agent_id,
            "engine_id": "docker-engine-123"
        }

        result = manager.reconnect_agent(reconnect_data)

        assert result["success"] is True
        assert result["agent_id"] == agent_id

    def test_reconnect_with_mismatched_engine_id(self, db_session):
        """Should reject reconnection if engine_id doesn't match"""
        from agent.manager import AgentManager

        manager = AgentManager(db_session)

        # Register agent
        token = manager.generate_registration_token(user_id=1)
        registration_data = {
            "token": token.token,
            "engine_id": "docker-engine-123",
            "version": "2.2.0",
            "proto_version": "1.0",
            "capabilities": {}
        }
        reg_result = manager.register_agent(registration_data)
        agent_id = reg_result["agent_id"]

        # Try to reconnect with different engine_id
        reconnect_data = {
            "agent_id": agent_id,
            "engine_id": "different-engine-456"  # MISMATCH
        }

        result = manager.reconnect_agent(reconnect_data)

        assert result["success"] is False
        assert "engine_id mismatch" in result["error"].lower()
