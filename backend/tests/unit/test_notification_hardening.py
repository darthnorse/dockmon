"""
Regression tests for notification-channel hardening:
- Update model sanitizes/rejects XSS in the channel name.
- Create-time config validation (reused on the update path) rejects dangerous values.
- Secret redaction helper strips tokens before logging.
"""

import pytest
from pydantic import ValidationError

from models.request_models import NotificationChannelUpdate, NotificationChannelCreate
from notifications import _redact


class TestNotificationChannelUpdateValidation:
    def test_rejects_xss_in_name(self):
        with pytest.raises(ValidationError):
            NotificationChannelUpdate(name='<script>alert(1)</script>')

    def test_allows_plain_name(self):
        m = NotificationChannelUpdate(name='My Channel')
        assert m.name == 'My Channel'

    def test_config_only_update_is_valid_model(self):
        # config is validated in the endpoint (needs the channel type), so the
        # model itself accepts a bare config dict.
        m = NotificationChannelUpdate(config={'url': 'https://example.com'})
        assert m.config == {'url': 'https://example.com'}


class TestReusedConfigValidation:
    def test_rejects_dangerous_config_value(self):
        with pytest.raises(ValidationError):
            NotificationChannelCreate(
                name='n', type='webhook',
                config={'url': 'https://x', 'note': 'javascript:alert(1)'},
            )

    def test_rejects_oversized_config_value(self):
        with pytest.raises(ValidationError):
            NotificationChannelCreate(
                name='n', type='webhook',
                config={'url': 'https://x', 'note': 'a' * 1001},
            )


class TestRedact:
    def test_redacts_secret(self):
        assert _redact('bot123:ABC/sendMessage', '123:ABC') == 'bot***/sendMessage'

    def test_no_secret_is_noop(self):
        assert _redact('nothing here', '') == 'nothing here'
