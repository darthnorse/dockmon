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
from typing import Dict, List, Optional, Tuple

import aiofiles

from utils.env_files import is_safe_env_filename, normalize_env_filename, parse_env_file_refs

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


def _managed_env_filenames(compose_yaml: str) -> set:
    """The set of env filenames a stack manages, derived from its compose.

    The conventional '.env' plus every same-dir bare filename named by an
    env_file: directive. This is the authoritative allowlist for which files
    delete_env_file may remove, and it is kept in lockstep with what read_stack
    surfaces as env tabs. Deriving it from the compose (not directory
    enumeration) is what keeps the delete path from ever removing the compose
    file, bind-mount data, or any other non-env file in the stack directory.
    """
    captured, _skipped = parse_env_file_refs(compose_yaml)
    return {".env", *captured}


async def read_stack(name: str) -> Tuple[str, Dict[str, str]]:
    """
    Read a stack's compose file and its managed env files.

    The env-file set is derived from the compose (not the directory): the
    conventional '.env' (if present) plus every same-dir bare filename named by
    an env_file: directive. Referenced-but-missing files read as ''. This keeps
    bind-mount runtime data in the stack dir invisible.

    Returns:
        (compose_yaml, env_files) where env_files maps filename -> content.

    Raises:
        FileNotFoundError: If no compose file exists for the stack.
    """
    stack_path = get_stack_path(name)

    def _read() -> Tuple[str, Dict[str, str]]:
        compose_path = find_compose_file(stack_path)
        if compose_path is None:
            raise FileNotFoundError(f"Stack '{name}' not found (no compose file)")
        compose_yaml = compose_path.read_text()

        env_files: Dict[str, str] = {}
        dot_env = stack_path / ".env"
        if dot_env.is_file() and not dot_env.is_symlink():
            env_files[".env"] = dot_env.read_text()

        captured, _skipped = parse_env_file_refs(compose_yaml)
        for fname in captured:
            if not is_safe_env_filename(fname):
                continue
            if fname in env_files:
                continue
            fpath = stack_path / fname
            if fpath.is_symlink():
                continue
            env_files[fname] = fpath.read_text() if fpath.is_file() else ""

        return compose_yaml, env_files

    return await asyncio.to_thread(_read)


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
    env_files: Optional[Dict[str, str]] = None,
    create_only: bool = False,
) -> None:
    """
    Write a stack's compose file and its env files.

    Writes ONLY compose.yaml and the provided env files (creating or
    overwriting them). Never deletes or touches any other file in the stack
    directory, protecting relative bind-mount data and leaving unreferenced
    env files as harmless, invisible orphans.

    Raises:
        ValueError: If the stack name or any env filename is invalid, or (with
            create_only) the stack already exists.
    """
    validate_stack_name(name)
    env_files = env_files or {}
    for fname in env_files:
        if not is_safe_env_filename(fname):
            raise ValueError(f"Unsafe env filename: {fname!r}")

    stack_path = get_stack_path(name)
    if create_only:
        try:
            stack_path.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            raise ValueError(f"Stack '{name}' already exists")
    else:
        stack_path.mkdir(parents=True, exist_ok=True)

    await _atomic_write_file(stack_path / "compose.yaml", compose_yaml)
    for fname, content in env_files.items():
        bare = normalize_env_filename(fname)
        await _atomic_write_file(stack_path / bare, content)

    logger.debug(f"Wrote stack '{name}' ({len(env_files)} env file(s)) to {stack_path}")


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


async def delete_env_file(name: str, filename: str) -> bool:
    """Delete a single managed env file from a stack dir.

    Only removes a file in the stack's managed env-file set (the conventional
    '.env' plus the bare same-dir filenames referenced by env_file: directives
    in the compose). Never removes the compose file, bind-mount data, an
    unreferenced file, a directory, or a symlink target. Returns True iff a
    regular managed env file was removed. Raises ValueError on an unsafe
    filename.

    Args:
        name: Stack name
        filename: Env filename to delete (e.g. '.env', '.db.env', './app.env')

    Returns:
        True if a regular managed env file was deleted, False otherwise

    Raises:
        ValueError: If stack name is invalid or filename is unsafe
    """
    validate_stack_name(name)
    if not is_safe_env_filename(filename):
        raise ValueError(f"Unsafe env filename: {filename!r}")
    bare = normalize_env_filename(filename)
    stack_path = get_stack_path(name)
    target = stack_path / bare

    def _delete() -> bool:
        compose_path = find_compose_file(stack_path)
        if compose_path is None:
            return False  # no compose -> nothing managed to delete
        if bare not in _managed_env_filenames(compose_path.read_text()):
            # Not a managed env file: the compose file itself, bind-mount data,
            # or any same-dir file not named '.env'/referenced by env_file:.
            return False
        if target.parent != stack_path:       # containment, defense in depth
            return False
        if target.is_symlink() or target.is_dir():
            return False
        if not target.is_file():
            return False
        target.unlink()
        logger.info(f"Deleted env file '{bare}' from stack '{name}'")
        return True

    return await asyncio.to_thread(_delete)


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
