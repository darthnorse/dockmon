"""
Security validation for container deployments in DockMon v2.1

Validates container configurations for security issues before deployment:
- Dangerous volume mounts (docker.sock, root filesystem, sensitive directories)
- Privileged containers
- Host network mode
- Dangerous Linux capabilities
- Resource limits
- Port conflicts
- Image security (unsigned images, :latest tag)
- Environment variable security (plaintext passwords)

Usage:
    validator = SecurityValidator()
    violations = validator.validate_container_config(config)

    if validator.has_blocking_violations(violations):
        print("Deployment blocked due to security violations:")
        print(validator.format_violations(violations))
    else:
        deploy_container(config)
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Dict, Any, Optional
import re
import logging

logger = logging.getLogger(__name__)


class SecurityLevel(Enum):
    """
    Security violation severity levels.

    Levels:
        CRITICAL (4): Blocks deployment, requires explicit override
        HIGH (3): Strong warning, deployment allowed but discouraged
        MEDIUM (2): Warning, user should review
        LOW (1): Informational, best practice recommendation
        INFO (0): Informational note, no action required
    """
    CRITICAL = 4
    HIGH = 3
    MEDIUM = 2
    LOW = 1
    INFO = 0


@dataclass
class SecurityViolation:
    """
    Represents a security violation found during validation.

    Attributes:
        level: Severity level of the violation
        field: Configuration field that triggered the violation
        message: Human-readable description of the violation
    """
    level: SecurityLevel
    field: str
    message: str


class SecurityValidator:
    """
    Validates container configurations for security issues.

    Performs comprehensive security checks before allowing container deployments.
    Categorizes violations by severity and provides remediation guidance.
    """

    # Dangerous mount paths that should trigger warnings/blocks
    DANGEROUS_MOUNTS = {
        '/var/run/docker.sock': {
            'level': SecurityLevel.CRITICAL,
            'message': 'Mounting docker.sock grants full Docker API access (container escape risk)'
        },
        '/var/run/podman/podman.sock': {
            'level': SecurityLevel.CRITICAL,
            'message': 'Mounting podman.sock grants full Podman API access (container escape risk)'
        },
        '/': {
            'level': SecurityLevel.CRITICAL,
            'message': 'Mounting root filesystem grants full host access'
        },
        '/etc': {
            'level': SecurityLevel.HIGH,
            'message': 'Mounting /etc exposes sensitive host configuration'
        },
        '/proc': {
            'level': SecurityLevel.HIGH,
            'message': 'Mounting /proc exposes host processes and system information'
        },
        '/sys': {
            'level': SecurityLevel.HIGH,
            'message': 'Mounting /sys exposes host kernel interfaces'
        },
        '/boot': {
            'level': SecurityLevel.HIGH,
            'message': 'Mounting /boot exposes bootloader and kernel files'
        },
        '/dev': {
            'level': SecurityLevel.HIGH,
            'message': 'Mounting /dev exposes host devices'
        },
    }

    # Dangerous Linux capabilities
    DANGEROUS_CAPABILITIES = {
        'SYS_ADMIN': {
            'level': SecurityLevel.HIGH,
            'message': 'CAP_SYS_ADMIN grants broad system administration privileges (container escape risk)'
        },
        'SYS_MODULE': {
            'level': SecurityLevel.HIGH,
            'message': 'CAP_SYS_MODULE allows loading kernel modules (container escape risk)'
        },
        'SYS_PTRACE': {
            'level': SecurityLevel.MEDIUM,
            'message': 'CAP_SYS_PTRACE allows debugging other processes (information disclosure risk)'
        },
        'SYS_BOOT': {
            'level': SecurityLevel.HIGH,
            'message': 'CAP_SYS_BOOT allows system reboot'
        },
        'NET_ADMIN': {
            'level': SecurityLevel.MEDIUM,
            'message': 'CAP_NET_ADMIN grants network administration privileges'
        },
        'SYS_RAWIO': {
            'level': SecurityLevel.HIGH,
            'message': 'CAP_SYS_RAWIO allows raw I/O operations (hardware access risk)'
        },
    }

    def validate_container_config(
        self,
        config: Dict[str, Any],
        host_id: Optional[str] = None,
        existing_containers: Optional[List[Dict[str, Any]]] = None
    ) -> List[SecurityViolation]:
        """
        Validate a container configuration for security issues.

        Args:
            config: Container configuration dictionary
            host_id: Host ID for port conflict checking (optional)
            existing_containers: List of existing containers for port conflict checking (optional)

        Returns:
            List of SecurityViolation objects, empty if no violations found

        Examples:
            >>> validator = SecurityValidator()
            >>> config = {"image": "nginx:latest", "privileged": True}
            >>> violations = validator.validate_container_config(config)
            >>> len(violations)
            2  # privileged=True + :latest tag
            >>> violations[0].level
            SecurityLevel.CRITICAL
        """
        violations = []

        # Check volume mounts
        violations.extend(self._check_volume_mounts(config))

        # Check privileged flag
        violations.extend(self._check_privileged(config))

        # Check network mode
        violations.extend(self._check_network_mode(config))

        # Check capabilities
        violations.extend(self._check_capabilities(config))

        # Check resource limits
        violations.extend(self._check_resource_limits(config))

        # Check port conflicts
        if host_id and existing_containers:
            violations.extend(self._check_port_conflicts(config, host_id, existing_containers))

        # Check image security
        violations.extend(self._check_image_security(config))

        # Check environment variables
        violations.extend(self._check_environment_variables(config))

        return violations

    def _check_volume_mounts(self, config: Dict[str, Any]) -> List[SecurityViolation]:
        """Check for dangerous volume mounts."""
        violations = []
        volumes = config.get('volumes', {})

        if not volumes:
            return violations

        # Handle both list and dictionary formats
        # List format: ["/host:/container:ro"]
        # Dict format: {"/host": {"bind": "/container", "mode": "ro"}}
        if isinstance(volumes, list):
            # Parse list format volumes
            for volume_spec in volumes:
                if not isinstance(volume_spec, str):
                    continue

                # Parse volume string: host_path:container_path[:mode]
                parts = volume_spec.split(':')
                if len(parts) < 2:
                    continue  # Invalid volume spec

                host_path = parts[0]
                mode = parts[2] if len(parts) >= 3 else 'rw'

                # Check if this is a dangerous mount
                self._check_dangerous_mount(violations, host_path, mode)

        elif isinstance(volumes, dict):
            # Dictionary format
            for host_path, bind_config in volumes.items():
                # Extract mode from bind config
                mode = 'rw'  # Default
                if isinstance(bind_config, dict):
                    mode = bind_config.get('mode', 'rw')

                # Check if this is a dangerous mount
                self._check_dangerous_mount(violations, host_path, mode)

        return violations

    def _check_dangerous_mount(self, violations: List[SecurityViolation], host_path: str, mode: str) -> None:
        """Check if a mount path is dangerous and add violation if so."""
        # Check against known dangerous paths
        for dangerous_path, danger_info in self.DANGEROUS_MOUNTS.items():
            if host_path == dangerous_path or host_path.startswith(dangerous_path + '/'):
                level = danger_info['level']
                message = danger_info['message']

                # Reduce severity if mount is read-only
                if mode == 'ro':
                    # Downgrade by one level for read-only
                    if level == SecurityLevel.CRITICAL:
                        level = SecurityLevel.HIGH
                    elif level == SecurityLevel.HIGH:
                        level = SecurityLevel.MEDIUM
                    message += ' (read-only reduces risk)'

                violations.append(SecurityViolation(
                    level=level,
                    field='volumes',
                    message=f"Dangerous mount '{host_path}': {message}"
                ))
                return  # Only report once per mount

        # Check for rootless Podman socket pattern: /run/user/*/podman/podman.sock
        if re.match(r'^/run/user/\d+/podman/podman\.sock$', host_path):
            level = SecurityLevel.CRITICAL
            message = 'Mounting podman.sock grants full Podman API access (container escape risk)'

            # Reduce severity if mount is read-only
            if mode == 'ro':
                level = SecurityLevel.HIGH
                message += ' (read-only reduces risk)'

            violations.append(SecurityViolation(
                level=level,
                field='volumes',
                message=f"Dangerous mount '{host_path}': {message}"
            ))

    def _check_privileged(self, config: Dict[str, Any]) -> List[SecurityViolation]:
        """Check for privileged container flag."""
        violations = []

        if config.get('privileged', False):
            violations.append(SecurityViolation(
                level=SecurityLevel.CRITICAL,
                field='privileged',
                message='Privileged mode disables all security isolation (full host access)'
            ))

        return violations

    def _check_network_mode(self, config: Dict[str, Any]) -> List[SecurityViolation]:
        """Check for host network mode."""
        violations = []

        network_mode = config.get('network_mode', 'bridge')
        if network_mode == 'host':
            violations.append(SecurityViolation(
                level=SecurityLevel.HIGH,
                field='network_mode',
                message='Host network mode bypasses network isolation and exposes all host ports'
            ))

        return violations

    def _check_capabilities(self, config: Dict[str, Any]) -> List[SecurityViolation]:
        """Check for dangerous Linux capabilities."""
        violations = []

        cap_add = config.get('cap_add', [])
        if not cap_add:
            return violations

        for capability in cap_add:
            # Normalize capability name (remove CAP_ prefix if present)
            cap_name = capability.upper().replace('CAP_', '')

            if cap_name in self.DANGEROUS_CAPABILITIES:
                danger_info = self.DANGEROUS_CAPABILITIES[cap_name]
                violations.append(SecurityViolation(
                    level=danger_info['level'],
                    field='cap_add',
                    message=f"Dangerous capability '{cap_name}': {danger_info['message']}"
                ))

        return violations

    def _check_resource_limits(self, config: Dict[str, Any]) -> List[SecurityViolation]:
        """Check for resource limit configuration."""
        violations = []

        # Check memory limit
        mem_limit = config.get('mem_limit')
        if not mem_limit:
            violations.append(SecurityViolation(
                level=SecurityLevel.LOW,
                field='mem_limit',
                message='No memory limit set - container can consume all available memory'
            ))
        else:
            # Parse memory limit and check if excessive (>16GB)
            mem_bytes = self._parse_memory_string(mem_limit)
            if mem_bytes and mem_bytes > 16 * 1024 * 1024 * 1024:  # 16GB
                violations.append(SecurityViolation(
                    level=SecurityLevel.MEDIUM,
                    field='mem_limit',
                    message=f'Excessive memory limit ({mem_limit}) - review if this is intentional'
                ))

        # Check CPU limit
        if not config.get('cpu_count') and not config.get('cpu_shares') and not config.get('cpus'):
            violations.append(SecurityViolation(
                level=SecurityLevel.LOW,
                field='cpu_limit',
                message='No CPU limit set - container can consume all available CPU'
            ))

        return violations

    def _check_port_conflicts(
        self,
        config: Dict[str, Any],
        host_id: str,
        existing_containers: List[Dict[str, Any]]
    ) -> List[SecurityViolation]:
        """Check for port binding conflicts with existing containers."""
        violations = []

        ports = config.get('ports', {})
        if not ports:
            return violations

        # Build map of used ports from existing containers
        used_ports = set()
        for container in existing_containers:
            container_ports = container.get('ports', {})
            for port_mapping, bindings in container_ports.items():
                if bindings:
                    for binding in bindings:
                        if isinstance(binding, dict) and 'HostPort' in binding:
                            used_ports.add(int(binding['HostPort']))

        # Check if any requested ports conflict
        for container_port, host_port in ports.items():
            if isinstance(host_port, int) and host_port in used_ports:
                violations.append(SecurityViolation(
                    level=SecurityLevel.HIGH,
                    field='ports',
                    message=f'Port {host_port} is already in use by another container on this host'
                ))

        return violations

    def _check_image_security(self, config: Dict[str, Any]) -> List[SecurityViolation]:
        """Check image security (unsigned images, :latest tag)."""
        violations = []

        image = config.get('image', '')
        if not image:
            return violations

        # Check for :latest tag
        if image.endswith(':latest') or ':' not in image:
            violations.append(SecurityViolation(
                level=SecurityLevel.LOW,
                field='image',
                message='Using :latest tag - prefer specific version tags for reproducibility'
            ))

        # Check for image signing/verification (informational)
        # Note: This is a simplified check - real implementation would query registry
        if '/' in image and not image.startswith('docker.io/'):
            # Custom registry - may not be signed
            violations.append(SecurityViolation(
                level=SecurityLevel.INFO,
                field='image',
                message='Custom registry image - verify image signature and provenance'
            ))

        return violations

    def _check_environment_variables(self, config: Dict[str, Any]) -> List[SecurityViolation]:
        """Check for plaintext passwords in environment variables."""
        violations = []

        environment = config.get('environment', {})
        if not environment:
            return violations

        # Pattern to detect password-like environment variables
        password_patterns = [
            r'.*PASSWORD.*',
            r'.*SECRET.*',
            r'.*TOKEN.*',
            r'.*KEY.*',
            r'.*APIKEY.*',
        ]

        for env_var, value in environment.items():
            # Check if this looks like a password variable
            for pattern in password_patterns:
                if re.match(pattern, env_var, re.IGNORECASE):
                    # Check if it's using a file reference (Docker secrets pattern)
                    if isinstance(value, str) and ('_FILE' in env_var or value.startswith('/run/secrets')):
                        # Using secrets file - good practice
                        break

                    # Plaintext password/secret
                    violations.append(SecurityViolation(
                        level=SecurityLevel.MEDIUM,
                        field='environment',
                        message=f"Environment variable '{env_var}' appears to contain plaintext credentials - consider using Docker secrets"
                    ))
                    break  # Only report once per variable

        return violations

    def _parse_memory_string(self, mem_str: str) -> Optional[int]:
        """Parse memory string (e.g., '512m', '2g') to bytes."""
        if not isinstance(mem_str, str):
            return None

        match = re.match(r'^(\d+(?:\.\d+)?)\s*([kmgtKMGT]?)(?:b|B)?$', mem_str.strip())
        if not match:
            return None

        value, unit = match.groups()
        value = float(value)

        multipliers = {
            '': 1,
            'k': 1024,
            'K': 1024,
            'm': 1024 ** 2,
            'M': 1024 ** 2,
            'g': 1024 ** 3,
            'G': 1024 ** 3,
            't': 1024 ** 4,
            'T': 1024 ** 4,
        }

        return int(value * multipliers.get(unit, 1))

    def filter_by_level(
        self,
        violations: List[SecurityViolation],
        level: SecurityLevel,
        include_higher: bool = False
    ) -> List[SecurityViolation]:
        """
        Filter violations by security level.

        Args:
            violations: List of violations to filter
            level: Minimum security level to include
            include_higher: If True, include all violations at or above the level

        Returns:
            Filtered list of violations

        Examples:
            >>> violations = [critical_violation, high_violation, low_violation]
            >>> filtered = validator.filter_by_level(violations, SecurityLevel.HIGH)
            >>> len(filtered)
            1  # Only HIGH violations

            >>> filtered = validator.filter_by_level(violations, SecurityLevel.HIGH, include_higher=True)
            >>> len(filtered)
            2  # HIGH and CRITICAL violations
        """
        if include_higher:
            return [v for v in violations if v.level.value >= level.value]
        else:
            return [v for v in violations if v.level == level]

    def has_blocking_violations(self, violations: List[SecurityViolation]) -> bool:
        """
        Check if violations contain CRITICAL level issues that should block deployment.

        Args:
            violations: List of violations to check

        Returns:
            True if any CRITICAL violations exist, False otherwise

        Examples:
            >>> violations = [SecurityViolation(SecurityLevel.HIGH, 'field', 'msg')]
            >>> validator.has_blocking_violations(violations)
            False

            >>> violations = [SecurityViolation(SecurityLevel.CRITICAL, 'field', 'msg')]
            >>> validator.has_blocking_violations(violations)
            True
        """
        return any(v.level == SecurityLevel.CRITICAL for v in violations)

    def format_violations(self, violations: List[SecurityViolation]) -> str:
        """
        Format violations for human-readable display.

        Args:
            violations: List of violations to format

        Returns:
            Formatted string with all violations grouped by severity

        Examples:
            >>> violations = [
            ...     SecurityViolation(SecurityLevel.CRITICAL, 'privileged', 'Privileged mode'),
            ...     SecurityViolation(SecurityLevel.HIGH, 'network_mode', 'Host network'),
            ... ]
            >>> print(validator.format_violations(violations))
            CRITICAL:
              - [privileged] Privileged mode
            HIGH:
              - [network_mode] Host network
        """
        if not violations:
            return "No security violations found."

        # Group by severity
        by_level = {}
        for violation in violations:
            level_name = violation.level.name
            if level_name not in by_level:
                by_level[level_name] = []
            by_level[level_name].append(violation)

        # Format output
        output = []
        for level in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']:
            if level in by_level:
                output.append(f"{level}:")
                for violation in by_level[level]:
                    output.append(f"  - [{violation.field}] {violation.message}")
                output.append("")  # Blank line between levels

        return "\n".join(output).strip()
