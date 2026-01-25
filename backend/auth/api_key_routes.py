"""
API Key Management Routes

Provides endpoints for creating, listing, updating, and revoking API keys.

SECURITY:
- All routes require authentication
- Create/update/delete require 'apikeys.manage_other' capability
- Keys are hashed before storage (never plaintext)
- Revocation is idempotent (returns 200 if already revoked)

v2.4.0 Refactor:
- API keys now belong to a group (not scopes)
- Permissions come from the assigned group
- created_by_user_id for audit trail
"""

import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field

from database import ApiKey, User, CustomGroup
from auth.api_key_auth import generate_api_key, get_current_user_or_api_key, require_capability
from auth.shared import db
from auth.utils import format_timestamp, format_timestamp_required
from security.audit import security_audit
from utils.client_ip import get_client_ip

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/api-keys", tags=["api-keys"])


def _get_auditable_user_info(current_user: dict) -> tuple[int | None, str]:
    """Extract user ID and username from auth context for audit logging.

    Handles both session auth and API key auth contexts.

    Args:
        current_user: Auth context from get_current_user_or_api_key

    Returns:
        Tuple of (user_id, display_name) where:
        - Session auth: (user_id, username)
        - API key auth: (created_by_user_id, "API Key: <name>")
    """
    if current_user.get("auth_type") == "api_key":
        return (
            current_user.get("created_by_user_id"),
            f"API Key: {current_user.get('api_key_name', 'unknown')}"
        )
    return (current_user.get("user_id"), current_user.get("username", "unknown"))


# Request/Response Models

class ApiKeyCreateRequest(BaseModel):
    """Request to create new API key (v2.4.0 group-based)"""
    name: str = Field(..., min_length=1, max_length=100, description="Human-readable name")
    description: str | None = Field(None, max_length=500, description="Optional description")
    group_id: int = Field(..., description="Group ID for permissions")
    allowed_ips: str | None = Field(None, description="Comma-separated IPs/CIDRs (optional)")
    expires_days: int | None = Field(None, ge=1, le=365, description="Expiration in days (optional)")


class ApiKeyCreateResponse(BaseModel):
    """Response after creating API key - includes plaintext key"""
    id: int
    name: str
    description: str | None = None
    key: str  # IMPORTANT: Only shown once!
    key_prefix: str
    group_id: int
    group_name: str
    expires_at: str | None
    message: str


class ApiKeyListItem(BaseModel):
    """API key list item (masked key)"""
    id: int
    name: str
    description: str | None
    key_prefix: str  # Only show prefix, never full key
    group_id: int
    group_name: str
    allowed_ips: str | None
    last_used_at: str | None
    usage_count: int
    expires_at: str | None
    revoked_at: str | None
    created_at: str
    created_by_username: str | None


class ApiKeyUpdateRequest(BaseModel):
    """Request to update API key.

    Note: group_id cannot be changed after creation. To use a different group,
    create a new API key.
    """
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    allowed_ips: str | None = None


# Routes

@router.post("/", response_model=ApiKeyCreateResponse, dependencies=[Depends(require_capability("apikeys.manage_other"))])
async def create_api_key(
    data: ApiKeyCreateRequest,
    current_user: dict = Depends(get_current_user_or_api_key),
    request: Request = None
):
    """
    Create a new API key for programmatic API access (v2.4.0 group-based).

    ## 🔐 Security Notes

    - **apikeys.manage_other capability required** - Only admins can create API keys
    - **Key shown only once** - Save immediately, cannot be retrieved later!
    - **SHA256 hashing** - Plaintext key never stored in database
    - **Group-based permissions** - Key inherits permissions from assigned group

    ## 📝 Request Example

    ```bash
    curl -X POST https://your-dockmon-url/api/v2/api-keys/ \\
      -H "Authorization: Bearer YOUR_EXISTING_KEY" \\
      -H "Content-Type: application/json" \\
      -d '{
        "name": "Homepage Dashboard",
        "description": "Read-only key for Homepage widget",
        "group_id": 3,
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
      "group_id": 3,
      "group_name": "Read Only",
      "expires_at": "2025-02-14T10:30:00Z",
      "message": "Save this key immediately - it will not be shown again!"
    }
    ```

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

    # Get user info for audit (handles both session and API key auth)
    user_id, display_name = _get_auditable_user_info(current_user)

    # Create database record
    with db.get_session() as session:
        # Validate group exists
        group = session.query(CustomGroup).filter(CustomGroup.id == data.group_id).first()
        if not group:
            raise HTTPException(status_code=400, detail=f"Group with ID {data.group_id} not found")

        api_key = ApiKey(
            group_id=data.group_id,
            created_by_user_id=user_id,
            name=data.name,
            description=data.description,
            key_hash=key_hash,
            key_prefix=key_prefix,
            allowed_ips=data.allowed_ips,
            expires_at=expires_at,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        session.add(api_key)
        session.commit()
        session.refresh(api_key)

        # Audit log
        client_ip = get_client_ip(request)
        security_audit.log_privileged_action(
            client_ip=client_ip,
            action="create_api_key",
            target=f"{api_key.name} (group: {group.name})",
            success=True
        )

        logger.info(f"{display_name} created API key: {api_key.name} (group: {group.name})")

        return ApiKeyCreateResponse(
            id=api_key.id,
            name=api_key.name,
            description=api_key.description,
            key=plaintext_key,  # ONLY TIME THIS IS RETURNED!
            key_prefix=api_key.key_prefix,
            group_id=group.id,
            group_name=group.name,
            expires_at=format_timestamp(expires_at),
            message="IMPORTANT: Save this key now - it cannot be retrieved later!"
        )


@router.get("/", response_model=list[ApiKeyListItem], dependencies=[Depends(require_capability("apikeys.manage_other"))])
async def list_api_keys(
    current_user: dict = Depends(get_current_user_or_api_key)
):
    """
    List all API keys (v2.4.0 group-based).

    ## 🔐 Security

    - Returns **key prefix only** (e.g., `dockmon_A1b2C3d4...`)
    - Full keys are **never** retrievable after creation
    - Shows usage statistics and expiration status
    - Shows assigned group for each key

    ## 📝 Example

    ```bash
    curl https://your-dockmon-url/api/v2/api-keys/ \\
      -H "Authorization: Bearer YOUR_API_KEY"
    ```

    ## 📊 Response Fields

    - `key_prefix` - First 20 characters (safe to display)
    - `group_id` - Assigned group ID
    - `group_name` - Assigned group name
    - `last_used_at` - Last authentication timestamp
    - `usage_count` - Total API calls made with this key
    - `revoked_at` - Revocation timestamp (null = active)
    - `expires_at` - Expiration timestamp (null = never expires)
    - `created_by_username` - User who created the key
    """
    with db.get_session() as session:
        # Join with CustomGroup to get group names
        keys = session.query(ApiKey, CustomGroup, User).join(
            CustomGroup, ApiKey.group_id == CustomGroup.id
        ).outerjoin(
            User, ApiKey.created_by_user_id == User.id
        ).order_by(ApiKey.created_at.desc()).all()

        return [
            ApiKeyListItem(
                id=key.id,
                name=key.name,
                description=key.description,
                key_prefix=key.key_prefix,
                group_id=group.id,
                group_name=group.name,
                allowed_ips=key.allowed_ips,
                last_used_at=format_timestamp(key.last_used_at),
                usage_count=key.usage_count,
                expires_at=format_timestamp(key.expires_at),
                revoked_at=format_timestamp(key.revoked_at),
                created_at=format_timestamp_required(key.created_at),
                created_by_username=creator.username if creator else None
            )
            for key, group, creator in keys
        ]


@router.patch("/{key_id}", dependencies=[Depends(require_capability("apikeys.manage_other"))])
async def update_api_key(
    key_id: int,
    data: ApiKeyUpdateRequest,
    current_user: dict = Depends(get_current_user_or_api_key),
    request: Request = None
):
    """
    Update API key metadata (name, description, IP restrictions).

    ## Important

    - **Cannot change the key itself or group** - only metadata
    - Requires `apikeys.manage_other` capability
    - All fields are optional (only update what you provide)
    - To use a different group, create a new API key

    ## Example

    ```bash
    curl -X PATCH https://your-dockmon-url/api/v2/api-keys/1 \\
      -H "Authorization: Bearer YOUR_ADMIN_KEY" \\
      -H "Content-Type: application/json" \\
      -d '{
        "name": "Updated Name",
        "allowed_ips": "192.168.1.0/24"
      }'
    ```

    ## Updatable Fields

    - `name` - Display name
    - `description` - Optional description
    - `allowed_ips` - Comma-separated IPs/CIDRs (or null to remove)
    """
    with db.get_session() as session:
        api_key = session.query(ApiKey).filter(ApiKey.id == key_id).first()

        if not api_key:
            raise HTTPException(status_code=404, detail="API key not found")

        # Debug logging for troubleshooting
        logger.debug(f"API Key update request - allowed_ips field: {repr(data.allowed_ips)}")

        # Collect changes for audit log
        changes = []
        if data.name is not None:
            changes.append(f"name: {api_key.name} → {data.name}")
            api_key.name = data.name
        if data.description is not None:
            changes.append("description updated")
            api_key.description = data.description
        # Handle allowed_ips field - use model_fields_set to detect if explicitly provided
        # This distinguishes "field not sent" from "field sent as null"
        if 'allowed_ips' in data.model_fields_set:
            if data.allowed_ips is None or (isinstance(data.allowed_ips, str) and data.allowed_ips.strip() == ""):
                changes.append("allowed_ips cleared (no restrictions)")
                api_key.allowed_ips = None
            else:
                changes.append("allowed_ips updated")
                api_key.allowed_ips = data.allowed_ips

        api_key.updated_at = datetime.now(timezone.utc)
        session.commit()

        # Audit log
        client_ip = get_client_ip(request) if request else "unknown"
        security_audit.log_privileged_action(
            client_ip=client_ip,
            action="update_api_key",
            target=f"{api_key.name} (changes: {', '.join(changes) if changes else 'none'})",
            success=True
        )

        _, display_name = _get_auditable_user_info(current_user)
        logger.info(f"{display_name} updated API key: {api_key.name}")

        return {"message": "API key updated successfully"}


@router.delete("/{key_id}", dependencies=[Depends(require_capability("apikeys.manage_other"))])
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

    - Requires `apikeys.manage_other` capability
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
        api_key = session.query(ApiKey).filter(ApiKey.id == key_id).first()

        if not api_key:
            raise HTTPException(status_code=404, detail="API key not found")

        # Get group name for audit log
        group = session.query(CustomGroup).filter(CustomGroup.id == api_key.group_id).first()
        group_name = group.name if group else "unknown"

        # Idempotent revoke
        if api_key.revoked_at is not None:
            logger.info(f"API key {api_key.name} already revoked")
            return {"message": "API key already revoked"}

        # Soft delete
        api_key.revoked_at = datetime.now(timezone.utc)
        api_key.updated_at = datetime.now(timezone.utc)
        session.commit()

        # Audit log
        client_ip = get_client_ip(request) if request else "unknown"
        security_audit.log_privileged_action(
            client_ip=client_ip,
            action="revoke_api_key",
            target=f"{api_key.name} (group: {group_name})",
            success=True
        )

        _, display_name = _get_auditable_user_info(current_user)
        logger.info(f"{display_name} revoked API key: {api_key.name}")

        return {"message": "API key revoked successfully"}
