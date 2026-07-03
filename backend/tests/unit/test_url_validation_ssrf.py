"""
Tests for SSRF target detection.

The default mode (Docker hosts) must keep allowing private/loopback addresses,
while the strict block_loopback mode (HTTP health checks) must additionally block
localhost, loopback, link-local and integer/hex IP encodings of them.
"""

import pytest

from utils.url_validation import is_ssrf_target


class TestDefaultMode:
    def test_blocks_cloud_metadata(self):
        assert is_ssrf_target("http://169.254.169.254/latest/meta-data/") is True

    def test_allows_private_rfc1918(self):
        # Docker hosts and container health targets legitimately live here.
        assert is_ssrf_target("tcp://192.168.1.50:2376") is False
        assert is_ssrf_target("http://172.17.0.5:8080/health") is False

    def test_allows_loopback_by_default(self):
        # Docker-host path historically allows tcp://127.0.0.1
        assert is_ssrf_target("tcp://127.0.0.1:2375") is False


class TestBlockLoopbackMode:
    def test_blocks_localhost(self):
        assert is_ssrf_target("http://localhost:8080/health", block_loopback=True) is True

    def test_blocks_loopback_ip(self):
        assert is_ssrf_target("http://127.0.0.1/health", block_loopback=True) is True
        assert is_ssrf_target("http://[::1]/health", block_loopback=True) is True

    def test_blocks_integer_encoded_loopback(self):
        # 2130706433 == 127.0.0.1
        assert is_ssrf_target("http://2130706433/health", block_loopback=True) is True

    def test_blocks_link_local_and_metadata(self):
        assert is_ssrf_target("http://169.254.169.254/", block_loopback=True) is True

    def test_still_allows_private_container_targets(self):
        # Containers on Docker/private networks must remain reachable.
        assert is_ssrf_target("http://172.17.0.5:8080/health", block_loopback=True) is False
        assert is_ssrf_target("http://192.168.1.10/health", block_loopback=True) is False

    def test_allows_public_host(self):
        assert is_ssrf_target("https://example.com/health", block_loopback=True) is False
