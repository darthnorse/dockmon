"""Stack-file rules shared by stack storage and backup.

Kept free of application imports: backup restore runs before database
migrations, when importing the app (and its database manager) is unsafe.
"""
import os
import re
from pathlib import Path
from typing import List, Optional

from utils.env_files import (
    MAX_ENV_FILE_BYTES,
    is_env_filename,
    is_safe_env_filename,
    parse_bind_mount_sources,
    parse_env_file_refs,
)

STACKS_DIR = Path(os.environ.get('STACKS_DIR', '/app/data/stacks'))

# Valid compose filenames (in priority order)
# We write as compose.yaml but read any of these for compatibility
COMPOSE_FILENAMES = ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")

# Larger compose files are backed up without scanning them for env_file references
MAX_COMPOSE_SCAN_BYTES = 16 * 1024 * 1024

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


def referenced_env_filenames(compose_yaml: str) -> set:
    """Env filenames the compose references: '.env' plus every same-dir bare
    filename named by an env_file: directive, minus any compose filename.

    Purely compose-derived (no directory access). This is the authoritative
    'active' set: '.env' (auto-loaded by compose) and the env_file: targets.
    The route returns it so the editor can badge tabs that are NOT in it.
    """
    captured, _skipped = parse_env_file_refs(compose_yaml)
    return {".env", *captured} - set(COMPOSE_FILENAMES)


def _discovered_env_filenames(stack_path: Path, compose_yaml: str) -> set:
    """On-disk env files NOT currently referenced by the compose.

    Top-level bare files in the stack dir whose name follows an env naming
    convention (is_env_filename) and that are not: already in the
    compose-referenced set, a compose file, a compose-declared bind-mount
    source, a symlink, a non-regular file, or larger than MAX_ENV_FILE_BYTES.

    This is what lets an env-swap workflow (.env.dev / .env.staging /
    .env.prod) keep editing the files that aren't the currently-referenced one,
    without surfacing bind-mount runtime data (which lives in subdirs, is
    declared in volumes:, or isn't env-named).
    """
    referenced = referenced_env_filenames(compose_yaml)
    bind_sources = parse_bind_mount_sources(compose_yaml)
    discovered: set = set()
    try:
        entries = list(os.scandir(stack_path))
    except OSError:
        return discovered
    for entry in entries:
        name = entry.name
        if name in referenced or name in COMPOSE_FILENAMES or name in bind_sources:
            continue
        if not is_env_filename(name) or not is_safe_env_filename(name):
            continue
        try:
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                continue
            if entry.stat(follow_symlinks=False).st_size > MAX_ENV_FILE_BYTES:
                continue
        except OSError:
            continue
        discovered.add(name)
    return discovered


def _managed_env_filenames(stack_path: Path, compose_yaml: str) -> set:
    """The delete allowlist: the compose-referenced set UNION naming-discovered
    unreferenced files on disk.

    A superset of read_stack's editor-tab set (every deletable file is one the
    editor can surface), kept in lockstep with it because both are derived from
    the same referenced_env_filenames / _discovered_env_filenames helpers — they
    cannot silently drift. The referenced half is compose-derived (never
    directory enumeration), so the delete path can never remove the compose file
    or bind-mount data; the discovered half is bounded by the is_env_filename +
    bind-mount + same-dir + symlink + size filters in _discovered_env_filenames.
    """
    return referenced_env_filenames(compose_yaml) | _discovered_env_filenames(stack_path, compose_yaml)


def managed_stack_files(stack_path: Path) -> List[Path]:
    """The files DockMon owns in a stack directory: its compose file plus the
    managed env files, regular files only. Everything else there (bind-mount
    data, notes, symlinks) belongs to the containers or the user.
    """
    compose = find_compose_file(stack_path)
    if compose is None or compose.is_symlink() or not compose.is_file():
        return []
    files = [compose]
    if compose.stat().st_size > MAX_COMPOSE_SCAN_BYTES:
        return files
    compose_yaml = compose.read_text(errors="replace")
    for name in sorted(_managed_env_filenames(stack_path, compose_yaml)):
        path = stack_path / name
        if not path.is_symlink() and path.is_file():
            files.append(path)
    return files
