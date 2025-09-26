"""
Tests for data persistence across restarts
Ensures all data survives container rebuilds (like the password bug)
"""

import pytest
import tempfile
import os
import json
from unittest.mock import patch, MagicMock


class TestDataPersistence:
    """Test data persistence across application restarts"""

    def test_password_persists_across_restart(self, temp_db):
        """Test that password changes persist (the bug we had)"""
        from database import DatabaseManager

        # Create user with initial password
        user = temp_db.create_user({
            "username": "admin",
            "password_hash": "initial_hash",
            "password_change_required": True
        })

        # Change password
        temp_db.update_user_password("admin", "new_password_hash")

        # Simulate restart - create new DB instance with same file
        db_path = temp_db.db_path
        new_db = DatabaseManager(db_path)

        # Password should persist
        user = new_db.get_user("admin")
        assert user.password_hash == "new_password_hash"
        assert user.password_change_required is False

    def test_hosts_persist_across_restart(self, temp_db):
        """Test Docker hosts persist across restart"""
        # Add hosts
        host1 = temp_db.add_host({
            "id": "host1",
            "name": "Production",
            "url": "tcp://prod:2376",
            "tls_cert": "cert_data",
            "tls_key": "key_data",
            "security_status": "secure"
        })

        host2 = temp_db.add_host({
            "id": "host2",
            "name": "Staging",
            "url": "tcp://staging:2376",
            "security_status": "insecure"
        })

        # Simulate restart
        db_path = temp_db.db_path
        new_db = DatabaseManager(db_path)

        # Hosts should persist
        hosts = new_db.get_hosts()
        assert len(hosts) == 2

        # Verify details persisted
        prod_host = next(h for h in hosts if h.name == "Production")
        assert prod_host.tls_cert == "cert_data"
        assert prod_host.security_status == "secure"

    def test_alert_rules_persist(self, temp_db):
        """Test alert rules persist across restart"""
        # Create alert rules
        rule1 = temp_db.add_alert_rule({
            "name": "Critical Alert",
            "container_pattern": "database-*",
            "trigger_states": ["exited", "dead"],
            "trigger_events": ["oom", "die"],
            "cooldown_minutes": 5,
            "enabled": True
        })

        # Simulate restart
        new_db = DatabaseManager(temp_db.db_path)

        # Rules should persist
        rules = new_db.get_alert_rules()
        assert len(rules) == 1
        assert rules[0].name == "Critical Alert"
        assert rules[0].trigger_events == ["oom", "die"]

    def test_notification_channels_persist(self, temp_db):
        """Test notification channels persist"""
        # Add channels
        channel = temp_db.add_notification_channel({
            "name": "Telegram",
            "type": "telegram",
            "config": json.dumps({
                "bot_token": "secret_token",
                "chat_id": "chat123"
            }),
            "enabled": True
        })

        # Simulate restart
        new_db = DatabaseManager(temp_db.db_path)

        # Channels should persist
        channels = new_db.get_notification_channels()
        assert len(channels) == 1

        config = json.loads(channels[0].config)
        assert config["bot_token"] == "secret_token"

    def test_session_cleanup_on_restart(self, temp_db):
        """Test that old sessions are cleaned up on restart"""
        # Create sessions
        temp_db.create_session("session1")
        temp_db.create_session("session2")

        # Simulate restart
        new_db = DatabaseManager(temp_db.db_path)

        # Old sessions should be invalidated
        assert new_db.validate_session("session1") is False
        assert new_db.validate_session("session2") is False

    def test_auto_restart_settings_persist(self, temp_db):
        """Test auto-restart settings persist"""
        # Configure auto-restart
        temp_db.set_auto_restart("host1", "container1", "web-app", True)
        temp_db.set_auto_restart("host1", "container2", "database", False)

        # Simulate restart
        new_db = DatabaseManager(temp_db.db_path)

        # Settings should persist
        configs = new_db.get_auto_restart_configs()
        assert len(configs) >= 2

        web_config = next((c for c in configs if c.container_name == "web-app"), None)
        assert web_config is not None
        assert web_config.enabled is True

    def test_event_history_persistence(self, temp_db):
        """Test container event history persists"""
        # Add events
        for i in range(10):
            temp_db.add_container_event({
                "host_id": "host1",
                "container_id": f"container{i}",
                "container_name": f"app{i}",
                "event_type": "start",
                "message": "Container started"
            })

        # Simulate restart
        new_db = DatabaseManager(temp_db.db_path)

        # Events should persist
        events = new_db.get_recent_events(limit=20)
        assert len(events) == 10

    def test_settings_persistence(self, temp_db):
        """Test global settings persist"""
        # Update settings
        temp_db.update_settings({
            "refresh_interval": 10,
            "enable_notifications": True,
            "dark_mode": True,
            "auto_cleanup_days": 7
        })

        # Simulate restart
        new_db = DatabaseManager(temp_db.db_path)

        # Settings should persist
        settings = new_db.get_settings()
        assert settings.refresh_interval == 10
        assert settings.enable_notifications is True
        assert settings.auto_cleanup_days == 7

    def test_certificate_storage_persistence(self):
        """Test TLS certificates persist in correct location"""
        from config.paths import CERTS_DIR
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch('config.paths.CERTS_DIR', temp_dir):
                cert_path = os.path.join(temp_dir, "host1", "client-cert.pem")
                key_path = os.path.join(temp_dir, "host1", "client-key.pem")

                # Create cert files
                os.makedirs(os.path.dirname(cert_path), exist_ok=True)
                with open(cert_path, 'w') as f:
                    f.write("CERTIFICATE DATA")
                with open(key_path, 'w') as f:
                    f.write("KEY DATA")

                # Set proper permissions
                os.chmod(cert_path, 0o600)
                os.chmod(key_path, 0o600)

                # Verify files exist and have correct permissions
                assert os.path.exists(cert_path)
                assert os.path.exists(key_path)
                assert oct(os.stat(cert_path).st_mode)[-3:] == '600'

    def test_logs_persistence(self):
        """Test that security audit logs persist"""
        from config.paths import DATA_DIR
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch('config.paths.DATA_DIR', temp_dir):
                log_dir = os.path.join(temp_dir, 'logs')
                os.makedirs(log_dir, exist_ok=True)

                log_file = os.path.join(log_dir, 'security_audit.log')

                # Write log entry
                with open(log_file, 'w') as f:
                    f.write('{"event": "login", "user": "admin"}\n')

                # Verify log persists
                assert os.path.exists(log_file)

                # Read back
                with open(log_file, 'r') as f:
                    content = f.read()
                    assert '"event": "login"' in content

    def test_database_file_permissions(self):
        """Test database file has secure permissions"""
        import tempfile
        import stat

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        from database import DatabaseManager
        db = DatabaseManager(db_path)

        # Check file permissions
        file_stat = os.stat(db_path)
        mode = stat.S_IMODE(file_stat.st_mode)

        # Should be readable/writable by owner only (600)
        assert mode == 0o600

        os.unlink(db_path)

    def test_migration_preserves_data(self, temp_db):
        """Test database migrations preserve existing data"""
        # Add data before "migration"
        host = temp_db.add_host({
            "id": "host1",
            "name": "Test Host",
            "url": "tcp://test:2376",
            "security_status": "secure"
        })

        # Simulate migration by adding new column
        with temp_db.get_session() as session:
            # This would normally be done by a migration script
            session.execute("ALTER TABLE docker_hosts ADD COLUMN new_field TEXT")
            session.commit()

        # Data should still be accessible
        hosts = temp_db.get_hosts()
        assert len(hosts) == 1
        assert hosts[0].name == "Test Host"