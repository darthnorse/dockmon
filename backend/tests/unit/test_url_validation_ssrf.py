"""
Tests for SSRF target detection.

is_ssrf_target blocks cloud metadata / link-local endpoints only. Private and
loopback addresses are intentionally allowed: Docker hosts and container
health-check targets legitimately live on private networks and localhost
(the health-check UI even suggests http://localhost:8080/health).
"""

import pytest

from utils.url_validation import is_ssrf_target


class TestSsrfTarget:
    def test_blocks_cloud_metadata(self):
        assert is_ssrf_target("http://169.254.169.254/latest/meta-data/") is True
        assert is_ssrf_target("http://metadata.google.internal/") is True

    def test_allows_private_rfc1918(self):
        assert is_ssrf_target("tcp://192.168.1.50:2376") is False
        assert is_ssrf_target("http://172.17.0.5:8080/health") is False

    def test_allows_loopback(self):
        # Health checks legitimately target localhost on the monitored host.
        assert is_ssrf_target("http://localhost:8080/health") is False
        assert is_ssrf_target("http://127.0.0.1:8080/health") is False

    def test_allows_public_host(self):
        assert is_ssrf_target("https://example.com/health") is False
