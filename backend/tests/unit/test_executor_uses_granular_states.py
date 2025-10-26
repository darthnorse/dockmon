"""
Phase 3.3 TDD Test: Verify executor uses granular 7-state flow

This test checks that executor.py uses the new granular states instead of old 3-state flow.

RED Phase (now): This test FAILS because executor uses 'executing' state
GREEN Phase (after refactoring): This test PASSES when executor uses granular states
"""

import os


def test_executor_does_not_use_executing_state():
    """
    executor.py should not reference obsolete 'executing' state.

    Old flow: planning → executing → completed
    New flow: pending → validating → pulling_image → creating → starting → running

    This test will FAIL (RED phase) until we refactor executor to use granular states.
    """
    executor_path = os.path.join(os.path.dirname(__file__), '../../deployment/executor.py')

    with open(executor_path, 'r') as f:
        content = f.read()

    # Check for 'executing' state being used in state transitions
    # We allow it in comments/docstrings but not in actual code
    lines = content.split('\n')

    for i, line in enumerate(lines, 1):
        # Skip comments and empty lines
        if line.strip().startswith('#') or not line.strip():
            continue

        # Skip docstring lines (basic check)
        if '"""' in line or "'''" in line:
            continue

        # Check if 'executing' appears as a state value
        if "'executing'" in line or '"executing"' in line:
            # Look for context that indicates this is a state transition
            if any(keyword in line for keyword in ['transition', '.status =', 'status ==', 'status !=', 'in [', 'in (']):
                assert False, (
                    f"Found obsolete 'executing' state at line {i}: {line.strip()}\n\n"
                    f"Executor should use granular states instead:\n"
                    f"  - Use 'validating' for config validation\n"
                    f"  - Use 'pulling_image' during image pull\n"
                    f"  - Use 'creating' during container creation\n"
                    f"  - Use 'starting' during container start\n"
                    f"  - Use 'running' for successful completion\n"
                )


def test_executor_uses_validating_state():
    """executor.py should use 'validating' state for config validation"""
    executor_path = os.path.join(os.path.dirname(__file__), '../../deployment/executor.py')

    with open(executor_path, 'r') as f:
        content = f.read()

    # Check that 'validating' state is used
    has_validating = "'validating'" in content or '"validating"' in content

    assert has_validating, (
        "Executor should transition to 'validating' state at the start of deployment.\n"
        "Expected: self.state_machine.transition(deployment, 'validating')"
    )


def test_executor_uses_pulling_image_state():
    """executor.py should use 'pulling_image' state during image pull"""
    executor_path = os.path.join(os.path.dirname(__file__), '../../deployment/executor.py')

    with open(executor_path, 'r') as f:
        content = f.read()

    # Check that 'pulling_image' state is used
    has_pulling_image = "'pulling_image'" in content or '"pulling_image"' in content

    assert has_pulling_image, (
        "Executor should transition to 'pulling_image' state before pulling image.\n"
        "Expected: self.state_machine.transition(deployment, 'pulling_image')"
    )


def test_executor_uses_creating_state():
    """executor.py should use 'creating' state during container creation"""
    executor_path = os.path.join(os.path.dirname(__file__), '../../deployment/executor.py')

    with open(executor_path, 'r') as f:
        content = f.read()

    # Check that 'creating' state is used
    has_creating = "'creating'" in content or '"creating"' in content

    assert has_creating, (
        "Executor should transition to 'creating' state before creating container.\n"
        "Expected: self.state_machine.transition(deployment, 'creating')"
    )


def test_executor_uses_starting_state():
    """executor.py should use 'starting' state during container start"""
    executor_path = os.path.join(os.path.dirname(__file__), '../../deployment/executor.py')

    with open(executor_path, 'r') as f:
        content = f.read()

    # Check that 'starting' state is used
    has_starting = "'starting'" in content or '"starting"' in content

    assert has_starting, (
        "Executor should transition to 'starting' state before starting container.\n"
        "Expected: self.state_machine.transition(deployment, 'starting')"
    )


def test_executor_uses_running_state_not_completed():
    """executor.py should use 'running' state for completion, not 'completed'"""
    executor_path = os.path.join(os.path.dirname(__file__), '../../deployment/executor.py')

    with open(executor_path, 'r') as f:
        content = f.read()

    # Check for 'completed' state being used (old state)
    lines = content.split('\n')

    for i, line in enumerate(lines, 1):
        # Skip comments and empty lines
        if line.strip().startswith('#') or not line.strip():
            continue

        # Skip docstring lines
        if '"""' in line or "'''" in line:
            continue

        # Check if 'completed' appears as a state value
        if "'completed'" in line or '"completed"' in line:
            if any(keyword in line for keyword in ['transition', '.status =', 'status ==', 'status !=', 'in [', 'in (']):
                assert False, (
                    f"Found obsolete 'completed' state at line {i}: {line.strip()}\n\n"
                    f"Executor should use 'running' state instead of 'completed'.\n"
                    f"The 'running' state indicates deployment is complete and container is running."
                )


def test_executor_docstring_documents_7_state_flow():
    """executor.py execute_deployment docstring should document 7-state flow"""
    executor_path = os.path.join(os.path.dirname(__file__), '../../deployment/executor.py')

    with open(executor_path, 'r') as f:
        content = f.read()

    # Find execute_deployment docstring
    execute_deployment_start = content.find('async def execute_deployment')
    if execute_deployment_start == -1:
        assert False, "Could not find execute_deployment method"

    # Get docstring (next 1000 chars should contain it)
    docstring_section = content[execute_deployment_start:execute_deployment_start + 1000]

    # Check for old 3-state references
    assert 'planning → executing' not in docstring_section, (
        "execute_deployment docstring still references old 3-state flow.\n"
        "Should document new flow: pending → validating → pulling_image → creating → starting → running"
    )

    # Check that new states are mentioned
    assert 'validating' in docstring_section.lower() or 'pulling' in docstring_section.lower(), (
        "execute_deployment docstring should document granular state flow.\n"
        "Expected states: validating, pulling_image, creating, starting, running"
    )
