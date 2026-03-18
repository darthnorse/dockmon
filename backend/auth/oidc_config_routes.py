"""
DockMon OIDC Configuration Routes - Admin-only OIDC Settings Management

Phase 4 of Multi-User Support (v2.3.0)
Updated for group-based permissions (v2.4.0)

SECURITY:
- All endpoints require admin capabilities
- Client secret is encrypted before storage
- Provider URL must use HTTPS
"""

import json
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field, field_validator

from auth.shared import db, safe_audit_log
from auth.api_key_auth import require_capability, get_current_user_or_api_key
from auth.utils import format_timestamp_required, get_group_or_400, get_auditable_user_info
from auth.oidc_auth_routes import _fetch_oidc_discovery, OIDC_HTTP_TIMEOUT
from database import OIDCConfig, OIDCGroupMapping, CustomGroup
from audit import get_client_info, AuditAction
from audit.audit_logger import AuditEntityType
from utils.encryption import encrypt_password, decrypt_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/oidc", tags=["oidc-config"])


# ==================== Request/Response Models ====================

class OIDCConfigResponse(BaseModel):
    """OIDC configuration response (admin only)"""
    enabled: bool
    provider_url: str | None = None
    client_id: str | None = None
    # Never return client_secret - only indicate if set
    client_secret_configured: bool
    scopes: str
    claim_for_groups: str
    default_group_id: int | None = None
    default_group_name: str | None = None  # For display
    sso_default: bool
    disable_pkce_with_secret: bool
    require_approval: bool  # New in v2.6.0
    approval_notify_channel_ids: list[int] | None = None  # New in v2.6.0
    created_at: str
    updated_at: str


class OIDCConfigUpdateRequest(BaseModel):
    """Update OIDC configuration"""
    enabled: bool | None = None
    provider_url: str | None = Field(None, max_length=500)
    client_id: str | None = Field(None, max_length=200)
    client_secret: str | None = Field(None, max_length=1000)
    scopes: str | None = Field(None, max_length=500)
    claim_for_groups: str | None = Field(None, max_length=100)
    default_group_id: int | None = None
    sso_default: bool | None = None
    disable_pkce_with_secret: bool | None = None
    require_approval: bool | None = None  # New in v2.6.0
    approval_notify_channel_ids: list[int] | None = None  # New in v2.6.0

    @field_validator('provider_url')
    @classmethod
    def validate_provider_url(cls, v: str | None) -> str | None:
        if v is not None and v:
            if not v.startswith('https://'):
                raise ValueError("Provider URL must use HTTPS")
            v = v.rstrip('/')
        return v


class OIDCGroupMappingResponse(BaseModel):
    """OIDC group mapping response"""
    id: int
    oidc_value: str
    group_id: int
    group_name: str  # For display
    priority: int
    created_at: str


class OIDCGroupMappingCreateRequest(BaseModel):
    """Create a new group mapping"""
    oidc_value: str = Field(..., min_length=1, max_length=200)
    group_id: int
    priority: int = Field(default=0, ge=0, le=1000)


class OIDCGroupMappingUpdateRequest(BaseModel):
    """Update a group mapping"""
    oidc_value: str | None = Field(None, min_length=1, max_length=200)
    group_id: int | None = None
    priority: int | None = Field(None, ge=0, le=1000)


class OIDCDiscoveryRequest(BaseModel):
    """Request body for OIDC discovery - uses form values if provided, otherwise saved config"""
    provider_url: str | None = Field(None, max_length=500)
    client_id: str | None = Field(None, max_length=200)
    client_secret: str | None = Field(None, max_length=1000)


class OIDCDiscoveryResponse(BaseModel):
    """OIDC provider discovery response"""
    success: bool
    message: str
    issuer: str | None = None
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None
    userinfo_endpoint: str | None = None
    end_session_endpoint: str | None = None
    scopes_supported: list[str] | None = None
    claims_supported: list[str] | None = None
    client_validated: bool | None = None
    client_validation_message: str | None = None


class OIDCStatusResponse(BaseModel):
    """OIDC status for public endpoints"""
    enabled: bool
    provider_configured: bool
    sso_default: bool


# ==================== Helper Functions ====================


def _deserialize_channel_ids(raw: str | None) -> list[int] | None:
    """Deserialize approval_notify_channel_ids from JSON string."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _config_to_response(config: OIDCConfig, session) -> OIDCConfigResponse:
    """Convert OIDCConfig model to response"""
    # Get default group name for display
    default_group_name = None
    if config.default_group_id:
        default_group = session.query(CustomGroup).filter(CustomGroup.id == config.default_group_id).first()
        if default_group:
            default_group_name = default_group.name

    return OIDCConfigResponse(
        enabled=config.enabled,
        provider_url=config.provider_url,
        client_id=config.client_id,
        client_secret_configured=config.client_secret_encrypted is not None,
        scopes=config.scopes,
        claim_for_groups=config.claim_for_groups,
        default_group_id=config.default_group_id,
        default_group_name=default_group_name,
        sso_default=config.sso_default,
        disable_pkce_with_secret=config.disable_pkce_with_secret,
        require_approval=config.require_approval,
        approval_notify_channel_ids=_deserialize_channel_ids(config.approval_notify_channel_ids),
        created_at=format_timestamp_required(config.created_at),
        updated_at=format_timestamp_required(config.updated_at),
    )


def _mapping_to_response(
    mapping: OIDCGroupMapping,
    group_names: dict[int, str] | None = None,
    session=None
) -> OIDCGroupMappingResponse:
    """Convert OIDCGroupMapping model to response.

    Args:
        mapping: The mapping to convert
        group_names: Optional pre-fetched dict of {group_id: group_name} to avoid N+1 queries
        session: Database session (only needed if group_names not provided)
    """
    # Get group name from pre-fetched dict or query
    if group_names is not None:
        group_name = group_names.get(mapping.group_id, "Unknown")
    elif session is not None:
        group = session.query(CustomGroup).filter(CustomGroup.id == mapping.group_id).first()
        group_name = group.name if group else "Unknown"
    else:
        group_name = "Unknown"

    return OIDCGroupMappingResponse(
        id=mapping.id,
        oidc_value=mapping.oidc_value,
        group_id=mapping.group_id,
        group_name=group_name,
        priority=mapping.priority,
        created_at=format_timestamp_required(mapping.created_at),
    )


def _get_or_create_config(session) -> OIDCConfig:
    """Get or create the singleton OIDC config"""
    config = session.query(OIDCConfig).filter(OIDCConfig.id == 1).first()
    if not config:
        config = OIDCConfig(
            id=1,
            enabled=False,
            scopes='openid profile email groups',
            claim_for_groups='groups',
            sso_default=False,
            require_approval=False,
            approval_notify_channel_ids=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(config)
        session.commit()
        session.refresh(config)
    return config


# ==================== Public Endpoints ====================

@router.get("/status", response_model=OIDCStatusResponse)
async def get_oidc_status() -> OIDCStatusResponse:
    """
    Get OIDC status (public endpoint for login page).

    Returns whether OIDC is enabled and configured.
    """
    with db.get_session() as session:
        row = session.query(
            OIDCConfig.enabled,
            OIDCConfig.provider_url,
            OIDCConfig.client_id,
            OIDCConfig.sso_default,
        ).filter(OIDCConfig.id == 1).first()

        if not row:
            return OIDCStatusResponse(enabled=False, provider_configured=False, sso_default=False)

        provider_configured = bool(row.provider_url and row.client_id)
        is_enabled = row.enabled and provider_configured

        return OIDCStatusResponse(
            enabled=is_enabled,
            provider_configured=provider_configured,
            sso_default=row.sso_default and is_enabled,
        )


# ==================== Admin Endpoints ====================

@router.get("/config", response_model=OIDCConfigResponse, dependencies=[Depends(require_capability("oidc.manage"))])
async def get_oidc_config(
    current_user: dict = Depends(get_current_user_or_api_key)
) -> OIDCConfigResponse:
    """
    Get OIDC configuration (admin only).
    """
    with db.get_session() as session:
        config = _get_or_create_config(session)
        return _config_to_response(config, session)


@router.put("/config", response_model=OIDCConfigResponse, dependencies=[Depends(require_capability("oidc.manage"))])
async def update_oidc_config(
    config_data: OIDCConfigUpdateRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key)
) -> OIDCConfigResponse:
    """
    Update OIDC configuration (admin only).

    Only updates fields that are provided (partial update).
    Client secret is encrypted before storage.
    """
    # Get user info for audit (handles both session and API key auth)
    user_id, display_name = get_auditable_user_info(current_user)

    with db.get_session() as session:
        config = _get_or_create_config(session)
        changes = {}

        if config_data.enabled is not None:
            changes['enabled'] = {'old': config.enabled, 'new': config_data.enabled}
            config.enabled = config_data.enabled

        if config_data.provider_url is not None:
            changes['provider_url'] = {'old': config.provider_url, 'new': config_data.provider_url}
            config.provider_url = config_data.provider_url if config_data.provider_url else None

        if config_data.client_id is not None:
            changes['client_id'] = {'old': config.client_id, 'new': config_data.client_id}
            config.client_id = config_data.client_id if config_data.client_id else None

        if config_data.client_secret is not None:
            changes['client_secret'] = 'updated'
            if config_data.client_secret:
                config.client_secret_encrypted = encrypt_password(config_data.client_secret)
            else:
                config.client_secret_encrypted = None

        if config_data.scopes is not None:
            changes['scopes'] = {'old': config.scopes, 'new': config_data.scopes}
            config.scopes = config_data.scopes if config_data.scopes else 'openid profile email groups'

        if config_data.claim_for_groups is not None:
            changes['claim_for_groups'] = {'old': config.claim_for_groups, 'new': config_data.claim_for_groups}
            config.claim_for_groups = config_data.claim_for_groups if config_data.claim_for_groups else 'groups'

        if config_data.default_group_id is not None:
            # Validate group exists (allow setting to None via 0 to clear)
            if config_data.default_group_id != 0:  # 0 means clear the default
                get_group_or_400(session, config_data.default_group_id)
                changes['default_group_id'] = {'old': config.default_group_id, 'new': config_data.default_group_id}
                config.default_group_id = config_data.default_group_id
            else:
                changes['default_group_id'] = {'old': config.default_group_id, 'new': None}
                config.default_group_id = None

        if config_data.sso_default is not None:
            changes['sso_default'] = {'old': config.sso_default, 'new': config_data.sso_default}
            config.sso_default = config_data.sso_default

        if config_data.disable_pkce_with_secret is not None:
            changes['disable_pkce_with_secret'] = {'old': config.disable_pkce_with_secret, 'new': config_data.disable_pkce_with_secret}
            config.disable_pkce_with_secret = config_data.disable_pkce_with_secret

        if config_data.require_approval is not None:
            changes['require_approval'] = {'old': config.require_approval, 'new': config_data.require_approval}
            config.require_approval = config_data.require_approval

        if config_data.approval_notify_channel_ids is not None:
            changes['approval_notify_channel_ids'] = {
                'old': _deserialize_channel_ids(config.approval_notify_channel_ids),
                'new': config_data.approval_notify_channel_ids,
            }
            config.approval_notify_channel_ids = json.dumps(config_data.approval_notify_channel_ids)

        config.updated_at = datetime.now(timezone.utc)
        # Audit log (before commit for atomicity)
        if changes:
            safe_audit_log(
                session,
                user_id,
                display_name,
                AuditAction.UPDATE,
                AuditEntityType.OIDC_CONFIG,
                entity_id='1',
                entity_name='oidc_config',
                details={'changes': changes},
                **get_client_info(request)
            )

        session.commit()
        session.refresh(config)

        logger.info(f"OIDC configuration updated by {display_name}")

        return _config_to_response(config, session)


async def _validate_client_credentials(
    token_endpoint: str,
    client_id: str,
    client_secret: str,
) -> tuple[bool | None, str]:
    """Validate client credentials via client_credentials grant. Returns (validated, message)."""
    if not token_endpoint.startswith('https://'):
        return None, "Token endpoint is not HTTPS — skipped credential validation"

    try:
        async with httpx.AsyncClient(timeout=OIDC_HTTP_TIMEOUT) as http:
            response = await http.post(
                token_endpoint,
                data={
                    'grant_type': 'client_credentials',
                    'client_id': client_id,
                    'client_secret': client_secret,
                },
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
            )
    except Exception as e:
        logger.warning(f"Client credential validation failed: {e}")
        return None, "Could not validate credentials: connection error during validation"

    if response.status_code == 200:
        return True, "Client credentials are valid"

    try:
        error_data = response.json()
    except Exception:
        error_data = {}

    error_code = error_data.get('error', '')
    if error_code in ('unauthorized_client', 'unsupported_grant_type'):
        return None, (
            f"Could not validate credentials: provider returned '{error_code}'. "
            "This client may not support the client_credentials grant type, "
            "but credentials may still be correct for the authorization code flow."
        )

    error_desc = error_data.get('error_description', f'HTTP {response.status_code}')
    return False, f"Invalid client credentials: {error_desc}"


@router.post("/discover", response_model=OIDCDiscoveryResponse, dependencies=[Depends(require_capability("oidc.manage"))])
async def discover_oidc_provider(
    body: OIDCDiscoveryRequest,
    current_user: dict = Depends(get_current_user_or_api_key),
) -> OIDCDiscoveryResponse:
    """
    Discover OIDC provider endpoints and validate client credentials (admin only).

    Uses form values from the request body if provided, otherwise falls back to saved config.
    After successful discovery, validates client_id/client_secret via client_credentials grant.
    """
    provider_url = body.provider_url
    client_id = body.client_id
    client_secret = body.client_secret

    if not provider_url or not client_id or not client_secret:
        with db.get_session() as session:
            config = session.query(OIDCConfig).filter(OIDCConfig.id == 1).first()
            if config:
                provider_url = provider_url or config.provider_url
                client_id = client_id or config.client_id
                if not client_secret and config.client_secret_encrypted:
                    try:
                        client_secret = decrypt_password(config.client_secret_encrypted)
                    except Exception:
                        pass

    if not provider_url:
        return OIDCDiscoveryResponse(
            success=False,
            message="Provider URL not configured",
        )

    # Use shared discovery function (handles HTTPS validation, URL normalization, endpoint checks)
    try:
        discovery = await _fetch_oidc_discovery(provider_url)
    except ValueError as e:
        return OIDCDiscoveryResponse(success=False, message=str(e))
    except httpx.TimeoutException:
        return OIDCDiscoveryResponse(success=False, message="Provider connection timeout")
    except httpx.HTTPStatusError as e:
        hint = ""
        if e.response.status_code == 404:
            provider_url = provider_url.rstrip('/')
            if provider_url.endswith('/.well-known/openid-configuration'):
                provider_url = provider_url[:-len('/.well-known/openid-configuration')]
            discovery_url = f"{provider_url}/.well-known/openid-configuration"
            hint = (
                f". Tried: {discovery_url} — check that the Provider URL includes the full path "
                "(e.g. for Authentik: https://auth.example.com/application/o/your-app-slug)"
            )
        return OIDCDiscoveryResponse(success=False, message=f"Provider returned HTTP {e.response.status_code}{hint}")
    except Exception as e:
        logger.error(f"OIDC provider discovery error: {e}", exc_info=True)
        return OIDCDiscoveryResponse(success=False, message="Discovery failed due to an unexpected error. Check server logs for details.")

    token_endpoint = discovery.get('token_endpoint')

    client_validated = None
    client_validation_message = None
    if client_id and client_secret and token_endpoint:
        client_validated, client_validation_message = await _validate_client_credentials(
            token_endpoint, client_id, client_secret,
        )
    elif not client_id or not client_secret:
        client_validation_message = "Client ID or secret not provided — skipped credential validation"

    return OIDCDiscoveryResponse(
        success=True,
        message="Provider discovery successful",
        issuer=discovery.get('issuer'),
        authorization_endpoint=discovery.get('authorization_endpoint'),
        token_endpoint=token_endpoint,
        userinfo_endpoint=discovery.get('userinfo_endpoint'),
        end_session_endpoint=discovery.get('end_session_endpoint'),
        scopes_supported=discovery.get('scopes_supported'),
        claims_supported=discovery.get('claims_supported'),
        client_validated=client_validated,
        client_validation_message=client_validation_message,
    )


# ==================== Group Mapping Endpoints ====================

@router.get("/group-mappings", response_model=list[OIDCGroupMappingResponse], dependencies=[Depends(require_capability("oidc.manage"))])
async def list_group_mappings(
    current_user: dict = Depends(get_current_user_or_api_key)
) -> list[OIDCGroupMappingResponse]:
    """
    List all OIDC group mappings (admin only).

    Mappings are returned sorted by priority (highest first).
    """
    with db.get_session() as session:
        mappings = session.query(OIDCGroupMapping).order_by(
            OIDCGroupMapping.priority.desc(),
            OIDCGroupMapping.id.asc()
        ).all()

        # Pre-fetch all group names in a single query to avoid N+1
        group_ids = list({m.group_id for m in mappings})
        if group_ids:
            groups = session.query(CustomGroup).filter(CustomGroup.id.in_(group_ids)).all()
            group_names = {g.id: g.name for g in groups}
        else:
            group_names = {}

        return [_mapping_to_response(m, group_names=group_names) for m in mappings]


@router.post("/group-mappings", response_model=OIDCGroupMappingResponse, dependencies=[Depends(require_capability("oidc.manage"))])
async def create_group_mapping(
    mapping_data: OIDCGroupMappingCreateRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key)
) -> OIDCGroupMappingResponse:
    """
    Create a new OIDC group mapping (admin only).

    Maps an OIDC group/claim value to a DockMon group. Each OIDC value maps
    to exactly one DockMon group (one-to-one). Users in multiple OIDC groups
    get added to all corresponding DockMon groups and receive the union of
    all group permissions.

    This follows industry best practice (Kubernetes, AWS, Vault, etc.).
    """
    # Get user info for audit (handles both session and API key auth)
    user_id, display_name = get_auditable_user_info(current_user)

    with db.get_session() as session:
        # One-to-one mapping: each OIDC value maps to exactly one DockMon group
        existing = session.query(OIDCGroupMapping).filter(
            OIDCGroupMapping.oidc_value == mapping_data.oidc_value
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Mapping for '{mapping_data.oidc_value}' already exists. Each OIDC group can only map to one DockMon group."
            )

        # Validate group exists (uses shared helper)
        group = get_group_or_400(session, mapping_data.group_id)

        mapping = OIDCGroupMapping(
            oidc_value=mapping_data.oidc_value,
            group_id=mapping_data.group_id,
            priority=mapping_data.priority,
            created_at=datetime.now(timezone.utc),
        )

        session.add(mapping)
        session.flush()  # Get mapping.id for audit log

        # Audit log (before commit for atomicity)
        safe_audit_log(
            session,
            user_id,
            display_name,
            AuditAction.CREATE,
            AuditEntityType.OIDC_CONFIG,
            entity_id=str(mapping.id),
            entity_name=f"group_mapping:{mapping_data.oidc_value}",
            details={
                'oidc_value': mapping_data.oidc_value,
                'group_id': mapping_data.group_id,
                'group_name': group.name,
                'priority': mapping_data.priority,
            },
            **get_client_info(request)
        )

        session.commit()
        session.refresh(mapping)

        logger.info(f"OIDC group mapping '{mapping_data.oidc_value}' -> group {mapping_data.group_id} ('{group.name}') created by {display_name}")

        return _mapping_to_response(mapping, session=session)


@router.put("/group-mappings/{mapping_id}", response_model=OIDCGroupMappingResponse, dependencies=[Depends(require_capability("oidc.manage"))])
async def update_group_mapping(
    mapping_id: int,
    mapping_data: OIDCGroupMappingUpdateRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key)
) -> OIDCGroupMappingResponse:
    """
    Update an OIDC group mapping (admin only).
    """
    # Get user info for audit (handles both session and API key auth)
    user_id, display_name = get_auditable_user_info(current_user)

    with db.get_session() as session:
        mapping = session.query(OIDCGroupMapping).filter(OIDCGroupMapping.id == mapping_id).first()

        if not mapping:
            raise HTTPException(status_code=404, detail="Group mapping not found")

        changes = {}

        if mapping_data.oidc_value is not None:
            # One-to-one mapping: check for duplicate OIDC value
            existing = session.query(OIDCGroupMapping).filter(
                OIDCGroupMapping.oidc_value == mapping_data.oidc_value,
                OIDCGroupMapping.id != mapping_id
            ).first()
            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Mapping for '{mapping_data.oidc_value}' already exists"
                )
            changes['oidc_value'] = {'old': mapping.oidc_value, 'new': mapping_data.oidc_value}
            mapping.oidc_value = mapping_data.oidc_value

        if mapping_data.group_id is not None:
            # Validate group exists (uses shared helper)
            get_group_or_400(session, mapping_data.group_id)
            changes['group_id'] = {'old': mapping.group_id, 'new': mapping_data.group_id}
            mapping.group_id = mapping_data.group_id

        if mapping_data.priority is not None:
            changes['priority'] = {'old': mapping.priority, 'new': mapping_data.priority}
            mapping.priority = mapping_data.priority

        # Audit log (before commit for atomicity)
        if changes:
            safe_audit_log(
                session,
                user_id,
                display_name,
                AuditAction.UPDATE,
                AuditEntityType.OIDC_CONFIG,
                entity_id=str(mapping.id),
                entity_name=f"group_mapping:{mapping.oidc_value}",
                details={'changes': changes},
                **get_client_info(request)
            )

        session.commit()
        session.refresh(mapping)

        logger.info(f"OIDC group mapping {mapping_id} updated by {display_name}")

        return _mapping_to_response(mapping, session=session)


@router.delete("/group-mappings/{mapping_id}", dependencies=[Depends(require_capability("oidc.manage"))])
async def delete_group_mapping(
    mapping_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key)
) -> dict:
    """
    Delete an OIDC group mapping (admin only).
    """
    # Get user info for audit (handles both session and API key auth)
    user_id, display_name = get_auditable_user_info(current_user)

    with db.get_session() as session:
        mapping = session.query(OIDCGroupMapping).filter(OIDCGroupMapping.id == mapping_id).first()

        if not mapping:
            raise HTTPException(status_code=404, detail="Group mapping not found")

        oidc_value = mapping.oidc_value
        group_id = mapping.group_id
        session.delete(mapping)

        # Audit log (before commit for atomicity)
        safe_audit_log(
            session,
            user_id,
            display_name,
            AuditAction.DELETE,
            AuditEntityType.OIDC_CONFIG,
            entity_id=str(mapping_id),
            entity_name=f"group_mapping:{oidc_value}",
            details={'oidc_value': oidc_value, 'group_id': group_id},
            **get_client_info(request)
        )

        session.commit()

        logger.info(f"OIDC group mapping '{oidc_value}' deleted by {display_name}")

        return {"message": f"Group mapping '{oidc_value}' deleted"}
