"""v2.2.7 - Filesystem storage for stacks

Revision ID: 031_v2_2_7
Revises: 030_v2_2_6
Create Date: 2026-01-10 12:00:00

This migration:
1. Extracts compose content from database to filesystem (/stacks/)
2. Drops the definition and deployment_type columns
3. Renames 'name' to 'stack_name'
4. Updates unique constraint for multi-host stack deployments
5. Drops the deployment_templates table

WARNING: This is a one-way migration. Downgrade is not supported.
Backup your database before upgrading.

Key behavior:
- Deployments with the same name share ONE stack on filesystem
- First deployment's compose content is used for the shared stack
- Container-type deployments are converted to compose format
"""
import json
import logging
import os
import re
from collections import defaultdict
from pathlib import Path

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '031_v2_2_7'
down_revision = '030_v2_2_6'
branch_labels = None
depends_on = None

logger = logging.getLogger('alembic.runtime.migration')

# Stacks directory - same as stack_storage.py
STACKS_DIR = Path(os.environ.get('STACKS_DIR', '/app/data/stacks'))

# Valid stack name pattern
VALID_NAME_PATTERN = re.compile(r'^[a-z0-9][a-z0-9_-]*$')


def sanitize_stack_name(name: str) -> str:
    """Convert name to filesystem-safe format."""
    safe = name.lower()
    safe = re.sub(r'[^a-z0-9_-]', '-', safe)
    safe = re.sub(r'-+', '-', safe)
    safe = safe.strip('-')
    if safe and not safe[0].isalnum():
        safe = 'stack-' + safe
    return safe or 'unnamed-stack'


def get_unique_stack_name(base_name: str, existing_names: set) -> str:
    """Get unique name by appending number if needed."""
    name = base_name
    counter = 1
    while name in existing_names:
        name = f"{base_name}-{counter}"
        counter += 1
    return name


def container_to_compose(definition: dict) -> str:
    """Convert single-container definition to compose format."""
    # Import yaml here since it's only needed during migration
    import yaml

    service = {'image': definition.get('image', 'unknown')}

    if definition.get('ports'):
        service['ports'] = definition['ports']
    if definition.get('volumes'):
        service['volumes'] = definition['volumes']
    if definition.get('environment'):
        service['environment'] = definition['environment']
    if definition.get('network_mode'):
        service['network_mode'] = definition['network_mode']
    if definition.get('restart'):
        service['restart'] = definition['restart']
    if definition.get('command'):
        service['command'] = definition['command']
    if definition.get('entrypoint'):
        service['entrypoint'] = definition['entrypoint']
    if definition.get('labels'):
        service['labels'] = definition['labels']

    compose = {'services': {'app': service}}
    return yaml.dump(compose, default_flow_style=False)


def write_stack_sync(name: str, compose_yaml: str, env_content: str = None) -> None:
    """Write stack files synchronously (for use in Alembic migration)."""
    stack_path = STACKS_DIR / name
    stack_path.mkdir(parents=True, exist_ok=True)

    compose_path = stack_path / "compose.yaml"
    compose_path.write_text(compose_yaml)

    if env_content and env_content.strip():
        env_path = stack_path / ".env"
        env_path.write_text(env_content)


def stack_exists_sync(name: str) -> bool:
    """Check if stack exists synchronously."""
    stack_path = STACKS_DIR / name
    return (stack_path / "compose.yaml").exists()


def list_stacks_sync() -> list:
    """List existing stacks synchronously."""
    if not STACKS_DIR.exists():
        return []
    return [
        d.name for d in STACKS_DIR.iterdir()
        if d.is_dir() and (d / "compose.yaml").exists()
    ]


def upgrade():
    connection = op.get_bind()

    # =========================================================================
    # PHASE 1: Data Migration - Extract compose content to filesystem
    # =========================================================================

    logger.info("Phase 1: Extracting compose content to filesystem...")

    # Ensure stacks directory exists
    STACKS_DIR.mkdir(parents=True, exist_ok=True)

    # Get existing stack names to avoid collisions
    existing_stack_names = set(list_stacks_sync())

    # Find deployments with definition column set
    result = connection.execute(sa.text("""
        SELECT id, name, definition, deployment_type, host_id
        FROM deployments
        WHERE definition IS NOT NULL
        ORDER BY created_at ASC
    """))
    rows = result.fetchall()

    if not rows:
        logger.info("No deployments to migrate")
    else:
        logger.info(f"Migrating {len(rows)} deployments to filesystem...")

        # Group deployments by name - same name = same stack
        deployments_by_name = defaultdict(list)
        for row in rows:
            deployment_id, name, definition_json, deployment_type, host_id = row
            deployments_by_name[name].append({
                'id': deployment_id,
                'definition': definition_json,
                'deployment_type': deployment_type,
                'host_id': host_id
            })

        migrated_stacks = 0
        migrated_deployments = 0
        name_mapping = {}  # old_name -> sanitized_name

        for original_name, deployments in deployments_by_name.items():
            # Sanitize name
            safe_name = sanitize_stack_name(original_name)

            # Handle collisions
            all_used_names = existing_stack_names | set(name_mapping.values())
            if safe_name in all_used_names:
                safe_name = get_unique_stack_name(safe_name, all_used_names)

            name_mapping[original_name] = safe_name

            if safe_name != original_name:
                logger.info(f"Renaming stack '{original_name}' -> '{safe_name}'")

            # Create stack file from first deployment's content (if not already exists)
            if not stack_exists_sync(safe_name):
                first_deployment = deployments[0]
                try:
                    definition = json.loads(first_deployment['definition'])
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(f"Failed to parse definition for '{original_name}': {e}")
                    continue

                if first_deployment['deployment_type'] == 'container':
                    compose_yaml = container_to_compose(definition)
                    env_content = None
                else:
                    compose_yaml = definition.get('compose_yaml', '')
                    env_content = definition.get('env_content')

                if compose_yaml:
                    write_stack_sync(safe_name, compose_yaml, env_content)
                    existing_stack_names.add(safe_name)
                    migrated_stacks += 1
                    logger.info(f"Created stack '{safe_name}'")

            # Update all deployments to use sanitized name and clear definition
            for deployment in deployments:
                connection.execute(
                    sa.text("UPDATE deployments SET name = :new_name WHERE id = :id"),
                    {"id": deployment['id'], "new_name": safe_name}
                )
                migrated_deployments += 1

            if len(deployments) > 1:
                logger.info(f"Stack '{safe_name}' shared by {len(deployments)} deployments")

        logger.info(f"Phase 1 complete: {migrated_stacks} stacks, {migrated_deployments} deployments")

    # =========================================================================
    # PHASE 2: Schema Migration - Drop columns and tables
    # =========================================================================

    logger.info("Phase 2: Updating database schema...")

    # SQLite doesn't support ALTER TABLE DROP COLUMN directly
    # We need to use batch_alter_table for SQLite compatibility
    with op.batch_alter_table('deployments', schema=None) as batch_op:
        # Drop definition column (data now on filesystem)
        batch_op.drop_column('definition')

        # Drop deployment_type column (everything is a stack now)
        batch_op.drop_column('deployment_type')

        # Rename 'name' to 'stack_name' for clarity
        batch_op.alter_column('name', new_column_name='stack_name')

    # Update unique constraint: (host_id, name) -> (stack_name, host_id)
    # This allows same stack to be deployed to multiple hosts
    with op.batch_alter_table('deployments', schema=None) as batch_op:
        # Drop old constraint (named uq_deployment_host_name in schema)
        batch_op.drop_constraint('uq_deployment_host_name', type_='unique')

        # Create new constraint
        batch_op.create_unique_constraint(
            'uq_deployment_stack_host',
            ['stack_name', 'host_id']
        )

    # Drop templates table entirely
    op.drop_table('deployment_templates')

    logger.info("Phase 2 complete: Schema updated")
    logger.info("Migration to filesystem storage complete!")


def downgrade():
    # This migration cannot be reversed - compose content is on filesystem
    # and the definition column no longer exists
    raise Exception(
        "Downgrade not supported. This is a one-way migration. "
        "Restore from backup if you need to revert."
    )
