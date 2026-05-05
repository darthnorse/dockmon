"""Tests for resolve/recovery notifications (issue #189)."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import inspect

import database as database_module
from alerts.engine import AlertEngine
from alerts.evaluation_service import AlertEvaluationService
from database import AlertRuleV2, AlertV2, DatabaseManager
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


def test_engine_resolve_alert_appends_to_queue_when_notify_true(db):
    """_resolve_alert(notify=True) records alert id in resolve queue."""
    engine = AlertEngine(db)

    with db.get_session() as session:
        rule = AlertRuleV2(
            id="r1", name="Test", scope="container", kind="container_stopped",
            severity="warning", enabled=True, notify_on_resolve=True,
        )
        session.add(rule)
        alert = AlertV2(
            id="a1", dedup_key="container_stopped|container:host-a:c1",
            scope_type="container", scope_id="host-a:c1", kind="container_stopped",
            severity="warning", state="open", title="X", message="Y",
            first_seen=datetime.now(timezone.utc), last_seen=datetime.now(timezone.utc),
            occurrences=1, rule_id="r1",
        )
        session.add(alert)
        session.commit()
        session.refresh(alert)

    engine._resolve_alert(alert, "test reason", notify=True)

    drained = engine.drain_recently_resolved()
    assert "a1" in drained
    assert engine.drain_recently_resolved() == []  # second drain is empty


def test_engine_resolve_alert_silent_when_notify_false(db):
    """_resolve_alert(notify=False) does NOT record alert id."""
    engine = AlertEngine(db)

    with db.get_session() as session:
        rule = AlertRuleV2(
            id="r2", name="Test", scope="container", kind="container_stopped",
            severity="warning", enabled=True, notify_on_resolve=True,
        )
        session.add(rule)
        alert = AlertV2(
            id="a2", dedup_key="k", scope_type="container", scope_id="h:c",
            kind="container_stopped", severity="warning", state="open",
            title="X", message="Y",
            first_seen=datetime.now(timezone.utc), last_seen=datetime.now(timezone.utc),
            occurrences=1, rule_id="r2",
        )
        session.add(alert)
        session.commit()
        session.refresh(alert)

    engine._resolve_alert(alert, "manual", notify=False)
    assert engine.drain_recently_resolved() == []


@pytest.mark.asyncio
async def test_dispatcher_skips_when_notify_on_resolve_false(db):
    """Dispatcher does NOT call send_resolve_v2 if rule.notify_on_resolve=False."""
    with db.get_session() as session:
        rule = AlertRuleV2(
            id="r1", name="Test", scope="container", kind="container_stopped",
            severity="warning", enabled=True, notify_on_resolve=False,
        )
        session.add(rule)
        alert = AlertV2(
            id="a1", dedup_key="k", scope_type="container", scope_id="h:c",
            kind="container_stopped", severity="warning", state="resolved",
            title="X", message="Y",
            first_seen=datetime.now(timezone.utc), last_seen=datetime.now(timezone.utc),
            resolved_at=datetime.now(timezone.utc),
            occurrences=1, rule_id="r1",
            notified_at=datetime.now(timezone.utc),
            resolve_notified_at=None,
        )
        session.add(alert)
        session.commit()

    notification_service = MagicMock()
    notification_service.send_resolve_v2 = AsyncMock(return_value=True)

    service = AlertEvaluationService(db=db, notification_service=notification_service)
    await service._send_resolve_notification("a1")

    notification_service.send_resolve_v2.assert_not_called()


@pytest.mark.asyncio
async def test_dispatcher_skips_when_alert_was_never_notified(db):
    """Dispatcher does NOT fire if alert.notified_at is None."""
    with db.get_session() as session:
        rule = AlertRuleV2(
            id="r2", name="Test", scope="container", kind="container_stopped",
            severity="warning", enabled=True, notify_on_resolve=True,
        )
        session.add(rule)
        alert = AlertV2(
            id="a2", dedup_key="k2", scope_type="container", scope_id="h:c",
            kind="container_stopped", severity="warning", state="resolved",
            title="X", message="Y",
            first_seen=datetime.now(timezone.utc), last_seen=datetime.now(timezone.utc),
            resolved_at=datetime.now(timezone.utc),
            occurrences=1, rule_id="r2",
            notified_at=None,
        )
        session.add(alert)
        session.commit()

    notification_service = MagicMock()
    notification_service.send_resolve_v2 = AsyncMock(return_value=True)

    service = AlertEvaluationService(db=db, notification_service=notification_service)
    await service._send_resolve_notification("a2")

    notification_service.send_resolve_v2.assert_not_called()


@pytest.mark.asyncio
async def test_dispatcher_skips_when_auto_resolve_true(db):
    """Dispatcher skips for notification-only rules (auto_resolve=True)."""
    with db.get_session() as session:
        rule = AlertRuleV2(
            id="r3", name="Test", scope="container", kind="update_completed",
            severity="info", enabled=True, notify_on_resolve=True,
            auto_resolve=True,
        )
        session.add(rule)
        alert = AlertV2(
            id="a3", dedup_key="k3", scope_type="container", scope_id="h:c",
            kind="update_completed", severity="info", state="resolved",
            title="X", message="Y",
            first_seen=datetime.now(timezone.utc), last_seen=datetime.now(timezone.utc),
            resolved_at=datetime.now(timezone.utc),
            occurrences=1, rule_id="r3",
            notified_at=datetime.now(timezone.utc),
        )
        session.add(alert)
        session.commit()

    notification_service = MagicMock()
    notification_service.send_resolve_v2 = AsyncMock(return_value=True)

    service = AlertEvaluationService(db=db, notification_service=notification_service)
    await service._send_resolve_notification("a3")

    notification_service.send_resolve_v2.assert_not_called()


@pytest.mark.asyncio
async def test_dispatcher_skips_when_already_resolve_notified(db):
    """Idempotency: dispatcher skips if resolve_notified_at is already set."""
    with db.get_session() as session:
        rule = AlertRuleV2(
            id="r4", name="Test", scope="container", kind="container_stopped",
            severity="warning", enabled=True, notify_on_resolve=True,
        )
        session.add(rule)
        alert = AlertV2(
            id="a4", dedup_key="k4", scope_type="container", scope_id="h:c",
            kind="container_stopped", severity="warning", state="resolved",
            title="X", message="Y",
            first_seen=datetime.now(timezone.utc), last_seen=datetime.now(timezone.utc),
            resolved_at=datetime.now(timezone.utc),
            occurrences=1, rule_id="r4",
            notified_at=datetime.now(timezone.utc),
            resolve_notified_at=datetime.now(timezone.utc),
        )
        session.add(alert)
        session.commit()

    notification_service = MagicMock()
    notification_service.send_resolve_v2 = AsyncMock(return_value=True)

    service = AlertEvaluationService(db=db, notification_service=notification_service)
    await service._send_resolve_notification("a4")

    notification_service.send_resolve_v2.assert_not_called()


@pytest.mark.asyncio
async def test_dispatcher_fires_and_sets_resolve_notified_at(db):
    """Happy path: all skip rules pass -> notification sent + resolve_notified_at set."""
    with db.get_session() as session:
        rule = AlertRuleV2(
            id="r5", name="Test", scope="container", kind="container_stopped",
            severity="warning", enabled=True, notify_on_resolve=True,
        )
        session.add(rule)
        alert = AlertV2(
            id="a5", dedup_key="k5", scope_type="container", scope_id="h:c",
            kind="container_stopped", severity="warning", state="resolved",
            title="X", message="Y",
            first_seen=datetime.now(timezone.utc), last_seen=datetime.now(timezone.utc),
            resolved_at=datetime.now(timezone.utc),
            occurrences=1, rule_id="r5",
            notified_at=datetime.now(timezone.utc),
            resolve_notified_at=None,
        )
        session.add(alert)
        session.commit()

    notification_service = MagicMock()
    notification_service.send_resolve_v2 = AsyncMock(return_value=True)

    service = AlertEvaluationService(db=db, notification_service=notification_service)
    await service._send_resolve_notification("a5")

    notification_service.send_resolve_v2.assert_called_once()
    sent_alert, sent_rule = notification_service.send_resolve_v2.call_args.args
    assert sent_alert.id == "a5"
    assert sent_rule.id == "r5"

    with db.get_session() as session:
        refreshed = session.query(AlertV2).filter(AlertV2.id == "a5").first()
        assert refreshed.resolve_notified_at is not None
