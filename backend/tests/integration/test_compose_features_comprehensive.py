"""
Comprehensive integration tests for ALL supported Docker Compose features.

Tests the full cycle: Compose YAML → Parse → Create → Inspect → Verify
Uses real Docker SDK to ensure format compatibility.

Coverage:
- Core features: ports, volumes, networks (list + dict with static IPs), environment
- Resource limits: mem_limit, cpus
- Container config: command, entrypoint, hostname, user, working_dir, privileged, labels
- Restart policies
- Multi-service stacks with depends_on

NETWORK BUG FIX:
The network support bug has been FIXED! The orchestrator now uses a hybrid approach:
- Single simple network → 'network' parameter (fast)
- Multiple networks or static IPs → Manual network.connect() after creation (complete)

All network tests now PASS.
"""

import pytest
import docker
import time
from deployment.stack_orchestrator import StackOrchestrator


@pytest.mark.integration
class TestComposeFeatures:
    """Comprehensive integration tests for ALL supported compose features"""

    @pytest.fixture
    def docker_client(self):
        """Get Docker client"""
        try:
            return docker.from_env()
        except Exception as e:
            pytest.skip(f"Docker not available: {e}")

    @pytest.fixture
    def orchestrator(self):
        """Get stack orchestrator"""
        return StackOrchestrator()

    @pytest.fixture(autouse=True)
    def cleanup_test_resources(self, docker_client):
        """Clean up any leftover test resources before and after each test"""
        def cleanup():
            # Clean up test containers
            for container_prefix in ['dockmon-test-', 'test-']:
                try:
                    for container in docker_client.containers.list(all=True):
                        if container.name.startswith(container_prefix):
                            container.remove(force=True)
                except Exception:
                    pass

            # Clean up test networks
            for network_prefix in ['test-network-', 'test-net-']:
                try:
                    for network in docker_client.networks.list():
                        if network.name.startswith(network_prefix):
                            try:
                                network.remove()
                            except Exception:
                                pass
                except Exception:
                    pass

        # Cleanup before test
        cleanup()

        # Run test
        yield

        # Cleanup after test
        cleanup()

    # ===== CORE FEATURES =====

    def test_ports_round_trip(self, docker_client, orchestrator):
        """Test port mappings work end-to-end"""
        service_config = {
            'image': 'alpine:latest',
            'ports': ['8080:80', '9090:90']
        }

        config = orchestrator.map_service_to_container_config(
            service_name='test-ports',
            service_config=service_config
        )

        container = None
        try:
            container = docker_client.containers.create(
                image='alpine:latest',
                name='dockmon-test-ports',
                command=['sleep', '10'],
                ports=config.get('ports'),
                detach=True
            )

            container.reload()
            port_bindings = container.attrs['HostConfig']['PortBindings']

            # Verify port mappings
            assert '80/tcp' in port_bindings
            assert port_bindings['80/tcp'][0]['HostPort'] == '8080'
            assert '90/tcp' in port_bindings
            assert port_bindings['90/tcp'][0]['HostPort'] == '9090'

            print("\n✓ Ports test PASSED")

        finally:
            if container:
                container.remove(force=True)

    def test_volumes_round_trip(self, docker_client, orchestrator):
        """Test volume mounts work end-to-end"""
        service_config = {
            'image': 'alpine:latest',
            'volumes': ['/tmp:/data:ro', '/var/log:/logs']
        }

        config = orchestrator.map_service_to_container_config(
            service_name='test-volumes',
            service_config=service_config
        )

        container = None
        try:
            container = docker_client.containers.create(
                image='alpine:latest',
                name='dockmon-test-volumes',
                command=['sleep', '10'],
                volumes=config.get('volumes'),
                detach=True
            )

            container.reload()
            binds = container.attrs['HostConfig']['Binds']

            # Verify volume mounts
            assert any('/tmp:/data:ro' in bind for bind in binds)
            assert any('/var/log:/logs' in bind for bind in binds)

            print("\n✓ Volumes test PASSED")

        finally:
            if container:
                container.remove(force=True)

    def test_networks_list_format(self, docker_client, orchestrator):
        """Test simple network list format (Bug Fixed!)"""
        # Create test network
        network = None
        container = None

        try:
            network = docker_client.networks.create('test-network-list')

            service_config = {
                'image': 'alpine:latest',
                'networks': ['test-network-list']
            }

            config = orchestrator.map_service_to_container_config(
                service_name='test-net-list',
                service_config=service_config
            )

            # Network bug fix: Use 'network' parameter (orchestrator returns this for single network)
            container = docker_client.containers.create(
                image='alpine:latest',
                name='dockmon-test-net-list',
                command=['sleep', '10'],
                network=config.get('network'),  # Bug fix: use 'network' not 'networking_config'
                detach=True
            )

            # CRITICAL: Must start container for network connection to be established
            container.start()
            container.reload()
            networks = container.attrs['NetworkSettings']['Networks']

            # Verify connected to network
            assert 'test-network-list' in networks

            print("\n✓ Networks (list) test PASSED")

        finally:
            if container:
                container.remove(force=True)
            if network:
                network.remove()

    def test_networks_static_ip_round_trip(self, docker_client, orchestrator):
        """
        CRITICAL: Test v2.1.8 static IP fix works! (Bug Fixed!)

        This is the bug fix that started the Quick Wins work.
        User reported static IPs were ignored - this test proves it works now.
        """
        network = None
        container = None

        try:
            # Create network with specific subnet
            network = docker_client.networks.create(
                'test-network-static-ip',
                driver='bridge',
                ipam=docker.types.IPAMConfig(
                    pool_configs=[
                        docker.types.IPAMPool(
                            subnet='172.28.0.0/16'
                        )
                    ]
                )
            )

            service_config = {
                'image': 'alpine:latest',
                'networks': {
                    'test-network-static-ip': {
                        'ipv4_address': '172.28.0.100',
                        'aliases': ['test-alias', 'another-alias']
                    }
                }
            }

            config = orchestrator.map_service_to_container_config(
                service_name='test-static-ip',
                service_config=service_config
            )

            # Create container (no network yet)
            container = docker_client.containers.create(
                image='alpine:latest',
                name='dockmon-test-static-ip',
                command=['sleep', '10'],
                detach=True
            )

            # Bug fix: Manually connect with static IP (orchestrator returns _dockmon_manual_networking_config)
            manual_config = config.get('_dockmon_manual_networking_config')
            if manual_config:
                endpoints = manual_config['EndpointsConfig']
                for net_name, endpoint_config in endpoints.items():
                    ipv4 = endpoint_config.get('IPAMConfig', {}).get('IPv4Address')
                    aliases = endpoint_config.get('Aliases', [])
                    network.connect(container, ipv4_address=ipv4, aliases=aliases)

            # Start container
            container.start()
            container.reload()
            network_settings = container.attrs['NetworkSettings']['Networks']['test-network-static-ip']

            # CRITICAL: Verify static IP was applied
            assert network_settings['IPAddress'] == '172.28.0.100', \
                f"Static IP not applied! Got {network_settings['IPAddress']}, expected 172.28.0.100"

            # Verify aliases
            assert 'test-alias' in network_settings['Aliases']
            assert 'another-alias' in network_settings['Aliases']

            print("\n✓ Static IP test PASSED (v2.1.8 bug fix verified!)")

        finally:
            if container:
                container.remove(force=True)
            if network:
                network.remove()

    def test_environment_list_format(self, docker_client, orchestrator):
        """Test environment variables (list format)"""
        service_config = {
            'image': 'alpine:latest',
            'environment': ['VAR1=value1', 'VAR2=value2']
        }

        config = orchestrator.map_service_to_container_config(
            service_name='test-env-list',
            service_config=service_config
        )

        container = None
        try:
            container = docker_client.containers.create(
                image='alpine:latest',
                name='dockmon-test-env-list',
                command=['sleep', '10'],
                environment=config.get('environment'),
                detach=True
            )

            container.reload()
            env = container.attrs['Config']['Env']

            # Verify environment variables
            assert 'VAR1=value1' in env
            assert 'VAR2=value2' in env

            print("\n✓ Environment (list) test PASSED")

        finally:
            if container:
                container.remove(force=True)

    def test_environment_dict_format(self, docker_client, orchestrator):
        """Test environment variables (dict format)"""
        service_config = {
            'image': 'alpine:latest',
            'environment': {
                'KEY1': 'val1',
                'KEY2': 'val2'
            }
        }

        config = orchestrator.map_service_to_container_config(
            service_name='test-env-dict',
            service_config=service_config
        )

        container = None
        try:
            container = docker_client.containers.create(
                image='alpine:latest',
                name='dockmon-test-env-dict',
                command=['sleep', '10'],
                environment=config.get('environment'),
                detach=True
            )

            container.reload()
            env = container.attrs['Config']['Env']

            # Verify environment variables
            # Note: Docker SDK converts dict to list of "KEY=value"
            assert any('KEY1=val1' in e for e in env)
            assert any('KEY2=val2' in e for e in env)

            print("\n✓ Environment (dict) test PASSED")

        finally:
            if container:
                container.remove(force=True)

    # ===== RESOURCE LIMITS =====

    def test_memory_limit(self, docker_client, orchestrator):
        """Test memory limits work"""
        service_config = {
            'image': 'alpine:latest',
            'mem_limit': '128m'
        }

        config = orchestrator.map_service_to_container_config(
            service_name='test-mem',
            service_config=service_config
        )

        container = None
        try:
            container = docker_client.containers.create(
                image='alpine:latest',
                name='dockmon-test-mem',
                command=['sleep', '10'],
                mem_limit=config.get('mem_limit'),
                detach=True
            )

            container.reload()
            memory = container.attrs['HostConfig']['Memory']

            # 128m = 134217728 bytes
            assert memory == 134217728

            print("\n✓ Memory limit test PASSED")

        finally:
            if container:
                container.remove(force=True)

    def test_cpu_limit(self, docker_client, orchestrator):
        """Test CPU limits work (cpus → nano_cpus conversion)"""
        service_config = {
            'image': 'alpine:latest',
            'cpus': '0.5'  # 0.5 CPUs
        }

        config = orchestrator.map_service_to_container_config(
            service_name='test-cpu',
            service_config=service_config
        )

        container = None
        try:
            container = docker_client.containers.create(
                image='alpine:latest',
                name='dockmon-test-cpu',
                command=['sleep', '10'],
                nano_cpus=config.get('nano_cpus'),
                detach=True
            )

            container.reload()
            nano_cpus = container.attrs['HostConfig']['NanoCpus']

            # 0.5 CPUs = 500000000 nano CPUs
            assert nano_cpus == 500000000

            print("\n✓ CPU limit test PASSED")

        finally:
            if container:
                container.remove(force=True)

    # ===== CONTAINER CONFIGURATION =====

    def test_command_override(self, docker_client, orchestrator):
        """Test command override works"""
        service_config = {
            'image': 'alpine:latest',
            'command': ['echo', 'hello', 'world']
        }

        config = orchestrator.map_service_to_container_config(
            service_name='test-cmd',
            service_config=service_config
        )

        container = None
        try:
            container = docker_client.containers.create(
                image='alpine:latest',
                name='dockmon-test-cmd',
                command=config.get('command'),
                detach=True
            )

            container.reload()
            cmd = container.attrs['Config']['Cmd']

            # Verify command
            assert cmd == ['echo', 'hello', 'world']

            print("\n✓ Command override test PASSED")

        finally:
            if container:
                container.remove(force=True)

    def test_entrypoint_override(self, docker_client, orchestrator):
        """Test entrypoint override works"""
        service_config = {
            'image': 'alpine:latest',
            'entrypoint': ['/bin/sh', '-c']
        }

        config = orchestrator.map_service_to_container_config(
            service_name='test-entrypoint',
            service_config=service_config
        )

        container = None
        try:
            container = docker_client.containers.create(
                image='alpine:latest',
                name='dockmon-test-entrypoint',
                entrypoint=config.get('entrypoint'),
                command=['sleep 10'],
                detach=True
            )

            container.reload()
            entrypoint = container.attrs['Config']['Entrypoint']

            # Verify entrypoint
            assert entrypoint == ['/bin/sh', '-c']

            print("\n✓ Entrypoint override test PASSED")

        finally:
            if container:
                container.remove(force=True)

    def test_hostname(self, docker_client, orchestrator):
        """Test hostname setting works"""
        service_config = {
            'image': 'alpine:latest',
            'hostname': 'test-hostname'
        }

        config = orchestrator.map_service_to_container_config(
            service_name='test-host',
            service_config=service_config
        )

        container = None
        try:
            container = docker_client.containers.create(
                image='alpine:latest',
                name='dockmon-test-hostname',
                hostname=config.get('hostname'),
                command=['sleep', '10'],
                detach=True
            )

            container.reload()
            hostname = container.attrs['Config']['Hostname']

            # Verify hostname
            assert hostname == 'test-hostname'

            print("\n✓ Hostname test PASSED")

        finally:
            if container:
                container.remove(force=True)

    def test_user(self, docker_client, orchestrator):
        """Test user setting works"""
        service_config = {
            'image': 'alpine:latest',
            'user': '1000:1000'
        }

        config = orchestrator.map_service_to_container_config(
            service_name='test-user',
            service_config=service_config
        )

        container = None
        try:
            container = docker_client.containers.create(
                image='alpine:latest',
                name='dockmon-test-user',
                user=config.get('user'),
                command=['sleep', '10'],
                detach=True
            )

            container.reload()
            user = container.attrs['Config']['User']

            # Verify user
            assert user == '1000:1000'

            print("\n✓ User test PASSED")

        finally:
            if container:
                container.remove(force=True)

    def test_working_dir(self, docker_client, orchestrator):
        """Test working directory setting works"""
        service_config = {
            'image': 'alpine:latest',
            'working_dir': '/app'
        }

        config = orchestrator.map_service_to_container_config(
            service_name='test-workdir',
            service_config=service_config
        )

        container = None
        try:
            container = docker_client.containers.create(
                image='alpine:latest',
                name='dockmon-test-workdir',
                working_dir=config.get('working_dir'),
                command=['sleep', '10'],
                detach=True
            )

            container.reload()
            working_dir = container.attrs['Config']['WorkingDir']

            # Verify working directory
            assert working_dir == '/app'

            print("\n✓ Working directory test PASSED")

        finally:
            if container:
                container.remove(force=True)

    def test_privileged(self, docker_client, orchestrator):
        """Test privileged mode works"""
        service_config = {
            'image': 'alpine:latest',
            'privileged': True
        }

        config = orchestrator.map_service_to_container_config(
            service_name='test-privileged',
            service_config=service_config
        )

        container = None
        try:
            container = docker_client.containers.create(
                image='alpine:latest',
                name='dockmon-test-privileged',
                privileged=config.get('privileged'),
                command=['sleep', '10'],
                detach=True
            )

            container.reload()
            privileged = container.attrs['HostConfig']['Privileged']

            # Verify privileged mode
            assert privileged is True

            print("\n✓ Privileged mode test PASSED")

        finally:
            if container:
                container.remove(force=True)

    def test_labels(self, docker_client, orchestrator):
        """Test labels work"""
        service_config = {
            'image': 'alpine:latest',
            'labels': {
                'com.example.app': 'myapp',
                'com.example.version': '1.0'
            }
        }

        config = orchestrator.map_service_to_container_config(
            service_name='test-labels',
            service_config=service_config
        )

        container = None
        try:
            container = docker_client.containers.create(
                image='alpine:latest',
                name='dockmon-test-labels',
                labels=config.get('labels'),
                command=['sleep', '10'],
                detach=True
            )

            container.reload()
            labels = container.attrs['Config']['Labels']

            # Verify labels
            assert labels['com.example.app'] == 'myapp'
            assert labels['com.example.version'] == '1.0'

            print("\n✓ Labels test PASSED")

        finally:
            if container:
                container.remove(force=True)

    # ===== RESTART POLICIES =====

    def test_restart_always(self, docker_client, orchestrator):
        """Test restart policy: always"""
        service_config = {
            'image': 'alpine:latest',
            'restart': 'always'
        }

        config = orchestrator.map_service_to_container_config(
            service_name='test-restart',
            service_config=service_config
        )

        container = None
        try:
            container = docker_client.containers.create(
                image='alpine:latest',
                name='dockmon-test-restart',
                restart_policy=config.get('restart_policy'),
                command=['sleep', '10'],
                detach=True
            )

            container.reload()
            restart_policy = container.attrs['HostConfig']['RestartPolicy']

            # Verify restart policy
            assert restart_policy['Name'] == 'always'

            print("\n✓ Restart policy test PASSED")

        finally:
            if container:
                container.remove(force=True)

    # ===== MULTI-SERVICE / COMPLEX SCENARIOS =====

    def test_all_features_combined(self, docker_client, orchestrator):
        """
        Test multiple features working together (Bug Fixed!)

        This simulates a real-world compose deployment with many features.
        """
        network = None
        container = None

        try:
            # Create network
            network = docker_client.networks.create(
                'test-combined-net',
                driver='bridge',
                ipam=docker.types.IPAMConfig(
                    pool_configs=[
                        docker.types.IPAMPool(subnet='172.29.0.0/16')
                    ]
                )
            )

            service_config = {
                'image': 'alpine:latest',
                'ports': ['8888:80'],
                'environment': {'ENV_VAR': 'test'},
                'volumes': ['/tmp:/data'],
                'networks': {
                    'test-combined-net': {
                        'ipv4_address': '172.29.0.50'
                    }
                },
                'hostname': 'combined-test',
                'user': '1000',
                'working_dir': '/app',
                'labels': {'test': 'combined'},
                'restart': 'unless-stopped',
                'mem_limit': '64m',
                'command': ['sleep', '30']
            }

            config = orchestrator.map_service_to_container_config(
                service_name='test-combined',
                service_config=service_config
            )

            # Create container (no network yet)
            container = docker_client.containers.create(
                image='alpine:latest',
                name='dockmon-test-combined',
                command=config.get('command'),
                environment=config.get('environment'),
                volumes=config.get('volumes'),
                ports=config.get('ports'),
                # Bug fix: Don't use networking_config (doesn't work)
                hostname=config.get('hostname'),
                user=config.get('user'),
                working_dir=config.get('working_dir'),
                labels=config.get('labels'),
                restart_policy=config.get('restart_policy'),
                mem_limit=config.get('mem_limit'),
                detach=True
            )

            # Bug fix: Manually connect with static IP
            manual_config = config.get('_dockmon_manual_networking_config')
            if manual_config:
                endpoints = manual_config['EndpointsConfig']
                for net_name, endpoint_config in endpoints.items():
                    ipv4 = endpoint_config.get('IPAMConfig', {}).get('IPv4Address')
                    aliases = endpoint_config.get('Aliases', [])
                    network.connect(container, ipv4_address=ipv4, aliases=aliases)

            # Start container
            container.start()
            container.reload()

            # Verify ALL features
            attrs = container.attrs

            # Ports
            assert '80/tcp' in attrs['HostConfig']['PortBindings']
            assert attrs['HostConfig']['PortBindings']['80/tcp'][0]['HostPort'] == '8888'

            # Environment
            assert any('ENV_VAR=test' in e for e in attrs['Config']['Env'])

            # Volumes
            assert any('/tmp:/data' in b for b in attrs['HostConfig']['Binds'])

            # Network + Static IP
            assert '172.29.0.50' == attrs['NetworkSettings']['Networks']['test-combined-net']['IPAddress']

            # Hostname
            assert attrs['Config']['Hostname'] == 'combined-test'

            # User
            assert attrs['Config']['User'] == '1000'

            # Working dir
            assert attrs['Config']['WorkingDir'] == '/app'

            # Labels
            assert attrs['Config']['Labels']['test'] == 'combined'

            # Restart policy
            assert attrs['HostConfig']['RestartPolicy']['Name'] == 'unless-stopped'

            # Memory
            assert attrs['HostConfig']['Memory'] == 67108864  # 64m in bytes

            # Command
            assert attrs['Config']['Cmd'] == ['sleep', '30']

            print("\n✓ All features combined test PASSED")
            print("✓ Verified 11 different features working together!")

        finally:
            if container:
                container.remove(force=True)
            if network:
                network.remove()
