"""
Integration tests for alert annotation author attribution (issue #213).

Annotations must be auto-attributed to the authenticated caller. The stored
value is the stable `username` for session users (or a literal
"API Key: <name>" marker for API key callers). The GET endpoint resolves
`username -> effective_display_name` at read time so display-name changes
propagate to historical annotations.
"""

import pytest
import uuid
from datetime import datetime, timezone

from database import AlertV2, AlertAnnotation, User
from alerts.api import add_annotation, get_annotations, AddAnnotationRequest


def _make_alert(db_session, alert_id: str | None = None) -> str:
    """Create an open alert and return its id."""
    alert_id = alert_id or str(uuid.uuid4())
    alert = AlertV2(
        id=alert_id,
        dedup_key=f"cpu_high|host:{alert_id}",
        scope_type="host",
        scope_id="test-host",
        kind="cpu_high",
        severity="warning",
        state="open",
        title="Test alert",
        message="Test alert body",
        first_seen=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
    )
    db_session.add(alert)
    db_session.commit()
    return alert_id


class _FakeDb:
    """Minimal DatabaseManager stand-in: returns the test session."""
    def __init__(self, session):
        self._session = session

    def get_session(self):
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            yield self._session
        return _cm()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_add_annotation_stores_session_username(db_session, test_user):
    """Session-auth: annotation row stores current_user['username'], not request.user."""
    alert_id = _make_alert(db_session)
    db = _FakeDb(db_session)
    current_user = {
        "auth_type": "session",
        "user_id": test_user.id,
        "username": test_user.username,
        "display_name": test_user.display_name,
    }

    await add_annotation(
        alert_id=alert_id,
        request=AddAnnotationRequest(text="investigating"),
        db=db,
        current_user=current_user,
    )

    row = db_session.query(AlertAnnotation).filter_by(alert_id=alert_id).one()
    assert row.user == test_user.username
    assert row.text == "investigating"
