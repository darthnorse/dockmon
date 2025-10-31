"""
Unit tests for correlation ID cleanup and memory leak prevention.

Tests verify that active correlations are properly cleaned up based on
TTL and size limits to prevent unbounded memory growth.

Issue #2: Active correlations dictionary leak
"""

import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock


class TestCorrelationCleanup:
    """Tests for correlation ID tracking and cleanup"""

    @pytest.fixture
    def event_logger(self):
        """Create event logger instance for testing"""
        from database import DatabaseManager
        from event_logger import EventLogger

        db = DatabaseManager()
        event_logger = EventLogger(db, websocket_manager=None)
        return event_logger

    @pytest.mark.asyncio
    async def test_correlation_timestamps_tracked(self, event_logger):
        """Verify that correlation creation records timestamp"""
        cid = event_logger.create_correlation_id()

        assert hasattr(event_logger, '_correlation_timestamps'), "EventLogger should have _correlation_timestamps attribute"
        assert cid in event_logger._correlation_timestamps, "Correlation timestamp should be recorded"
        assert isinstance(event_logger._correlation_timestamps[cid], datetime), "Timestamp should be datetime object"

    @pytest.mark.asyncio
    async def test_correlation_ttl_cleanup(self, event_logger):
        """Verify correlations older than TTL are cleaned up"""
        # Create old correlation (2 hours ago)
        old_cid = event_logger.create_correlation_id()
        event_logger._correlation_timestamps[old_cid] = datetime.now(timezone.utc) - timedelta(hours=2)

        # Create recent correlation
        recent_cid = event_logger.create_correlation_id()

        # Run cleanup
        await event_logger._cleanup_stale_correlations()

        # Old correlation should be removed
        assert old_cid not in event_logger._active_correlations, "Old correlation should be removed"
        assert old_cid not in event_logger._correlation_timestamps, "Old timestamp should be removed"

        # Recent correlation should remain
        assert recent_cid in event_logger._active_correlations, "Recent correlation should remain"
        assert recent_cid in event_logger._correlation_timestamps, "Recent timestamp should remain"

    @pytest.mark.asyncio
    async def test_correlation_size_limit(self, event_logger):
        """Verify LRU eviction when exceeding MAX_CORRELATIONS"""
        # Set low limit for testing
        event_logger.MAX_CORRELATIONS = 100

        # Create 150 correlations
        correlation_ids = []
        for i in range(150):
            cid = event_logger.create_correlation_id()
            correlation_ids.append(cid)
            await asyncio.sleep(0.001)  # Ensure different timestamps

        # Run cleanup
        await event_logger._cleanup_stale_correlations()

        # Should have evicted oldest 50+ correlations
        assert len(event_logger._active_correlations) <= 100, f"Should have <= 100 correlations, got {len(event_logger._active_correlations)}"

        # Oldest should be evicted, newest should remain
        assert correlation_ids[0] not in event_logger._active_correlations, "Oldest correlation should be evicted"
        assert correlation_ids[-1] in event_logger._active_correlations, "Newest correlation should remain"

    @pytest.mark.asyncio
    async def test_cleanup_task_starts_with_event_logger(self, event_logger):
        """Verify cleanup task is started when event logger starts"""
        await event_logger.start()

        assert hasattr(event_logger, '_correlation_cleanup_task'), "Should have cleanup task attribute"
        assert event_logger._correlation_cleanup_task is not None, "Cleanup task should be created"
        assert isinstance(event_logger._correlation_cleanup_task, asyncio.Task), "Should be an asyncio Task"
        assert not event_logger._correlation_cleanup_task.done(), "Task should be running"

        # Cleanup
        await event_logger.stop()

    @pytest.mark.asyncio
    async def test_cleanup_task_stops_with_event_logger(self, event_logger):
        """Verify cleanup task is cancelled when event logger stops"""
        await event_logger.start()

        cleanup_task = event_logger._correlation_cleanup_task
        assert not cleanup_task.done(), "Task should be running"

        # Stop event logger
        await event_logger.stop()

        # Task should be cancelled
        assert cleanup_task.done(), "Task should be stopped"
        assert cleanup_task.cancelled() or cleanup_task.exception() is None, "Task should be cancelled or completed normally"

    @pytest.mark.asyncio
    async def test_end_correlation_removes_timestamp(self, event_logger):
        """Verify end_correlation() removes both correlation and timestamp"""
        cid = event_logger.create_correlation_id()

        assert cid in event_logger._active_correlations
        assert cid in event_logger._correlation_timestamps

        # End correlation
        event_logger.end_correlation(cid)

        # Both should be removed
        assert cid not in event_logger._active_correlations, "Correlation should be removed"
        assert cid not in event_logger._correlation_timestamps, "Timestamp should be removed"

    @pytest.mark.asyncio
    async def test_cleanup_handles_exceptions_gracefully(self, event_logger):
        """Verify cleanup continues even if some operations fail"""
        # Create correlations
        cid1 = event_logger.create_correlation_id()
        cid2 = event_logger.create_correlation_id()

        # Make one correlation malformed (simulate corruption)
        event_logger._correlation_timestamps[cid1] = "invalid"  # Not a datetime

        # Cleanup should not crash
        try:
            await event_logger._cleanup_stale_correlations()
        except Exception as e:
            pytest.fail(f"Cleanup should handle exceptions gracefully, but raised: {e}")

        # Valid correlation should still exist
        assert cid2 in event_logger._active_correlations, "Valid correlation should remain"
