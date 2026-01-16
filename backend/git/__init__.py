"""
Git operations module for git-backed stacks (v2.4.0+).

This module provides:
- GitService: Core git operations (clone, pull, read files)
- SyncResult: Result dataclass for sync operations
- get_git_service(): Singleton accessor
- Environment override utilities for encrypted env var storage
"""
from git.git_service import (
    GitService,
    GitNotAvailableError,
    SyncResult,
    get_git_service,
    GIT_REPOS_DIR,
)
from git.env_overrides import (
    get_env_overrides,
    set_env_overrides,
    merge_env_content,
    validate_env_var_name,
    validate_env_var_value,
    validate_env_vars,
)

__all__ = [
    # git_service exports
    'GitService',
    'GitNotAvailableError',
    'SyncResult',
    'get_git_service',
    'GIT_REPOS_DIR',
    # env_overrides exports
    'get_env_overrides',
    'set_env_overrides',
    'merge_env_content',
    'validate_env_var_name',
    'validate_env_var_value',
    'validate_env_vars',
]
