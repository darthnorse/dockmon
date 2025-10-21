"""
Docker Models for DockMon
Pydantic models for Docker hosts, containers, and configurations
"""

import re
import uuid
import logging
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, validator, model_validator


logger = logging.getLogger(__name__)


def derive_container_tags(labels: dict[str, str]) -> list[str]:
    """
    Derive tags from Docker container labels

    Extracts tags from:
    - com.docker.compose.project → compose:{project}
    - com.docker.swarm.service.name → swarm:{service}
    - dockmon.tag → custom tags (comma-separated)

    Args:
        labels: Dictionary of Docker labels

    Returns:
        List of derived tags (lowercase, trimmed)

    Example:
        >>> derive_container_tags({'com.docker.compose.project': 'frontend'})
        ['compose:frontend']
    """
    tags = []

    # Compose project tag
    if 'com.docker.compose.project' in labels:
        project = labels['com.docker.compose.project'].strip()
        if project:
            tags.append(f"compose:{project}")

    # Swarm service tag
    if 'com.docker.swarm.service.name' in labels:
        service = labels['com.docker.swarm.service.name'].strip()
        if service:
            tags.append(f"swarm:{service}")

    # Custom DockMon tags (comma-separated)
    if 'dockmon.tag' in labels:
        custom_tags = labels['dockmon.tag'].split(',')
        for tag in custom_tags:
            tag = tag.strip()
            if tag:
                tags.append(tag)

    # Normalize: lowercase, remove empty
    tags = [t.lower() for t in tags if t.strip()]

    # Remove duplicates while preserving order
    seen = set()
    unique_tags = []
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            unique_tags.append(tag)

    return unique_tags


class DockerHostConfig(BaseModel):
    """Configuration for a Docker host"""
    name: str = Field(..., min_length=1, max_length=100, pattern=r'^[a-zA-Z0-9][a-zA-Z0-9 ._-]*$')
    url: str = Field(..., min_length=1, max_length=500)
    tls_cert: Optional[str] = Field(None, max_length=10000)
    tls_key: Optional[str] = Field(None, max_length=10000)
    tls_ca: Optional[str] = Field(None, max_length=10000)
    # Phase 3d - Host organization
    tags: Optional[list[str]] = Field(None, max_items=50)  # Max 50 tags per host
    description: Optional[str] = Field(None, max_length=1000)  # Optional description

    @validator('name')
    def validate_name(cls, v):
        """Validate host name for security"""
        if not v or not v.strip():
            raise ValueError('Host name cannot be empty')
        # Prevent XSS and injection
        sanitized = re.sub(r'[<>"\']', '', v.strip())
        if len(sanitized) != len(v.strip()):
            raise ValueError('Host name contains invalid characters')
        return sanitized

    @validator('url')
    def validate_url(cls, v):
        """Validate Docker URL for security - prevent SSRF attacks"""
        if not v or not v.strip():
            raise ValueError('URL cannot be empty')

        v = v.strip()

        # Only allow specific protocols
        allowed_protocols = ['tcp://', 'unix://', 'http://', 'https://']
        if not any(v.startswith(proto) for proto in allowed_protocols):
            raise ValueError('URL must use tcp://, unix://, http:// or https:// protocol')

        # Block ONLY the most dangerous SSRF targets (cloud metadata & loopback)
        # Allow private networks (10.*, 172.16-31.*, 192.168.*) for legitimate Docker hosts
        extremely_dangerous_patterns = [
            r'169\.254\.169\.254',                     # AWS/GCP metadata (specific)
            r'169\.254\.',                             # Link-local range (broader)
            r'metadata\.google\.internal',             # GCP metadata
            r'metadata\.goog',                         # GCP metadata alternative
            r'100\.100\.100\.200',                     # Alibaba Cloud metadata
            r'fd00:ec2::254',                          # AWS IPv6 metadata
            r'0\.0\.0\.0',                             # All interfaces binding
            r'::1',                                    # IPv6 localhost
            r'localhost(?!\:|$)',                      # Localhost variations but allow localhost:port
            r'127\.0\.0\.(?!1$)',                      # 127.x.x.x but allow 127.0.0.1
        ]

        # Check for extremely dangerous metadata service targets
        for pattern in extremely_dangerous_patterns:
            if re.search(pattern, v, re.IGNORECASE):
                # Special handling for localhost - allow localhost:port but block bare localhost
                if 'localhost' in pattern.lower() and ':' in v:
                    continue  # Allow localhost:2376 etc
                raise ValueError('URL targets cloud metadata service or dangerous internal endpoint')

        # Additional validation: warn about but allow private networks
        private_network_patterns = [
            r'10\.',                                   # 10.0.0.0/8
            r'172\.(1[6-9]|2[0-9]|3[01])\.',          # 172.16.0.0/12
            r'192\.168\.',                            # 192.168.0.0/16
        ]

        # Log private network usage for monitoring (but don't block)
        for pattern in private_network_patterns:
            if re.search(pattern, v, re.IGNORECASE):
                logger.info(f"Docker host configured on private network: {v[:50]}...")
                break

        return v

    @validator('tls_cert', 'tls_key', 'tls_ca')
    def validate_certificate(cls, v):
        """Validate TLS certificate data"""
        if v is None:
            return v

        v = v.strip()
        if not v:
            return None

        # Basic PEM format validation with helpful error messages
        if '-----BEGIN' not in v and '-----END' not in v:
            raise ValueError('Certificate is incomplete. PEM certificates must start with "-----BEGIN" and end with "-----END". Please copy the entire certificate including both lines.')
        elif '-----BEGIN' not in v:
            raise ValueError('Certificate is missing the "-----BEGIN" header line. Make sure you copied the complete certificate starting from the "-----BEGIN" line.')
        elif '-----END' not in v:
            raise ValueError('Certificate is missing the "-----END" footer line. Make sure you copied the complete certificate including the "-----END" line.')

        # Block potential code injection
        dangerous_patterns = ['<script', 'javascript:', 'data:', 'vbscript:', '<?php', '<%', '{{', '{%']
        v_lower = v.lower()
        if any(pattern in v_lower for pattern in dangerous_patterns):
            raise ValueError('Certificate contains potentially dangerous content')

        return v

    @model_validator(mode='after')
    def validate_tls_complete(self):
        """Ensure TLS configuration is complete when using TCP with certificates"""
        # Only validate for TCP connections
        if not self.url or not self.url.startswith('tcp://'):
            return self

        # If any TLS field is provided, all three must be provided
        tls_fields_provided = [
            ('Client Certificate', self.tls_cert),
            ('Client Private Key', self.tls_key),
            ('CA Certificate', self.tls_ca)
        ]

        provided_fields = [(name, val) for name, val in tls_fields_provided if val and val.strip()]

        if provided_fields and len(provided_fields) < 3:
            # Some but not all fields provided
            missing = [name for name, val in tls_fields_provided if not val or not val.strip()]
            missing_str = ', '.join(missing)
            raise ValueError(
                f'Incomplete TLS configuration. For secure TCP connections, you must provide all three certificates. '
                f'Missing: {missing_str}. Either provide all three certificates or remove all of them.'
            )

        return self


class DockerHost(BaseModel):
    """Docker host with connection status"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    url: str
    status: str = "offline"
    security_status: Optional[str] = None  # "secure", "insecure", "unknown"
    last_checked: datetime = Field(default_factory=datetime.now)
    container_count: int = 0
    error: Optional[str] = None
    # Phase 3d - Host organization
    tags: Optional[list[str]] = None  # User-defined tags for filtering/grouping
    description: Optional[str] = None  # Optional notes about the host
    # Phase 5 - System information
    os_type: Optional[str] = None  # "linux", "windows", etc.
    os_version: Optional[str] = None  # e.g., "Ubuntu 22.04.3 LTS"
    kernel_version: Optional[str] = None  # e.g., "5.15.0-88-generic"
    docker_version: Optional[str] = None  # e.g., "24.0.6"
    daemon_started_at: Optional[str] = None  # ISO timestamp when Docker daemon started (from bridge network)
    # System resources
    total_memory: Optional[int] = None  # Total memory in bytes
    num_cpus: Optional[int] = None  # Number of CPUs


class Container(BaseModel):
    """Container information"""
    id: str
    short_id: str
    name: str
    state: str
    status: str
    host_id: str
    host_name: str
    image: str
    created: str
    auto_restart: bool = False
    restart_attempts: int = 0
    desired_state: Optional[str] = 'unspecified'  # 'should_run', 'on_demand', or 'unspecified'
    web_ui_url: Optional[str] = None  # URL to container's web interface
    # Docker configuration
    ports: Optional[list[str]] = None  # e.g., ["8080:80/tcp", "443:443/tcp"]
    restart_policy: Optional[str] = None  # e.g., "always", "unless-stopped", "no"
    volumes: Optional[list[str]] = None  # e.g., ["/var/www:/usr/share/nginx/html"]
    env: Optional[dict[str, str]] = None  # Environment variables
    ip_address: Optional[str] = None  # Container IP address from NetworkSettings
    # Stats from Go stats service
    cpu_percent: Optional[float] = None
    memory_usage: Optional[int] = None
    memory_limit: Optional[int] = None
    memory_percent: Optional[float] = None
    network_rx: Optional[int] = None
    network_tx: Optional[int] = None
    net_bytes_per_sec: Optional[float] = None
    disk_read: Optional[int] = None
    disk_write: Optional[int] = None
    # Labels from Docker (Phase 3d)
    labels: Optional[dict[str, str]] = None
    # Derived tags (Phase 3d - computed from labels)
    tags: Optional[list[str]] = None