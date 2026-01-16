"""
Git Models for DockMon API Endpoints (v2.4.0+)

Pydantic models for Git credentials and repositories.
Follows DockMon patterns:
- Request models for validation
- Response models with sanitized output (no secrets)
- Field validators for security

Security:
    - Request models accept sensitive data (password, ssh_private_key)
    - Response models NEVER expose secrets, only has_* boolean flags
    - URL validation prevents injection
    - Name validation prevents XSS
"""

import re
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# Shared Validation Helpers
# =============================================================================

_VALID_URL_PREFIXES = ('https://', 'http://', 'git@', 'ssh://')
_DANGEROUS_URL_CHARS = (';', '|', '&', '$', '`', '\n', '\r')


def _validate_name(v: Optional[str], required: bool = True) -> Optional[str]:
    """Validate name field for XSS prevention."""
    if v is None:
        return None
    if not v.strip():
        if required:
            raise ValueError('Name cannot be empty')
        return None
    v = v.strip()
    sanitized = re.sub(r'[<>"\']', '', v)
    if len(sanitized) != len(v):
        raise ValueError('Name contains invalid characters')
    return sanitized


def _validate_ssh_key(v: Optional[str]) -> Optional[str]:
    """Validate SSH private key format (PEM)."""
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if not v.startswith('-----BEGIN') or '-----END' not in v:
        raise ValueError('SSH private key must be in PEM format')
    return v


def _validate_url(v: Optional[str], required: bool = True) -> Optional[str]:
    """Validate git repository URL."""
    if v is None:
        return None
    if not v.strip():
        if required:
            raise ValueError('Repository URL cannot be empty')
        return None
    v = v.strip()
    if not any(v.startswith(prefix) for prefix in _VALID_URL_PREFIXES):
        raise ValueError('Repository URL must start with https://, http://, git@, or ssh://')
    if ' ' in v:
        raise ValueError('Repository URL cannot contain spaces')
    if any(c in v for c in _DANGEROUS_URL_CHARS):
        raise ValueError('Repository URL contains invalid characters')
    return v


def _validate_branch(v: Optional[str], required: bool = True) -> Optional[str]:
    """Validate git branch name."""
    if v is None:
        return None
    if not v.strip():
        if required:
            raise ValueError('Branch name cannot be empty')
        return None
    v = v.strip()
    if v.startswith('-') or v.startswith('.'):
        raise ValueError('Branch name cannot start with - or .')
    if '..' in v:
        raise ValueError('Branch name cannot contain ..')
    if v.endswith('.lock'):
        raise ValueError('Branch name cannot end with .lock')
    if not re.match(r'^[a-zA-Z0-9/_.-]+$', v):
        raise ValueError('Branch name contains invalid characters')
    return v


def _validate_cron(v: Optional[str], required: bool = True) -> Optional[str]:
    """Validate cron expression (5 fields)."""
    if v is None:
        return None
    if not v.strip():
        if required:
            raise ValueError('Cron expression cannot be empty')
        return None
    v = v.strip()
    parts = v.split()
    if len(parts) != 5:
        raise ValueError('Cron expression must have 5 fields (minute hour day month weekday)')
    return v


# =============================================================================
# Git Credentials Models
# =============================================================================


class GitCredentialCreate(BaseModel):
    """Request model for creating git credentials."""
    name: str = Field(..., min_length=1, max_length=100)
    auth_type: str = Field(..., pattern='^(none|https|ssh)$')
    username: Optional[str] = Field(None, max_length=200)
    password: Optional[str] = Field(None, max_length=500)
    ssh_private_key: Optional[str] = Field(None, max_length=10000)

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_name(v, required=True)

    @field_validator('ssh_private_key')
    @classmethod
    def validate_ssh_key(cls, v: Optional[str]) -> Optional[str]:
        return _validate_ssh_key(v)


class GitCredentialUpdate(BaseModel):
    """Request model for updating git credentials."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    auth_type: Optional[str] = Field(None, pattern='^(none|https|ssh)$')
    username: Optional[str] = Field(None, max_length=200)
    password: Optional[str] = Field(None, max_length=500)
    ssh_private_key: Optional[str] = Field(None, max_length=10000)
    clear_password: bool = Field(default=False)
    clear_ssh_key: bool = Field(default=False)

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        return _validate_name(v, required=False)

    @field_validator('ssh_private_key')
    @classmethod
    def validate_ssh_key(cls, v: Optional[str]) -> Optional[str]:
        return _validate_ssh_key(v)


class GitCredentialResponse(BaseModel):
    """Response model for git credentials (sanitized - no secrets)."""
    id: int
    name: str
    auth_type: str
    username: Optional[str] = None
    has_password: bool = False
    has_ssh_key: bool = False
    created_at: str
    updated_at: str

    @classmethod
    def from_db(cls, credential) -> 'GitCredentialResponse':
        """Create response from database model."""
        return cls(
            id=credential.id,
            name=credential.name,
            auth_type=credential.auth_type,
            username=credential.username,
            has_password=credential._password is not None,
            has_ssh_key=credential._ssh_private_key is not None,
            created_at=credential.created_at.isoformat() + 'Z',
            updated_at=credential.updated_at.isoformat() + 'Z',
        )


# =============================================================================
# Git Repositories Models
# =============================================================================


class GitRepositoryCreate(BaseModel):
    """Request model for creating git repositories."""
    name: str = Field(..., min_length=1, max_length=100)
    url: str = Field(..., min_length=1, max_length=500)
    branch: str = Field(default='main', min_length=1, max_length=100)
    credential_id: Optional[int] = None
    auto_sync_enabled: bool = Field(default=False)
    auto_sync_cron: str = Field(default='0 3 * * *', max_length=100)

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_name(v, required=True)

    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        return _validate_url(v, required=True)

    @field_validator('branch')
    @classmethod
    def validate_branch(cls, v: str) -> str:
        return _validate_branch(v, required=True)

    @field_validator('auto_sync_cron')
    @classmethod
    def validate_cron(cls, v: str) -> str:
        return _validate_cron(v, required=True)


class GitRepositoryUpdate(BaseModel):
    """Request model for updating git repositories."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    url: Optional[str] = Field(None, min_length=1, max_length=500)
    branch: Optional[str] = Field(None, min_length=1, max_length=100)
    credential_id: Optional[int] = None
    auto_sync_enabled: Optional[bool] = None
    auto_sync_cron: Optional[str] = Field(None, max_length=100)
    clear_credential: bool = Field(default=False)

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        return _validate_name(v, required=False)

    @field_validator('url')
    @classmethod
    def validate_url(cls, v: Optional[str]) -> Optional[str]:
        return _validate_url(v, required=False)

    @field_validator('branch')
    @classmethod
    def validate_branch(cls, v: Optional[str]) -> Optional[str]:
        return _validate_branch(v, required=False)

    @field_validator('auto_sync_cron')
    @classmethod
    def validate_cron(cls, v: Optional[str]) -> Optional[str]:
        return _validate_cron(v, required=False)


class GitRepositoryResponse(BaseModel):
    """Response model for git repositories."""
    id: int
    name: str
    url: str
    branch: str
    credential_id: Optional[int] = None
    credential_name: Optional[str] = None
    auto_sync_enabled: bool
    auto_sync_cron: str
    last_sync_at: Optional[str] = None
    last_commit: Optional[str] = None
    sync_status: str
    sync_error: Optional[str] = None
    linked_stacks_count: int = 0
    created_at: str
    updated_at: str

    @classmethod
    def from_db(cls, repo, linked_stacks_count: int = 0) -> 'GitRepositoryResponse':
        """Create response from database model."""
        return cls(
            id=repo.id,
            name=repo.name,
            url=repo.url,
            branch=repo.branch,
            credential_id=repo.credential_id,
            credential_name=repo.credential.name if repo.credential else None,
            auto_sync_enabled=repo.auto_sync_enabled,
            auto_sync_cron=repo.auto_sync_cron,
            last_sync_at=repo.last_sync_at.isoformat() + 'Z' if repo.last_sync_at else None,
            last_commit=repo.last_commit,
            sync_status=repo.sync_status,
            sync_error=repo.sync_error,
            linked_stacks_count=linked_stacks_count,
            created_at=repo.created_at.isoformat() + 'Z',
            updated_at=repo.updated_at.isoformat() + 'Z',
        )


# =============================================================================
# Git Operations Models
# =============================================================================


class GitTestConnectionRequest(BaseModel):
    """Request model for testing git connection without saving."""
    url: str = Field(..., min_length=1, max_length=500)
    branch: str = Field(default='main', min_length=1, max_length=100)
    auth_type: str = Field(default='none', pattern='^(none|https|ssh)$')
    username: Optional[str] = Field(None, max_length=200)
    password: Optional[str] = Field(None, max_length=500)
    ssh_private_key: Optional[str] = Field(None, max_length=10000)

    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        return _validate_url(v, required=True)


class GitTestConnectionResponse(BaseModel):
    """Response model for git connection test."""
    success: bool
    message: str


class GitSyncResponse(BaseModel):
    """Response model for git sync operation."""
    success: bool
    updated: bool
    commit: Optional[str] = None
    error: Optional[str] = None


class GitFileListResponse(BaseModel):
    """Response model for listing files in repository."""
    files: List[str]
    total: int
