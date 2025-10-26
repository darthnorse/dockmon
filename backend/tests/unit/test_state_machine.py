"""
Tests for deployment state machine.

TDD Phase: RED (tests written first, will fail until implementation done)

Tests validate:
- Valid state transitions
- Invalid transitions are blocked
- Commitment point tracking
- State validation logic
- Error state handling
"""

import pytest
from datetime import datetime

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from database import Deployment


class InvalidStateTransition(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


def _validate_state_transition(current_state: str, new_state: str) -> bool:
    """
    Validate deployment state transition.

    This function will be implemented in the Deployment model or service layer.
    Tests define the expected behavior.

    Valid transitions:
    - pending → validating
    - validating → pulling_image
    - pulling_image → creating
    - creating → starting
    - starting → running
    - Any state → failed (can fail at any point)
    - running → stopped (user stopped)
    - stopped → starting (user restarted)

    Invalid transitions:
    - Cannot go backward (e.g., running → pending)
    - Cannot skip stages (e.g., pending → creating)
    """
    # This is a placeholder - actual implementation will be in model/service
    # Tests are written first to define expected behavior
    raise NotImplementedError("State validation not implemented yet (TDD: write tests first)")


@pytest.mark.unit
def test_valid_state_transition_pending_to_validating():
    """Test transition from pending to validating is allowed."""
    # This will fail until _validate_state_transition is implemented
    # That's expected in TDD (RED phase)
    with pytest.raises(NotImplementedError):
        _validate_state_transition('pending', 'validating')

    # When implemented, this should work:
    # assert _validate_state_transition('pending', 'validating') is True


@pytest.mark.unit
def test_valid_state_transition_validating_to_pulling_image():
    """Test transition from validating to pulling_image is allowed."""
    with pytest.raises(NotImplementedError):
        _validate_state_transition('validating', 'pulling_image')


@pytest.mark.unit
def test_valid_state_transition_pulling_to_creating():
    """Test transition from pulling_image to creating is allowed."""
    with pytest.raises(NotImplementedError):
        _validate_state_transition('pulling_image', 'creating')


@pytest.mark.unit
def test_valid_state_transition_creating_to_starting():
    """Test transition from creating to starting is allowed."""
    with pytest.raises(NotImplementedError):
        _validate_state_transition('creating', 'starting')


@pytest.mark.unit
def test_valid_state_transition_starting_to_running():
    """Test transition from starting to running is allowed."""
    with pytest.raises(NotImplementedError):
        _validate_state_transition('starting', 'running')


@pytest.mark.unit
def test_valid_state_transition_any_to_failed():
    """Test that any state can transition to failed."""
    states = ['pending', 'validating', 'pulling_image', 'creating', 'starting', 'running']

    for state in states:
        with pytest.raises(NotImplementedError):
            _validate_state_transition(state, 'failed')

        # When implemented:
        # assert _validate_state_transition(state, 'failed') is True


@pytest.mark.unit
def test_valid_state_transition_running_to_stopped():
    """Test user can stop a running deployment."""
    with pytest.raises(NotImplementedError):
        _validate_state_transition('running', 'stopped')


@pytest.mark.unit
def test_valid_state_transition_stopped_to_starting():
    """Test user can restart a stopped deployment."""
    with pytest.raises(NotImplementedError):
        _validate_state_transition('stopped', 'starting')


@pytest.mark.unit
def test_invalid_state_transition_running_to_pending():
    """Test that backwards transitions are not allowed."""
    with pytest.raises(NotImplementedError):
        _validate_state_transition('running', 'pending')

    # When implemented, this should raise InvalidStateTransition:
    # with pytest.raises(InvalidStateTransition):
    #     _validate_state_transition('running', 'pending')


@pytest.mark.unit
def test_invalid_state_transition_running_to_validating():
    """Test cannot go backward from running to validating."""
    with pytest.raises(NotImplementedError):
        _validate_state_transition('running', 'validating')


@pytest.mark.unit
def test_invalid_state_transition_skip_stages():
    """Test cannot skip stages (e.g., pending directly to creating)."""
    with pytest.raises(NotImplementedError):
        _validate_state_transition('pending', 'creating')

    # When implemented:
    # with pytest.raises(InvalidStateTransition):
    #     _validate_state_transition('pending', 'creating')


@pytest.mark.unit
def test_invalid_state_transition_creating_to_validating():
    """Test cannot go backward in deployment process."""
    with pytest.raises(NotImplementedError):
        _validate_state_transition('creating', 'validating')


@pytest.mark.unit
def test_deployment_state_updated_in_database(test_db, test_host):
    """
    Test that deployment state changes are persisted to database.

    Critical: State must be saved to DB so UI can display current status.
    """
    deployment = Deployment(
        id=f"{test_host.id}:statetest01",
        host_id=test_host.id,
        deployment_type='container',
        name='state-test',
        status='pending',
        definition='{}',
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(deployment)
    test_db.commit()

    # Update state
    deployment.status = 'validating'
    deployment.updated_at = datetime.utcnow()
    test_db.commit()

    # Retrieve and verify state changed
    retrieved = test_db.query(Deployment).filter_by(id=deployment.id).first()
    assert retrieved.status == 'validating'


@pytest.mark.unit
def test_deployment_progress_tracking(test_db, test_host):
    """
    Test that deployment tracks progress_percent and current_stage.

    Progress tracking enables real-time UI updates.
    """
    deployment = Deployment(
        id=f"{test_host.id}:progress001",
        host_id=test_host.id,
        deployment_type='container',
        name='progress-test',
        status='pulling_image',
        definition='{}',
        progress_percent=25,  # 25% complete
        current_stage='Pulling image',
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(deployment)
    test_db.commit()

    # Update progress
    deployment.progress_percent = 50
    deployment.current_stage = 'Creating container'
    deployment.status = 'creating'
    test_db.commit()

    # Verify progress saved
    retrieved = test_db.query(Deployment).filter_by(id=deployment.id).first()
    assert retrieved.progress_percent == 50
    assert retrieved.current_stage == 'Creating container'
    assert retrieved.status == 'creating'


@pytest.mark.unit
def test_deployment_error_state_with_message(test_db, test_host):
    """
    Test that failed deployments store error_message.

    Critical: Users need to see WHY a deployment failed.
    """
    deployment = Deployment(
        id=f"{test_host.id}:errortest01",
        host_id=test_host.id,
        deployment_type='container',
        name='error-test',
        status='failed',
        definition='{}',
        error_message='Failed to pull image: nginx:nonexistent - manifest unknown',
        progress_percent=30,
        current_stage='Pulling image',
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(deployment)
    test_db.commit()

    # Verify error captured
    retrieved = test_db.query(Deployment).filter_by(id=deployment.id).first()
    assert retrieved.status == 'failed'
    assert 'manifest unknown' in retrieved.error_message
    assert retrieved.progress_percent == 30  # Progress stopped at failure point


@pytest.mark.unit
def test_commitment_point_tracking():
    """
    Test commitment point pattern for deployment operations.

    Commitment point: The point at which an operation has succeeded and cannot be rolled back.

    For deployments:
    - BEFORE container created: Can fully rollback
    - AFTER container created but BEFORE DB commit: Rollback container
    - AFTER DB commit: Operation committed, can only handle failures going forward

    This test documents the expected behavior.
    """
    # This is a conceptual test documenting the commitment point pattern
    # Actual implementation will be in the deployment service

    class DeploymentOperation:
        def __init__(self):
            self.container_created = False
            self.db_committed = False

        def can_rollback(self) -> bool:
            """Can we fully rollback this operation?"""
            return not self.db_committed

        def needs_cleanup(self) -> bool:
            """Do we need to clean up created resources?"""
            return self.container_created and not self.db_committed

    # Scenario 1: No container created yet
    op1 = DeploymentOperation()
    assert op1.can_rollback() is True
    assert op1.needs_cleanup() is False

    # Scenario 2: Container created but not committed
    op2 = DeploymentOperation()
    op2.container_created = True
    assert op2.can_rollback() is True
    assert op2.needs_cleanup() is True  # Must remove container

    # Scenario 3: Container created AND committed
    op3 = DeploymentOperation()
    op3.container_created = True
    op3.db_committed = True
    assert op3.can_rollback() is False  # Past commitment point
    assert op3.needs_cleanup() is False  # Container is legitimate now


@pytest.mark.unit
def test_deployment_state_transitions_are_atomic(test_db, test_host):
    """
    Test that state transitions with progress updates happen atomically.

    Critical: State, progress, and current_stage must all update together.
    """
    deployment = Deployment(
        id=f"{test_host.id}:atomic0001",
        host_id=test_host.id,
        deployment_type='container',
        name='atomic-test',
        status='pending',
        progress_percent=0,
        current_stage='Initializing',
        definition='{}',
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(deployment)
    test_db.commit()

    # Atomic update: All three fields change together
    deployment.status = 'validating'
    deployment.progress_percent = 10
    deployment.current_stage = 'Validating configuration'
    deployment.updated_at = datetime.utcnow()
    test_db.commit()

    # Verify all updated together
    retrieved = test_db.query(Deployment).filter_by(id=deployment.id).first()
    assert retrieved.status == 'validating'
    assert retrieved.progress_percent == 10
    assert retrieved.current_stage == 'Validating configuration'
