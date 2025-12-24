"""
Unit tests for container configuration extraction in update operations.

Tests Issue #64 fixes: secrets, network, mac_address preservation.
"""
import pytest
from unittest.mock import MagicMock
from updates.update_executor import UpdateExecutor


# =============================================================================
# v2.1.9 NOTICE: This file tests v1 extraction logic (REMOVED)
# =============================================================================
#
# This test file is DISABLED because it tests the old v1 extraction methods:
# - filter_podman_incompatible_params() - REMOVED (52 lines)
# - _extract_container_config() - REMOVED (327 lines)
# - _create_container() - REMOVED (115 lines)
#
# v2.1.9 uses PASSTHROUGH APPROACH instead of field-by-field extraction.
#
# These behaviors are now tested in:
# - test_passthrough_critical.py (7 critical tests)
#
# See: docs/UPDATE_EXECUTOR_PASSTHROUGH_REFACTOR.md
# =============================================================================

import pytest
pytestmark = pytest.mark.skip(reason="v2.1.9: Tests v1 extraction logic (removed)")


class TestContainerConfigExtraction:
    """Test container configuration extraction for update operations."""

    @pytest.mark.asyncio
    async def test_extract_secret_mount_with_target_field(self):
        """Secrets use Target field, not Destination."""
        db = MagicMock()
        executor = UpdateExecutor(db)

        container = MagicMock()
        container.attrs = {
            "Name": "/test-container",
            "Config": {"Env": [], "Labels": {}},
            "HostConfig": {"RestartPolicy": {}, "Binds": None},
            "NetworkSettings": {"Networks": {}},
            "Mounts": [{
                "Type": "bind",
                "Source": "/path/to/secret",
                "Target": "/run/secrets/my_secret",
                "ReadOnly": True
            }]
        }

        config = await executor._extract_container_config(container, {})

        assert "/path/to/secret" in config["volumes"]
        assert config["volumes"]["/path/to/secret"]["bind"] == "/run/secrets/my_secret"
        assert config["volumes"]["/path/to/secret"]["mode"] == "ro"

    @pytest.mark.asyncio
    async def test_extract_mount_with_destination_field(self):
        """Regular mounts use Destination field."""
        db = MagicMock()
        executor = UpdateExecutor(db)

        container = MagicMock()
        container.attrs = {
            "Name": "/test-container",
            "Config": {"Env": [], "Labels": {}},
            "HostConfig": {"RestartPolicy": {}, "Binds": None},
            "NetworkSettings": {"Networks": {}},
            "Mounts": [{
                "Type": "bind",
                "Source": "/host/path",
                "Destination": "/container/path",
                "Mode": "rw"
            }]
        }

        config = await executor._extract_container_config(container, {})

        assert "/host/path" in config["volumes"]
        assert config["volumes"]["/host/path"]["bind"] == "/container/path"
        assert config["volumes"]["/host/path"]["mode"] == "rw"

    @pytest.mark.asyncio
    async def test_extract_readonly_mount(self):
        """ReadOnly boolean should be converted to 'ro' mode."""
        db = MagicMock()
        executor = UpdateExecutor(db)

        container = MagicMock()
        container.attrs = {
            "Name": "/test-container",
            "Config": {"Env": [], "Labels": {}},
            "HostConfig": {"RestartPolicy": {}, "Binds": None},
            "NetworkSettings": {"Networks": {}},
            "Mounts": [{
                "Type": "bind",
                "Source": "/host/path",
                "Destination": "/container/path",
                "ReadOnly": True
            }]
        }

        config = await executor._extract_container_config(container, {})

        assert config["volumes"]["/host/path"]["mode"] == "ro"

    @pytest.mark.asyncio
    async def test_extract_rw_false_mount(self):
        """RW: false should be converted to 'ro' mode."""
        db = MagicMock()
        executor = UpdateExecutor(db)

        container = MagicMock()
        container.attrs = {
            "Name": "/test-container",
            "Config": {"Env": [], "Labels": {}},
            "HostConfig": {"RestartPolicy": {}, "Binds": None},
            "NetworkSettings": {"Networks": {}},
            "Mounts": [{
                "Type": "bind",
                "Source": "/host/path",
                "Destination": "/container/path",
                "RW": False
            }]
        }

        config = await executor._extract_container_config(container, {})

        assert config["volumes"]["/host/path"]["mode"] == "ro"

    @pytest.mark.asyncio
    async def test_extract_custom_network_without_static_ip(self):
        """Container on custom network without static IP should preserve network."""
        db = MagicMock()
        executor = UpdateExecutor(db)

        container = MagicMock()
        container.attrs = {
            "Name": "/test-container",
            "Config": {"Env": [], "Labels": {}},
            "HostConfig": {"RestartPolicy": {}, "NetworkMode": "my_network"},
            "NetworkSettings": {
                "Networks": {
                    "my_network": {
                        "IPAddress": "172.18.0.5",  # Auto-assigned
                        "IPAMConfig": None,  # NOT user-configured
                        "Aliases": None
                    }
                }
            },
            "Mounts": []
        }

        config = await executor._extract_container_config(container, {})

        # Should use simple network parameter, not manual networking
        assert config.get("network") == "my_network"
        assert "_dockmon_manual_networking_config" not in config

    @pytest.mark.asyncio
    async def test_extract_custom_network_with_static_ip(self):
        """Container with static IP should preserve IP configuration."""
        db = MagicMock()
        executor = UpdateExecutor(db)

        container = MagicMock()
        container.attrs = {
            "Name": "/test-container",
            "Config": {"Env": [], "Labels": {}},
            "HostConfig": {"RestartPolicy": {}, "NetworkMode": "my_network"},
            "NetworkSettings": {
                "Networks": {
                    "my_network": {
                        "IPAddress": "172.18.0.100",
                        "IPAMConfig": {
                            "IPv4Address": "172.18.0.100"
                        },
                        "Aliases": None
                    }
                }
            },
            "Mounts": []
        }

        config = await executor._extract_container_config(container, {})

        # Should use manual networking to preserve static IP
        assert "_dockmon_manual_networking_config" in config
        endpoint = config["_dockmon_manual_networking_config"]["EndpointsConfig"]["my_network"]
        assert endpoint["IPAMConfig"]["IPv4Address"] == "172.18.0.100"

    @pytest.mark.asyncio
    async def test_extract_compose_network_with_auto_aliases(self):
        """Docker Compose auto-aliases should be preserved via manual networking."""
        db = MagicMock()
        executor = UpdateExecutor(db)

        container = MagicMock()
        container.attrs = {
            "Name": "/test-secrets-app",
            "Config": {
                "Env": [],
                "Labels": {
                    "com.docker.compose.service": "test-app",
                    "com.docker.compose.project": "dockmon-test"
                }
            },
            "HostConfig": {"RestartPolicy": {}, "NetworkMode": "dockmon-test_test_network"},
            "NetworkSettings": {
                "Networks": {
                    "dockmon-test_test_network": {
                        "IPAddress": "172.22.0.2",
                        "IPAMConfig": None,  # No static IP
                        # Docker Compose auto-adds container name and service name as aliases
                        "Aliases": ["test-secrets-app", "test-app"]
                    }
                }
            },
            "Mounts": []
        }

        config = await executor._extract_container_config(container, {})

        # Should set network AND use manual networking to preserve aliases
        assert config.get("network") == "dockmon-test_test_network"
        assert "_dockmon_manual_networking_config" in config
        endpoint = config["_dockmon_manual_networking_config"]["EndpointsConfig"]["dockmon-test_test_network"]
        # All aliases preserved (container name and service name)
        assert set(endpoint["Aliases"]) == {"test-secrets-app", "test-app"}

    @pytest.mark.asyncio
    async def test_extract_network_with_user_alias(self):
        """All aliases including user-configured should be preserved."""
        db = MagicMock()
        executor = UpdateExecutor(db)

        container = MagicMock()
        container.attrs = {
            "Name": "/myapp",
            "Config": {
                "Env": [],
                "Labels": {
                    "com.docker.compose.service": "web"
                }
            },
            "HostConfig": {"RestartPolicy": {}, "NetworkMode": "my_network"},
            "NetworkSettings": {
                "Networks": {
                    "my_network": {
                        "IPAddress": "172.18.0.5",
                        "IPAMConfig": None,
                        # Has user-configured alias "api" in addition to auto-generated ones
                        "Aliases": ["myapp", "web", "api"]
                    }
                }
            },
            "Mounts": []
        }

        config = await executor._extract_container_config(container, {})

        # Should set network AND use manual networking to preserve all aliases
        assert config.get("network") == "my_network"
        assert "_dockmon_manual_networking_config" in config
        endpoint = config["_dockmon_manual_networking_config"]["EndpointsConfig"]["my_network"]
        # All aliases preserved (container name, service name, and user alias)
        assert set(endpoint["Aliases"]) == {"myapp", "web", "api"}

    @pytest.mark.asyncio
    async def test_extract_mac_address(self):
        """Custom MAC address should be extracted."""
        db = MagicMock()
        executor = UpdateExecutor(db)

        container = MagicMock()
        container.attrs = {
            "Name": "/test-container",
            "Config": {
                "Env": [],
                "Labels": {},
                "MacAddress": "02:42:ac:11:00:02"
            },
            "HostConfig": {"RestartPolicy": {}, "NetworkMode": "bridge"},
            "NetworkSettings": {"Networks": {}},
            "Mounts": []
        }

        config = await executor._extract_container_config(container, {})

        assert config.get("mac_address") == "02:42:ac:11:00:02"

    @pytest.mark.asyncio
    async def test_extract_healthcheck(self):
        """Custom healthcheck should be preserved."""
        db = MagicMock()
        executor = UpdateExecutor(db)

        container = MagicMock()
        container.attrs = {
            "Name": "/test-container",
            "Config": {
                "Env": [],
                "Labels": {},
                "Healthcheck": {
                    "Test": ["CMD", "curl", "-f", "http://localhost/"],
                    "Interval": 30000000000,
                    "Timeout": 5000000000,
                    "Retries": 3
                }
            },
            "HostConfig": {"RestartPolicy": {}},
            "NetworkSettings": {"Networks": {}},
            "Mounts": []
        }

        config = await executor._extract_container_config(container, {})

        assert config.get("healthcheck") is not None
        assert config["healthcheck"]["Test"] == ["CMD", "curl", "-f", "http://localhost/"]

    @pytest.mark.asyncio
    async def test_extract_nvidia_runtime(self):
        """NVIDIA runtime should be preserved for GPU containers."""
        db = MagicMock()
        executor = UpdateExecutor(db)

        container = MagicMock()
        container.attrs = {
            "Name": "/test-gpu",
            "Config": {"Env": [], "Labels": {}},
            "HostConfig": {
                "RestartPolicy": {},
                "Runtime": "nvidia"
            },
            "NetworkSettings": {"Networks": {}},
            "Mounts": []
        }

        config = await executor._extract_container_config(container, {})

        assert config.get("runtime") == "nvidia"

    @pytest.mark.asyncio
    async def test_extract_cpu_memory_limits(self):
        """CPU and memory limits should be preserved."""
        db = MagicMock()
        executor = UpdateExecutor(db)

        container = MagicMock()
        container.attrs = {
            "Name": "/test-limited",
            "Config": {"Env": [], "Labels": {}},
            "HostConfig": {
                "RestartPolicy": {},
                "Memory": 536870912,  # 512MB
                "CpuShares": 512
            },
            "NetworkSettings": {"Networks": {}},
            "Mounts": []
        }

        config = await executor._extract_container_config(container, {})

        assert config.get("mem_limit") == 536870912
        assert config.get("cpu_shares") == 512

    @pytest.mark.asyncio
    async def test_extract_read_only_rootfs(self):
        """Read-only root filesystem should be preserved."""
        db = MagicMock()
        executor = UpdateExecutor(db)

        container = MagicMock()
        container.attrs = {
            "Name": "/test-readonly",
            "Config": {"Env": [], "Labels": {}},
            "HostConfig": {
                "RestartPolicy": {},
                "ReadonlyRootfs": True
            },
            "NetworkSettings": {"Networks": {}},
            "Mounts": []
        }

        config = await executor._extract_container_config(container, {})

        assert config.get("read_only") is True

    @pytest.mark.asyncio
    async def test_extract_sysctls(self):
        """Sysctls should be preserved."""
        db = MagicMock()
        executor = UpdateExecutor(db)

        container = MagicMock()
        container.attrs = {
            "Name": "/test-sysctls",
            "Config": {"Env": [], "Labels": {}},
            "HostConfig": {
                "RestartPolicy": {},
                "Sysctls": {
                    "net.core.somaxconn": "1024",
                    "net.ipv4.tcp_syncookies": "0"
                }
            },
            "NetworkSettings": {"Networks": {}},
            "Mounts": []
        }

        config = await executor._extract_container_config(container, {})

        assert config.get("sysctls") == {
            "net.core.somaxconn": "1024",
            "net.ipv4.tcp_syncookies": "0"
        }

    @pytest.mark.asyncio
    async def test_extract_log_config(self):
        """Custom log configuration should be preserved."""
        db = MagicMock()
        executor = UpdateExecutor(db)

        container = MagicMock()
        container.attrs = {
            "Name": "/test-logging",
            "Config": {"Env": [], "Labels": {}},
            "HostConfig": {
                "RestartPolicy": {},
                "LogConfig": {
                    "Type": "json-file",
                    "Config": {
                        "max-size": "10m",
                        "max-file": "3"
                    }
                }
            },
            "NetworkSettings": {"Networks": {}},
            "Mounts": []
        }

        config = await executor._extract_container_config(container, {})

        assert config.get("log_config") is not None
        assert config["log_config"]["Type"] == "json-file"
        assert config["log_config"]["Config"]["max-size"] == "10m"

    @pytest.mark.asyncio
    async def test_extract_oom_kill_disable(self):
        """OOM kill disable should be preserved for databases."""
        db = MagicMock()
        executor = UpdateExecutor(db)

        container = MagicMock()
        container.attrs = {
            "Name": "/test-database",
            "Config": {"Env": [], "Labels": {}},
            "HostConfig": {
                "RestartPolicy": {},
                "OomKillDisable": True
            },
            "NetworkSettings": {"Networks": {}},
            "Mounts": []
        }

        config = await executor._extract_container_config(container, {})

        assert config.get("oom_kill_disable") is True

    @pytest.mark.asyncio
    async def test_extract_stop_timeout(self):
        """Stop timeout should be preserved."""
        db = MagicMock()
        executor = UpdateExecutor(db)

        container = MagicMock()
        container.attrs = {
            "Name": "/test-timeout",
            "Config": {"Env": [], "Labels": {}},
            "HostConfig": {
                "RestartPolicy": {},
                "StopTimeout": 30
            },
            "NetworkSettings": {"Networks": {}},
            "Mounts": []
        }

        config = await executor._extract_container_config(container, {})

        assert config.get("stop_timeout") == 30

    @pytest.mark.asyncio
    async def test_extract_pids_limit(self):
        """Pids limit should be preserved."""
        db = MagicMock()
        executor = UpdateExecutor(db)

        container = MagicMock()
        container.attrs = {
            "Name": "/test-pids",
            "Config": {"Env": [], "Labels": {}},
            "HostConfig": {
                "RestartPolicy": {},
                "PidsLimit": 100
            },
            "NetworkSettings": {"Networks": {}},
            "Mounts": []
        }

        config = await executor._extract_container_config(container, {})

        assert config.get("pids_limit") == 100

    @pytest.mark.asyncio
    async def test_extract_init(self):
        """Init process flag should be preserved."""
        db = MagicMock()
        executor = UpdateExecutor(db)

        container = MagicMock()
        container.attrs = {
            "Name": "/test-init",
            "Config": {"Env": [], "Labels": {}},
            "HostConfig": {
                "RestartPolicy": {},
                "Init": True
            },
            "NetworkSettings": {"Networks": {}},
            "Mounts": []
        }

        config = await executor._extract_container_config(container, {})

        assert config.get("init") is True
