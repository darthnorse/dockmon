"""
Unit tests for SMTP notification channel.

Tests the _send_smtp() method in NotificationService for sending
notifications via SMTP, with and without authentication.

Issue: #179
"""

import sys
import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock

from notifications import NotificationService


VALID_SMTP_CONFIG = {
    'smtp_host': 'mail.example.com',
    'smtp_port': 587,
    'smtp_user': 'user@example.com',
    'smtp_password': 'secret',
    'from_email': 'dockmon@example.com',
    'to_email': 'admin@example.com',
    'use_tls': True,
}


class TestSmtpNotifications:
    """Test SMTP notification sending logic"""

    @pytest.fixture
    def notification_service(self):
        """Create NotificationService instance with mocked dependencies"""
        mock_db = Mock()
        return NotificationService(db=mock_db, event_logger=None)

    @pytest.fixture
    def mock_aiosmtplib(self):
        """Mock aiosmtplib module so _send_smtp can import it locally."""
        mock_smtp_instance = AsyncMock()
        mock_smtp_class = MagicMock()
        mock_smtp_class.return_value.__aenter__ = AsyncMock(return_value=mock_smtp_instance)
        mock_smtp_class.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_module = MagicMock()
        mock_module.SMTP = mock_smtp_class
        mock_module.SMTPAuthenticationError = Exception
        mock_module.SMTPException = Exception

        with patch.dict(sys.modules, {'aiosmtplib': mock_module}):
            yield mock_smtp_instance

    @pytest.mark.asyncio
    async def test_authenticated_send_calls_login(self, notification_service, mock_aiosmtplib):
        """SMTP send with user and password calls smtp.login()."""
        result = await notification_service._send_smtp(
            VALID_SMTP_CONFIG, message='Test message'
        )

        assert result is True
        mock_aiosmtplib.login.assert_called_once_with('user@example.com', 'secret')
        mock_aiosmtplib.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_unauthenticated_send_skips_login(self, notification_service, mock_aiosmtplib):
        """SMTP send without credentials skips smtp.login()."""
        config = {
            **VALID_SMTP_CONFIG,
            'smtp_user': '',
            'smtp_password': '',
            'smtp_port': 25,
            'use_tls': False,
        }

        result = await notification_service._send_smtp(
            config, message='Test message'
        )

        assert result is True
        mock_aiosmtplib.login.assert_not_called()
        mock_aiosmtplib.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_user_without_password_rejected(self, notification_service):
        """SMTP config with user but no password is rejected."""
        config = {**VALID_SMTP_CONFIG, 'smtp_password': ''}

        result = await notification_service._send_smtp(
            config, message='Test message'
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_password_without_user_rejected(self, notification_service):
        """SMTP config with password but no user is rejected."""
        config = {**VALID_SMTP_CONFIG, 'smtp_user': ''}

        result = await notification_service._send_smtp(
            config, message='Test message'
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_missing_host_rejected(self, notification_service):
        """SMTP config without host is rejected."""
        config = {**VALID_SMTP_CONFIG, 'smtp_host': ''}

        result = await notification_service._send_smtp(
            config, message='Test message'
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_missing_from_email_rejected(self, notification_service):
        """SMTP config without from_email is rejected."""
        config = {**VALID_SMTP_CONFIG, 'from_email': ''}

        result = await notification_service._send_smtp(
            config, message='Test message'
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_missing_to_email_rejected(self, notification_service):
        """SMTP config without to_email is rejected."""
        config = {**VALID_SMTP_CONFIG, 'to_email': ''}

        result = await notification_service._send_smtp(
            config, message='Test message'
        )

        assert result is False
