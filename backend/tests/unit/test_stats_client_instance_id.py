"""stats_client.get_instance_id is how the backend notices a restarted stats-service."""
import types

import pytest

from stats_client import StatsServiceClient


class FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def client_returning(status=200, payload=None, error=None):
    client = StatsServiceClient()

    def get(url):
        if error:
            raise error
        return FakeResponse(status, payload)

    async def get_session():
        return types.SimpleNamespace(get=get)

    client._get_session = get_session
    return client


async def test_returns_the_instance_id():
    client = client_returning(payload={"status": "ok", "instance_id": "a1b2c3"})
    assert await client.get_instance_id() == "a1b2c3"


@pytest.mark.parametrize(
    "client",
    [
        client_returning(status=503, payload={"instance_id": "a1b2c3"}),
        client_returning(payload={"status": "ok"}),
        client_returning(payload={"instance_id": ""}),
        client_returning(payload=["not", "a", "dict"]),
        client_returning(error=OSError("connection refused")),
    ],
    ids=["http-error", "missing", "empty", "not-a-dict", "unreachable"],
)
async def test_returns_none_when_unknown(client):
    assert await client.get_instance_id() is None
