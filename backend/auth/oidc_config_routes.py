"""
DockMon OIDC Configuration Routes - Admin-only OIDC Settings Management

Phase 4 of Multi-User Support (v2.3.0)
Updated for group-based permissions (v2.4.0)

SECURITY:
- All endpoints require admin capabilities
- Client secret is encrypted before storage
- Provider URL must use HTTPS
"""

import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field, field_validator

from auth.shared import db, safe_audit_log
from auth.api_key_auth import require_capability, get_current_user_or_api_key
from auth.utils import format_timestamp_required, get_group_or_400
from database import OIDCConfig, OIDCGroupMapping, CustomGroup
from audit import get_client_info, AuditAction
from audit.audit_logger import AuditEntityType
from utils.encryption import encrypt_password, decrypt_password

logger = logging.getLogger(__name__)

# HTTP client timeout for OIDC provider requests (shared with oidc_auth_routes)
OIDC_HTTP_TIMEOUT = 10.0

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
    created_at: str
    updated_at: str


class OIDCConfigUpdateRequest(BaseModel):
    """Update OIDC configuration"""
    enabled: bool | None = None
    provider_url: str | None = Field(None, max_length=500)
    client_id: str | None = Field(None, max_length=200)
    client_secret: str | None = Field(None, max_length=500)
    scopes: str | None = Field(None, max_length=500)
    claim_for_groups: str | None = Field(None, max_length=100)
    default_group_id: int | None = None

    @field_validator('provider_url')
    @classmethod
    def validate_provider_url(cls, v: str | None) -> str | None:
        if v is not None and v:
            if not v.startswith('https://'):
                raise ValueError("Provider URL must use HTTPS")
            # Remove trailing slash for consistency
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


class OIDCStatusResponse(BaseModel):
    """OIDC status for public endpoints"""
    enabled: bool
    provider_configured: bool


# ==================== Helper Functions ====================
# format_timestamp_required imported from auth.utils


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
        config = session.query(OIDCConfig).filter(OIDCConfig.id == 1).first()

        if not config:
            return OIDCStatusResponse(enabled=False, provider_configured=False)

        provider_configured = bool(config.provider_url and config.client_id)

        return OIDCStatusResponse(
            enabled=config.enabled and provider_configured,
            provider_configured=provider_configured,
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
                # Setting to 0 clears the default group
                changes['default_group_id'] = {'old': config.default_group_id, 'new': None}
                config.default_group_id = None

        config.updated_at = datetime.now(timezone.utc)
        # Audit log (before commit for atomicity)
        if changes:
            safe_audit_log(
                session,
                current_user['user_id'],
                current_user['username'],
                AuditAction.UPDATE,
                AuditEntityType.OIDC_CONFIG,
                entity_id='1',
                entity_name='oidc_config',
                details={'changes': changes},
                **get_client_info(request)
            )

        session.commit()
        session.refresh(config)

        logger.info(f"OIDC configuration updated by admin '{current_user['username']}'")

        return _config_to_response(config, session)


@router.post("/discover", response_model=OIDCDiscoveryResponse, dependencies=[Depends(require_capability("oidc.manage"))])
async def discover_oidc_provider(
    current_user: dict = Depends(get_current_user_or_api_key)
) -> OIDCDiscoveryResponse:
    """
    Discover OIDC provider endpoints (admin only).

    Fetches the provider's .well-known/openid-configuration and validates connectivity.
    Uses the configured provider_url.
    """
    with db.get_session() as session:
        config = session.query(OIDCConfig).filter(OIDCConfig.id == 1).first()

        if not config or not config.provider_url:
            return OIDCDiscoveryResponse(
                success=False,
                message="Provider URL not configured",
            )

        discovery_url = f"{config.provider_url}/.well-known/openid-configuration"

        try:
            async with httpx.AsyncClient(timeout=OIDC_HTTP_TIMEOUT) as client:
                response = await client.get(discovery_url)
                response.raise_for_status()
                discovery = response.json()

                return OIDCDiscoveryResponse(
                    success=True,
                    message="Provider discovery successful",
                    issuer=discovery.get('issuer'),
                    authorization_endpoint=discovery.get('authorization_endpoint'),
                    token_endpoint=discovery.get('token_endpoint'),
                    userinfo_endpoint=discovery.get('userinfo_endpoint'),
                    end_session_endpoint=discovery.get('end_session_endpoint'),
                    scopes_supported=discovery.get('scopes_supported'),
                    claims_supported=discovery.get('claims_supported'),
                )

        except httpx.TimeoutException:
            logger.warning(f"OIDC provider discovery timeout: {discovery_url}")
            return OIDCDiscoveryResponse(
                success=False,
                message="Provider connection timeout",
            )
        except httpx.HTTPStatusError as e:
            logger.warning(f"OIDC provider discovery HTTP error: {e}")
            return OIDCDiscoveryResponse(
                success=False,
                message=f"Provider returned HTTP {e.response.status_code}",
            )
        except Exception as e:
            logger.error(f"OIDC provider discovery error: {e}")
            return OIDCDiscoveryResponse(
                success=False,
                message=f"Discovery failed: {str(e)}",
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
            current_user['user_id'],
            current_user['username'],
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

        logger.info(f"OIDC group mapping '{mapping_data.oidc_value}' -> group {mapping_data.group_id} ('{group.name}') created by admin '{current_user['username']}'")

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
                current_user['user_id'],
                current_user['username'],
                AuditAction.UPDATE,
                AuditEntityType.OIDC_CONFIG,
                entity_id=str(mapping.id),
                entity_name=f"group_mapping:{mapping.oidc_value}",
                details={'changes': changes},
                **get_client_info(request)
            )

        session.commit()
        session.refresh(mapping)

        logger.info(f"OIDC group mapping {mapping_id} updated by admin '{current_user['username']}'")

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
            current_user['user_id'],
            current_user['username'],
            AuditAction.DELETE,
            AuditEntityType.OIDC_CONFIG,
            entity_id=str(mapping_id),
            entity_name=f"group_mapping:{oidc_value}",
            details={'oidc_value': oidc_value, 'group_id': group_id},
            **get_client_info(request)
        )

        session.commit()

        logger.info(f"OIDC group mapping '{oidc_value}' deleted by admin '{current_user['username']}'")

        return {"message": f"Group mapping '{oidc_value}' deleted"}
