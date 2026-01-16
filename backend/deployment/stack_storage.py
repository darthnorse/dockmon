"""
Filesystem storage for stacks.

Simple file I/O - no database interaction.

All public functions are async to avoid blocking the event loop on slow storage (NFS, etc.).
Uses asyncio.to_thread() for synchronous filesystem operations.

Git-backed stacks (v2.4.0+):
    Git-backed stacks store configuration in metadata.yaml instead of compose.yaml.
    The git section in metadata.yaml points to a cloned repository.
    See read_stack_metadata() and write_stack_metadata() for details.
"""
import asyncio
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import aiofiles
import yaml

logger = logging.getLogger(__name__)

STACKS_DIR = Path(os.environ.get('STACKS_DIR', '/app/data/stacks'))

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


async def stack_exists(name: str) -> bool:
    """
    Check if stack exists on filesystem.

    Async for NFS compatibility.

    Args:
        name: Stack name

    Returns:
        True if stack directory contains compose.yaml
    """
    def _check():
        try:
            path = get_stack_path(name)
            return (path / "compose.yaml").exists()
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
                if (d / "compose.yaml").exists():
                    return d.name
        return None

    return await asyncio.to_thread(_find)


async def read_stack(name: str) -> Tuple[str, Optional[str]]:
    """
    Read compose.yaml and .env for a stack.

    Args:
        name: Stack name

    Returns:
        Tuple of (compose_yaml, env_content or None)

    Raises:
        FileNotFoundError: If stack doesn't exist (missing compose.yaml)
    """
    stack_path = get_stack_path(name)
    compose_path = stack_path / "compose.yaml"
    env_path = stack_path / ".env"

    # Check existence async (for NFS compatibility)
    def _check_exists():
        return compose_path.exists(), env_path.exists()

    compose_exists, env_exists = await asyncio.to_thread(_check_exists)

    if not compose_exists:
        raise FileNotFoundError(f"Stack '{name}' not found (missing compose.yaml)")

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
        Sorted list of stack names (directories containing compose.yaml)
    """
    def _list():
        if not STACKS_DIR.exists():
            return []
        return sorted([
            d.name for d in STACKS_DIR.iterdir()
            if d.is_dir() and (d / "compose.yaml").exists()
        ])

    return await asyncio.to_thread(_list)


# =============================================================================
# Metadata support for git-backed stacks (v2.4.0+)
# =============================================================================

def _format_timestamp(dt: datetime) -> str:
    """
    Format datetime for YAML serialization with 'Z' suffix.

    Handles both naive and timezone-aware datetimes consistently.
    Always outputs ISO format with 'Z' suffix (UTC indicator).
    Non-UTC timezones are converted to UTC before formatting.
    """
    # If naive (no timezone), assume UTC and append Z
    if dt.tzinfo is None:
        return dt.isoformat() + 'Z'

    # Convert to UTC if not already
    utc_dt = dt.astimezone(timezone.utc)
    iso_str = utc_dt.isoformat()

    # Replace +00:00 with Z for cleaner output
    if iso_str.endswith('+00:00'):
        return iso_str[:-6] + 'Z'
    return iso_str


@dataclass
class StackMetadata:
    """
    Stack metadata from metadata.yaml.

    Git-backed stacks use metadata.yaml to store git configuration.
    Local stacks may also have metadata for description and timestamps.

    Example metadata.yaml for git-backed stack:
        name: my-app
        description: My application stack
        created_at: 2024-01-15T10:30:00Z
        updated_at: 2024-01-15T14:20:00Z
        git:
          repository_id: 1
          compose_path: stacks/my-app/docker-compose.yml
          env_file_path: stacks/my-app/.env
        env_overrides_encrypted: "gAAAAABhX3..."
    """
    name: str
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    git: Optional[Dict[str, Any]] = None
    env_overrides_encrypted: Optional[str] = None

    # Store raw metadata for any fields not in the dataclass
    _raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_git_backed(self) -> bool:
        """True if this stack is linked to a git repository."""
        return self.git is not None and 'repository_id' in self.git

    @property
    def repository_id(self) -> Optional[int]:
        """Git repository ID, or None if not git-backed."""
        if self.git:
            return self.git.get('repository_id')
        return None

    @property
    def compose_path(self) -> Optional[str]:
        """Path to compose file in git repo, or None if not git-backed."""
        if self.git:
            return self.git.get('compose_path')
        return None

    @property
    def env_file_path(self) -> Optional[str]:
        """Path to .env file in git repo, or None if not configured."""
        if self.git:
            return self.git.get('env_file_path')
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        data = {
            'name': self.name,
        }
        if self.description:
            data['description'] = self.description
        if self.created_at:
            data['created_at'] = _format_timestamp(self.created_at)
        if self.updated_at:
            data['updated_at'] = _format_timestamp(self.updated_at)
        if self.git:
            data['git'] = self.git
        if self.env_overrides_encrypted:
            data['env_overrides_encrypted'] = self.env_overrides_encrypted
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StackMetadata':
        """Create from dictionary (parsed YAML)."""
        # Parse datetime strings - preserve timezone info
        # 'Z' suffix means UTC, convert to proper timezone-aware datetime
        created_at = None
        updated_at = None
        if data.get('created_at'):
            try:
                dt_str = data['created_at']
                # Replace 'Z' with '+00:00' to create timezone-aware UTC datetime
                if dt_str.endswith('Z'):
                    dt_str = dt_str[:-1] + '+00:00'
                created_at = datetime.fromisoformat(dt_str)
            except (ValueError, AttributeError):
                pass
        if data.get('updated_at'):
            try:
                dt_str = data['updated_at']
                if dt_str.endswith('Z'):
                    dt_str = dt_str[:-1] + '+00:00'
                updated_at = datetime.fromisoformat(dt_str)
            except (ValueError, AttributeError):
                pass

        return cls(
            name=data.get('name', ''),
            description=data.get('description'),
            created_at=created_at,
            updated_at=updated_at,
            git=data.get('git'),
            env_overrides_encrypted=data.get('env_overrides_encrypted'),
            _raw=data,
        )


async def read_stack_metadata(name: str) -> Optional[StackMetadata]:
    """
    Read metadata.yaml for a stack.

    Args:
        name: Stack name

    Returns:
        StackMetadata instance, or None if metadata.yaml doesn't exist
    """
    stack_path = get_stack_path(name)
    metadata_path = stack_path / "metadata.yaml"

    def _read():
        if not metadata_path.exists():
            return None
        with open(metadata_path, 'r') as f:
            data = yaml.safe_load(f) or {}
        return StackMetadata.from_dict(data)

    return await asyncio.to_thread(_read)


async def write_stack_metadata(name: str, metadata: StackMetadata) -> None:
    """
    Write metadata.yaml for a stack.

    Creates the stack directory if it doesn't exist.
    Uses atomic write pattern for safety.

    Args:
        name: Stack name
        metadata: StackMetadata instance to write
    """
    validate_stack_name(name)
    stack_path = get_stack_path(name)
    metadata_path = stack_path / "metadata.yaml"

    # Ensure directory exists
    stack_path.mkdir(parents=True, exist_ok=True)

    # Update timestamps
    now = datetime.now(timezone.utc)
    if not metadata.created_at:
        metadata.created_at = now
    metadata.updated_at = now

    # Serialize to YAML
    data = metadata.to_dict()
    yaml_content = yaml.safe_dump(data, default_flow_style=False, sort_keys=False)

    # Atomic write
    await _atomic_write_file(metadata_path, yaml_content)
    logger.debug(f"Wrote metadata for stack '{name}'")


async def delete_stack_metadata(name: str) -> None:
    """
    Delete metadata.yaml for a stack (if exists).

    Args:
        name: Stack name
    """
    stack_path = get_stack_path(name)
    metadata_path = stack_path / "metadata.yaml"

    def _delete():
        if metadata_path.exists():
            metadata_path.unlink()
            logger.debug(f"Deleted metadata for stack '{name}'")

    await asyncio.to_thread(_delete)


def get_stacks_linked_to_repo_sync(repo_id: int) -> List[StackMetadata]:
    """
    Find all stacks linked to a git repository (synchronous).

    Scans all stack directories and reads metadata to find matches.
    This is synchronous for use in scheduler context.

    Args:
        repo_id: Git repository database ID

    Returns:
        List of StackMetadata objects for stacks with git.repository_id == repo_id
    """
    linked_stacks = []
    if not STACKS_DIR.exists():
        return linked_stacks

    for stack_dir in STACKS_DIR.iterdir():
        if not stack_dir.is_dir():
            continue

        metadata_path = stack_dir / "metadata.yaml"
        if not metadata_path.exists():
            continue

        try:
            with open(metadata_path, 'r') as f:
                data = yaml.safe_load(f) or {}

            git_config = data.get('git') or {}
            if git_config.get('repository_id') == repo_id:
                metadata = StackMetadata.from_dict(data)
                metadata.name = stack_dir.name  # Ensure name matches directory
                linked_stacks.append(metadata)
        except Exception as e:
            logger.warning(f"Failed to read metadata for stack {stack_dir.name}: {e}")
            continue

    return linked_stacks


async def get_stacks_linked_to_repo(repo_id: int) -> List[StackMetadata]:
    """
    Find all stacks linked to a git repository (async).

    Args:
        repo_id: Git repository database ID

    Returns:
        List of StackMetadata objects for stacks with git.repository_id == repo_id
    """
    return await asyncio.to_thread(get_stacks_linked_to_repo_sync, repo_id)


def get_all_linked_stack_counts_sync() -> Dict[int, int]:
    """
    Get count of linked stacks for all repositories in a single scan.

    This avoids N+1 queries when listing repositories - scans all stack
    directories once and returns a dict mapping repo_id -> stack count.

    Returns:
        Dict mapping repository ID to number of linked stacks
    """
    counts: Dict[int, int] = defaultdict(int)
    if not STACKS_DIR.exists():
        return counts

    for stack_dir in STACKS_DIR.iterdir():
        if not stack_dir.is_dir():
            continue

        metadata_path = stack_dir / "metadata.yaml"
        if not metadata_path.exists():
            continue

        try:
            with open(metadata_path, 'r') as f:
                data = yaml.safe_load(f) or {}

            git_config = data.get('git') or {}
            repo_id = git_config.get('repository_id')
            if repo_id is not None:
                counts[repo_id] += 1
        except Exception as e:
            logger.warning(f"Failed to read metadata for stack {stack_dir.name}: {e}")
            continue

    return counts


async def get_all_linked_stack_counts() -> Dict[int, int]:
    """
    Get count of linked stacks for all repositories in a single scan (async).

    Returns:
        Dict mapping repository ID to number of linked stacks
    """
    return await asyncio.to_thread(get_all_linked_stack_counts_sync)
