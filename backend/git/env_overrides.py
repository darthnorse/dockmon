"""
Environment variable overrides encryption for git-backed stacks (v2.4.0+).

Git-backed stacks store environment variable overrides as an encrypted JSON blob
in metadata.yaml. This protects secrets from being visible in plaintext.

Merge order (later wins):
1. .env file from git repository (if configured)
2. Environment variable overrides from DockMon UI (this module)
"""
import json
import logging
import re
from typing import Dict, List, Optional, Tuple

from utils.encryption import encrypt_password, decrypt_password

logger = logging.getLogger(__name__)

# Public API
__all__ = [
    'get_env_overrides',
    'set_env_overrides',
    'merge_env_content',
    'validate_env_var_name',
    'validate_env_var_value',
    'validate_env_vars',
]

# Valid env var name: starts with letter or underscore, contains only alphanumeric and underscore
# This matches POSIX standard for environment variable names
ENV_VAR_NAME_PATTERN = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

# Characters that are dangerous in env var values when written to .env files
# Newlines allow injection of additional variables
ENV_VAR_VALUE_FORBIDDEN = re.compile(r'[\r\n]')


def validate_env_var_value(value: str) -> bool:
    """
    Validate environment variable value is safe for .env files.

    Prevents injection attacks by blocking values containing:
    - Newlines (\\n, \\r) - could inject additional env vars

    Args:
        value: Environment variable value to validate

    Returns:
        True if value is safe, False otherwise
    """
    if not isinstance(value, str):
        return False
    return not bool(ENV_VAR_VALUE_FORBIDDEN.search(value))


def validate_env_var_name(name: str) -> bool:
    """
    Validate environment variable name is safe.

    Prevents injection attacks when env vars are written to .env files.
    Names must:
    - Start with letter or underscore
    - Contain only alphanumeric characters and underscores
    - Not contain =, newlines, or other special characters

    Args:
        name: Environment variable name to validate

    Returns:
        True if name is valid, False otherwise
    """
    if not name:
        return False
    return bool(ENV_VAR_NAME_PATTERN.match(name))


def validate_env_vars(env_vars: Dict[str, str]) -> Tuple[bool, List[str], List[str]]:
    """
    Validate all environment variable names and values in a dictionary.

    Args:
        env_vars: Dictionary of environment variables

    Returns:
        Tuple of (all_valid, list_of_invalid_names, list_of_invalid_value_keys)
    """
    invalid_names = [name for name in env_vars.keys() if not validate_env_var_name(name)]
    invalid_values = [name for name, value in env_vars.items() if not validate_env_var_value(value)]
    all_valid = len(invalid_names) == 0 and len(invalid_values) == 0
    return all_valid, invalid_names, invalid_values


def get_env_overrides(stack_metadata: dict) -> Dict[str, str]:
    """
    Decrypt env overrides from stack metadata.

    Args:
        stack_metadata: Stack metadata dict containing env_overrides_encrypted

    Returns:
        Dictionary of environment variable overrides, or empty dict if none
        or if decryption fails (encryption key inaccessible, corrupted data, etc.)
    """
    encrypted = stack_metadata.get('env_overrides_encrypted')
    if not encrypted:
        return {}

    try:
        decrypted_json = decrypt_password(encrypted)
        return json.loads(decrypted_json)
    except (ValueError, json.JSONDecodeError, IOError) as e:
        logger.error(f"Failed to decrypt env overrides: {e}")
        return {}


def set_env_overrides(stack_metadata: dict, env_vars: Dict[str, str]) -> None:
    """
    Encrypt and save env overrides to stack metadata.

    Modifies the stack_metadata dict in place.

    Args:
        stack_metadata: Stack metadata dict to modify
        env_vars: Dictionary of environment variables to encrypt and store

    Raises:
        ValueError: If any environment variable name or value is invalid
        IOError: If encryption key cannot be loaded or created
    """
    if env_vars:
        # Validate all env var names and values to prevent injection
        valid, invalid_names, invalid_values = validate_env_vars(env_vars)
        if invalid_names:
            raise ValueError(
                f"Invalid environment variable names: {', '.join(invalid_names)}. "
                "Names must start with a letter or underscore and contain only "
                "alphanumeric characters and underscores."
            )
        if invalid_values:
            raise ValueError(
                f"Invalid environment variable values for: {', '.join(invalid_values)}. "
                "Values cannot contain newlines or carriage returns."
            )

        # Sort keys for consistent encryption output
        json_blob = json.dumps(env_vars, sort_keys=True)
        stack_metadata['env_overrides_encrypted'] = encrypt_password(json_blob)
    else:
        # Remove the key if no overrides
        stack_metadata.pop('env_overrides_encrypted', None)


def merge_env_content(
    git_env_content: Optional[str],
    env_overrides: Dict[str, str]
) -> str:
    """
    Merge git .env file content with DockMon env overrides.

    DockMon overrides take precedence (appended at the end).

    Args:
        git_env_content: Content of .env file from git repo, or None
        env_overrides: Dictionary of env overrides from DockMon UI

    Returns:
        Merged .env file content as a string
    """
    lines = []

    # 1. Add git .env content if present
    if git_env_content:
        lines.append(git_env_content.rstrip())

    # 2. Append DockMon overrides (these take precedence - last wins)
    if env_overrides:
        if lines:
            lines.append('')  # Blank line separator
            lines.append('# DockMon environment overrides')
        override_lines = [f"{k}={v}" for k, v in sorted(env_overrides.items())]
        lines.extend(override_lines)

    return '\n'.join(lines)
