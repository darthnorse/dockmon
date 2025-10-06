"""
DockMon v2 User Preferences API

REPLACES: localStorage on frontend (v1)
PROVIDES: Database-backed preferences synchronized across devices

SECURITY:
- Preferences tied to authenticated user (session cookie required)
- Input validation with Pydantic
- SQL injection protection via SQLAlchemy
"""

import json
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from auth.v2_routes import get_current_user
from database import DatabaseManager
from config.paths import DATABASE_PATH

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/user", tags=["user-v2"])

# Use the same database instance as v1
db = DatabaseManager(DATABASE_PATH)


class UserPreferences(BaseModel):
    """
    User preferences schema.

    Replaces localStorage from v1 frontend.
    """
    theme: str = Field(default="dark", pattern="^(dark|light)$")
    group_by: Optional[str] = Field(default="env", pattern="^(env|region|compose|none)?$")
    compact_view: bool = Field(default=False)
    collapsed_groups: list[str] = Field(default_factory=list)
    filter_defaults: Dict[str, Any] = Field(default_factory=dict)


class PreferencesUpdate(BaseModel):
    """Partial update to preferences"""
    theme: Optional[str] = Field(None, pattern="^(dark|light)$")
    group_by: Optional[str] = Field(None, pattern="^(env|region|compose|none)?$")
    compact_view: Optional[bool] = None
    collapsed_groups: Optional[list[str]] = None
    filter_defaults: Optional[Dict[str, Any]] = None


@router.get("/preferences", response_model=UserPreferences)
async def get_user_preferences(
    current_user: dict = Depends(get_current_user)
):
    """
    Get user preferences (replaces localStorage).

    SECURITY: Requires valid session cookie

    Returns:
        User preferences or defaults if none exist
    """
    user_id = current_user["user_id"]

    with db.get_session() as session:
        # Query user_prefs table
        from sqlalchemy import text
        result = session.execute(
            text("SELECT * FROM user_prefs WHERE user_id = :user_id"),
            {"user_id": user_id}
        ).fetchone()

        if not result:
            # Return defaults if no preferences saved
            logger.info(f"No preferences found for user {user_id}, returning defaults")
            return UserPreferences()

        # Parse stored preferences
        try:
            defaults_json = json.loads(result.defaults_json) if result.defaults_json else {}
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in user_prefs for user {user_id}")
            defaults_json = {}

        return UserPreferences(
            theme=result.theme or "dark",
            group_by=defaults_json.get("group_by", "env"),
            compact_view=defaults_json.get("compact_view", False),
            collapsed_groups=defaults_json.get("collapsed_groups", []),
            filter_defaults=defaults_json.get("filter_defaults", {})
        )


@router.patch("/preferences")
async def update_user_preferences(
    updates: PreferencesUpdate,
    current_user: dict = Depends(get_current_user)
):
    """
    Update user preferences (partial update supported).

    SECURITY:
    - Requires valid session cookie
    - Input validation via Pydantic
    - SQL injection protection via parameterized queries

    Args:
        updates: Partial preferences to update

    Returns:
        Success message
    """
    user_id = current_user["user_id"]

    with db.get_session() as session:
        from sqlalchemy import text

        # Get existing preferences
        result = session.execute(
            text("SELECT * FROM user_prefs WHERE user_id = :user_id"),
            {"user_id": user_id}
        ).fetchone()

        # Parse existing defaults_json
        if result and result.defaults_json:
            try:
                existing_defaults = json.loads(result.defaults_json)
            except json.JSONDecodeError:
                existing_defaults = {}
        else:
            existing_defaults = {}

        # Merge updates
        new_theme = updates.theme if updates.theme is not None else (result.theme if result else "dark")

        if updates.group_by is not None:
            existing_defaults["group_by"] = updates.group_by
        if updates.compact_view is not None:
            existing_defaults["compact_view"] = updates.compact_view
        if updates.collapsed_groups is not None:
            existing_defaults["collapsed_groups"] = updates.collapsed_groups
        if updates.filter_defaults is not None:
            existing_defaults["filter_defaults"] = updates.filter_defaults

        # Upsert preferences
        # SECURITY: ON CONFLICT ensures atomic operation
        session.execute(
            text("""
                INSERT INTO user_prefs (user_id, theme, defaults_json)
                VALUES (:user_id, :theme, :defaults_json)
                ON CONFLICT(user_id) DO UPDATE SET
                    theme = :theme,
                    defaults_json = :defaults_json
            """),
            {
                "user_id": user_id,
                "theme": new_theme,
                "defaults_json": json.dumps(existing_defaults)
            }
        )

        session.commit()

    logger.info(f"Preferences updated for user {user_id}")

    return {"status": "ok", "message": "Preferences updated successfully"}


@router.delete("/preferences")
async def reset_user_preferences(
    current_user: dict = Depends(get_current_user)
):
    """
    Reset user preferences to defaults.

    SECURITY: Requires valid session cookie

    Returns:
        Success message
    """
    user_id = current_user["user_id"]

    with db.get_session() as session:
        from sqlalchemy import text

        session.execute(
            text("DELETE FROM user_prefs WHERE user_id = :user_id"),
            {"user_id": user_id}
        )

        session.commit()

    logger.info(f"Preferences reset to defaults for user {user_id}")

    return {"status": "ok", "message": "Preferences reset to defaults"}
