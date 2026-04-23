"""
Integration tests for POST /api/stacks/{name}/validate-ports.

Covers: conflict detection, self-exclusion on redeploy, 404/400/409 paths,
and graceful degradation when the host is unreachable.
"""

from dataclasses import dataclass
from typing import Optional

import pytest
from unittest.mock import AsyncMock, MagicMock


@dataclass(frozen=True)
class _FakeContainer:
    """Matches the fields validate-ports reads from the monitor cache."""
    id: str
    name: str
    host_id: str
    ports: Optional[list[str]]
    labels: Optional[dict[str, str]]


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
    """Make stack_storage.read_stack return valid compose."""
    from deployment import stack_storage
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

    The route reads `monitor.hosts[host_id].status` and
    `monitor.get_last_containers()`. By default the mock host is online
    with an empty cache; individual tests override per-test.
    """
    from deployment import routes as deployment_routes

    mock_monitor = MagicMock()
    mock_monitor.hosts = {"host-A": MagicMock(status="online")}
    mock_monitor.get_last_containers = MagicMock(return_value=[])

    monkeypatch.setattr(deployment_routes, "_docker_monitor", mock_monitor)

    return mock_monitor


@pytest.mark.integration
class TestValidatePortsRoute:
    def test_conflict_returned(self, authed_client, stack_exists, override_monitor):
        override_monitor.get_last_containers = MagicMock(return_value=[
            _FakeContainer(
                id="aaaaaaaaaaaa", name="nginx-proxy", host_id="host-A",
                ports=["8080:80/tcp"], labels={},
            ),
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
        response = authed_client.post(
            "/api/stacks/foo/validate-ports",
            json={"host_id": "host-A"},
        )

        assert response.status_code == 200
        assert response.json() == {"conflicts": []}

    def test_redeploy_self_exclusion(self, authed_client, stack_exists, override_monitor):
        override_monitor.get_last_containers = MagicMock(return_value=[
            _FakeContainer(
                id="aaaaaaaaaaaa", name="foo-web", host_id="host-A",
                ports=["8080:80/tcp"],
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
            stack_storage, "read_stack",
            AsyncMock(side_effect=FileNotFoundError("Stack 'does-not-exist' not found")),
        )

        response = authed_client.post(
            "/api/stacks/does-not-exist/validate-ports",
            json={"host_id": "host-A"},
        )

        assert response.status_code == 404

    def test_host_offline(self, authed_client, stack_exists, override_monitor):
        override_monitor.hosts["host-A"] = MagicMock(status="offline")

        response = authed_client.post(
            "/api/stacks/foo/validate-ports",
            json={"host_id": "host-A"},
        )

        assert response.status_code == 409

    def test_host_unknown(self, authed_client, stack_exists, override_monitor):
        response = authed_client.post(
            "/api/stacks/foo/validate-ports",
            json={"host_id": "host-unknown"},
        )

        assert response.status_code == 409

    def test_malformed_compose(self, authed_client, monkeypatch, override_monitor):
        from deployment import stack_storage
        monkeypatch.setattr(
            stack_storage, "read_stack",
            AsyncMock(return_value=("services:\n  web:\n    image: [unclosed", "")),
        )

        response = authed_client.post(
            "/api/stacks/foo/validate-ports",
            json={"host_id": "host-A"},
        )

        assert response.status_code == 400
