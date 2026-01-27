"""
Capabilities API - Returns available capabilities for the permissions UI

Group-Based Permissions Refactor (v2.4.0)
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth.api_key_auth import get_current_user_or_api_key
from auth.capabilities import CAPABILITY_INFO, get_categories


router = APIRouter(prefix="/api/v2/capabilities", tags=["capabilities"])


class CapabilityInfo(BaseModel):
    """Capability metadata for UI"""
    name: str
    capability: str
    category: str
    description: str


class CapabilitiesResponse(BaseModel):
    """List of all capabilities with metadata"""
    capabilities: list[CapabilityInfo]
    categories: list[str]


@router.get("", response_model=CapabilitiesResponse, dependencies=[Depends(get_current_user_or_api_key)])
async def get_capabilities():
    """
    Get all available capabilities with metadata.

    Returns capabilities grouped by category for the permissions UI.
    This endpoint is cached on the frontend (capabilities rarely change).
    """
    capabilities = [
        CapabilityInfo(
            name=info['name'],
            capability=cap,
            category=info['category'],
            description=info['description'],
        )
        for cap, info in CAPABILITY_INFO.items()
    ]

    # Sort by category then by name for consistent ordering
    capabilities.sort(key=lambda c: (c.category, c.name))

    return CapabilitiesResponse(
        capabilities=capabilities,
        categories=get_categories(),
    )
