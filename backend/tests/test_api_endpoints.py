"""
Comprehensive tests for all API endpoints
Ensures proper authentication, validation, and response handling
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, Mock
import json
import uuid
from datetime import datetime


class TestAPIEndpoints:
    """Test all API endpoints comprehensively"""

    @pytest.fixture
    def authenticated_client(self):
        """Create a test client with authentication"""
        from main import app
        client = TestClient(app)

        # Mock authentication
        with patch('auth.utils.verify_session_auth'):
            yield client

    @pytest.fixture
    def mock_monitor(self):
        """Create a mock monitor instance"""
        monitor = MagicMock()
        monitor.hosts = {}
        monitor.clients = {}
        monitor.get_all_containers = MagicMock(return_value=[])
        return monitor

    # ============= Authentication Endpoints =============

    def test_login_success(self, authenticated_client):
        """Test successful login"""
        with patch('auth.routes.DatabaseManager') as mock_db:
            mock_db_instance = MagicMock()
            mock_db_instance.get_user.return_value = MagicMock(
                username='admin',
                password_hash='hashed_password',
                password_change_required=False
            )
            mock_db.return_value = mock_db_instance

            with patch('auth.utils.verify_password', return_value=True):
                response = authenticated_client.post("/api/auth/login", json={
                    "username": "admin",
                    "password": "correct_password"
                })
                assert response.status_code == 200
                data = response.json()
                assert data["username"] == "admin"
                assert "session_id" in data

    def test_login_invalid_credentials(self, authenticated_client):
        """Test login with invalid credentials"""
        with patch('auth.routes.DatabaseManager') as mock_db:
            mock_db_instance = MagicMock()
            mock_db_instance.get_user.return_value = None
            mock_db.return_value = mock_db_instance

            response = authenticated_client.post("/api/auth/login", json={
                "username": "admin",
                "password": "wrong_password"
            })
            assert response.status_code == 401

    def test_login_missing_fields(self, authenticated_client):
        """Test login with missing fields"""
        response = authenticated_client.post("/api/auth/login", json={
            "username": "admin"
            # missing password
        })
        assert response.status_code == 422

    def test_logout(self, authenticated_client):
        """Test logout endpoint"""
        with patch('auth.routes.DatabaseManager') as mock_db:
            mock_db_instance = MagicMock()
            mock_db.return_value = mock_db_instance

            response = authenticated_client.post("/api/auth/logout")
            assert response.status_code == 200

    def test_auth_status(self, authenticated_client):
        """Test auth status check"""
        response = authenticated_client.get("/api/auth/status")
        assert response.status_code == 200
        data = response.json()
        assert "authenticated" in data

    def test_change_password(self, authenticated_client):
        """Test password change"""
        with patch('auth.routes.DatabaseManager') as mock_db:
            mock_db_instance = MagicMock()
            mock_db_instance.get_user.return_value = MagicMock(
                username='admin',
                password_hash='old_hash'
            )
            mock_db.return_value = mock_db_instance

            with patch('auth.utils.verify_password', return_value=True):
                response = authenticated_client.post("/api/auth/change-password", json={
                    "current_password": "old_password",
                    "new_password": "NewSecurePassword123!"
                })
                assert response.status_code == 200

    def test_change_password_weak(self, authenticated_client):
        """Test password change with weak password"""
        response = authenticated_client.post("/api/auth/change-password", json={
            "current_password": "old_password",
            "new_password": "weak"
        })
        assert response.status_code == 400

    # ============= Host Management Endpoints =============

    def test_get_hosts(self, authenticated_client, mock_monitor):
        """Test getting all hosts"""
        mock_host = MagicMock()
        mock_host.id = "host1"
        mock_host.name = "TestHost"
        mock_host.url = "tcp://localhost:2376"
        mock_host.status = "online"
        mock_host.container_count = 5
        mock_host.security_status = "secure"

        mock_monitor.hosts = {"host1": mock_host}

        with patch('main.monitor', mock_monitor):
            response = authenticated_client.get("/api/hosts")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["name"] == "TestHost"

    def test_add_host_success(self, authenticated_client, mock_monitor):
        """Test adding a new host"""
        mock_host = MagicMock()
        mock_host.id = "new_host"
        mock_host.name = "NewHost"
        mock_monitor.add_host = MagicMock(return_value=mock_host)

        with patch('main.monitor', mock_monitor):
            response = authenticated_client.post("/api/hosts", json={
                "name": "NewHost",
                "url": "tcp://localhost:2376"
            })
            assert response.status_code == 200
            data = response.json()
            assert data["name"] == "NewHost"

    def test_add_host_duplicate(self, authenticated_client, mock_monitor):
        """Test adding duplicate host"""
        mock_monitor.add_host = MagicMock(side_effect=ValueError("Host already exists"))

        with patch('main.monitor', mock_monitor):
            response = authenticated_client.post("/api/hosts", json={
                "name": "ExistingHost",
                "url": "tcp://localhost:2376"
            })
            assert response.status_code == 400

    def test_add_host_with_tls(self, authenticated_client, mock_monitor):
        """Test adding host with TLS certificates"""
        mock_host = MagicMock()
        mock_host.id = "secure_host"
        mock_host.name = "SecureHost"
        mock_host.security_status = "secure"
        mock_monitor.add_host = MagicMock(return_value=mock_host)

        with patch('main.monitor', mock_monitor):
            response = authenticated_client.post("/api/hosts", json={
                "name": "SecureHost",
                "url": "tcp://secure.example.com:2376",
                "tls_cert": "-----BEGIN CERTIFICATE-----\ncert\n-----END CERTIFICATE-----",
                "tls_key": "-----BEGIN PRIVATE KEY-----\nkey\n-----END PRIVATE KEY-----",
                "tls_ca": "-----BEGIN CERTIFICATE-----\nca\n-----END CERTIFICATE-----"
            })
            assert response.status_code == 200
            data = response.json()
            assert data["security_status"] == "secure"

    def test_remove_host(self, authenticated_client, mock_monitor):
        """Test removing a host"""
        with patch('main.monitor', mock_monitor):
            response = authenticated_client.delete("/api/hosts/host123")
            assert response.status_code == 200
            mock_monitor.remove_host.assert_called_once_with("host123")

    def test_test_host_connection(self, authenticated_client):
        """Test host connection testing"""
        with patch('docker.DockerClient') as mock_docker:
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            mock_client.version.return_value = {"Version": "20.10.0"}
            mock_docker.return_value = mock_client

            response = authenticated_client.post("/api/hosts/test", json={
                "url": "tcp://localhost:2376"
            })
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

    def test_test_host_connection_failure(self, authenticated_client):
        """Test host connection testing with failure"""
        with patch('docker.DockerClient') as mock_docker:
            mock_docker.side_effect = Exception("Connection refused")

            response = authenticated_client.post("/api/hosts/test", json={
                "url": "tcp://invalid:2376"
            })
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is False
            assert "Connection refused" in data["error"]

    # ============= Container Management Endpoints =============

    def test_get_containers(self, authenticated_client, mock_monitor):
        """Test getting all containers"""
        mock_monitor.get_all_containers.return_value = [
            {
                "id": "container1",
                "name": "app1",
                "status": "running",
                "host_id": "host1"
            },
            {
                "id": "container2",
                "name": "app2",
                "status": "exited",
                "host_id": "host2"
            }
        ]

        with patch('main.monitor', mock_monitor):
            response = authenticated_client.get("/api/containers")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
            assert data[0]["name"] == "app1"

    def test_get_container_logs(self, authenticated_client, mock_monitor):
        """Test getting container logs"""
        mock_container = MagicMock()
        mock_container.logs.return_value = b"Log line 1\nLog line 2\n"

        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container
        mock_monitor.clients = {"host1": mock_client}

        with patch('main.monitor', mock_monitor):
            response = authenticated_client.get(
                "/api/hosts/host1/containers/container123/logs?tail=100"
            )
            assert response.status_code == 200
            data = response.json()
            assert "logs" in data
            assert "Log line 1" in data["logs"]

    def test_restart_container(self, authenticated_client, mock_monitor):
        """Test restarting a container"""
        with patch('main.monitor', mock_monitor):
            response = authenticated_client.post("/api/containers/container123/restart", json={
                "host_id": "host1"
            })
            assert response.status_code == 200
            mock_monitor.restart_container.assert_called_once_with("host1", "container123")

    def test_stop_container(self, authenticated_client, mock_monitor):
        """Test stopping a container"""
        with patch('main.monitor', mock_monitor):
            response = authenticated_client.post("/api/containers/container123/stop", json={
                "host_id": "host1"
            })
            assert response.status_code == 200
            mock_monitor.stop_container.assert_called_once_with("host1", "container123")

    def test_start_container(self, authenticated_client, mock_monitor):
        """Test starting a container"""
        with patch('main.monitor', mock_monitor):
            response = authenticated_client.post("/api/containers/container123/start", json={
                "host_id": "host1"
            })
            assert response.status_code == 200
            mock_monitor.start_container.assert_called_once_with("host1", "container123")

    def test_pause_container(self, authenticated_client, mock_monitor):
        """Test pausing a container"""
        with patch('main.monitor', mock_monitor):
            response = authenticated_client.post("/api/containers/container123/pause", json={
                "host_id": "host1"
            })
            assert response.status_code == 200
            mock_monitor.pause_container.assert_called_once_with("host1", "container123")

    def test_unpause_container(self, authenticated_client, mock_monitor):
        """Test unpausing a container"""
        with patch('main.monitor', mock_monitor):
            response = authenticated_client.post("/api/containers/container123/unpause", json={
                "host_id": "host1"
            })
            assert response.status_code == 200
            mock_monitor.unpause_container.assert_called_once_with("host1", "container123")

    def test_toggle_auto_restart(self, authenticated_client, mock_monitor):
        """Test toggling auto-restart"""
        with patch('main.monitor', mock_monitor):
            response = authenticated_client.post("/api/containers/container123/auto-restart", json={
                "host_id": "host1",
                "container_name": "app1",
                "enabled": True
            })
            assert response.status_code == 200
            mock_monitor.toggle_auto_restart.assert_called_once()

    # ============= Alert Management Endpoints =============

    def test_get_alerts(self, authenticated_client):
        """Test getting all alert rules"""
        with patch('main.db') as mock_db:
            mock_db.get_alert_rules.return_value = [
                MagicMock(
                    id=1,
                    name="Test Alert",
                    container_pattern="test_*",
                    trigger_states=["exited"],
                    trigger_events=["die"],
                    enabled=True
                )
            ]

            response = authenticated_client.get("/api/alerts")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["name"] == "Test Alert"

    def test_create_alert(self, authenticated_client):
        """Test creating an alert rule"""
        with patch('main.db') as mock_db:
            mock_alert = MagicMock()
            mock_alert.id = 1
            mock_alert.name = "New Alert"
            mock_db.add_alert_rule.return_value = mock_alert

            response = authenticated_client.post("/api/alerts", json={
                "name": "New Alert",
                "container_pattern": "app_*",
                "trigger_states": ["exited", "dead"],
                "trigger_events": ["die", "oom"],
                "cooldown_minutes": 5,
                "enabled": True
            })
            assert response.status_code == 200

    def test_create_alert_invalid_pattern(self, authenticated_client):
        """Test creating alert with invalid regex pattern"""
        response = authenticated_client.post("/api/alerts", json={
            "name": "Invalid Alert",
            "container_pattern": "[invalid(regex",  # Invalid regex
            "trigger_states": ["exited"],
            "trigger_events": [],
            "cooldown_minutes": 5,
            "enabled": True
        })
        assert response.status_code == 400

    def test_update_alert(self, authenticated_client):
        """Test updating an alert rule"""
        with patch('main.db') as mock_db:
            mock_alert = MagicMock()
            mock_alert.id = 1
            mock_db.update_alert_rule.return_value = mock_alert

            response = authenticated_client.put("/api/alerts/1", json={
                "enabled": False
            })
            assert response.status_code == 200

    def test_delete_alert(self, authenticated_client):
        """Test deleting an alert rule"""
        with patch('main.db') as mock_db:
            response = authenticated_client.delete("/api/alerts/1")
            assert response.status_code == 200
            mock_db.delete_alert_rule.assert_called_once_with(1)

    def test_test_alert(self, authenticated_client):
        """Test alert testing endpoint"""
        with patch('main.db') as mock_db:
            mock_alert = MagicMock()
            mock_alert.name = "Test Alert"
            mock_db.get_alert_rule.return_value = mock_alert

            with patch('main.notification_manager') as mock_notif:
                mock_notif.send_test_alert.return_value = True

                response = authenticated_client.post("/api/alerts/1/test")
                assert response.status_code == 200

    # ============= Settings Endpoints =============

    def test_get_settings(self, authenticated_client):
        """Test getting settings"""
        with patch('main.db') as mock_db:
            mock_db.get_settings.return_value = {
                "theme": "dark",
                "refresh_interval": 5
            }

            response = authenticated_client.get("/api/settings")
            assert response.status_code == 200
            data = response.json()
            assert data["theme"] == "dark"

    def test_update_settings(self, authenticated_client):
        """Test updating settings"""
        with patch('main.db') as mock_db:
            response = authenticated_client.put("/api/settings", json={
                "theme": "light",
                "refresh_interval": 10
            })
            assert response.status_code == 200
            mock_db.update_settings.assert_called_once()

    # ============= Health Check Endpoint =============

    def test_health_check(self, authenticated_client):
        """Test health check endpoint"""
        response = authenticated_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    # ============= Rate Limit Stats =============

    def test_rate_limit_stats(self, authenticated_client):
        """Test rate limit statistics endpoint"""
        with patch('main.rate_limiter') as mock_limiter:
            mock_limiter.get_stats.return_value = {
                "blocked_ips": ["192.168.1.100"],
                "total_blocked": 5
            }

            response = authenticated_client.get("/api/rate-limit/stats")
            assert response.status_code == 200
            data = response.json()
            assert "blocked_ips" in data

    # ============= Error Handling Tests =============

    def test_404_not_found(self, authenticated_client):
        """Test 404 for non-existent endpoint"""
        response = authenticated_client.get("/api/nonexistent")
        assert response.status_code == 404

    def test_method_not_allowed(self, authenticated_client):
        """Test 405 for wrong HTTP method"""
        response = authenticated_client.get("/api/hosts")  # Should be POST
        # Actually this is valid, so let's test a real case
        response = authenticated_client.patch("/api/auth/login")  # Should be POST
        assert response.status_code == 405

    def test_request_validation_error(self, authenticated_client):
        """Test 422 for invalid request data"""
        response = authenticated_client.post("/api/hosts", json={
            "name": "Test",
            # Missing required 'url' field
        })
        assert response.status_code == 422

    def test_internal_server_error_handling(self, authenticated_client, mock_monitor):
        """Test 500 error handling"""
        mock_monitor.get_all_containers.side_effect = Exception("Database error")

        with patch('main.monitor', mock_monitor):
            response = authenticated_client.get("/api/containers")
            assert response.status_code == 500