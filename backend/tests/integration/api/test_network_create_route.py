"""
Integration smoke test for POST /api/hosts/{host_id}/networks.

Confirms the create-network route is registered and requires authentication.
The create logic itself is covered by unit tests (utils.networks,
AgentContainerOperations.create_network, CreateNetworkRequest).
"""

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.integration
class TestCreateNetworkRoute:
    def test_requires_authentication(self, client):
        """Unauthenticated create must be rejected (valid body, so only auth fails)."""
        response = client.post(
            "/api/hosts/some-host/networks",
            json={"name": "my-net", "driver": "bridge"},
        )
        assert response.status_code == 401
