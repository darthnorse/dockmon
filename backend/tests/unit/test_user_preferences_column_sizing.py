"""Container-table column widths round-trip through the user preferences endpoints."""

import asyncio
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from api.v2 import user as user_routes
from api.v2.user import PreferencesUpdate, get_user_preferences, update_user_preferences
from database import User


@pytest.fixture
def current_user(db, monkeypatch):
    with db.get_session() as session:
        user = User(username="alice", password_hash="$2b$12$test_hash_not_real", created_at=datetime.now(timezone.utc))
        session.add(user)
        session.commit()
        user_id = user.id
    monkeypatch.setattr(user_routes, "db", db)
    return {"user_id": user_id, "username": "alice", "auth_type": "session"}


def _patch(current_user, **fields):
    asyncio.run(update_user_preferences(PreferencesUpdate(**fields), current_user=current_user))


def _get(current_user):
    return asyncio.run(get_user_preferences(current_user=current_user))


def test_column_sizing_round_trips(current_user):
    _patch(current_user, container_table_column_sizing={"name": 320, "image": 180})

    assert _get(current_user).container_table_column_sizing == {"name": 320, "image": 180}


def test_column_sizing_is_replaced_not_merged(current_user):
    _patch(current_user, container_table_column_sizing={"name": 320, "image": 180})
    _patch(current_user, container_table_column_sizing={"name": 400})

    assert _get(current_user).container_table_column_sizing == {"name": 400}


def test_empty_column_sizing_resets(current_user):
    _patch(current_user, container_table_column_sizing={"name": 320})
    _patch(current_user, container_table_column_sizing={})

    assert _get(current_user).container_table_column_sizing == {}


def test_column_sizing_defaults_to_none(current_user):
    _patch(current_user, container_table_column_order=["name"])

    assert _get(current_user).container_table_column_sizing is None


def test_column_sizing_leaves_other_table_prefs_alone(current_user):
    _patch(
        current_user,
        container_table_column_order=["name", "image"],
        container_table_column_visibility={"ip": False},
    )
    _patch(current_user, container_table_column_sizing={"name": 300})

    prefs = _get(current_user)
    assert prefs.container_table_column_order == ["name", "image"]
    assert prefs.container_table_column_visibility == {"ip": False}
    assert prefs.container_table_column_sizing == {"name": 300}


@pytest.mark.parametrize(
    "sizing",
    [
        {"name": 10},
        {"name": 5000},
        {"name": 247.5},
        {"name": "300"},
        {"": 300},
        {"x" * 129: 300},
        {f"col{i}": 100 for i in range(101)},
    ],
    ids=["too-narrow", "too-wide", "fractional", "string-width", "empty-key", "long-key", "too-many"],
)
def test_invalid_column_sizing_is_rejected(sizing):
    with pytest.raises(ValidationError):
        PreferencesUpdate(container_table_column_sizing=sizing)
