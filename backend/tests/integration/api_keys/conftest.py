"""
Pytest configuration for API key integration tests (v2.3.0+).

Provides fixtures with in-memory SQLite databases that include
the group-based permissions model.
"""

import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import MagicMock
from contextlib import ExitStack

from database import Base, User, ApiKey, CustomGroup, GroupPermission
from auth.capabilities import ALL_CAPABILITIES
from auth.api_key_auth import generate_api_key


@pytest.fixture(autouse=True)
def mock_app_modules():
    """Mock heavy application modules to avoid full app startup."""
    with ExitStack() as stack:
        import sys

        modules_to_mock = [
            'realtime',
            'docker_monitor.monitor',
            'docker_monitor.periodic_jobs',
            'stats_client',
            'health_check.http_checker',
        ]

        for module_name in modules_to_mock:
            if module_name not in sys.modules:
                sys.modules[module_name] = MagicMock()

        yield


@pytest.fixture(scope="function")
def test_db_session():
    """Create an in-memory SQLite database with groups and a test user."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Seed system groups
    admin_group = CustomGroup(id=1, name="Administrators", description="Full access", is_system=True)
    operators_group = CustomGroup(id=2, name="Operators", description="Container operations", is_system=True)
    readonly_group = CustomGroup(id=3, name="Read Only", description="View only", is_system=True)
    session.add_all([admin_group, operators_group, readonly_group])
    session.flush()

    # Seed admin permissions (all capabilities)
    for cap in ALL_CAPABILITIES:
        session.add(GroupPermission(group_id=admin_group.id, capability=cap, allowed=True))

    # Seed operator permissions (subset)
    operator_caps = [
        'hosts.view', 'containers.operate', 'containers.view', 'containers.logs',
        'stacks.view', 'stacks.deploy', 'tags.manage', 'tags.view', 'events.view',
    ]
    for cap in operator_caps:
        session.add(GroupPermission(group_id=operators_group.id, capability=cap, allowed=True))

    # Seed readonly permissions (view only)
    readonly_caps = [
        'hosts.view', 'containers.view', 'containers.logs',
        'stacks.view', 'tags.view', 'events.view',
    ]
    for cap in readonly_caps:
        session.add(GroupPermission(group_id=readonly_group.id, capability=cap, allowed=True))

    session.flush()

    # Create test user
    user = User(
        id=1,
        username="testuser",
        password_hash="dummy_hash",
        role="admin",
        auth_provider="local",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(user)
    session.commit()

    yield session
    session.close()
