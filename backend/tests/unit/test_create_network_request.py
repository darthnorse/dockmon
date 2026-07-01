"""
Unit tests for CreateNetworkRequest validation.

Pins the per-host network create contract: Docker-valid names, a driver
allowlist that rejects overlay (Swarm-only), and CIDR/IP validation for the
optional IPAM fields.
"""

import pytest
from pydantic import ValidationError

from models.request_models import CreateNetworkRequest


@pytest.mark.unit
class TestCreateNetworkRequest:
    def test_minimal_defaults(self):
        req = CreateNetworkRequest(name="my-net")
        assert req.name == "my-net"
        assert req.driver == "bridge"
        assert req.subnet is None
        assert req.gateway is None
        assert req.internal is False

    def test_full_valid(self):
        req = CreateNetworkRequest(
            name="app_net.1",
            driver="bridge",
            subnet="172.30.0.0/16",
            gateway="172.30.0.1",
            internal=True,
        )
        assert req.subnet == "172.30.0.0/16"
        assert req.gateway == "172.30.0.1"
        assert req.internal is True

    def test_driver_normalized_to_lowercase(self):
        assert CreateNetworkRequest(name="n", driver="BRIDGE").driver == "bridge"

    def test_overlay_driver_rejected(self):
        with pytest.raises(ValidationError) as exc:
            CreateNetworkRequest(name="n", driver="overlay")
        assert "swarm" in str(exc.value).lower()

    def test_unknown_driver_rejected(self):
        with pytest.raises(ValidationError):
            CreateNetworkRequest(name="n", driver="frobnicate")

    @pytest.mark.parametrize("bad_name", ["", "  ", "-bad", "has space", "bad/slash"])
    def test_invalid_names_rejected(self, bad_name):
        with pytest.raises(ValidationError):
            CreateNetworkRequest(name=bad_name)

    def test_invalid_subnet_rejected(self):
        with pytest.raises(ValidationError):
            CreateNetworkRequest(name="n", subnet="not-a-cidr")

    def test_subnet_with_host_bits_rejected_with_suggestion(self):
        # 172.16.24.0/16 has host bits set; Docker requires the network base.
        with pytest.raises(ValidationError) as exc:
            CreateNetworkRequest(name="n", subnet="172.16.24.0/16")
        assert "172.16.0.0/16" in str(exc.value)

    def test_canonical_subnet_accepted(self):
        req = CreateNetworkRequest(name="n", subnet="172.16.0.0/16")
        assert req.subnet == "172.16.0.0/16"

    def test_invalid_gateway_rejected(self):
        with pytest.raises(ValidationError):
            CreateNetworkRequest(name="n", subnet="172.30.0.0/16", gateway="999.1.1.1")

    def test_gateway_without_subnet_rejected(self):
        with pytest.raises(ValidationError):
            CreateNetworkRequest(name="n", gateway="172.30.0.1")

    def test_gateway_outside_subnet_rejected(self):
        with pytest.raises(ValidationError) as exc:
            CreateNetworkRequest(name="n", subnet="172.30.0.0/16", gateway="10.0.0.1")
        assert "within subnet" in str(exc.value).lower()

    def test_gateway_version_mismatch_rejected(self):
        with pytest.raises(ValidationError):
            CreateNetworkRequest(name="n", subnet="172.30.0.0/16", gateway="fe80::1")

    def test_gateway_within_subnet_accepted(self):
        req = CreateNetworkRequest(name="n", subnet="172.30.0.0/16", gateway="172.30.0.1")
        assert req.gateway == "172.30.0.1"

    def test_blank_optional_fields_normalize_to_none(self):
        req = CreateNetworkRequest(name="n", subnet="", gateway="")
        assert req.subnet is None
        assert req.gateway is None
