"""
Contract tests for Docker SDK behavior.

These tests run against REAL Docker (not mocks) to verify:
- Docker SDK behavior matches our assumptions
- Breaking changes in docker-py are caught in CI
- Short IDs are actually 12 characters
- Labels survive create → inspect roundtrip

**NOTE:** These tests create/destroy real containers. Run in isolated environment.

Run with: pytest -m contract
"""

import pytest
import docker
from datetime import datetime


@pytest.mark.contract
@pytest.mark.slow
def test_docker_sdk_short_id_is_12_characters():
    """
    Verify Docker SDK .short_id is actually 12 characters.

    Critical: DockMon assumes short_id = 12 chars everywhere.
    If docker-py changes this, we need to know immediately.
    """
    try:
        client = docker.from_env()
    except docker.errors.DockerException:
        pytest.skip("Docker not available")

    # Create throwaway container
    container = client.containers.create(
        'alpine:latest',
        command='sleep 1',
        name='dockmon-contract-test-shortid'
    )

    try:
        # Verify short_id format
        assert len(container.short_id) == 12, \
            f"Docker SDK short_id changed! Expected 12 chars, got {len(container.short_id)}"

        # Verify id[:12] matches short_id
        assert container.id[:12] == container.short_id, \
            "Docker SDK id[:12] doesn't match short_id"

    finally:
        container.remove(force=True)


@pytest.mark.contract
@pytest.mark.slow
def test_docker_sdk_labels_roundtrip():
    """
    Verify labels can be set and retrieved correctly.

    Critical for v2.1: Deployment labels must survive create → inspect cycle.
    """
    try:
        client = docker.from_env()
    except docker.errors.DockerException:
        pytest.skip("Docker not available")

    test_labels = {
        'dockmon.deployment_id': 'host-uuid:deploy-uuid',
        'dockmon.managed': 'true',
        'dockmon.host_id': 'test-host-id'
    }

    # Create container with labels
    container = client.containers.create(
        'alpine:latest',
        command='sleep 1',
        name='dockmon-contract-test-labels',
        labels=test_labels
    )

    try:
        # Re-fetch container
        fetched = client.containers.get(container.short_id)

        # Verify labels preserved
        for key, value in test_labels.items():
            assert fetched.labels.get(key) == value, \
                f"Label {key} not preserved. Expected {value}, got {fetched.labels.get(key)}"

    finally:
        container.remove(force=True)


@pytest.mark.contract
@pytest.mark.slow
def test_docker_sdk_container_lifecycle():
    """
    Verify full create → start → stop → remove lifecycle.

    Critical: v2.1 deployment relies on this sequence working correctly.
    """
    try:
        client = docker.from_env()
    except docker.errors.DockerException:
        pytest.skip("Docker not available")

    # Create
    container = client.containers.create(
        'alpine:latest',
        command='sleep 60',
        name='dockmon-contract-test-lifecycle'
    )

    try:
        # Verify created state
        assert container.status == 'created'

        # Start
        container.start()
        container.reload()  # Refresh state
        assert container.status == 'running'

        # Stop
        container.stop(timeout=2)
        container.reload()
        assert container.status == 'exited'

    finally:
        # Remove
        container.remove(force=True)


@pytest.mark.contract
@pytest.mark.slow
def test_docker_sdk_recreated_container_gets_new_id():
    """
    Verify that recreating a container (remove + create) results in new ID.

    CRITICAL for DockMon: Update system assumes recreation = new ID.
    Database must be updated accordingly.
    """
    try:
        client = docker.from_env()
    except docker.errors.DockerException:
        pytest.skip("Docker not available")

    # Create first container
    container1 = client.containers.create(
        'alpine:latest',
        command='sleep 1',
        name='dockmon-contract-test-recreate'
    )
    old_id = container1.short_id
    container1.remove(force=True)

    # Recreate with same name
    container2 = client.containers.create(
        'alpine:latest',
        command='sleep 1',
        name='dockmon-contract-test-recreate'
    )
    new_id = container2.short_id

    try:
        # Verify: Different ID!
        assert old_id != new_id, \
            "Recreated container has same ID! DockMon's update logic assumes new ID."
        
        # Verify: Both are 12 chars
        assert len(old_id) == 12
        assert len(new_id) == 12

    finally:
        container2.remove(force=True)


@pytest.mark.contract
@pytest.mark.slow
def test_docker_sdk_labels_accessible_via_attrs():
    """
    Verify labels accessible via both .labels and attrs['Config']['Labels'].

    Critical: DockMon code uses both access patterns.
    """
    try:
        client = docker.from_env()
    except docker.errors.DockerException:
        pytest.skip("Docker not available")

    container = client.containers.create(
        'alpine:latest',
        labels={'test': 'value'}
    )

    try:
        # Verify both access patterns work
        assert container.labels['test'] == 'value'
        assert container.attrs['Config']['Labels']['test'] == 'value'

    finally:
        container.remove(force=True)


@pytest.mark.contract
@pytest.mark.slow
def test_docker_sdk_port_bindings_structure():
    """
    Verify NetworkSettings.Ports structure hasn't changed.

    Critical: Port conflict detection relies on specific attrs structure.
    """
    try:
        client = docker.from_env()
    except docker.errors.DockerException:
        pytest.skip("Docker not available")

    container = client.containers.create(
        'nginx:alpine',
        name='dockmon-contract-test-ports',
        ports={'80/tcp': 9999}  # Map port 80 to 9999
    )

    try:
        container.start()
        container.reload()

        # Verify port bindings structure
        network_settings = container.attrs.get('NetworkSettings', {})
        ports = network_settings.get('Ports', {})

        assert '80/tcp' in ports, "Port binding format changed"
        assert isinstance(ports['80/tcp'], list), "Port binding is not a list"

        if ports['80/tcp']:  # May be None if not exposed
            binding = ports['80/tcp'][0]
            assert 'HostPort' in binding, "HostPort key missing from binding"

    finally:
        container.stop(timeout=2)
        container.remove(force=True)


@pytest.mark.contract
@pytest.mark.slow
def test_docker_sdk_volume_mounts_structure():
    """
    Verify volume mounts structure in HostConfig.Binds.

    Critical: Update system must preserve volume mounts.
    """
    try:
        client = docker.from_env()
    except docker.errors.DockerException:
        pytest.skip("Docker not available")

    # Create container with volume mount
    container = client.containers.create(
        'alpine:latest',
        command='sleep 1',
        volumes={'/tmp': {'bind': '/data', 'mode': 'rw'}}
    )

    try:
        # Verify volume mount structure
        host_config = container.attrs.get('HostConfig', {})
        binds = host_config.get('Binds', [])

        assert isinstance(binds, list), "Binds should be a list"
        # Format should be like ['/tmp:/data:rw']
        if binds:
            assert '/data' in binds[0], "Volume bind format unexpected"

    finally:
        container.remove(force=True)
