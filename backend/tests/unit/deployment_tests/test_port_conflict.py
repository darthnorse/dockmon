"""
Unit tests for port_conflict.extract_ports_from_compose.

Covers compose port syntax: short form, long form, ranges, protocols,
auto-assigned ports, dedup across services.
"""

from dataclasses import dataclass
from typing import Optional

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

    def test_malformed_long_form_published_raises(self):
        yaml = """
services:
  web:
    image: nginx
    ports:
      - target: 80
        published: 8080-abc
"""
        with pytest.raises(ValueError, match="Invalid published port"):
            extract_ports_from_compose(yaml)

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


@dataclass(frozen=True)
class _FakeContainer:
    """Minimal fake matching the fields find_port_conflicts reads."""
    id: str
    name: str
    ports: Optional[list[str]]
    labels: Optional[dict[str, str]]


class TestFindPortConflicts:
    def test_empty_cache_no_conflicts(self):
        result = find_port_conflicts(
            requested=[PortSpec(port=8080, protocol="tcp")],
            containers=[],
            exclude_project=None,
        )
        assert result == []

    def test_single_match(self):
        result = find_port_conflicts(
            requested=[PortSpec(port=8080, protocol="tcp")],
            containers=[
                _FakeContainer(
                    id="aaaaaaaaaaaa", name="nginx-proxy",
                    ports=["8080:80/tcp"], labels={},
                ),
            ],
            exclude_project=None,
        )
        assert result == [Conflict(
            port=8080, protocol="tcp",
            container_id="aaaaaaaaaaaa", container_name="nginx-proxy",
        )]

    def test_multiple_matches(self):
        result = find_port_conflicts(
            requested=[
                PortSpec(port=8080, protocol="tcp"),
                PortSpec(port=443, protocol="tcp"),
            ],
            containers=[
                _FakeContainer(
                    id="aaaaaaaaaaaa", name="nginx",
                    ports=["8080:80/tcp"], labels={},
                ),
                _FakeContainer(
                    id="bbbbbbbbbbbb", name="api",
                    ports=["443:443/tcp"], labels={},
                ),
            ],
            exclude_project=None,
        )
        assert len(result) == 2
        ports = {c.port for c in result}
        assert ports == {8080, 443}

    def test_tcp_udp_separation(self):
        result = find_port_conflicts(
            requested=[PortSpec(port=53, protocol="tcp")],  # TCP, not UDP
            containers=[
                _FakeContainer(
                    id="aaaaaaaaaaaa", name="dns",
                    ports=["53:53/udp"], labels={},
                ),
            ],
            exclude_project=None,
        )
        assert result == []

    def test_exclude_project_filter_hits(self):
        result = find_port_conflicts(
            requested=[PortSpec(port=8080, protocol="tcp")],
            containers=[
                _FakeContainer(
                    id="aaaaaaaaaaaa", name="foo-web",
                    ports=["8080:80/tcp"],
                    labels={"com.docker.compose.project": "foo"},
                ),
            ],
            exclude_project="foo",
        )
        # foo's own container is excluded - no conflict reported
        assert result == []

    def test_exclude_project_filter_misses(self):
        result = find_port_conflicts(
            requested=[PortSpec(port=8080, protocol="tcp")],
            containers=[
                _FakeContainer(
                    id="aaaaaaaaaaaa", name="bar-web",
                    ports=["8080:80/tcp"],
                    labels={"com.docker.compose.project": "bar"},
                ),
            ],
            exclude_project="foo",  # looking for foo, but bar is what's there
        )
        assert len(result) == 1
        assert result[0].container_name == "bar-web"

    def test_external_docker_run_still_flagged(self):
        """Containers without compose labels are flagged even when exclude_project is set."""
        result = find_port_conflicts(
            requested=[PortSpec(port=8080, protocol="tcp")],
            containers=[
                _FakeContainer(
                    id="aaaaaaaaaaaa", name="rogue",
                    ports=["8080:80/tcp"],
                    labels={},  # no compose project label
                ),
            ],
            exclude_project="foo",
        )
        assert len(result) == 1
        assert result[0].container_name == "rogue"

    def test_no_containers(self):
        result = find_port_conflicts(
            requested=[PortSpec(port=8080, protocol="tcp")],
            containers=[],
            exclude_project=None,
        )
        assert result == []

    def test_port_with_no_protocol_defaults_tcp(self):
        """Container.ports strings may lack a protocol suffix (bare '8080:80')."""
        result = find_port_conflicts(
            requested=[PortSpec(port=8080, protocol="tcp")],
            containers=[
                _FakeContainer(
                    id="aaaaaaaaaaaa", name="x",
                    ports=["8080:80"], labels={},
                ),
            ],
            exclude_project=None,
        )
        assert len(result) == 1
