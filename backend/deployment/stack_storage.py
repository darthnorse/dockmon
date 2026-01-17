"""
Filesystem storage for stacks.

Simple file I/O - no database interaction.

All public functions are async to avoid blocking the event loop on slow storage (NFS, etc.).
Uses asyncio.to_thread() for synchronous filesystem operations.
"""
import asyncio
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

import aiofiles

logger = logging.getLogger(__name__)

STACKS_DIR = Path(os.environ.get('STACKS_DIR', '/app/data/stacks'))

# Valid compose filenames (in priority order)
# We write as compose.yaml but read any of these for compatibility
COMPOSE_FILENAMES = ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")

# Valid stack name pattern: lowercase alphanumeric, hyphens, underscores
# Must start with alphanumeric
VALID_NAME_PATTERN = re.compile(r'^[a-z0-9][a-z0-9_-]*$')


def validate_stack_name(name: str) -> None:
    """
    Validate stack name is filesystem-safe.

    Args:
        name: Stack name to validate

    Raises:
        ValueError: If name is invalid
    """
    if not name or len(name) > 100:
        raise ValueError("Stack name must be 1-100 characters")
    if not VALID_NAME_PATTERN.match(name):
        raise ValueError(
            "Stack name must be lowercase alphanumeric, hyphens, underscores, "
            "and start with a letter or number"
        )


def sanitize_stack_name(name: str) -> str:
    """
    Convert name to filesystem-safe format.

    Used during migration to convert existing deployment names.

    Args:
        name: Original name (may contain spaces, special chars)

    Returns:
        Sanitized name safe for filesystem use
    """
    # Lowercase
    safe = name.lower()
    # Replace spaces and special chars with hyphens
    safe = re.sub(r'[^a-z0-9_-]', '-', safe)
    # Remove consecutive hyphens
    safe = re.sub(r'-+', '-', safe)
    # Remove leading/trailing hyphens
    safe = safe.strip('-')
    # Ensure it starts with alphanumeric
    if safe and not safe[0].isalnum():
        safe = 'stack-' + safe
    return safe or 'unnamed-stack'


def get_unique_stack_name(base_name: str, existing_names: set) -> str:
    """
    Get unique name by appending number if needed.

    Args:
        base_name: Desired base name
        existing_names: Set of names already in use

    Returns:
        Unique name (base_name or base_name-N)
    """
    name = base_name
    counter = 1
    while name in existing_names:
        name = f"{base_name}-{counter}"
        counter += 1
    return name


def validate_path_safety(path: Path) -> None:
    """
    Ensure path is within STACKS_DIR and not a symlink escape.

    Prevents path traversal attacks like "../../../etc/passwd".
    Also rejects symlinks to prevent TOCTOU race conditions.

    Args:
        path: Path to validate

    Raises:
        ValueError: If path escapes stacks directory or is a symlink
    """
    # Reject symlinks to prevent TOCTOU race conditions
    # An attacker could replace a stack directory with a symlink between validation and file operation
    if path.is_symlink():
        raise ValueError("Symlinks not allowed in stacks directory")

    resolved = path.resolve()
    stacks_resolved = STACKS_DIR.resolve()
    if not str(resolved).startswith(str(stacks_resolved) + os.sep) and resolved != stacks_resolved:
        raise ValueError("Path escapes stacks directory")


def get_stack_path(name: str) -> Path:
    """
    Get directory path for a stack.

    Args:
        name: Stack name

    Returns:
        Path to stack directory

    Raises:
        ValueError: If path would escape stacks directory
    """
    path = STACKS_DIR / name
    validate_path_safety(path)
    return path


def find_compose_file(stack_path: Path) -> Optional[Path]:
    """
    Find compose file in stack directory.

    Checks for compose.yaml, compose.yml, docker-compose.yaml, docker-compose.yml
    in priority order.

    Args:
        stack_path: Path to stack directory

    Returns:
        Path to compose file if found, None otherwise
    """
    for filename in COMPOSE_FILENAMES:
        compose_path = stack_path / filename
        if compose_path.exists():
            return compose_path
    return None


async def stack_exists(name: str) -> bool:
    """
    Check if stack exists on filesystem.

    Async for NFS compatibility.

    Args:
        name: Stack name

    Returns:
        True if stack directory contains a compose file
    """
    def _check():
        try:
            path = get_stack_path(name)
            return find_compose_file(path) is not None
        except ValueError:
            return False

    return await asyncio.to_thread(_check)


async def find_stack_by_name(name: str) -> Optional[str]:
    """
    Find actual stack name on filesystem (case-insensitive match).

    Used when importing with "use existing stack" to get the exact
    filesystem name rather than a sanitized version.

    Args:
        name: Stack name to search for (case-insensitive)

    Returns:
        Actual stack name from filesystem, or None if not found
    """
    def _find():
        if not STACKS_DIR.exists():
            return None

        name_lower = name.lower()
        for d in STACKS_DIR.iterdir():
            if d.is_dir() and d.name.lower() == name_lower:
                if find_compose_file(d) is not None:
                    return d.name
        return None

    return await asyncio.to_thread(_find)


async def read_stack(name: str) -> Tuple[str, Optional[str]]:
    """
    Read compose file and .env for a stack.

    Supports compose.yaml, compose.yml, docker-compose.yaml, docker-compose.yml.

    Args:
        name: Stack name

    Returns:
        Tuple of (compose_yaml, env_content or None)

    Raises:
        FileNotFoundError: If stack doesn't exist (no compose file found)
    """
    stack_path = get_stack_path(name)
    env_path = stack_path / ".env"

    # Check existence async (for NFS compatibility)
    def _find_files():
        compose_path = find_compose_file(stack_path)
        env_exists = env_path.exists()
        return compose_path, env_exists

    compose_path, env_exists = await asyncio.to_thread(_find_files)

    if compose_path is None:
        raise FileNotFoundError(f"Stack '{name}' not found (no compose file)")

    async with aiofiles.open(compose_path, 'r') as f:
        compose_yaml = await f.read()

    env_content = None
    if env_exists:
        async with aiofiles.open(env_path, 'r') as f:
            env_content = await f.read()

    return compose_yaml, env_content


async def _atomic_write_file(target_path: Path, content: str) -> None:
    """Write content atomically using temp file + rename pattern."""
    fd, temp_path = tempfile.mkstemp(dir=target_path.parent, suffix='.tmp')
    try:
        async with aiofiles.open(fd, 'w', closefd=True) as f:
            await f.write(content)
        # Use asyncio.to_thread to avoid blocking on slow filesystems (NFS)
        await asyncio.to_thread(Path(temp_path).rename, target_path)
    except Exception:
        await asyncio.to_thread(Path(temp_path).unlink, True)  # missing_ok=True
        raise


async def write_stack(
    name: str,
    compose_yaml: str,
    env_content: Optional[str] = None,
    create_only: bool = False
) -> None:
    """
    Write compose.yaml and .env for a stack.

    Creates directory if needed. Uses atomic write pattern.

    Args:
        name: Stack name (validated)
        compose_yaml: Compose file content
        env_content: Optional .env file content
        create_only: If True, fail if stack already exists (race-safe creation)

    Raises:
        ValueError: If name is invalid or stack exists (when create_only=True)
    """
    validate_stack_name(name)
    stack_path = get_stack_path(name)

    # For create_only, use atomic directory creation to prevent race conditions
    if create_only:
        try:
            stack_path.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            raise ValueError(f"Stack '{name}' already exists")
    else:
        stack_path.mkdir(parents=True, exist_ok=True)

    # Write compose.yaml atomically
    await _atomic_write_file(stack_path / "compose.yaml", compose_yaml)

    # Handle .env file
    env_path = stack_path / ".env"
    if env_content and env_content.strip():
        await _atomic_write_file(env_path, env_content)
    else:
        # Remove .env if it exists and new content is empty
        def _remove_env_if_exists():
            if env_path.exists():
                env_path.unlink()
        await asyncio.to_thread(_remove_env_if_exists)

    logger.debug(f"Wrote stack '{name}' to {stack_path}")


async def delete_stack_files(name: str) -> None:
    """
    Delete stack directory and all contents.

    Does NOT check for deployments - caller must verify no deployments exist.

    Args:
        name: Stack name
    """
    stack_path = get_stack_path(name)

    def _delete():
        if stack_path.exists():
            shutil.rmtree(stack_path)
            logger.info(f"Deleted stack '{name}' from {stack_path}")

    await asyncio.to_thread(_delete)


async def copy_stack(source_name: str, dest_name: str) -> None:
    """
    Copy a stack to a new name.

    Args:
        source_name: Source stack name
        dest_name: Destination stack name

    Raises:
        ValueError: If dest_name is invalid or already exists
        FileNotFoundError: If source doesn't exist
    """
    validate_stack_name(dest_name)
    source_path = get_stack_path(source_name)
    dest_path = get_stack_path(dest_name)

    def _copy():
        if not source_path.exists():
            raise FileNotFoundError(f"Source stack '{source_name}' not found")
        if dest_path.exists():
            raise ValueError(f"Stack '{dest_name}' already exists")
        shutil.copytree(source_path, dest_path, symlinks=False)
        logger.info(f"Copied stack '{source_name}' to '{dest_name}'")

    await asyncio.to_thread(_copy)


async def rename_stack_files(old_name: str, new_name: str) -> None:
    """
    Rename a stack directory.

    Does NOT update deployment records - caller must handle that.

    Args:
        old_name: Current stack name
        new_name: New stack name

    Raises:
        ValueError: If new_name is invalid or already exists
        FileNotFoundError: If old_name doesn't exist
    """
    validate_stack_name(new_name)
    old_path = get_stack_path(old_name)
    new_path = get_stack_path(new_name)

    def _rename():
        if not old_path.exists():
            raise FileNotFoundError(f"Stack '{old_name}' not found")
        if new_path.exists():
            raise ValueError(f"Stack '{new_name}' already exists")
        old_path.rename(new_path)
        logger.info(f"Renamed stack '{old_name}' to '{new_name}'")

    await asyncio.to_thread(_rename)


async def list_stacks() -> List[str]:
    """
    List all stack names on filesystem.

    Async for NFS compatibility.

    Returns:
        Sorted list of stack names (directories containing a compose file)
    """
    def _list():
        if not STACKS_DIR.exists():
            return []
        return sorted([
            d.name for d in STACKS_DIR.iterdir()
            if d.is_dir() and find_compose_file(d) is not None
        ])

    return await asyncio.to_thread(_list)
