"""
Unit tests for event suppression pattern matching.

Tests the container name pattern matching for event log suppression.
"""

import pytest
from unittest.mock import MagicMock, patch
from event_logger import EventLogger, EventCategory, EventContext


class TestEventSuppressionPatternMatching:
    """Test the _should_suppress_container_event method"""

    def setup_method(self):
        """Set up test fixtures"""
        # Create a mock database manager
        self.mock_db = MagicMock()
        self.mock_db.get_settings.return_value = None

        # Create event logger instance
        self.event_logger = EventLogger(self.mock_db)

    def test_no_patterns_configured(self):
        """Test that no suppression occurs when patterns list is empty"""
        self.event_logger._suppression_patterns = []

        assert self.event_logger._should_suppress_container_event("any-container") is False
        assert self.event_logger._should_suppress_container_event("runner-abc123") is False

    def test_empty_container_name(self):
        """Test that empty container names are not suppressed"""
        self.event_logger._suppression_patterns = ["runner-*"]

        assert self.event_logger._should_suppress_container_event("") is False
        assert self.event_logger._should_suppress_container_event(None) is False

    def test_starts_with_pattern(self):
        """Test 'starts with' pattern matching (runner-*)"""
        self.event_logger._suppression_patterns = ["runner-*"]

        # Should match
        assert self.event_logger._should_suppress_container_event("runner-abc123") is True
        assert self.event_logger._should_suppress_container_event("runner-") is True
        assert self.event_logger._should_suppress_container_event("runner-xyz-456") is True

        # Should not match
        assert self.event_logger._should_suppress_container_event("my-runner-container") is False
        assert self.event_logger._should_suppress_container_event("runnercontainer") is False
        assert self.event_logger._should_suppress_container_event("nginx") is False

    def test_ends_with_pattern(self):
        """Test 'ends with' pattern matching (*-tmp)"""
        self.event_logger._suppression_patterns = ["*-tmp"]

        # Should match
        assert self.event_logger._should_suppress_container_event("mycontainer-tmp") is True
        assert self.event_logger._should_suppress_container_event("nginx-tmp") is True
        assert self.event_logger._should_suppress_container_event("-tmp") is True

        # Should not match
        assert self.event_logger._should_suppress_container_event("tmp-container") is False
        assert self.event_logger._should_suppress_container_event("mycontainer-tmp-2") is False
        assert self.event_logger._should_suppress_container_event("tmpcontainer") is False

    def test_contains_pattern(self):
        """Test 'contains' pattern matching (*cronjob*)"""
        self.event_logger._suppression_patterns = ["*cronjob*"]

        # Should match
        assert self.event_logger._should_suppress_container_event("my-cronjob-runner") is True
        assert self.event_logger._should_suppress_container_event("cronjob") is True
        assert self.event_logger._should_suppress_container_event("daily-cronjob-task-abc") is True

        # Should not match
        assert self.event_logger._should_suppress_container_event("cron-job-container") is False
        assert self.event_logger._should_suppress_container_event("nginx") is False

    def test_exact_match_pattern(self):
        """Test exact match pattern (no wildcards)"""
        self.event_logger._suppression_patterns = ["temp-container"]

        # Should match only exact name
        assert self.event_logger._should_suppress_container_event("temp-container") is True

        # Should not match partial or different names
        assert self.event_logger._should_suppress_container_event("temp-container-2") is False
        assert self.event_logger._should_suppress_container_event("my-temp-container") is False

    def test_multiple_patterns(self):
        """Test that any matching pattern causes suppression"""
        self.event_logger._suppression_patterns = ["runner-*", "*-tmp", "*cronjob*"]

        # Should match first pattern
        assert self.event_logger._should_suppress_container_event("runner-abc") is True

        # Should match second pattern
        assert self.event_logger._should_suppress_container_event("mycontainer-tmp") is True

        # Should match third pattern
        assert self.event_logger._should_suppress_container_event("daily-cronjob") is True

        # Should not match any pattern
        assert self.event_logger._should_suppress_container_event("nginx") is False
        assert self.event_logger._should_suppress_container_event("postgres") is False

    def test_question_mark_wildcard(self):
        """Test single character wildcard (?)"""
        self.event_logger._suppression_patterns = ["runner-?"]

        # Should match single character after runner-
        assert self.event_logger._should_suppress_container_event("runner-1") is True
        assert self.event_logger._should_suppress_container_event("runner-a") is True

        # Should not match multiple characters
        assert self.event_logger._should_suppress_container_event("runner-12") is False
        assert self.event_logger._should_suppress_container_event("runner-abc") is False

    def test_case_sensitive_matching(self):
        """Test that pattern matching is case-sensitive"""
        self.event_logger._suppression_patterns = ["Runner-*"]

        # Should match with correct case
        assert self.event_logger._should_suppress_container_event("Runner-abc") is True

        # Should not match with different case
        assert self.event_logger._should_suppress_container_event("runner-abc") is False
        assert self.event_logger._should_suppress_container_event("RUNNER-abc") is False


class TestEventSuppressionReload:
    """Test the reload_suppression_patterns method"""

    def setup_method(self):
        """Set up test fixtures"""
        self.mock_db = MagicMock()
        self.event_logger = EventLogger(self.mock_db)

    def test_reload_with_patterns(self):
        """Test loading patterns from settings"""
        mock_settings = MagicMock()
        mock_settings.event_suppression_patterns = ["runner-*", "*-tmp"]
        self.mock_db.get_settings.return_value = mock_settings

        self.event_logger.reload_suppression_patterns()

        assert self.event_logger._suppression_patterns == ["runner-*", "*-tmp"]

    def test_reload_with_no_patterns(self):
        """Test loading when no patterns configured"""
        mock_settings = MagicMock()
        mock_settings.event_suppression_patterns = None
        self.mock_db.get_settings.return_value = mock_settings

        self.event_logger.reload_suppression_patterns()

        assert self.event_logger._suppression_patterns == []

    def test_reload_with_empty_patterns(self):
        """Test loading empty patterns list"""
        mock_settings = MagicMock()
        mock_settings.event_suppression_patterns = []
        self.mock_db.get_settings.return_value = mock_settings

        self.event_logger.reload_suppression_patterns()

        assert self.event_logger._suppression_patterns == []

    def test_reload_with_no_settings(self):
        """Test loading when settings object is None"""
        self.mock_db.get_settings.return_value = None

        self.event_logger.reload_suppression_patterns()

        assert self.event_logger._suppression_patterns == []

    def test_reload_handles_exception(self):
        """Test that reload handles database exceptions gracefully"""
        self.mock_db.get_settings.side_effect = Exception("Database error")

        # Should not raise, just log error and reset patterns
        self.event_logger.reload_suppression_patterns()

        assert self.event_logger._suppression_patterns == []


class TestEventSuppressionIntegration:
    """Test event suppression in the log_event method"""

    def setup_method(self):
        """Set up test fixtures"""
        self.mock_db = MagicMock()
        self.mock_db.get_settings.return_value = None
        self.event_logger = EventLogger(self.mock_db)
        self.event_logger._suppression_patterns = ["runner-*"]

    def test_container_event_suppressed(self):
        """Test that matching container events are suppressed"""
        context = EventContext(
            container_id="abc123",
            container_name="runner-temp-1234"
        )

        # This should return early without queuing
        self.event_logger.log_event(
            category=EventCategory.CONTAINER,
            event_type=MagicMock(value="state_change"),
            title="Container stopped",
            context=context
        )

        # Event queue should be empty (event was suppressed)
        assert self.event_logger._event_queue.empty()

    def test_container_event_not_suppressed(self):
        """Test that non-matching container events are logged"""
        context = EventContext(
            container_id="abc123",
            container_name="nginx-web"
        )

        self.event_logger.log_event(
            category=EventCategory.CONTAINER,
            event_type=MagicMock(value="state_change"),
            title="Container stopped",
            context=context
        )

        # Event should be in queue
        assert not self.event_logger._event_queue.empty()

    def test_non_container_event_not_suppressed(self):
        """Test that non-container events are never suppressed"""
        context = EventContext(
            host_id="host123",
            host_name="runner-host"  # Name matches pattern but it's a host event
        )

        self.event_logger.log_event(
            category=EventCategory.HOST,
            event_type=MagicMock(value="connection"),
            title="Host connected",
            context=context
        )

        # Event should be in queue (host events not suppressed)
        assert not self.event_logger._event_queue.empty()
