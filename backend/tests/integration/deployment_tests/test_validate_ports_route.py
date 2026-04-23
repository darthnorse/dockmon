"""
Integration tests for POST /api/stacks/{name}/validate-ports.

Covers: conflict detection, self-exclusion on redeploy, 404/400/409 paths,
and graceful degradation when the host is unreachable.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def valid_compose_yaml():
    return """
services:
  web:
    image: nginx
    ports:
      - "8080:80"
"""


@pytest.fixture
def stack_exists(monkeypatch, valid_compose_yaml):
    """Make stack_storage report the stack exists and return valid compose."""
    from deployment import stack_storage
    monkeypatch.setattr(
        stack_storage, "stack_exists",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        stack_storage, "read_stack",
        AsyncMock(return_value=(valid_compose_yaml, "")),
    )


@pytest.fixture
def authed_client(client, monkeypatch):
    """
    Authed FastAPI TestClient that also bypasses require_capability.

    Builds on the shared `client` fixture (which overrides get_current_user
    from auth.v2_routes). Adds:
    - Override of get_current_user_or_api_key from auth.api_key_auth so that
      require_capability() has a user to pass into check_auth_capability.
    - Monkeypatch of check_auth_capability to always return True.
    """
    import main
    from auth.api_key_auth import get_current_user_or_api_key

    async def _mock_current_user_or_api_key():
        return {
            "username": "test_user",
            "user_id": 1,
            "auth_type": "session",
        }

    main.app.dependency_overrides[get_current_user_or_api_key] = _mock_current_user_or_api_key
    monkeypatch.setattr("auth.api_key_auth.check_auth_capability", lambda user, cap: True)

    yield client


@pytest.fixture
def override_monitor(monkeypatch):
    """
    Replace the monitor used by stack_routes with a MagicMock.

    The route calls `get_docker_monitor()` (exported from deployment.routes)
    to fetch the monitor. We swap that module-level reference to a freshly
    configured MagicMock whose `get_containers` attribute the individual
    tests can then rewire per-test.
    """
    from deployment import routes as deployment_routes

    mock_monitor = MagicMock()
    mock_monitor.get_containers = AsyncMock(return_value=[])

    # deployment.routes owns the singleton; stack_routes imports
    # get_docker_monitor from deployment.routes and calls it at request time,
    # so patching the module-level _docker_monitor in deployment.routes is enough.
    monkeypatch.setattr(deployment_routes, "_docker_monitor", mock_monitor)

    return mock_monitor


def _fake_container(id, name, ports, labels=None):
    """Build a duck-typed container with the attributes find_port_conflicts reads."""
    c = MagicMock()
    c.id = id
    c.name = name
    c.ports = ports
    c.labels = labels or {}
    return c


@pytest.mark.integration
class TestValidatePortsRoute:
    def test_conflict_returned(self, authed_client, stack_exists, override_monitor):
        override_monitor.get_containers = AsyncMock(return_value=[
            _fake_container("aaaaaaaaaaaa", "nginx-proxy", ["8080:80/tcp"]),
        ])

        response = authed_client.post(
            "/api/stacks/foo/validate-ports",
            json={"host_id": "host-A"},
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert len(payload["conflicts"]) == 1
        conflict = payload["conflicts"][0]
        assert conflict["port"] == 8080
        assert conflict["protocol"] == "tcp"
        assert conflict["container_name"] == "nginx-proxy"
        assert conflict["container_id"] == "aaaaaaaaaaaa"

    def test_no_conflicts(self, authed_client, stack_exists, override_monitor):
        override_monitor.get_containers = AsyncMock(return_value=[])

        response = authed_client.post(
            "/api/stacks/foo/validate-ports",
            json={"host_id": "host-A"},
        )

        assert response.status_code == 200
        assert response.json() == {"conflicts": []}

    def test_redeploy_self_exclusion(self, authed_client, stack_exists, override_monitor):
        override_monitor.get_containers = AsyncMock(return_value=[
            _fake_container(
                "aaaaaaaaaaaa", "foo-web", ["8080:80/tcp"],
                labels={"com.docker.compose.project": "foo"},
            ),
        ])

        response = authed_client.post(
            "/api/stacks/foo/validate-ports",
            json={"host_id": "host-A"},
        )

        assert response.status_code == 200
        assert response.json() == {"conflicts": []}

    def test_stack_not_found(self, authed_client, monkeypatch, override_monitor):
        from deployment import stack_storage
        monkeypatch.setattr(
            stack_storage, "stack_exists",
            AsyncMock(return_value=False),
        )

        response = authed_client.post(
            "/api/stacks/does-not-exist/validate-ports",
            json={"host_id": "host-A"},
        )

        assert response.status_code == 404

    def test_host_unavailable(self, authed_client, stack_exists, override_monitor):
        # get_containers raises — e.g., host offline
        override_monitor.get_containers = AsyncMock(
            side_effect=RuntimeError("host offline")
        )

        response = authed_client.post(
            "/api/stacks/foo/validate-ports",
            json={"host_id": "host-offline"},
        )

        assert response.status_code == 409

    def test_malformed_compose(self, authed_client, monkeypatch, override_monitor):
        from deployment import stack_storage
        monkeypatch.setattr(
            stack_storage, "stack_exists",
            AsyncMock(return_value=True),
        )
        # Return compose that's structurally valid YAML but raises ValueError
        # from extract_ports_from_compose (services as a list).
        # Actually: services-as-list now returns [] gracefully (handled in Task 1
        # fix commit bc70d0f), so we need a TRULY malformed YAML here.
        monkeypatch.setattr(
            stack_storage, "read_stack",
            AsyncMock(return_value=("services:\n  web:\n    image: [unclosed", "")),
        )

        response = authed_client.post(
            "/api/stacks/foo/validate-ports",
            json={"host_id": "host-A"},
        )

        assert response.status_code == 400
