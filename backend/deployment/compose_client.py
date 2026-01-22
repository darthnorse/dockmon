"""
Python client for the Go Compose Service.

Communicates with the Go compose service via Unix socket for stack deployments.
Provides SSE progress streaming for real-time updates.

This client is used for:
- Local hosts (Python backend has direct Docker socket access)
- mTLS remote hosts (Python backend has TLS certificates)

Agent-based hosts continue to use agent_executor.py directly.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Default socket path - matches compose-service default
COMPOSE_SOCKET_PATH = "/tmp/compose.sock"

# Default stacks directory for persistent stack storage
# This allows relative bind mounts (./data) to persist across redeployments
DEFAULT_STACKS_DIR = "/app/data/stacks"


class ComposeServiceError(Exception):
    """Error from Go Compose Service."""

    def __init__(
        self,
        message: str,
        category: str = "internal",
        partial_success: bool = False,
        services: Optional[Dict[str, Any]] = None,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.message = message
        self.category = category
        self.partial_success = partial_success
        self.services = services or {}
        self.retryable = retryable


class ComposeServiceUnavailable(Exception):
    """Go Compose Service is not available."""

    pass


@dataclass
class DeployResult:
    """Result from a compose deployment."""

    deployment_id: str
    success: bool
    partial_success: bool = False
    services: Optional[Dict[str, Any]] = None
    failed_services: Optional[List[str]] = None
    error: Optional[str] = None
    error_category: Optional[str] = None


@dataclass
class ProgressEvent:
    """Progress event during deployment."""

    stage: str
    progress: int
    message: str
    service: Optional[str] = None
    service_idx: Optional[int] = None
    total_services: Optional[int] = None


class ComposeClient:
    """
    Client for the Go Compose Service.

    Communicates via Unix socket for high performance local communication.
    Supports both JSON and SSE response formats.
    """

    def __init__(self, socket_path: str = COMPOSE_SOCKET_PATH):
        """
        Initialize compose client.

        Args:
            socket_path: Path to the Unix socket (default: /tmp/compose.sock)
        """
        self.socket_path = socket_path

    def health_check(self, require_docker: bool = True, timeout: float = 3.0) -> bool:
        """
        Check if compose service is healthy.

        Args:
            require_docker: If True, requires Docker connectivity (default)
            timeout: Timeout in seconds

        Returns:
            True if service is healthy and ready for deployments
        """
        try:
            import socket

            # Quick socket connectivity test
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            try:
                sock.connect(self.socket_path)
            finally:
                sock.close()

            # Full health check via HTTP
            transport = httpx.HTTPTransport(uds=self.socket_path)
            with httpx.Client(transport=transport, timeout=timeout) as client:
                response = client.get("http://localhost/health")
                if response.status_code != 200:
                    return False

                data = response.json()

                if require_docker:
                    return data.get("status") == "ok" and data.get("docker_ok", False)

                return data.get("status") in ("ok", "degraded")

        except Exception as e:
            logger.debug(f"Compose service health check failed: {e}")
            return False

    async def deploy(
        self,
        deployment_id: str,
        project_name: str,
        compose_yaml: str,
        action: str = "up",
        env_file_content: Optional[str] = None,
        profiles: Optional[List[str]] = None,
        remove_volumes: bool = False,
        force_recreate: bool = False,
        pull_images: bool = False,
        wait_for_healthy: bool = False,
        health_timeout: int = 60,
        timeout: int = 1800,
        docker_host: Optional[str] = None,
        tls_ca_cert: Optional[str] = None,
        tls_cert: Optional[str] = None,
        tls_key: Optional[str] = None,
        registry_credentials: Optional[List[Dict[str, str]]] = None,
        stacks_dir: Optional[str] = None,
    ) -> DeployResult:
        """
        Deploy a compose stack (JSON response, no streaming).

        Args:
            deployment_id: Unique deployment ID
            project_name: Docker Compose project name
            compose_yaml: Docker Compose YAML content
            action: "up", "down", or "restart"
            env_file_content: Raw .env file content (written to temp dir for env_file: .env)
            profiles: Compose profiles to activate
            remove_volumes: Remove volumes on "down" action
            force_recreate: Force recreate containers even if unchanged
            pull_images: Pull images before starting (for redeploy)
            wait_for_healthy: Wait for health checks to pass
            health_timeout: Health check timeout in seconds
            timeout: Operation timeout in seconds
            docker_host: Remote Docker host (empty for local)
            tls_ca_cert: TLS CA certificate PEM
            tls_cert: TLS client certificate PEM
            tls_key: TLS client key PEM
            registry_credentials: List of registry credentials
            stacks_dir: Persistent stacks directory (uses STACKS_DIR env or default)

        Returns:
            DeployResult with deployment outcome
        """
        request = self._build_request(
            deployment_id=deployment_id,
            project_name=project_name,
            compose_yaml=compose_yaml,
            action=action,
            env_file_content=env_file_content,
            profiles=profiles,
            remove_volumes=remove_volumes,
            force_recreate=force_recreate,
            pull_images=pull_images,
            wait_for_healthy=wait_for_healthy,
            health_timeout=health_timeout,
            timeout=timeout,
            stacks_dir=stacks_dir,
            docker_host=docker_host,
            tls_ca_cert=tls_ca_cert,
            tls_cert=tls_cert,
            tls_key=tls_key,
            registry_credentials=registry_credentials,
        )

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
                    "http://localhost/deploy",
                    json=request,
                )

                if response.status_code != 200:
                    raise ComposeServiceError(
                        f"Compose service error: HTTP {response.status_code}"
                    )

                data = response.json()
                return self._parse_result(data)

        except httpx.ConnectError:
            raise ComposeServiceUnavailable(
                f"Cannot connect to compose service at {self.socket_path}"
            )

    async def deploy_with_progress(
        self,
        deployment_id: str,
        project_name: str,
        compose_yaml: str,
        progress_callback: Callable[[ProgressEvent], Awaitable[None]],
        action: str = "up",
        env_file_content: Optional[str] = None,
        profiles: Optional[List[str]] = None,
        remove_volumes: bool = False,
        force_recreate: bool = False,
        pull_images: bool = False,
        wait_for_healthy: bool = False,
        health_timeout: int = 60,
        timeout: int = 1800,
        docker_host: Optional[str] = None,
        tls_ca_cert: Optional[str] = None,
        tls_cert: Optional[str] = None,
        tls_key: Optional[str] = None,
        registry_credentials: Optional[List[Dict[str, str]]] = None,
        stacks_dir: Optional[str] = None,
    ) -> DeployResult:
        """
        Deploy with SSE progress streaming.

        Same as deploy() but with real-time progress updates via callback.

        Args:
            progress_callback: Async callback for progress events
            ... (same as deploy())

        Returns:
            DeployResult with deployment outcome
        """
        request = self._build_request(
            deployment_id=deployment_id,
            project_name=project_name,
            compose_yaml=compose_yaml,
            action=action,
            env_file_content=env_file_content,
            profiles=profiles,
            remove_volumes=remove_volumes,
            force_recreate=force_recreate,
            pull_images=pull_images,
            wait_for_healthy=wait_for_healthy,
            health_timeout=health_timeout,
            timeout=timeout,
            stacks_dir=stacks_dir,
            docker_host=docker_host,
            tls_ca_cert=tls_ca_cert,
            tls_cert=tls_cert,
            tls_key=tls_key,
            registry_credentials=registry_credentials,
        )

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
                        logger.debug(f"Opening SSE stream for deployment {deployment_id}")
                        async with client.stream(
                            "POST",
                            "http://localhost/deploy",
                            json=request,
                            headers={"Accept": "text/event-stream"},
                        ) as response:
                            logger.debug(f"SSE stream opened, status={response.status_code}")
                            event_type = None

                            async for line in response.aiter_lines():
                                line = line.strip()

                                if line.startswith("event:"):
                                    event_type = line.split(":", 1)[1].strip()
                                    logger.debug(f"SSE event type: {event_type}")
                                elif line.startswith("data:"):
                                    data_str = line.split(":", 1)[1].strip()
                                    try:
                                        data = json.loads(data_str)
                                    except json.JSONDecodeError as e:
                                        logger.error(f"SSE JSON parse error: {e}, data: {data_str[:200]}")
                                        continue

                                    if event_type == "progress":
                                        event = ProgressEvent(
                                            stage=data.get("stage", ""),
                                            progress=data.get("progress", 0),
                                            message=data.get("message", ""),
                                            service=data.get("service"),
                                            service_idx=data.get("service_idx"),
                                            total_services=data.get("total_services"),
                                        )
                                        await progress_callback(event)
                                    elif event_type == "complete":
                                        logger.debug(f"SSE complete event received for {deployment_id}")
                                        return self._parse_result(data)
                                elif line.startswith(":"):
                                    # Keepalive comment, ignore
                                    pass

                            logger.warning(f"SSE stream ended without complete event for {deployment_id}")

                except asyncio.TimeoutError:
                    raise ComposeServiceError(
                        f"Deployment timed out after {http_timeout} seconds",
                        category="timeout",
                        retryable=True,
                    )

            raise ComposeServiceError("SSE stream ended without completion event")

        except httpx.ConnectError:
            raise ComposeServiceUnavailable(
                f"Cannot connect to compose service at {self.socket_path}"
            )

    def _build_request(
        self,
        deployment_id: str,
        project_name: str,
        compose_yaml: str,
        action: str,
        env_file_content: Optional[str],
        profiles: Optional[List[str]],
        remove_volumes: bool,
        force_recreate: bool,
        pull_images: bool,
        wait_for_healthy: bool,
        health_timeout: int,
        timeout: int,
        stacks_dir: Optional[str],
        docker_host: Optional[str],
        tls_ca_cert: Optional[str],
        tls_cert: Optional[str],
        tls_key: Optional[str],
        registry_credentials: Optional[List[Dict[str, str]]],
    ) -> Dict[str, Any]:
        """Build request payload for compose service."""
        effective_stacks_dir = stacks_dir or os.getenv("STACKS_DIR") or DEFAULT_STACKS_DIR

        request: Dict[str, Any] = {
            "deployment_id": deployment_id,
            "project_name": project_name,
            "compose_yaml": compose_yaml,
            "action": action,
            "env_file_content": env_file_content or "",
            "profiles": profiles or [],
            "remove_volumes": remove_volumes,
            "force_recreate": force_recreate,
            "pull_images": pull_images,
            "wait_for_healthy": wait_for_healthy,
            "health_timeout": health_timeout,
            "timeout": timeout,
            "stacks_dir": effective_stacks_dir,
        }

        if docker_host:
            request["docker_host"] = docker_host
            if tls_ca_cert:
                request["tls_ca_cert"] = tls_ca_cert
            if tls_cert:
                request["tls_cert"] = tls_cert
            if tls_key:
                request["tls_key"] = tls_key

        if registry_credentials:
            request["registry_credentials"] = registry_credentials

        return request

    def _parse_result(self, data: Dict[str, Any]) -> DeployResult:
        """Parse JSON response into DeployResult."""
        error_msg = None
        error_category = None

        if data.get("error"):
            error = data["error"]
            if isinstance(error, dict):
                error_msg = error.get("message", str(error))
                error_category = error.get("category")
            else:
                error_msg = str(error)

        return DeployResult(
            deployment_id=data.get("deployment_id", ""),
            success=data.get("success", False),
            partial_success=data.get("partial_success", False),
            services=data.get("services"),
            failed_services=data.get("failed_services"),
            error=error_msg,
            error_category=error_category,
        )


# Singleton instance for convenience
_client: Optional[ComposeClient] = None


def get_compose_client() -> ComposeClient:
    """Get singleton compose client instance."""
    global _client
    if _client is None:
        _client = ComposeClient()
    return _client


def is_compose_service_available() -> bool:
    """Check if the Go compose service is available."""
    return get_compose_client().health_check(require_docker=True)
