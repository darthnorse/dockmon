"""
Integration Tests for Passthrough Refactor (v2.1.9) - Phase 3

These tests validate the passthrough approach with REAL containers running in Docker.
Unlike unit tests, these create actual containers and perform real updates.

Critical Test Coverage:
1. GPU containers (NVIDIA runtime) - DeviceRequests preservation
2. Complex volume setups - Binds passthrough without transformation
3. Static IP containers - IPAMConfig preservation
4. NetworkMode container - container:name resolution
5. Multiple networks - Manual connection workflow
6. Full update workflow - End-to-end alpine:3.18 → 3.19
7. Real-world scenarios - Grafana-like complex configs
8. Issue #68 (Olen) - UniFi duplicate mount fix validation

Special thanks to @Olen for Issue #68 bug report and testing!

IMPORTANT: These tests require Docker to be available and running.
"""

import pytest
import docker
import os
import time
from pathlib import Path
from unittest.mock import Mock
from updates.update_executor import UpdateExecutor
from database import DatabaseManager


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def docker_client():
    """Get Docker client or skip if Docker not available."""
    try:
        client = docker.from_env()
        # Test connection
        client.ping()
        return client
    except Exception as e:
        pytest.skip(f"Docker not available: {e}")


@pytest.fixture
def db_manager(db_session):
    """Create DatabaseManager with test database."""
    db = Mock(spec=DatabaseManager)
    db.get_session = Mock(return_value=db_session)
    return db


@pytest.fixture
def update_executor(db_manager):
    """Create UpdateExecutor for testing."""
    # Mock monitor to avoid real monitoring
    mock_monitor = Mock()
    mock_monitor.manager = None  # No WebSocket manager needed

    executor = UpdateExecutor(db=db_manager, monitor=mock_monitor)
    return executor


@pytest.fixture
def cleanup_containers(docker_client):
    """Cleanup test containers after test."""
    containers_to_cleanup = []

    yield containers_to_cleanup

    # Cleanup
    for container_name in containers_to_cleanup:
        try:
            container = docker_client.containers.get(container_name)
            container.remove(force=True)
        except docker.errors.NotFound:
            pass
        except Exception as e:
            print(f"Warning: Failed to cleanup {container_name}: {e}")


@pytest.fixture
def cleanup_networks(docker_client):
    """Cleanup test networks after test."""
    networks_to_cleanup = []

    yield networks_to_cleanup

    # Cleanup
    for network_name in networks_to_cleanup:
        try:
            network = docker_client.networks.get(network_name)
            network.remove()
        except docker.errors.NotFound:
            pass
        except Exception as e:
            print(f"Warning: Failed to cleanup {network_name}: {e}")


# =============================================================================
# Test 1: GPU Container Update (Critical!)
# =============================================================================

class TestGPUContainerUpdate:
    """
    Test GPU container updates to validate DeviceRequests preservation.

    This is the CRITICAL test that validates the main bug fix in the passthrough
    refactor. v1 was missing DeviceRequests extraction, breaking GPU containers.
    """

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.skipif(
        not os.path.exists('/usr/bin/nvidia-smi'),
        reason="NVIDIA runtime not available"
    )
    async def test_gpu_container_preserves_device_requests(
        self,
        docker_client,
        update_executor,
        cleanup_containers
    ):
        """
        Test that GPU container update preserves DeviceRequests.

        This test requires:
        - NVIDIA GPU installed
        - nvidia-docker runtime installed
        - Docker configured with nvidia runtime

        If not available, test will be skipped (not failed).
        """
        container_name = 'test-gpu-passthrough'
        cleanup_containers.append(container_name)

        try:
            # Create GPU container with NVIDIA runtime
            container = docker_client.containers.create(
                image='nvidia/cuda:11.0-base',
                name=container_name,
                command=['sleep', '300'],
                device_requests=[
                    docker.types.DeviceRequest(
                        count=-1,  # All GPUs
                        capabilities=[['gpu']]
                    )
                ],
                detach=True
            )
            container.start()

            # Wait for container to be running
            time.sleep(1)
            container.reload()
            assert container.status == 'running'

            # Extract config using v2 passthrough method
            extracted = await update_executor._extract_container_config_v2(
                container=container,
                client=docker_client,
                new_image_labels={},
                is_podman=False
            )

            # CRITICAL: Verify DeviceRequests is in HostConfig
            host_config = extracted['host_config']
            assert 'DeviceRequests' in host_config, \
                "DeviceRequests missing from passthrough HostConfig!"

            device_requests = host_config['DeviceRequests']
            assert len(device_requests) > 0, \
                "DeviceRequests should contain at least one entry"

            # Verify GPU request structure
            gpu_request = device_requests[0]
            assert gpu_request['Count'] == -1, \
                "Count should be -1 (all GPUs)"
            assert 'gpu' in gpu_request['Capabilities'][0], \
                "GPU capability should be present"

            print(f"✅ GPU DeviceRequests preserved: {device_requests}")

        except docker.errors.APIError as e:
            if 'could not select device driver' in str(e).lower():
                pytest.skip("NVIDIA runtime not configured in Docker")
            raise


# =============================================================================
# Test 2: Complex Volume Configuration
# =============================================================================

class TestVolumePassthrough:
    """
    Test that complex volume configurations are preserved through passthrough.

    Validates:
    - Multiple bind mounts
    - Named volumes
    - Tmpfs mounts
    - No duplicate mount errors (Issue #68)
    """

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_multiple_bind_mounts_preserved(
        self,
        docker_client,
        update_executor,
        cleanup_containers,
        tmp_path
    ):
        """Test that multiple bind mounts are preserved exactly."""
        container_name = 'test-volumes-passthrough'
        cleanup_containers.append(container_name)

        # Ensure alpine:latest image is available
        try:
            docker_client.images.get("alpine:latest")
        except docker.errors.ImageNotFound:
            print("  Pulling alpine:latest...")
            docker_client.images.pull("alpine:latest")

        # Create host directories
        config_dir = tmp_path / "config"
        data_dir = tmp_path / "data"
        logs_dir = tmp_path / "logs"
        config_dir.mkdir()
        data_dir.mkdir()
        logs_dir.mkdir()

        # Create test files
        (config_dir / "test.conf").write_text("config=test")

        # Create container with multiple bind mounts
        container = docker_client.containers.create(
            image='alpine:latest',
            name=container_name,
            command=['sleep', '300'],
            volumes={
                str(config_dir): {'bind': '/config', 'mode': 'ro'},
                str(data_dir): {'bind': '/data', 'mode': 'rw'},
                str(logs_dir): {'bind': '/logs', 'mode': 'rw'},
            },
            tmpfs={'/tmp': 'size=100m,mode=1777'},
            detach=True
        )
        container.start()

        # Extract config using v2 passthrough
        extracted = await update_executor._extract_container_config_v2(
            container=container,
            client=docker_client,
            new_image_labels={},
            is_podman=False
        )

        host_config = extracted['host_config']

        # Verify Binds array is present and preserved
        assert 'Binds' in host_config, "Binds missing from HostConfig"
        binds = host_config['Binds']
        assert len(binds) == 3, f"Expected 3 bind mounts, got {len(binds)}"

        # Verify bind format (array of strings, not transformed)
        for bind in binds:
            assert isinstance(bind, str), f"Bind should be string, got {type(bind)}"
            assert ':' in bind, f"Bind should have ':' separator: {bind}"

        # Verify tmpfs preserved
        assert 'Tmpfs' in host_config, "Tmpfs missing from HostConfig"
        assert '/tmp' in host_config['Tmpfs'], "Tmpfs /tmp mount missing"

        print(f"✅ Volume passthrough preserved: {len(binds)} binds, tmpfs=/tmp")


    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_no_duplicate_mount_errors(
        self,
        docker_client,
        update_executor,
        cleanup_containers,
        tmp_path
    ):
        """
        Test that passthrough approach eliminates duplicate mount errors (Issue #68).

        The v1 approach transformed Binds to volume dict and back, sometimes creating
        duplicates. v2 passes Binds through directly, eliminating the issue.
        """
        container_name = 'test-no-duplicate-mounts'
        cleanup_containers.append(container_name)

        # Ensure alpine:latest image is available
        try:
            docker_client.images.get("alpine:latest")
        except docker.errors.ImageNotFound:
            print("  Pulling alpine:latest...")
            docker_client.images.pull("alpine:latest")

        # Create host directory (Issue #68 reporter had trailing slash issues)
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        # Create container with bind mount
        container = docker_client.containers.create(
            image='alpine:latest',
            name=container_name,
            command=['sleep', '300'],
            volumes={
                str(config_dir): {'bind': '/config', 'mode': 'rw'},
            },
            detach=True
        )
        container.start()

        # Extract and create new container using v2 methods
        extracted = await update_executor._extract_container_config_v2(
            container=container,
            client=docker_client,
            new_image_labels={},
            is_podman=False
        )

        # Remove old container (simulating update workflow where old container is renamed/removed before creating new)
        container.remove(force=True)

        # Try to create new container with same config
        # This should NOT raise "Duplicate mount point" error
        try:
            new_container = await update_executor._create_container_v2(
                client=docker_client,
                image='alpine:latest',
                extracted_config=extracted,
                is_podman=False
            )

            # Verify container created successfully
            assert new_container is not None
            new_container.reload()

            # Verify mount is present in new container
            new_binds = new_container.attrs['HostConfig']['Binds']
            assert len(new_binds) == 1, "Should have exactly 1 bind mount"

            print(f"✅ No duplicate mount error - passthrough working correctly")

            # Cleanup new container
            new_container.remove(force=True)

        except docker.errors.APIError as e:
            if 'duplicate mount point' in str(e).lower():
                pytest.fail(f"Duplicate mount error should not occur with passthrough: {e}")
            raise


# =============================================================================
# Test 3: Static IP Container Update
# =============================================================================

class TestStaticIPPreservation:
    """
    Test that static IP configuration is preserved during updates.

    This validates the network configuration extraction logic which is
    retained in the passthrough approach (complex network handling).
    """

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_static_ip_preserved(
        self,
        docker_client,
        update_executor,
        cleanup_containers,
        cleanup_networks
    ):
        """Test that static IP is preserved through update."""
        import random
        suffix = random.randint(1000, 9999)
        network_name = f'test-static-ip-net-{suffix}'
        container_name = f'test-static-ip-container-{suffix}'
        cleanup_networks.append(network_name)
        cleanup_containers.append(container_name)

        # Ensure alpine:latest image is available
        try:
            docker_client.images.get("alpine:latest")
        except docker.errors.ImageNotFound:
            print("  Pulling alpine:latest...")
            docker_client.images.pull("alpine:latest")

        # Create custom network with subnet (use unique subnet to avoid conflicts)
        import random
        # Use 10.x.x.x range with random second octet to avoid conflicts
        # Try multiple times with different subnets if we hit conflicts
        network = None
        max_attempts = 10
        for attempt in range(max_attempts):
            subnet_base = random.randint(100, 250)
            subnet = f'10.{subnet_base}.0.0/16'
            gateway = f'10.{subnet_base}.0.1'
            static_ip = f'10.{subnet_base}.0.10'

            try:
                network = docker_client.networks.create(
                    name=network_name,
                    driver='bridge',
                    ipam=docker.types.IPAMConfig(
                        pool_configs=[docker.types.IPAMPool(
                            subnet=subnet,
                            gateway=gateway
                        )]
                    )
                )
                break  # Success, exit retry loop
            except docker.errors.APIError as e:
                if 'Pool overlaps' in str(e) and attempt < max_attempts - 1:
                    # Subnet conflict, try again with different subnet
                    continue
                else:
                    # Different error or out of retries
                    raise

        if network is None:
            raise Exception(f"Failed to create network after {max_attempts} attempts")

        # Create container with static IP
        networking_config = docker_client.api.create_networking_config({
            network_name: docker_client.api.create_endpoint_config(
                ipv4_address=static_ip
            )
        })

        container = docker_client.api.create_container(
            image='alpine:latest',
            name=container_name,
            command=['sleep', '300'],
            networking_config=networking_config,
            detach=True
        )
        container_obj = docker_client.containers.get(container['Id'])
        container_obj.start()

        # Extract config
        extracted = await update_executor._extract_container_config_v2(
            container=container_obj,
            client=docker_client,
            new_image_labels={},
            is_podman=False
        )

        # DEBUG: Print network data to understand structure
        network_settings = container_obj.attrs['NetworkSettings']['Networks']
        print(f"\n🔍 Network data for {network_name}:")
        import json
        print(json.dumps(network_settings[network_name], indent=2))

        # Verify manual networking config includes static IP
        manual_config = extracted.get('_dockmon_manual_networking_config')
        assert manual_config is not None, "Manual networking config should be present"

        endpoints = manual_config['EndpointsConfig']
        assert network_name in endpoints, f"Network {network_name} should be in endpoints"

        # Verify IPAMConfig is preserved
        ipam_config = endpoints[network_name].get('IPAMConfig')
        assert ipam_config is not None, "IPAMConfig should be preserved for static IP"
        assert ipam_config['IPv4Address'] == static_ip, \
            f"Static IP should be {static_ip}, got {ipam_config.get('IPv4Address')}"

        print(f"✅ Static IP {static_ip} preserved in network config")


# =============================================================================
# Test 4: NetworkMode Container (container:name)
# =============================================================================

class TestNetworkModeContainer:
    """
    Test NetworkMode container:ID → container:name resolution.

    This validates that dependent containers using network_mode: container:X
    are correctly updated with name resolution.
    """

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_network_mode_container_resolution(
        self,
        docker_client,
        update_executor,
        cleanup_containers
    ):
        """Test that container:ID is resolved to container:name."""
        provider_name = 'test-network-provider'
        dependent_name = 'test-network-dependent'
        cleanup_containers.extend([provider_name, dependent_name])

        # Ensure alpine:latest image is available
        try:
            docker_client.images.get("alpine:latest")
        except docker.errors.ImageNotFound:
            print("  Pulling alpine:latest...")
            docker_client.images.pull("alpine:latest")

        # Create provider container
        provider = docker_client.containers.create(
            image='alpine:latest',
            name=provider_name,
            command=['sleep', '300'],
            detach=True
        )
        provider.start()

        # Create dependent container using container:ID network mode
        dependent = docker_client.containers.create(
            image='alpine:latest',
            name=dependent_name,
            command=['sleep', '300'],
            network_mode=f'container:{provider.id}',  # Using ID
            detach=True
        )
        dependent.start()

        # Extract config - should resolve ID to name
        extracted = await update_executor._extract_container_config_v2(
            container=dependent,
            client=docker_client,
            new_image_labels={},
            is_podman=False
        )

        host_config = extracted['host_config']
        network_mode = host_config.get('NetworkMode', '')

        # Verify ID was resolved to name
        assert network_mode == f'container:{provider_name}', \
            f"NetworkMode should be 'container:{provider_name}', got '{network_mode}'"

        print(f"✅ NetworkMode resolved: container:{provider.id[:12]} → {network_mode}")


# =============================================================================
# Test 5: Multiple Networks
# =============================================================================

class TestMultipleNetworks:
    """
    Test containers connected to multiple custom networks.

    This validates the manual network connection workflow which is
    necessary because Docker SDK's networking_config is broken.
    """

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_multiple_networks_preserved(
        self,
        docker_client,
        update_executor,
        cleanup_containers,
        cleanup_networks
    ):
        """Test that containers with multiple networks preserve all connections."""
        container_name = 'test-multi-network'
        net1_name = 'test-net-1'
        net2_name = 'test-net-2'
        net3_name = 'test-net-3'

        cleanup_containers.append(container_name)
        cleanup_networks.extend([net1_name, net2_name, net3_name])

        # Ensure alpine:latest image is available
        try:
            docker_client.images.get("alpine:latest")
        except docker.errors.ImageNotFound:
            print("  Pulling alpine:latest...")
            docker_client.images.pull("alpine:latest")

        # Create three custom networks (with unique names to avoid conflicts)
        import random
        suffix = random.randint(1000, 9999)
        net1_name = f'test-net-1-{suffix}'
        net2_name = f'test-net-2-{suffix}'
        net3_name = f'test-net-3-{suffix}'
        cleanup_networks.clear()  # Replace old names
        cleanup_networks.extend([net1_name, net2_name, net3_name])

        net1 = docker_client.networks.create(net1_name, driver='bridge')
        net2 = docker_client.networks.create(net2_name, driver='bridge')
        net3 = docker_client.networks.create(net3_name, driver='bridge')

        # Create container on first network
        container = docker_client.containers.create(
            image='alpine:latest',
            name=container_name,
            command=['sleep', '300'],
            detach=True
        )

        # Connect to all three networks
        net1.connect(container)
        net2.connect(container, aliases=['service-alias'])
        net3.connect(container)

        container.start()
        container.reload()

        # Verify container is on all three networks
        networks = container.attrs['NetworkSettings']['Networks']
        assert len(networks) >= 3, f"Container should be on at least 3 networks, got {len(networks)}"

        # Extract config
        extracted = await update_executor._extract_container_config_v2(
            container=container,
            client=docker_client,
            new_image_labels={},
            is_podman=False
        )

        # Verify manual networking config includes all networks
        manual_config = extracted.get('_dockmon_manual_networking_config')
        assert manual_config is not None, "Manual networking config should be present"

        endpoints = manual_config['EndpointsConfig']
        assert len(endpoints) >= 3, \
            f"Should have at least 3 endpoints, got {len(endpoints)}"

        # Verify alias preservation
        net2_config = endpoints.get(net2_name)
        assert net2_config is not None, f"Network {net2_name} should be in endpoints"
        aliases = net2_config.get('Aliases', [])
        assert 'service-alias' in aliases, \
            f"Alias 'service-alias' should be preserved, got {aliases}"

        print(f"✅ Multiple networks preserved: {list(endpoints.keys())}")


# =============================================================================
# Test 6: Full Update Workflow (End-to-End)
# =============================================================================

class TestFullUpdateWorkflow:
    """
    Test complete container update workflow from old to new image.

    This is the highest-level integration test that validates the entire
    update process works end-to-end with real containers.
    """

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_complete_update_workflow(
        self,
        docker_client,
        update_executor,
        cleanup_containers,
        tmp_path
    ):
        """
        Test complete update workflow: extract → create → verify.

        This simulates the real update process without the monitoring/database
        overhead, focusing purely on the container recreation logic.
        """
        container_name = 'test-full-update'
        cleanup_containers.append(container_name)
        cleanup_containers.append(f'{container_name}-new')

        # Create host directory for volume
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "test.txt").write_text("original data")

        # Pull images first
        docker_client.images.pull('alpine:3.18')
        docker_client.images.pull('alpine:3.19')

        # Create original container (simulating old version)
        original = docker_client.containers.create(
            image='alpine:3.18',  # Old version
            name=container_name,
            command=['sh', '-c', 'echo "Running v3.18" && sleep 300'],
            environment=['TEST_VAR=original'],
            volumes={
                str(data_dir): {'bind': '/data', 'mode': 'rw'},
            },
            restart_policy={'Name': 'unless-stopped'},
            detach=True
        )
        original.start()

        # Wait for container to be running
        time.sleep(1)
        original.reload()
        assert original.status == 'running'

        # Step 1: Extract config from old container
        extracted = await update_executor._extract_container_config_v2(
            container=original,
            client=docker_client,
            new_image_labels={'version': '3.19'},  # New image metadata
            is_podman=False
        )

        # Step 2: New image already pulled above

        # Step 3: Stop and remove old container (simulating real update workflow)
        original.stop(timeout=5)
        original.remove()

        # Step 4: Create new container with same config but new image
        new_container = await update_executor._create_container_v2(
            client=docker_client,
            image='alpine:3.19',  # New version
            extracted_config=extracted,
            is_podman=False
        )

        # Step 5: Verify new container has correct config
        new_container.reload()
        new_attrs = new_container.attrs

        # Verify image updated
        assert 'alpine:3.19' in new_attrs['Config']['Image'], \
            "New container should use alpine:3.19"

        # Verify environment preserved
        env = new_attrs['Config']['Env']
        assert any('TEST_VAR=original' in e for e in env), \
            "Environment variable should be preserved"

        # Verify volumes preserved
        binds = new_attrs['HostConfig']['Binds']
        assert len(binds) == 1, "Volume bind should be preserved"
        assert str(data_dir) in binds[0], "Volume should point to same host directory"

        # Verify restart policy preserved
        restart = new_attrs['HostConfig']['RestartPolicy']
        assert restart['Name'] == 'unless-stopped', \
            "Restart policy should be preserved"

        # Start new container and verify it works
        new_container.start()
        time.sleep(1)
        new_container.reload()
        assert new_container.status == 'running', \
            "New container should be running"

        print(f"✅ Full update workflow: alpine:3.18 → alpine:3.19")

        # Cleanup
        new_container.remove(force=True)


# =============================================================================
# Test 7: Real-World Complex Configuration (Grafana-like)
# =============================================================================

class TestComplexRealWorld:
    """
    Test real-world complex container configuration based on Issue #68 reporter's
    Grafana setup: multiple volumes, networks, secrets, environment variables.
    """

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_grafana_like_complex_config(
        self,
        docker_client,
        update_executor,
        cleanup_containers,
        cleanup_networks,
        tmp_path
    ):
        """
        Test complex Grafana-like configuration preservation.

        Features:
        - 4 volume mounts (config, provisioning, data, logs)
        - 3 custom networks (traefik, mariadb, elastic)
        - Environment variables
        - Hostname
        - Restart policy
        - Port bindings
        """
        container_name = 'test-grafana-complex'
        cleanup_containers.append(container_name)

        # Create networks
        net_names = ['test-traefik', 'test-mariadb', 'test-elastic']
        cleanup_networks.extend(net_names)

        networks = []
        for net_name in net_names:
            try:
                net = docker_client.networks.create(net_name, driver='bridge')
                networks.append(net)
            except docker.errors.APIError:
                net = docker_client.networks.get(net_name)
                networks.append(net)

        # Create volume directories
        grafana_base = tmp_path / "grafana"
        (grafana_base / "config").mkdir(parents=True)
        (grafana_base / "provisioning").mkdir()
        (grafana_base / "data").mkdir()
        (grafana_base / "logs").mkdir()

        # Create test files
        (grafana_base / "config" / "grafana.ini").write_text("[server]\nhttp_port = 3000")
        (grafana_base / "provisioning" / "datasources.yml").write_text("datasources: []")

        # Pull image first
        docker_client.images.pull('grafana/grafana:9.5.0')

        # Create complex container
        container = docker_client.containers.create(
            image='grafana/grafana:9.5.0',
            name=container_name,
            hostname='grafana-host',
            command=None,  # Use default from image
            environment=[
                'GF_SECURITY_ADMIN_PASSWORD=test123',
                'GF_INSTALL_PLUGINS=grafana-clock-panel',
            ],
            volumes={
                str(grafana_base / "config" / "grafana.ini"): {
                    'bind': '/etc/grafana/grafana.ini',
                    'mode': 'rw'
                },
                str(grafana_base / "provisioning"): {
                    'bind': '/etc/grafana/provisioning',
                    'mode': 'rw'
                },
                str(grafana_base / "data"): {
                    'bind': '/var/lib/grafana',
                    'mode': 'rw'
                },
                str(grafana_base / "logs"): {
                    'bind': '/var/log/grafana',
                    'mode': 'rw'
                },
            },
            ports={'3000/tcp': 3000},
            restart_policy={'Name': 'unless-stopped'},
            detach=True
        )

        # Connect to all networks
        for net in networks:
            net.connect(container)

        container.start()
        container.reload()

        # Extract config using passthrough
        extracted = await update_executor._extract_container_config_v2(
            container=container,
            client=docker_client,
            new_image_labels={},
            is_podman=False
        )

        host_config = extracted['host_config']

        # Verify all 4 volume mounts preserved
        binds = host_config.get('Binds', [])
        assert len(binds) == 4, f"Should have 4 bind mounts, got {len(binds)}"

        # Verify hostname preserved
        config = extracted['config']
        assert config.get('Hostname') == 'grafana-host', \
            "Hostname should be preserved"

        # Verify environment preserved
        env = config.get('Env', [])
        assert any('GF_SECURITY_ADMIN_PASSWORD' in e for e in env), \
            "Environment variables should be preserved"

        # Verify restart policy preserved
        restart = host_config.get('RestartPolicy', {})
        assert restart.get('Name') == 'unless-stopped', \
            "Restart policy should be preserved"

        # Verify port bindings preserved
        port_bindings = host_config.get('PortBindings', {})
        assert '3000/tcp' in port_bindings, \
            "Port bindings should be preserved"

        # Verify multiple networks
        manual_config = extracted.get('_dockmon_manual_networking_config')
        assert manual_config is not None, "Manual networking config should be present"
        endpoints = manual_config['EndpointsConfig']
        assert len(endpoints) >= 3, \
            f"Should have at least 3 network endpoints, got {len(endpoints)}"

        print(f"✅ Complex Grafana-like config preserved: "
              f"{len(binds)} volumes, {len(endpoints)} networks")


# =============================================================================
# Summary Report
# =============================================================================

def pytest_sessionfinish(session, exitstatus):
    """Print summary after all integration tests complete."""
    if exitstatus == 0:
        print("\n" + "="*80)
        print("✅ ALL INTEGRATION TESTS PASSED - Passthrough refactor validated!")
        print("="*80)
        print("\nValidated:")
        print("  ✅ GPU container DeviceRequests preservation")
        print("  ✅ Volume passthrough without duplicates")
        print("  ✅ Static IP preservation")
        print("  ✅ NetworkMode container:name resolution")
        print("  ✅ Multiple networks with aliases")
        print("  ✅ Full update workflow end-to-end")
        print("  ✅ Complex real-world configurations")
        print("  ✅ Issue #68 (Olen's UniFi scenario)")
        print("\n🚀 Ready for Phase 4: Beta Build")
        print("="*80 + "\n")


# =============================================================================
# Test 8: Issue #68 - Olen's UniFi Controller Scenario
# =============================================================================

class TestIssue68OlenUniFi:
    """
    Integration test for Issue #68 reported by @Olen.

    Validates the fix for duplicate mount point errors when Docker reports
    the same mount in both Binds (no trailing slash) and Mounts (with trailing slash).

    Original Error: "Duplicate mount point: /config"
    Fixed By: Passthrough refactor (v2.1.9) - no transformation = no duplicates

    Thanks to @Olen for the detailed bug report and testing!
    """

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_olen_unifi_trailing_slash_scenario(
        self,
        docker_client,
        update_executor,
        cleanup_containers,
        tmp_path
    ):
        """
        Test Olen's UniFi Controller scenario where Docker reports mount with
        trailing slash difference between Binds and Mounts arrays.

        This was causing "Duplicate mount point: /config" in v1.
        """
        print("\n" + "="*80)
        print("Test 8: Issue #68 - Olen's UniFi Controller Scenario")
        print("="*80)

        # Create test directory mimicking /mnt/user/appdata/unifi (Unraid path)
        test_dir = tmp_path / "unifi-config"
        test_dir.mkdir()
        (test_dir / "test-data.txt").write_text("UniFi test data")

        container_name = "test-issue68-olen-unifi"
        cleanup_containers.append(container_name)

        # Ensure nginx:1.24.0 image is available
        try:
            docker_client.images.get("nginx:1.24.0")
        except docker.errors.ImageNotFound:
            print("  Pulling nginx:1.24.0...")
            docker_client.images.pull("nginx:1.24.0")

        # Create container matching Olen's setup
        print(f"Creating container matching Olen's UniFi setup...")
        print(f"  Volume: {test_dir}:/config")

        container = docker_client.containers.create(
            image="nginx:1.24.0",  # Using nginx for faster test
            name=container_name,
            detach=True,
            restart_policy={"Name": "unless-stopped"},
            volumes={
                str(test_dir): {
                    "bind": "/config",
                    "mode": "rw"
                }
            },
            environment={"TEST_VAR": "unifi-test"}
        )

        container.start()
        print(f"✅ Container created: {container.short_id}")

        # Wait for container to be running
        for _ in range(10):
            container.reload()
            if container.status == "running":
                break
            await asyncio.sleep(0.5)

        # Inspect mount configuration (this is where the bug manifested)
        container.reload()
        binds = container.attrs['HostConfig'].get('Binds', [])
        mounts = container.attrs.get('Mounts', [])

        print(f"\nMount Configuration (potential mismatch):")
        print(f"  Binds:  {binds}")
        mount_summary = [f"{m['Source']} -> {m['Destination']}" for m in mounts]
        print(f"  Mounts: {mount_summary}")

        # Extract config using v2 passthrough (the fix!)
        print("\n⚙️  Extracting config with v2 passthrough method...")
        extracted_config = await update_executor._extract_container_config_v2(
            container,
            client=docker_client,
            is_podman=False
        )

        # CRITICAL ASSERTION: HostConfig passthrough should NOT create duplicates
        host_config = extracted_config['host_config']
        binds_in_config = host_config.get('Binds', [])

        print(f"  Extracted Binds: {binds_in_config}")

        # Count mounts to /config (should be exactly 1)
        config_mounts = [b for b in binds_in_config if ':/config' in b or ':/config:' in b]

        assert len(config_mounts) == 1, (
            f"❌ Issue #68 REGRESSION! Should have exactly 1 mount to /config, "
            f"got {len(config_mounts)}. This would cause 'Duplicate mount point' error. "
            f"Binds: {binds_in_config}"
        )

        print(f"✅ PASS: Exactly 1 mount to /config (no duplicates)")

        # Simulate update by creating new container
        print("\n🔄 Simulating update to nginx:1.27.0...")

        # Remove old container (simulating real update workflow where old is renamed/removed)
        container.remove(force=True)

        new_container = None
        try:
            # Pull newer image
            docker_client.images.pull("nginx:1.27.0")

            # Create new container using passthrough HostConfig
            new_container = await update_executor._create_container_v2(
                client=docker_client,
                image="nginx:1.27.0",
                extracted_config=extracted_config,
                is_podman=False
            )

            cleanup_containers.append(new_container.name)
            print(f"✅ NEW CONTAINER CREATED: {new_container.short_id}")
            print("✅ NO 'Duplicate mount point' ERROR - Issue #68 FIXED!")

            # Start and verify
            new_container.start()

            for _ in range(10):
                new_container.reload()
                if new_container.status == "running":
                    break
                await asyncio.sleep(0.5)

            assert new_container.status == "running", "New container should be running"

            # Verify mount preserved
            new_container.reload()
            new_mounts = new_container.attrs.get('Mounts', [])
            assert len(new_mounts) == 1, "Should have exactly one mount"
            assert new_mounts[0]['Destination'] == "/config", "Mount destination should be /config"

            # Verify data persisted
            exec_result = new_container.exec_run("cat /config/test-data.txt")
            assert exec_result.exit_code == 0, "Should be able to read test file"
            assert b"UniFi test data" in exec_result.output, "Data should be preserved"

            print(f"✅ Volume data persisted correctly")
            print(f"\n{'='*80}")
            print("✅ Issue #68 (Olen's UniFi scenario) - VALIDATED")
            print(f"{'='*80}\n")

        finally:
            # Cleanup handled by fixture
            pass

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_olen_scenario_multiple_volumes(
        self,
        docker_client,
        update_executor,
        cleanup_containers,
        tmp_path
    ):
        """
        Test Issue #68 fix with multiple volumes (like typical Unraid setups).

        Ensures no accidental deduplication of different mount points.
        """
        print("\n" + "="*80)
        print("Test 8b: Issue #68 - Multiple Volumes (Unraid-like)")
        print("="*80)

        # Create test directories
        test_dirs = {
            "config": tmp_path / "config",
            "data": tmp_path / "data",
            "logs": tmp_path / "logs"
        }
        for dir_path in test_dirs.values():
            dir_path.mkdir()

        container_name = "test-issue68-multi-volumes"
        cleanup_containers.append(container_name)

        # Ensure nginx:1.24.0 image is available
        try:
            docker_client.images.get("nginx:1.24.0")
        except docker.errors.ImageNotFound:
            print("  Pulling nginx:1.24.0...")
            docker_client.images.pull("nginx:1.24.0")

        print(f"Creating container with 3 volumes (Unraid-like)...")

        container = docker_client.containers.create(
            image="nginx:1.24.0",
            name=container_name,
            detach=True,
            volumes={
                str(test_dirs["config"]): {"bind": "/config", "mode": "rw"},
                str(test_dirs["data"]): {"bind": "/data", "mode": "rw"},
                str(test_dirs["logs"]): {"bind": "/logs", "mode": "ro"},
            }
        )

        container.start()
        print(f"✅ Container created: {container.short_id}")

        # Wait for running
        for _ in range(10):
            container.reload()
            if container.status == "running":
                break
            await asyncio.sleep(0.5)

        # Extract config
        container.reload()
        extracted_config = await update_executor._extract_container_config_v2(
            container,
            client=docker_client,
            is_podman=False
        )

        # Verify all 3 volumes preserved
        host_config = extracted_config['host_config']
        binds_in_config = host_config.get('Binds', [])

        print(f"  Extracted Binds: {binds_in_config}")
        assert len(binds_in_config) == 3, f"Should have 3 bind mounts, got {len(binds_in_config)}"

        # Verify each destination appears exactly once
        destinations = [b.split(':')[1] for b in binds_in_config]
        assert destinations.count("/config") == 1, "Should have exactly 1 mount to /config"
        assert destinations.count("/data") == 1, "Should have exactly 1 mount to /data"
        assert destinations.count("/logs") == 1, "Should have exactly 1 mount to /logs"

        print(f"✅ All 3 volumes preserved correctly (no duplicates, no missing mounts)")
        print(f"\n{'='*80}")
        print("✅ Issue #68 (Multiple Volumes) - VALIDATED")
        print(f"{'='*80}\n")
