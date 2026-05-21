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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_annotations_resolves_display_name(db_session, test_user):
    """GET resolves stored username -> User.effective_display_name."""
    alert_id = _make_alert(db_session)

    # Two annotations by the same user
    db_session.add_all([
        AlertAnnotation(
            alert_id=alert_id,
            timestamp=datetime.now(timezone.utc),
            user=test_user.username,
            text="first",
        ),
        AlertAnnotation(
            alert_id=alert_id,
            timestamp=datetime.now(timezone.utc),
            user=test_user.username,
            text="second",
        ),
    ])
    db_session.commit()

    # Set a display name distinct from the username so resolution is observable.
    test_user.display_name = "Patrik Runald"
    db_session.commit()

    result = await get_annotations(alert_id=alert_id, db=_FakeDb(db_session))

    assert [a["user"] for a in result["annotations"]] == ["Patrik Runald", "Patrik Runald"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_annotations_falls_back_to_stored_string(db_session):
    """GET returns the stored string verbatim when no User row matches.

    Covers three cases: deleted user, renamed user (stored username stale),
    and API-key markers like 'API Key: Foo'.
    """
    alert_id = _make_alert(db_session)
    db_session.add_all([
        AlertAnnotation(
            alert_id=alert_id,
            timestamp=datetime.now(timezone.utc),
            user="ghost_user",       # no such User row
            text="orphan",
        ),
        AlertAnnotation(
            alert_id=alert_id,
            timestamp=datetime.now(timezone.utc),
            user="API Key: Deploy Bot",
            text="from a key",
        ),
    ])
    db_session.commit()

    result = await get_annotations(alert_id=alert_id, db=_FakeDb(db_session))
    users = {a["text"]: a["user"] for a in result["annotations"]}
    assert users["orphan"] == "ghost_user"
    assert users["from a key"] == "API Key: Deploy Bot"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_annotations_no_user_row_query_n_plus_1(db_session, test_user):
    """N+1 guard: many annotations by the same user should issue a single User query.

    Implementation detail check via SQLAlchemy event hook — keeps the read
    path cheap as alerts accrue annotations.
    """
    from sqlalchemy import event

    alert_id = _make_alert(db_session)
    test_user.display_name = "Patrik"
    db_session.commit()

    for i in range(10):
        db_session.add(AlertAnnotation(
            alert_id=alert_id,
            timestamp=datetime.now(timezone.utc),
            user=test_user.username,
            text=f"note {i}",
        ))
    db_session.commit()

    user_table_queries = 0

    def _before_execute(conn, clauseelement, multiparams, params, execution_options):
        nonlocal user_table_queries
        sql = str(clauseelement).lower()
        if "from users" in sql:
            user_table_queries += 1

    event.listen(db_session.get_bind(), "before_execute", _before_execute)
    try:
        await get_annotations(alert_id=alert_id, db=_FakeDb(db_session))
    finally:
        event.remove(db_session.get_bind(), "before_execute", _before_execute)

    assert user_table_queries <= 1, f"expected <=1 User query, got {user_table_queries}"
