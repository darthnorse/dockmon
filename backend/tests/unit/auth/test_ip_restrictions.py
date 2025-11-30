"""
Comprehensive unit tests for IP allowlist functionality.

Tests cover:
- Single IP matching
- CIDR range matching (various subnet masks)
- Multiple entries (comma-separated lists)
- IPv4 edge cases
- Invalid IP format handling
- Reverse proxy scenarios
"""

import pytest
from auth.api_key_auth import _check_ip_allowed


class TestSingleIpAllowlist:
    """Test IP allowlist with single IP addresses"""

    def test_single_ip_exact_match(self):
        """Exact IP match allows access"""
        assert _check_ip_allowed("192.168.1.100", "192.168.1.100") is True

    def test_single_ip_no_match(self):
        """Different IP denies access"""
        assert _check_ip_allowed("192.168.1.100", "192.168.1.101") is False

    def test_single_ip_different_subnet(self):
        """IP in different subnet denies access"""
        assert _check_ip_allowed("192.168.1.100", "192.168.2.100") is False

    def test_single_ip_different_class(self):
        """IP in different class denies access"""
        assert _check_ip_allowed("10.0.0.1", "192.168.1.1") is False


class TestCidrRanges:
    """Test IP allowlist with CIDR ranges"""

    def test_cidr_24_subnet_start(self):
        """/24 CIDR: Match at subnet start"""
        assert _check_ip_allowed("192.168.1.0", "192.168.1.0/24") is True

    def test_cidr_24_subnet_middle(self):
        """/24 CIDR: Match in subnet middle"""
        assert _check_ip_allowed("192.168.1.128", "192.168.1.0/24") is True

    def test_cidr_24_subnet_end(self):
        """/24 CIDR: Match at subnet end"""
        assert _check_ip_allowed("192.168.1.255", "192.168.1.0/24") is True

    def test_cidr_24_subnet_outside(self):
        """/24 CIDR: Outside subnet denies"""
        assert _check_ip_allowed("192.168.2.1", "192.168.1.0/24") is False

    def test_cidr_16_subnet(self):
        """/16 CIDR: Larger subnet range"""
        assert _check_ip_allowed("192.168.255.255", "192.168.0.0/16") is True
        assert _check_ip_allowed("192.167.1.1", "192.168.0.0/16") is False

    def test_cidr_8_subnet(self):
        """/8 CIDR: Class A range"""
        assert _check_ip_allowed("10.255.255.255", "10.0.0.0/8") is True
        assert _check_ip_allowed("11.0.0.1", "10.0.0.0/8") is False

    def test_cidr_30_subnet(self):
        """/30 CIDR: Small subnet (4 hosts)"""
        assert _check_ip_allowed("192.168.1.1", "192.168.1.0/30") is True
        assert _check_ip_allowed("192.168.1.2", "192.168.1.0/30") is True
        assert _check_ip_allowed("192.168.1.3", "192.168.1.0/30") is True
        assert _check_ip_allowed("192.168.1.4", "192.168.1.0/30") is False

    def test_cidr_32_single_host(self):
        """/32 CIDR: Single host (equivalent to single IP)"""
        assert _check_ip_allowed("192.168.1.100", "192.168.1.100/32") is True
        assert _check_ip_allowed("192.168.1.101", "192.168.1.100/32") is False


class TestMultipleEntries:
    """Test IP allowlist with multiple comma-separated entries"""

    def test_multiple_ips_first_matches(self):
        """First IP in list matches"""
        allowed = "192.168.1.100,10.0.0.1,172.16.0.1"
        assert _check_ip_allowed("192.168.1.100", allowed) is True

    def test_multiple_ips_middle_matches(self):
        """Middle IP in list matches"""
        allowed = "192.168.1.100,10.0.0.1,172.16.0.1"
        assert _check_ip_allowed("10.0.0.1", allowed) is True

    def test_multiple_ips_last_matches(self):
        """Last IP in list matches"""
        allowed = "192.168.1.100,10.0.0.1,172.16.0.1"
        assert _check_ip_allowed("172.16.0.1", allowed) is True

    def test_multiple_ips_none_matches(self):
        """None of the IPs match"""
        allowed = "192.168.1.100,10.0.0.1,172.16.0.1"
        assert _check_ip_allowed("8.8.8.8", allowed) is False

    def test_multiple_cidrs_first_matches(self):
        """First CIDR in list matches"""
        allowed = "192.168.1.0/24,10.0.0.0/8"
        assert _check_ip_allowed("192.168.1.100", allowed) is True

    def test_multiple_cidrs_second_matches(self):
        """Second CIDR in list matches"""
        allowed = "192.168.1.0/24,10.0.0.0/8"
        assert _check_ip_allowed("10.50.100.200", allowed) is True

    def test_multiple_cidrs_none_matches(self):
        """None of the CIDRs match"""
        allowed = "192.168.1.0/24,10.0.0.0/8"
        assert _check_ip_allowed("172.16.0.1", allowed) is False

    def test_mixed_ips_and_cidrs_ip_matches(self):
        """Mixed IPs and CIDRs - IP matches"""
        allowed = "192.168.1.100,10.0.0.0/8,172.16.0.1"
        assert _check_ip_allowed("192.168.1.100", allowed) is True

    def test_mixed_ips_and_cidrs_cidr_matches(self):
        """Mixed IPs and CIDRs - CIDR matches"""
        allowed = "192.168.1.100,10.0.0.0/8,172.16.0.1"
        assert _check_ip_allowed("10.50.100.200", allowed) is True

    def test_mixed_ips_and_cidrs_exact_match(self):
        """Mixed IPs and CIDRs - Exact IP match (not in CIDR)"""
        allowed = "192.168.1.100,10.0.0.0/8,172.16.0.1"
        assert _check_ip_allowed("172.16.0.1", allowed) is True


class TestWhitespaceHandling:
    """Test IP allowlist with various whitespace"""

    def test_spaces_around_commas(self):
        """Spaces around comma separators are handled"""
        assert _check_ip_allowed("192.168.1.100", "192.168.1.100 , 10.0.0.1") is True

    def test_spaces_before_cidr(self):
        """Spaces before CIDR notation are handled"""
        assert _check_ip_allowed("192.168.1.100", "192.168.1.0/24 , 10.0.0.1") is True

    def test_leading_trailing_whitespace(self):
        """Leading/trailing whitespace in list is handled"""
        allowed = "  192.168.1.0/24  ,  10.0.0.1  "
        assert _check_ip_allowed("192.168.1.100", allowed) is True
        assert _check_ip_allowed("10.0.0.1", allowed) is True


class TestEdgeCases:
    """Test edge cases and error conditions"""

    def test_empty_allowed_list(self):
        """Empty allowlist denies all access"""
        assert _check_ip_allowed("192.168.1.100", "") is False

    def test_invalid_client_ip_format(self):
        """Invalid client IP format is denied"""
        assert _check_ip_allowed("not-an-ip", "192.168.1.0/24") is False

    def test_invalid_client_ip_too_many_octets(self):
        """Client IP with too many octets is denied"""
        assert _check_ip_allowed("192.168.1.1.1", "192.168.1.0/24") is False

    def test_invalid_allowed_ip_format(self):
        """Invalid allowed IP is skipped gracefully"""
        # Mix valid and invalid entries
        allowed = "192.168.1.0/24,invalid-entry,10.0.0.1"
        assert _check_ip_allowed("192.168.1.100", allowed) is True
        assert _check_ip_allowed("10.0.0.1", allowed) is True

    def test_invalid_cidr_prefix_too_large(self):
        """CIDR prefix > 32 is invalid and skipped"""
        allowed = "192.168.1.0/33,10.0.0.1"
        # Should skip invalid CIDR and check next entry
        assert _check_ip_allowed("10.0.0.1", allowed) is True

    def test_ipv4_localhost(self):
        """Localhost IP (127.0.0.1) matching"""
        assert _check_ip_allowed("127.0.0.1", "127.0.0.1") is True
        assert _check_ip_allowed("127.0.0.1", "127.0.0.0/8") is True

    def test_ipv4_zero(self):
        """0.0.0.0 as wildcard (allowed by ipaddress module)"""
        # 0.0.0.0 is technically valid but unusual
        # This tests the library behavior, not our policy
        assert _check_ip_allowed("192.168.1.1", "0.0.0.0/0") is True


class TestRealWorldScenarios:
    """Test real-world use cases"""

    def test_home_network_single_ip(self):
        """Home network: allow single external IP"""
        # Static IP from home ISP
        allowed = "203.0.113.5"
        assert _check_ip_allowed("203.0.113.5", allowed) is True
        assert _check_ip_allowed("203.0.113.6", allowed) is False

    def test_office_network_cidr(self):
        """Office network: allow entire subnet"""
        allowed = "192.168.1.0/24"
        assert _check_ip_allowed("192.168.1.1", allowed) is True
        assert _check_ip_allowed("192.168.1.254", allowed) is True
        assert _check_ip_allowed("192.168.2.1", allowed) is False

    def test_multiple_office_locations(self):
        """Multiple office locations with different subnets"""
        allowed = "192.168.1.0/24,10.20.0.0/16,172.16.50.0/24"
        # Office A
        assert _check_ip_allowed("192.168.1.100", allowed) is True
        # Office B
        assert _check_ip_allowed("10.20.50.100", allowed) is True
        # Office C
        assert _check_ip_allowed("172.16.50.100", allowed) is True
        # Outside
        assert _check_ip_allowed("8.8.8.8", allowed) is False

    def test_vlan_across_datacenters(self):
        """VPN spanning multiple subnets"""
        allowed = "10.0.0.0/8"  # Entire 10.0.0.0 - 10.255.255.255
        assert _check_ip_allowed("10.1.1.1", allowed) is True
        assert _check_ip_allowed("10.100.50.1", allowed) is True
        assert _check_ip_allowed("10.255.255.255", allowed) is True

    def test_reverse_proxy_ip(self):
        """Reverse proxy (trusting X-Forwarded-For extracted IP)"""
        # IP extracted from X-Forwarded-For header
        client_ip = "203.0.113.42"
        allowed = "203.0.113.0/24"  # Allow entire ISP subnet
        assert _check_ip_allowed(client_ip, allowed) is True

    def test_corporate_vpn_gateway(self):
        """Corporate VPN with multiple gateways"""
        allowed = "10.0.1.1,10.0.2.1,10.0.3.1"  # Multiple VPN gateways
        assert _check_ip_allowed("10.0.1.1", allowed) is True
        assert _check_ip_allowed("10.0.2.1", allowed) is True
        assert _check_ip_allowed("10.0.3.1", allowed) is True
        assert _check_ip_allowed("10.0.4.1", allowed) is False
