#!/usr/bin/env python3
"""
Fix missing default update policies.

This script inserts the default update policy patterns that should have been
seeded during the v2.0.0 migration. The migration uses execute_if_zero_rows,
which skips seeding if the table already has any rows.

Usage:
    # Run from host machine (executes inside dockmon container):
    python scripts/fix_update_policies.py

    # Dry run to see what would be inserted:
    python scripts/fix_update_policies.py --dry-run

    # Use a different container name:
    python scripts/fix_update_policies.py --container my-dockmon

    # Run directly on a local database (development):
    python scripts/fix_update_policies.py --local --db-path ./data/dockmon.db
"""

import argparse
import subprocess
import sys

# Python code to execute inside the container
CONTAINER_SCRIPT = '''
import sqlite3
from datetime import datetime, timezone

DEFAULT_POLICIES = [
    ("databases", "postgres"), ("databases", "mysql"), ("databases", "mariadb"),
    ("databases", "mongodb"), ("databases", "mongo"), ("databases", "redis"),
    ("databases", "sqlite"), ("databases", "mssql"), ("databases", "cassandra"),
    ("databases", "influxdb"), ("databases", "elasticsearch"),
    ("proxies", "traefik"), ("proxies", "nginx"), ("proxies", "caddy"),
    ("proxies", "haproxy"), ("proxies", "envoy"),
    ("monitoring", "grafana"), ("monitoring", "prometheus"),
    ("monitoring", "alertmanager"), ("monitoring", "uptime-kuma"),
    ("critical", "portainer"), ("critical", "watchtower"),
    ("critical", "dockmon"), ("critical", "komodo"),
]

db_path = "/app/data/dockmon.db"
dry_run = {dry_run}

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("SELECT category, pattern FROM update_policies")
existing = set(cursor.fetchall())
print(f"Found {{len(existing)}} existing policies")

missing = [(cat, pat) for cat, pat in DEFAULT_POLICIES if (cat, pat) not in existing]

if not missing:
    print("All default policies already exist. Nothing to do.")
else:
    print(f"Missing {{len(missing)}} policies:")
    for cat, pat in missing:
        print(f"  - {{cat}}: {{pat}}")

    if dry_run:
        print("\\nDry run - no changes made.")
    else:
        now = datetime.now(timezone.utc).isoformat()
        inserted = 0
        for cat, pat in missing:
            try:
                cursor.execute(
                    "INSERT INTO update_policies (category, pattern, enabled, created_at, updated_at) VALUES (?, ?, 1, ?, ?)",
                    (cat, pat, now, now)
                )
                inserted += 1
            except sqlite3.IntegrityError:
                print(f"  Skipped {{cat}}:{{pat}} - already exists")
        conn.commit()
        print(f"\\nInserted {{inserted}} policies successfully.")

conn.close()
'''


def run_in_container(container_name: str, dry_run: bool) -> int:
    """Execute the fix script inside the Docker container."""
    script = CONTAINER_SCRIPT.format(dry_run=dry_run)

    cmd = ["docker", "exec", container_name, "python", "-c", script]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return result.returncode
    except FileNotFoundError:
        print("Error: docker command not found. Is Docker installed?", file=sys.stderr)
        return 1


def run_local(db_path: str, dry_run: bool) -> int:
    """Execute the fix directly on a local database."""
    import sqlite3
    from datetime import datetime, timezone

    DEFAULT_POLICIES = [
        ("databases", "postgres"), ("databases", "mysql"), ("databases", "mariadb"),
        ("databases", "mongodb"), ("databases", "mongo"), ("databases", "redis"),
        ("databases", "sqlite"), ("databases", "mssql"), ("databases", "cassandra"),
        ("databases", "influxdb"), ("databases", "elasticsearch"),
        ("proxies", "traefik"), ("proxies", "nginx"), ("proxies", "caddy"),
        ("proxies", "haproxy"), ("proxies", "envoy"),
        ("monitoring", "grafana"), ("monitoring", "prometheus"),
        ("monitoring", "alertmanager"), ("monitoring", "uptime-kuma"),
        ("critical", "portainer"), ("critical", "watchtower"),
        ("critical", "dockmon"), ("critical", "komodo"),
    ]

    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error as e:
        print(f"Error connecting to database: {e}", file=sys.stderr)
        return 1

    cursor = conn.cursor()

    cursor.execute("SELECT category, pattern FROM update_policies")
    existing = set(cursor.fetchall())
    print(f"Found {len(existing)} existing policies")

    missing = [(cat, pat) for cat, pat in DEFAULT_POLICIES if (cat, pat) not in existing]

    if not missing:
        print("All default policies already exist. Nothing to do.")
        conn.close()
        return 0

    print(f"Missing {len(missing)} policies:")
    for cat, pat in missing:
        print(f"  - {cat}: {pat}")

    if dry_run:
        print("\nDry run - no changes made.")
        conn.close()
        return 0

    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for cat, pat in missing:
        try:
            cursor.execute(
                "INSERT INTO update_policies (category, pattern, enabled, created_at, updated_at) VALUES (?, ?, 1, ?, ?)",
                (cat, pat, now, now)
            )
            inserted += 1
        except sqlite3.IntegrityError:
            print(f"  Skipped {cat}:{pat} - already exists")

    conn.commit()
    conn.close()
    print(f"\nInserted {inserted} policies successfully.")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Fix missing default update policies in DockMon database"
    )
    parser.add_argument(
        "--container",
        default="dockmon",
        help="Docker container name (default: dockmon)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be inserted without making changes",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Run directly on local database instead of Docker container",
    )
    parser.add_argument(
        "--db-path",
        default="/app/data/dockmon.db",
        help="Path to database (only used with --local, default: /app/data/dockmon.db)",
    )
    args = parser.parse_args()

    if args.local:
        print(f"Running locally on database: {args.db_path}")
        print()
        sys.exit(run_local(args.db_path, args.dry_run))
    else:
        print(f"Running inside container: {args.container}")
        print()
        sys.exit(run_in_container(args.container, args.dry_run))


if __name__ == "__main__":
    main()
