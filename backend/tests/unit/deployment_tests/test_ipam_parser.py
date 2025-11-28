"""
Unit tests for IPAM configuration parser in deployment.

Tests the parse_ipam_config() function which converts Docker Compose IPAM
configuration to Docker SDK IPAMConfig objects.
"""

import pytest
from docker.types import IPAMConfig, IPAMPool

# Import directly from the new module location
from deployment.network_helpers import parse_ipam_config


@pytest.mark.unit
class TestIPAMParser:
    """Test IPAM configuration parser"""

    def test_parse_ipam_minimal_subnet_only(self):
        """Test parsing IPAM config with just subnet"""
        ipam_dict = {
            'config': [
                {'subnet': '172.20.0.0/16'}
            ]
        }

        result = parse_ipam_config(ipam_dict)

        assert isinstance(result, IPAMConfig)
        assert result.get('Driver') is None  # Not specified
        assert result.get('Options') is None
        assert len(result['Config']) == 1
        assert result['Config'][0]['Subnet'] == '172.20.0.0/16'
        assert result['Config'][0].get('Gateway') is None
        assert result['Config'][0].get('IPRange') is None

    def test_parse_ipam_with_gateway(self):
        """Test parsing IPAM config with subnet and gateway"""
        ipam_dict = {
            'config': [
                {
                    'subnet': '172.20.0.0/16',
                    'gateway': '172.20.0.1'
                }
            ]
        }

        result = parse_ipam_config(ipam_dict)

        assert result['Config'][0]['Subnet'] == '172.20.0.0/16'
        assert result['Config'][0]['Gateway'] == '172.20.0.1'

    def test_parse_ipam_with_ip_range(self):
        """Test parsing IPAM config with IP range for dynamic allocation"""
        ipam_dict = {
            'config': [
                {
                    'subnet': '172.20.0.0/16',
                    'gateway': '172.20.0.1',
                    'ip_range': '172.20.240.0/20'
                }
            ]
        }

        result = parse_ipam_config(ipam_dict)

        assert result['Config'][0]['Subnet'] == '172.20.0.0/16'
        assert result['Config'][0]['Gateway'] == '172.20.0.1'
        assert result['Config'][0]['IPRange'] == '172.20.240.0/20'

    def test_parse_ipam_with_aux_addresses(self):
        """Test parsing IPAM config with auxiliary addresses"""
        ipam_dict = {
            'config': [
                {
                    'subnet': '172.20.0.0/16',
                    'aux_addresses': {
                        'host1': '172.20.0.5',
                        'host2': '172.20.0.6'
                    }
                }
            ]
        }

        result = parse_ipam_config(ipam_dict)

        assert result['Config'][0]['AuxiliaryAddresses'] == {
            'host1': '172.20.0.5',
            'host2': '172.20.0.6'
        }

    def test_parse_ipam_with_driver(self):
        """Test parsing IPAM config with custom driver"""
        ipam_dict = {
            'driver': 'custom-driver',
            'config': [
                {'subnet': '172.20.0.0/16'}
            ]
        }

        result = parse_ipam_config(ipam_dict)

        assert result['Driver'] == 'custom-driver'

    def test_parse_ipam_with_options(self):
        """Test parsing IPAM config with driver options"""
        ipam_dict = {
            'config': [
                {'subnet': '172.20.0.0/16'}
            ],
            'options': {
                'foo': 'bar',
                'custom': 'value'
            }
        }

        result = parse_ipam_config(ipam_dict)

        assert result['Options'] == {
            'foo': 'bar',
            'custom': 'value'
        }

    def test_parse_ipam_multiple_subnets(self):
        """Test parsing IPAM config with multiple subnet pools"""
        ipam_dict = {
            'config': [
                {
                    'subnet': '172.20.0.0/16',
                    'gateway': '172.20.0.1'
                },
                {
                    'subnet': '172.21.0.0/16',
                    'gateway': '172.21.0.1'
                }
            ]
        }

        result = parse_ipam_config(ipam_dict)

        assert len(result['Config']) == 2
        assert result['Config'][0]['Subnet'] == '172.20.0.0/16'
        assert result['Config'][0]['Gateway'] == '172.20.0.1'
        assert result['Config'][1]['Subnet'] == '172.21.0.0/16'
        assert result['Config'][1]['Gateway'] == '172.21.0.1'

    def test_parse_ipam_full_config(self):
        """Test parsing complete IPAM config with all fields"""
        ipam_dict = {
            'driver': 'default',
            'config': [
                {
                    'subnet': '172.20.0.0/16',
                    'gateway': '172.20.0.1',
                    'ip_range': '172.20.240.0/20',
                    'aux_addresses': {
                        'host1': '172.20.0.5'
                    }
                }
            ],
            'options': {
                'foo': 'bar'
            }
        }

        result = parse_ipam_config(ipam_dict)

        assert result['Driver'] == 'default'
        assert len(result['Config']) == 1
        assert result['Config'][0]['Subnet'] == '172.20.0.0/16'
        assert result['Config'][0]['Gateway'] == '172.20.0.1'
        assert result['Config'][0]['IPRange'] == '172.20.240.0/20'
        assert result['Config'][0]['AuxiliaryAddresses'] == {'host1': '172.20.0.5'}
        assert result['Options'] == {'foo': 'bar'}

    def test_parse_ipam_empty_dict(self):
        """Test parsing empty IPAM dict returns None"""
        result = parse_ipam_config({})

        assert result is None

    def test_parse_ipam_none(self):
        """Test parsing None returns None"""
        result = parse_ipam_config(None)

        assert result is None

    def test_parse_ipam_no_config_section(self):
        """Test parsing IPAM with driver but no config section"""
        ipam_dict = {
            'driver': 'default',
            'options': {'foo': 'bar'}
        }

        result = parse_ipam_config(ipam_dict)

        # Should create IPAMConfig with driver/options but empty Config
        assert isinstance(result, IPAMConfig)
        assert result['Driver'] == 'default'
        assert result['Options'] == {'foo': 'bar'}
        # No config section means no pool_configs passed (becomes empty list in Docker SDK)
        assert result.get('Config') in (None, [])

    def test_parse_ipam_empty_config_list(self):
        """Test parsing IPAM with empty config list"""
        ipam_dict = {
            'config': []
        }

        result = parse_ipam_config(ipam_dict)

        # Empty config list should result in empty Config list
        assert isinstance(result, IPAMConfig)
        assert result['Config'] == []

    def test_parse_ipam_invalid_config_entry(self):
        """Test parsing IPAM with invalid config entry (non-dict) skips it"""
        ipam_dict = {
            'config': [
                'invalid-string',  # Should be skipped
                {'subnet': '172.20.0.0/16'},  # Valid
                123,  # Should be skipped
            ]
        }

        result = parse_ipam_config(ipam_dict)

        # Should only have 1 pool (the valid one)
        assert len(result['Config']) == 1
        assert result['Config'][0]['Subnet'] == '172.20.0.0/16'
