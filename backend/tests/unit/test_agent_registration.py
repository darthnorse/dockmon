"""
Unit tests for agent registration functionality.

Tests the agent registration token generation, validation, and agent registration flow.

NOTE: These tests use mock patching since AgentManager uses DatabaseManager internally
(short-lived sessions pattern) rather than accepting a db_session parameter.
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agent.manager import AgentManager
from database import Base, RegistrationToken, Agent, DockerHostDB


@pytest.fixture
def db_engine():
    """Create an in-memory SQLite database engine for testing"""
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(db_engine):
    """Create a session for testing"""
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def mock_db_manager(db_session):
    """Create a mock DatabaseManager that uses the test session"""
    mock_manager = MagicMock()
    mock_manager.get_session.return_value.__enter__ = MagicMock(return_value=db_session)
    mock_manager.get_session.return_value.__exit__ = MagicMock(return_value=False)
    return mock_manager


def create_mock_init(mock_db_manager):
    """Create a mock __init__ that sets both db_manager and monitor.

    AgentManager.__init__ sets:
    - self.db_manager = DatabaseManager()
    - self.monitor = monitor

    Tests that call register_agent need monitor set to avoid AttributeError.
    """
    def mock_init(self):
        self.db_manager = mock_db_manager
        self.monitor = None
    return mock_init


class TestRegistrationTokenGeneration:
    """Test registration token generation"""

    def test_generate_registration_token(self, db_session, mock_db_manager):
        """Should generate a valid registration token"""

        with patch.object(AgentManager, '__init__', lambda self: setattr(self, 'db_manager', mock_db_manager)):
            manager = AgentManager()
            user_id = 1

            token_record = manager.generate_registration_token(user_id)

            assert token_record is not None
            assert token_record.token is not None
            assert len(token_record.token) == 36  # UUID format
            assert token_record.created_by_user_id == user_id
            assert token_record.use_count == 0
            assert token_record.max_uses == 1  # Default single-use
            # DB returns naive datetime, so compare as naive (both are UTC)
            assert token_record.expires_at > datetime.now(timezone.utc).replace(tzinfo=None)

    def test_token_expires_after_15_minutes(self, db_session, mock_db_manager):
        """Token should expire after 15 minutes"""

        with patch.object(AgentManager, '__init__', lambda self: setattr(self, 'db_manager', mock_db_manager)):
            manager = AgentManager()
            token_record = manager.generate_registration_token(user_id=1)

            expected_expiry = token_record.created_at + timedelta(minutes=15)

            # Allow 1 second tolerance for test execution time
            assert abs((token_record.expires_at - expected_expiry).total_seconds()) < 1

    def test_multiple_tokens_can_exist(self, db_session, mock_db_manager):
        """Multiple unused tokens can exist for a user"""

        with patch.object(AgentManager, '__init__', lambda self: setattr(self, 'db_manager', mock_db_manager)):
            manager = AgentManager()
            user_id = 1

            token1 = manager.generate_registration_token(user_id)
            token2 = manager.generate_registration_token(user_id)

            assert token1.token != token2.token

            # Both should be in database
            tokens = db_session.query(RegistrationToken).filter_by(created_by_user_id=user_id).all()
            assert len(tokens) == 2


class TestTokenValidation:
    """Test registration token validation"""

    def test_validate_valid_token(self, db_session, mock_db_manager):
        """Should validate a valid, unused, non-expired token"""

        with patch.object(AgentManager, '__init__', lambda self: setattr(self, 'db_manager', mock_db_manager)):
            manager = AgentManager()
            token_record = manager.generate_registration_token(user_id=1)

            is_valid = manager.validate_registration_token(token_record.token)

            assert is_valid is True

    def test_validate_expired_token(self, db_session, mock_db_manager):
        """Should reject expired token"""

        # Create token that expired 1 minute ago
        expired_token = RegistrationToken(
            token="expired-token-uuid",
            created_by_user_id=1,
            created_at=datetime.now(timezone.utc) - timedelta(minutes=20),
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            max_uses=1,
            use_count=0
        )
        db_session.add(expired_token)
        db_session.commit()

        with patch.object(AgentManager, '__init__', lambda self: setattr(self, 'db_manager', mock_db_manager)):
            manager = AgentManager()

            is_valid = manager.validate_registration_token("expired-token-uuid")

            assert is_valid is False

    def test_validate_exhausted_token(self, db_session, mock_db_manager):
        """Should reject token that has reached max uses"""

        # Create exhausted token (use_count >= max_uses)
        exhausted_token = RegistrationToken(
            token="exhausted-token-uuid",
            created_by_user_id=1,
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
            max_uses=1,
            use_count=1,
            last_used_at=datetime.now(timezone.utc)
        )
        db_session.add(exhausted_token)
        db_session.commit()

        with patch.object(AgentManager, '__init__', lambda self: setattr(self, 'db_manager', mock_db_manager)):
            manager = AgentManager()

            is_valid = manager.validate_registration_token("exhausted-token-uuid")

            assert is_valid is False

    def test_validate_nonexistent_token(self, db_session, mock_db_manager):
        """Should reject token that doesn't exist"""

        with patch.object(AgentManager, '__init__', lambda self: setattr(self, 'db_manager', mock_db_manager)):
            manager = AgentManager()

            is_valid = manager.validate_registration_token("nonexistent-token")

            assert is_valid is False


class TestAgentRegistration:
    """Test agent registration with tokens"""

    def test_register_agent_with_valid_token(self, db_session, mock_db_manager):
        """Should register agent with valid token and create host"""

        with patch.object(AgentManager, '__init__', create_mock_init(mock_db_manager)):
            manager = AgentManager()
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

            # Verify token use count incremented
            token = db_session.query(RegistrationToken).filter_by(token=token_record.token).first()
            assert token.use_count == 1
            assert token.last_used_at is not None

    def test_register_agent_with_expired_token(self, db_session, mock_db_manager):
        """Should reject registration with expired token"""

        # Create expired token
        expired_token = RegistrationToken(
            token="expired-token",
            created_by_user_id=1,
            created_at=datetime.now(timezone.utc) - timedelta(minutes=20),
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            max_uses=1,
            use_count=0
        )
        db_session.add(expired_token)
        db_session.commit()

        with patch.object(AgentManager, '__init__', create_mock_init(mock_db_manager)):
            manager = AgentManager()

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

    def test_register_agent_with_duplicate_engine_id(self, db_session, mock_db_manager):
        """Should reject registration if engine_id already registered"""

        with patch.object(AgentManager, '__init__', create_mock_init(mock_db_manager)):
            manager = AgentManager()

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


class TestEngineIdValidation:
    """Test engine_id format validation (Issue #112)"""

    def test_uuid_format_engine_id(self):
        """Should accept UUID format engine_id (newer Docker format)"""
        from agent.models import AgentRegistrationRequest

        # UUID format - standard for newer Docker installations
        data = AgentRegistrationRequest(
            type="register",
            token="valid-token",
            engine_id="4be40a44-3998-4f47-981e-1c3d09ae54a5",
            version="2.2.0",
            proto_version="1.0",
            capabilities={}
        )
        assert data.engine_id == "4be40a44-3998-4f47-981e-1c3d09ae54a5"

    def test_legacy_colon_format_engine_id(self):
        """Should accept legacy colon format engine_id (older Docker format)"""
        from agent.models import AgentRegistrationRequest

        # Legacy colon format - used by older Docker installations
        data = AgentRegistrationRequest(
            type="register",
            token="valid-token",
            engine_id="EOGD:IMML:ZAXF:LJYT:FU42:6BHD:DV6D:K3KU:B5CX:OMGQ:IKQ3:BVS6",
            version="2.2.0",
            proto_version="1.0",
            capabilities={}
        )
        assert data.engine_id == "EOGD:IMML:ZAXF:LJYT:FU42:6BHD:DV6D:K3KU:B5CX:OMGQ:IKQ3:BVS6"

    def test_simple_alphanumeric_engine_id(self):
        """Should accept simple alphanumeric engine_id"""
        from agent.models import AgentRegistrationRequest

        data = AgentRegistrationRequest(
            type="register",
            token="valid-token",
            engine_id="docker-engine-123",
            version="2.2.0",
            proto_version="1.0",
            capabilities={}
        )
        assert data.engine_id == "docker-engine-123"

    def test_invalid_engine_id_with_spaces(self):
        """Should reject engine_id with spaces"""
        from agent.models import AgentRegistrationRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            AgentRegistrationRequest(
                type="register",
                token="valid-token",
                engine_id="invalid engine id",
                version="2.2.0",
                proto_version="1.0",
                capabilities={}
            )
        assert "alphanumeric" in str(exc_info.value).lower()

    def test_invalid_engine_id_with_special_chars(self):
        """Should reject engine_id with injection characters"""
        from agent.models import AgentRegistrationRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AgentRegistrationRequest(
                type="register",
                token="valid-token",
                engine_id="engine;DROP TABLE agents;--",
                version="2.2.0",
                proto_version="1.0",
                capabilities={}
            )


class TestForceUniqueRegistration:
    """Tests for the FORCE_UNIQUE_REGISTRATION opt-in path (cloned VMs)."""

    def test_force_unique_skips_engine_id_check(self, db_session, mock_db_manager):
        """Two agents with identical engine_id can both register when force_unique=True and unique hostnames."""

        with patch.object(AgentManager, '__init__', create_mock_init(mock_db_manager)):
            manager = AgentManager()
            engine_id = "sha256:cloned-vm-engine-id-shared"

            # First agent registers normally (sets up the collision target).
            token1 = manager.generate_registration_token(user_id=1)
            first = manager.register_agent({
                "token": token1.token,
                "engine_id": engine_id,
                "hostname": "clone-01",
                "version": "1.0.0",
                "proto_version": "1.1",
                "capabilities": {},
                "force_unique_registration": False,
            })
            assert first["success"], f"first registration unexpectedly failed: {first}"

            # Second agent uses force_unique=True with a distinct hostname.
            # hostname_source="agent_name" is required to prove AGENT_NAME was set.
            token2 = manager.generate_registration_token(user_id=1)
            second = manager.register_agent({
                "token": token2.token,
                "engine_id": engine_id,
                "hostname": "clone-02",
                "hostname_source": "agent_name",
                "version": "1.0.0",
                "proto_version": "1.1",
                "capabilities": {},
                "force_unique_registration": True,
            })
            assert second["success"], f"second registration unexpectedly failed: {second}"
            assert second["host_id"] != first["host_id"], "expected distinct host_ids for cloned VMs"
            assert second["agent_id"] != first["agent_id"], "expected distinct agent_ids for cloned VMs"

    def test_force_unique_requires_agent_name(self, db_session, mock_db_manager):
        """force_unique=True without hostname (AGENT_NAME) is rejected with a friendly error."""

        with patch.object(AgentManager, '__init__', create_mock_init(mock_db_manager)):
            manager = AgentManager()
            token = manager.generate_registration_token(user_id=1)

            result = manager.register_agent({
                "token": token.token,
                "engine_id": "sha256:cloned-without-name",
                "hostname": None,
                "version": "1.0.0",
                "proto_version": "1.1",
                "capabilities": {},
                "force_unique_registration": True,
            })
            assert result["success"] is False
            assert "AGENT_NAME" in result["error"]
            assert "FORCE_UNIQUE" in result["error"]

    def test_force_unique_rejects_non_agent_name_source(self, db_session, mock_db_manager):
        """force_unique=True with a non-empty hostname but hostname_source!='agent_name'
        is rejected — prevents agents from using daemon/OS hostname fallbacks to
        bypass the AGENT_NAME requirement when opting out of engine_id uniqueness."""

        with patch.object(AgentManager, '__init__', create_mock_init(mock_db_manager)):
            manager = AgentManager()
            token = manager.generate_registration_token(user_id=1)

            result = manager.register_agent({
                "token": token.token,
                "engine_id": "sha256:cloned-with-daemon-source",
                "hostname": "auto-detected-host",  # would pass `if not hostname:` check
                "hostname_source": "daemon",       # but source is NOT agent_name
                "version": "1.0.0",
                "proto_version": "1.1",
                "capabilities": {},
                "force_unique_registration": True,
            })
            assert result["success"] is False
            assert "AGENT_NAME" in result["error"]
            assert "FORCE_UNIQUE" in result["error"]
            assert "daemon" in result["error"]  # error explains the actual source it received

    def test_force_unique_still_rejects_local_host_collision(self, db_session, mock_db_manager):
        """Even with force_unique=True, an engine_id matching a local-socket host is rejected."""

        engine_id = "sha256:local-host-engine-id"
        db_session.add(DockerHostDB(
            id="local-host-uuid",
            name="My Local Docker",
            url="unix:///var/run/docker.sock",
            connection_type="local",
            engine_id=engine_id,
            is_active=True,
        ))
        db_session.commit()

        with patch.object(AgentManager, '__init__', create_mock_init(mock_db_manager)):
            manager = AgentManager()
            token = manager.generate_registration_token(user_id=1)

            result = manager.register_agent({
                "token": token.token,
                "engine_id": engine_id,
                "hostname": "would-be-clone",
                "version": "1.0.0",
                "proto_version": "1.1",
                "capabilities": {},
                "force_unique_registration": True,
            })
            assert result["success"] is False
            assert "Migration not supported for local Docker connections" in result["error"]

    def test_default_rejection_message_mentions_force_unique(self, db_session, mock_db_manager):
        """When force_unique=False (default) and engine_id collides, the error suggests FORCE_UNIQUE_REGISTRATION."""

        with patch.object(AgentManager, '__init__', create_mock_init(mock_db_manager)):
            manager = AgentManager()
            engine_id = "sha256:default-path-collision"

            token1 = manager.generate_registration_token(user_id=1)
            first = manager.register_agent({
                "token": token1.token,
                "engine_id": engine_id,
                "hostname": "first",
                "version": "1.0.0",
                "proto_version": "1.1",
                "capabilities": {},
                "force_unique_registration": False,
            })
            assert first["success"], f"first registration unexpectedly failed: {first}"

            token2 = manager.generate_registration_token(user_id=1)
            result = manager.register_agent({
                "token": token2.token,
                "engine_id": engine_id,
                "hostname": "second",
                "version": "1.0.0",
                "proto_version": "1.1",
                "capabilities": {},
                "force_unique_registration": False,
            })
            assert result["success"] is False
            assert "FORCE_UNIQUE_REGISTRATION" in result["error"]
            assert "/var/lib/docker/engine-id" in result["error"]
