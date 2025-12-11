"""
Action Token Routes for DockMon

Provides endpoints for validating and executing one-time action tokens
from notification links.

SECURITY:
- Endpoints require authentication (user must be logged in)
- Token validates the specific action is permitted
- Tokens are single-use and time-limited
- All operations are audit logged
- Execute requires explicit confirmation
"""

import logging
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field

from auth.action_token_auth import validate_action_token
from auth.shared import db
from auth.api_key_auth import get_current_user_or_api_key as get_current_user
from utils.client_ip import get_client_ip
from security.audit import security_audit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/action-tokens", tags=["action-tokens"])


# Response Models

class ActionTokenInfoResponse(BaseModel):
    """Response for token info endpoint"""
    valid: bool
    reason: Optional[str] = None  # If invalid: 'expired', 'used', 'revoked', 'not_found'
    action_type: Optional[str] = None
    action_params: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    expires_at: Optional[str] = None
    hours_remaining: Optional[float] = None


class ActionTokenExecuteRequest(BaseModel):
    """Request to execute action token"""
    confirmed: bool = Field(..., description="Must be true to execute")


class ActionTokenExecuteResponse(BaseModel):
    """Response from executing action token"""
    success: bool
    action_type: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@router.get("/{token}/info", response_model=ActionTokenInfoResponse)
async def get_action_token_info(
    token: str,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    Validate action token and return action details.

    Requires authentication - user must be logged in.
    Used by the confirmation page to display what action will be performed.

    Returns action details if valid, or reason if invalid.
    """
    client_ip = get_client_ip(request)

    result = validate_action_token(db, token, client_ip, mark_used=False)

    if not result["valid"]:
        return ActionTokenInfoResponse(
            valid=False,
            reason=result.get("reason", "unknown")
        )

    return ActionTokenInfoResponse(
        valid=True,
        action_type=result["action_type"],
        action_params=result["action_params"],
        created_at=result["created_at"],
        expires_at=result["expires_at"],
        hours_remaining=result["hours_remaining"]
    )


@router.post("/{token}/consume", response_model=ActionTokenExecuteResponse)
async def consume_action_token(
    token: str,
    body: ActionTokenExecuteRequest,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    Consume (validate and mark as used) an action token.

    Requires authentication - user must be logged in.
    Requires explicit confirmation (confirmed=true) in request body.

    Returns the action_type and action_params so the frontend can call
    the appropriate existing endpoint (e.g., execute-update).

    The token is marked as used after this call and cannot be reused.
    """
    client_ip = get_client_ip(request)
    user_id = current_user.get("user_id")

    # Require explicit confirmation
    if not body.confirmed:
        return ActionTokenExecuteResponse(
            success=False,
            error="Confirmation required"
        )

    # Validate and mark as used (atomic)
    result = validate_action_token(db, token, client_ip, mark_used=True)

    if not result["valid"]:
        reason = result.get("reason", "unknown")
        security_audit.log_event(
            event_type="action_token_consume_failed",
            severity="warning",
            user_id=user_id,
            client_ip=client_ip,
            details={"reason": reason}
        )
        return ActionTokenExecuteResponse(
            success=False,
            error=f"Token invalid: {reason}"
        )

    action_type = result["action_type"]
    action_params = result["action_params"]

    # Log successful consumption
    security_audit.log_event(
        event_type="action_token_consumed",
        severity="info",
        user_id=user_id,
        client_ip=client_ip,
        details={
            "action_type": action_type,
            "action_params": action_params
        }
    )

    # Return the action details - frontend will call the appropriate endpoint
    return ActionTokenExecuteResponse(
        success=True,
        action_type=action_type,
        result=action_params  # host_id, container_id, container_name, etc.
    )
