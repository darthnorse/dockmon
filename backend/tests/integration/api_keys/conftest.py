"""
Pytest configuration for API key integration tests.

This conftest provides fixtures for api_key tests that need to avoid
importing the full application (main.py triggers app startup).

IMPORTANT: We use fixtures, NOT pytest_configure, to avoid polluting
the global module namespace for other tests.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from contextlib import ExitStack


@pytest.fixture(autouse=True)
def mock_app_modules():
    """
    Mock heavy application modules for api_key tests.

    This prevents importing main.py from triggering full app startup
    (database connections, Docker clients, background tasks, etc.)

    Uses autouse=True so it applies to all tests in this directory.
    Scoped to function level so mocks are fresh for each test.
    """
    with ExitStack() as stack:
        # Only mock if not already imported (avoid breaking other tests)
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
                # Create a mock module
                mock_module = MagicMock()
                sys.modules[module_name] = mock_module

        yield

        # Cleanup is handled by ExitStack
