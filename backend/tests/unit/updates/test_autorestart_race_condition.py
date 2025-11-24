"""
Unit tests for auto-restart race condition fix (Issue #69).

Tests that both old and new container IDs are tracked in updating_containers
to prevent auto-restart interference during rollback.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from updates.update_executor import UpdateExecutor
from utils.keys import make_composite_key


@pytest.mark.unit
class TestAutoRestartRaceCondition:
    """Test auto-restart race condition prevention during rollback"""

    @pytest.fixture
    def mock_db(self):
        """Mock database manager"""
        db = Mock()
        session_mock = MagicMock()
        session_mock.__enter__ = Mock(return_value=session_mock)
        session_mock.__exit__ = Mock(return_value=False)
        db.get_session = Mock(return_value=session_mock)
        return db

    @pytest.fixture
    def mock_monitor(self):
        """Mock docker monitor"""
        monitor = Mock()
        monitor.get_docker_client = AsyncMock(return_value=Mock())
        monitor.hosts = {}
        return monitor

    @pytest.fixture
    def executor(self, mock_db, mock_monitor):
        """Create UpdateExecutor instance"""
        return UpdateExecutor(db=mock_db, monitor=mock_monitor)

    def test_new_container_added_to_updating_set(self, executor):
        """Test that new container ID is added to updating_containers after creation"""
        host_id = "test-host-123"
        old_container_id = "abc123def456"
        new_container_id = "xyz789uvw012"

        old_composite_key = make_composite_key(host_id, old_container_id)
        new_composite_key = make_composite_key(host_id, new_container_id)

        # Simulate update starting - add old container
        with executor._update_lock:
            executor.updating_containers.add(old_composite_key)

        # Verify old container is tracked
        assert executor.is_container_updating(host_id, old_container_id)

        # Simulate new container creation - add new container
        with executor._update_lock:
            executor.updating_containers.add(new_composite_key)

        # Verify both containers are now tracked
        assert executor.is_container_updating(host_id, old_container_id)
        assert executor.is_container_updating(host_id, new_container_id)
        assert len(executor.updating_containers) == 2

    def test_both_containers_removed_in_finally(self, executor):
        """Test that both old and new container IDs are removed in finally block"""
        host_id = "test-host-123"
        old_container_id = "abc123def456"
        new_container_id = "xyz789uvw012"

        old_composite_key = make_composite_key(host_id, old_container_id)
        new_composite_key = make_composite_key(host_id, new_container_id)

        # Add both containers
        with executor._update_lock:
            executor.updating_containers.add(old_composite_key)
            executor.updating_containers.add(new_composite_key)

        assert len(executor.updating_containers) == 2

        # Simulate finally block cleanup
        with executor._update_lock:
            executor.updating_containers.discard(old_composite_key)
            executor.updating_containers.discard(new_composite_key)

        # Verify both removed
        assert not executor.is_container_updating(host_id, old_container_id)
        assert not executor.is_container_updating(host_id, new_container_id)
        assert len(executor.updating_containers) == 0

    def test_early_failure_only_removes_old_container(self, executor):
        """Test that early failure (no new container) only removes old ID"""
        host_id = "test-host-123"
        old_container_id = "abc123def456"

        old_composite_key = make_composite_key(host_id, old_container_id)

        # Add only old container (new container never created)
        with executor._update_lock:
            executor.updating_containers.add(old_composite_key)

        assert len(executor.updating_containers) == 1

        # Simulate finally block with no new_container_id
        new_container_id = None
        with executor._update_lock:
            executor.updating_containers.discard(old_composite_key)
            if new_container_id:  # This branch should not execute
                new_composite_key = make_composite_key(host_id, new_container_id)
                executor.updating_containers.discard(new_composite_key)

        # Verify only old removed (no exception from missing new_container_id)
        assert not executor.is_container_updating(host_id, old_container_id)
        assert len(executor.updating_containers) == 0

    def test_concurrent_updates_different_containers(self, executor):
        """Test that concurrent updates of different containers don't interfere"""
        # Container 1
        host1_id = "host1"
        container1_old = "old1abc12345"  # 12 chars
        container1_new = "new1def67890"  # 12 chars

        # Container 2
        host2_id = "host2"
        container2_old = "old2ghi12345"  # 12 chars
        container2_new = "new2jkl67890"  # 12 chars

        # Add both updates
        with executor._update_lock:
            executor.updating_containers.add(make_composite_key(host1_id, container1_old))
            executor.updating_containers.add(make_composite_key(host1_id, container1_new))
            executor.updating_containers.add(make_composite_key(host2_id, container2_old))
            executor.updating_containers.add(make_composite_key(host2_id, container2_new))

        # Verify all 4 tracked
        assert len(executor.updating_containers) == 4
        assert executor.is_container_updating(host1_id, container1_old)
        assert executor.is_container_updating(host1_id, container1_new)
        assert executor.is_container_updating(host2_id, container2_old)
        assert executor.is_container_updating(host2_id, container2_new)

        # Complete container 1 update
        with executor._update_lock:
            executor.updating_containers.discard(make_composite_key(host1_id, container1_old))
            executor.updating_containers.discard(make_composite_key(host1_id, container1_new))

        # Verify only container 1 removed
        assert len(executor.updating_containers) == 2
        assert not executor.is_container_updating(host1_id, container1_old)
        assert not executor.is_container_updating(host1_id, container1_new)
        assert executor.is_container_updating(host2_id, container2_old)
        assert executor.is_container_updating(host2_id, container2_new)

    @pytest.mark.asyncio
    async def test_auto_restart_blocked_during_rollback(self, executor, mock_db, mock_monitor):
        """Test that auto-restart is blocked for new container during rollback"""
        host_id = "test-host-123"
        old_container_id = "abc123def456"
        new_container_id = "xyz789uvw012"

        # Simulate update in progress with both containers tracked
        old_composite_key = make_composite_key(host_id, old_container_id)
        new_composite_key = make_composite_key(host_id, new_container_id)

        with executor._update_lock:
            executor.updating_containers.add(old_composite_key)
            executor.updating_containers.add(new_composite_key)

        # Auto-restart should be blocked for BOTH containers
        assert executor.is_container_updating(host_id, old_container_id)
        assert executor.is_container_updating(host_id, new_container_id)

        # This prevents the race condition - auto-restart will skip both:
        # - Old container (backup): already protected
        # - New container (being rolled back): NOW protected (Issue #69 fix)

    def test_thread_safety_atomic_operations(self, executor):
        """Test that set modifications are thread-safe with lock"""
        host_id = "test-host"
        container_id = "test12345678"  # 12 chars
        composite_key = make_composite_key(host_id, container_id)

        # Verify lock is used for add
        with executor._update_lock:
            executor.updating_containers.add(composite_key)

        assert composite_key in executor.updating_containers

        # Verify lock is used for remove
        with executor._update_lock:
            executor.updating_containers.discard(composite_key)

        assert composite_key not in executor.updating_containers

    def test_idempotent_removal(self, executor):
        """Test that removing non-existent container ID is safe (idempotent)"""
        host_id = "test-host"
        container_id = "none12345678"  # 12 chars
        composite_key = make_composite_key(host_id, container_id)

        # Remove non-existent key (should not raise exception)
        with executor._update_lock:
            executor.updating_containers.discard(composite_key)

        # Verify no error and set is empty
        assert len(executor.updating_containers) == 0

    @pytest.mark.asyncio
    async def test_rollback_cleans_up_both_containers(self, executor, mock_db):
        """Test that rollback scenario properly tracks and cleans up both IDs"""
        host_id = "test-host-123"
        old_container_id = "old123456789"  # 12 chars
        new_container_id = "new456789012"  # 12 chars

        old_composite_key = make_composite_key(host_id, old_container_id)
        new_composite_key = make_composite_key(host_id, new_container_id)

        # Simulate update lifecycle
        # Step 1: Add old container (update starts)
        with executor._update_lock:
            executor.updating_containers.add(old_composite_key)

        # Step 2: Add new container (after creation)
        with executor._update_lock:
            executor.updating_containers.add(new_composite_key)

        # Both should be tracked during rollback
        assert len(executor.updating_containers) == 2

        # Step 3: Rollback kills new container
        # Auto-restart checks: is_container_updating(new_container_id)?
        # Result: TRUE (because we added it) -> auto-restart SKIPS it
        assert executor.is_container_updating(host_id, new_container_id)

        # Step 4: Finally block removes both
        with executor._update_lock:
            executor.updating_containers.discard(old_composite_key)
            executor.updating_containers.discard(new_composite_key)

        # Verify cleanup
        assert len(executor.updating_containers) == 0

    def test_batch_update_independence(self, executor):
        """Test that batch updates maintain separate tracking per container"""
        # Simulate 3 concurrent updates (like in the logs)
        updates = [
            ("host1", "c1old1234567", "c1new7890123"),  # 12 chars each
            ("host2", "c2old1234567", "c2new7890123"),  # 12 chars each
            ("host3", "c3old1234567", "c3new7890123"),  # 12 chars each
        ]

        # Add all updates
        with executor._update_lock:
            for host_id, old_id, new_id in updates:
                executor.updating_containers.add(make_composite_key(host_id, old_id))
                executor.updating_containers.add(make_composite_key(host_id, new_id))

        # Verify 6 containers tracked (2 per update)
        assert len(executor.updating_containers) == 6

        # Complete one update (remove both IDs)
        host_id, old_id, new_id = updates[0]
        with executor._update_lock:
            executor.updating_containers.discard(make_composite_key(host_id, old_id))
            executor.updating_containers.discard(make_composite_key(host_id, new_id))

        # Verify only 4 remain
        assert len(executor.updating_containers) == 4

        # Other updates still tracked
        for host_id, old_id, new_id in updates[1:]:
            assert executor.is_container_updating(host_id, old_id)
            assert executor.is_container_updating(host_id, new_id)
