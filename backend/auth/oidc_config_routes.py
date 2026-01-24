"""
DockMon OIDC Configuration Routes - Admin-only OIDC Settings Management

Phase 4 of Multi-User Support (v2.3.0)

SECURITY:
- All endpoints require admin role
- Client secret is encrypted before storage
- Provider URL must use HTTPS
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field, field_validator

from auth.shared import db
from auth.api_key_auth import require_scope, get_current_user_or_api_key
from database import OIDCConfig, OIDCRoleMapping
from audit import get_client_info, AuditAction
from audit.audit_logger import log_audit, AuditEntityType
from utils.encryption import encrypt_password, decrypt_password

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/oidc", tags=["oidc-config"])

# Valid DockMon roles
VALID_ROLES = ["admin", "user", "readonly"]


# ==================== Request/Response Models ====================

class OIDCConfigResponse(BaseModel):
    """OIDC configuration response (admin only)"""
    enabled: bool
    provider_url: Optional[str] = None
    client_id: Optional[str] = None
    # Never return client_secret - only indicate if set
    client_secret_configured: bool
    scopes: str
    claim_for_groups: str
    created_at: str
    updated_at: str


class OIDCConfigUpdateRequest(BaseModel):
    """Update OIDC configuration"""
    enabled: Optional[bool] = None
    provider_url: Optional[str] = Field(None, max_length=500)
    client_id: Optional[str] = Field(None, max_length=200)
    client_secret: Optional[str] = Field(None, max_length=500)
    scopes: Optional[str] = Field(None, max_length=500)
    claim_for_groups: Optional[str] = Field(None, max_length=100)

    @field_validator('provider_url')
    @classmethod
    def validate_provider_url(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v:
            if not v.startswith('https://'):
                raise ValueError("Provider URL must use HTTPS")
            # Remove trailing slash for consistency
            v = v.rstrip('/')
        return v


class OIDCRoleMappingResponse(BaseModel):
    """OIDC role mapping response"""
    id: int
    oidc_value: str
    dockmon_role: str
    priority: int
    created_at: str


class OIDCRoleMappingCreateRequest(BaseModel):
    """Create a new role mapping"""
    oidc_value: str = Field(..., min_length=1, max_length=200)
    dockmon_role: str = Field(...)
    priority: int = Field(default=0, ge=0, le=1000)

    @field_validator('dockmon_role')
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}")
        return v


class OIDCRoleMappingUpdateRequest(BaseModel):
    """Update a role mapping"""
    oidc_value: Optional[str] = Field(None, min_length=1, max_length=200)
    dockmon_role: Optional[str] = None
    priority: Optional[int] = Field(None, ge=0, le=1000)

    @field_validator('dockmon_role')
    @classmethod
    def validate_role(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_ROLES:
            raise ValueError(f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}")
        return v


class OIDCDiscoveryResponse(BaseModel):
    """OIDC provider discovery response"""
    success: bool
    message: str
    issuer: Optional[str] = None
    authorization_endpoint: Optional[str] = None
    token_endpoint: Optional[str] = None
    userinfo_endpoint: Optional[str] = None
    end_session_endpoint: Optional[str] = None
    scopes_supported: Optional[List[str]] = None
    claims_supported: Optional[List[str]] = None


class OIDCStatusResponse(BaseModel):
    """OIDC status for public endpoints"""
    enabled: bool
    provider_configured: bool


# ==================== Helper Functions ====================

def _config_to_response(config: OIDCConfig) -> OIDCConfigResponse:
    """Convert OIDCConfig model to response"""
    return OIDCConfigResponse(
        enabled=config.enabled,
        provider_url=config.provider_url,
        client_id=config.client_id,
        client_secret_configured=config.client_secret_encrypted is not None,
        scopes=config.scopes,
        claim_for_groups=config.claim_for_groups,
        created_at=config.created_at.isoformat() + 'Z' if config.created_at else datetime.now(timezone.utc).isoformat() + 'Z',
        updated_at=config.updated_at.isoformat() + 'Z' if config.updated_at else datetime.now(timezone.utc).isoformat() + 'Z',
    )


def _mapping_to_response(mapping: OIDCRoleMapping) -> OIDCRoleMappingResponse:
    """Convert OIDCRoleMapping model to response"""
    return OIDCRoleMappingResponse(
        id=mapping.id,
        oidc_value=mapping.oidc_value,
        dockmon_role=mapping.dockmon_role,
        priority=mapping.priority,
        created_at=mapping.created_at.isoformat() + 'Z' if mapping.created_at else datetime.now(timezone.utc).isoformat() + 'Z',
    )


def _safe_audit_log(session, *args, **kwargs) -> None:
    """Execute audit logging with error handling"""
    try:
        log_audit(session, *args, **kwargs)
        session.commit()
    except Exception as e:
        logger.warning(f"Failed to log audit entry: {e}")


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

@router.get("/config", response_model=OIDCConfigResponse, dependencies=[Depends(require_scope("admin"))])
async def get_oidc_config(
    current_user: dict = Depends(get_current_user_or_api_key)
) -> OIDCConfigResponse:
    """
    Get OIDC configuration (admin only).
    """
    with db.get_session() as session:
        config = _get_or_create_config(session)
        return _config_to_response(config)


@router.put("/config", response_model=OIDCConfigResponse, dependencies=[Depends(require_scope("admin"))])
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

        config.updated_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(config)

        logger.info(f"OIDC configuration updated by admin '{current_user['username']}'")

        # Audit log
        if changes:
            _safe_audit_log(
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

        return _config_to_response(config)


@router.post("/discover", response_model=OIDCDiscoveryResponse, dependencies=[Depends(require_scope("admin"))])
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
            async with httpx.AsyncClient(timeout=10.0) as client:
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


# ==================== Role Mapping Endpoints ====================

@router.get("/role-mappings", response_model=List[OIDCRoleMappingResponse], dependencies=[Depends(require_scope("admin"))])
async def list_role_mappings(
    current_user: dict = Depends(get_current_user_or_api_key)
) -> List[OIDCRoleMappingResponse]:
    """
    List all OIDC role mappings (admin only).

    Mappings are returned sorted by priority (highest first).
    """
    with db.get_session() as session:
        mappings = session.query(OIDCRoleMapping).order_by(
            OIDCRoleMapping.priority.desc(),
            OIDCRoleMapping.id.asc()
        ).all()

        return [_mapping_to_response(m) for m in mappings]


@router.post("/role-mappings", response_model=OIDCRoleMappingResponse, dependencies=[Depends(require_scope("admin"))])
async def create_role_mapping(
    mapping_data: OIDCRoleMappingCreateRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key)
) -> OIDCRoleMappingResponse:
    """
    Create a new OIDC role mapping (admin only).

    Maps an OIDC group/claim value to a DockMon role.
    Higher priority mappings take precedence when a user has multiple matching groups.
    """
    with db.get_session() as session:
        # Check for duplicate OIDC value
        existing = session.query(OIDCRoleMapping).filter(
            OIDCRoleMapping.oidc_value == mapping_data.oidc_value
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Mapping for '{mapping_data.oidc_value}' already exists"
            )

        mapping = OIDCRoleMapping(
            oidc_value=mapping_data.oidc_value,
            dockmon_role=mapping_data.dockmon_role,
            priority=mapping_data.priority,
            created_at=datetime.now(timezone.utc),
        )

        session.add(mapping)
        session.commit()
        session.refresh(mapping)

        logger.info(f"OIDC role mapping '{mapping_data.oidc_value}' -> '{mapping_data.dockmon_role}' created by admin '{current_user['username']}'")

        # Audit log
        _safe_audit_log(
            session,
            current_user['user_id'],
            current_user['username'],
            AuditAction.CREATE,
            AuditEntityType.OIDC_CONFIG,
            entity_id=str(mapping.id),
            entity_name=f"role_mapping:{mapping_data.oidc_value}",
            details={
                'oidc_value': mapping_data.oidc_value,
                'dockmon_role': mapping_data.dockmon_role,
                'priority': mapping_data.priority,
            },
            **get_client_info(request)
        )

        return _mapping_to_response(mapping)


@router.put("/role-mappings/{mapping_id}", response_model=OIDCRoleMappingResponse, dependencies=[Depends(require_scope("admin"))])
async def update_role_mapping(
    mapping_id: int,
    mapping_data: OIDCRoleMappingUpdateRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key)
) -> OIDCRoleMappingResponse:
    """
    Update an OIDC role mapping (admin only).
    """
    with db.get_session() as session:
        mapping = session.query(OIDCRoleMapping).filter(OIDCRoleMapping.id == mapping_id).first()

        if not mapping:
            raise HTTPException(status_code=404, detail="Role mapping not found")

        changes = {}

        if mapping_data.oidc_value is not None:
            # Check for duplicate
            existing = session.query(OIDCRoleMapping).filter(
                OIDCRoleMapping.oidc_value == mapping_data.oidc_value,
                OIDCRoleMapping.id != mapping_id
            ).first()
            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Mapping for '{mapping_data.oidc_value}' already exists"
                )
            changes['oidc_value'] = {'old': mapping.oidc_value, 'new': mapping_data.oidc_value}
            mapping.oidc_value = mapping_data.oidc_value

        if mapping_data.dockmon_role is not None:
            changes['dockmon_role'] = {'old': mapping.dockmon_role, 'new': mapping_data.dockmon_role}
            mapping.dockmon_role = mapping_data.dockmon_role

        if mapping_data.priority is not None:
            changes['priority'] = {'old': mapping.priority, 'new': mapping_data.priority}
            mapping.priority = mapping_data.priority

        session.commit()
        session.refresh(mapping)

        logger.info(f"OIDC role mapping {mapping_id} updated by admin '{current_user['username']}'")

        # Audit log
        if changes:
            _safe_audit_log(
                session,
                current_user['user_id'],
                current_user['username'],
                AuditAction.UPDATE,
                AuditEntityType.OIDC_CONFIG,
                entity_id=str(mapping.id),
                entity_name=f"role_mapping:{mapping.oidc_value}",
                details={'changes': changes},
                **get_client_info(request)
            )

        return _mapping_to_response(mapping)


@router.delete("/role-mappings/{mapping_id}", dependencies=[Depends(require_scope("admin"))])
async def delete_role_mapping(
    mapping_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key)
) -> dict:
    """
    Delete an OIDC role mapping (admin only).
    """
    with db.get_session() as session:
        mapping = session.query(OIDCRoleMapping).filter(OIDCRoleMapping.id == mapping_id).first()

        if not mapping:
            raise HTTPException(status_code=404, detail="Role mapping not found")

        oidc_value = mapping.oidc_value
        session.delete(mapping)
        session.commit()

        logger.info(f"OIDC role mapping '{oidc_value}' deleted by admin '{current_user['username']}'")

        # Audit log
        _safe_audit_log(
            session,
            current_user['user_id'],
            current_user['username'],
            AuditAction.DELETE,
            AuditEntityType.OIDC_CONFIG,
            entity_id=str(mapping_id),
            entity_name=f"role_mapping:{oidc_value}",
            **get_client_info(request)
        )

        return {"message": f"Role mapping '{oidc_value}' deleted"}
