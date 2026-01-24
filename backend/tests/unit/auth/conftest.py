"""
Local conftest for auth unit tests.

Provides isolated test fixtures that don't trigger the production database initialization.
Uses in-memory SQLite database with fresh schema for each test.
"""

import os
import sys
import tempfile
from datetime import datetime, timezone

# Add backend to path before importing database
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="function")
def db_session() -> Session:
    """
    Create a temporary SQLite database for testing.

    Uses a temporary file database with fresh schema for complete isolation.
    All tables are created from the SQLAlchemy models.
    Foreign key constraints are enabled for proper CASCADE/RESTRICT testing.
    """
    # Import Base after path is set up (required for test isolation)
    from database import Base

    # Create temporary database file (file-based required for FK constraint support)
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    engine = create_engine(f'sqlite:///{db_path}')

    # Enable foreign key constraints in SQLite
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()

    yield session

    session.close()
    engine.dispose()
    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def test_user(db_session: Session):
    """Create a test user for tests that need a user."""
    from database import User

    user = User(
        username='testuser',
        password_hash='$2b$12$test_hash_not_real',
        role='admin',
        auth_provider='local',
        created_at=datetime.now(timezone.utc)
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    return user


@pytest.fixture
def test_group(db_session: Session):
    """Create a test group for tests that need a group."""
    from database import CustomGroup

    group = CustomGroup(
        name='Test Group',
        description='A test group',
        is_system=False,
    )
    db_session.add(group)
    db_session.commit()
    db_session.refresh(group)

    return group
