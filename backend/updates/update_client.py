"""
Python client for the Go Update Service.

Communicates with the Go compose service via Unix socket for container updates.
Provides SSE progress streaming for real-time updates.

This client is used for:
- Local hosts (Python backend has direct Docker socket access)
- mTLS remote hosts (Python backend has TLS certificates)

Agent-based hosts continue to use agent_executor.py directly.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Default socket path - matches compose-service default
UPDATE_SOCKET_PATH = "/tmp/compose.sock"


class UpdateServiceError(Exception):
    """Error from Go Update Service."""

    def __init__(
        self,
        message: str,
        rolled_back: bool = False,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.message = message
        self.rolled_back = rolled_back
        self.retryable = retryable


class UpdateServiceUnavailable(Exception):
    """Go Update Service is not available."""

    pass


@dataclass
class UpdateResult:
    """Result from a container update."""

    success: bool
    old_container_id: str
    new_container_id: str = ""
    container_name: str = ""
    rolled_back: bool = False
    failed_dependents: Optional[List[str]] = None
    error: Optional[str] = None


@dataclass
class ProgressEvent:
    """Progress event during update."""

    stage: str
    message: str
    progress: int = 0


@dataclass
class PullProgressEvent:
    """Pull progress event during image pull."""

    container_id: str
    overall_progress: int
    total_layers: int
    summary: str
    speed_mbps: float = 0.0
    layers: Optional[List[Dict[str, Any]]] = None


@dataclass
class RegistryAuth:
    """Registry authentication credentials."""

    username: str
    password: str


class UpdateClient:
    """
    Client for the Go Update Service.

    Communicates via Unix socket for high performance local communication.
    Supports both JSON and SSE response formats.
    """

    def __init__(self, socket_path: str = UPDATE_SOCKET_PATH):
        """
        Initialize update client.

        Args:
            socket_path: Path to the Unix socket (default: /tmp/compose.sock)
        """
        self.socket_path = socket_path

    async def update_container(
        self,
        container_id: str,
        new_image: str,
        stop_timeout: int = 30,
        health_timeout: int = 120,
        timeout: int = 1800,
        docker_host: Optional[str] = None,
        tls_ca_cert: Optional[str] = None,
        tls_cert: Optional[str] = None,
        tls_key: Optional[str] = None,
        registry_auth: Optional[RegistryAuth] = None,
    ) -> UpdateResult:
        """
        Update a container (JSON response, no streaming).

        Args:
            container_id: Container ID to update
            new_image: New image to update to
            stop_timeout: Timeout for stopping container in seconds
            health_timeout: Timeout for health check in seconds
            timeout: Operation timeout in seconds
            docker_host: Remote Docker host (empty for local)
            tls_ca_cert: TLS CA certificate PEM
            tls_cert: TLS client certificate PEM
            tls_key: TLS client key PEM
            registry_auth: Registry authentication for private registries

        Returns:
            UpdateResult with update outcome
        """
        request = {
            "container_id": container_id,
            "new_image": new_image,
            "stop_timeout": stop_timeout,
            "health_timeout": health_timeout,
            "timeout": timeout,
        }

        # Add remote connection info if provided
        if docker_host:
            request["docker_host"] = docker_host
            if tls_ca_cert:
                request["tls_ca_cert"] = tls_ca_cert
            if tls_cert:
                request["tls_cert"] = tls_cert
            if tls_key:
                request["tls_key"] = tls_key

        # Add registry auth if provided
        if registry_auth:
            request["registry_auth"] = {
                "username": registry_auth.username,
                "password": registry_auth.password,
            }

        # HTTP timeout = operation timeout + 60s buffer
        http_timeout = timeout + 60

        try:
            transport = httpx.AsyncHTTPTransport(uds=self.socket_path)
            async with httpx.AsyncClient(
                transport=transport,
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=float(http_timeout),
                    write=10.0,
                    pool=10.0,
                ),
            ) as client:
                response = await client.post(
                    "http://localhost/update",
                    json=request,
                )

                if response.status_code != 200:
                    raise UpdateServiceError(
                        f"Update service error: HTTP {response.status_code}"
                    )

                data = response.json()
                return self._parse_result(data)

        except httpx.ConnectError:
            raise UpdateServiceUnavailable(
                f"Cannot connect to update service at {self.socket_path}"
            )

    async def update_with_progress(
        self,
        container_id: str,
        new_image: str,
        progress_callback: Callable[[ProgressEvent], Awaitable[None]],
        pull_progress_callback: Optional[Callable[[PullProgressEvent], Awaitable[None]]] = None,
        stop_timeout: int = 30,
        health_timeout: int = 120,
        timeout: int = 1800,
        docker_host: Optional[str] = None,
        tls_ca_cert: Optional[str] = None,
        tls_cert: Optional[str] = None,
        tls_key: Optional[str] = None,
        registry_auth: Optional[RegistryAuth] = None,
    ) -> UpdateResult:
        """
        Update with SSE progress streaming.

        Same as update_container() but with real-time progress updates via callback.

        Args:
            progress_callback: Async callback for progress events
            pull_progress_callback: Optional async callback for pull layer progress
            ... (same as update_container())

        Returns:
            UpdateResult with update outcome
        """
        request = {
            "container_id": container_id,
            "new_image": new_image,
            "stop_timeout": stop_timeout,
            "health_timeout": health_timeout,
            "timeout": timeout,
        }

        # Add remote connection info if provided
        if docker_host:
            request["docker_host"] = docker_host
            if tls_ca_cert:
                request["tls_ca_cert"] = tls_ca_cert
            if tls_cert:
                request["tls_cert"] = tls_cert
            if tls_key:
                request["tls_key"] = tls_key

        # Add registry auth if provided
        if registry_auth:
            request["registry_auth"] = {
                "username": registry_auth.username,
                "password": registry_auth.password,
            }

        # HTTP timeout = operation timeout + 60s buffer
        http_timeout = timeout + 60

        try:
            transport = httpx.AsyncHTTPTransport(uds=self.socket_path)
            async with httpx.AsyncClient(
                transport=transport,
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=30.0,  # Per-read timeout (keepalives prevent firing)
                    write=10.0,
                    pool=10.0,
                ),
            ) as client:
                try:
                    async with asyncio.timeout(http_timeout):
                        async with client.stream(
                            "POST",
                            "http://localhost/update",
                            json=request,
                            headers={"Accept": "text/event-stream"},
                        ) as response:
                            event_type = None

                            async for line in response.aiter_lines():
                                line = line.strip()

                                if line.startswith("event:"):
                                    event_type = line.split(":", 1)[1].strip()
                                elif line.startswith("data:"):
                                    data_str = line.split(":", 1)[1].strip()
                                    data = json.loads(data_str)

                                    if event_type == "progress":
                                        event = ProgressEvent(
                                            stage=data.get("stage", ""),
                                            message=data.get("message", ""),
                                            progress=data.get("progress", 0),
                                        )
                                        await progress_callback(event)
                                    elif event_type == "pull_progress":
                                        if pull_progress_callback:
                                            event = PullProgressEvent(
                                                container_id=data.get("container_id", ""),
                                                overall_progress=data.get("overall_progress", 0),
                                                total_layers=data.get("total_layers", 0),
                                                summary=data.get("summary", ""),
                                                speed_mbps=data.get("speed_mbps", 0.0),
                                                layers=data.get("layers"),
                                            )
                                            await pull_progress_callback(event)
                                    elif event_type == "complete":
                                        return self._parse_result(data)
                                elif line.startswith(":"):
                                    # Keepalive comment, ignore
                                    pass

                except asyncio.TimeoutError:
                    raise UpdateServiceError(
                        f"Update timed out after {http_timeout} seconds",
                        retryable=True,
                    )

            raise UpdateServiceError("SSE stream ended without completion event")

        except httpx.ConnectError:
            raise UpdateServiceUnavailable(
                f"Cannot connect to update service at {self.socket_path}"
            )

    def _parse_result(self, data: Dict[str, Any]) -> UpdateResult:
        """Parse JSON response into UpdateResult."""
        return UpdateResult(
            success=data.get("success", False),
            old_container_id=data.get("old_container_id", ""),
            new_container_id=data.get("new_container_id", ""),
            container_name=data.get("container_name", ""),
            rolled_back=data.get("rolled_back", False),
            failed_dependents=data.get("failed_dependents"),
            error=data.get("error"),
        )


# Singleton instance for convenience
_client: Optional[UpdateClient] = None


def get_update_client() -> UpdateClient:
    """Get singleton update client instance."""
    global _client
    if _client is None:
        _client = UpdateClient()
    return _client


def is_update_service_available() -> bool:
    """Check if the Go update service is available."""
    try:
        import socket

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        try:
            sock.connect(UPDATE_SOCKET_PATH)
            return True
        finally:
            sock.close()
    except Exception:
        return False
