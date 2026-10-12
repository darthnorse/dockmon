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
import yaml

from utils.env_files import (
    is_safe_env_filename,
    normalize_env_filename,
    parse_env_file_refs,
    MAX_ENV_FILE_BYTES,
)

from utils.stack_files import (  # noqa: F401 - re-exported; these lived here before the backup split
    COMPOSE_FILENAMES,
    STACKS_DIR,
    VALID_NAME_PATTERN,
    _discovered_env_filenames,
    _managed_env_filenames,
    find_compose_file,
    referenced_env_filenames,
    validate_stack_name,
)

logger = logging.getLogger(__name__)

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


async def read_stack(name: str, include_discovered: bool = True) -> Tuple[str, Dict[str, str]]:
    """
    Read a stack's compose file and its managed env files.

    The env-file set is: the conventional '.env' (if present on disk) plus every
    same-dir bare filename named by an env_file: directive (referenced-but-missing
    files read as ''). When include_discovered is True (the default, for the
    editor) it ALSO surfaces env-named files on disk that the compose does NOT
    reference -- the inactive files of an env-swap workflow -- filtered to exclude
    bind-mount data, symlinks, and oversized files.

    Deploy callers MUST pass include_discovered=False so an inactive, unreferenced
    env file (e.g. .env.staging) is never shipped to the compose service / remote
    agent and never trips the old-agent multi_env_files gate. Bind-mount runtime
    data and the compose file are excluded either way.

    Args:
        name: Stack name.
        include_discovered: Include naming-discovered unreferenced env files
            (editor view). Deploy paths pass False for referenced-only content.

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

        # Discovered: env-named files on disk not referenced by the compose
        # (e.g. the inactive files in an env-swap workflow). Editor view only --
        # deploy callers pass include_discovered=False so these never reach the
        # compose service / agent. The discovery set already filtered
        # symlinks/size/bind-mounts; re-check symlink, regular-file, and size at
        # read time so a scan->read swap can't make us follow a symlink, block on
        # a fifo, or slurp an oversized file (mirrors the env_file: loop above).
        if include_discovered:
            for fname in _discovered_env_filenames(stack_path, compose_yaml):
                if fname in env_files:
                    continue
                fpath = stack_path / fname
                if fpath.is_symlink():
                    continue
                try:
                    if not fpath.is_file() or fpath.stat().st_size > MAX_ENV_FILE_BYTES:
                        continue
                except OSError:
                    continue
                env_files[fname] = fpath.read_text()

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


def _format_compose_yaml_error(exc: yaml.YAMLError, compose_yaml: str) -> str:
    """Turn a PyYAML error into an actionable message, with a dedicated hint for
    invisible tab characters."""
    mark = getattr(exc, "problem_mark", None)
    problem = (getattr(exc, "problem", None) or "").strip()
    if mark is None:
        return f"Invalid compose YAML: {problem or str(exc).strip()}"

    line_no, col_no = mark.line + 1, mark.column + 1
    lines = compose_yaml.splitlines()
    source_line = lines[mark.line] if 0 <= mark.line < len(lines) else ""
    if "\t" in source_line or "\\t" in problem:
        return (
            f"Compose file has a tab character at line {line_no}, column {col_no}. "
            "YAML uses spaces, not tabs, for indentation — replace the tab with spaces."
        )
    return (
        f"Invalid compose YAML at line {line_no}: {problem}"
        if problem
        else f"Invalid compose YAML at line {line_no}."
    )


def validate_compose_syntax(compose_yaml: str) -> None:
    """Raise ValueError with a user-friendly message if compose_yaml is not
    parseable YAML.

    Syntax-only gate (empty content allowed); semantic checks stay at deploy time.
    """
    if not compose_yaml or not compose_yaml.strip():
        return
    try:
        yaml.safe_load(compose_yaml)
    except yaml.YAMLError as exc:
        raise ValueError(_format_compose_yaml_error(exc, compose_yaml)) from exc
    except RecursionError as exc:
        # PyYAML raises RecursionError (not YAMLError) on deeply-nested input.
        raise ValueError("Compose file is nested too deeply.") from exc


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
        ValueError: If the stack name or any env filename is invalid, the
            compose YAML is malformed, or (with create_only) the stack already
            exists.
    """
    validate_stack_name(name)
    # Offload the parse: a near-1MB compose can stall the event loop.
    await asyncio.to_thread(validate_compose_syntax, compose_yaml)
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

    Only removes a file in the stack's managed env-file set: the conventional
    '.env', the bare same-dir filenames referenced by env_file: directives, and
    env-named files discovered on disk (the inactive files of an env-swap
    workflow). Never removes the compose file, a compose-declared bind-mount
    source, a non-env-named file, a directory, or a symlink target. Returns True
    iff a regular managed env file was removed. Raises ValueError on an unsafe
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
        if bare not in _managed_env_filenames(stack_path, compose_path.read_text()):
            # Not a managed env file: the compose file, a bind-mount source, a
            # directory/symlink, or any same-dir file that is not '.env',
            # env_file:-referenced, or an env-named discovered file.
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
