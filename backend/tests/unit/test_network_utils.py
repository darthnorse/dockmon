"""
Unit tests for utils.networks helpers.

format_network() is the single source of truth for the network response shape
returned by BOTH the list and create endpoints - these tests pin that shape so
the two paths can never drift. build_network_ipam() covers IPAM construction
for the local/mTLS create path.
"""

import pytest
from unittest.mock import MagicMock
from docker.errors import APIError
from fastapi import HTTPException

from utils.networks import build_network_ipam, format_network, create_network_local


def make_network(
    net_id="abcdef123456" + "0" * 52,
    name="my-net",
    driver="bridge",
    scope="local",
    internal=False,
    created="2025-01-01T00:00:00.000000000Z",
    containers=None,
    subnet="172.20.0.0/16",
):
    net = MagicMock()
    net.id = net_id
    net.short_id = net_id[:12]
    net.name = name
    net.attrs = {
        "Driver": driver,
        "Scope": scope,
        "Internal": internal,
        "Created": created,
        "Containers": containers or {},
        "IPAM": {"Config": [{"Subnet": subnet}] if subnet else []},
    }
    return net


@pytest.mark.unit
class TestBuildNetworkIpam:
    def test_none_when_no_subnet(self):
        assert build_network_ipam("", "") is None
        # Gateway without subnet is meaningless - still None
        assert build_network_ipam("", "172.20.0.1") is None

    def test_subnet_and_gateway(self):
        ipam = build_network_ipam("172.20.0.0/16", "172.20.0.1")
        cfg = dict(ipam)["Config"][0]
        assert cfg["Subnet"] == "172.20.0.0/16"
        assert cfg["Gateway"] == "172.20.0.1"

    def test_subnet_without_gateway(self):
        ipam = build_network_ipam("10.0.0.0/24", "")
        cfg = dict(ipam)["Config"][0]
        assert cfg["Subnet"] == "10.0.0.0/24"
        assert cfg["Gateway"] is None


@pytest.mark.unit
class TestFormatNetwork:
    def test_full_shape(self):
        net = make_network(
            net_id="abcdef123456" + "0" * 52,
            name="app-net",
            driver="bridge",
            subnet="172.20.0.0/16",
            containers={"containerfullid000000": {"Name": "/web"}},
        )

        out = format_network(net)

        assert out == {
            "id": "abcdef123456",
            "name": "app-net",
            "driver": "bridge",
            "scope": "local",
            "created": "2025-01-01T00:00:00.000000000Z",
            "internal": False,
            "subnet": "172.20.0.0/16",
            "containers": [{"id": "containerful", "name": "web"}],
            "container_count": 1,
            "is_builtin": False,
        }

    def test_builtin_flag_and_timezone_normalization(self):
        net = make_network(
            name="bridge",
            created="2026-01-03T17:11:27.020018176-07:00",
            subnet=None,
        )
        net.attrs["IPAM"]["Config"] = []

        out = format_network(net)

        assert out["is_builtin"] is True
        assert out["subnet"] == ""
        assert out["created"].endswith("Z")
        assert "-07:00" not in out["created"]


def make_client(created_network=None, side_effect=None):
    """Mock docker client whose networks.create returns/raises as configured."""
    client = MagicMock()
    if side_effect is not None:
        client.networks.create = MagicMock(side_effect=side_effect)
    else:
        client.networks.create = MagicMock(return_value=created_network)
    return client


@pytest.mark.unit
class TestCreateNetworkLocal:
    async def test_success_creates_and_returns_formatted(self):
        net = make_network(name="my-net", subnet="172.20.0.0/16")
        net.reload = MagicMock()
        client = make_client(created_network=net)

        out = await create_network_local(
            client, "my-net", "bridge", "172.20.0.0/16", "172.20.0.1", False
        )

        assert out["name"] == "my-net"
        assert out["subnet"] == "172.20.0.0/16"
        # IPAM was passed through to the SDK
        _, kwargs = client.networks.create.call_args
        assert kwargs["driver"] == "bridge"
        assert kwargs["internal"] is False
        assert kwargs["ipam"] is not None
        net.reload.assert_called_once()

    async def test_no_subnet_passes_nil_ipam(self):
        net = make_network(name="auto", subnet=None)
        net.attrs["IPAM"]["Config"] = []
        net.reload = MagicMock()
        client = make_client(created_network=net)

        await create_network_local(client, "auto", "bridge", "", "", False)

        _, kwargs = client.networks.create.call_args
        assert kwargs["ipam"] is None

    async def test_duplicate_name_maps_to_409_by_status_code(self):
        resp = MagicMock()
        resp.status_code = 409
        client = make_client(side_effect=APIError("conflict", response=resp))

        with pytest.raises(HTTPException) as exc:
            await create_network_local(client, "my-net", "bridge", "", "", False)
        assert exc.value.status_code == 409

    async def test_duplicate_name_maps_to_409_by_message(self):
        # No response object -> status_code is None; fall back to message match
        client = make_client(side_effect=APIError("network with name my-net already exists"))

        with pytest.raises(HTTPException) as exc:
            await create_network_local(client, "my-net", "bridge", "", "", False)
        assert exc.value.status_code == 409

    async def test_other_api_error_maps_to_500(self):
        client = make_client(side_effect=APIError("pool overlaps with other one"))

        with pytest.raises(HTTPException) as exc:
            await create_network_local(client, "my-net", "bridge", "10.0.0.0/8", "", False)
        assert exc.value.status_code == 500
        # Surfaces the actionable Docker message
        assert "overlap" in exc.value.detail.lower()

    async def test_reload_failure_still_returns_success(self):
        # The network was created; a failed attribute refresh must NOT surface
        # as an error (otherwise a retry hits a spurious 409).
        net = make_network(name="my-net")
        net.id = "abc123def456" + "0" * 52
        net.reload = MagicMock(side_effect=APIError("daemon hiccup during inspect"))
        client = make_client(created_network=net)

        out = await create_network_local(client, "my-net", "bridge", "172.20.0.0/16", "", False)

        assert out["name"] == "my-net"
        assert out["id"] == "abc123def456"
        assert out["subnet"] == "172.20.0.0/16"
        assert out["containers"] == []

    async def test_non_api_error_on_create_maps_to_generic_500(self):
        # A non-APIError (e.g. dead socket) must be caught, not escape uncaught,
        # and must NOT echo the raw error (only Docker APIErrors are surfaced).
        client = make_client(side_effect=RuntimeError("socket gone: /var/run/docker.sock"))

        with pytest.raises(HTTPException) as exc:
            await create_network_local(client, "my-net", "bridge", "", "", False)
        assert exc.value.status_code == 500
        assert exc.value.detail == "Failed to create network"
