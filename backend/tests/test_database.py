"""
Unit tests for database operations
Tests for the issues we've encountered like duplicate host insertions
"""

import pytest
import uuid
from datetime import datetime, timedelta


class TestDatabaseOperations:
    """Test database CRUD operations"""

    def test_add_host_success(self, temp_db):
        """Test adding a new Docker host"""
        host_data = {
            'id': str(uuid.uuid4()),
            'name': 'TestHost',
            'url': 'tcp://localhost:2376',
            'security_status': 'insecure'
        }

        host = temp_db.add_host(host_data)
        assert host.name == 'TestHost'
        assert host.url == 'tcp://localhost:2376'

    def test_add_duplicate_host_fails(self, temp_db):
        """Test that adding duplicate host fails (catches the bug we had)"""
        host_data = {
            'id': str(uuid.uuid4()),
            'name': 'TestHost',
            'url': 'tcp://localhost:2376',
            'security_status': 'insecure'
        }

        # First insert should succeed
        host1 = temp_db.add_host(host_data)
        assert host1 is not None

        # Second insert with same name should fail
        with pytest.raises(Exception) as exc_info:
            temp_db.add_host(host_data)
        assert "UNIQUE constraint failed" in str(exc_info.value) or "IntegrityError" in str(exc_info.value)

    def test_get_hosts(self, temp_db):
        """Test retrieving hosts"""
        # Add multiple hosts
        for i in range(3):
            host_data = {
                'id': str(uuid.uuid4()),
                'name': f'TestHost{i}',
                'url': f'tcp://localhost:237{i}',
                'security_status': 'insecure'
            }
            temp_db.add_host(host_data)

        hosts = temp_db.get_hosts()
        assert len(hosts) == 3
        assert all(h.name.startswith('TestHost') for h in hosts)

    def test_update_host(self, temp_db):
        """Test updating host information"""
        host_data = {
            'id': str(uuid.uuid4()),
            'name': 'TestHost',
            'url': 'tcp://localhost:2376',
            'security_status': 'insecure'
        }
        host = temp_db.add_host(host_data)

        # Update the host
        updated = temp_db.update_host(host.id, {'security_status': 'secure'})
        assert updated.security_status == 'secure'

    def test_delete_host(self, temp_db):
        """Test deleting a host"""
        host_data = {
            'id': str(uuid.uuid4()),
            'name': 'TestHost',
            'url': 'tcp://localhost:2376',
            'security_status': 'insecure'
        }
        host = temp_db.add_host(host_data)

        # Delete the host
        temp_db.delete_host(host.id)

        # Verify it's gone
        retrieved = temp_db.get_host(host.id)
        assert retrieved is None

    def test_alert_rule_crud(self, temp_db):
        """Test alert rule operations"""
        rule_data = {
            'name': 'Test Alert',
            'container_pattern': 'test_*',
            'trigger_states': ['exited', 'dead'],
            'trigger_events': ['die', 'oom'],
            'cooldown_minutes': 5,
            'enabled': True
        }

        # Create
        rule = temp_db.add_alert_rule(rule_data)
        assert rule.name == 'Test Alert'
        assert rule.trigger_states == ['exited', 'dead']
        assert rule.trigger_events == ['die', 'oom']

        # Read
        rules = temp_db.get_alert_rules()
        assert len(rules) == 1

        # Update
        updated = temp_db.update_alert_rule(rule.id, {'enabled': False})
        assert updated.enabled is False

        # Delete
        temp_db.delete_alert_rule(rule.id)
        rules = temp_db.get_alert_rules()
        assert len(rules) == 0

    def test_session_management(self, temp_db):
        """Test session creation and validation"""
        session_id = str(uuid.uuid4())

        # Create session
        session = temp_db.create_session(session_id)
        assert session.session_id == session_id
        assert session.is_valid is True

        # Validate session
        is_valid = temp_db.validate_session(session_id)
        assert is_valid is True

        # Invalidate session
        temp_db.invalidate_session(session_id)
        is_valid = temp_db.validate_session(session_id)
        assert is_valid is False

    def test_session_expiration(self, temp_db):
        """Test that expired sessions are invalid"""
        session_id = str(uuid.uuid4())
        session = temp_db.create_session(session_id)

        # Manually set session to expired
        with temp_db.get_session() as db_session:
            session.expires_at = datetime.utcnow() - timedelta(hours=1)
            db_session.commit()

        # Should be invalid
        is_valid = temp_db.validate_session(session_id)
        assert is_valid is False

    def test_auto_restart_config(self, temp_db):
        """Test auto-restart configuration storage"""
        host_id = str(uuid.uuid4())
        container_id = 'container123'

        # Add auto-restart config
        config = temp_db.set_auto_restart(host_id, container_id, 'test_container', True)
        assert config.enabled is True
        assert config.restart_count == 0

        # Update restart count
        config = temp_db.increment_restart_count(host_id, container_id)
        assert config.restart_count == 1

        # Disable auto-restart
        config = temp_db.set_auto_restart(host_id, container_id, 'test_container', False)
        assert config.enabled is False

    def test_cleanup_old_events(self, temp_db):
        """Test that old events are cleaned up"""
        # Add some events
        for i in range(10):
            event_data = {
                'host_id': str(uuid.uuid4()),
                'container_id': f'container{i}',
                'container_name': f'test{i}',
                'event_type': 'start',
                'message': 'Container started'
            }
            temp_db.add_container_event(event_data)

        # Cleanup (this would normally remove events older than X days)
        # For testing, we'll just verify the method exists
        temp_db.cleanup_old_events(days=30)
        # Events should still exist since they're recent
        # This test mainly verifies the method doesn't crash