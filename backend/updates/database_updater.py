"""
Database updater for container updates.

Shared logic for updating all database records after a container is recreated
with a new ID. Used by both DockerUpdateExecutor and AgentUpdateExecutor.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from database import (
    DatabaseManager,
    ContainerUpdate,
    AutoRestartConfig,
    ContainerDesiredState,
    ContainerHttpHealthCheck,
    DeploymentMetadata,
    TagAssignment,
)
from alerts.engine import resolve_update_available_alerts
from utils.keys import make_composite_key

logger = logging.getLogger(__name__)


def update_container_records_after_update(
    db: DatabaseManager,
    host_id: str,
    old_container_id: str,
    new_container_id: str,
    new_image: str,
    new_digest: str = None,
    invalidate_cache: bool = True,
    old_image: str = None,
) -> bool:
    """
    Update all database records after a container is recreated with a new ID.

    This function updates composite keys across all container-related tables
    to point to the new container ID. It handles:
    - ContainerUpdate (with race condition handling)
    - AutoRestartConfig
    - ContainerDesiredState
    - ContainerHttpHealthCheck
    - DeploymentMetadata
    - TagAssignment (with reattachment handling)
    - open update_available alerts on the old key (resolved)

    Args:
        db: DatabaseManager instance
        host_id: Host UUID
        old_container_id: Old container short ID (12 chars)
        new_container_id: New container short ID (12 chars)
        new_image: New image name after update
        new_digest: New image digest after update (optional)
        invalidate_cache: Whether to invalidate image cache (default True)
        old_image: Old image name for cache invalidation (optional)

    Returns:
        True if successful, False otherwise
    """
    old_composite_key = make_composite_key(host_id, old_container_id)
    new_composite_key = make_composite_key(host_id, new_container_id)

    logger.info(f"Updating database records: {old_composite_key} -> {new_composite_key}")

    try:
        with db.get_session() as session:
            now = datetime.now(timezone.utc)

            # Update ContainerUpdate
            record = session.query(ContainerUpdate).filter_by(
                container_id=old_composite_key
            ).first()

            if record:
                # Handle race condition: update checker may have created new record
                conflicting = session.query(ContainerUpdate).filter_by(
                    container_id=new_composite_key
                ).first()
                if conflicting:
                    session.delete(conflicting)
                    session.flush()

                record.container_id = new_composite_key
                record.update_available = False
                record.check_status = None
                record.current_image = new_image
                record.current_digest = new_digest
                record.last_updated_at = now
                record.updated_at = now

            # Update AutoRestartConfig
            session.query(AutoRestartConfig).filter_by(
                host_id=host_id, container_id=old_container_id
            ).update({
                "container_id": new_container_id,
                "updated_at": now
            })

            # Update ContainerDesiredState
            session.query(ContainerDesiredState).filter_by(
                host_id=host_id, container_id=old_container_id
            ).update({
                "container_id": new_container_id,
                "updated_at": now
            })

            # Update ContainerHttpHealthCheck
            session.query(ContainerHttpHealthCheck).filter_by(
                container_id=old_composite_key
            ).update({
                "container_id": new_composite_key
            })

            # Update DeploymentMetadata
            session.query(DeploymentMetadata).filter_by(
                container_id=old_composite_key
            ).update({
                "container_id": new_composite_key,
                "updated_at": now
            })

            resolved = resolve_update_available_alerts(session, old_composite_key, "Container updated")
            if resolved:
                logger.info(f"Resolved {resolved} update_available alert(s) for {old_composite_key}")

            # A savepoint, so a concurrent reattachment rolls back only the tag move.
            try:
                with session.begin_nested():
                    _move_tag_assignments(session, old_composite_key, new_composite_key, now)
            except IntegrityError as e:
                if "tag_assignments" not in str(e).lower():
                    raise
                logger.debug("Tag migration race detected; reattachment already moved the tags")
                with session.begin_nested():
                    _move_tag_assignments(session, old_composite_key, new_composite_key, now)

            session.commit()
            logger.debug(f"Database updated: {old_composite_key} -> {new_composite_key}")

        # Invalidate image digest cache
        if invalidate_cache and old_image:
            try:
                invalidated = db.invalidate_image_cache(old_image)
                if invalidated:
                    logger.debug(f"Invalidated {invalidated} cache entries for {old_image}")
            except Exception as e:
                logger.warning(f"Failed to invalidate image cache: {e}")

        return True

    except Exception as e:
        logger.error(f"Error updating database records: {e}", exc_info=True)
        return False


def _move_tag_assignments(session, old_composite_key: str, new_composite_key: str, now: datetime) -> None:
    query = session.query(TagAssignment).filter(
        TagAssignment.subject_type == 'container',
        TagAssignment.subject_id == old_composite_key,
    )
    new_tag_count = session.query(TagAssignment).filter(
        TagAssignment.subject_type == 'container',
        TagAssignment.subject_id == new_composite_key,
    ).count()
    if new_tag_count > 0:
        # Reattachment already migrated the tags.
        query.delete()
    else:
        query.update({"subject_id": new_composite_key, "last_seen_at": now})
