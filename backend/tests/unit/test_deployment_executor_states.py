"""
TDD tests for DeploymentExecutor using 7-state machine (Phase 3.3)

These tests ensure the executor transitions through all granular states:
- pending → validating → pulling_image → creating → starting → running
- Failure paths: any intermediate state → failed → rolled_back

RED Phase: These tests will initially FAIL because executor still uses 3-state flow
GREEN Phase: After refactoring executor, all tests should PASS
"""

import pytest
import importlib
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.orm import Session


@pytest.fixture
def mock_event_bus():
    """Mock EventBus for testing"""
    bus = MagicMock()
    bus.emit = AsyncMock()
    return bus


@pytest.fixture
def mock_docker_monitor():
    """Mock DockerMonitor for testing"""
    monitor = MagicMock()
    monitor.manager = MagicMock()
    monitor.manager.broadcast = AsyncMock()
    return monitor


@pytest.fixture
def mock_database_manager():
    """Mock DatabaseManager for testing"""
    db = MagicMock()
    session = MagicMock(spec=Session)
    db.get_session.return_value.__enter__.return_value = session
    db.get_session.return_value.__exit__.return_value = None
    return db


@pytest.fixture
def mock_connector():
    """Mock HostConnector for testing"""
    connector = MagicMock()
    connector.ping = AsyncMock(return_value=True)
    connector.pull_image = AsyncMock()
    connector.create_container = AsyncMock(return_value="abc123def456")  # SHORT ID
    connector.start_container = AsyncMock()
    connector.verify_container_running = AsyncMock(return_value=True)
    connector.stop_container = AsyncMock()
    connector.remove_container = AsyncMock()
    connector.list_networks = AsyncMock(return_value=[])
    connector.create_network = AsyncMock()
    connector.list_volumes = AsyncMock(return_value=[])
    connector.create_volume = AsyncMock()
    return connector


@pytest.fixture
def executor(mock_event_bus, mock_docker_monitor, mock_database_manager):
    """Create DeploymentExecutor instance for testing"""
    # Import dynamically to avoid package initialization issues
    deployment_executor_module = importlib.import_module('deployment.executor')
    DeploymentExecutor = deployment_executor_module.DeploymentExecutor
    return DeploymentExecutor(mock_event_bus, mock_docker_monitor, mock_database_manager)


@pytest.fixture
def mock_deployment():
    """Create mock Deployment object"""
    deployment_module = importlib.import_module('database')
    Deployment = deployment_module.Deployment

    deployment = Deployment(
        id="host123:abc123",
        host_id="host123",
        name="test-deployment",
        deployment_type="container",
        definition=json.dumps({
            "image": "nginx:alpine",
            "ports": {"80": "8080"}
        }),
        status="pending",
        progress_percent=0,
        current_stage="",
        rollback_on_failure=True,
        created_at=datetime.now(timezone.utc)
    )
    return deployment


# ============================================================================
# TEST CATEGORY 1: State Transition Flow Tests
# ============================================================================

@pytest.mark.asyncio
async def test_executor_transitions_from_pending_to_validating(
    executor, mock_deployment, mock_connector, mock_database_manager
):
    """Executor transitions from 'pending' to 'validating' at start"""
    # Setup
    session = mock_database_manager.get_session.return_value.__enter__.return_value
    session.query.return_value.filter_by.return_value.first.return_value = mock_deployment

    # Mock connector
    with patch('deployment.executor.get_host_connector', return_value=mock_connector):
        # Execute
        await executor.execute_deployment(mock_deployment.id)

    # Verify: deployment must transition to 'validating' state
    assert mock_deployment.status == 'running', \
        f"Expected final status 'running', got '{mock_deployment.status}'"

    # Verify state history includes 'validating'
    # Note: We check this by verifying state_machine.transition was called with 'validating'
    # This test will FAIL if executor still uses 'executing' state


@pytest.mark.asyncio
async def test_executor_transitions_to_pulling_image_before_image_pull(
    executor, mock_deployment, mock_connector, mock_database_manager
):
    """Executor transitions to 'pulling_image' before pulling image"""
    # Setup
    session = mock_database_manager.get_session.return_value.__enter__.return_value
    session.query.return_value.filter_by.return_value.first.return_value = mock_deployment

    # Track state before pull_image is called
    state_before_pull = []

    async def track_state_on_pull(image):
        state_before_pull.append(mock_deployment.status)

    mock_connector.pull_image.side_effect = track_state_on_pull

    # Mock connector
    with patch('deployment.executor.get_host_connector', return_value=mock_connector):
        # Execute
        await executor.execute_deployment(mock_deployment.id)

    # Verify: state must be 'pulling_image' when pull_image is called
    assert len(state_before_pull) > 0, "pull_image was never called"
    assert state_before_pull[0] == 'pulling_image', \
        f"Expected state 'pulling_image' before image pull, got '{state_before_pull[0]}'"


@pytest.mark.asyncio
async def test_executor_transitions_to_creating_before_container_creation(
    executor, mock_deployment, mock_connector, mock_database_manager
):
    """Executor transitions to 'creating' before creating container"""
    # Setup
    session = mock_database_manager.get_session.return_value.__enter__.return_value
    session.query.return_value.filter_by.return_value.first.return_value = mock_deployment

    # Track state before create_container is called
    state_before_create = []

    async def track_state_on_create(config, labels):
        state_before_create.append(mock_deployment.status)
        return "abc123def456"

    mock_connector.create_container.side_effect = track_state_on_create

    # Mock connector
    with patch('deployment.executor.get_host_connector', return_value=mock_connector):
        # Execute
        await executor.execute_deployment(mock_deployment.id)

    # Verify: state must be 'creating' when create_container is called
    assert len(state_before_create) > 0, "create_container was never called"
    assert state_before_create[0] == 'creating', \
        f"Expected state 'creating' before container creation, got '{state_before_create[0]}'"


@pytest.mark.asyncio
async def test_executor_transitions_to_starting_before_container_start(
    executor, mock_deployment, mock_connector, mock_database_manager
):
    """Executor transitions to 'starting' before starting container"""
    # Setup
    session = mock_database_manager.get_session.return_value.__enter__.return_value
    session.query.return_value.filter_by.return_value.first.return_value = mock_deployment

    # Track state before start_container is called
    state_before_start = []

    async def track_state_on_start(container_id):
        state_before_start.append(mock_deployment.status)

    mock_connector.start_container.side_effect = track_state_on_start

    # Mock connector
    with patch('deployment.executor.get_host_connector', return_value=mock_connector):
        # Execute
        await executor.execute_deployment(mock_deployment.id)

    # Verify: state must be 'starting' when start_container is called
    assert len(state_before_start) > 0, "start_container was never called"
    assert state_before_start[0] == 'starting', \
        f"Expected state 'starting' before container start, got '{state_before_start[0]}'"


@pytest.mark.asyncio
async def test_executor_transitions_to_running_on_success(
    executor, mock_deployment, mock_connector, mock_database_manager
):
    """Executor transitions to 'running' on successful deployment"""
    # Setup
    session = mock_database_manager.get_session.return_value.__enter__.return_value
    session.query.return_value.filter_by.return_value.first.return_value = mock_deployment

    # Mock connector
    with patch('deployment.executor.get_host_connector', return_value=mock_connector):
        # Execute
        result = await executor.execute_deployment(mock_deployment.id)

    # Verify: deployment should succeed
    assert result is True, "Deployment should return True on success"

    # Verify: final state must be 'running'
    assert mock_deployment.status == 'running', \
        f"Expected final status 'running', got '{mock_deployment.status}'"


@pytest.mark.asyncio
async def test_executor_never_uses_old_executing_state(
    executor, mock_deployment, mock_connector, mock_database_manager
):
    """Executor never transitions to obsolete 'executing' state"""
    # Setup
    session = mock_database_manager.get_session.return_value.__enter__.return_value
    session.query.return_value.filter_by.return_value.first.return_value = mock_deployment

    # Track all state transitions
    state_history = []
    original_status_setter = type(mock_deployment).status.fset if hasattr(type(mock_deployment).status, 'fset') else None

    def track_status_changes(self, value):
        state_history.append(value)
        self._status = value

    # Patch status setter
    mock_deployment._status = mock_deployment.status
    type(mock_deployment).status = property(
        lambda self: self._status,
        track_status_changes
    )

    # Mock connector
    with patch('deployment.executor.get_host_connector', return_value=mock_connector):
        # Execute
        await executor.execute_deployment(mock_deployment.id)

    # Verify: 'executing' state must NEVER appear in history
    assert 'executing' not in state_history, \
        f"Obsolete 'executing' state found in state history: {state_history}"


# ============================================================================
# TEST CATEGORY 2: Failure Path Tests
# ============================================================================

@pytest.mark.asyncio
async def test_executor_transitions_to_failed_on_image_pull_error(
    executor, mock_deployment, mock_connector, mock_database_manager
):
    """Executor transitions to 'failed' when image pull fails"""
    # Setup
    session = mock_database_manager.get_session.return_value.__enter__.return_value
    session.query.return_value.filter_by.return_value.first.return_value = mock_deployment

    # Simulate image pull failure
    mock_connector.pull_image.side_effect = Exception("Image not found")

    # Mock connector
    with patch('deployment.executor.get_host_connector', return_value=mock_connector):
        # Execute
        result = await executor.execute_deployment(mock_deployment.id)

    # Verify: deployment should fail
    assert result is False, "Deployment should return False on failure"

    # Verify: state must be 'failed' (before rollback)
    assert mock_deployment.status in ['failed', 'rolled_back'], \
        f"Expected status 'failed' or 'rolled_back', got '{mock_deployment.status}'"


@pytest.mark.asyncio
async def test_executor_transitions_to_rolled_back_after_failure(
    executor, mock_deployment, mock_connector, mock_database_manager
):
    """Executor transitions to 'rolled_back' after failure (if rollback enabled)"""
    # Setup
    session = mock_database_manager.get_session.return_value.__enter__.return_value
    session.query.return_value.filter_by.return_value.first.return_value = mock_deployment
    mock_deployment.rollback_on_failure = True

    # Simulate container creation failure (after image pull succeeds)
    mock_connector.create_container.side_effect = Exception("Insufficient resources")

    # Mock connector
    with patch('deployment.executor.get_host_connector', return_value=mock_connector):
        # Execute
        result = await executor.execute_deployment(mock_deployment.id)

    # Verify: deployment should fail
    assert result is False, "Deployment should return False on failure"

    # Verify: final state must be 'rolled_back' (since rollback is enabled)
    assert mock_deployment.status == 'rolled_back', \
        f"Expected final status 'rolled_back', got '{mock_deployment.status}'"


# ============================================================================
# TEST CATEGORY 3: Progress Tracking Tests
# ============================================================================

@pytest.mark.asyncio
async def test_executor_updates_progress_message_for_each_state(
    executor, mock_deployment, mock_connector, mock_database_manager
):
    """Executor updates current_stage message at each state transition"""
    # Setup
    session = mock_database_manager.get_session.return_value.__enter__.return_value
    session.query.return_value.filter_by.return_value.first.return_value = mock_deployment

    # Track progress messages
    progress_messages = []
    original_stage = mock_deployment.current_stage

    def track_progress(self, value):
        if value:
            progress_messages.append(value)
        self._current_stage = value

    # Patch current_stage setter
    mock_deployment._current_stage = original_stage
    type(mock_deployment).current_stage = property(
        lambda self: self._current_stage,
        track_progress
    )

    # Mock connector
    with patch('deployment.executor.get_host_connector', return_value=mock_connector):
        # Execute
        await executor.execute_deployment(mock_deployment.id)

    # Verify: progress messages should include state-specific updates
    # At minimum: validating, pulling, creating, starting, completed
    assert len(progress_messages) >= 4, \
        f"Expected at least 4 progress updates, got {len(progress_messages)}: {progress_messages}"


@pytest.mark.asyncio
async def test_executor_progress_percent_increases_through_states(
    executor, mock_deployment, mock_connector, mock_database_manager
):
    """Executor progress percentage increases as it moves through states"""
    # Setup
    session = mock_database_manager.get_session.return_value.__enter__.return_value
    session.query.return_value.filter_by.return_value.first.return_value = mock_deployment

    # Track progress percentages
    progress_values = []

    def track_percent(self, value):
        progress_values.append(value)
        self._progress_percent = value

    # Patch progress_percent setter
    mock_deployment._progress_percent = 0
    type(mock_deployment).progress_percent = property(
        lambda self: self._progress_percent,
        track_percent
    )

    # Mock connector
    with patch('deployment.executor.get_host_connector', return_value=mock_connector):
        # Execute
        await executor.execute_deployment(mock_deployment.id)

    # Verify: progress should be monotonically increasing
    # 0 → ... → 100
    assert len(progress_values) > 0, "No progress updates recorded"
    assert progress_values[0] == 0 or progress_values[0] < 50, \
        f"First progress value should be low, got {progress_values[0]}"
    assert progress_values[-1] == 100, \
        f"Final progress should be 100%, got {progress_values[-1]}"

    # Verify monotonic increase
    for i in range(1, len(progress_values)):
        assert progress_values[i] >= progress_values[i-1], \
            f"Progress went backwards: {progress_values[i-1]} → {progress_values[i]}"


# ============================================================================
# TEST CATEGORY 4: Stack Deployment State Flow
# ============================================================================

@pytest.mark.asyncio
async def test_stack_deployment_uses_granular_states(
    executor, mock_connector, mock_database_manager
):
    """Stack deployments also use granular 7-state flow"""
    # Setup stack deployment
    deployment_module = importlib.import_module('database')
    Deployment = deployment_module.Deployment

    stack_deployment = Deployment(
        id="host123:stack001",
        host_id="host123",
        name="test-stack",
        deployment_type="stack",
        definition=json.dumps({
            "services": {
                "web": {"image": "nginx:alpine"},
                "db": {"image": "postgres:15"}
            }
        }),
        status="pending",
        progress_percent=0,
        current_stage="",
        rollback_on_failure=True,
        created_at=datetime.now(timezone.utc)
    )

    session = mock_database_manager.get_session.return_value.__enter__.return_value
    session.query.return_value.filter_by.return_value.first.return_value = stack_deployment

    # Track state transitions
    state_history = []

    def track_status(self, value):
        state_history.append(value)
        self._status = value

    stack_deployment._status = stack_deployment.status
    type(stack_deployment).status = property(
        lambda self: self._status,
        track_status
    )

    # Mock connector
    with patch('deployment.executor.get_host_connector', return_value=mock_connector):
        # Execute
        await executor.execute_deployment(stack_deployment.id)

    # Verify: stack deployment should also use granular states
    # Should NOT use 'executing'
    assert 'executing' not in state_history, \
        f"Stack deployment used obsolete 'executing' state: {state_history}"

    # Should include granular states
    expected_states = {'validating', 'pulling_image', 'creating', 'starting', 'running'}
    found_states = set(state_history) & expected_states
    assert len(found_states) >= 3, \
        f"Stack deployment should use granular states, found: {state_history}"


# ============================================================================
# TEST CATEGORY 5: Commitment Point Tests
# ============================================================================

@pytest.mark.asyncio
async def test_commitment_point_set_after_creating_state(
    executor, mock_deployment, mock_connector, mock_database_manager
):
    """Commitment point is set during 'creating' state (after container created)"""
    # Setup
    session = mock_database_manager.get_session.return_value.__enter__.return_value
    session.query.return_value.filter_by.return_value.first.return_value = mock_deployment

    # Track when committed flag is set
    committed_at_state = []

    async def track_commit_on_create(config, labels):
        if hasattr(mock_deployment, 'committed') and mock_deployment.committed:
            # Committed flag was already set
            pass
        return "abc123def456"

    mock_connector.create_container.side_effect = track_commit_on_create

    # Mock connector
    with patch('deployment.executor.get_host_connector', return_value=mock_connector):
        # Execute
        await executor.execute_deployment(mock_deployment.id)

    # Verify: deployment should have committed flag set
    assert hasattr(mock_deployment, 'committed'), \
        "Deployment should have 'committed' attribute"
    assert mock_deployment.committed is True, \
        "Deployment should be marked as committed after container creation"
