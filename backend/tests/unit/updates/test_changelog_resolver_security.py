"""
Tests that OCI-label changelog resolution only accepts genuine GitHub https URLs.

An image label is attacker-controlled; a substring check ('github.com' in source)
let a value like "javascript:...//github.com" through, which was later rendered as
a clickable link (stored XSS). The resolver must validate scheme + host.
"""

import pytest

from updates.changelog_resolver import _check_oci_labels


class TestCheckOciLabels:
    def test_accepts_real_github_https_url(self):
        result = _check_oci_labels({"org.opencontainers.image.source": "https://github.com/foo/bar"})
        assert result == "https://github.com/foo/bar/releases"

    def test_rejects_javascript_scheme_disguised_with_github_substring(self):
        malicious = "javascript:fetch('//evil')//github.com"
        assert _check_oci_labels({"org.opencontainers.image.source": malicious}) is None

    def test_rejects_non_github_host_containing_substring(self):
        assert _check_oci_labels({"org.opencontainers.image.source": "https://evil.com/x#github.com"}) is None
        assert _check_oci_labels({"org.opencontainers.image.source": "https://github.com.evil.com/x"}) is None

    def test_accepts_subdomain_of_github(self):
        # e.g. enterprise/pages hosts — still a github.com host
        result = _check_oci_labels({"org.opencontainers.image.source": "https://www.github.com/foo/bar"})
        assert result == "https://www.github.com/foo/bar/releases"

    def test_missing_label_returns_none(self):
        assert _check_oci_labels({}) is None
        assert _check_oci_labels(None) is None
