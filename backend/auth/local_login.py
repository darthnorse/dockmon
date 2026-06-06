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
from database import GroupPermission, OIDCConfig, User, UserGroupMembership


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


# Capabilities that mark a user as an administrator for lockout-guard purposes.
# Possessing any of these via a group means an OIDC user can keep administering
# DockMon, so SSO is a viable sole login path.
ADMIN_GUARD_CAPABILITIES = ("users.manage", "groups.manage", "oidc.manage", "settings.manage")


def oidc_usable(config) -> bool:
    """OIDC is usable as a login path when enabled and fully configured."""
    return bool(config and config.enabled and config.provider_url and config.client_id)


def has_approved_oidc_admin(session) -> bool:
    """True if at least one approved OIDC user has an admin-tier capability."""
    return session.query(User.id).join(
        UserGroupMembership, UserGroupMembership.user_id == User.id
    ).join(
        GroupPermission, GroupPermission.group_id == UserGroupMembership.group_id
    ).filter(
        User.auth_provider == "oidc",
        User.approved.is_(True),
        GroupPermission.allowed.is_(True),
        GroupPermission.capability.in_(ADMIN_GUARD_CAPABILITIES),
    ).first() is not None
