"""
Tests for event logging and security audit functionality
Ensures proper logging of all security-relevant events
"""

import pytest
from unittest.mock import MagicMock, patch, mock_open
import json
from datetime import datetime, timedelta
import os


class TestEventLogging:
    """Test event logging system"""

    def test_event_logger_initialization(self):
        """Test event logger proper initialization"""
        from utils.event_logger import EventLogger

        logger = EventLogger()
        assert logger.queue is not None
        assert logger.is_running is True

    def test_log_container_event(self):
        """Test logging container events"""
        from utils.event_logger import EventLogger

        logger = EventLogger()

        event = {
            "host_id": "host123",
            "container_id": "container456",
            "container_name": "web-app",
            "event_type": "die",
            "exit_code": 1,
            "timestamp": datetime.utcnow().isoformat()
        }

        logger.log_container_event(event)

        # Event should be queued
        assert logger.queue.qsize() > 0

    def test_log_host_connection(self):
        """Test logging host connection events"""
        from utils.event_logger import EventLogger

        logger = EventLogger()

        logger.log_host_connection(
            host_name="production-server",
            host_url="tcp://192.168.1.100:2376",
            success=True
        )

        # Should log the connection
        assert logger.queue.qsize() > 0

    def test_log_alert_triggered(self):
        """Test logging alert trigger events"""
        from utils.event_logger import EventLogger

        logger = EventLogger()

        logger.log_alert_triggered(
            alert_name="Critical Container Alert",
            container_name="database",
            trigger_reason="Container exited with code 1",
            notification_sent=True
        )

        assert logger.queue.qsize() > 0

    def test_event_persistence(self, temp_db):
        """Test events are persisted to database"""
        from utils.event_logger import EventLogger

        logger = EventLogger(database=temp_db)

        # Log event
        event = {
            "host_id": "host123",
            "container_id": "container456",
            "container_name": "web-app",
            "event_type": "start",
            "message": "Container started"
        }

        logger.log_container_event(event)
        logger.flush()  # Force write to database

        # Verify event was persisted
        events = temp_db.get_recent_events(limit=1)
        assert len(events) == 1
        assert events[0].container_name == "web-app"

    def test_event_cleanup(self, temp_db):
        """Test old events are cleaned up"""
        from utils.event_logger import EventLogger

        logger = EventLogger(database=temp_db)

        # Add old events
        for i in range(100):
            event = {
                "host_id": "host123",
                "container_id": f"container{i}",
                "event_type": "start",
                "timestamp": (datetime.utcnow() - timedelta(days=35)).isoformat()
            }
            temp_db.add_container_event(event)

        # Run cleanup (default: remove events older than 30 days)
        logger.cleanup_old_events()

        # Old events should be removed
        events = temp_db.get_recent_events(limit=200)
        assert len(events) < 100

    def test_event_search(self, temp_db):
        """Test searching events"""
        from utils.event_logger import EventLogger

        logger = EventLogger(database=temp_db)

        # Add various events
        events = [
            {"container_name": "web-app", "event_type": "start"},
            {"container_name": "web-app", "event_type": "stop"},
            {"container_name": "database", "event_type": "start"},
            {"container_name": "cache", "event_type": "oom"}
        ]

        for event in events:
            event["host_id"] = "host123"
            event["container_id"] = "container456"
            temp_db.add_container_event(event)

        # Search by container name
        results = temp_db.search_events(container_name="web-app")
        assert len(results) == 2

        # Search by event type
        results = temp_db.search_events(event_type="start")
        assert len(results) == 2

        # Search by multiple criteria
        results = temp_db.search_events(
            container_name="web-app",
            event_type="stop"
        )
        assert len(results) == 1


class TestSecurityAuditLogging:
    """Test security audit logging"""

    @patch('builtins.open', new_callable=mock_open)
    def test_security_audit_logger_initialization(self, mock_file):
        """Test security audit logger setup"""
        from security.audit import SecurityAuditLogger

        audit_logger = SecurityAuditLogger()

        # Should create log file with secure permissions
        assert audit_logger.security_logger is not None

    def test_log_authentication_attempt(self):
        """Test logging authentication attempts"""
        from security.audit import SecurityAuditLogger

        with patch('logging.Logger.info') as mock_log_info:
            with patch('logging.Logger.warning') as mock_log_warning:
                audit_logger = SecurityAuditLogger()

                # Successful auth
                audit_logger.log_authentication_attempt(
                    client_ip="192.168.1.100",
                    success=True,
                    endpoint="/api/auth/login",
                    user_agent="Mozilla/5.0"
                )
                mock_log_info.assert_called()

                # Failed auth
                audit_logger.log_authentication_attempt(
                    client_ip="192.168.1.100",
                    success=False,
                    endpoint="/api/auth/login",
                    user_agent="Mozilla/5.0"
                )
                mock_log_warning.assert_called()

    def test_log_rate_limit_violation(self):
        """Test logging rate limit violations"""
        from security.audit import SecurityAuditLogger

        with patch('logging.Logger.warning') as mock_log_warning:
            with patch('logging.Logger.error') as mock_log_error:
                audit_logger = SecurityAuditLogger()

                # Regular violation
                audit_logger.log_rate_limit_violation(
                    client_ip="192.168.1.100",
                    endpoint="/api/containers",
                    violations=3,
                    banned=False
                )
                mock_log_warning.assert_called()

                # Ban event
                audit_logger.log_rate_limit_violation(
                    client_ip="192.168.1.100",
                    endpoint="/api/containers",
                    violations=10,
                    banned=True
                )
                mock_log_error.assert_called()

    def test_log_input_validation_failure(self):
        """Test logging input validation failures (potential attacks)"""
        from security.audit import SecurityAuditLogger

        with patch('logging.Logger.warning') as mock_log:
            audit_logger = SecurityAuditLogger()

            audit_logger.log_input_validation_failure(
                client_ip="192.168.1.100",
                endpoint="/api/hosts",
                field="url",
                attempted_value="<script>alert('xss')</script>",
                user_agent="Mozilla/5.0"
            )

            # Should log with attack indicators
            call_args = mock_log.call_args[0][0]
            log_data = json.loads(call_args)
            assert log_data["event_type"] == "INPUT_VALIDATION_FAILURE"
            assert "XSS" in log_data["details"]["attack_indicators"]

    def test_attack_pattern_detection(self):
        """Test detection of common attack patterns"""
        from security.audit import SecurityAuditLogger

        audit_logger = SecurityAuditLogger()

        # XSS patterns
        patterns = audit_logger._detect_attack_patterns("<script>alert(1)</script>")
        assert "XSS" in patterns

        patterns = audit_logger._detect_attack_patterns("javascript:void(0)")
        assert "XSS" in patterns

        # SQL injection patterns
        patterns = audit_logger._detect_attack_patterns("' OR '1'='1")
        assert "SQL_INJECTION" in patterns

        patterns = audit_logger._detect_attack_patterns("'; DROP TABLE users;--")
        assert "SQL_INJECTION" in patterns

        # Command injection patterns
        patterns = audit_logger._detect_attack_patterns("; rm -rf /")
        assert "COMMAND_INJECTION" in patterns

        patterns = audit_logger._detect_attack_patterns("| cat /etc/passwd")
        assert "COMMAND_INJECTION" in patterns

        # Path traversal patterns
        patterns = audit_logger._detect_attack_patterns("../../../etc/passwd")
        assert "PATH_TRAVERSAL" in patterns

        # SSRF patterns
        patterns = audit_logger._detect_attack_patterns("http://169.254.169.254/")
        assert "SSRF" in patterns

    def test_log_privileged_action(self):
        """Test logging privileged actions"""
        from security.audit import SecurityAuditLogger

        with patch('logging.Logger.info') as mock_log:
            audit_logger = SecurityAuditLogger()

            audit_logger.log_privileged_action(
                client_ip="192.168.1.100",
                action="delete_host",
                target="production-server",
                success=True,
                user_agent="Mozilla/5.0"
            )

            call_args = mock_log.call_args[0][0]
            log_data = json.loads(call_args)
            assert log_data["event_type"] == "PRIVILEGED_ACTION_DELETE_HOST"
            assert log_data["details"]["target"] == "production-server"

    def test_log_session_hijack_attempt(self):
        """Test logging potential session hijacking"""
        from security.audit import SecurityAuditLogger

        with patch('logging.Logger.error') as mock_log:
            audit_logger = SecurityAuditLogger()

            audit_logger.log_session_hijack_attempt(
                original_ip="192.168.1.100",
                attempted_ip="10.0.0.50",
                session_id="session123"
            )

            call_args = mock_log.call_args[0][0]
            log_data = json.loads(call_args)
            assert log_data["event_type"] == "SESSION_HIJACK_ATTEMPT"
            assert log_data["risk_level"] == "HIGH"

    def test_security_stats_generation(self):
        """Test security statistics generation"""
        from security.audit import SecurityAuditLogger

        audit_logger = SecurityAuditLogger()

        stats = audit_logger.get_security_stats(hours=24)

        assert "timeframe_hours" in stats
        assert stats["timeframe_hours"] == 24
        assert "log_location" in stats

    def test_log_file_rotation(self):
        """Test log file rotation when size limit reached"""
        from security.audit import SecurityAuditLogger
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = os.path.join(temp_dir, "security_audit.log")

            # Create large log file
            with open(log_file, 'w') as f:
                f.write("x" * (10 * 1024 * 1024))  # 10MB

            with patch('config.paths.DATA_DIR', temp_dir):
                audit_logger = SecurityAuditLogger()

                # Should rotate when size limit exceeded
                audit_logger.rotate_log_if_needed()

                # Backup file should exist
                assert os.path.exists(f"{log_file}.1")

    def test_structured_log_format(self):
        """Test structured JSON log format for easy parsing"""
        from security.audit import SecurityAuditLogger

        with patch('logging.Logger.info') as mock_log:
            audit_logger = SecurityAuditLogger()

            audit_logger._log_security_event(
                level="INFO",
                event_type="TEST_EVENT",
                client_ip="192.168.1.100",
                endpoint="/api/test",
                user_agent="TestAgent",
                details={"key": "value"},
                risk_level="LOW"
            )

            # Should log valid JSON
            call_args = mock_log.call_args[0][0]
            log_data = json.loads(call_args)  # Should not raise

            assert log_data["event_type"] == "TEST_EVENT"
            assert log_data["client_ip"] == "192.168.1.100"
            assert log_data["risk_level"] == "LOW"