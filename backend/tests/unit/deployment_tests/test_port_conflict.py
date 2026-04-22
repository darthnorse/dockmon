"""
Unit tests for port_conflict.extract_ports_from_compose.

Covers compose port syntax: short form, long form, ranges, protocols,
auto-assigned ports, dedup across services.
"""

from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from deployment.port_conflict import Conflict, PortSpec, extract_ports_from_compose, find_port_conflicts


class TestExtractPortsFromCompose:
    def test_short_form_host_and_container(self):
        yaml = """
services:
  web:
    image: nginx
    ports:
      - "8080:80"
"""
        assert extract_ports_from_compose(yaml) == [PortSpec(port=8080, protocol="tcp")]

    def test_short_form_with_protocol(self):
        yaml = """
services:
  dns:
    image: pihole
    ports:
      - "53:53/udp"
"""
        assert extract_ports_from_compose(yaml) == [PortSpec(port=53, protocol="udp")]

    def test_short_form_with_ip_prefix(self):
        yaml = """
services:
  web:
    image: nginx
    ports:
      - "127.0.0.1:8080:80"
"""
        assert extract_ports_from_compose(yaml) == [PortSpec(port=8080, protocol="tcp")]

    def test_short_form_container_only_skipped(self):
        yaml = """
services:
  web:
    image: nginx
    ports:
      - "80"
"""
        assert extract_ports_from_compose(yaml) == []

    def test_short_form_range_expands(self):
        yaml = """
services:
  proxy:
    image: nginx
    ports:
      - "3000-3002:3000-3002"
"""
        result = extract_ports_from_compose(yaml)
        assert result == [
            PortSpec(port=3000, protocol="tcp"),
            PortSpec(port=3001, protocol="tcp"),
            PortSpec(port=3002, protocol="tcp"),
        ]

    def test_long_form(self):
        yaml = """
services:
  web:
    image: nginx
    ports:
      - target: 80
        published: 8080
        protocol: tcp
        mode: host
"""
        assert extract_ports_from_compose(yaml) == [PortSpec(port=8080, protocol="tcp")]

    def test_long_form_defaults_to_tcp(self):
        yaml = """
services:
  web:
    image: nginx
    ports:
      - target: 80
        published: 8080
"""
        assert extract_ports_from_compose(yaml) == [PortSpec(port=8080, protocol="tcp")]

    def test_long_form_udp(self):
        yaml = """
services:
  dns:
    image: pihole
    ports:
      - target: 53
        published: 53
        protocol: udp
"""
        assert extract_ports_from_compose(yaml) == [PortSpec(port=53, protocol="udp")]

    def test_long_form_without_published_skipped(self):
        yaml = """
services:
  web:
    image: nginx
    ports:
      - target: 80
"""
        assert extract_ports_from_compose(yaml) == []

    def test_dedup_across_services(self):
        yaml = """
services:
  web:
    image: nginx
    ports:
      - "8080:80"
  api:
    image: myapi
    ports:
      - "8080:80"
"""
        # Same host port declared twice — dedup, the compose itself will fail
        # to deploy, but our job is only to report what's conflicting with OTHER
        # stacks. Returning one entry keeps the API response simple.
        assert extract_ports_from_compose(yaml) == [PortSpec(port=8080, protocol="tcp")]

    def test_no_services_key(self):
        assert extract_ports_from_compose("version: '3'\n") == []

    def test_service_with_no_ports(self):
        yaml = """
services:
  worker:
    image: myworker
"""
        assert extract_ports_from_compose(yaml) == []

    def test_services_not_dict_returns_empty(self):
        """Compose with services declared as a list (structurally invalid) returns empty, not a crash."""
        yaml = """
services:
  - web
"""
        assert extract_ports_from_compose(yaml) == []

    def test_ports_not_list_skipped(self):
        """Service with ports declared as a scalar (structurally invalid) is skipped, not a crash."""
        yaml = """
services:
  web:
    image: nginx
    ports: 8080
"""
        assert extract_ports_from_compose(yaml) == []

    def test_malformed_yaml_raises(self):
        with pytest.raises(ValueError, match="Invalid compose YAML"):
            extract_ports_from_compose("services:\n  web:\n    image: [unclosed")

    def test_numeric_port_values(self):
        # Compose allows numeric (integer) port values in short form
        yaml = """
services:
  web:
    image: nginx
    ports:
      - 8080:80
"""
        assert extract_ports_from_compose(yaml) == [PortSpec(port=8080, protocol="tcp")]


@dataclass
class _FakeContainer:
    """Minimal fake matching the fields find_port_conflicts reads."""
    id: str
    name: str
    ports: Optional[list[str]]
    labels: Optional[dict[str, str]]


def _make_monitor(containers_by_host: dict[str, list[_FakeContainer]]) -> MagicMock:
    """
    Build a mock monitor whose `get_containers(host_id=...)` coroutine returns
    the provided list for the given host, or [] for unknown hosts.
    """
    monitor = MagicMock()

    async def _get(host_id=None):
        return containers_by_host.get(host_id, [])

    monitor.get_containers = AsyncMock(side_effect=_get)
    return monitor


class TestFindPortConflicts:
    @pytest.mark.asyncio
    async def test_empty_cache_no_conflicts(self):
        monitor = _make_monitor({"host-A": []})
        result = await find_port_conflicts(
            host_id="host-A",
            requested=[PortSpec(port=8080, protocol="tcp")],
            exclude_project=None,
            monitor=monitor,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_single_match(self):
        monitor = _make_monitor({
            "host-A": [
                _FakeContainer(
                    id="aaaaaaaaaaaa", name="nginx-proxy",
                    ports=["8080:80/tcp"], labels={},
                ),
            ],
        })
        result = await find_port_conflicts(
            host_id="host-A",
            requested=[PortSpec(port=8080, protocol="tcp")],
            exclude_project=None,
            monitor=monitor,
        )
        assert result == [Conflict(
            port=8080, protocol="tcp",
            container_id="aaaaaaaaaaaa", container_name="nginx-proxy",
        )]

    @pytest.mark.asyncio
    async def test_multiple_matches(self):
        monitor = _make_monitor({
            "host-A": [
                _FakeContainer(
                    id="aaaaaaaaaaaa", name="nginx",
                    ports=["8080:80/tcp"], labels={},
                ),
                _FakeContainer(
                    id="bbbbbbbbbbbb", name="api",
                    ports=["443:443/tcp"], labels={},
                ),
            ],
        })
        result = await find_port_conflicts(
            host_id="host-A",
            requested=[
                PortSpec(port=8080, protocol="tcp"),
                PortSpec(port=443, protocol="tcp"),
            ],
            exclude_project=None,
            monitor=monitor,
        )
        assert len(result) == 2
        ports = {c.port for c in result}
        assert ports == {8080, 443}

    @pytest.mark.asyncio
    async def test_tcp_udp_separation(self):
        monitor = _make_monitor({
            "host-A": [
                _FakeContainer(
                    id="aaaaaaaaaaaa", name="dns",
                    ports=["53:53/udp"], labels={},
                ),
            ],
        })
        result = await find_port_conflicts(
            host_id="host-A",
            requested=[PortSpec(port=53, protocol="tcp")],  # TCP, not UDP
            exclude_project=None,
            monitor=monitor,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_exclude_project_filter_hits(self):
        monitor = _make_monitor({
            "host-A": [
                _FakeContainer(
                    id="aaaaaaaaaaaa", name="foo-web",
                    ports=["8080:80/tcp"],
                    labels={"com.docker.compose.project": "foo"},
                ),
            ],
        })
        result = await find_port_conflicts(
            host_id="host-A",
            requested=[PortSpec(port=8080, protocol="tcp")],
            exclude_project="foo",
            monitor=monitor,
        )
        # foo's own container is excluded - no conflict reported
        assert result == []

    @pytest.mark.asyncio
    async def test_exclude_project_filter_misses(self):
        monitor = _make_monitor({
            "host-A": [
                _FakeContainer(
                    id="aaaaaaaaaaaa", name="bar-web",
                    ports=["8080:80/tcp"],
                    labels={"com.docker.compose.project": "bar"},
                ),
            ],
        })
        result = await find_port_conflicts(
            host_id="host-A",
            requested=[PortSpec(port=8080, protocol="tcp")],
            exclude_project="foo",  # looking for foo, but bar is what's there
            monitor=monitor,
        )
        assert len(result) == 1
        assert result[0].container_name == "bar-web"

    @pytest.mark.asyncio
    async def test_external_docker_run_still_flagged(self):
        """Containers without compose labels are flagged even when exclude_project is set."""
        monitor = _make_monitor({
            "host-A": [
                _FakeContainer(
                    id="aaaaaaaaaaaa", name="rogue",
                    ports=["8080:80/tcp"],
                    labels={},  # no compose project label
                ),
            ],
        })
        result = await find_port_conflicts(
            host_id="host-A",
            requested=[PortSpec(port=8080, protocol="tcp")],
            exclude_project="foo",
            monitor=monitor,
        )
        assert len(result) == 1
        assert result[0].container_name == "rogue"

    @pytest.mark.asyncio
    async def test_no_cache_for_host(self):
        monitor = _make_monitor({})  # host not in cache
        result = await find_port_conflicts(
            host_id="host-unknown",
            requested=[PortSpec(port=8080, protocol="tcp")],
            exclude_project=None,
            monitor=monitor,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_port_with_no_protocol_defaults_tcp(self):
        """Container.ports strings may lack a protocol suffix (bare '8080:80')."""
        monitor = _make_monitor({
            "host-A": [
                _FakeContainer(
                    id="aaaaaaaaaaaa", name="x",
                    ports=["8080:80"], labels={},
                ),
            ],
        })
        result = await find_port_conflicts(
            host_id="host-A",
            requested=[PortSpec(port=8080, protocol="tcp")],
            exclude_project=None,
            monitor=monitor,
        )
        assert len(result) == 1
