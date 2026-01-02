"""
Tests for UpdateEventEmitter.

Verifies that update events are emitted with correct data.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from updates.event_emitter import UpdateEventEmitter
from event_bus import EventType


class TestUpdateEventEmitter:
    """Tests for UpdateEventEmitter class."""

    @pytest.fixture
    def mock_monitor(self):
        """Create a mock monitor with hosts."""
        monitor = MagicMock()
        monitor.hosts = {
            'host-123': MagicMock(name='Test Host')
        }
        return monitor

    @pytest.fixture
    def emitter(self, mock_monitor):
        """Create an UpdateEventEmitter instance."""
        return UpdateEventEmitter(mock_monitor)

    @pytest.mark.asyncio
    async def test_emit_completed_includes_changelog_url(self, emitter):
        """
        Test that emit_completed includes changelog_url in event data.

        Issue #118: UPDATE_COMPLETED events were missing changelog_url,
        causing alert notifications to show 'Not found' for changelog.
        """
        with patch('updates.event_emitter.get_event_bus') as mock_get_bus:
            mock_bus = AsyncMock()
            mock_get_bus.return_value = mock_bus

            # Call emit_completed with changelog_url
            await emitter.emit_completed(
                host_id='host-123',
                container_id='abc123def456',
                container_name='test-container',
                previous_image='nginx:1.24',
                new_image='nginx:1.25',
                previous_digest='sha256:olddigest',
                new_digest='sha256:newdigest',
                changelog_url='https://github.com/nginx/nginx/releases'
            )

            # Verify event was emitted
            mock_bus.emit.assert_called_once()

            # Get the Event object that was passed
            event = mock_bus.emit.call_args[0][0]

            # Verify event type
            assert event.event_type == EventType.UPDATE_COMPLETED

            # Verify changelog_url is in the data (Issue #118 fix)
            assert 'changelog_url' in event.data
            assert event.data['changelog_url'] == 'https://github.com/nginx/nginx/releases'

            # Verify other expected fields
            assert event.data['previous_image'] == 'nginx:1.24'
            assert event.data['new_image'] == 'nginx:1.25'
            assert event.data['current_digest'] == 'sha256:olddigest'
            assert event.data['latest_digest'] == 'sha256:newdigest'

    @pytest.mark.asyncio
    async def test_emit_completed_handles_none_changelog_url(self, emitter):
        """
        Test that emit_completed handles None changelog_url gracefully.

        Some containers may not have a resolved changelog URL.
        """
        with patch('updates.event_emitter.get_event_bus') as mock_get_bus:
            mock_bus = AsyncMock()
            mock_get_bus.return_value = mock_bus

            # Call emit_completed without changelog_url (defaults to None)
            await emitter.emit_completed(
                host_id='host-123',
                container_id='abc123def456',
                container_name='test-container',
                previous_image='custom:latest',
                new_image='custom:latest',
            )

            # Verify event was emitted
            mock_bus.emit.assert_called_once()

            # Get the Event object
            event = mock_bus.emit.call_args[0][0]

            # Verify changelog_url is present but None
            assert 'changelog_url' in event.data
            assert event.data['changelog_url'] is None

    @pytest.mark.asyncio
    async def test_emit_started_event(self, emitter):
        """Test that emit_started emits correct event."""
        with patch('updates.event_emitter.get_event_bus') as mock_get_bus:
            mock_bus = AsyncMock()
            mock_get_bus.return_value = mock_bus

            await emitter.emit_started(
                host_id='host-123',
                container_id='abc123def456',
                container_name='test-container',
                target_image='nginx:1.25'
            )

            mock_bus.emit.assert_called_once()
            event = mock_bus.emit.call_args[0][0]

            assert event.event_type == EventType.UPDATE_STARTED
            assert event.data['target_image'] == 'nginx:1.25'

    @pytest.mark.asyncio
    async def test_emit_failed_event(self, emitter):
        """Test that emit_failed emits correct event."""
        with patch('updates.event_emitter.get_event_bus') as mock_get_bus:
            mock_bus = AsyncMock()
            mock_get_bus.return_value = mock_bus

            await emitter.emit_failed(
                host_id='host-123',
                container_id='abc123def456',
                container_name='test-container',
                error_message='Container failed health check'
            )

            mock_bus.emit.assert_called_once()
            event = mock_bus.emit.call_args[0][0]

            assert event.event_type == EventType.UPDATE_FAILED
            assert event.data['error_message'] == 'Container failed health check'
