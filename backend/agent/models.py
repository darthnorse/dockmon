"""
Pydantic validation models for agent registration and communication.

These models provide:
- Input validation (type checking, range validation)
- XSS protection (HTML tag sanitization)
- DoS protection (length limits)
- Clear error messages for invalid data
"""
import re
from typing import Optional, Dict
from pydantic import BaseModel, Field, field_validator, ConfigDict


class AgentRegistrationRequest(BaseModel):
    """
    Validated agent registration request.

    Enforces strict validation to prevent:
    - XSS attacks via hostname/version fields
    - Type confusion (e.g., strings for integer fields)
    - DoS via oversized payloads
    - Invalid data ranges (negative memory, etc.)
    """
    # Message type (always "register" for registration)
    type: str = Field(pattern="^register$", description="Message type (must be 'register')")

    # Required authentication fields
    token: str = Field(max_length=255, description="Registration or permanent token")
    engine_id: str = Field(max_length=255, description="Docker engine ID")

    # Agent metadata
    version: str = Field(max_length=50, description="Agent version")
    proto_version: str = Field(max_length=20, description="Protocol version")
    capabilities: Dict[str, bool] = Field(description="Agent capabilities")

    # Optional host identification
    hostname: Optional[str] = Field(None, max_length=255, description="System hostname")

    # System information fields (collected from Docker daemon)
    os_type: Optional[str] = Field(None, max_length=50, description="OS type (linux, windows, etc.)")
    os_version: Optional[str] = Field(None, max_length=500, description="OS version string")
    kernel_version: Optional[str] = Field(None, max_length=255, description="Kernel version")
    docker_version: Optional[str] = Field(None, max_length=50, description="Docker version")
    daemon_started_at: Optional[str] = Field(None, max_length=100, description="Docker daemon start time")
    total_memory: Optional[int] = Field(None, gt=0, le=1000000000000000, description="Total memory in bytes (max 1PB)")
    num_cpus: Optional[int] = Field(None, gt=0, le=10000, description="Number of CPUs (max 10k)")

    # Agent platform fields (for self-update binary selection)
    agent_os: Optional[str] = Field(None, max_length=20, description="Agent OS (GOOS: linux, darwin, windows)")
    agent_arch: Optional[str] = Field(None, max_length=20, description="Agent architecture (GOARCH: amd64, arm64, arm)")

    # Host network info (systemd agents only - container agents would report Docker network IPs)
    host_ip: Optional[str] = Field(None, max_length=45, description="Host IP address (IPv4 or IPv6)")

    @field_validator('hostname', 'os_version', 'kernel_version', 'docker_version', 'os_type', 'agent_os', 'agent_arch', 'host_ip')
    @classmethod
    def sanitize_html(cls, v: Optional[str]) -> Optional[str]:
        """
        Sanitize string fields to prevent XSS attacks.

        Removes:
        - HTML tags (< >)
        - Non-printable characters (except newlines, tabs)

        This prevents malicious agents from injecting:
        - <script>alert('xss')</script>
        - <img src=x onerror=alert(1)>
        - etc.
        """
        if v:
            # Remove < > to prevent HTML/script injection
            v = re.sub(r'[<>]', '', v)
            # Keep only printable characters plus common whitespace
            v = ''.join(c for c in v if c.isprintable() or c in '\n\r\t')
            # Strip leading/trailing whitespace
            v = v.strip()
        return v

    @field_validator('daemon_started_at')
    @classmethod
    def validate_timestamp(cls, v: Optional[str]) -> Optional[str]:
        """
        Validate timestamp format (ISO 8601).

        Accepts formats like:
        - 2025-10-30T11:55:52.337598034-06:00
        - 2025-10-30T11:55:52Z
        """
        if v:
            # Remove any HTML characters
            v = re.sub(r'[<>]', '', v)
            # Basic timestamp format validation (flexible for various ISO formats)
            # We don't strictly parse it since it's just stored as a string
            if len(v) > 100:
                v = v[:100]  # Truncate oversized timestamps
        return v

    @field_validator('engine_id', 'token')
    @classmethod
    def validate_ids(cls, v: str) -> str:
        """
        Validate ID fields (engine_id, token).

        These should be alphanumeric + hyphens (UUIDs, SHA256 hashes).
        """
        # Allow alphanumeric, hyphens, underscores, colons (common in IDs)
        # Colons are needed for legacy Docker Engine ID format (EOGD:IMML:ZAXF:...)
        # This prevents injection of special characters
        if not re.match(r'^[a-zA-Z0-9\-_:]+$', v):
            raise ValueError("ID must contain only alphanumeric characters, hyphens, underscores, and colons")
        return v

    model_config = ConfigDict(
        extra='forbid',           # Don't allow extra fields not defined in the model
        validate_assignment=True  # Validate on assignment (not just initialization)
    )
