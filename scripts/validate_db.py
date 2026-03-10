"""
Database migration validation script for DockMon v2.3.0+
Run: cat scripts/validate_db.py | docker exec -i dockmon python3 -
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
    result = {}
    for r in rows:
        idx_name = r[1]
        idx_unique = r[2]
        # Get columns in this index
        idx_cols = conn.execute(f"PRAGMA index_info({idx_name})").fetchall()
        col_names = [c[2] for c in idx_cols]
        result[idx_name] = {'unique': idx_unique, 'columns': col_names}
    return result


def table_exists(conn, table):
    r = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return r[0] > 0


def get_fk_map(conn, table):
    """Get foreign key map: column -> on_delete policy"""
    fks = conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    return {fk[3]: fk[6] for fk in fks}


# Expected capabilities per group (from migration file)
ALL_CAPABILITIES = [
    'hosts.manage', 'hosts.view',
    'stacks.edit', 'stacks.deploy', 'stacks.view', 'stacks.view_env',
    'containers.operate', 'containers.shell', 'containers.update',
    'containers.view', 'containers.logs', 'containers.view_env',
    'healthchecks.manage', 'healthchecks.test', 'healthchecks.view',
    'batch.create', 'batch.view',
    'policies.manage', 'policies.view',
    'alerts.manage', 'alerts.view',
    'notifications.manage', 'notifications.view',
    'registry.manage', 'registry.view',
    'agents.manage', 'agents.view',
    'settings.manage',
    'users.manage',
    'oidc.manage',
    'groups.manage',
    'audit.view',
    'apikeys.manage_other',
    'tags.manage', 'tags.view',
    'events.view',
]

OPERATOR_CAPABILITIES = [
    'hosts.view',
    'stacks.deploy', 'stacks.view', 'stacks.view_env',
    'containers.operate', 'containers.view', 'containers.logs', 'containers.view_env',
    'healthchecks.test', 'healthchecks.view',
    'batch.create', 'batch.view',
    'policies.view',
    'alerts.view',
    'notifications.view',
    'agents.view',
    'tags.manage', 'tags.view',
    'events.view',
]

READONLY_CAPABILITIES = [
    'hosts.view',
    'stacks.view',
    'containers.view', 'containers.logs',
    'healthchecks.view',
    'batch.view',
    'policies.view',
    'alerts.view',
    'notifications.view',
    'agents.view',
    'tags.view',
    'events.view',
]


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
    check(current == '034_v2_3_0', f"Version: {current} (expected 034_v2_3_0)")

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

    # must_change_password should be NOT NULL with default 0
    if 'must_change_password' in cols:
        check(cols['must_change_password']['notnull'] == 1, "  must_change_password: NOT NULL")

    # auth_provider should be NOT NULL with default 'local'
    if 'auth_provider' in cols:
        check(cols['auth_provider']['notnull'] == 1, "  auth_provider: NOT NULL")

    # Check unique index on oidc_subject
    indexes = get_indexes(conn, 'users')
    check('uq_users_oidc_subject' in indexes, "Index: uq_users_oidc_subject (unique)")

    # Verify existing users have email set
    null_emails = conn.execute("SELECT COUNT(*) FROM users WHERE email IS NULL").fetchone()[0]
    check(null_emails == 0, f"All active users have email set ({null_emails} missing)", warn_only=True)

    # OIDC password sentinel: OIDC users must not have empty/null password_hash
    oidc_bad_pw = conn.execute(
        "SELECT COUNT(*) FROM users WHERE auth_provider = 'oidc' AND (password_hash = '' OR password_hash IS NULL)"
    ).fetchone()[0]
    check(oidc_bad_pw == 0, f"OIDC users: no empty/null password_hash ({oidc_bad_pw} found)", warn_only=True)

    # ── Groups ──
    print("\n=== Groups & Permissions ===")
    for table in ['custom_groups', 'group_permissions', 'user_group_memberships']:
        check(table_exists(conn, table), f"Table: {table}")

    # custom_groups structure
    if table_exists(conn, 'custom_groups'):
        cg_indexes = get_indexes(conn, 'custom_groups')
        has_name_unique = any(
            idx['unique'] == 1 and 'name' in idx['columns']
            for idx in cg_indexes.values()
        )
        check(has_name_unique, "custom_groups: name unique")
        cg_fk_map = get_fk_map(conn, 'custom_groups')
        check(cg_fk_map.get('created_by') == 'SET NULL',
              f"custom_groups.created_by: on_delete={cg_fk_map.get('created_by', 'MISSING')} (expected SET NULL)")
        check(cg_fk_map.get('updated_by') == 'SET NULL',
              f"custom_groups.updated_by: on_delete={cg_fk_map.get('updated_by', 'MISSING')} (expected SET NULL)")

    # System groups exist with correct capabilities
    group_capability_map = {
        'Administrators': ALL_CAPABILITIES,
        'Operators': OPERATOR_CAPABILITIES,
        'Read Only': READONLY_CAPABILITIES,
    }
    group_ids = {}  # name -> id

    for group_name, expected_caps in group_capability_map.items():
        r = conn.execute("SELECT id, is_system FROM custom_groups WHERE name=?", (group_name,)).fetchone()
        check(r is not None, f"Group: {group_name}")
        if r:
            group_ids[group_name] = r[0]
            check(r[1] == 1, f"  {group_name}: is_system=True")

            # Get actual capabilities for this group
            actual_caps = conn.execute(
                "SELECT capability FROM group_permissions WHERE group_id=? AND allowed=1",
                (r[0],)
            ).fetchall()
            actual_cap_set = {row[0] for row in actual_caps}
            expected_cap_set = set(expected_caps)

            check(len(actual_caps) == len(expected_caps),
                  f"  {group_name}: {len(actual_caps)} permissions (expected {len(expected_caps)})")

            missing = expected_cap_set - actual_cap_set
            if missing:
                check(False, f"  {group_name}: missing capabilities: {sorted(missing)}")
            else:
                check(True, f"  {group_name}: all expected capabilities present")

    # At least one user in Administrators
    admin_gid = group_ids.get('Administrators')
    if admin_gid:
        members = conn.execute("SELECT COUNT(*) FROM user_group_memberships WHERE group_id=?", (admin_gid,)).fetchone()[0]
        check(members >= 1, f"Administrators has {members} member(s)")

    # user_group_memberships unique constraint + indexes + FKs
    if table_exists(conn, 'user_group_memberships'):
        ugm_indexes = get_indexes(conn, 'user_group_memberships')
        has_unique = any(
            idx['unique'] == 1 and set(idx['columns']) == {'user_id', 'group_id'}
            for idx in ugm_indexes.values()
        )
        check(has_unique, "user_group_memberships: unique(user_id, group_id)")
        check('idx_user_group_user' in ugm_indexes, "user_group_memberships: idx_user_group_user")
        check('idx_user_group_group' in ugm_indexes, "user_group_memberships: idx_user_group_group")
        ugm_fk_map = get_fk_map(conn, 'user_group_memberships')
        check(ugm_fk_map.get('group_id') == 'CASCADE',
              f"user_group_memberships.group_id: on_delete={ugm_fk_map.get('group_id', 'MISSING')} (expected CASCADE)")
        check(ugm_fk_map.get('added_by') == 'SET NULL',
              f"user_group_memberships.added_by: on_delete={ugm_fk_map.get('added_by', 'MISSING')} (expected SET NULL)")

    # group_permissions unique constraint + index + FK
    if table_exists(conn, 'group_permissions'):
        gp_indexes = get_indexes(conn, 'group_permissions')
        has_unique = any(
            idx['unique'] == 1 and set(idx['columns']) == {'group_id', 'capability'}
            for idx in gp_indexes.values()
        )
        check(has_unique, "group_permissions: unique(group_id, capability)")
        check('idx_group_permissions_group' in gp_indexes, "group_permissions: idx_group_permissions_group")
        gp_fk_map = get_fk_map(conn, 'group_permissions')
        check(gp_fk_map.get('group_id') == 'CASCADE',
              f"group_permissions.group_id: on_delete={gp_fk_map.get('group_id', 'MISSING')} (expected CASCADE)")

    # ── OIDC Config ──
    print("\n=== OIDC Config ===")
    check(table_exists(conn, 'oidc_config'), "Table: oidc_config")
    if table_exists(conn, 'oidc_config'):
        oidc_cols = get_columns(conn, 'oidc_config')
        for col in ['enabled', 'provider_url', 'client_id', 'client_secret_encrypted',
                     'scopes', 'claim_for_groups', 'default_group_id', 'sso_default',
                     'disable_pkce_with_secret']:
            check(col in oidc_cols, f"Column: {col}")

        # FK on default_group_id -> custom_groups with SET NULL
        oidc_fk_map = get_fk_map(conn, 'oidc_config')
        check(oidc_fk_map.get('default_group_id') == 'SET NULL',
              f"oidc_config.default_group_id: on_delete={oidc_fk_map.get('default_group_id', 'MISSING')} (expected SET NULL)")

        # Default record exists (singleton, id=1)
        oidc_row = conn.execute("SELECT id, enabled FROM oidc_config WHERE id=1").fetchone()
        check(oidc_row is not None, "oidc_config: default record exists (id=1)")

        # default_group_id should be set to Read Only group
        readonly_gid = group_ids.get('Read Only')
        if readonly_gid:
            oidc_default_gid = conn.execute("SELECT default_group_id FROM oidc_config WHERE id=1").fetchone()
            if oidc_default_gid:
                check(oidc_default_gid[0] == readonly_gid,
                      f"oidc_config.default_group_id = {oidc_default_gid[0]} (expected {readonly_gid} = Read Only)")

    check(table_exists(conn, 'oidc_group_mappings'), "Table: oidc_group_mappings")
    if table_exists(conn, 'oidc_group_mappings'):
        ogm_cols = get_columns(conn, 'oidc_group_mappings')
        check('oidc_value' in ogm_cols, "oidc_group_mappings: oidc_value column")
        check('group_id' in ogm_cols, "oidc_group_mappings: group_id column")
        # oidc_value should be unique
        ogm_indexes = get_indexes(conn, 'oidc_group_mappings')
        has_unique_oidc_val = any(
            idx['unique'] == 1 and 'oidc_value' in idx['columns']
            for idx in ogm_indexes.values()
        )
        check(has_unique_oidc_val, "oidc_group_mappings: oidc_value unique")
        # group_id FK CASCADE
        ogm_fk_map = get_fk_map(conn, 'oidc_group_mappings')
        check(ogm_fk_map.get('group_id') == 'CASCADE',
              f"oidc_group_mappings.group_id: on_delete={ogm_fk_map.get('group_id', 'MISSING')} (expected CASCADE)")

    # ── Legacy tables ──
    print("\n=== Legacy Tables ===")
    check(table_exists(conn, 'role_permissions'), "Table: role_permissions")
    if table_exists(conn, 'role_permissions'):
        rp_cols = get_columns(conn, 'role_permissions')
        check('role' in rp_cols and 'capability' in rp_cols and 'allowed' in rp_cols,
              "role_permissions: has role, capability, allowed columns")

    check(table_exists(conn, 'oidc_role_mappings'), "Table: oidc_role_mappings")
    if table_exists(conn, 'oidc_role_mappings'):
        orm_cols = get_columns(conn, 'oidc_role_mappings')
        check('oidc_value' in orm_cols and 'dockmon_role' in orm_cols,
              "oidc_role_mappings: has oidc_value, dockmon_role columns")
        orm_indexes = get_indexes(conn, 'oidc_role_mappings')
        check('idx_oidc_mapping_value' in orm_indexes, "oidc_role_mappings: idx_oidc_mapping_value")

    check(table_exists(conn, 'stack_metadata'), "Table: stack_metadata")
    if table_exists(conn, 'stack_metadata'):
        sm_cols = get_columns(conn, 'stack_metadata')
        check('stack_name' in sm_cols and 'created_by' in sm_cols and 'updated_by' in sm_cols,
              "stack_metadata: has stack_name, created_by, updated_by columns")
        # FK checks
        sm_fk_map = get_fk_map(conn, 'stack_metadata')
        check(sm_fk_map.get('created_by') == 'SET NULL',
              f"stack_metadata.created_by: on_delete={sm_fk_map.get('created_by', 'MISSING')} (expected SET NULL)")
        check(sm_fk_map.get('updated_by') == 'SET NULL',
              f"stack_metadata.updated_by: on_delete={sm_fk_map.get('updated_by', 'MISSING')} (expected SET NULL)")

    # ── Auth & Audit Tables ──
    print("\n=== Auth & Audit Tables ===")
    for table in ['audit_log', 'api_keys', 'password_reset_tokens', 'pending_oidc_auth', 'action_tokens']:
        check(table_exists(conn, table), f"Table: {table}")

    # password_reset_tokens detailed checks
    if table_exists(conn, 'password_reset_tokens'):
        prt_cols = get_columns(conn, 'password_reset_tokens')
        for col in ['user_id', 'token_hash', 'expires_at', 'used_at', 'created_at']:
            check(col in prt_cols, f"password_reset_tokens: {col} column")
        # user_id FK with CASCADE
        prt_fk_map = get_fk_map(conn, 'password_reset_tokens')
        check(prt_fk_map.get('user_id') == 'CASCADE',
              f"password_reset_tokens.user_id: on_delete={prt_fk_map.get('user_id', 'MISSING')} (expected CASCADE)")
        # token_hash unique
        prt_indexes = get_indexes(conn, 'password_reset_tokens')
        has_token_unique = any(
            idx['unique'] == 1 and 'token_hash' in idx['columns']
            for idx in prt_indexes.values()
        )
        check(has_token_unique, "password_reset_tokens: token_hash unique")
        # expires_at index
        has_expires_idx = any(
            'expires_at' in idx['columns']
            for idx in prt_indexes.values()
        )
        check(has_expires_idx, "password_reset_tokens: expires_at indexed")

    # api_keys detailed checks
    if table_exists(conn, 'api_keys'):
        ak_cols = get_columns(conn, 'api_keys')
        check('group_id' in ak_cols, "api_keys: group_id column")
        check('created_by_user_id' in ak_cols, "api_keys: created_by_user_id column")

        # group_id should be NOT NULL
        if 'group_id' in ak_cols:
            check(ak_cols['group_id']['notnull'] == 1, "api_keys.group_id: NOT NULL")

        ak_fk_map = get_fk_map(conn, 'api_keys')
        check(ak_fk_map.get('group_id') in ('RESTRICT', 'NO ACTION'),
              f"api_keys.group_id: on_delete={ak_fk_map.get('group_id', 'MISSING')} (expected RESTRICT)")
        check(ak_fk_map.get('created_by_user_id') == 'SET NULL',
              f"api_keys.created_by_user_id: on_delete={ak_fk_map.get('created_by_user_id', 'MISSING')} (expected SET NULL)")

        # No api_keys should have NULL group_id
        null_gid = conn.execute("SELECT COUNT(*) FROM api_keys WHERE group_id IS NULL").fetchone()[0]
        check(null_gid == 0, f"api_keys: no NULL group_id values ({null_gid} found)")

    # audit_log detailed checks
    if table_exists(conn, 'audit_log'):
        al_cols = get_columns(conn, 'audit_log')
        audit_log_expected = ['user_id', 'username', 'action', 'entity_type', 'entity_id',
                              'entity_name', 'host_id', 'host_name', 'details',
                              'ip_address', 'user_agent', 'created_at']
        for col in audit_log_expected:
            check(col in al_cols, f"audit_log: {col} column")

        # Check indexes
        al_indexes = get_indexes(conn, 'audit_log')
        expected_indexes = {
            'idx_audit_log_user': ['user_id'],
            'idx_audit_log_entity': ['entity_type', 'entity_id'],
            'idx_audit_log_created': ['created_at'],
            'idx_audit_log_action': ['action'],
        }
        for idx_name, expected_cols in expected_indexes.items():
            if idx_name in al_indexes:
                check(True, f"audit_log: index {idx_name}")
            else:
                check(False, f"audit_log: index {idx_name} missing")

        # FK on user_id
        al_fk_map = get_fk_map(conn, 'audit_log')
        check(al_fk_map.get('user_id') == 'SET NULL',
              f"audit_log.user_id: on_delete={al_fk_map.get('user_id', 'MISSING')} (expected SET NULL)")

    # ── Audit columns on existing tables ──
    print("\n=== Audit Columns (created_by/updated_by) ===")
    audit_tables = ['docker_hosts', 'notification_channels', 'tags', 'registry_credentials',
                    'container_desired_states', 'container_http_health_checks', 'update_policies', 'auto_restart_configs']
    for table in audit_tables:
        if table_exists(conn, table):
            cols = get_columns(conn, table)
            has_both = 'created_by' in cols and 'updated_by' in cols
            check(has_both, f"{table}: created_by + updated_by")
            if has_both:
                fk_map = get_fk_map(conn, table)
                check(fk_map.get('created_by') == 'SET NULL',
                      f"  {table}.created_by: on_delete={fk_map.get('created_by', 'MISSING')} (expected SET NULL)")
                check(fk_map.get('updated_by') == 'SET NULL',
                      f"  {table}.updated_by: on_delete={fk_map.get('updated_by', 'MISSING')} (expected SET NULL)")

                # Existing records should have created_by = 1
                null_created = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE created_by IS NULL"
                ).fetchone()[0]
                check(null_created == 0,
                      f"  {table}: no NULL created_by ({null_created} found)", warn_only=True)

    # ── Global Settings ──
    print("\n=== Global Settings ===")
    if table_exists(conn, 'global_settings'):
        gs_cols = get_columns(conn, 'global_settings')
        check('audit_log_retention_days' in gs_cols, "Column: audit_log_retention_days")
        if 'audit_log_retention_days' in gs_cols:
            check(gs_cols['audit_log_retention_days']['notnull'] == 1,
                  "  audit_log_retention_days: NOT NULL")
            default = gs_cols['audit_log_retention_days']['default']
            check(default in ("'90'", '90'),
                  f"  audit_log_retention_days: default={default} (expected 90)")

        check('session_timeout_hours' in gs_cols, "Column: session_timeout_hours")
        if 'session_timeout_hours' in gs_cols:
            check(gs_cols['session_timeout_hours']['notnull'] == 1,
                  "  session_timeout_hours: NOT NULL")
            default = gs_cols['session_timeout_hours']['default']
            check(default in ("'24'", '24'),
                  f"  session_timeout_hours: default={default} (expected 24)")

    # ── FK on_delete policies ──
    print("\n=== FK on_delete Policies ===")
    fk_expectations = [
        ('user_prefs', 'user_id', 'CASCADE'),
        ('registration_tokens', 'created_by_user_id', 'SET NULL'),
        ('batch_jobs', 'user_id', 'SET NULL'),
        ('deployments', 'user_id', 'SET NULL'),
        ('user_group_memberships', 'user_id', 'CASCADE'),
        ('audit_log', 'user_id', 'SET NULL'),
    ]
    for table, col, expected in fk_expectations:
        if table_exists(conn, table):
            fk_map = get_fk_map(conn, table)
            actual = fk_map.get(col, 'MISSING')
            check(actual == expected, f"{table}.{col}: on_delete={actual} (expected {expected})")

    # Columns with SET NULL FK must be nullable for the policy to work
    if table_exists(conn, 'deployments'):
        dep_cols = get_columns(conn, 'deployments')
        if 'user_id' in dep_cols:
            check(dep_cols['user_id']['notnull'] == 0, "deployments.user_id: nullable (required for SET NULL FK)")

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

    # API keys point to valid groups
    if table_exists(conn, 'api_keys') and 'group_id' in get_columns(conn, 'api_keys'):
        orphan_apikeys = conn.execute("""
            SELECT COUNT(*) FROM api_keys ak
            LEFT JOIN custom_groups g ON ak.group_id = g.id
            WHERE g.id IS NULL
        """).fetchone()[0]
        check(orphan_apikeys == 0, f"No orphaned api_key group references ({orphan_apikeys} found)")

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
