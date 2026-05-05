"""Tests for resolve/recovery notifications (issue #189)."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import inspect

import database as database_module
from database import DatabaseManager
from models.settings_models import AlertRuleV2Create, AlertRuleV2Update
from notifications import NotificationService


@pytest.fixture
def db(tmp_path):
    """Temporary file-backed test database with full schema and migrations.

    Uses the singleton reset pattern from tests/integration/test_discovery_gating.py
    because DatabaseManager is a singleton and DatabaseManager.__init__ expects a
    plain file path (not a sqlite:// URL) and calls os.makedirs on the parent dir.
    """
    db_path = str(tmp_path / "test.db")
    # Reset singleton so DatabaseManager initialises a fresh instance with our path
    database_module._database_manager_instance = None
    db_manager = DatabaseManager(db_path=db_path)
    try:
        yield db_manager
    finally:
        if hasattr(db_manager, "engine"):
            db_manager.engine.dispose()
        database_module._database_manager_instance = None


def test_alert_rules_v2_has_notify_on_resolve_column(db):
    """Migration adds notify_on_resolve column to alert_rules_v2."""
    with db.get_session() as session:
        inspector = inspect(session.connection())
        cols = {c["name"]: c for c in inspector.get_columns("alert_rules_v2")}
        assert "notify_on_resolve" in cols
        col = cols["notify_on_resolve"]
        # Column must be NOT NULL
        assert col["nullable"] is False
        # Default is False / 0; SQLite reflection returns '0' for SQL DEFAULT 0
        # and None for a Python-side default (create_all path). Both are correct.
        assert col["default"] in (0, "0", False, "false", None)


def test_alerts_v2_has_resolve_notified_at_column(db):
    """Migration adds resolve_notified_at column to alerts_v2."""
    with db.get_session() as session:
        inspector = inspect(session.connection())
        cols = {c["name"] for c in inspector.get_columns("alerts_v2")}
        assert "resolve_notified_at" in cols


def test_alert_rule_v2_create_accepts_notify_on_resolve():
    """AlertRuleV2Create model accepts notify_on_resolve field."""
    rule = AlertRuleV2Create(
        name="test",
        scope="container",
        kind="container_stopped",
        severity="warning",
        notify_on_resolve=True,
    )
    assert rule.notify_on_resolve is True


def test_alert_rule_v2_create_defaults_notify_on_resolve_false():
    """notify_on_resolve defaults to False when not provided."""
    rule = AlertRuleV2Create(
        name="test",
        scope="container",
        kind="container_stopped",
        severity="warning",
    )
    assert rule.notify_on_resolve is False


def test_alert_rule_v2_update_accepts_notify_on_resolve():
    """AlertRuleV2Update model accepts notify_on_resolve field."""
    rule = AlertRuleV2Update(notify_on_resolve=True)
    assert rule.notify_on_resolve is True


def _make_resolved_alert():
    """Build an AlertV2-like mock representing a resolved alert."""
    alert = MagicMock()
    alert.id = "alert-123"
    alert.title = "Container Stopped: nginx"
    alert.message = "Container nginx on host-a stopped"
    alert.scope_type = "container"
    alert.scope_id = "host-uuid-abc:67c5d2141338"
    alert.kind = "container_stopped"
    alert.severity = "warning"
    alert.host_name = "host-a"
    alert.container_name = "nginx"
    alert.first_seen = datetime(2026, 5, 4, 10, 0, 0, tzinfo=timezone.utc)
    alert.last_seen = datetime(2026, 5, 4, 10, 5, 0, tzinfo=timezone.utc)
    alert.resolved_at = datetime(2026, 5, 4, 10, 5, 0, tzinfo=timezone.utc)
    alert.resolved_reason = "Clear condition met"
    alert.event_context_json = None
    alert.labels_json = None
    return alert


def _make_rule(notify_on_resolve=True, channels='[1]'):
    """Build an AlertRuleV2-like mock."""
    rule = MagicMock()
    rule.id = "rule-1"
    rule.name = "Container Stopped Alert"
    rule.kind = "container_stopped"
    rule.metric = None
    rule.notify_on_resolve = notify_on_resolve
    rule.notify_channels_json = channels
    rule.custom_template = None
    rule.auto_resolve = False
    return rule


def test_format_resolve_message_v2_renders_default_template():
    """Default resolve template substitutes core variables."""
    db = MagicMock()
    db.get_settings.return_value = MagicMock(timezone_offset=0)
    service = NotificationService(db)

    alert = _make_resolved_alert()
    rule = _make_rule()

    msg = service._format_resolve_message_v2(alert, rule)

    assert "Recovered" in msg
    assert "nginx" in msg
    assert "host-a" in msg
    assert "Clear condition met" in msg
    assert "Container Stopped Alert" in msg


@pytest.mark.asyncio
async def test_send_resolve_v2_sends_to_configured_channels():
    """send_resolve_v2 dispatches to channels listed in rule.notify_channels_json."""
    db = MagicMock()
    db.get_settings.return_value = MagicMock(timezone_offset=0)
    discord_channel = MagicMock(id=1, type="discord", config={"webhook_url": "x"}, enabled=True)
    db.get_notification_channels.return_value = [discord_channel]

    service = NotificationService(db)
    service.blackout_manager = MagicMock()
    service.blackout_manager.is_in_blackout_window.return_value = (False, None)
    service._send_discord = AsyncMock(return_value=True)
    service._is_rate_limited = MagicMock(return_value=False)

    alert = _make_resolved_alert()
    rule = _make_rule(channels='[1]')

    result = await service.send_resolve_v2(alert, rule)

    assert result is True
    service._send_discord.assert_called_once()


@pytest.mark.asyncio
async def test_send_resolve_v2_skips_when_no_channels():
    """send_resolve_v2 returns False when rule has no channels configured."""
    db = MagicMock()
    service = NotificationService(db)
    service.blackout_manager = MagicMock()

    alert = _make_resolved_alert()
    rule = _make_rule(channels=None)

    result = await service.send_resolve_v2(alert, rule)
    assert result is False


@pytest.mark.asyncio
async def test_send_resolve_v2_skips_during_blackout():
    """send_resolve_v2 returns False when in blackout window."""
    db = MagicMock()
    db.get_settings.return_value = MagicMock(timezone_offset=0)
    db.get_notification_channels.return_value = []
    service = NotificationService(db)
    service.blackout_manager = MagicMock()
    service.blackout_manager.is_in_blackout_window.return_value = (True, "Maintenance Window")

    alert = _make_resolved_alert()
    rule = _make_rule()

    result = await service.send_resolve_v2(alert, rule)
    assert result is False
