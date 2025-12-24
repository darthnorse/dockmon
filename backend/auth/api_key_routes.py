"""
API Key Management Routes

Provides endpoints for creating, listing, updating, and revoking API keys.

SECURITY:
- All routes require authentication
- Create/update/delete require 'admin' scope
- Keys are hashed before storage (never plaintext)
- Revocation is idempotent (returns 200 if already revoked)
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field, field_validator

from database import ApiKey, User
from auth.api_key_auth import generate_api_key, get_current_user_or_api_key, require_scope
from auth.shared import db
from security.audit import security_audit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/api-keys", tags=["api-keys"])


# Request/Response Models

class ApiKeyCreateRequest(BaseModel):
    """Request to create new API key"""
    name: str = Field(..., min_length=1, max_length=100, description="Human-readable name")
    description: Optional[str] = Field(None, max_length=500, description="Optional description")
    scopes: str = Field(default="read", description="Comma-separated scopes: read,write,admin")
    allowed_ips: Optional[str] = Field(None, description="Comma-separated IPs/CIDRs (optional)")
    expires_days: Optional[int] = Field(None, ge=1, le=365, description="Expiration in days (optional)")

    @field_validator('scopes')
    @classmethod
    def validate_scopes(cls, v: str) -> str:
        """Validate scopes are valid"""
        valid_scopes = {'read', 'write', 'admin'}
        scopes = set(s.strip() for s in v.split(','))
        invalid = scopes - valid_scopes
        if invalid:
            raise ValueError(f"Invalid scopes: {invalid}. Valid: {valid_scopes}")
        return ','.join(sorted(scopes))


class ApiKeyCreateResponse(BaseModel):
    """Response after creating API key - includes plaintext key"""
    id: int
    name: str
    key: str  # IMPORTANT: Only shown once!
    key_prefix: str
    scopes: str
    expires_at: Optional[str]
    message: str


class ApiKeyListItem(BaseModel):
    """API key list item (masked key)"""
    id: int
    name: str
    description: Optional[str]
    key_prefix: str  # Only show prefix, never full key
    scopes: str
    allowed_ips: Optional[str]
    last_used_at: Optional[str]
    usage_count: int
    expires_at: Optional[str]
    revoked_at: Optional[str]
    created_at: str


class ApiKeyUpdateRequest(BaseModel):
    """Request to update API key"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    scopes: Optional[str] = None
    allowed_ips: Optional[str] = None

    @field_validator('scopes')
    @classmethod
    def validate_scopes(cls, v: Optional[str]) -> Optional[str]:
        """Validate scopes if provided"""
        if v is None:
            return v
        valid_scopes = {'read', 'write', 'admin'}
        scopes = set(s.strip() for s in v.split(','))
        invalid = scopes - valid_scopes
        if invalid:
            raise ValueError(f"Invalid scopes: {invalid}. Valid: {valid_scopes}")
        return ','.join(sorted(scopes))


# Routes

@router.post("/", response_model=ApiKeyCreateResponse, dependencies=[Depends(require_scope("admin"))])
async def create_api_key(
    data: ApiKeyCreateRequest,
    current_user: dict = Depends(get_current_user_or_api_key),
    request: Request = None
):
    """
    Create a new API key for programmatic API access.

    ## 🔐 Security Notes

    - **Admin scope required** - Only admins can create API keys
    - **Key shown only once** - Save immediately, cannot be retrieved later!
    - **SHA256 hashing** - Plaintext key never stored in database

    ## 📝 Request Example

    ```bash
    curl -X POST https://your-dockmon-url/api/v2/api-keys/ \\
      -H "Authorization: Bearer YOUR_EXISTING_KEY" \\
      -H "Content-Type: application/json" \\
      -d '{
        "name": "Homepage Dashboard",
        "description": "Read-only key for Homepage widget",
        "scopes": "read",
        "expires_days": 90
      }'
    ```

    ## 📊 Response Example

    ```json
    {
      "id": 1,
      "name": "Homepage Dashboard",
      "key": "dockmon_A1b2C3d4E5f6...",
      "key_prefix": "dockmon_A1b2C3d4E5f6",
      "scopes": "read",
      "expires_at": "2025-02-14T10:30:00Z",
      "message": "Save this key immediately - it will not be shown again!"
    }
    ```

    ## 🎯 Scope Options

    - `read` - View-only (dashboards, monitoring)
    - `write` - Container operations (Ansible, CI/CD)
    - `admin` - Full access (create API keys, manage hosts)

    ## 🔗 See Also

    - [Security Guide](https://github.com/darthnorse/dockmon/blob/main/docs/API_KEY_SECURITY_CAVEATS.md)
    - [Wiki: API Access](https://github.com/darthnorse/dockmon/wiki/API-Access)
    """
    # Generate cryptographically secure key
    plaintext_key, key_hash, key_prefix = generate_api_key()

    # Calculate expiration if specified
    expires_at = None
    if data.expires_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=data.expires_days)

    # Create database record
    with db.get_session() as session:
        api_key = ApiKey(
            user_id=current_user["user_id"],
            name=data.name,
            description=data.description,
            key_hash=key_hash,
            key_prefix=key_prefix,
            scopes=data.scopes,
            allowed_ips=data.allowed_ips,
            expires_at=expires_at,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        session.add(api_key)
        session.commit()
        session.refresh(api_key)

        # Audit log
        from utils.client_ip import get_client_ip
        client_ip = get_client_ip(request)  # request is available from function params
        security_audit.log_privileged_action(
            client_ip=client_ip,
            action="create_api_key",
            target=f"{api_key.name} (scopes: {api_key.scopes})",
            success=True
        )

        logger.info(f"User {current_user['username']} created API key: {api_key.name}")

        return ApiKeyCreateResponse(
            id=api_key.id,
            name=api_key.name,
            key=plaintext_key,  # ONLY TIME THIS IS RETURNED!
            key_prefix=api_key.key_prefix,
            scopes=api_key.scopes,
            expires_at=expires_at.isoformat() + 'Z' if expires_at else None,
            message="IMPORTANT: Save this key now - it cannot be retrieved later!"
        )


@router.get("/", response_model=List[ApiKeyListItem])
async def list_api_keys(
    current_user: dict = Depends(get_current_user_or_api_key)
):
    """
    List all API keys for the authenticated user.

    ## 🔐 Security

    - Returns **key prefix only** (e.g., `dockmon_A1b2C3d4...`)
    - Full keys are **never** retrievable after creation
    - Shows usage statistics and expiration status

    ## 📝 Example

    ```bash
    curl https://your-dockmon-url/api/v2/api-keys/ \\
      -H "Authorization: Bearer YOUR_API_KEY"
    ```

    ## 📊 Response Fields

    - `key_prefix` - First 20 characters (safe to display)
    - `last_used_at` - Last authentication timestamp
    - `usage_count` - Total API calls made with this key
    - `revoked_at` - Revocation timestamp (null = active)
    - `expires_at` - Expiration timestamp (null = never expires)
    """
    with db.get_session() as session:
        keys = session.query(ApiKey).filter(
            ApiKey.user_id == current_user["user_id"]
        ).order_by(ApiKey.created_at.desc()).all()

        return [
            ApiKeyListItem(
                id=key.id,
                name=key.name,
                description=key.description,
                key_prefix=key.key_prefix,
                scopes=key.scopes,
                allowed_ips=key.allowed_ips,
                last_used_at=key.last_used_at.isoformat() + 'Z' if key.last_used_at else None,
                usage_count=key.usage_count,
                expires_at=key.expires_at.isoformat() + 'Z' if key.expires_at else None,
                revoked_at=key.revoked_at.isoformat() + 'Z' if key.revoked_at else None,
                created_at=key.created_at.isoformat() + 'Z'
            )
            for key in keys
        ]


@router.patch("/{key_id}", dependencies=[Depends(require_scope("admin"))])
async def update_api_key(
    key_id: int,
    data: ApiKeyUpdateRequest,
    current_user: dict = Depends(get_current_user_or_api_key),
    request: Request = None
):
    """
    Update API key metadata (name, scopes, IP restrictions).

    ## ⚠️ Important

    - **Cannot change the key itself** - only metadata
    - Requires `admin` scope
    - All fields are optional (only update what you provide)

    ## 📝 Example

    ```bash
    curl -X PATCH https://your-dockmon-url/api/v2/api-keys/1 \\
      -H "Authorization: Bearer YOUR_ADMIN_KEY" \\
      -H "Content-Type: application/json" \\
      -d '{
        "name": "Updated Name",
        "scopes": "read,write",
        "allowed_ips": "192.168.1.0/24"
      }'
    ```

    ## 🔄 Updatable Fields

    - `name` - Display name
    - `description` - Optional description
    - `scopes` - Comma-separated (read, write, admin)
    - `allowed_ips` - Comma-separated IPs/CIDRs (or null to remove)
    """
    with db.get_session() as session:
        api_key = session.query(ApiKey).filter(
            ApiKey.id == key_id,
            ApiKey.user_id == current_user["user_id"]
        ).first()

        if not api_key:
            raise HTTPException(status_code=404, detail="API key not found")

        # Debug logging (use INFO to ensure it shows in logs)
        logger.info(f"API Key update request - allowed_ips field: {repr(data.allowed_ips)}")

        # Collect changes for audit log
        changes = []
        if data.name is not None:
            changes.append(f"name: {api_key.name} → {data.name}")
            api_key.name = data.name
        if data.description is not None:
            changes.append(f"description updated")
            api_key.description = data.description
        if data.scopes is not None:
            changes.append(f"scopes: {api_key.scopes} → {data.scopes}")
            api_key.scopes = data.scopes
        # Handle allowed_ips field - need to check if it's explicitly in the request
        # Pydantic sets it to None when field is sent as null/empty
        if hasattr(data, 'allowed_ips'):
            if data.allowed_ips is None or (isinstance(data.allowed_ips, str) and data.allowed_ips.strip() == ""):
                changes.append(f"allowed_ips cleared (no restrictions)")
                api_key.allowed_ips = None
            else:
                changes.append(f"allowed_ips updated")
                api_key.allowed_ips = data.allowed_ips

        api_key.updated_at = datetime.now(timezone.utc)
        session.commit()

        # Audit log
        from utils.client_ip import get_client_ip
        client_ip = get_client_ip(request) if request else "unknown"
        security_audit.log_privileged_action(
            client_ip=client_ip,
            action="update_api_key",
            target=f"{api_key.name} (changes: {', '.join(changes) if changes else 'none'})",
            success=True
        )

        logger.info(f"User {current_user['username']} updated API key: {api_key.name}")

        return {"message": "API key updated successfully"}


@router.delete("/{key_id}", dependencies=[Depends(require_scope("admin"))])
async def revoke_api_key(
    key_id: int,
    current_user: dict = Depends(get_current_user_or_api_key),
    request: Request = None
):
    """
    Revoke (delete) an API key immediately.

    ## 🔐 Security

    - **Soft delete** - Key marked as revoked, record kept for audit trail
    - **Immediate effect** - Key stops working instantly
    - **Idempotent** - Safe to call multiple times

    ## 📝 Example

    ```bash
    curl -X DELETE https://your-dockmon-url/api/v2/api-keys/1 \\
      -H "Authorization: Bearer YOUR_ADMIN_KEY"
    ```

    ## ⚠️ Important

    - Requires `admin` scope
    - Cannot be undone - create a new key if needed
    - All active sessions using this key will fail immediately
    - Record remains in database for audit purposes

    ## 💡 Use Cases

    - Key potentially compromised
    - Decommissioning automation tool
    - Regular key rotation
    - Removing unused integrations
    """
    with db.get_session() as session:
        api_key = session.query(ApiKey).filter(
            ApiKey.id == key_id,
            ApiKey.user_id == current_user["user_id"]
        ).first()

        if not api_key:
            raise HTTPException(status_code=404, detail="API key not found")

        # Idempotent revoke
        if api_key.revoked_at is not None:
            logger.info(f"API key {api_key.name} already revoked")
            return {"message": "API key already revoked"}

        # Soft delete
        api_key.revoked_at = datetime.now(timezone.utc)
        api_key.updated_at = datetime.now(timezone.utc)
        session.commit()

        # Audit log
        from utils.client_ip import get_client_ip
        client_ip = get_client_ip(request) if request else "unknown"
        security_audit.log_privileged_action(
            client_ip=client_ip,
            action="revoke_api_key",
            target=f"{api_key.name} (scopes: {api_key.scopes})",
            success=True
        )

        logger.info(f"User {current_user['username']} revoked API key: {api_key.name}")

        return {"message": "API key revoked successfully"}
