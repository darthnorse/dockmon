"""
Regression tests for ignore_removed=True on containers.list() calls (Issue #174)

Ghost containers (listed by Docker but 404 on inspect) crash the entire
containers.list() operation when ignore_removed is not set. These tests
verify that ignore_removed=True is passed to all production call sites.
"""

import pytest
from unittest.mock import Mock, patch

from utils.async_docker import async_containers_list


async def _fake_to_thread(fn, *args, **kwargs):
    """Replace asyncio.to_thread with synchronous call for testing."""
    return fn(*args, **kwargs)


class TestAsyncContainersListIgnoreRemoved:
    """Verify async_containers_list defaults ignore_removed=True"""

    @pytest.mark.asyncio
    async def test_defaults_ignore_removed_true(self):
        """ignore_removed=True should be set by default"""
        mock_client = Mock()
        mock_client.containers.list = Mock(return_value=[])

        with patch('utils.async_docker.asyncio.to_thread', side_effect=_fake_to_thread):
            await async_containers_list(mock_client, all=True)

        mock_client.containers.list.assert_called_once_with(all=True, ignore_removed=True)

    @pytest.mark.asyncio
    async def test_can_override_ignore_removed_false(self):
        """Callers can explicitly pass ignore_removed=False to override"""
        mock_client = Mock()
        mock_client.containers.list = Mock(return_value=[])

        with patch('utils.async_docker.asyncio.to_thread', side_effect=_fake_to_thread):
            await async_containers_list(mock_client, all=True, ignore_removed=False)

        mock_client.containers.list.assert_called_once_with(all=True, ignore_removed=False)

    @pytest.mark.asyncio
    async def test_explicit_true_not_overridden(self):
        """Explicit ignore_removed=True should not be changed"""
        mock_client = Mock()
        mock_client.containers.list = Mock(return_value=[])

        with patch('utils.async_docker.asyncio.to_thread', side_effect=_fake_to_thread):
            await async_containers_list(mock_client, ignore_removed=True)

        mock_client.containers.list.assert_called_once_with(ignore_removed=True)
