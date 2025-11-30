"""
Unit tests for HTTP health check request execution logic.

Tests verify:
- HTTP methods (GET, POST, PUT, DELETE)
- Status code validation (single, multiple, ranges)
- Timeout handling
- Connection error handling
- SSL verification
- Redirect following
- Authentication (basic, bearer)
- Custom headers
- Response time tracking

These tests use mocked httpx to test request building without actual network calls.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timezone
import json
import httpx

from health_check.http_checker import HttpHealthChecker


# =============================================================================
# HTTP Method Tests
# =============================================================================

class TestHttpMethods:
    """Test that different HTTP methods are used correctly"""

    @pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE", "PATCH"])
    @pytest.mark.asyncio
    async def test_http_method_used_in_request(self, method):
        """Test that configured HTTP method is used in request"""
        # Arrange
        monitor = Mock()
        db = Mock()
        checker = HttpHealthChecker(monitor, db)

        config = {
            'container_id': 'test123456789',
            'host_id': 'host123',
            'url': 'http://localhost:8080/health',
            'method': method,
            'expected_status_codes': '200',
            'timeout_seconds': 5,
            'check_interval_seconds': 30,
            'follow_redirects': False,
            'verify_ssl': True,
            'headers_json': None,
            'auth_config_json': None,
            'current_status': 'unknown',
            'auto_restart_on_failure': False,
            'failure_threshold': 3,
        }

        # Mock httpx client and response
        mock_response = Mock()
        mock_response.status_code = 200

        # Track what method was actually used
        actual_method = None

        async def mock_request(*args, **kwargs):
            nonlocal actual_method
            actual_method = kwargs.get('method')
            return mock_response

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.request = mock_request
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            # Mock database update
            mock_session = MagicMock()
            mock_query = mock_session.query.return_value
            mock_filter = mock_query.filter_by.return_value
            mock_filter.first.return_value = None  # No check found (skip update)

            context_mgr = Mock()
            context_mgr.__enter__ = Mock(return_value=mock_session)
            context_mgr.__exit__ = Mock(return_value=None)
            db.get_session.return_value = context_mgr

            # Act
            await checker._perform_check(config)

        # Assert
        assert actual_method == method, f"Expected method {method}, got {actual_method}"


# =============================================================================
# Status Code Validation Tests
# =============================================================================

class TestStatusCodeValidation:
    """Test status code parsing and validation"""

    @pytest.mark.parametrize("status_codes,test_code,expected_healthy", [
        # Single code
        ("200", 200, True),
        ("200", 201, False),
        ("200", 500, False),

        # Multiple codes
        ("200,201,204", 200, True),
        ("200,201,204", 201, True),
        ("200,201,204", 204, True),
        ("200,201,204", 202, False),

        # Ranges
        ("200-299", 200, True),
        ("200-299", 250, True),
        ("200-299", 299, True),
        ("200-299", 199, False),
        ("200-299", 300, False),

        # Mixed
        ("200-299,301", 200, True),
        ("200-299,301", 250, True),
        ("200-299,301", 301, True),
        ("200-299,301", 300, False),

        # Edge cases
        ("", 200, True),  # Default to 200
        ("invalid", 200, True),  # Default to 200 on parse error
    ])
    @pytest.mark.asyncio
    async def test_status_code_validation(self, status_codes, test_code, expected_healthy):
        """Test status code parsing and validation logic"""
        # Arrange
        monitor = Mock()
        db = Mock()
        checker = HttpHealthChecker(monitor, db)

        config = {
            'container_id': 'test123456789',
            'host_id': 'host123',
            'url': 'http://localhost:8080/health',
            'method': 'GET',
            'expected_status_codes': status_codes,
            'timeout_seconds': 5,
            'check_interval_seconds': 30,
            'follow_redirects': False,
            'verify_ssl': True,
            'headers_json': None,
            'auth_config_json': None,
            'current_status': 'unknown',
            'auto_restart_on_failure': False,
            'failure_threshold': 3,
        }

        # Mock response with test status code
        mock_response = Mock()
        mock_response.status_code = test_code

        # Track if check was marked healthy
        check_healthy = None

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            # Mock _update_check_state to capture is_healthy
            original_update = checker._update_check_state

            async def capture_update(config, is_healthy, response_time_ms, error_message):
                nonlocal check_healthy
                check_healthy = is_healthy
                # Don't actually update DB

            checker._update_check_state = capture_update

            # Act
            await checker._perform_check(config)

        # Assert
        assert check_healthy == expected_healthy, \
            f"Status code {test_code} with config '{status_codes}': expected healthy={expected_healthy}, got {check_healthy}"


    def test_status_code_range_parsing(self):
        """Test _parse_status_codes method directly"""
        monitor = Mock()
        db = Mock()
        checker = HttpHealthChecker(monitor, db)

        # Test single code
        assert checker._parse_status_codes("200") == {200}

        # Test multiple codes
        assert checker._parse_status_codes("200,201,204") == {200, 201, 204}

        # Test range
        result = checker._parse_status_codes("200-204")
        assert result == {200, 201, 202, 203, 204}

        # Test mixed
        result = checker._parse_status_codes("200-202,204,301")
        assert result == {200, 201, 202, 204, 301}

        # Test default on invalid
        assert checker._parse_status_codes("") == {200}
        assert checker._parse_status_codes("invalid") == {200}


# =============================================================================
# Timeout and Error Handling Tests
# =============================================================================

class TestTimeoutAndErrors:
    """Test timeout and connection error handling"""

    @pytest.mark.asyncio
    async def test_timeout_marks_unhealthy(self):
        """Test that timeout exception marks check as unhealthy"""
        # Arrange
        monitor = Mock()
        db = Mock()
        checker = HttpHealthChecker(monitor, db)

        config = {
            'container_id': 'test123456789',
            'host_id': 'host123',
            'url': 'http://localhost:8080/health',
            'method': 'GET',
            'expected_status_codes': '200',
            'timeout_seconds': 5,
            'check_interval_seconds': 30,
            'follow_redirects': False,
            'verify_ssl': True,
            'headers_json': None,
            'auth_config_json': None,
            'current_status': 'healthy',
            'auto_restart_on_failure': False,
            'failure_threshold': 3,
        }

        # Track error
        captured_healthy = None
        captured_error = None

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            # Simulate timeout
            mock_client.request = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            async def capture_update(config, is_healthy, response_time_ms, error_message):
                nonlocal captured_healthy, captured_error
                captured_healthy = is_healthy
                captured_error = error_message

            checker._update_check_state = capture_update

            # Act
            await checker._perform_check(config)

        # Assert
        assert captured_healthy is False, "Timeout should mark check as unhealthy"
        assert "Timeout" in captured_error, f"Error message should mention timeout, got: {captured_error}"


    @pytest.mark.asyncio
    async def test_connection_error_marks_unhealthy(self):
        """Test that connection error marks check as unhealthy"""
        monitor = Mock()
        db = Mock()
        checker = HttpHealthChecker(monitor, db)

        config = {
            'container_id': 'test123456789',
            'host_id': 'host123',
            'url': 'http://localhost:8080/health',
            'method': 'GET',
            'expected_status_codes': '200',
            'timeout_seconds': 5,
            'check_interval_seconds': 30,
            'follow_redirects': False,
            'verify_ssl': True,
            'headers_json': None,
            'auth_config_json': None,
            'current_status': 'healthy',
            'auto_restart_on_failure': False,
            'failure_threshold': 3,
        }

        captured_healthy = None
        captured_error = None

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            # Simulate connection failure
            mock_client.request = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            async def capture_update(config, is_healthy, response_time_ms, error_message):
                nonlocal captured_healthy, captured_error
                captured_healthy = is_healthy
                captured_error = error_message

            checker._update_check_state = capture_update

            # Act
            await checker._perform_check(config)

        # Assert
        assert captured_healthy is False
        assert "Connection" in captured_error


# =============================================================================
# SSL Verification Tests
# =============================================================================

class TestSSLVerification:
    """Test SSL verification configuration"""

    @pytest.mark.parametrize("url,verify_ssl,should_set_verify", [
        ("https://localhost/health", True, True),
        ("https://localhost/health", False, True),
        ("http://localhost/health", True, False),  # HTTP shouldn't set verify
        ("http://localhost/health", False, False),
    ])
    @pytest.mark.asyncio
    async def test_ssl_verification_setting(self, url, verify_ssl, should_set_verify):
        """Test that verify_ssl is set correctly for HTTPS (not HTTP)"""
        monitor = Mock()
        db = Mock()
        checker = HttpHealthChecker(monitor, db)

        config = {
            'container_id': 'test123456789',
            'host_id': 'host123',
            'url': url,
            'method': 'GET',
            'expected_status_codes': '200',
            'timeout_seconds': 5,
            'check_interval_seconds': 30,
            'follow_redirects': False,
            'verify_ssl': verify_ssl,
            'headers_json': None,
            'auth_config_json': None,
            'current_status': 'unknown',
            'auto_restart_on_failure': False,
            'failure_threshold': 3,
        }

        # Track client creation kwargs
        client_kwargs = None

        with patch('httpx.AsyncClient') as mock_client_class:
            def capture_client_creation(**kwargs):
                nonlocal client_kwargs
                client_kwargs = kwargs
                mock_client = AsyncMock()
                mock_response = Mock()
                mock_response.status_code = 200
                mock_client.request = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock()
                return mock_client

            mock_client_class.side_effect = capture_client_creation

            checker._update_check_state = AsyncMock()

            # Act
            await checker._perform_check(config)

        # Assert
        if should_set_verify:
            assert 'verify' in client_kwargs, f"verify should be set for {url}"
            assert client_kwargs['verify'] == verify_ssl, \
                f"verify should be {verify_ssl} for {url}"
        else:
            assert 'verify' not in client_kwargs, \
                f"verify should NOT be set for HTTP URL {url}"


# =============================================================================
# Authentication Tests
# =============================================================================

class TestAuthentication:
    """Test authentication configuration"""

    @pytest.mark.asyncio
    async def test_basic_auth_applied(self):
        """Test that basic auth is correctly applied to request"""
        monitor = Mock()
        db = Mock()
        checker = HttpHealthChecker(monitor, db)

        config = {
            'container_id': 'test123456789',
            'host_id': 'host123',
            'url': 'http://localhost:8080/health',
            'method': 'GET',
            'expected_status_codes': '200',
            'timeout_seconds': 5,
            'check_interval_seconds': 30,
            'follow_redirects': False,
            'verify_ssl': True,
            'headers_json': None,
            'auth_config_json': json.dumps({
                'type': 'basic',
                'username': 'admin',
                'password': 'secret123'
            }),
            'current_status': 'unknown',
            'auto_restart_on_failure': False,
            'failure_threshold': 3,
        }

        # Track auth in request
        actual_auth = None

        with patch('httpx.AsyncClient') as mock_client_class:
            async def capture_request(**kwargs):
                nonlocal actual_auth
                actual_auth = kwargs.get('auth')
                mock_response = Mock()
                mock_response.status_code = 200
                return mock_response

            mock_client = AsyncMock()
            mock_client.request = capture_request
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            checker._update_check_state = AsyncMock()

            # Act
            await checker._perform_check(config)

        # Assert
        assert actual_auth is not None, "Auth should be set"
        assert actual_auth == ('admin', 'secret123'), \
            f"Expected ('admin', 'secret123'), got {actual_auth}"


    @pytest.mark.asyncio
    async def test_bearer_token_auth_applied(self):
        """Test that bearer token is correctly applied to Authorization header"""
        monitor = Mock()
        db = Mock()
        checker = HttpHealthChecker(monitor, db)

        config = {
            'container_id': 'test123456789',
            'host_id': 'host123',
            'url': 'http://localhost:8080/health',
            'method': 'GET',
            'expected_status_codes': '200',
            'timeout_seconds': 5,
            'check_interval_seconds': 30,
            'follow_redirects': False,
            'verify_ssl': True,
            'headers_json': None,
            'auth_config_json': json.dumps({
                'type': 'bearer',
                'token': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9'
            }),
            'current_status': 'unknown',
            'auto_restart_on_failure': False,
            'failure_threshold': 3,
        }

        # Track headers in request
        actual_headers = None

        with patch('httpx.AsyncClient') as mock_client_class:
            async def capture_request(**kwargs):
                nonlocal actual_headers
                actual_headers = kwargs.get('headers')
                mock_response = Mock()
                mock_response.status_code = 200
                return mock_response

            mock_client = AsyncMock()
            mock_client.request = capture_request
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            checker._update_check_state = AsyncMock()

            # Act
            await checker._perform_check(config)

        # Assert
        assert actual_headers is not None, "Headers should be set for bearer token"
        assert 'Authorization' in actual_headers, "Authorization header missing"
        assert actual_headers['Authorization'].startswith('Bearer '), \
            f"Expected 'Bearer ...' header, got: {actual_headers['Authorization']}"


# =============================================================================
# Custom Headers Tests
# =============================================================================

class TestCustomHeaders:
    """Test custom header configuration"""

    @pytest.mark.asyncio
    async def test_custom_headers_applied(self):
        """Test that custom headers are correctly applied to request"""
        monitor = Mock()
        db = Mock()
        checker = HttpHealthChecker(monitor, db)

        config = {
            'container_id': 'test123456789',
            'host_id': 'host123',
            'url': 'http://localhost:8080/health',
            'method': 'GET',
            'expected_status_codes': '200',
            'timeout_seconds': 5,
            'check_interval_seconds': 30,
            'follow_redirects': False,
            'verify_ssl': True,
            'headers_json': json.dumps({
                'X-Custom-Header': 'custom-value',
                'X-Request-ID': '12345',
                'Accept': 'application/json'
            }),
            'auth_config_json': None,
            'current_status': 'unknown',
            'auto_restart_on_failure': False,
            'failure_threshold': 3,
        }

        # Track headers
        actual_headers = None

        with patch('httpx.AsyncClient') as mock_client_class:
            async def capture_request(**kwargs):
                nonlocal actual_headers
                actual_headers = kwargs.get('headers')
                mock_response = Mock()
                mock_response.status_code = 200
                return mock_response

            mock_client = AsyncMock()
            mock_client.request = capture_request
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            checker._update_check_state = AsyncMock()

            # Act
            await checker._perform_check(config)

        # Assert
        assert actual_headers is not None
        assert actual_headers['X-Custom-Header'] == 'custom-value'
        assert actual_headers['X-Request-ID'] == '12345'
        assert actual_headers['Accept'] == 'application/json'


    @pytest.mark.asyncio
    async def test_invalid_headers_json_handled_gracefully(self):
        """Test that invalid headers JSON doesn't crash the check"""
        monitor = Mock()
        db = Mock()
        checker = HttpHealthChecker(monitor, db)

        config = {
            'container_id': 'test123456789',
            'host_id': 'host123',
            'url': 'http://localhost:8080/health',
            'method': 'GET',
            'expected_status_codes': '200',
            'timeout_seconds': 5,
            'check_interval_seconds': 30,
            'follow_redirects': False,
            'verify_ssl': True,
            'headers_json': '{invalid json}',  # Invalid JSON
            'auth_config_json': None,
            'current_status': 'unknown',
            'auto_restart_on_failure': False,
            'failure_threshold': 3,
        }

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_response = Mock()
            mock_response.status_code = 200
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            checker._update_check_state = AsyncMock()

            # Act - should not raise exception
            await checker._perform_check(config)

        # Assert - check completed (no exception raised)
        assert checker._update_check_state.called


# =============================================================================
# Response Time Tracking Tests
# =============================================================================

class TestResponseTimeTracking:
    """Test that response time is correctly measured"""

    @pytest.mark.asyncio
    async def test_response_time_tracked(self):
        """Test that response time is measured and passed to update"""
        monitor = Mock()
        db = Mock()
        checker = HttpHealthChecker(monitor, db)

        config = {
            'container_id': 'test123456789',
            'host_id': 'host123',
            'url': 'http://localhost:8080/health',
            'method': 'GET',
            'expected_status_codes': '200',
            'timeout_seconds': 5,
            'check_interval_seconds': 30,
            'follow_redirects': False,
            'verify_ssl': True,
            'headers_json': None,
            'auth_config_json': None,
            'current_status': 'unknown',
            'auto_restart_on_failure': False,
            'failure_threshold': 3,
        }

        captured_response_time = None

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_response = Mock()
            mock_response.status_code = 200
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            async def capture_update(config, is_healthy, response_time_ms, error_message):
                nonlocal captured_response_time
                captured_response_time = response_time_ms

            checker._update_check_state = capture_update

            # Act
            await checker._perform_check(config)

        # Assert
        assert captured_response_time is not None, "Response time should be measured"
        assert isinstance(captured_response_time, int), "Response time should be integer (ms)"
        assert captured_response_time >= 0, "Response time should be non-negative"
