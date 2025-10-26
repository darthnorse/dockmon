"""
TDD tests for DeploymentExecutor using 7-state machine (Phase 3.3)

These tests ensure the executor transitions through all granular states:
- pending → validating → pulling_image → creating → starting → running
- Failure paths: any intermediate state → failed → rolled_back

RED Phase: These tests will initially FAIL because executor still uses old 3-state flow
GREEN Phase: After refactoring executor, all tests should PASS

NOTE: This is a simpler integration test approach that tests actual state transitions.
"""

import pytest
import importlib


def test_state_machine_supports_granular_states():
    """State machine supports all 7 granular states from spec"""
    state_machine_module = importlib.import_module('deployment.state_machine')
    DeploymentStateMachine = state_machine_module.DeploymentStateMachine
    sm = DeploymentStateMachine()

    required_states = {
        'pending', 'validating', 'pulling_image',
        'creating', 'starting', 'running',
        'failed', 'rolled_back'
    }

    # Verify all required states are valid
    for state in required_states:
        assert state in sm.VALID_STATES, f"State '{state}' not in VALID_STATES"


def test_state_machine_allows_pending_to_validating():
    """State machine allows transition from pending to validating"""
    sm = DeploymentStateMachine()

    # Mock deployment object
    class MockDeployment:
        status = 'pending'
        committed = False

    deployment = MockDeployment()

    # Transition should succeed
    result = sm.transition(deployment, 'validating')
    assert result is True, "Should allow pending → validating"
    assert deployment.status == 'validating', f"Expected status 'validating', got '{deployment.status}'"


def test_state_machine_allows_validating_to_pulling_image():
    """State machine allows transition from validating to pulling_image"""
    sm = DeploymentStateMachine()

    class MockDeployment:
        status = 'validating'
        committed = False
        started_at = None

    deployment = MockDeployment()

    result = sm.transition(deployment, 'pulling_image')
    assert result is True, "Should allow validating → pulling_image"
    assert deployment.status == 'pulling_image'


def test_state_machine_allows_pulling_image_to_creating():
    """State machine allows transition from pulling_image to creating"""
    sm = DeploymentStateMachine()

    class MockDeployment:
        status = 'pulling_image'
        committed = False

    deployment = MockDeployment()

    result = sm.transition(deployment, 'creating')
    assert result is True, "Should allow pulling_image → creating"
    assert deployment.status == 'creating'


def test_state_machine_allows_creating_to_starting():
    """State machine allows transition from creating to starting"""
    sm = DeploymentStateMachine()

    class MockDeployment:
        status = 'creating'
        committed = False

    deployment = MockDeployment()

    result = sm.transition(deployment, 'starting')
    assert result is True, "Should allow creating → starting"
    assert deployment.status == 'starting'


def test_state_machine_allows_starting_to_running():
    """State machine allows transition from starting to running"""
    sm = DeploymentStateMachine()

    class MockDeployment:
        status = 'starting'
        committed = False
        completed_at = None

    deployment = MockDeployment()

    result = sm.transition(deployment, 'running')
    assert result is True, "Should allow starting → running"
    assert deployment.status == 'running'


def test_state_machine_rejects_pending_to_creating():
    """State machine rejects invalid transition (skipping states)"""
    sm = DeploymentStateMachine()

    class MockDeployment:
        status = 'pending'
        committed = False

    deployment = MockDeployment()

    # Should reject transition that skips states
    result = sm.transition(deployment, 'creating')
    assert result is False, "Should reject pending → creating (skips validating and pulling_image)"


def test_state_machine_rejects_obsolete_executing_state():
    """State machine rejects obsolete 'executing' state"""
    sm = DeploymentStateMachine()

    # 'executing' should not be in valid states
    assert 'executing' not in sm.VALID_STATES, "Obsolete 'executing' state still in VALID_STATES"


def test_state_machine_allows_intermediate_to_failed():
    """State machine allows transitions from intermediate states to failed"""
    sm = DeploymentStateMachine()

    # Test from validating
    class MockDeployment1:
        status = 'validating'
        committed = False
        completed_at = None

    d1 = MockDeployment1()
    assert sm.transition(d1, 'failed') is True, "Should allow validating → failed"

    # Test from pulling_image
    class MockDeployment2:
        status = 'pulling_image'
        committed = False
        completed_at = None

    d2 = MockDeployment2()
    assert sm.transition(d2, 'failed') is True, "Should allow pulling_image → failed"

    # Test from creating
    class MockDeployment3:
        status = 'creating'
        committed = False
        completed_at = None

    d3 = MockDeployment3()
    assert sm.transition(d3, 'failed') is True, "Should allow creating → failed"

    # Test from starting
    class MockDeployment4:
        status = 'starting'
        committed = False
        completed_at = None

    d4 = MockDeployment4()
    assert sm.transition(d4, 'failed') is True, "Should allow starting → failed"


def test_state_machine_allows_failed_to_rolled_back():
    """State machine allows transition from failed to rolled_back"""
    sm = DeploymentStateMachine()

    class MockDeployment:
        status = 'failed'
        committed = False
        completed_at = None

    deployment = MockDeployment()

    result = sm.transition(deployment, 'rolled_back')
    assert result is True, "Should allow failed → rolled_back"
    assert deployment.status == 'rolled_back'


def test_state_machine_running_is_terminal():
    """State machine treats 'running' as terminal state"""
    sm = DeploymentStateMachine()

    assert sm.is_terminal('running') is True, "'running' should be a terminal state"


def test_state_machine_failed_is_terminal():
    """State machine treats 'failed' as terminal state"""
    sm = DeploymentStateMachine()

    assert sm.is_terminal('failed') is True, "'failed' should be a terminal state"


def test_state_machine_rolled_back_is_terminal():
    """State machine treats 'rolled_back' as terminal state"""
    sm = DeploymentStateMachine()

    assert sm.is_terminal('rolled_back') is True, "'rolled_back' should be a terminal state"


def test_state_machine_completed_is_not_valid():
    """Old 'completed' state is no longer valid"""
    sm = DeploymentStateMachine()

    # 'completed' was used in old 3-state flow, should be removed
    assert 'completed' not in sm.VALID_STATES, "Obsolete 'completed' state still in VALID_STATES (use 'running' instead)"


def test_state_machine_planning_is_not_valid():
    """Old 'planning' state is no longer valid"""
    sm = DeploymentStateMachine()

    # 'planning' was used in old 3-state flow, should be removed
    assert 'planning' not in sm.VALID_STATES, "Obsolete 'planning' state still in VALID_STATES (use 'pending' instead)"


# ============================================================================
# EXECUTOR INTEGRATION TESTS
# ============================================================================
# These tests will check that executor.py uses granular states
# They will FAIL in RED phase because executor still uses 'executing' state
# ============================================================================

def test_executor_file_does_not_reference_executing_state():
    """executor.py should not reference obsolete 'executing' state in code"""
    import os

    executor_path = os.path.join(os.path.dirname(__file__), '../../deployment/executor.py')

    with open(executor_path, 'r') as f:
        content = f.read()

    # Check for string 'executing' in state transitions
    # Exclude comments and docstrings (basic check)
    lines = content.split('\n')
    code_lines = [
        line for line in lines
        if line.strip() and
        not line.strip().startswith('#') and
        not line.strip().startswith('"""') and
        not line.strip().startswith("'''")
    ]

    for i, line in enumerate(code_lines):
        # Skip docstring blocks
        if '"""' in line or "'''" in line:
            continue

        # Check if 'executing' appears as a state
        if "'executing'" in line or '"executing"' in line:
            # Filter out false positives (like variable names containing "executing")
            if 'transition' in line or 'status' in line or 'state' in line:
                pytest.fail(
                    f"Found obsolete 'executing' state reference in executor.py at line {i+1}: {line.strip()}\n"
                    f"Should use granular states: validating, pulling_image, creating, starting, running"
                )


def test_executor_docstring_references_granular_states():
    """executor.py docstrings should document 7-state flow, not 3-state"""
    import os

    executor_path = os.path.join(os.path.dirname(__file__), '../../deployment/executor.py')

    with open(executor_path, 'r') as f:
        content = f.read()

    # Check that docstrings mention granular states
    assert 'validating' in content.lower(), "executor.py should document 'validating' state"
    assert 'pulling_image' in content.lower(), "executor.py should document 'pulling_image' state"
    assert 'creating' in content.lower(), "executor.py should document 'creating' state"
    assert 'starting' in content.lower(), "executor.py should document 'starting' state"
