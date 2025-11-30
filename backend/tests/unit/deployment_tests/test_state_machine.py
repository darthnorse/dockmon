"""
Unit tests for deployment state machine.

Tests verify:
- Valid state transitions
- Invalid state transitions blocked
- Commitment point tracking
- Rollback safety logic
- Progress tracking
- State validation
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock

from deployment.state_machine import DeploymentStateMachine


# =============================================================================
# State Transition Validation Tests
# =============================================================================

class TestStateTransitionValidation:
    """Test state transition validation logic"""

    def test_valid_linear_flow(self):
        """Test valid linear state progression"""
        sm = DeploymentStateMachine()

        # planning -> validating -> pulling_image -> creating -> starting -> running
        assert sm.can_transition('planning', 'validating') is True
        assert sm.can_transition('validating', 'pulling_image') is True
        assert sm.can_transition('pulling_image', 'creating') is True
        assert sm.can_transition('creating', 'starting') is True
        assert sm.can_transition('starting', 'running') is True


    def test_valid_failure_transitions(self):
        """Test valid transitions to failed state"""
        sm = DeploymentStateMachine()

        # Any active state can transition to failed
        assert sm.can_transition('validating', 'failed') is True
        assert sm.can_transition('pulling_image', 'failed') is True
        assert sm.can_transition('creating', 'failed') is True
        assert sm.can_transition('starting', 'failed') is True


    def test_valid_rollback_transition(self):
        """Test valid transition from failed to rolled_back"""
        sm = DeploymentStateMachine()

        assert sm.can_transition('failed', 'rolled_back') is True


    def test_cannot_skip_states(self):
        """Test that you cannot skip intermediate states"""
        sm = DeploymentStateMachine()

        # Cannot skip from planning directly to creating
        assert sm.can_transition('planning', 'creating') is False
        assert sm.can_transition('planning', 'starting') is False
        assert sm.can_transition('planning', 'running') is False

        # Cannot skip from validating to starting
        assert sm.can_transition('validating', 'starting') is False


    def test_terminal_states_cannot_transition(self):
        """Test that terminal states (running, rolled_back) cannot transition"""
        sm = DeploymentStateMachine()

        # running is terminal (success)
        assert sm.can_transition('running', 'failed') is False
        assert sm.can_transition('running', 'creating') is False

        # rolled_back is terminal (cleanup complete)
        assert sm.can_transition('rolled_back', 'planning') is False
        assert sm.can_transition('rolled_back', 'failed') is False


    def test_cannot_transition_from_failed_except_rollback(self):
        """Test that failed state can only transition to rolled_back"""
        sm = DeploymentStateMachine()

        assert sm.can_transition('failed', 'rolled_back') is True
        assert sm.can_transition('failed', 'planning') is False
        assert sm.can_transition('failed', 'creating') is False
        assert sm.can_transition('failed', 'running') is False


    def test_invalid_state_names(self):
        """Test transition validation with invalid state names"""
        sm = DeploymentStateMachine()

        # Invalid from_state
        assert sm.can_transition('invalid_state', 'validating') is False

        # Invalid to_state
        assert sm.can_transition('planning', 'invalid_state') is False

        # Both invalid
        assert sm.can_transition('bad_state', 'wrong_state') is False


# =============================================================================
# State Transition Execution Tests
# =============================================================================

class TestStateTransitionExecution:
    """Test actual state transition execution"""

    def test_transition_updates_status(self):
        """Test that transition() updates deployment.status"""
        sm = DeploymentStateMachine()
        deployment = Mock()
        deployment.status = 'planning'

        result = sm.transition(deployment, 'validating')

        assert result is True
        assert deployment.status == 'validating'


    def test_transition_sets_started_at(self):
        """Test that transitioning to validating sets started_at"""
        sm = DeploymentStateMachine()
        deployment = Mock()
        deployment.status = 'planning'
        deployment.started_at = None

        sm.transition(deployment, 'validating')

        assert deployment.started_at is not None


    def test_transition_sets_completed_at_on_success(self):
        """Test that transitioning to running sets completed_at"""
        sm = DeploymentStateMachine()
        deployment = Mock()
        deployment.status = 'starting'
        deployment.completed_at = None

        sm.transition(deployment, 'running')

        assert deployment.completed_at is not None


    def test_transition_sets_completed_at_on_rollback(self):
        """Test that transitioning to rolled_back sets completed_at"""
        sm = DeploymentStateMachine()
        deployment = Mock()
        deployment.status = 'failed'
        deployment.completed_at = None

        sm.transition(deployment, 'rolled_back')

        assert deployment.completed_at is not None


    def test_invalid_transition_returns_false(self):
        """Test that invalid transitions return False"""
        sm = DeploymentStateMachine()
        deployment = Mock()
        deployment.status = 'planning'

        result = sm.transition(deployment, 'running')  # Cannot skip

        assert result is False
        assert deployment.status == 'planning'  # Status unchanged


    def test_transition_preserves_other_fields(self):
        """Test that transition() only updates expected fields"""
        sm = DeploymentStateMachine()
        deployment = Mock()
        deployment.status = 'planning'
        deployment.name = "test-deployment"
        deployment.error_message = None

        sm.transition(deployment, 'validating')

        # These should be preserved
        assert deployment.name == "test-deployment"
        assert deployment.error_message is None


# =============================================================================
# Commitment Point Tests
# =============================================================================

class TestCommitmentPoint:
    """Test commitment point tracking for rollback safety"""

    def test_mark_committed_sets_flag(self):
        """Test that mark_committed() sets committed flag"""
        sm = DeploymentStateMachine()
        deployment = Mock()
        deployment.committed = False

        sm.mark_committed(deployment)

        assert deployment.committed is True


    def test_should_rollback_returns_true_when_not_committed(self):
        """Test rollback allowed when not committed"""
        sm = DeploymentStateMachine()
        deployment = Mock()
        deployment.committed = False
        deployment.rollback_on_failure = True
        deployment.status = 'failed'  # Must be in rollback-eligible state

        assert sm.should_rollback(deployment) is True


    def test_should_rollback_returns_false_when_committed(self):
        """
        Test rollback blocked when committed.

        Critical safety check: Don't rollback if operation already committed.
        """
        sm = DeploymentStateMachine()
        deployment = Mock()
        deployment.committed = True
        deployment.rollback_on_failure = True

        assert sm.should_rollback(deployment) is False


    def test_should_rollback_respects_rollback_on_failure_flag(self):
        """Test that rollback_on_failure flag is respected"""
        sm = DeploymentStateMachine()
        deployment = Mock()
        deployment.committed = False
        deployment.rollback_on_failure = False  # User disabled rollback
        deployment.status = 'failed'

        assert sm.should_rollback(deployment) is False


    def test_should_rollback_requires_all_conditions(self):
        """Test that all conditions must be met for rollback"""
        sm = DeploymentStateMachine()

        # Case 1: Not committed, rollback enabled, eligible state → ROLLBACK
        deployment1 = Mock()
        deployment1.committed = False
        deployment1.rollback_on_failure = True
        deployment1.status = 'failed'
        assert sm.should_rollback(deployment1) is True

        # Case 2: Committed, rollback enabled → NO ROLLBACK
        deployment2 = Mock()
        deployment2.committed = True
        deployment2.rollback_on_failure = True
        deployment2.status = 'failed'
        assert sm.should_rollback(deployment2) is False

        # Case 3: Not committed, rollback disabled → NO ROLLBACK
        deployment3 = Mock()
        deployment3.committed = False
        deployment3.rollback_on_failure = False
        deployment3.status = 'failed'
        assert sm.should_rollback(deployment3) is False

        # Case 4: Not committed, rollback enabled, but ineligible state → NO ROLLBACK
        deployment4 = Mock()
        deployment4.committed = False
        deployment4.rollback_on_failure = True
        deployment4.status = 'planning'  # Not eligible for rollback
        assert sm.should_rollback(deployment4) is False


    def test_should_rollback_only_from_eligible_states(self):
        """Test that rollback only occurs from specific states"""
        sm = DeploymentStateMachine()

        # Eligible states: validating, pulling_image, creating, starting, failed
        eligible_states = ['validating', 'pulling_image', 'creating', 'starting', 'failed']
        for state in eligible_states:
            deployment = Mock()
            deployment.status = state
            deployment.committed = False
            deployment.rollback_on_failure = True
            assert sm.should_rollback(deployment) is True, f"Should rollback from {state}"

        # Ineligible states: planning, running, rolled_back
        ineligible_states = ['planning', 'running', 'rolled_back']
        for state in ineligible_states:
            deployment = Mock()
            deployment.status = state
            deployment.committed = False
            deployment.rollback_on_failure = True
            assert sm.should_rollback(deployment) is False, f"Should NOT rollback from {state}"


# =============================================================================
# State Validation Tests
# =============================================================================

class TestStateValidation:
    """Test state validation helpers"""

    def test_validate_state_recognizes_valid_states(self):
        """Test validate_state() returns True for valid states"""
        sm = DeploymentStateMachine()

        valid_states = [
            'planning', 'validating', 'pulling_image', 'creating',
            'starting', 'running', 'failed', 'rolled_back'
        ]

        for state in valid_states:
            assert sm.validate_state(state) is True, f"{state} should be valid"


    def test_validate_state_rejects_invalid_states(self):
        """Test validate_state() returns False for invalid states"""
        sm = DeploymentStateMachine()

        invalid_states = [
            'invalid', 'pending', 'executing', 'completed', 'unknown'
        ]

        for state in invalid_states:
            assert sm.validate_state(state) is False, f"{state} should be invalid"


    def test_get_valid_next_states(self):
        """Test get_valid_next_states() returns correct transitions"""
        sm = DeploymentStateMachine()

        # planning -> validating
        assert sm.get_valid_next_states('planning') == ['validating']

        # validating -> pulling_image | failed
        next_states = sm.get_valid_next_states('validating')
        assert set(next_states) == {'pulling_image', 'failed'}

        # Terminal states have no next states
        assert sm.get_valid_next_states('running') == []
        assert sm.get_valid_next_states('rolled_back') == []


# =============================================================================
# State Flow Integration Tests
# =============================================================================

class TestCompleteStateFlow:
    """Test complete state flow scenarios"""

    def test_successful_deployment_flow(self):
        """Test complete successful deployment state flow"""
        sm = DeploymentStateMachine()
        deployment = Mock()
        deployment.status = 'planning'
        deployment.started_at = None
        deployment.completed_at = None
        deployment.committed = False

        # planning -> validating
        assert sm.transition(deployment, 'validating') is True
        assert deployment.status == 'validating'
        assert deployment.started_at is not None

        # validating -> pulling_image
        assert sm.transition(deployment, 'pulling_image') is True
        assert deployment.status == 'pulling_image'

        # pulling_image -> creating
        assert sm.transition(deployment, 'creating') is True
        assert deployment.status == 'creating'

        # Mark committed after container created
        sm.mark_committed(deployment)
        assert deployment.committed is True

        # creating -> starting
        assert sm.transition(deployment, 'starting') is True
        assert deployment.status == 'starting'

        # starting -> running
        assert sm.transition(deployment, 'running') is True
        assert deployment.status == 'running'
        assert deployment.completed_at is not None


    def test_failed_deployment_with_rollback(self):
        """Test deployment failure and rollback flow"""
        sm = DeploymentStateMachine()
        deployment = Mock()
        deployment.status = 'pulling_image'
        deployment.committed = False
        deployment.rollback_on_failure = True
        deployment.completed_at = None

        # Failure during image pull
        assert sm.transition(deployment, 'failed') is True
        assert deployment.status == 'failed'

        # Rollback allowed (not committed)
        assert sm.should_rollback(deployment) is True

        # Perform rollback
        assert sm.transition(deployment, 'rolled_back') is True
        assert deployment.status == 'rolled_back'
        assert deployment.completed_at is not None


    def test_failed_deployment_after_commit_no_rollback(self):
        """Test that committed deployments don't rollback"""
        sm = DeploymentStateMachine()
        deployment = Mock()
        deployment.status = 'creating'
        deployment.committed = False
        deployment.rollback_on_failure = True

        # Container created → mark committed
        sm.mark_committed(deployment)

        # Failure during starting (after commitment)
        sm.transition(deployment, 'failed')

        # Rollback NOT allowed (committed)
        assert sm.should_rollback(deployment) is False
