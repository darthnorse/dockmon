"""
Container update validation system.

Provides validation layer to protect critical containers from automatic updates.
Uses priority-based validation: labels → per-container → patterns → default allow.

Priority Order:
1. Docker label: com.dockmon.update.policy (allow/warn/block)
2. Per-container database setting (container_updates.update_policy)
3. Global pattern matching (update_policies table)
4. Default: ALLOW
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional
from sqlalchemy.orm import Session
from database import UpdatePolicy, ContainerUpdate
from utils.keys import make_composite_key
import logging

logger = logging.getLogger(__name__)


class ValidationResult(Enum):
    """Result of container update validation."""
    ALLOW = "allow"   # Update can proceed without warning
    WARN = "warn"     # Show warning but allow user to proceed
    BLOCK = "block"   # Prevent update entirely


@dataclass
class ValidationResponse:
    """Response from validation check."""
    result: ValidationResult
    reason: str                    # Human-readable explanation
    matched_pattern: Optional[str] = None  # Pattern that triggered the result


class ContainerValidator:
    """
    Validates whether a container should be updated.

    Checks multiple sources in priority order:
    1. Docker labels (com.dockmon.update.policy)
    2. Per-container database setting
    3. Global pattern matching
    4. Default to ALLOW
    """

    LABEL_KEY = "com.dockmon.update.policy"

    def __init__(self, session: Session):
        """
        Initialize validator.

        Args:
            session: SQLAlchemy database session
        """
        self.session = session

    def validate_update(
        self,
        host_id: str,
        container_id: str,
        container_name: str,
        image_name: str,
        labels: dict[str, str]
    ) -> ValidationResponse:
        """
        Validate if container should be updated.

        Args:
            host_id: Host UUID
            container_id: Container SHORT ID (12 chars)
            container_name: Container name (without leading /)
            image_name: Image name (e.g., "postgres:14" or "traefik:latest")
            labels: Container labels dict

        Returns:
            ValidationResponse with result and reason
        """

        # Priority 0: Block DockMon from updating itself (critical safety check)
        # Prevents the "pulling the rug out" scenario where DockMon stops itself
        # and cannot complete the update process
        # Protects: dockmon, dockmon-dev, dockmon-prod, dockmon-backup-*, etc.
        container_name_lower = container_name.lower()
        if container_name_lower == 'dockmon' or container_name_lower.startswith('dockmon-'):
            logger.warning(
                f"Blocked self-update attempt for DockMon container '{container_name}'. "
                f"DockMon cannot update itself - please update manually."
            )
            return ValidationResponse(
                result=ValidationResult.BLOCK,
                reason="DockMon cannot update itself. Please update manually by pulling the new image and restarting the container.",
                matched_pattern=None
            )

        # Priority 1: Check Docker label
        if self.LABEL_KEY in labels:
            label_value = labels[self.LABEL_KEY].lower()
            if label_value in ["allow", "warn", "block"]:
                result = ValidationResult(label_value)
                logger.info(
                    f"Container {container_name} validation: {result.value} "
                    f"(source: Docker label)"
                )
                return ValidationResponse(
                    result=result,
                    reason=f"Docker label '{self.LABEL_KEY}' set to '{label_value}'",
                    matched_pattern=None
                )

        # Priority 2: Check per-container database setting
        composite_key = make_composite_key(host_id, container_id)
        update_record = self.session.query(ContainerUpdate).filter_by(
            container_id=composite_key
        ).first()

        if update_record and update_record.update_policy:
            policy_value = update_record.update_policy.lower()
            if policy_value in ["allow", "warn", "block"]:
                result = ValidationResult(policy_value)
                logger.info(
                    f"Container {container_name} validation: {result.value} "
                    f"(source: per-container setting)"
                )
                return ValidationResponse(
                    result=result,
                    reason=f"Per-container policy set to '{policy_value}'",
                    matched_pattern=None
                )

        # Priority 3: Check global pattern matching
        # Get all enabled patterns
        patterns = self.session.query(UpdatePolicy).filter_by(
            enabled=True
        ).all()

        for pattern in patterns:
            # Check if pattern matches container name or image name
            pattern_lower = pattern.pattern.lower()
            container_name_lower = container_name.lower()
            image_name_lower = image_name.lower()

            if pattern_lower in container_name_lower or pattern_lower in image_name_lower:
                # Pattern matched - block or warn based on category
                # All patterns default to WARN (user can proceed with confirmation)
                result = ValidationResult.WARN
                logger.info(
                    f"Container {container_name} validation: {result.value} "
                    f"(matched pattern: {pattern.pattern} in category: {pattern.category})"
                )
                return ValidationResponse(
                    result=result,
                    reason=f"Matched {pattern.category} pattern: '{pattern.pattern}'",
                    matched_pattern=pattern.pattern
                )

        # Priority 4: Default to ALLOW
        logger.info(
            f"Container {container_name} validation: allow (no restrictions found)"
        )
        return ValidationResponse(
            result=ValidationResult.ALLOW,
            reason="No restrictions found - update allowed",
            matched_pattern=None
        )

    def get_validation_priority_order(
        self,
        host_id: str,
        container_id: str,
        labels: dict[str, str]
    ) -> list[str]:
        """
        Get the priority order of validation sources for a container.

        Useful for debugging and UI display.

        Args:
            host_id: Host UUID
            container_id: Container SHORT ID (12 chars)
            labels: Container labels dict

        Returns:
            List of validation sources in priority order
        """
        sources = []

        # Priority 1: Docker label
        if self.LABEL_KEY in labels:
            sources.append(f"Docker label: {self.LABEL_KEY}={labels[self.LABEL_KEY]}")

        # Priority 2: Per-container setting
        composite_key = make_composite_key(host_id, container_id)
        update_record = self.session.query(ContainerUpdate).filter_by(
            container_id=composite_key
        ).first()

        if update_record and update_record.update_policy:
            sources.append(f"Per-container setting: {update_record.update_policy}")

        # Priority 3: Global patterns
        patterns = self.session.query(UpdatePolicy).filter_by(
            enabled=True
        ).count()

        sources.append(f"Global patterns: {patterns} enabled")

        # Priority 4: Default
        sources.append("Default: ALLOW")

        return sources
