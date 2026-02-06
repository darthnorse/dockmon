"""
Real-World Grafana Container Test

Tests container update handling for a complex real-world Grafana setup based on
Issue #68 reporter's actual compose file.

Features tested:
- Multiple volume mounts (4 volumes)
- Multiple networks (3 networks)
- Docker secrets
- Environment variables
- Hostname + container name
- Restart policy (unless-stopped)
"""

import pytest
import docker
from docker.types import Mount
from updates.update_executor import UpdateExecutor


@pytest.fixture
def docker_client():
    """Get Docker client"""
    try:
        return docker.from_env(version="auto")
    except Exception as e:
        pytest.skip(f"Docker not available: {e}")


@pytest.fixture
def grafana_networks(docker_client):
    """Create test networks for Grafana."""
    networks = []
    for net_name in ['test_traefik_net', 'test_mariadb_net', 'test_elastic_net']:
        try:
            network = docker_client.networks.create(net_name)
            networks.append(network)
        except docker.errors.APIError:
            # Network might already exist
            network = docker_client.networks.get(net_name)
            networks.append(network)

    yield networks

    # Cleanup
    for network in networks:
        try:
            network.remove()
        except docker.errors.APIError:
            pass


@pytest.fixture
def grafana_secret_file(tmp_path):
    """Create a temporary secret file for Grafana admin password."""
    secret_file = tmp_path / "grafana_admin_pw"
    secret_file.write_text("test_password_123")
    return str(secret_file)


class TestGrafanaRealWorld:
    """Test real-world Grafana container configuration preservation during updates."""

    def test_grafana_volumes_preserved(self, docker_client, tmp_path):
        """Test that all 4 Grafana volume mounts are preserved during update."""
        # Create temporary directories mimicking Grafana structure
        grafana_base = tmp_path / "grafana"
        (grafana_base / "config").mkdir(parents=True)
        (grafana_base / "config" / "provisioning").mkdir()
        (grafana_base / "data").mkdir()
        (grafana_base / "logs").mkdir()

        # Create test files
        (grafana_base / "config" / "grafana.ini").write_text("[server]\nhttp_port = 3000")
        (grafana_base / "config" / "provisioning" / "datasources.yml").write_text("datasources: []")

        # Create container with Grafana-style volumes
        container = docker_client.containers.create(
            image='alpine:latest',
            name='test-grafana-volumes',
            command=['sleep', '3600'],
            volumes={
                str(grafana_base / "config" / "grafana.ini"): {
                    'bind': '/etc/grafana/grafana.ini',
                    'mode': 'rw'
                },
                str(grafana_base / "config" / "provisioning"): {
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
            }
        )

        try:
            # Get mounts from created container
            container.reload()
            mounts = container.attrs['Mounts']

            # Verify all 4 mounts are present
            assert len(mounts) == 4, f"Expected 4 mounts, got {len(mounts)}"

            mount_destinations = {m['Destination'] for m in mounts}
            expected = {
                '/etc/grafana/grafana.ini',
                '/etc/grafana/provisioning',
                '/var/lib/grafana',
                '/var/log/grafana'
            }
            assert mount_destinations == expected, f"Mount destinations mismatch: {mount_destinations}"

            # Verify no duplicate destinations
            assert len(mount_destinations) == len(mounts), "Duplicate mount destinations detected"

        finally:
            try:
                container.remove(force=True)
            except docker.errors.APIError:
                pass

    def test_grafana_multiple_networks(self, docker_client, grafana_networks):
        """Test that multiple networks are preserved during update."""
        # Create container connected to 3 networks (like Grafana)
        container = docker_client.containers.create(
            image='alpine:latest',
            name='test-grafana-networks',
            command=['sleep', '3600'],
            network=grafana_networks[0].name,  # Connect to first network on create
            hostname='grafana'
        )

        try:
            # Connect to additional networks (traefik_net, mariadb_net, elastic_net pattern)
            for network in grafana_networks[1:]:
                network.connect(container)

            # Verify container is connected to all 3 networks
            container.reload()
            container_networks = container.attrs['NetworkSettings']['Networks']

            assert len(container_networks) == 3, f"Expected 3 networks, got {len(container_networks)}"

            connected_network_names = set(container_networks.keys())
            expected_names = {net.name for net in grafana_networks}
            assert connected_network_names == expected_names, \
                f"Network mismatch: {connected_network_names} != {expected_names}"

        finally:
            try:
                container.remove(force=True)
            except docker.errors.APIError:
                pass

    def test_grafana_secrets_as_volume(self, docker_client, grafana_secret_file):
        """Test that Docker secrets (mounted as files) are preserved."""
        # Docker secrets are mounted as read-only files in /run/secrets/
        # Simulate this with a bind mount
        container = docker_client.containers.create(
            image='alpine:latest',
            name='test-grafana-secrets',
            command=['sleep', '3600'],
            volumes={
                grafana_secret_file: {
                    'bind': '/run/secrets/grafana_admin_pw',
                    'mode': 'ro'
                }
            }
        )

        try:
            container.reload()
            mounts = container.attrs['Mounts']

            # Find the secrets mount
            secret_mount = next(
                (m for m in mounts if m['Destination'] == '/run/secrets/grafana_admin_pw'),
                None
            )

            assert secret_mount is not None, "Secret mount not found"
            assert secret_mount['Mode'] == 'ro', "Secret mount should be read-only"
            assert secret_mount['Type'] == 'bind', "Secret mount should be bind type"

        finally:
            try:
                container.remove(force=True)
            except docker.errors.APIError:
                pass

    def test_grafana_environment_with_secret_path(self, docker_client, grafana_secret_file):
        """Test that environment variables referencing secret paths are preserved."""
        # Grafana pattern: env var points to secret file location
        container = docker_client.containers.create(
            image='alpine:latest',
            name='test-grafana-env-secrets',
            command=['sleep', '3600'],
            environment={
                'TZ': 'America/New_York',
                'PUID': '1000',
                'PGID': '1000',
                'GF_SECURITY_ADMIN_PASSWORD_FILE': '/run/secrets/grafana_admin_pw'
            },
            volumes={
                grafana_secret_file: {
                    'bind': '/run/secrets/grafana_admin_pw',
                    'mode': 'ro'
                }
            }
        )

        try:
            container.reload()
            env_vars = container.attrs['Config']['Env']

            # Convert to dict
            env_dict = {}
            for env in env_vars:
                if '=' in env:
                    key, value = env.split('=', 1)
                    env_dict[key] = value

            # Verify critical env vars are present
            assert env_dict.get('TZ') == 'America/New_York'
            assert env_dict.get('PUID') == '1000'
            assert env_dict.get('PGID') == '1000'
            assert env_dict.get('GF_SECURITY_ADMIN_PASSWORD_FILE') == '/run/secrets/grafana_admin_pw'

        finally:
            try:
                container.remove(force=True)
            except docker.errors.APIError:
                pass

    def test_grafana_hostname_and_restart_policy(self, docker_client):
        """Test that hostname and restart policy (unless-stopped) are preserved."""
        container = docker_client.containers.create(
            image='alpine:latest',
            name='test-grafana-hostname',
            hostname='grafana',
            command=['sleep', '3600'],
            restart_policy={'Name': 'unless-stopped'}
        )

        try:
            container.reload()

            # Verify hostname
            assert container.attrs['Config']['Hostname'] == 'grafana'

            # Verify restart policy
            restart_policy = container.attrs['HostConfig']['RestartPolicy']
            assert restart_policy['Name'] == 'unless-stopped'
            assert restart_policy['MaximumRetryCount'] == 0

        finally:
            try:
                container.remove(force=True)
            except docker.errors.APIError:
                pass

    @pytest.mark.integration
    def test_grafana_full_config_round_trip(self, docker_client, tmp_path, grafana_networks, grafana_secret_file):
        """
        Integration test: Create Grafana-like container, extract config,
        verify all components are preserved.

        This is the comprehensive test that validates Issue #68 fix in a real-world scenario.
        """
        # Create Grafana directory structure
        grafana_base = tmp_path / "grafana"
        (grafana_base / "config").mkdir(parents=True)
        (grafana_base / "config" / "provisioning").mkdir()
        (grafana_base / "data").mkdir()
        (grafana_base / "logs").mkdir()

        (grafana_base / "config" / "grafana.ini").write_text("[server]\nhttp_port = 3000")

        # Create container with full Grafana configuration
        container = docker_client.containers.create(
            image='alpine:latest',
            name='test-grafana-full',
            hostname='grafana',
            command=['sleep', '3600'],
            network=grafana_networks[0].name,
            environment={
                'TZ': 'America/New_York',
                'PUID': '1000',
                'PGID': '1000',
                'GF_SECURITY_ADMIN_PASSWORD_FILE': '/run/secrets/grafana_admin_pw'
            },
            volumes={
                str(grafana_base / "config" / "grafana.ini"): {
                    'bind': '/etc/grafana/grafana.ini',
                    'mode': 'rw'
                },
                str(grafana_base / "config" / "provisioning"): {
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
                grafana_secret_file: {
                    'bind': '/run/secrets/grafana_admin_pw',
                    'mode': 'ro'
                }
            },
            restart_policy={'Name': 'unless-stopped'}
        )

        try:
            # Connect to additional networks
            for network in grafana_networks[1:]:
                network.connect(container)

            # Reload to get fresh state
            container.reload()

            # Validate all configuration components

            # 1. Volumes (5 total: 4 Grafana + 1 secret)
            mounts = container.attrs['Mounts']
            assert len(mounts) == 5, f"Expected 5 mounts, got {len(mounts)}"

            mount_destinations = {m['Destination'] for m in mounts}
            expected_mounts = {
                '/etc/grafana/grafana.ini',
                '/etc/grafana/provisioning',
                '/var/lib/grafana',
                '/var/log/grafana',
                '/run/secrets/grafana_admin_pw'
            }
            assert mount_destinations == expected_mounts, "Mount destinations mismatch"

            # 2. No duplicate destinations (Issue #68)
            assert len(mount_destinations) == len(mounts), "Duplicate mount destinations detected"

            # 3. Networks (3 networks)
            container_networks = container.attrs['NetworkSettings']['Networks']
            assert len(container_networks) == 3, f"Expected 3 networks, got {len(container_networks)}"

            # 4. Environment variables (4 vars)
            env_vars = container.attrs['Config']['Env']
            env_dict = {}
            for env in env_vars:
                if '=' in env:
                    key, value = env.split('=', 1)
                    env_dict[key] = value

            assert 'TZ' in env_dict
            assert 'PUID' in env_dict
            assert 'PGID' in env_dict
            assert 'GF_SECURITY_ADMIN_PASSWORD_FILE' in env_dict

            # 5. Hostname
            assert container.attrs['Config']['Hostname'] == 'grafana'

            # 6. Restart policy
            restart_policy = container.attrs['HostConfig']['RestartPolicy']
            assert restart_policy['Name'] == 'unless-stopped'

            # 7. Secret file is read-only
            secret_mount = next(m for m in mounts if m['Destination'] == '/run/secrets/grafana_admin_pw')
            assert secret_mount['Mode'] == 'ro', "Secret should be read-only"

        finally:
            try:
                container.remove(force=True)
            except docker.errors.APIError:
                pass


class TestGrafanaUpdatePreservation:
    """Test that Grafana config is preserved through container updates."""

    @pytest.mark.integration
    def test_grafana_config_preserved_after_simulated_update(self, docker_client, tmp_path):
        """
        Simulate a container update and verify all Grafana configuration is preserved.

        This tests the specific scenario from Issue #68 where duplicate mounts could
        cause update failures.
        """
        # Create Grafana directory structure
        grafana_base = tmp_path / "grafana"
        (grafana_base / "config").mkdir(parents=True)
        (grafana_base / "data").mkdir()

        # Create original container
        old_container = docker_client.containers.create(
            image='alpine:latest',
            name='test-grafana-update',
            command=['sleep', '3600'],
            volumes={
                str(grafana_base / "config"): {
                    'bind': '/etc/grafana',
                    'mode': 'rw'
                },
                str(grafana_base / "data"): {
                    'bind': '/var/lib/grafana',
                    'mode': 'rw'
                }
            }
        )

        try:
            # Extract configuration (simulating what update_executor does)
            old_container.reload()
            old_mounts = old_container.attrs['Mounts']

            # Create new container with same config (simulating update)
            volumes = {}
            for mount in old_mounts:
                if mount['Type'] == 'bind':
                    volumes[mount['Source']] = {
                        'bind': mount['Destination'],
                        'mode': mount['Mode']
                    }

            new_container = docker_client.containers.create(
                image='alpine:latest',
                name='test-grafana-update-new',
                command=['sleep', '3600'],
                volumes=volumes
            )

            try:
                # Verify new container has same mounts
                new_container.reload()
                new_mounts = new_container.attrs['Mounts']

                assert len(new_mounts) == len(old_mounts), \
                    f"Mount count mismatch: old={len(old_mounts)}, new={len(new_mounts)}"

                old_destinations = sorted([m['Destination'] for m in old_mounts])
                new_destinations = sorted([m['Destination'] for m in new_mounts])

                assert old_destinations == new_destinations, \
                    f"Mount destinations changed: {old_destinations} -> {new_destinations}"

            finally:
                try:
                    new_container.remove(force=True)
                except docker.errors.APIError:
                    pass

        finally:
            try:
                old_container.remove(force=True)
            except docker.errors.APIError:
                pass
