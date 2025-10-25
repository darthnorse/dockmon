"""
Deployment state machine for DockMon v2.1

Manages deployment state transitions and commitment point tracking to ensure
safe rollback operations that don't destroy committed database state.

State Flow:
    planning -> executing -> completed
                         |-> failed -> rolled_back
                         |-> rolled_back

Commitment Point Pattern:
    When a deployment commits to the database (e.g., container created in Docker),
    the `committed` flag is set to True. This prevents rollback operations from
    destroying successfully committed state, even if post-commit operations fail.

Usage:
    sm = DeploymentStateMachine()

    # Check if transition is valid
    if sm.can_transition(deployment.status, 'executing'):
        sm.transition(deployment, 'executing')

    # Mark commitment point
    container = docker_client.containers.create(...)
    sm.mark_committed(deployment)

    # Check if rollback should occur on failure
    if error and sm.should_rollback(deployment):
        sm.transition(deployment, 'rolled_back')
"""

from datetime import datetime, timezone
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class DeploymentStateMachine:
    """
    State machine for deployment lifecycle management.

    Enforces valid state transitions and tracks commitment points
    to prevent incorrect rollback operations.
    """

    # Valid state transitions (from_state -> to_state)
    VALID_TRANSITIONS = {
        'planning': ['executing'],
        'executing': ['completed', 'failed', 'rolled_back'],
        'failed': ['rolled_back'],
        'completed': [],  # Terminal state
        'rolled_back': [],  # Terminal state
    }

    # Valid deployment states
    VALID_STATES = {'planning', 'executing', 'completed', 'failed', 'rolled_back'}

    def can_transition(self, from_state: str, to_state: str) -> bool:
        """
        Check if a state transition is valid.

        Args:
            from_state: Current deployment state
            to_state: Desired target state

        Returns:
            True if transition is allowed, False otherwise

        Examples:
            >>> sm = DeploymentStateMachine()
            >>> sm.can_transition('planning', 'executing')
            True
            >>> sm.can_transition('planning', 'completed')
            False
            >>> sm.can_transition('completed', 'failed')
            False  # Terminal state
        """
        if from_state not in self.VALID_STATES:
            logger.warning(f"Invalid from_state: {from_state}")
            return False

        if to_state not in self.VALID_STATES:
            logger.warning(f"Invalid to_state: {to_state}")
            return False

        return to_state in self.VALID_TRANSITIONS.get(from_state, [])

    def transition(self, deployment, to_state: str) -> bool:
        """
        Transition deployment to a new state with validation.

        Updates deployment status and timestamps based on target state.
        Validates transition is allowed before making changes.

        Args:
            deployment: Deployment model instance
            to_state: Target state to transition to

        Returns:
            True if transition succeeded, False if invalid

        Side Effects:
            - Updates deployment.status
            - Sets started_at when transitioning to 'executing'
            - Sets completed_at when transitioning to terminal states
            - Logs state transitions

        Examples:
            >>> sm = DeploymentStateMachine()
            >>> deployment.status = 'planning'
            >>> sm.transition(deployment, 'executing')
            True
            >>> deployment.status
            'executing'
            >>> deployment.started_at
            datetime(...)
        """
        from_state = deployment.status

        # Validate transition
        if not self.can_transition(from_state, to_state):
            logger.error(
                f"Invalid state transition for deployment {deployment.id}: "
                f"{from_state} -> {to_state}"
            )
            return False

        # Update deployment state
        deployment.status = to_state

        # Update timestamps based on state
        utcnow = datetime.now(timezone.utc)

        if to_state == 'executing' and not deployment.started_at:
            deployment.started_at = utcnow

        if to_state in {'completed', 'failed', 'rolled_back'} and not deployment.completed_at:
            deployment.completed_at = utcnow

        logger.info(
            f"Deployment {deployment.id} transitioned: {from_state} -> {to_state}"
        )

        return True

    def mark_committed(self, deployment) -> None:
        """
        Mark a deployment as committed to the database.

        Sets the commitment point flag to indicate that the deployment has
        successfully written state to the database (e.g., container created).
        After this point, rollback operations should NOT destroy the committed
        state, even if post-commit operations fail.

        Args:
            deployment: Deployment model instance

        Side Effects:
            - Sets deployment.committed = True
            - Logs commitment point

        Examples:
            >>> sm = DeploymentStateMachine()
            >>> deployment.committed
            False
            >>> container = docker_client.containers.create(...)
            >>> sm.mark_committed(deployment)
            >>> deployment.committed
            True

        Critical for Rollback Safety:
            If an exception occurs AFTER marking committed, do NOT rollback:

            ```python
            committed = False
            try:
                container = docker_client.containers.create(...)
                sm.mark_committed(deployment)
                committed = True
                # ... post-commit operations ...
            except Exception as e:
                if committed:
                    # Don't rollback - operation succeeded!
                    logger.error(f"Post-commit failure: {e}")
                else:
                    # Safe to rollback
                    rollback_operation()
            ```
        """
        deployment.committed = True
        logger.info(f"Deployment {deployment.id} marked as committed")

    def should_rollback(self, deployment) -> bool:
        """
        Determine if a failed deployment should be rolled back.

        Checks:
            1. Deployment has rollback_on_failure enabled
            2. Deployment is NOT in a committed state (safe to rollback)
            3. Deployment is in a rollback-eligible state (executing, failed)

        Args:
            deployment: Deployment model instance

        Returns:
            True if rollback should occur, False otherwise

        Examples:
            >>> sm = DeploymentStateMachine()
            >>> deployment.status = 'executing'
            >>> deployment.committed = False
            >>> deployment.rollback_on_failure = True
            >>> sm.should_rollback(deployment)
            True

            >>> deployment.committed = True
            >>> sm.should_rollback(deployment)
            False  # Already committed, don't destroy state!

        Commitment Point Logic:
            - committed=False: Safe to rollback, operation didn't complete
            - committed=True: Unsafe to rollback, would destroy committed state
        """
        # Check if rollback is disabled
        if not deployment.rollback_on_failure:
            logger.debug(f"Deployment {deployment.id}: rollback disabled")
            return False

        # Never rollback if operation was committed
        if deployment.committed:
            logger.warning(
                f"Deployment {deployment.id}: rollback requested but operation "
                f"was committed. Refusing to destroy committed state."
            )
            return False

        # Only rollback from certain states
        rollback_eligible_states = {'executing', 'failed'}
        if deployment.status not in rollback_eligible_states:
            logger.debug(
                f"Deployment {deployment.id}: status '{deployment.status}' "
                f"not eligible for rollback"
            )
            return False

        logger.info(f"Deployment {deployment.id}: rollback approved")
        return True

    def validate_state(self, state: str) -> bool:
        """
        Validate that a state is a recognized deployment state.

        Args:
            state: State string to validate

        Returns:
            True if state is valid, False otherwise

        Examples:
            >>> sm = DeploymentStateMachine()
            >>> sm.validate_state('executing')
            True
            >>> sm.validate_state('invalid_state')
            False
        """
        return state in self.VALID_STATES

    def get_valid_next_states(self, current_state: str) -> list:
        """
        Get list of valid states that can be transitioned to from current state.

        Args:
            current_state: Current deployment state

        Returns:
            List of valid target states, empty list if current state is terminal

        Examples:
            >>> sm = DeploymentStateMachine()
            >>> sm.get_valid_next_states('planning')
            ['executing']
            >>> sm.get_valid_next_states('executing')
            ['completed', 'failed', 'rolled_back']
            >>> sm.get_valid_next_states('completed')
            []  # Terminal state
        """
        return self.VALID_TRANSITIONS.get(current_state, [])
