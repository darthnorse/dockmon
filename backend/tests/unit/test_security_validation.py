"""
Security validation tests for deployment feature.

Tests dangerous configurations that should be blocked or warned about:
- Dangerous volume mounts (docker.sock, root fs, etc.)
- Privileged containers
- Host network mode
- Dangerous capabilities
- Port conflicts
- Resource limits
"""

import pytest
from backend.deployment.security_validator import (
    SecurityValidator,
    SecurityViolation,
    SecurityLevel,
)


def get_secure_base_config():
    """
    Returns a baseline secure container config with no violations.
    Tests can override specific fields to test individual security issues.
    """
    return {
        "image": "nginx:1.25.3",  # Specific tag (not :latest)
        "mem_limit": "512m",  # Memory limit set
        "cpus": "1.0",  # CPU limit set
    }


@pytest.mark.unit
class TestDangerousMounts:
    """Test detection of dangerous volume mounts."""

    def test_detect_docker_socket_mount(self, test_db):
        """Should detect mounting of /var/run/docker.sock as CRITICAL."""
        config = get_secure_base_config()
        config["volumes"] = {
            "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"}
        }

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        # Should have exactly one CRITICAL violation
        assert len(violations) == 1
        assert violations[0].level == SecurityLevel.CRITICAL
        assert "docker.sock" in violations[0].message.lower()
        assert violations[0].field == "volumes"

    def test_detect_root_filesystem_mount(self, test_db):
        """Should detect mounting of root filesystem as CRITICAL."""
        config = get_secure_base_config()
        config["volumes"] = {
            "/": {"bind": "/host", "mode": "rw"}  # rw to maintain CRITICAL level
        }

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        assert len(violations) == 1
        assert violations[0].level == SecurityLevel.CRITICAL
        assert "root filesystem" in violations[0].message.lower()

    def test_detect_etc_mount(self, test_db):
        """Should detect mounting of /etc as HIGH severity."""
        config = get_secure_base_config()
        config["volumes"] = {
            "/etc": {"bind": "/host-etc", "mode": "rw"}  # rw to maintain HIGH level
        }

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        assert len(violations) == 1
        assert violations[0].level == SecurityLevel.HIGH
        assert "/etc" in violations[0].message

    def test_detect_proc_mount(self, test_db):
        """Should detect mounting of /proc as HIGH severity."""
        config = get_secure_base_config()
        config["volumes"] = {
            "/proc": {"bind": "/host-proc", "mode": "rw"}  # rw to maintain HIGH level
        }

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        assert len(violations) == 1
        assert violations[0].level == SecurityLevel.HIGH

    def test_detect_sys_mount(self, test_db):
        """Should detect mounting of /sys as HIGH severity."""
        config = get_secure_base_config()
        config["volumes"] = {
            "/sys": {"bind": "/host-sys", "mode": "rw"}  # rw to maintain HIGH level
        }

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        assert len(violations) == 1
        assert violations[0].level == SecurityLevel.HIGH

    def test_readonly_mount_reduces_severity(self, test_db):
        """Read-only mounts should be less severe than read-write."""
        rw_config = get_secure_base_config()
        rw_config["volumes"] = {
            "/etc": {"bind": "/host-etc", "mode": "rw"}
        }

        ro_config = get_secure_base_config()
        ro_config["volumes"] = {
            "/etc": {"bind": "/host-etc", "mode": "ro"}
        }

        validator = SecurityValidator()
        rw_violations = validator.validate_container_config(rw_config)
        ro_violations = validator.validate_container_config(ro_config)

        # Read-write should be more severe
        assert rw_violations[0].level.value > ro_violations[0].level.value

    def test_safe_volume_mounts_pass(self, test_db):
        """Normal volume mounts should not trigger violations."""
        config = get_secure_base_config()
        config["volumes"] = {
            "/app/data": {"bind": "/data", "mode": "rw"},
            "/var/log/nginx": {"bind": "/logs", "mode": "rw"}
        }

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        assert len(violations) == 0

    def test_multiple_dangerous_mounts(self, test_db):
        """Should detect multiple dangerous mounts."""
        config = get_secure_base_config()
        config["volumes"] = {
            "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
            "/etc": {"bind": "/host-etc", "mode": "ro"},
            "/proc": {"bind": "/host-proc", "mode": "ro"}
        }

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        # Should detect all three dangerous mounts
        assert len(violations) == 3

    def test_detect_docker_socket_mount_list_format(self, test_db):
        """Should detect mounting of /var/run/docker.sock in list format."""
        config = get_secure_base_config()
        config["volumes"] = [
            "/var/run/docker.sock:/var/run/docker.sock:rw"
        ]

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        # Should have exactly one CRITICAL violation
        assert len(violations) == 1
        assert violations[0].level == SecurityLevel.CRITICAL
        assert "docker.sock" in violations[0].message.lower()
        assert violations[0].field == "volumes"

    def test_detect_dangerous_mounts_list_format(self, test_db):
        """Should detect multiple dangerous mounts in list format."""
        config = get_secure_base_config()
        config["volumes"] = [
            "/var/run/docker.sock:/var/run/docker.sock:rw",
            "/etc:/host-etc:ro",
            "/proc:/host-proc:ro"
        ]

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        # Should detect all three dangerous mounts
        assert len(violations) == 3

    def test_readonly_mount_reduces_severity_list_format(self, test_db):
        """Read-only mounts in list format should be less severe."""
        rw_config = get_secure_base_config()
        rw_config["volumes"] = ["/etc:/host-etc:rw"]

        ro_config = get_secure_base_config()
        ro_config["volumes"] = ["/etc:/host-etc:ro"]

        validator = SecurityValidator()
        rw_violations = validator.validate_container_config(rw_config)
        ro_violations = validator.validate_container_config(ro_config)

        # Read-write should be more severe
        assert rw_violations[0].level.value > ro_violations[0].level.value

    def test_safe_volume_mounts_list_format_pass(self, test_db):
        """Normal volume mounts in list format should not trigger violations."""
        config = get_secure_base_config()
        config["volumes"] = [
            "/app/data:/data:rw",
            "/var/log/nginx:/logs:rw"
        ]

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        assert len(violations) == 0


@pytest.mark.unit
class TestPrivilegedContainers:
    """Test detection of privileged container configurations."""

    def test_detect_privileged_flag(self, test_db):
        """Should detect privileged=true as CRITICAL."""
        config = get_secure_base_config()
        config["privileged"] = True

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        assert len(violations) == 1
        assert violations[0].level == SecurityLevel.CRITICAL
        assert "privileged" in violations[0].message.lower()
        assert violations[0].field == "privileged"

    def test_privileged_false_passes(self, test_db):
        """Privileged=false should not trigger violation."""
        config = get_secure_base_config()
        config["privileged"] = False

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        assert len(violations) == 0


@pytest.mark.unit
class TestHostNetworkMode:
    """Test detection of host network mode."""

    def test_detect_host_network_mode(self, test_db):
        """Should detect network_mode=host as HIGH severity."""
        config = get_secure_base_config()
        config["network_mode"] = "host"

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        assert len(violations) == 1
        assert violations[0].level == SecurityLevel.HIGH
        assert "host network" in violations[0].message.lower()
        assert violations[0].field == "network_mode"

    def test_bridge_network_mode_passes(self, test_db):
        """Bridge network mode should not trigger violation."""
        config = get_secure_base_config()
        config["network_mode"] = "bridge"

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        assert len(violations) == 0

    def test_custom_network_passes(self, test_db):
        """Custom networks should not trigger violation."""
        config = get_secure_base_config()
        config["network_mode"] = "my-custom-network"

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        assert len(violations) == 0


@pytest.mark.unit
class TestDangerousCapabilities:
    """Test detection of dangerous Linux capabilities."""

    def test_detect_sys_admin_capability(self, test_db):
        """Should detect CAP_SYS_ADMIN as HIGH severity."""
        config = get_secure_base_config()
        config["cap_add"] = ["SYS_ADMIN"]

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        assert len(violations) == 1
        assert violations[0].level == SecurityLevel.HIGH
        assert "SYS_ADMIN" in violations[0].message

    def test_detect_net_admin_capability(self, test_db):
        """Should detect CAP_NET_ADMIN as MEDIUM severity."""
        config = get_secure_base_config()
        config["cap_add"] = ["NET_ADMIN"]

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        assert len(violations) == 1
        assert violations[0].level == SecurityLevel.MEDIUM

    def test_detect_sys_module_capability(self, test_db):
        """Should detect CAP_SYS_MODULE as HIGH severity."""
        config = get_secure_base_config()
        config["cap_add"] = ["SYS_MODULE"]

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        assert len(violations) == 1
        assert violations[0].level == SecurityLevel.HIGH

    def test_safe_capabilities_pass(self, test_db):
        """Safe capabilities should not trigger violations."""
        config = get_secure_base_config()
        config["cap_add"] = ["NET_BIND_SERVICE", "CHOWN"]

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        assert len(violations) == 0

    def test_dropping_capabilities_passes(self, test_db):
        """Dropping capabilities should not trigger violations."""
        config = get_secure_base_config()
        config["cap_drop"] = ["ALL"]

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        assert len(violations) == 0

    def test_multiple_dangerous_capabilities(self, test_db):
        """Should detect multiple dangerous capabilities."""
        config = get_secure_base_config()
        config["cap_add"] = ["SYS_ADMIN", "SYS_MODULE", "NET_ADMIN"]

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        # Should detect all three
        assert len(violations) == 3


@pytest.mark.unit
class TestResourceLimits:
    """Test validation of resource limits."""

    def test_warn_no_memory_limit(self, test_db):
        """Should warn if no memory limit is set."""
        config = {
            "image": "nginx:latest"
            # No mem_limit specified
        }

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        # Should have a LOW severity warning
        memory_warnings = [v for v in violations if "memory" in v.message.lower()]
        assert len(memory_warnings) == 1
        assert memory_warnings[0].level == SecurityLevel.LOW

    def test_memory_limit_specified_passes(self, test_db):
        """Should not warn if memory limit is set."""
        config = {
            "image": "nginx:latest",
            "mem_limit": "512m"
        }

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        # Should have no memory warnings
        memory_warnings = [v for v in violations if "memory" in v.message.lower()]
        assert len(memory_warnings) == 0

    def test_warn_excessive_memory_limit(self, test_db):
        """Should warn if memory limit is excessive (>16GB)."""
        config = {
            "image": "nginx:latest",
            "mem_limit": "32g"
        }

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        # Should have a MEDIUM severity warning
        memory_warnings = [v for v in violations if "memory" in v.message.lower()]
        assert len(memory_warnings) == 1
        assert memory_warnings[0].level == SecurityLevel.MEDIUM

    def test_warn_no_cpu_limit(self, test_db):
        """Should warn if no CPU limit is set."""
        config = {
            "image": "nginx:latest"
            # No cpu_count or cpu_shares specified
        }

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        # Should have a LOW severity warning
        cpu_warnings = [v for v in violations if "cpu" in v.message.lower()]
        assert len(cpu_warnings) == 1
        assert cpu_warnings[0].level == SecurityLevel.LOW


@pytest.mark.unit
class TestPortConflicts:
    """Test detection of port binding conflicts."""

    def test_detect_port_80_conflict(self, test_db, test_host):
        """Should detect if port 80 is already in use on host."""
        # Simulate existing container using port 80
        existing_containers = [
            {
                "id": "abc123def456",
                "ports": {"80/tcp": [{"HostPort": "80"}]}
            }
        ]

        config = {
            "image": "nginx:latest",
            "ports": {"80/tcp": 80}
        }

        validator = SecurityValidator()
        violations = validator.validate_container_config(
            config,
            host_id=test_host.id,
            existing_containers=existing_containers
        )

        # Should detect port conflict
        port_conflicts = [v for v in violations if "port" in v.message.lower()]
        assert len(port_conflicts) == 1
        assert port_conflicts[0].level == SecurityLevel.HIGH
        assert "80" in port_conflicts[0].message

    def test_no_conflict_different_ports(self, test_db, test_host):
        """Should pass if ports don't conflict."""
        existing_containers = [
            {
                "id": "abc123def456",
                "ports": {"80/tcp": [{"HostPort": "80"}]}
            }
        ]

        config = {
            "image": "nginx:latest",
            "ports": {"8080/tcp": 8080}
        }

        validator = SecurityValidator()
        violations = validator.validate_container_config(
            config,
            host_id=test_host.id,
            existing_containers=existing_containers
        )

        # Should have no port conflicts
        port_conflicts = [v for v in violations if "port" in v.message.lower()]
        assert len(port_conflicts) == 0

    def test_detect_multiple_port_conflicts(self, test_db, test_host):
        """Should detect multiple port conflicts."""
        existing_containers = [
            {
                "id": "abc123def456",
                "ports": {
                    "80/tcp": [{"HostPort": "80"}],
                    "443/tcp": [{"HostPort": "443"}]
                }
            }
        ]

        config = {
            "image": "nginx:latest",
            "ports": {
                "80/tcp": 80,
                "443/tcp": 443,
                "8080/tcp": 8080
            }
        }

        validator = SecurityValidator()
        violations = validator.validate_container_config(
            config,
            host_id=test_host.id,
            existing_containers=existing_containers
        )

        # Should detect conflicts for ports 80 and 443
        port_conflicts = [v for v in violations if "port" in v.message.lower()]
        assert len(port_conflicts) == 2


@pytest.mark.unit
class TestImageValidation:
    """Test validation of container images."""

    def test_warn_unsigned_image(self, test_db):
        """Should warn about unsigned images (INFO level)."""
        config = {
            "image": "myregistry.com/unsigned-image:latest"
        }

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        # Should have INFO level warning about unsigned image
        image_warnings = [v for v in violations if "image" in v.message.lower()]
        assert len(image_warnings) >= 1
        # At least one should be about signing/verification
        signing_warnings = [v for v in image_warnings if "sign" in v.message.lower() or "verif" in v.message.lower()]
        assert len(signing_warnings) >= 1

    def test_warn_latest_tag(self, test_db):
        """Should warn about using :latest tag (LOW level)."""
        config = {
            "image": "nginx:latest"
        }

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        # Should have LOW level warning about :latest tag
        tag_warnings = [v for v in violations if "latest" in v.message.lower()]
        assert len(tag_warnings) == 1
        assert tag_warnings[0].level == SecurityLevel.LOW

    def test_specific_tag_passes_latest_check(self, test_db):
        """Specific image tags should not trigger :latest warning."""
        config = {
            "image": "nginx:1.25.3"
        }

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        # Should not warn about :latest
        tag_warnings = [v for v in violations if "latest" in v.message.lower()]
        assert len(tag_warnings) == 0


@pytest.mark.unit
class TestEnvironmentVariableSecurity:
    """Test validation of environment variables."""

    def test_warn_plaintext_password_vars(self, test_db):
        """Should warn about plaintext password environment variables."""
        config = {
            "image": "postgres:15",
            "environment": {
                "POSTGRES_PASSWORD": "my-secret-password",
                "DB_PASSWORD": "another-secret"
            }
        }

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        # Should warn about plaintext passwords
        password_warnings = [v for v in violations if "password" in v.message.lower()]
        assert len(password_warnings) >= 1
        assert password_warnings[0].level == SecurityLevel.MEDIUM

    def test_docker_secrets_pass(self, test_db):
        """Using Docker secrets should not trigger password warning."""
        config = {
            "image": "postgres:15",
            "environment": {
                "POSTGRES_PASSWORD_FILE": "/run/secrets/db_password"
            }
        }

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        # Should not warn - using secrets file
        password_warnings = [v for v in violations if "password" in v.message.lower()]
        assert len(password_warnings) == 0


@pytest.mark.unit
class TestSecurityValidatorUtility:
    """Test SecurityValidator utility methods."""

    def test_get_violations_by_level(self, test_db):
        """Should filter violations by security level."""
        config = {
            "image": "nginx:latest",
            "privileged": True,  # CRITICAL
            "network_mode": "host",  # HIGH
            "cap_add": ["NET_ADMIN"]  # MEDIUM
        }

        validator = SecurityValidator()
        all_violations = validator.validate_container_config(config)

        # Get only CRITICAL violations
        critical = validator.filter_by_level(all_violations, SecurityLevel.CRITICAL)
        assert len(critical) == 1
        assert critical[0].field == "privileged"

        # Get HIGH and above (CRITICAL + HIGH)
        high_and_above = validator.filter_by_level(all_violations, SecurityLevel.HIGH, include_higher=True)
        assert len(high_and_above) == 2

    def test_has_blocking_violations(self, test_db):
        """Should identify if violations are blocking deployment."""
        config_safe = {
            "image": "nginx:1.25.3",
            "mem_limit": "512m"
        }

        config_critical = {
            "image": "nginx:latest",
            "privileged": True
        }

        validator = SecurityValidator()

        safe_violations = validator.validate_container_config(config_safe)
        assert not validator.has_blocking_violations(safe_violations)

        critical_violations = validator.validate_container_config(config_critical)
        assert validator.has_blocking_violations(critical_violations)

    def test_format_violations_for_display(self, test_db):
        """Should format violations for user display."""
        config = {
            "image": "nginx:latest",
            "privileged": True,
            "network_mode": "host"
        }

        validator = SecurityValidator()
        violations = validator.validate_container_config(config)

        # Should return formatted string with all violations
        formatted = validator.format_violations(violations)
        assert isinstance(formatted, str)
        assert "privileged" in formatted.lower()
        assert "host network" in formatted.lower()
        assert len(formatted) > 0
