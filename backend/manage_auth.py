#!/usr/bin/env python3
"""
DockMon Auth Management Tool

Control surface for SSO-only enforcement (disable local login). Run via
docker exec (the script lives at /app/backend while the container workdir is
/app, so the path is backend/manage_auth.py):

    docker exec dockmon python backend/manage_auth.py status
    docker exec dockmon python backend/manage_auth.py disable-local-login
    docker exec dockmon python backend/manage_auth.py enable-local-login   # break-glass

disable-local-login refuses to run unless OIDC is usable AND an approved OIDC
admin exists, so you cannot lock yourself out. --force overrides the guard.

Break-glass recovery if SSO breaks while local login is disabled:
    1. docker exec dockmon python backend/manage_auth.py enable-local-login
    2. or set DOCKMON_FORCE_LOCAL_LOGIN=true in compose and restart
"""

import argparse
import sys
from datetime import datetime, timezone

from audit.audit_logger import AuditAction, AuditEntityType, log_audit
from auth.local_login import local_login_effective_disabled
from config.paths import DATABASE_PATH
from config.settings import AppConfig
from database import (
    DatabaseManager,
    GroupPermission,
    OIDCConfig,
    User,
    UserGroupMembership,
)

# Capabilities that mark a user as an administrator for lockout-guard purposes.
# Possessing any of these via a group means the OIDC user can keep administering
# DockMon, so SSO is a viable sole login path.
ADMIN_GUARD_CAPABILITIES = ("users.manage", "groups.manage", "oidc.manage", "settings.manage")

AUDIT_USERNAME = "manage_auth CLI"
ENABLE_COMMAND = "docker exec dockmon python backend/manage_auth.py enable-local-login"


class GuardError(Exception):
    """Raised when the safety guard refuses to disable local login."""


def _get_config(session) -> OIDCConfig | None:
    return session.query(OIDCConfig).filter(OIDCConfig.id == 1).first()


def _oidc_usable(config: OIDCConfig | None) -> bool:
    """OIDC is usable as a login path when enabled and fully configured."""
    return bool(config and config.enabled and config.provider_url and config.client_id)


def _has_approved_oidc_admin(session) -> bool:
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


def _audit_flag_change(session, new_value: bool) -> None:
    log_audit(
        session,
        user_id=None,
        username=AUDIT_USERNAME,
        action=AuditAction.UPDATE,
        entity_type=AuditEntityType.OIDC_CONFIG,
        entity_id="1",
        entity_name="oidc_config",
        details={"local_login_disabled": new_value, "via": "cli"},
    )


def get_status(db) -> dict:
    """Return the effective SSO-only state plus the inputs that produced it."""
    with db.get_session() as session:
        config = _get_config(session)
        db_flag = bool(config.local_login_disabled) if config else False
        return {
            "db_flag": db_flag,
            "env_override": AppConfig.FORCE_LOCAL_LOGIN,
            "effective_disabled": local_login_effective_disabled(db_flag),
            "oidc_enabled": _oidc_usable(config),
            "has_oidc_admin": _has_approved_oidc_admin(session),
        }


def disable_local_login(db, force: bool = False) -> None:
    """Set the DB flag. Refuses (GuardError) without OIDC + an OIDC admin unless forced."""
    with db.get_session() as session:
        config = _get_config(session)

        if not force:
            if not _oidc_usable(config):
                raise GuardError(
                    "OIDC is not enabled/configured. Disabling local login now would "
                    "leave no way in. Enable OIDC first, or re-run with --force if you "
                    "know what you are doing."
                )
            if not _has_approved_oidc_admin(session):
                raise GuardError(
                    "No approved OIDC admin exists. Disabling local login now could "
                    "lock you out. Ensure an approved OIDC user with admin permissions "
                    "exists, or re-run with --force."
                )

        if config is None:
            # --force with no OIDC config yet: create the singleton (model defaults).
            config = OIDCConfig(id=1, enabled=False)
            session.add(config)
        config.local_login_disabled = True
        config.updated_at = datetime.now(timezone.utc)
        _audit_flag_change(session, True)
        session.commit()


def enable_local_login(db) -> None:
    """Clear the DB flag (break-glass). Always succeeds and is idempotent."""
    with db.get_session() as session:
        config = _get_config(session)
        if config is None or not config.local_login_disabled:
            # Already enabled; nothing to change (avoid a spurious audit entry).
            return
        config.local_login_disabled = False
        config.updated_at = datetime.now(timezone.utc)
        _audit_flag_change(session, False)
        session.commit()


def _force_lockout_warning(status: dict) -> str | None:
    """Warning text when --force would disable local login without a usable SSO
    fallback, or None when an OIDC admin can still get in."""
    if status["oidc_enabled"] and status["has_oidc_admin"]:
        return None
    return (
        "WARNING: --force is disabling local login while OIDC is not a usable "
        f"login path (OIDC usable: {status['oidc_enabled']}, approved OIDC admin: "
        f"{status['has_oidc_admin']}). You may lock yourself out. Recover with "
        "DOCKMON_FORCE_LOCAL_LOGIN=true (set in compose, restart) or the "
        "enable-local-login command below."
    )


def _print_status(db) -> None:
    status = get_status(db)
    effective = "DISABLED" if status["effective_disabled"] else "ENABLED"
    print(f"Local login: {effective}")
    print(f"  DB flag (oidc_config.local_login_disabled): {status['db_flag']}")
    print(f"  DOCKMON_FORCE_LOCAL_LOGIN override active:  {status['env_override']}")
    print(f"  OIDC usable as a login path:                {status['oidc_enabled']}")
    print(f"  Approved OIDC admin present:                {status['has_oidc_admin']}")
    if status["env_override"] and status["db_flag"]:
        print(
            "\nNote: the DB flag is set but DOCKMON_FORCE_LOCAL_LOGIN is forcing local "
            "login ON. Remove that env var to let the DB flag take effect."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="DockMon Auth Management Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Show effective local-login state")

    disable_parser = subparsers.add_parser(
        "disable-local-login", help="Disable local password login (SSO-only)"
    )
    disable_parser.add_argument(
        "--force", action="store_true",
        help="Bypass the lockout safety guard (no OIDC admin required)",
    )

    subparsers.add_parser(
        "enable-local-login", help="Re-enable local password login (break-glass)"
    )

    args = parser.parse_args()
    db = DatabaseManager(DATABASE_PATH)

    if args.command == "status":
        _print_status(db)
        return

    if args.command == "disable-local-login":
        if args.force:
            warning = _force_lockout_warning(get_status(db))
            if warning:
                print(warning, file=sys.stderr)
        try:
            disable_local_login(db, force=args.force)
        except GuardError as e:
            print(f"Refused: {e}", file=sys.stderr)
            sys.exit(1)
        print("Local login is now DISABLED. Only SSO can be used to sign in.")
        print(f"\nTo re-enable, run:\n    {ENABLE_COMMAND}")
        print(
            "\nNote: existing local sessions are NOT terminated. Already-signed-in "
            "local users stay logged in until their session expires or the container "
            "is restarted."
        )
        return

    if args.command == "enable-local-login":
        enable_local_login(db)
        print("Local login is now ENABLED.")
        return


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nOperation cancelled.")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
