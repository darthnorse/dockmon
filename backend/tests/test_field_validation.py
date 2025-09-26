"""
Tests for field name validation and API contract consistency
These tests would have caught the bot_token vs token mismatch
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import json


class TestFieldValidation:
    """Test field name consistency between frontend and backend"""

    @pytest.fixture
    def client(self):
        """Create test client"""
        from main import app
        return TestClient(app)

    def test_telegram_channel_requires_bot_token_not_token(self, client):
        """Test that Telegram channel requires 'bot_token' field, not 'token'"""
        with patch('auth.utils.verify_session_auth', return_value=True):
            with patch('main.monitor') as mock_monitor:
                mock_db = MagicMock()
                mock_monitor.db = mock_db

                # This is what the frontend was incorrectly sending
                incorrect_payload = {
                    "name": "Telegram",
                    "type": "telegram",
                    "config": {
                        "token": "123456:ABC-DEF",  # Wrong field name!
                        "chat_id": "-100123456789"
                    },
                    "enabled": True
                }

                response = client.post("/api/notifications/channels", json=incorrect_payload)

                # Should fail with 422 validation error
                assert response.status_code == 422
                error_detail = response.json()["detail"][0]
                assert "bot_token" in error_detail["msg"]

                # Correct payload should work
                correct_payload = {
                    "name": "Telegram",
                    "type": "telegram",
                    "config": {
                        "bot_token": "123456:ABC-DEF",  # Correct field name
                        "chat_id": "-100123456789"
                    },
                    "enabled": True
                }

                mock_db.add_notification_channel.return_value = MagicMock(id=1)
                response = client.post("/api/notifications/channels", json=correct_payload)
                assert response.status_code == 200

    def test_discord_channel_requires_webhook_url(self, client):
        """Test Discord channel field validation"""
        with patch('auth.utils.verify_session_auth', return_value=True):
            with patch('main.monitor') as mock_monitor:
                mock_db = MagicMock()
                mock_monitor.db = mock_db

                # Missing webhook_url
                invalid_payload = {
                    "name": "Discord",
                    "type": "discord",
                    "config": {
                        "url": "https://discord.com/webhook"  # Wrong field name
                    },
                    "enabled": True
                }

                response = client.post("/api/notifications/channels", json=invalid_payload)
                assert response.status_code == 422

                # Correct field
                correct_payload = {
                    "name": "Discord",
                    "type": "discord",
                    "config": {
                        "webhook_url": "https://discord.com/api/webhooks/123/abc"
                    },
                    "enabled": True
                }

                mock_db.add_notification_channel.return_value = MagicMock(id=1)
                response = client.post("/api/notifications/channels", json=correct_payload)
                assert response.status_code == 200

    def test_pushover_channel_field_names(self, client):
        """Test Pushover channel field validation"""
        with patch('auth.utils.verify_session_auth', return_value=True):
            with patch('main.monitor') as mock_monitor:
                mock_db = MagicMock()
                mock_monitor.db = mock_db

                # Test various wrong field combinations
                wrong_payloads = [
                    {
                        "config": {
                            "token": "app_token_here",  # Should be app_token
                            "user_key": "user_key_here"
                        }
                    },
                    {
                        "config": {
                            "app_token": "app_token_here",
                            "user": "user_key_here"  # Should be user_key
                        }
                    },
                    {
                        "config": {
                            "application_token": "app_token_here",  # Wrong name
                            "user_key": "user_key_here"
                        }
                    }
                ]

                for config in wrong_payloads:
                    payload = {
                        "name": "Pushover",
                        "type": "pushover",
                        "enabled": True,
                        **config
                    }
                    response = client.post("/api/notifications/channels", json=payload)
                    assert response.status_code == 422, f"Failed for config: {config}"

                # Correct fields
                correct_payload = {
                    "name": "Pushover",
                    "type": "pushover",
                    "config": {
                        "app_token": "azGDORePK8gMaC0QOYAMyEEuzJnyUi",
                        "user_key": "uQiRzpo4DXghDmr9QzzfQu27cmVRsG"
                    },
                    "enabled": True
                }

                mock_db.add_notification_channel.return_value = MagicMock(id=1)
                response = client.post("/api/notifications/channels", json=correct_payload)
                assert response.status_code == 200

    def test_alert_rule_field_consistency(self, client):
        """Test alert rule field names are consistent"""
        with patch('auth.utils.verify_session_auth', return_value=True):
            with patch('main.db') as mock_db:
                # Test that frontend field names match backend expectations
                payload = {
                    "name": "Test Alert",
                    "container_pattern": "web-*",
                    "trigger_states": ["exited", "dead"],  # Not trigger_state
                    "trigger_events": ["die", "oom"],      # Not trigger_event
                    "cooldown_minutes": 5,
                    "enabled": True
                }

                mock_db.add_alert_rule.return_value = MagicMock(id=1)
                response = client.post("/api/alerts", json=payload)

                # Should succeed with correct field names
                assert response.status_code == 200

                # Test wrong field names
                wrong_payload = {
                    "name": "Test Alert",
                    "container_pattern": "web-*",
                    "trigger_state": ["exited"],  # Wrong: singular
                    "trigger_event": ["die"],      # Wrong: singular
                    "cooldown_minutes": 5,
                    "enabled": True
                }

                response = client.post("/api/alerts", json=wrong_payload)
                assert response.status_code == 422

    def test_container_operation_field_names(self, client):
        """Test container operation endpoints use consistent field names"""
        with patch('auth.utils.verify_session_auth', return_value=True):
            with patch('main.monitor') as mock_monitor:
                # Test restart endpoint
                payload = {"host_id": "host123"}  # Not host_uuid or hostId

                response = client.post("/api/containers/container123/restart", json=payload)
                assert response.status_code == 200

                # Test auto-restart toggle
                payload = {
                    "host_id": "host123",
                    "container_name": "web-app",  # Not containerName
                    "enabled": True
                }

                response = client.post("/api/containers/container123/auto-restart", json=payload)
                assert response.status_code == 200

    def test_settings_field_names(self, client):
        """Test settings field name consistency"""
        with patch('auth.utils.verify_session_auth', return_value=True):
            with patch('main.db') as mock_db:
                # These field names should match what frontend sends
                settings_payload = {
                    "refresh_interval": 5,       # Not refreshInterval
                    "enable_notifications": True, # Not enableNotifications
                    "dark_mode": True,           # Not darkMode
                    "auto_cleanup_days": 30      # Not autoCleanupDays
                }

                response = client.put("/api/settings", json=settings_payload)
                assert response.status_code == 200

    def test_authentication_field_names(self, client):
        """Test auth endpoints use consistent field names"""
        with patch('auth.routes.DatabaseManager') as mock_db:
            mock_db_instance = MagicMock()
            mock_db.return_value = mock_db_instance

            # Login should expect 'username' and 'password'
            login_payload = {
                "username": "admin",  # Not user_name or userName
                "password": "password123"  # Not pass or passwd
            }

            response = client.post("/api/auth/login", json=login_payload)
            # Should at least parse the request (might fail auth)
            assert response.status_code in [200, 401]

            # Wrong field names should fail validation
            wrong_payload = {
                "user": "admin",  # Wrong field name
                "pass": "password123"  # Wrong field name
            }

            response = client.post("/api/auth/login", json=wrong_payload)
            assert response.status_code == 422

            # Password change endpoint
            change_payload = {
                "current_password": "old_password",  # Not currentPassword
                "new_password": "new_password"       # Not newPassword
            }

            response = client.post("/api/auth/change-password", json=change_payload)
            # Should at least parse the request
            assert response.status_code in [200, 400, 401]

    def test_host_configuration_field_names(self, client):
        """Test host configuration field names"""
        with patch('auth.utils.verify_session_auth', return_value=True):
            with patch('main.monitor') as mock_monitor:
                mock_host = MagicMock()
                mock_host.id = "host123"
                mock_monitor.add_host.return_value = mock_host

                # Correct field names
                host_payload = {
                    "name": "Production Server",
                    "url": "tcp://192.168.1.100:2376",
                    "tls_cert": "cert_content",  # Not tlsCert or certificate
                    "tls_key": "key_content",    # Not tlsKey or private_key
                    "tls_ca": "ca_content"       # Not tlsCa or ca_cert
                }

                response = client.post("/api/hosts", json=host_payload)
                assert response.status_code == 200

                # Test connection endpoint
                test_payload = {
                    "url": "tcp://192.168.1.100:2376",  # Not host_url
                    "tls_cert": "cert",
                    "tls_key": "key",
                    "tls_ca": "ca"
                }

                with patch('docker.DockerClient') as mock_docker:
                    mock_docker.return_value.ping.return_value = True
                    response = client.post("/api/hosts/test", json=test_payload)
                    assert response.status_code == 200