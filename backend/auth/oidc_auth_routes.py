"""
DockMon OIDC Authentication Routes - OpenID Connect Login Flow

Phase 4 of Multi-User Support (v2.3.0)

Flow:
1. /authorize - Redirect user to OIDC provider
2. /callback - Handle provider callback, exchange code for tokens
3. Auto-provision user if first login
4. Map OIDC groups to DockMon role
5. Create session and redirect to frontend

SECURITY:
- State parameter for CSRF protection
- Nonce parameter for replay protection (validated against ID token)
- PKCE flow for authorization code security
- Email conflicts with local users are blocked
- Rate limiting on /authorize endpoint
- Database storage for pending auth requests (multi-instance safe)
"""

import base64
import hashlib
import json
import logging
import secrets
from base64 import urlsafe_b64encode
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlencode, urlparse, quote

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from auth.shared import db
from auth.cookie_sessions import cookie_session_manager
from config.settings import AppConfig
from database import User, OIDCConfig, OIDCRoleMapping, PendingOIDCAuth
from security.rate_limiting import rate_limit_auth
from audit import log_login, log_login_failure, get_client_info, AuditAction
from audit.audit_logger import log_audit, AuditEntityType
from utils.encryption import decrypt_password

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/auth/oidc", tags=["oidc-auth"])

# Default role for users with no matching group mappings
DEFAULT_OIDC_ROLE = "readonly"

# Pending auth request expiry time
PENDING_AUTH_EXPIRY_MINUTES = 10

# Session cookie duration (matches v2_routes.py)
SESSION_MAX_AGE_SECONDS = 86400 * 7  # 7 days


# ==================== Helper Functions ====================

def _validate_redirect_url(redirect: Optional[str]) -> str:
    """
    Validate redirect URL to prevent open redirect attacks.

    Only allows relative URLs starting with /. Rejects absolute URLs
    and URLs with schemes/netlocs that could redirect to external sites.
    """
    if not redirect:
        return '/'

    # Parse the URL
    parsed = urlparse(redirect)

    # Reject URLs with scheme or netloc (absolute URLs)
    if parsed.scheme or parsed.netloc:
        logger.warning(f"Rejected absolute redirect URL: {redirect[:50]}")
        return '/'

    # Ensure it starts with /
    if not redirect.startswith('/'):
        logger.warning(f"Rejected relative redirect URL not starting with /: {redirect[:50]}")
        return '/'

    # Prevent protocol-relative URLs (//evil.com)
    if redirect.startswith('//'):
        logger.warning(f"Rejected protocol-relative redirect URL: {redirect[:50]}")
        return '/'

    return redirect


def _generate_code_verifier() -> str:
    """Generate a PKCE code verifier (43-128 chars, URL-safe)."""
    return secrets.token_urlsafe(32)


def _generate_code_challenge(verifier: str) -> str:
    """Generate a PKCE code challenge from verifier (S256 method)."""
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    return urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')


def _generate_state() -> str:
    """Generate a random state parameter for CSRF protection."""
    return secrets.token_urlsafe(32)


def _generate_nonce() -> str:
    """Generate a random nonce for replay protection."""
    return secrets.token_urlsafe(32)


async def _fetch_oidc_discovery(provider_url: str) -> dict:
    """Fetch OIDC provider discovery document."""
    discovery_url = f"{provider_url}/.well-known/openid-configuration"

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(discovery_url)
        response.raise_for_status()
        return response.json()


async def _exchange_code_for_tokens(
    token_endpoint: str,
    code: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str,
    code_verifier: str,
) -> dict:
    """Exchange authorization code for tokens."""
    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': redirect_uri,
        'client_id': client_id,
        'client_secret': client_secret,
        'code_verifier': code_verifier,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(token_endpoint, data=data)
        response.raise_for_status()
        return response.json()


async def _fetch_userinfo(userinfo_endpoint: str, access_token: str) -> dict:
    """Fetch user info from OIDC provider."""
    headers = {'Authorization': f'Bearer {access_token}'}

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(userinfo_endpoint, headers=headers)
        response.raise_for_status()
        return response.json()


def _normalize_groups_claim(groups_value) -> list:
    """
    Normalize groups claim to a list of strings.

    Handles various formats that OIDC providers might return:
    - list of strings (standard)
    - single string (some providers)
    - None (no groups)
    - Invalid types (logged and ignored)
    """
    if groups_value is None:
        return []

    if isinstance(groups_value, str):
        return [groups_value]

    if isinstance(groups_value, list):
        # Filter to only strings, log and skip invalid items
        result = []
        for item in groups_value:
            if isinstance(item, str):
                result.append(item)
            else:
                logger.warning(f"Ignoring non-string group value: {type(item).__name__}")
        return result

    # Unexpected type - log warning and return empty
    logger.warning(f"Unexpected groups claim type: {type(groups_value).__name__}, ignoring")
    return []


def _map_groups_to_role(groups: list, session) -> str:
    """
    Map OIDC groups to DockMon role using configured mappings.

    Returns the role of the highest priority matching mapping,
    or DEFAULT_OIDC_ROLE if no mappings match.
    """
    if not groups:
        return DEFAULT_OIDC_ROLE

    # Get all mappings ordered by priority (highest first)
    mappings = session.query(OIDCRoleMapping).order_by(
        OIDCRoleMapping.priority.desc()
    ).all()

    # Find the highest priority matching mapping
    for mapping in mappings:
        if mapping.oidc_value in groups:
            logger.debug(f"OIDC group '{mapping.oidc_value}' matched role '{mapping.dockmon_role}'")
            return mapping.dockmon_role

    logger.debug(f"No matching OIDC group mapping for groups: {groups}")
    return DEFAULT_OIDC_ROLE


def _safe_audit_log(session, *args, **kwargs) -> None:
    """Execute audit logging with error handling."""
    try:
        log_audit(session, *args, **kwargs)
        session.commit()
    except Exception as e:
        logger.warning(f"Failed to log audit entry: {e}")


# ==================== OIDC Flow Endpoints ====================

@router.get("/authorize")
async def oidc_authorize(
    request: Request,
    redirect: Optional[str] = None,
    rate_limit_check: bool = rate_limit_auth,
) -> RedirectResponse:
    """
    Initiate OIDC authorization flow.

    Redirects user to OIDC provider's authorization endpoint.
    Stores state, nonce, and code verifier in database for callback validation.

    Rate limited to prevent abuse.
    """
    with db.get_session() as session:
        config = session.query(OIDCConfig).filter(OIDCConfig.id == 1).first()

        if not config or not config.enabled:
            raise HTTPException(status_code=400, detail="OIDC is not enabled")

        if not config.provider_url or not config.client_id:
            raise HTTPException(status_code=400, detail="OIDC is not configured")

        # Fetch discovery document
        try:
            discovery = await _fetch_oidc_discovery(config.provider_url)
        except Exception as e:
            logger.error(f"OIDC discovery failed: {e}")
            raise HTTPException(status_code=502, detail="Failed to contact OIDC provider")

        authorization_endpoint = discovery.get('authorization_endpoint')
        if not authorization_endpoint:
            raise HTTPException(status_code=502, detail="OIDC provider missing authorization_endpoint")

        # Generate security parameters
        state = _generate_state()
        nonce = _generate_nonce()
        code_verifier = _generate_code_verifier()
        code_challenge = _generate_code_challenge(code_verifier)

        # Build callback URL
        # Use request's base URL, respecting reverse proxy headers
        scheme = request.headers.get('X-Forwarded-Proto', request.url.scheme)
        host = request.headers.get('X-Forwarded-Host', request.headers.get('Host', request.url.netloc))

        # Handle BASE_PATH for reverse proxy subpath deployments
        base_path = AppConfig.BASE_PATH.rstrip('/') if AppConfig.BASE_PATH else ''
        redirect_uri = f"{scheme}://{host}{base_path}/api/v2/auth/oidc/callback"

        # Validate and sanitize the redirect URL to prevent open redirect attacks
        validated_redirect = _validate_redirect_url(redirect)

        # Clean up expired pending auth requests
        now = datetime.now(timezone.utc)
        session.query(PendingOIDCAuth).filter(
            PendingOIDCAuth.expires_at < now
        ).delete()

        # Store pending auth request in database (expires in 10 minutes)
        pending_auth = PendingOIDCAuth(
            state=state,
            nonce=nonce,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            frontend_redirect=validated_redirect,
            expires_at=now + timedelta(minutes=PENDING_AUTH_EXPIRY_MINUTES),
            created_at=now,
        )
        session.add(pending_auth)
        session.commit()

        # Build authorization URL
        params = {
            'response_type': 'code',
            'client_id': config.client_id,
            'redirect_uri': redirect_uri,
            'scope': config.scopes,
            'state': state,
            'nonce': nonce,
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256',
        }

        auth_url = f"{authorization_endpoint}?{urlencode(params)}"

        logger.info(f"OIDC authorize redirect: state={state[:8]}...")
        return RedirectResponse(url=auth_url, status_code=302)


@router.get("/callback")
async def oidc_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
) -> RedirectResponse:
    """
    Handle OIDC provider callback.

    Validates state, exchanges code for tokens, validates nonce,
    fetches user info, provisions/updates user, and creates session.
    """
    # Handle provider errors
    if error:
        logger.warning(f"OIDC callback error: {error} - {error_description}")
        # Redirect to login with error (URL-encode to prevent XSS)
        error_msg = quote(str(error_description or error)[:100])
        return RedirectResponse(url=f"/login?error=oidc_error&message={error_msg}")

    if not code or not state:
        logger.warning("OIDC callback missing code or state")
        return RedirectResponse(url="/login?error=oidc_error&message=Missing+authorization+code")

    with db.get_session() as session:
        # Validate state from database
        pending = session.query(PendingOIDCAuth).filter(
            PendingOIDCAuth.state == state
        ).first()

        if not pending:
            logger.warning(f"OIDC callback invalid state: {state[:8]}...")
            return RedirectResponse(url="/login?error=oidc_error&message=Invalid+or+expired+state")

        # Check expiry
        if pending.is_expired:
            session.delete(pending)
            session.commit()
            logger.warning(f"OIDC callback expired state: {state[:8]}...")
            return RedirectResponse(url="/login?error=oidc_error&message=Session+expired")

        # Extract values and delete pending request (one-time use)
        expected_nonce = pending.nonce
        code_verifier = pending.code_verifier
        redirect_uri = pending.redirect_uri
        frontend_redirect = pending.frontend_redirect
        session.delete(pending)
        session.commit()
        config = session.query(OIDCConfig).filter(OIDCConfig.id == 1).first()

        if not config or not config.enabled:
            return RedirectResponse(url="/login?error=oidc_error&message=OIDC+disabled")

        try:
            # Fetch discovery document
            discovery = await _fetch_oidc_discovery(config.provider_url)
            token_endpoint = discovery.get('token_endpoint')
            userinfo_endpoint = discovery.get('userinfo_endpoint')

            if not token_endpoint:
                raise ValueError("Missing token_endpoint")

            # Decrypt client secret
            client_secret = ''
            if config.client_secret_encrypted:
                client_secret = decrypt_password(config.client_secret_encrypted)

            # Exchange code for tokens
            tokens = await _exchange_code_for_tokens(
                token_endpoint=token_endpoint,
                code=code,
                redirect_uri=redirect_uri,
                client_id=config.client_id,
                client_secret=client_secret,
                code_verifier=code_verifier,
            )

            access_token = tokens.get('access_token')
            id_token = tokens.get('id_token')

            if not access_token:
                raise ValueError("No access_token in response")

            # Decode and validate ID token (nonce validation for replay protection)
            id_token_claims = None
            if id_token:
                parts = id_token.split('.')
                if len(parts) >= 2:
                    # Decode payload (add padding if needed)
                    payload_b64 = parts[1]
                    padding = 4 - len(payload_b64) % 4
                    if padding != 4:
                        payload_b64 += '=' * padding
                    id_token_claims = json.loads(base64.urlsafe_b64decode(payload_b64))

                    # Validate nonce to prevent replay attacks
                    token_nonce = id_token_claims.get('nonce')
                    if token_nonce != expected_nonce:
                        logger.warning(f"OIDC nonce mismatch: expected={expected_nonce[:8]}... got={str(token_nonce)[:8]}...")
                        return RedirectResponse(url="/login?error=oidc_error&message=Invalid+nonce")

            # Fetch user info (prefer userinfo endpoint, fall back to ID token claims)
            if userinfo_endpoint:
                userinfo = await _fetch_userinfo(userinfo_endpoint, access_token)
            elif id_token_claims:
                userinfo = id_token_claims
            else:
                raise ValueError("No userinfo endpoint and no ID token")

            # Extract user info
            oidc_subject = userinfo.get('sub')
            email = userinfo.get('email')
            preferred_username = userinfo.get('preferred_username', email)
            name = userinfo.get('name', preferred_username)

            if not oidc_subject:
                raise ValueError("No 'sub' claim in userinfo")

            # Get groups from configured claim (with type safety)
            groups_claim = config.claim_for_groups
            groups_raw = userinfo.get(groups_claim)
            groups = _normalize_groups_claim(groups_raw)

            # Map groups to role
            role = _map_groups_to_role(groups, session)

            logger.info(f"OIDC callback: sub={oidc_subject}, email={email}, groups={groups}, role={role}")

            # Find or create user
            user = session.query(User).filter(User.oidc_subject == oidc_subject).first()

            now = datetime.now(timezone.utc)

            if user:
                # Existing OIDC user - update role if changed
                old_role = user.role
                if old_role != role:
                    user.role = role
                    logger.info(f"OIDC user '{user.username}' role changed: {old_role} -> {role}")

                    # Audit role change
                    _safe_audit_log(
                        session,
                        user.id,
                        user.username,
                        AuditAction.ROLE_CHANGE,
                        AuditEntityType.USER,
                        entity_id=str(user.id),
                        entity_name=user.username,
                        details={'old_role': old_role, 'new_role': role, 'source': 'oidc_refresh'},
                        **get_client_info(request)
                    )

                user.last_login = now
                user.updated_at = now
                session.commit()

            else:
                # New OIDC user - check for email conflict
                if email:
                    existing_email = session.query(User).filter(
                        User.email == email,
                        User.auth_provider == 'local',
                    ).first()
                    if existing_email:
                        logger.warning(f"OIDC login blocked: email '{email}' exists as local user")
                        _safe_audit_log(
                            session,
                            None,
                            preferred_username,
                            AuditAction.LOGIN_FAILED,
                            AuditEntityType.SESSION,
                            details={'reason': 'email_conflict', 'email': email},
                            **get_client_info(request)
                        )
                        return RedirectResponse(
                            url="/login?error=oidc_error&message=Email+already+exists+as+local+account"
                        )

                # Check for username conflict
                username = preferred_username or email or oidc_subject[:20]
                base_username = username
                counter = 1
                while session.query(User).filter(User.username == username).first():
                    username = f"{base_username}_{counter}"
                    counter += 1
                    if counter > 100:
                        raise ValueError("Could not generate unique username")

                # Auto-provision new user
                user = User(
                    username=username,
                    password_hash='',  # OIDC users don't have passwords
                    display_name=name,
                    email=email,
                    role=role,
                    auth_provider='oidc',
                    oidc_subject=oidc_subject,
                    is_first_login=False,
                    must_change_password=False,
                    created_at=now,
                    updated_at=now,
                    last_login=now,
                )

                session.add(user)
                session.commit()
                session.refresh(user)

                logger.info(f"OIDC user '{username}' auto-provisioned with role '{role}'")

                # Audit user creation
                _safe_audit_log(
                    session,
                    user.id,
                    user.username,
                    AuditAction.CREATE,
                    AuditEntityType.USER,
                    entity_id=str(user.id),
                    entity_name=user.username,
                    details={'source': 'oidc_auto_provision', 'role': role, 'email': email},
                    **get_client_info(request)
                )

            # Check if user is soft-deleted
            if user.is_deleted:
                logger.warning(f"OIDC login blocked: user '{user.username}' is deactivated")
                _safe_audit_log(
                    session,
                    user.id,
                    user.username,
                    AuditAction.LOGIN_FAILED,
                    AuditEntityType.SESSION,
                    details={'reason': 'user_deactivated'},
                    **get_client_info(request)
                )
                return RedirectResponse(url="/login?error=oidc_error&message=Account+deactivated")

            # Create session
            client_ip = request.client.host if request.client else "unknown"
            signed_token = cookie_session_manager.create_session(
                user_id=user.id,
                username=user.username,
                client_ip=client_ip
            )

            # Audit login
            try:
                log_login(session, user.id, user.username, request, auth_method='oidc')
                session.commit()
            except Exception as e:
                logger.warning(f"Failed to log OIDC login: {e}")

            # Create response with session cookie
            redirect_response = RedirectResponse(url=frontend_redirect, status_code=302)
            redirect_response.set_cookie(
                key="session_id",
                value=signed_token,
                httponly=True,
                secure=not AppConfig.REVERSE_PROXY_MODE,
                samesite="lax",
                max_age=SESSION_MAX_AGE_SECONDS,
                path="/",
                domain=None
            )

            logger.info(f"OIDC login successful: user='{user.username}', role='{user.role}'")
            return redirect_response

        except httpx.HTTPStatusError as e:
            logger.error(f"OIDC token exchange failed: {e}")
            return RedirectResponse(url="/login?error=oidc_error&message=Token+exchange+failed")
        except Exception as e:
            # Log full error for debugging, but return generic message to prevent info leakage
            logger.error(f"OIDC callback error: {e}")
            return RedirectResponse(url="/login?error=oidc_error&message=Authentication+failed")
