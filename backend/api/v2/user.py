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
from collections import deque
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from auth.api_key_auth import get_current_user_or_api_key as get_current_user, require_scope

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/user", tags=["user-v2"])

# Default time format (12h or 24h) - must match frontend DEFAULT_TIME_FORMAT
DEFAULT_TIME_FORMAT = "24h"


def validate_json_depth(obj: Any, max_depth: int = 10) -> None:
    """
    Validate JSON structure depth to prevent DOS attacks.

    SECURITY: Prevent deeply nested JSON from causing CPU exhaustion

    Args:
        obj: Object to validate
        max_depth: Maximum allowed nesting depth

    Raises:
        ValueError: If depth exceeds max_depth
    """
    queue = deque([(obj, 0)])
    while queue:
        current, depth = queue.popleft()
        if depth > max_depth:
            raise ValueError(f"JSON depth exceeds maximum allowed depth of {max_depth}")
        if isinstance(current, dict):
            for v in current.values():
                queue.append((v, depth + 1))
        elif isinstance(current, (list, tuple)):
            for item in current:
                queue.append((item, depth + 1))

# Import shared database instance (single connection pool)
from auth.shared import db


class DashboardPreferences(BaseModel):
    """Dashboard-specific preferences"""
    enableCustomLayout: bool = Field(default=True)
    hostOrder: list[str] = Field(default_factory=list)
    compactHostOrder: Optional[list[str]] = Field(default=None)  # Host order for compact view (non-grouped)
    containerSortKey: str = Field(default="state", pattern="^(name|state|cpu|memory|start_time)$")
    hostContainerSorts: Dict[str, str] = Field(default_factory=dict)  # Per-host container sort preferences
    hostCardLayout: Optional[list[Dict[str, Any]]] = Field(default=None)  # Expanded mode layout (ungrouped)
    hostCardLayoutStandard: Optional[list[Dict[str, Any]]] = Field(default=None)  # Standard mode layout (ungrouped)
    hostCardLayoutGroupedStandard: Optional[list[Dict[str, Any]]] = Field(default=None)  # Standard mode layout (grouped by tags)
    hostCardLayoutGroupedExpanded: Optional[list[Dict[str, Any]]] = Field(default=None)  # Expanded mode layout (grouped by tags)
    tagGroupOrder: Optional[list[str]] = Field(default=None)  # User-defined order of tag groups
    groupLayouts: Dict[str, Any] = Field(default_factory=dict)  # Dynamic group layouts/orders: supports both Layout[] and string[]
    showKpiBar: bool = Field(default=True)
    showStatsWidgets: bool = Field(default=False)
    showContainerStats: bool = Field(default=False)
    optimizedLoading: bool = Field(default=True)


class UserPreferences(BaseModel):
    """
    User preferences schema.

    Replaces localStorage from v1 frontend.
    """
    theme: str = Field(default="dark", pattern="^(dark|light)$")
    group_by: Optional[str] = Field(default="none", pattern="^(env|region|compose|tags|none)?$")
    compact_view: bool = Field(default=False)
    collapsed_groups: list[str] = Field(default_factory=list)

    # React v2 preferences
    sidebar_collapsed: bool = Field(default=False)
    dashboard_layout_v2: Optional[Dict[str, Any]] = Field(default=None)  # react-grid-layout format
    dashboard: DashboardPreferences = Field(default_factory=DashboardPreferences)
    simplified_workflow: bool = Field(default=True)  # Skip drawer, open modal directly

    # Display preferences
    time_format: str = Field(default=DEFAULT_TIME_FORMAT, pattern="^(12h|24h)$")  # 12-hour or 24-hour time format

    # Table sorting preferences (TanStack Table format: [{ id: 'column', desc: bool }])
    host_table_sort: Optional[list[Dict[str, Any]]] = Field(default=None)
    container_table_sort: Optional[list[Dict[str, Any]]] = Field(default=None)

    # Table column customization preferences
    container_table_column_visibility: Optional[Dict[str, bool]] = Field(default=None)  # { column_id: visible }
    container_table_column_order: Optional[list[str]] = Field(default=None)  # ['column_id1', 'column_id2', ...]


class PreferencesUpdate(BaseModel):
    """Partial update to preferences"""
    theme: Optional[str] = Field(None, pattern="^(dark|light)$")
    group_by: Optional[str] = Field(None, pattern="^(env|region|compose|tags|none)?$")
    compact_view: Optional[bool] = None
    collapsed_groups: Optional[list[str]] = None

    # React v2 preferences
    sidebar_collapsed: Optional[bool] = None
    dashboard_layout_v2: Optional[Dict[str, Any]] = None
    dashboard: Optional[DashboardPreferences] = None
    simplified_workflow: Optional[bool] = None

    # Display preferences
    time_format: Optional[str] = Field(None, pattern="^(12h|24h)$")

    # Table sorting preferences
    host_table_sort: Optional[list[Dict[str, Any]]] = None
    container_table_sort: Optional[list[Dict[str, Any]]] = None

    # Table column customization preferences
    container_table_column_visibility: Optional[Dict[str, bool]] = None
    container_table_column_order: Optional[list[str]] = None


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
        from sqlalchemy import text

        # Query user_prefs table and users table (for React v2 preferences)
        prefs_result = session.execute(
            text("SELECT * FROM user_prefs WHERE user_id = :user_id"),
            {"user_id": user_id}
        ).fetchone()

        user_result = session.execute(
            text("SELECT sidebar_collapsed, dashboard_layout_v2, prefs, view_mode, container_sort_order, simplified_workflow FROM users WHERE id = :user_id"),
            {"user_id": user_id}
        ).fetchone()

        if not prefs_result and not user_result:
            # Return defaults if no preferences saved
            logger.info(f"No preferences found for user {user_id}, returning defaults")
            return UserPreferences()

        # Parse stored preferences from user_prefs table
        defaults_json = {}
        if prefs_result and prefs_result.defaults_json:
            try:
                defaults_json = json.loads(prefs_result.defaults_json)
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON in user_prefs for user {user_id}")
                defaults_json = {}

        # Parse React v2 preferences from users table
        dashboard_layout_v2 = None
        if user_result and user_result.dashboard_layout_v2:
            try:
                dashboard_layout_v2 = json.loads(user_result.dashboard_layout_v2)
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON in dashboard_layout_v2 for user {user_id}")
                dashboard_layout_v2 = None

        # Parse prefs column (new JSONB-style preferences)
        prefs_data = {}
        if user_result and user_result.prefs:
            try:
                prefs_data = json.loads(user_result.prefs)
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON in prefs for user {user_id}")
                prefs_data = {}

        # Build dashboard preferences (with migration from old columns)
        dashboard_prefs = prefs_data.get("dashboard", {})

        # Migrate view_mode and container_sort_order if present in old columns
        if not dashboard_prefs and user_result:
            # Map old container_sort_order values to new containerSortKey
            old_sort_order = user_result.container_sort_order or "state"
            # Strip -asc/-desc suffix from old format (e.g., "name-asc" -> "name")
            if "-" in old_sort_order:
                old_sort_order = old_sort_order.split("-")[0]
            # Migrate old "status" to new "state"
            if old_sort_order == "status":
                old_sort_order = "state"

            dashboard_prefs = {
                "enableCustomLayout": True,
                "hostOrder": [],
                "containerSortKey": old_sort_order
            }

        # Get containerSortKey with migration for old "status" value
        container_sort_key = dashboard_prefs.get("containerSortKey", "state")
        # Strip -asc/-desc suffix if present
        if "-" in container_sort_key:
            container_sort_key = container_sort_key.split("-")[0]
        if container_sort_key == "status":
            container_sort_key = "state"

        # Helper to validate layout fields - must be list or None
        def validate_layout(value):
            return value if isinstance(value, list) else None

        dashboard = DashboardPreferences(
            enableCustomLayout=dashboard_prefs.get("enableCustomLayout", True),
            hostOrder=dashboard_prefs.get("hostOrder", []),
            compactHostOrder=dashboard_prefs.get("compactHostOrder"),
            containerSortKey=container_sort_key,
            hostContainerSorts=dashboard_prefs.get("hostContainerSorts", {}),
            hostCardLayout=validate_layout(dashboard_prefs.get("hostCardLayout")),
            hostCardLayoutStandard=validate_layout(dashboard_prefs.get("hostCardLayoutStandard")),
            hostCardLayoutGroupedStandard=validate_layout(dashboard_prefs.get("hostCardLayoutGroupedStandard")),
            hostCardLayoutGroupedExpanded=validate_layout(dashboard_prefs.get("hostCardLayoutGroupedExpanded")),
            tagGroupOrder=dashboard_prefs.get("tagGroupOrder"),
            groupLayouts=dashboard_prefs.get("groupLayouts", {}),
            showKpiBar=dashboard_prefs.get("showKpiBar", True),
            showStatsWidgets=dashboard_prefs.get("showStatsWidgets", False),
            showContainerStats=dashboard_prefs.get("showContainerStats", False),
            optimizedLoading=dashboard_prefs.get("optimizedLoading", True)
        )

        return UserPreferences(
            theme=prefs_result.theme if prefs_result else "dark",
            group_by=defaults_json.get("group_by", "none"),
            compact_view=defaults_json.get("compact_view", False),
            collapsed_groups=defaults_json.get("collapsed_groups", []),
            sidebar_collapsed=user_result.sidebar_collapsed if user_result else False,
            dashboard_layout_v2=dashboard_layout_v2,
            dashboard=dashboard,
            simplified_workflow=user_result.simplified_workflow if user_result and hasattr(user_result, 'simplified_workflow') else True,
            time_format=prefs_data.get("time_format", DEFAULT_TIME_FORMAT),
            host_table_sort=prefs_data.get("host_table_sort"),
            container_table_sort=prefs_data.get("container_table_sort"),
            container_table_column_visibility=prefs_data.get("container_table_column_visibility"),
            container_table_column_order=prefs_data.get("container_table_column_order")
        )


@router.patch("/preferences", dependencies=[Depends(require_scope("write"))])
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

        # SECURITY FIX: Validate JSON depth before serialization to prevent DOS
        try:
            validate_json_depth(existing_defaults, max_depth=10)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=str(e)
            )

        # Serialize and validate size
        defaults_json_str = json.dumps(existing_defaults)

        # DOS PROTECTION: Limit JSON size to 100KB
        MAX_JSON_SIZE = 100 * 1024  # 100KB
        if len(defaults_json_str) > MAX_JSON_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"Preferences too large ({len(defaults_json_str)} bytes, max {MAX_JSON_SIZE} bytes)"
            )

        # Upsert preferences in user_prefs table
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
                "defaults_json": defaults_json_str
            }
        )

        # Update React v2 preferences in users table
        update_parts = []
        update_params = {"user_id": user_id}

        if updates.sidebar_collapsed is not None:
            update_parts.append("sidebar_collapsed = :sidebar_collapsed")
            update_params["sidebar_collapsed"] = updates.sidebar_collapsed

        if updates.dashboard_layout_v2 is not None:
            # SECURITY FIX: Validate JSON depth before serialization
            try:
                validate_json_depth(updates.dashboard_layout_v2, max_depth=10)
            except ValueError as e:
                raise HTTPException(
                    status_code=400,
                    detail=str(e)
                )

            dashboard_json = json.dumps(updates.dashboard_layout_v2)
            # DOS PROTECTION: Limit JSON size to 500KB for layout
            MAX_LAYOUT_SIZE = 500 * 1024  # 500KB
            if len(dashboard_json) > MAX_LAYOUT_SIZE:
                raise HTTPException(
                    status_code=413,
                    detail=f"Dashboard layout too large ({len(dashboard_json)} bytes, max {MAX_LAYOUT_SIZE} bytes)"
                )
            update_parts.append("dashboard_layout_v2 = :dashboard_layout_v2")
            update_params["dashboard_layout_v2"] = dashboard_json

        if updates.simplified_workflow is not None:
            update_parts.append("simplified_workflow = :simplified_workflow")
            update_params["simplified_workflow"] = updates.simplified_workflow

        # Handle prefs column (new JSONB-style preferences)
        needs_prefs_update = (
            updates.dashboard is not None or
            updates.time_format is not None or
            updates.host_table_sort is not None or
            updates.container_table_sort is not None or
            updates.container_table_column_visibility is not None or
            updates.container_table_column_order is not None
        )

        if needs_prefs_update:
            # Get existing prefs
            user_result = session.execute(
                text("SELECT prefs FROM users WHERE id = :user_id"),
                {"user_id": user_id}
            ).fetchone()

            existing_prefs = {}
            if user_result and user_result.prefs:
                try:
                    existing_prefs = json.loads(user_result.prefs)
                except json.JSONDecodeError:
                    existing_prefs = {}

            # Merge dashboard preferences (don't overwrite, merge with existing)
            if updates.dashboard is not None:
                if "dashboard" not in existing_prefs:
                    existing_prefs["dashboard"] = {}
                existing_prefs["dashboard"].update(updates.dashboard.model_dump(exclude_unset=True))

            # Update display preferences
            if updates.time_format is not None:
                existing_prefs["time_format"] = updates.time_format

            # Update table sorting preferences
            if updates.host_table_sort is not None:
                existing_prefs["host_table_sort"] = updates.host_table_sort

            if updates.container_table_sort is not None:
                existing_prefs["container_table_sort"] = updates.container_table_sort

            # Update column customization preferences
            if updates.container_table_column_visibility is not None:
                existing_prefs["container_table_column_visibility"] = updates.container_table_column_visibility

            if updates.container_table_column_order is not None:
                existing_prefs["container_table_column_order"] = updates.container_table_column_order

            # SECURITY FIX: Validate JSON depth before serialization
            try:
                validate_json_depth(existing_prefs, max_depth=10)
            except ValueError as e:
                raise HTTPException(
                    status_code=400,
                    detail=str(e)
                )

            prefs_json = json.dumps(existing_prefs)
            # DOS PROTECTION: Limit JSON size to 100KB
            if len(prefs_json) > MAX_JSON_SIZE:
                raise HTTPException(
                    status_code=413,
                    detail=f"Preferences too large ({len(prefs_json)} bytes, max {MAX_JSON_SIZE} bytes)"
                )
            update_parts.append("prefs = :prefs")
            update_params["prefs"] = prefs_json

        # SECURITY FIX: Use SQLAlchemy update() instead of dynamic query construction
        # This prevents SQL injection even if field names are ever sourced from user input
        if update_parts:
            from sqlalchemy import update
            from database import User

            # Build safe update values from validated parameters
            update_values = {}
            for part in update_parts:
                # Extract field name from "field = :field" pattern
                field = part.split(" = ")[0]
                param_key = part.split(":")[1]
                update_values[field] = update_params[param_key]

            stmt = (
                update(User)
                .where(User.id == user_id)
                .values(**update_values)
            )
            session.execute(stmt)

        session.commit()

    # Note: Removed noisy log - preferences update frequently from frontend (column changes, etc.)
    # Only log errors/warnings for this endpoint

    return {"status": "ok", "message": "Preferences updated successfully"}


@router.delete("/preferences", dependencies=[Depends(require_scope("write"))])
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
