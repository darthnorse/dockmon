"""
Action Token Routes for DockMon

Provides endpoints for validating and executing one-time action tokens
from notification links.

SECURITY:
- Token validation endpoints do NOT require authentication (token IS the auth)
- Tokens are single-use and time-limited
- All operations are audit logged
- Execute requires explicit confirmation
"""

import logging
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from auth.action_token_auth import validate_action_token
from auth.shared import db
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
async def get_action_token_info(token: str, request: Request):
    """
    Validate action token and return action details.

    This endpoint does NOT require authentication - the token IS the authentication.
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


@router.post("/{token}/execute", response_model=ActionTokenExecuteResponse)
async def execute_action_token(
    token: str,
    body: ActionTokenExecuteRequest,
    request: Request
):
    """
    Execute the action associated with the token.

    This endpoint does NOT require authentication - the token IS the authentication.
    Requires explicit confirmation (confirmed=true) in request body.

    The token is marked as used after this call and cannot be reused.
    """
    client_ip = get_client_ip(request)

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
        return ActionTokenExecuteResponse(
            success=False,
            error=f"Token invalid: {reason}"
        )

    action_type = result["action_type"]
    action_params = result["action_params"]
    user_id = result["user_id"]

    # Execute the action based on type
    try:
        if action_type == "container_update":
            exec_result = await _execute_container_update(action_params, user_id, client_ip)
        else:
            logger.error(f"Unknown action type: {action_type}")
            return ActionTokenExecuteResponse(
                success=False,
                action_type=action_type,
                error=f"Unknown action type: {action_type}"
            )

        return ActionTokenExecuteResponse(
            success=exec_result.get("success", False),
            action_type=action_type,
            result=exec_result if exec_result.get("success") else None,
            error=exec_result.get("error") if not exec_result.get("success") else None
        )

    except Exception as e:
        logger.error(f"Error executing action token: {e}", exc_info=True)
        security_audit.log_event(
            event_type="action_token_execute_error",
            severity="error",
            user_id=user_id,
            client_ip=client_ip,
            details={
                "action_type": action_type,
                "action_params": action_params,
                "error": str(e)  # Full error logged for debugging
            }
        )
        # Return generic error to client (don't expose internal details)
        return ActionTokenExecuteResponse(
            success=False,
            action_type=action_type,
            error="Execution failed. Please check the DockMon logs for details."
        )


async def _execute_container_update(
    params: Dict[str, Any],
    user_id: int,
    client_ip: str
) -> Dict[str, Any]:
    """
    Execute a container update action.

    Args:
        params: Action parameters (host_id, container_id, etc.)
        user_id: User who owns the token
        client_ip: Client IP for audit logging

    Returns:
        Dict with success/failure and details
    """
    # Import here to avoid circular imports
    from updates.update_executor import get_update_executor
    from docker_monitor.monitor import get_monitor

    host_id = params.get("host_id")
    container_id = params.get("container_id")

    if not host_id or not container_id:
        return {"success": False, "error": "Missing host_id or container_id"}

    try:
        monitor = get_monitor()
        executor = get_update_executor(db, monitor)

        # Execute the update (force=True to skip WARN validation, user already confirmed via token)
        result = await executor.update_container(
            host_id=host_id,
            container_id=container_id,
            force=True
        )

        if result.get("success"):
            security_audit.log_event(
                event_type="action_token_update_success",
                severity="info",
                user_id=user_id,
                client_ip=client_ip,
                details={
                    "host_id": host_id,
                    "container_id": container_id,
                    "container_name": params.get("container_name"),
                    "previous_image": result.get("previous_image"),
                    "new_image": result.get("new_image")
                }
            )
            return {
                "success": True,
                "message": result.get("message", "Update successful"),
                "previous_image": result.get("previous_image"),
                "new_image": result.get("new_image")
            }
        else:
            error_msg = result.get("detail") or result.get("message") or "Update failed"
            security_audit.log_event(
                event_type="action_token_update_failed",
                severity="warning",
                user_id=user_id,
                client_ip=client_ip,
                details={
                    "host_id": host_id,
                    "container_id": container_id,
                    "container_name": params.get("container_name"),
                    "error": error_msg,
                    "rolled_back": result.get("rolled_back", False)
                }
            )
            return {
                "success": False,
                "error": error_msg,
                "rolled_back": result.get("rolled_back", False)
            }

    except Exception as e:
        logger.error(f"Container update via action token failed: {e}", exc_info=True)
        # Return sanitized error - full details are in logs
        return {"success": False, "error": "Container update failed. Check logs for details."}
