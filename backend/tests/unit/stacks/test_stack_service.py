"""
Unit tests for Stack Service module.

Tests the service layer that coordinates filesystem and database operations.
"""

from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from deployment.stack_service import (
    StackInfo,
    list_stacks_with_counts,
    get_stack,
    create_stack,
    update_stack,
    rename_stack,
    delete_stack,
    copy_stack,
    get_deployment_count,
)


class TestStackInfo:
    """Test StackInfo data class"""

    def test_to_dict_basic(self):
        """Should return dict with name and count"""
        info = StackInfo(name="nginx", deployment_count=3)
        result = info.to_dict()

        assert result == {"name": "nginx", "deployment_count": 3}

    def test_to_dict_with_content(self):
        """Should include content when present"""
        info = StackInfo(
            name="nginx",
            deployment_count=1,
            compose_yaml="services: {}",
            env_content="PORT=80",
        )
        result = info.to_dict()

        assert result["name"] == "nginx"
        assert result["deployment_count"] == 1
        assert result["compose_yaml"] == "services: {}"
        assert result["env_content"] == "PORT=80"

    def test_to_dict_excludes_none_content(self):
        """Should exclude content fields when None"""
        info = StackInfo(name="nginx", deployment_count=0)
        result = info.to_dict()

        assert "compose_yaml" not in result
        assert "env_content" not in result


class TestListStacksWithCounts:
    """Test listing stacks with deployment counts"""

    @pytest.mark.asyncio
    async def test_empty_list(self):
        """Should return empty list when no stacks"""
        session = MagicMock()

        with patch("deployment.stack_service.stack_storage") as mock_storage:
            mock_storage.list_stacks = AsyncMock(return_value=[])

            result = await list_stacks_with_counts(session)

        assert result == []

    @pytest.mark.asyncio
    async def test_stacks_with_counts(self):
        """Should return stacks with deployment counts"""
        session = MagicMock()
        # Mock query chain
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.group_by.return_value = mock_query
        mock_query.all.return_value = [("nginx", 2), ("postgres", 1)]
        session.query.return_value = mock_query

        with patch("deployment.stack_service.stack_storage") as mock_storage:
            mock_storage.list_stacks = AsyncMock(return_value=["nginx", "postgres", "redis"])

            result = await list_stacks_with_counts(session)

        assert len(result) == 3
        assert result[0].name == "nginx"
        assert result[0].deployment_count == 2
        assert result[1].name == "postgres"
        assert result[1].deployment_count == 1
        assert result[2].name == "redis"
        assert result[2].deployment_count == 0  # No deployments


class TestGetStack:
    """Test getting a single stack"""

    @pytest.mark.asyncio
    async def test_get_existing_stack(self):
        """Should return stack info with content"""
        session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.scalar.return_value = 2
        session.query.return_value = mock_query

        with patch("deployment.stack_service.stack_storage") as mock_storage:
            mock_storage.stack_exists = AsyncMock(return_value=True)
            mock_storage.read_stack = AsyncMock(return_value=("services: {}", "PORT=80"))

            result = await get_stack(session, "nginx")

        assert result is not None
        assert result.name == "nginx"
        assert result.deployment_count == 2
        assert result.compose_yaml == "services: {}"
        assert result.env_content == "PORT=80"

    @pytest.mark.asyncio
    async def test_get_nonexistent_stack(self):
        """Should return None for nonexistent stack"""
        session = MagicMock()

        with patch("deployment.stack_service.stack_storage") as mock_storage:
            mock_storage.stack_exists = AsyncMock(return_value=False)

            result = await get_stack(session, "nonexistent")

        assert result is None


class TestCreateStack:
    """Test creating stacks"""

    @pytest.mark.asyncio
    async def test_create_success(self):
        """Should create stack and return info"""
        with patch("deployment.stack_service.stack_storage") as mock_storage:
            mock_storage.write_stack = AsyncMock()

            result = await create_stack("nginx", "services: {}", "PORT=80")

        assert result.name == "nginx"
        assert result.deployment_count == 0
        assert result.compose_yaml == "services: {}"
        assert result.env_content == "PORT=80"
        mock_storage.write_stack.assert_called_once_with(
            "nginx", "services: {}", "PORT=80", create_only=True
        )

    @pytest.mark.asyncio
    async def test_create_already_exists(self):
        """Should raise ValueError if stack exists"""
        with patch("deployment.stack_service.stack_storage") as mock_storage:
            mock_storage.write_stack = AsyncMock(
                side_effect=ValueError("Stack 'nginx' already exists")
            )

            with pytest.raises(ValueError, match="already exists"):
                await create_stack("nginx", "services: {}")


class TestUpdateStack:
    """Test updating stacks"""

    @pytest.mark.asyncio
    async def test_update_success(self):
        """Should update stack content"""
        with patch("deployment.stack_service.stack_storage") as mock_storage:
            mock_storage.stack_exists = AsyncMock(return_value=True)
            mock_storage.write_stack = AsyncMock()

            result = await update_stack("nginx", "services: {}", "PORT=8080")

        assert result.name == "nginx"
        assert result.compose_yaml == "services: {}"
        assert result.env_content == "PORT=8080"
        mock_storage.write_stack.assert_called_once_with(
            "nginx", "services: {}", "PORT=8080"
        )

    @pytest.mark.asyncio
    async def test_update_nonexistent(self):
        """Should raise FileNotFoundError if stack doesn't exist"""
        with patch("deployment.stack_service.stack_storage") as mock_storage:
            mock_storage.stack_exists = AsyncMock(return_value=False)

            with pytest.raises(FileNotFoundError, match="not found"):
                await update_stack("nonexistent", "services: {}")


class TestRenameStack:
    """Test renaming stacks"""

    @pytest.mark.asyncio
    async def test_rename_success(self):
        """Should validate, update DB, rename files, and return content"""
        session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.update.return_value = 3  # 3 deployments updated
        session.query.return_value = mock_query

        with patch("deployment.stack_service.stack_storage") as mock_storage:
            mock_storage.validate_stack_name = MagicMock()  # Sync function
            mock_storage.stack_exists = AsyncMock(side_effect=[True, False])  # old exists, new doesn't
            mock_storage.rename_stack_files = AsyncMock()
            mock_storage.read_stack = AsyncMock(return_value=("services: {}", "PORT=80"))

            result = await rename_stack(session, "old-name", "new-name")

        assert result.name == "new-name"
        assert result.deployment_count == 3
        assert result.compose_yaml == "services: {}"
        assert result.env_content == "PORT=80"
        mock_storage.rename_stack_files.assert_called_once_with("old-name", "new-name")
        mock_storage.read_stack.assert_called_once_with("new-name")
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_rename_file_error_rolls_back_db(self):
        """Should rollback DB if file rename fails after commit"""
        session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.update.return_value = 2  # 2 deployments updated
        session.query.return_value = mock_query

        with patch("deployment.stack_service.stack_storage") as mock_storage:
            mock_storage.validate_stack_name = MagicMock()
            mock_storage.stack_exists = AsyncMock(side_effect=[True, False])  # old exists, new doesn't
            mock_storage.rename_stack_files = AsyncMock(
                side_effect=OSError("Filesystem error")
            )

            with pytest.raises(OSError, match="Filesystem error"):
                await rename_stack(session, "old-name", "new-name")

        # DB should be committed then rolled back
        assert session.commit.call_count == 2  # Initial commit + rollback commit

    @pytest.mark.asyncio
    async def test_rename_old_not_found(self):
        """Should raise FileNotFoundError if old stack doesn't exist"""
        session = MagicMock()

        with patch("deployment.stack_service.stack_storage") as mock_storage:
            mock_storage.validate_stack_name = MagicMock()
            mock_storage.stack_exists = AsyncMock(return_value=False)

            with pytest.raises(FileNotFoundError, match="not found"):
                await rename_stack(session, "nonexistent", "new-name")

        # DB should not be touched
        session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_rename_new_already_exists(self):
        """Should raise ValueError if new name already exists"""
        session = MagicMock()

        with patch("deployment.stack_service.stack_storage") as mock_storage:
            mock_storage.validate_stack_name = MagicMock()
            mock_storage.stack_exists = AsyncMock(side_effect=[True, True])  # Both exist

            with pytest.raises(ValueError, match="already exists"):
                await rename_stack(session, "old-name", "existing-name")

        # DB should not be touched
        session.commit.assert_not_called()


class TestDeleteStack:
    """Test deleting stacks"""

    @pytest.mark.asyncio
    async def test_delete_success(self):
        """Should delete stack with no deployments"""
        session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.scalar.return_value = 0  # No deployments
        session.query.return_value = mock_query

        with patch("deployment.stack_service.stack_storage") as mock_storage:
            mock_storage.stack_exists = AsyncMock(return_value=True)
            mock_storage.delete_stack_files = AsyncMock()

            await delete_stack(session, "nginx")

        mock_storage.delete_stack_files.assert_called_once_with("nginx")

    @pytest.mark.asyncio
    async def test_delete_blocked_with_deployments(self):
        """Should raise ValueError if deployments exist"""
        session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.scalar.return_value = 2  # Has deployments
        session.query.return_value = mock_query

        with patch("deployment.stack_service.stack_storage") as mock_storage:
            mock_storage.stack_exists = AsyncMock(return_value=True)

            with pytest.raises(ValueError, match="2 deployment"):
                await delete_stack(session, "nginx")

        # Files should not be deleted
        mock_storage.delete_stack_files.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self):
        """Should raise FileNotFoundError if stack doesn't exist"""
        session = MagicMock()

        with patch("deployment.stack_service.stack_storage") as mock_storage:
            mock_storage.stack_exists = AsyncMock(return_value=False)

            with pytest.raises(FileNotFoundError, match="not found"):
                await delete_stack(session, "nonexistent")


class TestCopyStack:
    """Test copying stacks"""

    @pytest.mark.asyncio
    async def test_copy_success(self):
        """Should copy stack and return new info with content"""
        with patch("deployment.stack_service.stack_storage") as mock_storage:
            mock_storage.copy_stack = AsyncMock()
            mock_storage.read_stack = AsyncMock(return_value=("services: {}", "PORT=80"))

            result = await copy_stack("source", "dest")

        assert result.name == "dest"
        assert result.deployment_count == 0
        assert result.compose_yaml == "services: {}"
        assert result.env_content == "PORT=80"
        mock_storage.copy_stack.assert_called_once_with("source", "dest")
        mock_storage.read_stack.assert_called_once_with("dest")


class TestGetDeploymentCount:
    """Test synchronous deployment count helper"""

    def test_get_count(self):
        """Should return deployment count"""
        session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.scalar.return_value = 5
        session.query.return_value = mock_query

        result = get_deployment_count(session, "nginx")

        assert result == 5

    def test_get_count_none_returns_zero(self):
        """Should return 0 if query returns None"""
        session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.scalar.return_value = None
        session.query.return_value = mock_query

        result = get_deployment_count(session, "nginx")

        assert result == 0
