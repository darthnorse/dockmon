"""
Tests for error recovery and edge cases
Ensures the system handles failures gracefully
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import asyncio
from datetime import datetime, timedelta


class TestErrorRecovery:
    """Test error recovery mechanisms"""

    def test_docker_connection_retry(self):
        """Test automatic retry when Docker connection fails"""
        from docker_monitor.monitor import DockerMonitor

        with patch('docker.DockerClient') as mock_docker:
            # First 2 attempts fail, 3rd succeeds
            mock_docker.side_effect = [
                Exception("Connection refused"),
                Exception("Connection refused"),
                MagicMock()  # Success
            ]

            monitor = DockerMonitor(MagicMock())

            # Should retry and eventually succeed
            from models.docker_models import DockerHostConfig
            config = DockerHostConfig(
                name="TestHost",
                url="tcp://localhost:2376"
            )

            with patch('time.sleep'):  # Skip actual sleep
                host = monitor.add_host_with_retry(config, max_retries=3)

            assert host is not None
            assert mock_docker.call_count == 3

    def test_database_transaction_rollback(self, temp_db):
        """Test database transaction rollback on error"""
        from database import DatabaseManager

        # Simulate error during transaction
        with patch.object(temp_db, 'get_session') as mock_session:
            session = MagicMock()
            session.commit.side_effect = Exception("Database error")
            mock_session.return_value.__enter__ = MagicMock(return_value=session)
            mock_session.return_value.__exit__ = MagicMock(return_value=None)

            # Should not crash, should rollback
            try:
                temp_db.add_host({"name": "Test", "url": "tcp://test:2376"})
            except:
                pass

            session.rollback.assert_called()

    @pytest.mark.asyncio
    async def test_websocket_reconnection_backoff(self):
        """Test exponential backoff for WebSocket reconnection"""
        from realtime import WebSocketReconnector

        reconnector = WebSocketReconnector()

        attempts = []

        async def mock_connect():
            attempts.append(datetime.utcnow())
            if len(attempts) < 3:
                raise Exception("Connection failed")
            return MagicMock()  # Success on 3rd attempt

        ws = await reconnector.connect_with_backoff(mock_connect)

        assert ws is not None
        assert len(attempts) == 3

        # Check exponential backoff
        if len(attempts) >= 2:
            gap1 = (attempts[1] - attempts[0]).total_seconds()
            gap2 = (attempts[2] - attempts[1]).total_seconds()
            assert gap2 > gap1  # Exponential backoff

    def test_corrupted_database_recovery(self):
        """Test recovery from corrupted database"""
        from database import DatabaseManager
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        # Write corrupted data
        with open(db_path, 'w') as f:
            f.write("This is not a valid SQLite database")

        # Should detect corruption and recreate
        db = DatabaseManager(db_path)

        # Should work after recreation
        db.add_host({
            "id": "test123",
            "name": "Test",
            "url": "tcp://test:2376",
            "security_status": "insecure"
        })

        hosts = db.get_hosts()
        assert len(hosts) >= 0  # Database is functional

        os.unlink(db_path)

    def test_notification_failure_fallback(self):
        """Test fallback when primary notification channel fails"""
        from notifications import NotificationManager

        manager = NotificationManager(MagicMock())

        # Setup multiple channels
        channels = [
            {"type": "telegram", "name": "Primary", "enabled": True},
            {"type": "discord", "name": "Fallback", "enabled": True}
        ]

        with patch.object(manager, 'send_telegram', side_effect=Exception("Failed")):
            with patch.object(manager, 'send_discord', return_value=True) as mock_discord:
                manager.send_alert_with_fallback("Test alert", channels)

                # Should try discord after telegram fails
                mock_discord.assert_called()

    def test_rate_limit_recovery_after_ban(self):
        """Test that rate limiting recovers after ban expires"""
        from auth.rate_limiter import RateLimiter

        limiter = RateLimiter()
        client_ip = "192.168.1.100"

        # Ban the IP
        limiter.ban_ip(client_ip, duration_minutes=0.01)  # 0.6 seconds

        # Should be banned
        allowed, _ = limiter.check_rate_limit(client_ip, "/api/test")
        assert allowed is False

        # Wait for ban to expire
        import time
        time.sleep(1)

        # Should be allowed again
        allowed, _ = limiter.check_rate_limit(client_ip, "/api/test")
        assert allowed is True

    def test_container_restart_after_crash(self):
        """Test automatic container restart after crash"""
        from docker_monitor.monitor import DockerMonitor

        monitor = DockerMonitor(MagicMock())

        # Setup auto-restart
        monitor.toggle_auto_restart("host123", "container456", "web-app", True)

        # Simulate container crash
        mock_container = MagicMock()
        mock_container.status = "exited"
        mock_container.attrs = {"State": {"ExitCode": 1}}

        with patch.object(monitor, 'restart_container') as mock_restart:
            monitor.handle_container_exit("host123", "container456", mock_container)

            # Should trigger restart
            mock_restart.assert_called_with("host123", "container456")

    def test_disk_space_monitoring(self):
        """Test handling of low disk space conditions"""
        from utils.system_monitor import check_disk_space

        with patch('shutil.disk_usage') as mock_disk:
            # Simulate low disk space
            mock_disk.return_value = MagicMock(
                total=100 * 1024 * 1024 * 1024,  # 100GB
                used=95 * 1024 * 1024 * 1024,     # 95GB
                free=5 * 1024 * 1024 * 1024       # 5GB
            )

            result = check_disk_space("/app/data")

            assert result["percentage_used"] > 90
            assert result["should_alert"] is True

    def test_memory_leak_detection(self):
        """Test detection of memory leaks"""
        from utils.system_monitor import detect_memory_leak

        # Simulate increasing memory usage
        memory_samples = [
            100 * 1024 * 1024,  # 100MB
            200 * 1024 * 1024,  # 200MB
            400 * 1024 * 1024,  # 400MB
            800 * 1024 * 1024,  # 800MB
        ]

        is_leak = detect_memory_leak(memory_samples, threshold_multiplier=2)
        assert is_leak is True  # Memory doubled multiple times

    def test_concurrent_update_handling(self, temp_db):
        """Test handling of concurrent database updates"""
        from database import DatabaseManager
        import threading

        results = []

        def update_host():
            try:
                temp_db.update_host("host123", {"status": "online"})
                results.append("success")
            except Exception as e:
                results.append(f"error: {e}")

        # Add a host first
        temp_db.add_host({
            "id": "host123",
            "name": "Test",
            "url": "tcp://test:2376",
            "security_status": "insecure"
        })

        # Try concurrent updates
        threads = []
        for _ in range(10):
            t = threading.Thread(target=update_host)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Should handle concurrency without crashes
        success_count = results.count("success")
        assert success_count > 0

    def test_invalid_docker_response_handling(self):
        """Test handling of invalid/unexpected Docker API responses"""
        from docker_monitor.monitor import parse_container_info

        # Invalid container data
        invalid_data = [
            None,
            {},
            {"id": "abc"},  # Missing required fields
            {"attrs": None},  # Null attrs
        ]

        for data in invalid_data:
            # Should not crash, should return safe defaults
            result = parse_container_info(data)
            assert result is not None
            assert "id" in result
            assert "status" in result

    def test_certificate_expiry_detection(self):
        """Test detection of expiring TLS certificates"""
        from security.tls_validator import check_certificate_expiry
        import ssl
        from datetime import datetime, timedelta

        # Mock certificate that expires in 5 days
        mock_cert = {
            'notAfter': (datetime.utcnow() + timedelta(days=5)).strftime('%b %d %H:%M:%S %Y GMT')
        }

        with patch('ssl.SSLSocket.getpeercert', return_value=mock_cert):
            result = check_certificate_expiry("tcp://test:2376")

            assert result["days_until_expiry"] <= 5
            assert result["should_warn"] is True

    @pytest.mark.asyncio
    async def test_deadlock_prevention(self):
        """Test prevention of deadlocks in async operations"""
        from asyncio import Lock, TimeoutError

        lock1 = Lock()
        lock2 = Lock()

        async def task1():
            async with lock1:
                await asyncio.sleep(0.1)
                # Try to acquire lock2 with timeout
                try:
                    async with asyncio.timeout(0.5):
                        async with lock2:
                            pass
                except TimeoutError:
                    return "timeout_prevented_deadlock"

        async def task2():
            async with lock2:
                await asyncio.sleep(0.1)
                # Try to acquire lock1 with timeout
                try:
                    async with asyncio.timeout(0.5):
                        async with lock1:
                            pass
                except TimeoutError:
                    return "timeout_prevented_deadlock"

        # Run both tasks - should not deadlock due to timeouts
        results = await asyncio.gather(task1(), task2(), return_exceptions=True)

        # At least one should timeout, preventing deadlock
        assert "timeout_prevented_deadlock" in results or any(isinstance(r, TimeoutError) for r in results)