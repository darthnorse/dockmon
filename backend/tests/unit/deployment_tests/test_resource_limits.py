"""
Unit tests for resource limits in stack orchestrator.

Tests the parsing of Docker Compose resource limit directives:
- Compose v2 syntax: mem_limit, cpus
- Compose v3 syntax: deploy.resources.limits/reservations
- Precedence: v3 takes priority over v2 when both specified
"""

import pytest
from deployment.stack_orchestrator import StackOrchestrator


class TestComposeV2ResourceLimits:
    """Test Compose v2 resource limit syntax (backward compatibility)"""

    def test_parse_mem_limit(self):
        """Test mem_limit directive (Compose v2)"""
        service_config = {
            'image': 'nginx:latest',
            'mem_limit': '512m'
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config.get('mem_limit') == '512m'

    def test_parse_cpus(self):
        """Test cpus directive (Compose v2)"""
        service_config = {
            'image': 'nginx:latest',
            'cpus': '1.5'
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        # Should be converted to NanoCpus (1.5 * 1e9)
        assert config.get('nano_cpus') == 1500000000

    def test_parse_cpus_float(self):
        """Test cpus with decimal value (Compose v2)"""
        service_config = {
            'image': 'nginx:latest',
            'cpus': '0.25'
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config.get('nano_cpus') == 250000000

    def test_parse_both_mem_and_cpu(self):
        """Test mem_limit and cpus together (Compose v2)"""
        service_config = {
            'image': 'nginx:latest',
            'mem_limit': '1g',
            'cpus': '2.0'
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config.get('mem_limit') == '1g'
        assert config.get('nano_cpus') == 2000000000


class TestComposeV3ResourceLimits:
    """Test Compose v3 deploy.resources syntax"""

    def test_parse_deploy_resources_memory_limit(self):
        """Test deploy.resources.limits.memory (Compose v3)"""
        service_config = {
            'image': 'nginx:latest',
            'deploy': {
                'resources': {
                    'limits': {
                        'memory': '512M'
                    }
                }
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config.get('mem_limit') == '512M'

    def test_parse_deploy_resources_cpu_limit(self):
        """Test deploy.resources.limits.cpus (Compose v3)"""
        service_config = {
            'image': 'nginx:latest',
            'deploy': {
                'resources': {
                    'limits': {
                        'cpus': '1.5'
                    }
                }
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config.get('nano_cpus') == 1500000000

    def test_parse_deploy_resources_memory_reservation(self):
        """Test deploy.resources.reservations.memory (Compose v3)"""
        service_config = {
            'image': 'nginx:latest',
            'deploy': {
                'resources': {
                    'reservations': {
                        'memory': '256M'
                    }
                }
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config.get('mem_reservation') == '256M'

    def test_parse_deploy_resources_all_fields(self):
        """Test deploy.resources with all fields (Compose v3)"""
        service_config = {
            'image': 'nginx:latest',
            'deploy': {
                'resources': {
                    'limits': {
                        'memory': '512M',
                        'cpus': '1.5'
                    },
                    'reservations': {
                        'memory': '256M'
                    }
                }
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config.get('mem_limit') == '512M'
        assert config.get('nano_cpus') == 1500000000
        assert config.get('mem_reservation') == '256M'

    def test_deploy_resources_with_only_limits(self):
        """Test deploy.resources with only limits, no reservations"""
        service_config = {
            'image': 'nginx:latest',
            'deploy': {
                'resources': {
                    'limits': {
                        'memory': '1G',
                        'cpus': '2'
                    }
                }
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config.get('mem_limit') == '1G'
        assert config.get('nano_cpus') == 2000000000
        assert 'mem_reservation' not in config

    def test_deploy_resources_with_only_reservations(self):
        """Test deploy.resources with only reservations, no limits"""
        service_config = {
            'image': 'nginx:latest',
            'deploy': {
                'resources': {
                    'reservations': {
                        'memory': '128M'
                    }
                }
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config.get('mem_reservation') == '128M'
        assert 'mem_limit' not in config
        assert 'nano_cpus' not in config


class TestResourceLimitsPrecedence:
    """Test precedence when both v2 and v3 syntax specified"""

    def test_v3_memory_overrides_v2(self):
        """Test deploy.resources.limits.memory overrides mem_limit"""
        service_config = {
            'image': 'nginx:latest',
            'mem_limit': '256m',  # v2 syntax
            'deploy': {
                'resources': {
                    'limits': {
                        'memory': '512M'  # v3 syntax - should win
                    }
                }
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        # v3 should override v2
        assert config.get('mem_limit') == '512M'

    def test_v3_cpus_overrides_v2(self):
        """Test deploy.resources.limits.cpus overrides cpus"""
        service_config = {
            'image': 'nginx:latest',
            'cpus': '1.0',  # v2 syntax
            'deploy': {
                'resources': {
                    'limits': {
                        'cpus': '2.0'  # v3 syntax - should win
                    }
                }
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        # v3 should override v2 (2.0 CPUs = 2e9 NanoCpus)
        assert config.get('nano_cpus') == 2000000000

    def test_v2_still_works_without_v3(self):
        """Test v2 syntax works when no v3 deploy section"""
        service_config = {
            'image': 'nginx:latest',
            'mem_limit': '128m',
            'cpus': '0.5'
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config.get('mem_limit') == '128m'
        assert config.get('nano_cpus') == 500000000


class TestResourceLimitsEdgeCases:
    """Test edge cases and error handling"""

    def test_deploy_without_resources(self):
        """Test deploy section without resources key"""
        service_config = {
            'image': 'nginx:latest',
            'deploy': {
                'replicas': 3  # Other deploy config, no resources
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        # Should not crash, no resource limits set
        assert 'mem_limit' not in config
        assert 'nano_cpus' not in config

    def test_empty_deploy_resources(self):
        """Test empty deploy.resources section"""
        service_config = {
            'image': 'nginx:latest',
            'deploy': {
                'resources': {}
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        # Should not crash, no limits set
        assert 'mem_limit' not in config
        assert 'nano_cpus' not in config

    def test_empty_limits_section(self):
        """Test empty limits section"""
        service_config = {
            'image': 'nginx:latest',
            'deploy': {
                'resources': {
                    'limits': {}
                }
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        # Should not crash
        assert 'mem_limit' not in config
        assert 'nano_cpus' not in config

    def test_only_memory_limit_no_cpu(self):
        """Test specifying only memory limit"""
        service_config = {
            'image': 'nginx:latest',
            'deploy': {
                'resources': {
                    'limits': {
                        'memory': '1G'
                    }
                }
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config.get('mem_limit') == '1G'
        assert 'nano_cpus' not in config

    def test_only_cpu_limit_no_memory(self):
        """Test specifying only CPU limit"""
        service_config = {
            'image': 'nginx:latest',
            'deploy': {
                'resources': {
                    'limits': {
                        'cpus': '4'
                    }
                }
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config.get('nano_cpus') == 4000000000
        assert 'mem_limit' not in config

    def test_integer_cpu_value(self):
        """Test CPU value as integer instead of string"""
        service_config = {
            'image': 'nginx:latest',
            'deploy': {
                'resources': {
                    'limits': {
                        'cpus': 2  # Integer, not string
                    }
                }
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        # Should handle int or str
        assert config.get('nano_cpus') == 2000000000
