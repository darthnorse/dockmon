"""
Setup script to add container_updates table and columns to database
Run this once to add update tracking support
"""

import sys
import os
import sqlite3

def setup_updates_schema():
    print("Setting up container updates schema...")

    # Use sqlite3 directly to avoid DatabaseManager trying to query columns that don't exist yet
    conn = sqlite3.connect('/app/data/dockmon.db')
    cursor = conn.cursor()

    # Create container_updates table
    print("\n1. Creating container_updates table...")
    cursor.execute("""
            CREATE TABLE IF NOT EXISTS container_updates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                container_id TEXT NOT NULL UNIQUE,
                host_id TEXT NOT NULL,
                current_image TEXT NOT NULL,
                current_digest TEXT NOT NULL,
                latest_image TEXT,
                latest_digest TEXT,
                update_available INTEGER DEFAULT 0 NOT NULL,
                floating_tag_mode TEXT DEFAULT 'exact' NOT NULL,
                auto_update_enabled INTEGER DEFAULT 0 NOT NULL,
                health_check_strategy TEXT DEFAULT 'docker' NOT NULL,
                health_check_url TEXT,
                last_checked_at TEXT,
                last_updated_at TEXT,
                registry_url TEXT,
                platform TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
        """)
    conn.commit()
    print("   ✅ Table created")

    # Create indexes
    print("\n2. Creating indexes...")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_container_updates_container_id ON container_updates(container_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_container_updates_update_available ON container_updates(update_available)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_container_updates_host_id ON container_updates(host_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_container_updates_auto_update ON container_updates(auto_update_enabled)")
    conn.commit()
    print("   ✅ Indexes created")

    # Add global_settings columns
    print("\n3. Adding global_settings columns...")
    cursor.execute("PRAGMA table_info(global_settings)")
    existing_cols = [row[1] for row in cursor.fetchall()]

    columns_to_add = {
        'auto_update_enabled_default': 'INTEGER DEFAULT 0',
        'update_check_interval_hours': 'INTEGER DEFAULT 24',
        'update_check_time': 'TEXT DEFAULT "02:00"',
        'skip_compose_containers': 'INTEGER DEFAULT 1',
        'health_check_timeout_seconds': 'INTEGER DEFAULT 120',
        'alert_template_update': 'TEXT DEFAULT NULL',
    }

    for col_name, col_def in columns_to_add.items():
        if col_name not in existing_cols:
            cursor.execute(f"ALTER TABLE global_settings ADD COLUMN {col_name} {col_def}")
            conn.commit()
            print(f"   ✅ Added {col_name}")
        else:
            print(f"   ⏭️  {col_name} already exists")

    # Verify
    print("\n4. Verifying schema...")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='container_updates'")
    result = cursor.fetchone()
    if result:
        print("   ✅ container_updates table verified")

    cursor.execute("PRAGMA table_info(container_updates)")
    result = cursor.fetchall()
    print(f"   ✅ {len(result)} columns in container_updates")

    cursor.execute("PRAGMA table_info(global_settings)")
    all_cols = cursor.fetchall()
    update_cols = [row[1] for row in all_cols if 'update' in row[1] or 'health_check_timeout' in row[1]]
    print(f"   ✅ {len(update_cols)} update-related columns in global_settings")

    conn.close()
    print("\n✅ Container updates schema setup complete!")

if __name__ == "__main__":
    try:
        setup_updates_schema()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
