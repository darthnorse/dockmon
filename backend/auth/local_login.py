"""
SSO-only enforcement (disable local login).

Single source of truth for the *effective* local-login-disabled state, shared by
the login handler, the public OIDC status endpoint, and the manage_auth CLI.

Effective state = the oidc_config.local_login_disabled DB flag AND NOT the
DOCKMON_FORCE_LOCAL_LOGIN env override. The env override is a break-glass that
forces local login back on without touching the database, so recovery works even
when SSO is broken and the DB flag is awkward to flip.
"""

from config.settings import AppConfig
from database import OIDCConfig


def local_login_effective_disabled(db_flag: bool) -> bool:
    """Resolve whether local password login is effectively disabled.

    Args:
        db_flag: The oidc_config.local_login_disabled column value.

    Returns:
        True if local logins must be rejected; False if they are allowed.
        The env override always wins, so it can never be disabled while
        DOCKMON_FORCE_LOCAL_LOGIN is set.
    """
    if AppConfig.FORCE_LOCAL_LOGIN:
        return False
    return bool(db_flag)


def is_local_login_effectively_disabled(session) -> bool:
    """Effective SSO-only state for a DB session.

    The env override short-circuits the DB read entirely (the break-glass forces
    local login on regardless of the flag), so the hot login path skips the query
    on every deployment that uses the override.
    """
    if AppConfig.FORCE_LOCAL_LOGIN:
        return False
    db_flag = bool(
        session.query(OIDCConfig.local_login_disabled)
        .filter(OIDCConfig.id == 1)
        .scalar()
    )
    return local_login_effective_disabled(db_flag)
