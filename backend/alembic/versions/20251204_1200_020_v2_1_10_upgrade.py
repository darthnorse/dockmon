"""v2.1.10 upgrade - Fix missing default update policies

Revision ID: 020_v2_1_10
Revises: 018_v2_1_9
Create Date: 2025-12-04

BUG FIXES:
- Fix missing default update policies
  - The v2.0.0 migration used execute_if_zero_rows() to seed default policies
  - If the table already had any rows, seeding was skipped entirely
  - This caused categories (databases, proxies, monitoring) to appear disabled
  - Fix: Defensively insert missing policies without affecting existing ones

CHANGES:
- Seed missing default update policies (defensive - skips existing patterns)
- Update app_version to '2.1.10'
"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone


# revision identifiers, used by Alembic.
revision = '020_v2_1_10'
down_revision = '018_v2_1_9'
branch_labels = None
depends_on = None


# Default update policies that should exist
DEFAULT_POLICIES = [
    # Databases - require confirmation before auto-update
    ("databases", "postgres"),
    ("databases", "mysql"),
    ("databases", "mariadb"),
    ("databases", "mongodb"),
    ("databases", "mongo"),
    ("databases", "redis"),
    ("databases", "sqlite"),
    ("databases", "mssql"),
    ("databases", "cassandra"),
    ("databases", "influxdb"),
    ("databases", "elasticsearch"),
    # Proxies - require confirmation before auto-update
    ("proxies", "traefik"),
    ("proxies", "nginx"),
    ("proxies", "caddy"),
    ("proxies", "haproxy"),
    ("proxies", "envoy"),
    # Monitoring - require confirmation before auto-update
    ("monitoring", "grafana"),
    ("monitoring", "prometheus"),
    ("monitoring", "alertmanager"),
    ("monitoring", "uptime-kuma"),
    # Critical infrastructure - require confirmation before auto-update
    ("critical", "portainer"),
    ("critical", "watchtower"),
    ("critical", "dockmon"),
    ("critical", "komodo"),
]


def upgrade():
    # Get database connection
    bind = op.get_bind()

    # Check which policies already exist
    result = bind.execute(sa.text("SELECT category, pattern FROM update_policies"))
    existing = set((row[0], row[1]) for row in result)

    # Insert missing policies
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    inserted = 0

    for category, pattern in DEFAULT_POLICIES:
        if (category, pattern) not in existing:
            bind.execute(
                sa.text("""
                    INSERT INTO update_policies (category, pattern, enabled, created_at, updated_at)
                    VALUES (:category, :pattern, 1, :now, :now)
                """),
                {"category": category, "pattern": pattern, "now": now}
            )
            inserted += 1

    if inserted > 0:
        print(f"  Inserted {inserted} missing default update policies")
    else:
        print("  All default update policies already exist")



def downgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass
