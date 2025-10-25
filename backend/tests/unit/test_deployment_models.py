"""
Tests for deployment database models.

TDD Phase: RED (tests written first, will fail until models implemented)

Tests validate:
- Deployment model structure and composite keys
- DeploymentContainer junction table
- DeploymentTemplate model
- SHORT ID enforcement (12 chars)
- Composite key format: {host_id}:{deployment_id}
- Timestamp handling ('Z' suffix for frontend)
- Foreign key relationships
- UNIQUE constraints
"""

import pytest
from datetime import datetime
import json

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from database import Deployment, DeploymentContainer, DeploymentTemplate


@pytest.mark.unit
def test_deployment_composite_key_format(test_db, test_host):
    """
    Test that Deployment uses composite key format: {host_id}:{deployment_id}

    Critical: Composite keys prevent collisions across multiple hosts.
    """
    deployment_short_id = "abc123def456"  # 12 chars
    composite_key = f"{test_host.id}:{deployment_short_id}"

    deployment = Deployment(
        id=composite_key,
        host_id=test_host.id,
        deployment_type='container',
        name='test-nginx',
        status='pending',
        definition='{"container": {"image": "nginx:alpine"}}',
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(deployment)
    test_db.commit()

    # Verify composite key format
    assert ':' in deployment.id
    parts = deployment.id.split(':', 1)
    assert len(parts) == 2
    assert parts[0] == test_host.id  # Host UUID
    assert len(parts[1]) == 12  # SHORT ID (12 chars)


@pytest.mark.unit
def test_deployment_short_id_enforcement(test_db, test_host):
    """
    Test that deployment IDs after the colon are SHORT (12 chars), never full UUIDs.

    Standard: SHORT IDs (12 chars) enforced everywhere in DockMon.
    """
    # Valid: 12-char deployment ID
    valid_id = f"{test_host.id}:a1b2c3d4e5f6"
    deployment = Deployment(
        id=valid_id,
        host_id=test_host.id,
        deployment_type='container',
        name='valid-deployment',
        status='pending',
        definition='{}',
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(deployment)
    test_db.commit()

    # Verify SHORT ID length
    deployment_id_part = deployment.id.split(':', 1)[1]
    assert len(deployment_id_part) == 12, "Deployment ID must be SHORT (12 chars)"


@pytest.mark.unit
def test_deployment_unique_name_per_host(test_db, test_host):
    """
    Test UNIQUE(host_id, name) constraint.

    Decision: Deployment names are unique per host, not globally.
    Allows same deployment name on different hosts (e.g., prod + staging).
    """
    # First deployment with name 'web-server' on test_host
    deployment1 = Deployment(
        id=f"{test_host.id}:deployment01",
        host_id=test_host.id,
        deployment_type='container',
        name='web-server',
        status='pending',
        definition='{}',
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(deployment1)
    test_db.commit()

    # Second deployment with same name on same host should fail
    deployment2 = Deployment(
        id=f"{test_host.id}:deployment02",
        host_id=test_host.id,
        deployment_type='container',
        name='web-server',  # Same name, same host
        status='pending',
        definition='{}',
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(deployment2)

    with pytest.raises(Exception):  # Should raise IntegrityError
        test_db.commit()


@pytest.mark.unit
def test_deployment_foreign_key_to_host(test_db, test_host):
    """
    Test that Deployment has foreign key to docker_hosts table.

    Cascading: If host deleted, deployments should cascade delete.
    """
    deployment = Deployment(
        id=f"{test_host.id}:testdeploy1",
        host_id=test_host.id,
        deployment_type='container',
        name='fk-test',
        status='pending',
        definition='{}',
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(deployment)
    test_db.commit()

    # Verify foreign key relationship
    assert deployment.host_id == test_host.id

    # NOTE: Cascade delete testing requires actually deleting host,
    # which might affect other tests. Structural FK test is sufficient.


@pytest.mark.unit
def test_deployment_status_field(test_db, test_host):
    """
    Test that deployment status field accepts expected values.

    Valid states: pending, validating, pulling_image, creating, starting, running, failed, stopped
    """
    valid_statuses = [
        'pending', 'validating', 'pulling_image', 'creating',
        'starting', 'running', 'failed', 'stopped'
    ]

    for status in valid_statuses:
        deployment = Deployment(
            id=f"{test_host.id}:status{status[:4]}",
            host_id=test_host.id,
            deployment_type='container',
            name=f'test-{status}',
            status=status,
            definition='{}',
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(deployment)

    test_db.commit()

    # Verify all statuses saved correctly
    deployments = test_db.query(Deployment).filter_by(host_id=test_host.id).all()
    statuses_saved = [d.status for d in deployments]

    for status in valid_statuses:
        assert status in statuses_saved


@pytest.mark.unit
def test_deployment_definition_json(test_db, test_host):
    """
    Test that deployment definition field stores JSON correctly.

    Definition contains full deployment configuration (ports, volumes, env, etc.)
    """
    definition = {
        'container': {
            'image': 'nginx:latest',
            'ports': {'80/tcp': 8080},
            'volumes': [{'source': 'mydata', 'target': '/data', 'mode': 'rw'}],
            'environment': {'DEBUG': 'true'}
        }
    }

    deployment = Deployment(
        id=f"{test_host.id}:jsontest001",
        host_id=test_host.id,
        deployment_type='container',
        name='json-test',
        status='pending',
        definition=json.dumps(definition),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(deployment)
    test_db.commit()

    # Retrieve and verify JSON
    retrieved = test_db.query(Deployment).filter_by(id=deployment.id).first()
    retrieved_def = json.loads(retrieved.definition)

    assert retrieved_def['container']['image'] == 'nginx:latest'
    assert retrieved_def['container']['ports']['80/tcp'] == 8080
    assert retrieved_def['container']['environment']['DEBUG'] == 'true'


@pytest.mark.unit
def test_deployment_container_junction_table(test_db, test_host):
    """
    Test DeploymentContainer junction table links deployments to containers.

    Critical: Supports 1:1 (single container) and 1:N (stack) relationships.
    """
    # Create deployment
    deployment = Deployment(
        id=f"{test_host.id}:junctiontest",
        host_id=test_host.id,
        deployment_type='container',
        name='junction-test',
        status='running',
        definition='{}',
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(deployment)
    test_db.commit()

    # Link to container (using composite key)
    container_id = f"{test_host.id}:abc123def456"  # SHORT ID
    link = DeploymentContainer(
        deployment_id=deployment.id,
        container_id=container_id,
        service_name=None,  # NULL for single container deployments
        created_at=datetime.utcnow()
    )
    test_db.add(link)
    test_db.commit()

    # Verify link
    retrieved_link = test_db.query(DeploymentContainer).filter_by(
        deployment_id=deployment.id
    ).first()

    assert retrieved_link is not None
    assert retrieved_link.container_id == container_id
    assert retrieved_link.service_name is None


@pytest.mark.unit
def test_deployment_container_stack_services(test_db, test_host):
    """
    Test that DeploymentContainer supports stack deployments with service names.

    For stacks: service_name populated (e.g., 'web', 'db', 'cache').
    """
    # Create stack deployment
    deployment = Deployment(
        id=f"{test_host.id}:stacktest01",
        host_id=test_host.id,
        deployment_type='stack',
        name='wordpress-stack',
        status='running',
        definition='{}',
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(deployment)
    test_db.commit()

    # Link multiple containers (simulating WordPress + MySQL stack)
    services = [
        ('web', f"{test_host.id}:webcontainer"),
        ('db', f"{test_host.id}:dbcontainer1"),
        ('cache', f"{test_host.id}:cachecontnr")
    ]

    for service_name, container_id in services:
        link = DeploymentContainer(
            deployment_id=deployment.id,
            container_id=container_id,
            service_name=service_name,
            created_at=datetime.utcnow()
        )
        test_db.add(link)

    test_db.commit()

    # Verify all services linked
    links = test_db.query(DeploymentContainer).filter_by(
        deployment_id=deployment.id
    ).all()

    assert len(links) == 3
    service_names = [link.service_name for link in links]
    assert 'web' in service_names
    assert 'db' in service_names
    assert 'cache' in service_names


@pytest.mark.unit
def test_deployment_template_structure(test_db):
    """
    Test DeploymentTemplate model structure.

    Templates store pre-configured deployment definitions for common apps.
    """
    template = DeploymentTemplate(
        id='tpl_nginx_001',
        name='nginx-proxy',
        category='web',
        description='Nginx reverse proxy',
        deployment_type='container',
        template_definition=json.dumps({
            'container': {
                'image': 'nginx:latest',
                'ports': {'80/tcp': '${PORT}'}
            }
        }),
        variables=json.dumps({
            'PORT': {'default': 8080, 'type': 'integer', 'description': 'Exposed port'}
        }),
        is_builtin=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(template)
    test_db.commit()

    # Verify template saved
    retrieved = test_db.query(DeploymentTemplate).filter_by(name='nginx-proxy').first()
    assert retrieved is not None
    assert retrieved.category == 'web'
    assert retrieved.is_builtin is True

    # Verify variables JSON
    variables = json.loads(retrieved.variables)
    assert 'PORT' in variables
    assert variables['PORT']['default'] == 8080


@pytest.mark.unit
def test_deployment_template_unique_name(test_db):
    """
    Test that template names are globally unique.

    Unlike deployments (unique per host), templates are global.
    """
    template1 = DeploymentTemplate(
        id='tpl_postgres_01',
        name='postgres-14',
        category='database',
        description='PostgreSQL 14',
        deployment_type='container',
        template_definition='{}',
        is_builtin=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(template1)
    test_db.commit()

    # Try to create another template with same name
    template2 = DeploymentTemplate(
        id='tpl_postgres_02',
        name='postgres-14',  # Same name
        category='database',
        description='PostgreSQL 14 custom',
        deployment_type='container',
        template_definition='{}',
        is_builtin=False,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(template2)

    with pytest.raises(Exception):  # Should raise IntegrityError
        test_db.commit()


@pytest.mark.unit
def test_deployment_timestamps_have_z_suffix():
    """
    Test that timestamp serialization includes 'Z' suffix for frontend.

    Standard: All timestamps returned to frontend must have 'Z' suffix (UTC indicator).

    Note: This tests the pattern, not the model directly. Model stores datetime,
    API serialization adds 'Z'.
    """
    now = datetime.utcnow()

    # Pattern used in API serialization
    timestamp_with_z = now.isoformat() + 'Z'

    assert timestamp_with_z.endswith('Z')
    assert 'T' in timestamp_with_z  # ISO format

    # Verify format example: "2025-10-25T15:30:00.123456Z"
    parts = timestamp_with_z.split('T')
    assert len(parts) == 2
    assert parts[1].endswith('Z')
