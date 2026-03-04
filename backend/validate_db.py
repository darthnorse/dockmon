"""
Database migration validation script for DockMon v2.3.0+
Run: docker exec dockmon python3 backend/validate_db.py
"""

import sqlite3
import sys
import os

DB_PATH = os.environ.get('DOCKMON_DB_PATH', '/app/data/dockmon.db')

# Fall back for local development
if not os.path.exists(DB_PATH):
    DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'dockmon.db')

errors = []
warnings = []


def check(ok: bool, msg: str, warn_only: bool = False):
    if not ok:
        if warn_only:
            warnings.append(msg)
            print(f"  WARN  {msg}")
        else:
            errors.append(msg)
            print(f"  FAIL  {msg}")
    else:
        print(f"  OK    {msg}")


def get_columns(conn, table):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1]: {'type': r[2], 'notnull': r[3], 'default': r[4], 'pk': r[5]} for r in rows}


def get_indexes(conn, table):
    rows = conn.execute(f"PRAGMA index_list({table})").fetchall()
    return {r[1]: {'unique': r[2]} for r in rows}


def table_exists(conn, table):
    r = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return r[0] > 0


def main():
    if not os.path.exists(DB_PATH):
        print(f"Database not found: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    print(f"Database: {DB_PATH}\n")

    # ── Migration version ──
    print("=== Migration Version ===")
    ver = conn.execute("SELECT version_num FROM alembic_version LIMIT 1").fetchone()
    current = ver[0] if ver else "NONE"
    check(current == '036_account_lockout_fixup', f"Version: {current} (expected 036_account_lockout_fixup)")

    # ── Users table ──
    print("\n=== Users Table ===")
    check(table_exists(conn, 'users'), "Table exists")
    cols = get_columns(conn, 'users')

    required_cols = {
        'email': 'TEXT',
        'auth_provider': 'TEXT',
        'oidc_subject': 'TEXT',
        'failed_login_attempts': 'INTEGER',
        'locked_until': 'DATETIME',
        'must_change_password': 'BOOLEAN',
        'deleted_at': 'DATETIME',
        'deleted_by': 'INTEGER',
    }
    for col_name, expected_type in required_cols.items():
        exists = col_name in cols
        check(exists, f"Column: {col_name}")
        if exists:
            actual_type = cols[col_name]['type'].upper()
            check(expected_type in actual_type, f"  {col_name} type: {actual_type} (expected {expected_type})")

    # failed_login_attempts should be NOT NULL with default 0
    if 'failed_login_attempts' in cols:
        check(cols['failed_login_attempts']['notnull'] == 1, "  failed_login_attempts: NOT NULL")
        check(cols['failed_login_attempts']['default'] == "'0'" or cols['failed_login_attempts']['default'] == '0',
              f"  failed_login_attempts: default={cols['failed_login_attempts']['default']} (expected 0)")

    # auth_provider should be NOT NULL with default 'local'
    if 'auth_provider' in cols:
        check(cols['auth_provider']['notnull'] == 1, "  auth_provider: NOT NULL")

    # Check unique index on oidc_subject
    indexes = get_indexes(conn, 'users')
    check('uq_users_oidc_subject' in indexes, "Index: uq_users_oidc_subject (unique)")

    # Verify existing users have email set
    null_emails = conn.execute("SELECT COUNT(*) FROM users WHERE email IS NULL AND deleted_at IS NULL").fetchone()[0]
    check(null_emails == 0, f"All active users have email set ({null_emails} missing)", warn_only=True)

    # ── Groups ──
    print("\n=== Groups & Permissions ===")
    for table in ['custom_groups', 'group_permissions', 'user_group_memberships']:
        check(table_exists(conn, table), f"Table: {table}")

    # System groups exist
    for group_name in ['Administrators', 'Operators', 'Read Only']:
        r = conn.execute("SELECT id, is_system FROM custom_groups WHERE name=?", (group_name,)).fetchone()
        check(r is not None, f"Group: {group_name}")
        if r:
            check(r[1] == 1, f"  {group_name}: is_system=True")
            perms = conn.execute("SELECT COUNT(*) FROM group_permissions WHERE group_id=?", (r[0],)).fetchone()[0]
            check(perms > 0, f"  {group_name}: {perms} permissions")

    # At least one user in Administrators
    admin_gid = conn.execute("SELECT id FROM custom_groups WHERE name='Administrators'").fetchone()
    if admin_gid:
        members = conn.execute("SELECT COUNT(*) FROM user_group_memberships WHERE group_id=?", (admin_gid[0],)).fetchone()[0]
        check(members >= 1, f"Administrators has {members} member(s)")

    # ── OIDC Config ──
    print("\n=== OIDC Config ===")
    check(table_exists(conn, 'oidc_config'), "Table: oidc_config")
    if table_exists(conn, 'oidc_config'):
        oidc_cols = get_columns(conn, 'oidc_config')
        check('default_group_id' in oidc_cols, "Column: default_group_id")
        check('sso_default' in oidc_cols, "Column: sso_default")
        check('disable_pkce_with_secret' in oidc_cols, "Column: disable_pkce_with_secret")

    check(table_exists(conn, 'oidc_group_mappings'), "Table: oidc_group_mappings")

    # ── Audit & Auth Tables ──
    print("\n=== Auth & Audit Tables ===")
    for table in ['audit_log', 'api_keys', 'password_reset_tokens', 'pending_oidc_auth', 'action_tokens']:
        check(table_exists(conn, table), f"Table: {table}")

    if table_exists(conn, 'api_keys'):
        ak_cols = get_columns(conn, 'api_keys')
        check('group_id' in ak_cols, "api_keys: group_id column")
        check('created_by_user_id' in ak_cols, "api_keys: created_by_user_id column")

    # ── Audit columns on existing tables ──
    print("\n=== Audit Columns (created_by/updated_by) ===")
    audit_tables = ['docker_hosts', 'notification_channels', 'tags', 'registry_credentials',
                    'container_desired_states', 'container_http_health_checks', 'update_policies', 'auto_restart_configs']
    for table in audit_tables:
        if table_exists(conn, table):
            cols = get_columns(conn, table)
            has_both = 'created_by' in cols and 'updated_by' in cols
            check(has_both, f"{table}: created_by + updated_by")

    # ── Global Settings ──
    print("\n=== Global Settings ===")
    if table_exists(conn, 'global_settings'):
        gs_cols = get_columns(conn, 'global_settings')
        check('audit_log_retention_days' in gs_cols, "Column: audit_log_retention_days")
        check('session_timeout_hours' in gs_cols, "Column: session_timeout_hours")

    # ── FK integrity spot check ──
    print("\n=== Foreign Key Integrity ===")
    # Memberships point to valid users and groups
    orphan_memberships = conn.execute("""
        SELECT COUNT(*) FROM user_group_memberships m
        LEFT JOIN users u ON m.user_id = u.id
        LEFT JOIN custom_groups g ON m.group_id = g.id
        WHERE u.id IS NULL OR g.id IS NULL
    """).fetchone()[0]
    check(orphan_memberships == 0, f"No orphaned group memberships ({orphan_memberships} found)")

    # Group permissions point to valid groups
    orphan_perms = conn.execute("""
        SELECT COUNT(*) FROM group_permissions p
        LEFT JOIN custom_groups g ON p.group_id = g.id
        WHERE g.id IS NULL
    """).fetchone()[0]
    check(orphan_perms == 0, f"No orphaned group permissions ({orphan_perms} found)")

    # ── Summary ──
    conn.close()
    print(f"\n{'='*50}")
    if errors:
        print(f"FAILED: {len(errors)} error(s), {len(warnings)} warning(s)")
        sys.exit(1)
    elif warnings:
        print(f"PASSED with {len(warnings)} warning(s)")
    else:
        print("ALL CHECKS PASSED")


if __name__ == '__main__':
    main()
