"""
Unit tests for port_conflict.extract_ports_from_compose.

Covers compose port syntax: short form, long form, ranges, protocols,
auto-assigned ports, dedup across services.
"""

import pytest
from deployment.port_conflict import PortSpec, extract_ports_from_compose


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
