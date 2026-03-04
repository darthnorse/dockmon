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

import asyncio
import hashlib
import json
import logging
import re
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlencode, urlparse, quote

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from sqlalchemy.exc import IntegrityError

from auth.shared import db, safe_audit_log
from auth.cookie_sessions import cookie_session_manager, get_session_cookie_max_age
from auth.api_key_auth import invalidate_user_groups_cache
from auth.utils import count_other_admins
from config.settings import AppConfig
from utils.base_path import get_base_path
from database import User, OIDCConfig, OIDCGroupMapping, PendingOIDCAuth, CustomGroup, UserGroupMembership
from security.rate_limiting import rate_limit_auth
from audit import log_login, log_login_failure, get_client_info, AuditAction
from audit.audit_logger import AuditEntityType
from utils.client_ip import get_client_ip
from utils.encryption import decrypt_password

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/auth/oidc", tags=["oidc-auth"])

# Pending auth request expiry time
PENDING_AUTH_EXPIRY_MINUTES = 10

# HTTP client timeout for OIDC provider requests
OIDC_HTTP_TIMEOUT = 10.0


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

    # Prevent protocol-relative URLs (//evil.com) and backslash variants (\/evil.com)
    if redirect.startswith('//') or redirect.startswith('/\\') or redirect.startswith('\\'):
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
    provider_url = provider_url.rstrip('/')
    if provider_url.endswith('/.well-known/openid-configuration'):
        provider_url = provider_url[:-len('/.well-known/openid-configuration')]

    if not provider_url.startswith('https://'):
        logger.warning(f"OIDC provider URL is not HTTPS: {provider_url}")
        raise ValueError(f"OIDC provider URL must use HTTPS: {provider_url}")

    discovery_url = f"{provider_url}/.well-known/openid-configuration"

    async with httpx.AsyncClient(timeout=OIDC_HTTP_TIMEOUT) as client:
        response = await client.get(discovery_url)
        response.raise_for_status()
        discovery = response.json()

    # Validate critical endpoints use HTTPS
    for key in ('token_endpoint', 'userinfo_endpoint', 'jwks_uri'):
        endpoint = discovery.get(key)
        if endpoint and not endpoint.startswith('https://'):
            logger.warning(f"OIDC discovery '{key}' is not HTTPS: {endpoint}")
            raise ValueError(f"OIDC discovery '{key}' must use HTTPS: {endpoint}")

    # Validate endpoint origins match provider (warn only — some providers use CDN subdomains)
    provider_origin = urlparse(provider_url).netloc
    for key in ('token_endpoint', 'userinfo_endpoint', 'jwks_uri'):
        endpoint = discovery.get(key)
        if endpoint:
            endpoint_origin = urlparse(endpoint).netloc
            if endpoint_origin != provider_origin:
                logger.warning(
                    f"OIDC discovery '{key}' origin ({endpoint_origin}) "
                    f"differs from provider ({provider_origin})"
                )

    return discovery


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
    }
    # Send client_secret and/or code_verifier as available
    if client_secret:
        data['client_secret'] = client_secret
    if code_verifier:
        data['code_verifier'] = code_verifier

    async with httpx.AsyncClient(timeout=OIDC_HTTP_TIMEOUT) as client:
        response = await client.post(token_endpoint, data=data)
        if response.status_code >= 400:
            logger.error(f"OIDC token endpoint returned {response.status_code}")
        response.raise_for_status()
        return response.json()


async def _fetch_userinfo(userinfo_endpoint: str, access_token: str) -> dict:
    """Fetch user info from OIDC provider."""
    headers = {'Authorization': f'Bearer {access_token}'}

    async with httpx.AsyncClient(timeout=OIDC_HTTP_TIMEOUT) as client:
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


def _get_groups_for_oidc_user(oidc_groups: list, session) -> list[int]:
    """
    Map OIDC groups to DockMon groups.

    Returns ALL matching group IDs (user gets added to all matching groups).
    If no matches, returns [default_group_id] from config.
    If no default configured, returns empty list.

    Args:
        oidc_groups: List of OIDC group values from the provider
        session: Database session

    Returns:
        List of DockMon group IDs to assign to the user
    """
    # Get all group mappings
    mappings = session.query(OIDCGroupMapping).all()

    # Find ALL matching groups (not just highest priority)
    matched_group_ids = []
    for mapping in mappings:
        if mapping.oidc_value in oidc_groups:
            matched_group_ids.append(mapping.group_id)
            logger.debug(f"OIDC group '{mapping.oidc_value}' matched DockMon group {mapping.group_id}")

    if matched_group_ids:
        # Deduplicate in case same group mapped multiple times
        return list(set(matched_group_ids))

    # No matches - use default group from config
    config = session.query(OIDCConfig).filter(OIDCConfig.id == 1).first()
    if config and config.default_group_id:
        logger.debug(f"No OIDC group matches, using default group {config.default_group_id}")
        return [config.default_group_id]

    logger.warning("No OIDC group matches and no default group configured")
    return []


_jwks_cache: dict[str, dict] = {}
_jwks_cache_lock = asyncio.Lock()
_JWKS_CACHE_TTL_SECONDS = 3600  # 1 hour
_JWKS_STALE_MAX_SECONDS = 86400  # 24 hours max stale age


async def _fetch_jwks(jwks_uri: str) -> dict:
    """Fetch and cache the provider's JWKS (JSON Web Key Set).

    Falls back to stale cache on fetch failure to maintain availability.
    Thread-safe via asyncio.Lock to prevent concurrent double-fetches.
    """
    now = time.monotonic()
    cached = _jwks_cache.get(jwks_uri)

    if cached and (now - cached["fetched_at"]) < _JWKS_CACHE_TTL_SECONDS:
        return cached["jwks"]

    async with _jwks_cache_lock:
        # Re-check after acquiring lock (another coroutine may have fetched)
        cached = _jwks_cache.get(jwks_uri)
        if cached and (now - cached["fetched_at"]) < _JWKS_CACHE_TTL_SECONDS:
            return cached["jwks"]

        try:
            async with httpx.AsyncClient(timeout=OIDC_HTTP_TIMEOUT) as client:
                response = await client.get(jwks_uri)
                response.raise_for_status()
                jwks = response.json()
        except Exception as e:
            if cached and (now - cached["fetched_at"]) < _JWKS_STALE_MAX_SECONDS:
                logger.warning(f"JWKS fetch failed ({e}), using stale cache for {jwks_uri}")
                return cached["jwks"]
            raise

        _jwks_cache[jwks_uri] = {"jwks": jwks, "fetched_at": now}
        logger.debug(f"JWKS fetched and cached from {jwks_uri} ({len(jwks.get('keys', []))} keys)")
        return jwks


ALLOWED_JWT_ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]

_JWK_KTY_TO_ALGORITHM_CLASS = {
    "RSA": jwt.algorithms.RSAAlgorithm,
    "EC": jwt.algorithms.ECAlgorithm,
}


def _verify_id_token(
    id_token: str,
    jwks_data: dict,
    provider_url: str,
    client_id: str,
    expected_nonce: str,
) -> dict:
    """Verify an OIDC ID token's JWT signature and validate claims (exp, iss, aud, nonce)."""
    try:
        unverified_header = jwt.get_unverified_header(id_token)
    except jwt.DecodeError as e:
        raise jwt.InvalidTokenError(f"Failed to decode JWT header: {e}")

    kid = unverified_header.get("kid")
    alg = unverified_header.get("alg", "RS256")

    if alg not in ALLOWED_JWT_ALGORITHMS:
        raise jwt.InvalidTokenError(
            f"JWT algorithm '{alg}' is not allowed. "
            f"Allowed algorithms: {ALLOWED_JWT_ALGORITHMS}"
        )

    signing_key = None
    key_data_match = None
    jwk_keys = jwks_data.get("keys", [])

    if kid:
        for key_data in jwk_keys:
            if key_data.get("kid") == kid:
                key_data_match = key_data
                break
    else:
        if jwk_keys:
            key_data_match = jwk_keys[0]
            logger.warning("JWT has no 'kid' header, using first JWKS key")

    if key_data_match is not None:
        kty = key_data_match.get("kty", "RSA")
        alg_class = _JWK_KTY_TO_ALGORITHM_CLASS.get(kty)
        if alg_class is None:
            raise jwt.InvalidTokenError(f"Unsupported JWK key type: {kty}")
        signing_key = alg_class.from_jwk(json.dumps(key_data_match))

    if signing_key is None:
        raise jwt.InvalidTokenError(
            f"No matching key found in JWKS for kid={kid}"
        )

    expected_issuer = provider_url.rstrip("/")

    try:
        claims = jwt.decode(
            id_token,
            signing_key,
            algorithms=[alg],
            audience=client_id,
            issuer=expected_issuer,
            options={
                "verify_exp": True,
                "verify_iss": True,
                "verify_aud": True,
            },
        )
    except jwt.InvalidIssuerError:
        # Fallback: some providers include/omit trailing slash
        alt_issuer = expected_issuer + "/" if not expected_issuer.endswith("/") else expected_issuer.rstrip("/")
        try:
            claims = jwt.decode(
                id_token,
                signing_key,
                algorithms=[alg],
                audience=client_id,
                issuer=alt_issuer,
                options={
                    "verify_exp": True,
                    "verify_iss": True,
                    "verify_aud": True,
                },
            )
            logger.warning(f"OIDC issuer matched with trailing slash variant: {alt_issuer}")
        except jwt.InvalidIssuerError:
            raise jwt.InvalidTokenError(
                f"Issuer mismatch: expected={expected_issuer}"
            )

    token_nonce = claims.get("nonce")
    if token_nonce != expected_nonce:
        raise jwt.InvalidTokenError("Nonce mismatch in ID token")

    return claims


_ALG_TO_HASH = {
    "RS256": "sha256", "ES256": "sha256",
    "RS384": "sha384", "ES384": "sha384",
    "RS512": "sha512", "ES512": "sha512",
}


def _validate_at_hash(access_token: str, at_hash: str, id_token_str: str) -> None:
    """Validate access token hash (at_hash) per OIDC Core Section 3.2.2.9."""
    try:
        header = jwt.get_unverified_header(id_token_str)
    except jwt.DecodeError:
        return  # Can't validate without header
    alg = header.get("alg", "RS256")
    hash_name = _ALG_TO_HASH.get(alg)
    if not hash_name:
        logger.debug(f"Unknown algorithm for at_hash validation: {alg}")
        return
    digest = hashlib.new(hash_name, access_token.encode('ascii')).digest()
    left_half = digest[:len(digest) // 2]
    expected = urlsafe_b64encode(left_half).rstrip(b'=').decode('ascii')
    if expected != at_hash:
        raise jwt.InvalidTokenError(f"at_hash mismatch: expected={expected}, got={at_hash}")


def _sync_oidc_user_groups(session, user, oidc_groups: list, request, now) -> tuple[set, set]:
    """Sync OIDC user's group memberships. Returns (added_groups, removed_groups).

    Full bidirectional sync with admin guard and audit logging.
    Does NOT commit — caller must commit.
    """
    new_group_ids = set(_get_groups_for_oidc_user(oidc_groups, session))

    existing = session.query(UserGroupMembership).filter_by(user_id=user.id).all()
    existing_group_ids = {m.group_id for m in existing}

    added_groups = new_group_ids - existing_group_ids
    removed_groups = existing_group_ids - new_group_ids

    # Admin guard: don't remove last admin from Administrators
    admin_group = session.query(CustomGroup).filter_by(name="Administrators").first()
    if admin_group and admin_group.id in removed_groups:
        if count_other_admins(session, user.id) == 0:
            removed_groups.discard(admin_group.id)
            new_group_ids.add(admin_group.id)
            logger.warning(
                f"Preserved Administrators membership for last admin "
                f"'{user.username}' during OIDC sync"
            )

    for gid in added_groups:
        session.add(UserGroupMembership(
            user_id=user.id,
            group_id=gid,
            added_by=None,
            added_at=now,
        ))
        logger.info(f"OIDC user '{user.username}' added to group {gid}")

    for membership in existing:
        if membership.group_id in removed_groups:
            session.delete(membership)
            logger.info(f"OIDC user '{user.username}' removed from group {membership.group_id}")

    if added_groups or removed_groups:
        safe_audit_log(
            session,
            user.id,
            user.effective_display_name,
            AuditAction.UPDATE,
            AuditEntityType.USER,
            entity_id=str(user.id),
            entity_name=user.effective_display_name,
            details={
                'source': 'oidc_group_sync',
                'added_groups': list(added_groups),
                'removed_groups': list(removed_groups),
                'oidc_groups': oidc_groups,
            },
            **get_client_info(request)
        )

    return added_groups, removed_groups


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

        # Always use PKCE unless provider doesn't support it with client_secret
        skip_pkce = bool(config.client_secret_encrypted) and config.disable_pkce_with_secret
        code_verifier = '' if skip_pkce else _generate_code_verifier()
        code_challenge = '' if skip_pkce else _generate_code_challenge(code_verifier)

        # Build callback URL
        # Only trust proxy headers when REVERSE_PROXY_MODE is enabled
        if AppConfig.REVERSE_PROXY_MODE:
            scheme = request.headers.get('X-Forwarded-Proto', request.url.scheme)
            host = request.headers.get('X-Forwarded-Host', request.headers.get('Host', request.url.netloc))
        else:
            scheme = request.url.scheme
            host = request.headers.get('Host', request.url.netloc)

        base_path = get_base_path().rstrip('/')
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
            'scope': ' '.join(s.strip() for s in config.scopes.replace(',', ' ').split() if s.strip()),
            'state': state,
            'nonce': nonce,
        }
        if code_challenge:
            params['code_challenge'] = code_challenge
            params['code_challenge_method'] = 'S256'

        auth_url = f"{authorization_endpoint}?{urlencode(params)}"

        logger.info(f"OIDC authorize redirect: state={state[:8]}..., redirect_uri={redirect_uri}")
        return RedirectResponse(url=auth_url, status_code=302)


@router.get("/callback")
async def oidc_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
    rate_limit_check: bool = rate_limit_auth,
) -> RedirectResponse:
    """
    Handle OIDC provider callback.

    Validates state, exchanges code for tokens, validates nonce,
    fetches user info, provisions/updates user, and creates session.
    """
    base = get_base_path().rstrip('/')

    # Handle provider errors
    if error:
        logger.warning(f"OIDC callback error: {error} - {error_description}")
        return RedirectResponse(url=f"{base}/login?error=oidc_error&message=auth_failed")

    if not code or not state:
        logger.warning("OIDC callback missing code or state")
        return RedirectResponse(url=f"{base}/login?error=oidc_error&message=missing_code")

    with db.get_session() as session:
        # Clean up expired pending auth entries
        session.query(PendingOIDCAuth).filter(
            PendingOIDCAuth.expires_at < datetime.now(timezone.utc)
        ).delete()

        # Validate state from database
        pending = session.query(PendingOIDCAuth).filter(
            PendingOIDCAuth.state == state
        ).first()

        if not pending:
            logger.warning(f"OIDC callback invalid state: {state[:8]}...")
            return RedirectResponse(url=f"{base}/login?error=oidc_error&message=invalid_state")

        # Check expiry
        if pending.is_expired:
            session.delete(pending)
            session.commit()
            logger.warning(f"OIDC callback expired state: {state[:8]}...")
            return RedirectResponse(url=f"{base}/login?error=oidc_error&message=session_expired")

        # Extract values and delete pending request (one-time use)
        expected_nonce = pending.nonce
        code_verifier = pending.code_verifier
        redirect_uri = pending.redirect_uri
        frontend_redirect = pending.frontend_redirect
        session.delete(pending)
        session.commit()
        config = session.query(OIDCConfig).filter(OIDCConfig.id == 1).first()

        if not config or not config.enabled:
            return RedirectResponse(url=f"{base}/login?error=oidc_error&message=oidc_disabled")

        if not config.provider_url:
            return RedirectResponse(url=f"{base}/login?error=oidc_error&message=oidc_not_configured")

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

            logger.debug(f"OIDC token response keys: {list(tokens.keys())}, scope: {tokens.get('scope', 'not returned')}")

            # Require id_token when openid scope is configured
            configured_scopes = {s.strip() for s in config.scopes.replace(',', ' ').split() if s.strip()}
            if 'openid' in configured_scopes and not id_token:
                raise ValueError("Provider returned no id_token despite 'openid' scope")

            # Verify ID token JWT signature and validate claims
            id_token_claims = None
            if id_token:
                jwks_uri = discovery.get('jwks_uri')
                if not jwks_uri:
                    raise ValueError("Missing jwks_uri in discovery document")

                try:
                    jwks_data = await _fetch_jwks(jwks_uri)
                    id_token_claims = _verify_id_token(
                        id_token=id_token,
                        jwks_data=jwks_data,
                        provider_url=config.provider_url,
                        client_id=config.client_id,
                        expected_nonce=expected_nonce,
                    )
                    logger.info("OIDC ID token verified successfully")

                    # Validate at_hash if present (OIDC Core 3.2.2.9)
                    if id_token_claims and access_token:
                        at_hash_claim = id_token_claims.get('at_hash')
                        if at_hash_claim:
                            _validate_at_hash(access_token, at_hash_claim, id_token)

                except jwt.InvalidTokenError as e:
                    logger.warning(f"OIDC ID token verification failed: {e}")
                    return RedirectResponse(url=f"{base}/login?error=oidc_error&message=token_verification_failed")
                except Exception as e:
                    logger.error(f"OIDC ID token verification error: {e}")
                    return RedirectResponse(url=f"{base}/login?error=oidc_error&message=token_verification_failed")

            # Fetch user info from provider (server-to-server, authenticated via access token)
            userinfo = None
            if userinfo_endpoint:
                try:
                    userinfo = await _fetch_userinfo(userinfo_endpoint, access_token)
                except httpx.HTTPStatusError as e:
                    logger.warning(f"OIDC userinfo request failed ({e.response.status_code})")
            if not userinfo:
                raise ValueError("Failed to fetch user information from provider")

            # Extract user info - prefer ID token claims where available
            logger.info(f"OIDC userinfo/claims keys: {list(userinfo.keys())}")
            oidc_subject = userinfo.get('sub')
            email = userinfo.get('email')
            preferred_username = userinfo.get('preferred_username', email)
            name = userinfo.get('name', preferred_username)

            if not oidc_subject:
                raise ValueError("No 'sub' claim in userinfo")

            # Cross-check: if ID token was verified, its 'sub' is authoritative
            if id_token_claims:
                id_token_sub = id_token_claims.get('sub')
                if id_token_sub and id_token_sub != oidc_subject:
                    raise ValueError(
                        f"Subject mismatch: id_token sub='{id_token_sub}' vs userinfo sub='{oidc_subject}'"
                    )
                # Use ID token sub as authoritative
                oidc_subject = id_token_sub or oidc_subject

            # Get groups from configured claim (with type safety)
            # Try userinfo first, fall back to ID token claims
            groups_claim = config.claim_for_groups
            groups_raw = userinfo.get(groups_claim)
            if groups_raw is None and id_token_claims:
                groups_raw = id_token_claims.get(groups_claim)
            oidc_groups = _normalize_groups_claim(groups_raw)

            logger.info(f"OIDC callback: sub={oidc_subject}, email={email}, groups_count={len(oidc_groups) if oidc_groups else 0}")
            logger.debug(f"OIDC groups detail: {oidc_groups}")

            # Find or create user
            user = session.query(User).filter(User.oidc_subject == oidc_subject).first()

            now = datetime.now(timezone.utc)

            if user:
                # Existing OIDC user - check groups before sync
                new_group_ids = set(_get_groups_for_oidc_user(oidc_groups, session))

                if not new_group_ids:
                    logger.warning(f"OIDC login blocked: user '{user.username}' has no group memberships")
                    safe_audit_log(
                        session,
                        user.id,
                        user.effective_display_name,
                        AuditAction.LOGIN_FAILED,
                        AuditEntityType.SESSION,
                        details={'reason': 'no_matching_groups', 'oidc_groups': oidc_groups},
                        **get_client_info(request)
                    )
                    session.commit()
                    return RedirectResponse(
                        url=f"{base}/login?error=oidc_error&message=no_matching_groups"
                    )

                # Full bidirectional group sync with admin guard
                _sync_oidc_user_groups(session, user, oidc_groups, request, now)

                user.last_login = now
                user.updated_at = now

                # Sync profile from OIDC provider
                if name and user.display_name != name:
                    user.display_name = name
                if email and user.email != email:
                    email_conflict = session.query(User).filter(
                        User.email == email,
                        User.id != user.id,
                    ).first()
                    if email_conflict:
                        logger.warning(f"OIDC email sync skipped: '{email}' already used by user '{email_conflict.username}'")
                    else:
                        user.email = email

                session.commit()
                session.refresh(user)

                # Invalidate user's group cache after sync
                invalidate_user_groups_cache(user.id)

            else:
                # New OIDC user - check for email conflict
                if email:
                    existing_email = session.query(User).filter(
                        User.email == email,
                    ).first()
                    if existing_email:
                        logger.warning(f"OIDC login blocked: email '{email}' already used by user '{existing_email.username}'")
                        safe_audit_log(
                            session,
                            None,
                            name or preferred_username,
                            AuditAction.LOGIN_FAILED,
                            AuditEntityType.SESSION,
                            details={'reason': 'email_conflict', 'email': email},
                            **get_client_info(request)
                        )
                        session.commit()  # Commit the audit log
                        return RedirectResponse(
                            url=f"{base}/login?error=oidc_error&message=email_conflict"
                        )

                # Sanitize username: only allow safe characters, truncate to reasonable length
                raw_username = preferred_username or email or oidc_subject[:20]
                # Strip control chars and non-ASCII, keep alphanumeric + safe punctuation
                sanitized = re.sub(r'[^a-zA-Z0-9._@-]', '_', raw_username)
                username = sanitized[:64]
                base_username = username
                counter = 1
                while session.query(User).filter(User.username == username).first():
                    username = f"{base_username}_{counter}"
                    counter += 1
                    if counter > 100:
                        raise ValueError("Could not generate unique username")

                # Check if this is the first user ever (auto-assign to Administrators)
                user_count = session.query(User).count()
                is_first_user = user_count == 0

                if is_first_user:
                    # First user ever - assign to Administrators regardless of OIDC claims
                    admin_group = session.query(CustomGroup).filter_by(name="Administrators").first()
                    if admin_group:
                        group_ids = [admin_group.id]
                        logger.info(f"First OIDC user '{username}' auto-assigned to Administrators")
                    else:
                        # Fallback: use OIDC-based groups if Administrators doesn't exist
                        group_ids = _get_groups_for_oidc_user(oidc_groups, session)
                        logger.warning("Administrators group not found, using OIDC-based groups")
                else:
                    # Normal flow - map OIDC groups to DockMon groups
                    group_ids = _get_groups_for_oidc_user(oidc_groups, session)

                # Validate user will have at least one group
                if not group_ids:
                    logger.error(f"OIDC user '{username}' would have no groups - login blocked")
                    safe_audit_log(
                        session,
                        None,
                        name or username,
                        AuditAction.LOGIN_FAILED,
                        AuditEntityType.SESSION,
                        details={'reason': 'no_matching_groups', 'oidc_groups': oidc_groups},
                        **get_client_info(request)
                    )
                    session.commit()  # Commit the audit log
                    return RedirectResponse(
                        url=f"{base}/login?error=oidc_error&message=no_matching_groups"
                    )

                # Auto-provision new user (no role field - groups provide permissions)
                user = User(
                    username=username,
                    password_hash='!OIDC_NO_PASSWORD',  # Sentinel: never matches any hash algorithm
                    display_name=name,
                    email=email,
                    role='user',  # Legacy field - kept for compatibility but groups determine permissions
                    auth_provider='oidc',
                    oidc_subject=oidc_subject,
                    is_first_login=False,
                    must_change_password=False,
                    created_at=now,
                    updated_at=now,
                    last_login=now,
                )

                session.add(user)
                try:
                    session.flush()  # Get user.id for group memberships
                except IntegrityError:
                    # Race condition: concurrent callback created this user first
                    session.rollback()
                    user = session.query(User).filter(User.oidc_subject == oidc_subject).first()
                    if not user:
                        # May have been an email conflict instead of oidc_subject conflict
                        logger.error("OIDC user creation race: IntegrityError but user not found by oidc_subject")
                        return RedirectResponse(url=f"{base}/login?error=oidc_error&message=auth_failed")

                    logger.info(f"OIDC user creation race resolved: found existing user '{user.username}'")
                    # Full bidirectional group sync (same as existing-user path)
                    _sync_oidc_user_groups(session, user, oidc_groups, request, now)
                    session.commit()
                    invalidate_user_groups_cache(user.id)
                else:
                    # Add user to all matching groups
                    for gid in group_ids:
                        session.add(UserGroupMembership(
                            user_id=user.id,
                            group_id=gid,
                            added_by=None,  # System-assigned via OIDC
                            added_at=now
                        ))

                    # Audit user creation (before commit for atomicity)
                    safe_audit_log(
                        session,
                        user.id,
                        user.effective_display_name,
                        AuditAction.CREATE,
                        AuditEntityType.USER,
                        entity_id=str(user.id),
                        entity_name=user.effective_display_name,
                        details={
                            'source': 'oidc_auto_provision',
                            'groups': group_ids,
                            'oidc_groups': oidc_groups,
                            'email': email,
                            'is_first_user': is_first_user
                        },
                        **get_client_info(request)
                    )

                    session.commit()
                    session.refresh(user)

                logger.info(f"OIDC user '{username}' auto-provisioned with groups {group_ids}")

                # Invalidate cache for new user (defensive - ensures fresh state)
                invalidate_user_groups_cache(user.id)

            # Create session
            client_ip = get_client_ip(request)
            signed_token = cookie_session_manager.create_session(
                user_id=user.id,
                username=user.username,
                client_ip=client_ip,
                display_name=user.effective_display_name
            )

            # Audit login
            try:
                log_login(session, user.id, user.effective_display_name, request, auth_method='oidc')
                session.commit()
            except Exception as e:
                logger.warning(f"Failed to log OIDC login: {e}")

            # Create response with session cookie
            redirect_response = RedirectResponse(url=frontend_redirect, status_code=302)
            redirect_response.set_cookie(
                key="session_id",
                value=signed_token,
                httponly=True,
                secure=True,
                samesite="lax",
                max_age=get_session_cookie_max_age(),
                path="/",
                domain=None
            )

            # Get user's current groups for logging
            user_memberships = session.query(UserGroupMembership).filter_by(user_id=user.id).all()
            user_group_ids = [m.group_id for m in user_memberships]
            user_groups = session.query(CustomGroup).filter(CustomGroup.id.in_(user_group_ids)).all() if user_group_ids else []
            group_names = [g.name for g in user_groups]

            logger.info(f"OIDC login successful: user='{user.username}', groups={group_names}")
            return redirect_response

        except httpx.HTTPStatusError as e:
            logger.error(f"OIDC token exchange failed: status={e.response.status_code if e.response else 'unknown'}")
            return RedirectResponse(url=f"{base}/login?error=oidc_error&message=token_exchange_failed")
        except Exception as e:
            # Log full error for debugging, but return generic message to prevent info leakage
            logger.error(f"OIDC callback error: {e}")
            return RedirectResponse(url=f"{base}/login?error=oidc_error&message=auth_failed")
