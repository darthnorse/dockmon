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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_add_annotation_stores_session_username(db_session, test_user, test_database_manager):
    """Session-auth: annotation row stores current_user['username'], not request.user."""
    alert_id = _make_alert(db_session)
    current_user = {
        "auth_type": "session",
        "user_id": test_user.id,
        "username": test_user.username,
        "display_name": test_user.display_name,
    }

    await add_annotation(
        alert_id=alert_id,
        request=AddAnnotationRequest(text="investigating"),
        db=test_database_manager,
        current_user=current_user,
    )

    row = db_session.query(AlertAnnotation).filter_by(alert_id=alert_id).one()
    assert row.user == test_user.username
    assert row.text == "investigating"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_annotations_resolves_display_name(db_session, test_user, test_database_manager):
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

    result = await get_annotations(alert_id=alert_id, db=test_database_manager)

    assert [a["user"] for a in result["annotations"]] == ["Patrik Runald", "Patrik Runald"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_annotations_falls_back_to_stored_string(db_session, test_database_manager):
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

    result = await get_annotations(alert_id=alert_id, db=test_database_manager)
    users = {a["text"]: a["user"] for a in result["annotations"]}
    assert users["orphan"] == "ghost_user"
    assert users["from a key"] == "API Key: Deploy Bot"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_annotations_no_user_row_query_n_plus_1(db_session, test_user, test_database_manager):
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
        await get_annotations(alert_id=alert_id, db=test_database_manager)
    finally:
        event.remove(db_session.get_bind(), "before_execute", _before_execute)

    assert user_table_queries <= 1, f"expected <=1 User query, got {user_table_queries}"


@pytest.fixture
def db_manager(tmp_path):
    """Real DatabaseManager backed by a temp SQLite file.

    Needed for tests that call instance methods like change_username, which
    open their own session via self.get_session().
    """
    import database as database_module
    from database import DatabaseManager

    db_path = str(tmp_path / "test_annotations.db")
    database_module._database_manager_instance = None
    db = DatabaseManager(db_path=db_path)
    try:
        yield db
    finally:
        if hasattr(db, "engine"):
            db.engine.dispose()
        database_module._database_manager_instance = None


@pytest.mark.integration
def test_change_username_cascades_to_annotations(db_manager):
    """Renaming a user updates the username stored on their annotations."""
    from database import User

    with db_manager.get_session() as session:
        user = User(
            username="rename_me",
            password_hash="$2b$12$test_hash_not_real",
            auth_provider="local",
            created_at=datetime.now(timezone.utc),
        )
        session.add(user)
        session.commit()

        alert_id = _make_alert(session)
        session.add(AlertAnnotation(
            alert_id=alert_id,
            timestamp=datetime.now(timezone.utc),
            user="rename_me",
            text="before rename",
        ))
        session.commit()

    assert db_manager.change_username("rename_me", "renamed_user") is True

    with db_manager.get_session() as session:
        row = session.query(AlertAnnotation).filter_by(alert_id=alert_id).one()
        assert row.user == "renamed_user"


@pytest.mark.integration
def test_api_key_caller_stored_as_api_key_marker(db_manager, monkeypatch):
    """API-key callers: annotation.user is 'API Key: <key name>' verbatim.

    Uses the TestClient + real api_key_auth path so the live dependency
    populates current_user. Wires the auth-shared DB and monitor.db to the
    same test DatabaseManager so the API key validates against the same
    rows the endpoint reads/writes.
    """
    import secrets
    import hashlib
    from fastapi.testclient import TestClient

    from database import User, ApiKey, CustomGroup, GroupPermission
    from auth.capabilities import ALL_CAPABILITIES

    # Seed: admin group + permissions + user + API key in the test DB.
    raw_key = f"dockmon_{secrets.token_hex(16)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_name = "Test Write Key"

    with db_manager.get_session() as session:
        group = session.query(CustomGroup).filter(
            CustomGroup.name == "Administrators"
        ).first()
        if not group:
            group = CustomGroup(name="Administrators", description="Full access", is_system=True)
            session.add(group)
            session.flush()
            for cap in ALL_CAPABILITIES:
                session.add(GroupPermission(group_id=group.id, capability=cap, allowed=True))
            session.flush()

        user = User(
            username="api_key_owner",
            password_hash="$2b$12$test_hash_not_real",
            auth_provider="local",
            created_at=datetime.now(timezone.utc),
        )
        session.add(user)
        session.flush()

        api_key = ApiKey(
            created_by_user_id=user.id,
            group_id=group.id,
            name=key_name,
            key_hash=key_hash,
            key_prefix=raw_key[:12],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(api_key)

        alert_id = _make_alert(session)
        session.commit()

    # Wire all DB references to the same test DatabaseManager.
    # api_key_auth binds `db` at import time via `from auth.shared import db`,
    # so we must patch the bound name on the api_key_auth module.
    import main
    import auth.api_key_auth as api_key_auth_mod
    import auth.shared as auth_shared
    monkeypatch.setattr(auth_shared, "db", db_manager)
    monkeypatch.setattr(api_key_auth_mod, "db", db_manager)
    monkeypatch.setattr(main.monitor, "db", db_manager)

    client = TestClient(main.app)

    response = client.post(
        f"/api/alerts/{alert_id}/annotations",
        json={"text": "deploy bot here"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200, response.text

    with db_manager.get_session() as session:
        row = session.query(AlertAnnotation).filter_by(alert_id=alert_id).one()
        assert row.user == f"API Key: {key_name}"

    # GET passes the marker through unchanged.
    get_resp = client.get(
        f"/api/alerts/{alert_id}/annotations",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["annotations"][0]["user"] == f"API Key: {key_name}"


@pytest.mark.integration
def test_profile_rename_cascades_to_annotations(db_manager, monkeypatch):
    """Renaming via POST /api/v2/auth/update-profile cascades to AlertAnnotation.user.

    Regression test for the bug where DatabaseManager.change_username had the
    cascade but the live rename path in auth/v2_routes.py mutated user.username
    directly, leaving historical annotations pointing at the stale username.
    """
    from fastapi.testclient import TestClient
    from database import User

    with db_manager.get_session() as session:
        user = User(
            username="rename_via_api",
            password_hash="$2b$12$test_hash_not_real",
            auth_provider="local",
            must_change_password=False,
            created_at=datetime.now(timezone.utc),
        )
        session.add(user)
        session.flush()
        user_id = user.id

        alert_id = _make_alert(session)
        session.add(AlertAnnotation(
            alert_id=alert_id,
            timestamp=datetime.now(timezone.utc),
            user="rename_via_api",
            text="before rename",
        ))
        session.commit()

    import main
    import auth.v2_routes as v2_routes_mod
    import auth.shared as auth_shared
    monkeypatch.setattr(auth_shared, "db", db_manager)
    monkeypatch.setattr(v2_routes_mod, "db", db_manager)

    async def _mock_current_user():
        return {
            "auth_type": "session",
            "user_id": user_id,
            "username": "rename_via_api",
            "display_name": None,
        }

    main.app.dependency_overrides[v2_routes_mod.get_current_user_dependency] = _mock_current_user
    try:
        client = TestClient(main.app)
        resp = client.post(
            "/api/v2/auth/update-profile",
            json={"username": "renamed_via_api"},
        )
        assert resp.status_code == 200, resp.text
    finally:
        main.app.dependency_overrides.pop(v2_routes_mod.get_current_user_dependency, None)

    with db_manager.get_session() as session:
        row = session.query(AlertAnnotation).filter_by(alert_id=alert_id).one()
        assert row.user == "renamed_via_api"


def test_username_validators_block_api_key_marker_collision():
    """Username regex must reject 'API Key: ...' so it cannot collide with
    the marker stored on AlertAnnotation rows for API-key authors.

    If either validator is relaxed in the future, this test fires before
    the namespace ambiguity reaches production.
    """
    from pydantic import ValidationError
    from auth.user_management_routes import CreateUserRequest
    from auth.v2_routes import UpdateProfileRequest

    with pytest.raises(ValidationError):
        CreateUserRequest(
            username="API Key: Deploy Bot",
            password="placeholder123",
            group_ids=[1],
        )

    with pytest.raises(ValidationError):
        UpdateProfileRequest(username="API Key: Deploy Bot")
