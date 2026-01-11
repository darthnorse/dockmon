"""
Unit tests for Stack Storage module.

Tests filesystem operations for stack management:
- Stack name validation and sanitization
- Read/write operations
- Path safety (traversal prevention)
- Atomic operations (create_only, rename, copy, delete)
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from deployment import stack_storage
from deployment.stack_storage import (
    validate_stack_name,
    sanitize_stack_name,
    get_unique_stack_name,
    validate_path_safety,
    get_stack_path,
    stack_exists,
    read_stack,
    write_stack,
    delete_stack_files,
    copy_stack,
    rename_stack_files,
    list_stacks,
    VALID_NAME_PATTERN,
)


@pytest.fixture
def temp_stacks_dir(tmp_path):
    """Create a temporary stacks directory and patch STACKS_DIR."""
    stacks_dir = tmp_path / "stacks"
    stacks_dir.mkdir()
    with patch.object(stack_storage, 'STACKS_DIR', stacks_dir):
        yield stacks_dir


class TestValidateStackName:
    """Test stack name validation"""

    def test_valid_simple_name(self):
        """Should accept simple lowercase names"""
        validate_stack_name("nginx")
        validate_stack_name("my-app")
        validate_stack_name("app_v2")
        validate_stack_name("123app")

    def test_valid_with_numbers(self):
        """Should accept names with numbers"""
        validate_stack_name("app123")
        validate_stack_name("v2-api")
        validate_stack_name("2024-backup")

    def test_valid_with_hyphens_underscores(self):
        """Should accept names with hyphens and underscores"""
        validate_stack_name("my-cool-app")
        validate_stack_name("my_cool_app")
        validate_stack_name("my-cool_app-v2")

    def test_reject_empty_name(self):
        """Should reject empty names"""
        with pytest.raises(ValueError, match="1-100 characters"):
            validate_stack_name("")

    def test_reject_too_long_name(self):
        """Should reject names over 100 characters"""
        with pytest.raises(ValueError, match="1-100 characters"):
            validate_stack_name("a" * 101)

    def test_reject_uppercase(self):
        """Should reject uppercase letters"""
        with pytest.raises(ValueError, match="lowercase"):
            validate_stack_name("MyApp")

    def test_reject_spaces(self):
        """Should reject spaces"""
        with pytest.raises(ValueError, match="lowercase"):
            validate_stack_name("my app")

    def test_reject_special_chars(self):
        """Should reject special characters"""
        with pytest.raises(ValueError, match="lowercase"):
            validate_stack_name("my@app")
        with pytest.raises(ValueError, match="lowercase"):
            validate_stack_name("my.app")
        with pytest.raises(ValueError, match="lowercase"):
            validate_stack_name("my/app")

    def test_reject_starting_with_hyphen(self):
        """Should reject names starting with hyphen"""
        with pytest.raises(ValueError, match="start with"):
            validate_stack_name("-myapp")

    def test_reject_starting_with_underscore(self):
        """Should reject names starting with underscore"""
        with pytest.raises(ValueError, match="start with"):
            validate_stack_name("_myapp")


class TestSanitizeStackName:
    """Test stack name sanitization"""

    def test_lowercase_conversion(self):
        """Should convert to lowercase"""
        assert sanitize_stack_name("MyApp") == "myapp"
        assert sanitize_stack_name("NGINX") == "nginx"

    def test_space_to_hyphen(self):
        """Should replace spaces with hyphens"""
        assert sanitize_stack_name("my app") == "my-app"
        assert sanitize_stack_name("my  app") == "my-app"  # Multiple spaces

    def test_special_chars_to_hyphen(self):
        """Should replace special chars with hyphens"""
        assert sanitize_stack_name("my@app") == "my-app"
        assert sanitize_stack_name("my.app.v2") == "my-app-v2"

    def test_strip_leading_trailing_hyphens(self):
        """Should strip leading/trailing hyphens"""
        assert sanitize_stack_name("-myapp-") == "myapp"
        assert sanitize_stack_name("---myapp---") == "myapp"

    def test_add_prefix_if_starts_with_underscore(self):
        """Should add 'stack-' prefix if result starts with underscore"""
        # Underscores are valid chars but can't start with them
        assert sanitize_stack_name("_myapp") == "stack-_myapp"
        # Pure underscores get prefix added
        assert sanitize_stack_name("___") == "stack-___"

    def test_empty_becomes_unnamed(self):
        """Should return 'unnamed-stack' for empty result"""
        assert sanitize_stack_name("") == "unnamed-stack"
        assert sanitize_stack_name("@#$%") == "unnamed-stack"

    def test_preserve_valid_names(self):
        """Should preserve already-valid names"""
        assert sanitize_stack_name("nginx") == "nginx"
        assert sanitize_stack_name("my-app") == "my-app"
        assert sanitize_stack_name("app_v2") == "app_v2"


class TestGetUniqueStackName:
    """Test unique name generation"""

    def test_no_conflict(self):
        """Should return base name if no conflict"""
        assert get_unique_stack_name("nginx", set()) == "nginx"
        assert get_unique_stack_name("nginx", {"postgres"}) == "nginx"

    def test_single_conflict(self):
        """Should append -1 on first conflict"""
        assert get_unique_stack_name("nginx", {"nginx"}) == "nginx-1"

    def test_multiple_conflicts(self):
        """Should increment counter until unique"""
        existing = {"nginx", "nginx-1", "nginx-2"}
        assert get_unique_stack_name("nginx", existing) == "nginx-3"


class TestPathSafety:
    """Test path traversal prevention"""

    def test_valid_path(self, temp_stacks_dir):
        """Should accept valid paths within stacks dir"""
        path = temp_stacks_dir / "myapp"
        validate_path_safety(path)  # Should not raise

    def test_reject_parent_traversal(self, temp_stacks_dir):
        """Should reject parent directory traversal"""
        path = temp_stacks_dir / ".." / "etc" / "passwd"
        with pytest.raises(ValueError, match="escapes"):
            validate_path_safety(path)

    def test_reject_absolute_escape(self, temp_stacks_dir):
        """Should reject absolute paths outside stacks dir"""
        path = Path("/etc/passwd")
        with pytest.raises(ValueError, match="escapes"):
            validate_path_safety(path)


class TestGetStackPath:
    """Test stack path resolution"""

    def test_returns_path(self, temp_stacks_dir):
        """Should return path within stacks dir"""
        path = get_stack_path("myapp")
        assert path == temp_stacks_dir / "myapp"

    def test_rejects_traversal(self, temp_stacks_dir):
        """Should reject path traversal attempts"""
        with pytest.raises(ValueError, match="escapes"):
            get_stack_path("../../../etc/passwd")


class TestStackExists:
    """Test stack existence checking"""

    @pytest.mark.asyncio
    async def test_exists_with_compose(self, temp_stacks_dir):
        """Should return True if compose.yaml exists"""
        stack_dir = temp_stacks_dir / "myapp"
        stack_dir.mkdir()
        (stack_dir / "compose.yaml").write_text("services: {}")

        assert await stack_exists("myapp") is True

    @pytest.mark.asyncio
    async def test_not_exists_no_directory(self, temp_stacks_dir):
        """Should return False if directory doesn't exist"""
        assert await stack_exists("nonexistent") is False

    @pytest.mark.asyncio
    async def test_not_exists_no_compose(self, temp_stacks_dir):
        """Should return False if directory exists but no compose.yaml"""
        stack_dir = temp_stacks_dir / "empty"
        stack_dir.mkdir()

        assert await stack_exists("empty") is False

    @pytest.mark.asyncio
    async def test_traversal_returns_false(self, temp_stacks_dir):
        """Should return False for traversal attempts (not raise)"""
        assert await stack_exists("../../../etc") is False


class TestReadStack:
    """Test stack reading"""

    @pytest.mark.asyncio
    async def test_read_compose_only(self, temp_stacks_dir):
        """Should read compose.yaml when no .env exists"""
        stack_dir = temp_stacks_dir / "myapp"
        stack_dir.mkdir()
        (stack_dir / "compose.yaml").write_text("services:\n  web:\n    image: nginx")

        compose, env = await read_stack("myapp")

        assert "nginx" in compose
        assert env is None

    @pytest.mark.asyncio
    async def test_read_compose_and_env(self, temp_stacks_dir):
        """Should read both compose.yaml and .env"""
        stack_dir = temp_stacks_dir / "myapp"
        stack_dir.mkdir()
        (stack_dir / "compose.yaml").write_text("services:\n  web:\n    image: nginx")
        (stack_dir / ".env").write_text("PORT=8080\nDEBUG=true")

        compose, env = await read_stack("myapp")

        assert "nginx" in compose
        assert "PORT=8080" in env
        assert "DEBUG=true" in env

    @pytest.mark.asyncio
    async def test_read_nonexistent_raises(self, temp_stacks_dir):
        """Should raise FileNotFoundError for nonexistent stack"""
        with pytest.raises(FileNotFoundError, match="not found"):
            await read_stack("nonexistent")

    @pytest.mark.asyncio
    async def test_read_no_compose_raises(self, temp_stacks_dir):
        """Should raise FileNotFoundError if directory exists but no compose.yaml"""
        stack_dir = temp_stacks_dir / "empty"
        stack_dir.mkdir()

        with pytest.raises(FileNotFoundError, match="missing compose.yaml"):
            await read_stack("empty")


class TestWriteStack:
    """Test stack writing"""

    @pytest.mark.asyncio
    async def test_write_compose_only(self, temp_stacks_dir):
        """Should write compose.yaml"""
        await write_stack("myapp", "services:\n  web:\n    image: nginx")

        compose_path = temp_stacks_dir / "myapp" / "compose.yaml"
        assert compose_path.exists()
        assert "nginx" in compose_path.read_text()

    @pytest.mark.asyncio
    async def test_write_compose_and_env(self, temp_stacks_dir):
        """Should write both compose.yaml and .env"""
        await write_stack("myapp", "services: {}", env_content="PORT=8080")

        compose_path = temp_stacks_dir / "myapp" / "compose.yaml"
        env_path = temp_stacks_dir / "myapp" / ".env"

        assert compose_path.exists()
        assert env_path.exists()
        assert "PORT=8080" in env_path.read_text()

    @pytest.mark.asyncio
    async def test_write_removes_empty_env(self, temp_stacks_dir):
        """Should remove .env if content is empty/whitespace"""
        stack_dir = temp_stacks_dir / "myapp"
        stack_dir.mkdir()
        env_path = stack_dir / ".env"
        env_path.write_text("OLD=value")

        await write_stack("myapp", "services: {}", env_content="   ")

        assert not env_path.exists()

    @pytest.mark.asyncio
    async def test_write_creates_directory(self, temp_stacks_dir):
        """Should create stack directory if it doesn't exist"""
        await write_stack("newstack", "services: {}")

        stack_dir = temp_stacks_dir / "newstack"
        assert stack_dir.is_dir()

    @pytest.mark.asyncio
    async def test_write_overwrites_existing(self, temp_stacks_dir):
        """Should overwrite existing files"""
        await write_stack("myapp", "version: '1'")
        await write_stack("myapp", "version: '2'")

        compose_path = temp_stacks_dir / "myapp" / "compose.yaml"
        assert "version: '2'" in compose_path.read_text()

    @pytest.mark.asyncio
    async def test_write_create_only_success(self, temp_stacks_dir):
        """Should succeed with create_only if stack doesn't exist"""
        await write_stack("newstack", "services: {}", create_only=True)

        assert (temp_stacks_dir / "newstack" / "compose.yaml").exists()

    @pytest.mark.asyncio
    async def test_write_create_only_fails_if_exists(self, temp_stacks_dir):
        """Should fail with create_only if stack already exists"""
        await write_stack("myapp", "services: {}")

        with pytest.raises(ValueError, match="already exists"):
            await write_stack("myapp", "new content", create_only=True)

    @pytest.mark.asyncio
    async def test_write_validates_name(self, temp_stacks_dir):
        """Should reject invalid names"""
        with pytest.raises(ValueError, match="lowercase"):
            await write_stack("Invalid Name!", "services: {}")


class TestDeleteStackFiles:
    """Test stack deletion"""

    @pytest.mark.asyncio
    async def test_delete_existing(self, temp_stacks_dir):
        """Should delete existing stack directory"""
        stack_dir = temp_stacks_dir / "myapp"
        stack_dir.mkdir()
        (stack_dir / "compose.yaml").write_text("services: {}")
        (stack_dir / ".env").write_text("KEY=value")

        await delete_stack_files("myapp")

        assert not stack_dir.exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_no_error(self, temp_stacks_dir):
        """Should not raise error for nonexistent stack"""
        await delete_stack_files("nonexistent")  # Should not raise


class TestCopyStack:
    """Test stack copying"""

    @pytest.mark.asyncio
    async def test_copy_success(self, temp_stacks_dir):
        """Should copy stack to new name"""
        source_dir = temp_stacks_dir / "source"
        source_dir.mkdir()
        (source_dir / "compose.yaml").write_text("services: {}")
        (source_dir / ".env").write_text("KEY=value")

        await copy_stack("source", "dest")

        dest_dir = temp_stacks_dir / "dest"
        assert dest_dir.exists()
        assert (dest_dir / "compose.yaml").exists()
        assert (dest_dir / ".env").exists()

    @pytest.mark.asyncio
    async def test_copy_validates_dest_name(self, temp_stacks_dir):
        """Should validate destination name"""
        source_dir = temp_stacks_dir / "source"
        source_dir.mkdir()
        (source_dir / "compose.yaml").write_text("services: {}")

        with pytest.raises(ValueError, match="lowercase"):
            await copy_stack("source", "Invalid Name!")

    @pytest.mark.asyncio
    async def test_copy_fails_if_dest_exists(self, temp_stacks_dir):
        """Should fail if destination already exists"""
        for name in ["source", "dest"]:
            d = temp_stacks_dir / name
            d.mkdir()
            (d / "compose.yaml").write_text("services: {}")

        with pytest.raises(ValueError, match="already exists"):
            await copy_stack("source", "dest")

    @pytest.mark.asyncio
    async def test_copy_fails_if_source_missing(self, temp_stacks_dir):
        """Should fail if source doesn't exist"""
        with pytest.raises(FileNotFoundError, match="not found"):
            await copy_stack("nonexistent", "dest")


class TestRenameStackFiles:
    """Test stack renaming"""

    @pytest.mark.asyncio
    async def test_rename_success(self, temp_stacks_dir):
        """Should rename stack directory"""
        old_dir = temp_stacks_dir / "oldname"
        old_dir.mkdir()
        (old_dir / "compose.yaml").write_text("services: {}")

        await rename_stack_files("oldname", "newname")

        assert not old_dir.exists()
        assert (temp_stacks_dir / "newname").exists()
        assert (temp_stacks_dir / "newname" / "compose.yaml").exists()

    @pytest.mark.asyncio
    async def test_rename_validates_new_name(self, temp_stacks_dir):
        """Should validate new name"""
        old_dir = temp_stacks_dir / "oldname"
        old_dir.mkdir()
        (old_dir / "compose.yaml").write_text("services: {}")

        with pytest.raises(ValueError, match="lowercase"):
            await rename_stack_files("oldname", "Invalid Name!")

    @pytest.mark.asyncio
    async def test_rename_fails_if_new_exists(self, temp_stacks_dir):
        """Should fail if new name already exists"""
        for name in ["oldname", "newname"]:
            d = temp_stacks_dir / name
            d.mkdir()
            (d / "compose.yaml").write_text("services: {}")

        with pytest.raises(ValueError, match="already exists"):
            await rename_stack_files("oldname", "newname")

    @pytest.mark.asyncio
    async def test_rename_fails_if_old_missing(self, temp_stacks_dir):
        """Should fail if old name doesn't exist"""
        with pytest.raises(FileNotFoundError, match="not found"):
            await rename_stack_files("nonexistent", "newname")


class TestListStacks:
    """Test stack listing"""

    @pytest.mark.asyncio
    async def test_list_empty(self, temp_stacks_dir):
        """Should return empty list for empty directory"""
        stacks = await list_stacks()
        assert stacks == []

    @pytest.mark.asyncio
    async def test_list_multiple(self, temp_stacks_dir):
        """Should list all stacks with compose.yaml"""
        for name in ["nginx", "postgres", "redis"]:
            d = temp_stacks_dir / name
            d.mkdir()
            (d / "compose.yaml").write_text("services: {}")

        stacks = await list_stacks()

        assert stacks == ["nginx", "postgres", "redis"]  # Sorted

    @pytest.mark.asyncio
    async def test_list_excludes_no_compose(self, temp_stacks_dir):
        """Should exclude directories without compose.yaml"""
        valid_dir = temp_stacks_dir / "valid"
        valid_dir.mkdir()
        (valid_dir / "compose.yaml").write_text("services: {}")

        invalid_dir = temp_stacks_dir / "invalid"
        invalid_dir.mkdir()
        # No compose.yaml

        stacks = await list_stacks()

        assert stacks == ["valid"]

    @pytest.mark.asyncio
    async def test_list_excludes_files(self, temp_stacks_dir):
        """Should exclude regular files (only directories)"""
        (temp_stacks_dir / "somefile.txt").write_text("not a stack")

        stacks = await list_stacks()

        assert stacks == []
