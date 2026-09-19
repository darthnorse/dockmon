"""
Pytest configuration for API integration tests.

These tests hit real FastAPI endpoints with TestClient but need the
authentication system to use the test database instead of production.
"""

import pytest
from contextlib import contextmanager

from auth.api_key_auth import (
    invalidate_group_permissions_cache,
    invalidate_group_tag_scopes_cache,
    invalidate_user_groups_cache,
)


def _reset_auth_caches():
    invalidate_group_permissions_cache()
    invalidate_user_groups_cache()
    invalidate_group_tag_scopes_cache()


@pytest.fixture(autouse=True)
def reset_auth_caches():
    """User/group ids repeat across the fresh test databases while the auth caches
    are process-global, so a lookup made by one test must not leak into the next."""
    _reset_auth_caches()
    yield
    _reset_auth_caches()


@pytest.fixture(autouse=True)
def use_test_database_for_auth(db_session, monkeypatch):
    """
    Make the authentication system use the test database.

    The auth system normally uses monitor.db to look up API keys.
    We need to redirect it to use the test database where we've
    created test API keys.
    """
    import main as main_module

    @contextmanager
    def mock_get_session():
        yield db_session

    # Patch monitor.db.get_session to return test database session
    monkeypatch.setattr(main_module.monitor.db, 'get_session', mock_get_session)

    # Also clear any caches that might have stale data
    if hasattr(main_module, '_dashboard_summary_cache'):
        main_module._dashboard_summary_cache["data"] = None
        main_module._dashboard_summary_cache["timestamp"] = None
