"""
Unit tests for stack orchestration and dependency resolution.

Tests:
- Service dependency resolution and grouping
- Topological sort algorithm correctness
- Parallel deployment grouping
- Integration with ComposeValidator
"""

import pytest
import sys
import os
import tempfile

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

# Set temp data dir for tests BEFORE importing any modules
# This prevents audit.py from trying to create /app directory
temp_dir = tempfile.mkdtemp()
os.environ['DOCKMON_DATA_DIR'] = temp_dir

# Now safe to import
from deployment.stack_orchestrator import StackOrchestrator, StackOrchestrationError
from deployment.compose_validator import ComposeValidator, DependencyCycleError, ComposeValidationError


# Cleanup temp directory after all tests
@pytest.fixture(scope="module", autouse=True)
def cleanup_temp_dir():
    """Cleanup temporary directory after tests"""
    yield
    import shutil
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)


class TestServiceGrouping:
    """Test service dependency resolution and grouping for parallel deployment."""

    def setup_method(self):
        """Setup test fixtures."""
        self.orchestrator = StackOrchestrator()

    def test_no_dependencies_all_parallel(self):
        """Test stack with no dependencies - all services should be in one group."""
        compose_data = {
            'services': {
                'service1': {'image': 'nginx:latest'},
                'service2': {'image': 'redis:latest'},
                'service3': {'image': 'postgres:14'},
            }
        }

        groups = self.orchestrator.get_service_groups(compose_data)

        assert len(groups) == 1, "All services without dependencies should be in one group"
        assert set(groups[0]) == {'service1', 'service2', 'service3'}

    def test_linear_dependency_chain(self):
        """Test simple linear dependency chain."""
        compose_data = {
            'services': {
                'db': {'image': 'postgres:14'},
                'api': {
                    'image': 'myapp/api:latest',
                    'depends_on': ['db']
                },
                'web': {
                    'image': 'myapp/web:latest',
                    'depends_on': ['api']
                },
            }
        }

        groups = self.orchestrator.get_service_groups(compose_data)

        assert len(groups) == 3, "Linear chain should produce 3 groups"
        assert groups[0] == ['db'], "Database should be in first group"
        assert groups[1] == ['api'], "API should be in second group"
        assert groups[2] == ['web'], "Web should be in third group"

    def test_diamond_dependency_pattern(self):
        """Test diamond dependency pattern - parallel deployment in middle layer."""
        compose_data = {
            'services': {
                'db': {'image': 'postgres:14'},
                'cache': {'image': 'redis:latest'},
                'api': {
                    'image': 'myapp/api:latest',
                    'depends_on': ['db', 'cache']
                },
                'web': {
                    'image': 'myapp/web:latest',
                    'depends_on': ['api']
                },
            }
        }

        groups = self.orchestrator.get_service_groups(compose_data)

        assert len(groups) == 3, "Diamond pattern should produce 3 groups"
        assert set(groups[0]) == {'cache', 'db'}, "DB and cache should be in first group (parallel)"
        assert groups[1] == ['api'], "API should be in second group"
        assert groups[2] == ['web'], "Web should be in third group"

    def test_complex_multi_level_dependencies(self):
        """Test complex dependency graph with multiple levels."""
        compose_data = {
            'services': {
                'd': {'image': 'service-d'},
                'b': {
                    'image': 'service-b',
                    'depends_on': ['d']
                },
                'c': {
                    'image': 'service-c',
                    'depends_on': ['d']
                },
                'a': {
                    'image': 'service-a',
                    'depends_on': ['b', 'c']
                },
            }
        }

        groups = self.orchestrator.get_service_groups(compose_data)

        assert len(groups) == 3, "Complex graph should produce 3 groups"
        assert groups[0] == ['d'], "Service d should be in first group"
        assert set(groups[1]) == {'b', 'c'}, "Services b and c should be in second group (parallel)"
        assert groups[2] == ['a'], "Service a should be in third group"

    def test_depends_on_dict_format(self):
        """Test depends_on in dict format (with healthcheck conditions)."""
        compose_data = {
            'services': {
                'db': {'image': 'postgres:14'},
                'api': {
                    'image': 'myapp/api:latest',
                    'depends_on': {
                        'db': {
                            'condition': 'service_healthy'
                        }
                    }
                },
            }
        }

        groups = self.orchestrator.get_service_groups(compose_data)

        assert len(groups) == 2, "Dict format should work same as list format"
        assert groups[0] == ['db']
        assert groups[1] == ['api']

    def test_depends_on_list_format(self):
        """Test depends_on in list format (simple dependencies)."""
        compose_data = {
            'services': {
                'db': {'image': 'postgres:14'},
                'api': {
                    'image': 'myapp/api:latest',
                    'depends_on': ['db']
                },
            }
        }

        groups = self.orchestrator.get_service_groups(compose_data)

        assert len(groups) == 2
        assert groups[0] == ['db']
        assert groups[1] == ['api']

    def test_empty_services(self):
        """Test compose file with no services."""
        compose_data = {}

        groups = self.orchestrator.get_service_groups(compose_data)

        assert groups == [], "Empty services should return empty list"

    def test_wordpress_mysql_stack(self):
        """Test realistic WordPress + MySQL stack."""
        compose_data = {
            'services': {
                'db': {
                    'image': 'mysql:8',
                    'environment': {
                        'MYSQL_ROOT_PASSWORD': 'example',
                        'MYSQL_DATABASE': 'wordpress'
                    }
                },
                'wordpress': {
                    'image': 'wordpress:latest',
                    'depends_on': ['db'],
                    'ports': ['8080:80']
                }
            }
        }

        groups = self.orchestrator.get_service_groups(compose_data)

        assert len(groups) == 2
        assert groups[0] == ['db']
        assert groups[1] == ['wordpress']


class TestDependencyValidation:
    """Test dependency validation via ComposeValidator."""

    def setup_method(self):
        """Setup test fixtures."""
        self.validator = ComposeValidator()

    def test_circular_dependency_simple(self):
        """Test circular dependency detection - simple 2-service cycle."""
        compose_data = {
            'services': {
                'a': {
                    'image': 'service-a',
                    'depends_on': ['b']
                },
                'b': {
                    'image': 'service-b',
                    'depends_on': ['a']
                },
            }
        }

        with pytest.raises(DependencyCycleError, match="Dependency cycle detected"):
            self.validator.validate_dependencies(compose_data)

    def test_circular_dependency_complex(self):
        """Test circular dependency detection - 3-service cycle."""
        compose_data = {
            'services': {
                'a': {
                    'image': 'service-a',
                    'depends_on': ['b']
                },
                'b': {
                    'image': 'service-b',
                    'depends_on': ['c']
                },
                'c': {
                    'image': 'service-c',
                    'depends_on': ['a']
                },
            }
        }

        with pytest.raises(DependencyCycleError, match="Dependency cycle detected"):
            self.validator.validate_dependencies(compose_data)

    def test_self_dependency(self):
        """Test service depending on itself."""
        compose_data = {
            'services': {
                'a': {
                    'image': 'service-a',
                    'depends_on': ['a']
                },
            }
        }

        with pytest.raises(DependencyCycleError, match="depends on itself"):
            self.validator.validate_dependencies(compose_data)

    def test_missing_dependency(self):
        """Test service depending on non-existent service."""
        compose_data = {
            'services': {
                'api': {
                    'image': 'myapp/api:latest',
                    'depends_on': ['nonexistent']
                },
            }
        }

        with pytest.raises(ComposeValidationError, match="not found"):
            self.validator.validate_dependencies(compose_data)

    def test_missing_dependency_in_dict_format(self):
        """Test missing dependency with dict format depends_on."""
        compose_data = {
            'services': {
                'api': {
                    'image': 'myapp/api:latest',
                    'depends_on': {
                        'nonexistent': {
                            'condition': 'service_healthy'
                        }
                    }
                },
            }
        }

        with pytest.raises(ComposeValidationError, match="not found"):
            self.validator.validate_dependencies(compose_data)

    def test_valid_dependencies(self):
        """Test that valid dependencies pass validation."""
        compose_data = {
            'services': {
                'db': {'image': 'postgres:14'},
                'api': {
                    'image': 'myapp/api:latest',
                    'depends_on': ['db']
                },
            }
        }

        # Should not raise
        self.validator.validate_dependencies(compose_data)


class TestStartupOrder:
    """Test startup order calculation (topological sort)."""

    def setup_method(self):
        """Setup test fixtures."""
        self.validator = ComposeValidator()

    def test_startup_order_linear(self):
        """Test startup order for linear dependency chain."""
        compose_data = {
            'services': {
                'db': {'image': 'postgres:14'},
                'api': {
                    'image': 'myapp/api:latest',
                    'depends_on': ['db']
                },
                'web': {
                    'image': 'myapp/web:latest',
                    'depends_on': ['api']
                },
            }
        }

        order = self.validator.get_startup_order(compose_data)

        assert order == ['db', 'api', 'web'], "Linear chain should produce sequential order"

    def test_startup_order_parallel_possible(self):
        """Test startup order preserves parallel opportunities."""
        compose_data = {
            'services': {
                'db': {'image': 'postgres:14'},
                'cache': {'image': 'redis:latest'},
                'api': {
                    'image': 'myapp/api:latest',
                    'depends_on': ['db', 'cache']
                },
            }
        }

        order = self.validator.get_startup_order(compose_data)

        # Both db and cache should come before api
        db_index = order.index('db')
        cache_index = order.index('cache')
        api_index = order.index('api')

        assert db_index < api_index, "DB should start before API"
        assert cache_index < api_index, "Cache should start before API"

    def test_startup_order_deterministic(self):
        """Test that startup order is deterministic (sorted when multiple valid orders)."""
        compose_data = {
            'services': {
                'service1': {'image': 'img1'},
                'service2': {'image': 'img2'},
                'service3': {'image': 'img3'},
            }
        }

        # Run multiple times, should always be same order
        order1 = self.validator.get_startup_order(compose_data)
        order2 = self.validator.get_startup_order(compose_data)
        order3 = self.validator.get_startup_order(compose_data)

        assert order1 == order2 == order3, "Order should be deterministic"
        assert order1 == ['service1', 'service2', 'service3'], "Should be alphabetically sorted"

    def test_startup_order_cycle_detection(self):
        """Test that get_startup_order detects cycles."""
        compose_data = {
            'services': {
                'a': {
                    'image': 'service-a',
                    'depends_on': ['b']
                },
                'b': {
                    'image': 'service-b',
                    'depends_on': ['a']
                },
            }
        }

        with pytest.raises(DependencyCycleError):
            self.validator.get_startup_order(compose_data)


class TestDeploymentPlanning:
    """Test deployment operation planning."""

    def setup_method(self):
        """Setup test fixtures."""
        self.orchestrator = StackOrchestrator()

    def test_plan_deployment_services_only(self):
        """Test planning deployment with only services."""
        compose_data = {
            'services': {
                'db': {'image': 'postgres:14'},
                'api': {
                    'image': 'myapp/api:latest',
                    'depends_on': ['db']
                },
            }
        }

        operations = self.orchestrator.plan_deployment(compose_data)

        # Should have 2 create_service operations
        service_ops = [op for op in operations if op['type'] == 'create_service']
        assert len(service_ops) == 2

        # DB should be before API (dependency order)
        service_names = [op['name'] for op in service_ops]
        db_index = service_names.index('db')
        api_index = service_names.index('api')
        assert db_index < api_index

    def test_plan_deployment_with_networks(self):
        """Test planning deployment with networks."""
        compose_data = {
            'networks': {
                'frontend': {},
                'backend': {},
            },
            'services': {
                'web': {
                    'image': 'nginx:latest',
                    'networks': ['frontend']
                },
            }
        }

        operations = self.orchestrator.plan_deployment(compose_data)

        # Networks should be created before services
        network_ops = [op for op in operations if op['type'] == 'create_network']
        service_ops = [op for op in operations if op['type'] == 'create_service']

        assert len(network_ops) == 2
        assert len(service_ops) == 1

        # Find indices (networks should come first)
        first_network_idx = operations.index(network_ops[0])
        first_service_idx = operations.index(service_ops[0])
        assert first_network_idx < first_service_idx

    def test_plan_deployment_with_volumes(self):
        """Test planning deployment with volumes."""
        compose_data = {
            'volumes': {
                'db-data': {},
            },
            'services': {
                'db': {
                    'image': 'postgres:14',
                    'volumes': ['db-data:/var/lib/postgresql/data']
                },
            }
        }

        operations = self.orchestrator.plan_deployment(compose_data)

        # Should have volume creation
        volume_ops = [op for op in operations if op['type'] == 'create_volume']
        assert len(volume_ops) == 1
        assert volume_ops[0]['name'] == 'db-data'

    def test_plan_deployment_skips_external_networks(self):
        """Test that external networks are not created."""
        compose_data = {
            'networks': {
                'internal': {},
                'external_net': {
                    'external': True
                }
            },
            'services': {
                'web': {'image': 'nginx:latest'}
            }
        }

        operations = self.orchestrator.plan_deployment(compose_data)

        network_ops = [op for op in operations if op['type'] == 'create_network']

        # Should only create 'internal', not 'external_net'
        assert len(network_ops) == 1
        assert network_ops[0]['name'] == 'internal'

    def test_plan_deployment_wordpress_stack(self):
        """Test planning realistic WordPress + MySQL + Redis stack."""
        compose_data = {
            'networks': {
                'wordpress-net': {}
            },
            'volumes': {
                'db-data': {},
                'wp-data': {}
            },
            'services': {
                'db': {
                    'image': 'mysql:8',
                    'volumes': ['db-data:/var/lib/mysql'],
                    'networks': ['wordpress-net']
                },
                'redis': {
                    'image': 'redis:latest',
                    'networks': ['wordpress-net']
                },
                'wordpress': {
                    'image': 'wordpress:latest',
                    'depends_on': ['db', 'redis'],
                    'volumes': ['wp-data:/var/www/html'],
                    'networks': ['wordpress-net']
                }
            }
        }

        operations = self.orchestrator.plan_deployment(compose_data)

        # Verify operation order
        network_ops = [op for op in operations if op['type'] == 'create_network']
        volume_ops = [op for op in operations if op['type'] == 'create_volume']
        service_ops = [op for op in operations if op['type'] == 'create_service']

        assert len(network_ops) == 1
        assert len(volume_ops) == 2
        assert len(service_ops) == 3

        # Services should be in dependency order
        service_names = [op['name'] for op in service_ops]
        wordpress_index = service_names.index('wordpress')

        # Both db and redis should come before wordpress
        if 'db' in service_names:
            db_index = service_names.index('db')
            assert db_index < wordpress_index

        if 'redis' in service_names:
            redis_index = service_names.index('redis')
            assert redis_index < wordpress_index


class TestRollbackPlanning:
    """Test rollback operation planning."""

    def setup_method(self):
        """Setup test fixtures."""
        self.orchestrator = StackOrchestrator()

    def test_plan_rollback_services_only(self):
        """Test rollback removes services in reverse order."""
        created_services = ['db', 'api', 'web']

        operations = self.orchestrator.plan_rollback(created_services)

        # Should have 3 remove operations
        assert len(operations) == 3
        assert all(op['type'] == 'remove_service' for op in operations)

        # Should be in reverse order
        service_names = [op['name'] for op in operations]
        assert service_names == ['web', 'api', 'db']

    def test_plan_rollback_with_networks(self):
        """Test rollback removes networks after services."""
        created_services = ['db', 'api']
        created_networks = ['frontend', 'backend']

        operations = self.orchestrator.plan_rollback(
            created_services,
            created_networks=created_networks
        )

        # Services should be removed first, then networks
        service_ops = [op for op in operations if op['type'] == 'remove_service']
        network_ops = [op for op in operations if op['type'] == 'remove_network']

        assert len(service_ops) == 2
        assert len(network_ops) == 2

        # Last service removal should come before first network removal
        last_service_idx = operations.index(service_ops[-1])
        first_network_idx = operations.index(network_ops[0])
        assert last_service_idx < first_network_idx

    def test_plan_rollback_preserves_external_networks(self):
        """Test rollback does not remove external networks."""
        created_services = ['web']
        created_networks = ['internal', 'external_net']
        external_networks = ['external_net']

        operations = self.orchestrator.plan_rollback(
            created_services,
            created_networks=created_networks,
            external_networks=external_networks
        )

        network_ops = [op for op in operations if op['type'] == 'remove_network']

        # Should only remove 'internal', not 'external_net'
        assert len(network_ops) == 1
        assert network_ops[0]['name'] == 'internal'


class TestProgressCalculation:
    """Test stack deployment progress calculation."""

    def setup_method(self):
        """Setup test fixtures."""
        self.orchestrator = StackOrchestrator()

    def test_progress_no_services(self):
        """Test progress calculation with zero services."""
        progress = self.orchestrator.calculate_progress(
            current_phase='pull_image',
            phase_percent=50,
            total_services=0,
            completed_services=0
        )

        assert progress == 100, "Zero services should be 100% complete"

    def test_progress_all_completed(self):
        """Test progress when all services are completed."""
        progress = self.orchestrator.calculate_progress(
            current_phase='pull_image',
            phase_percent=0,
            total_services=3,
            completed_services=3
        )

        assert progress == 100

    def test_progress_first_service_pulling(self):
        """Test progress during first service pull."""
        progress = self.orchestrator.calculate_progress(
            current_phase='pull_image',
            phase_percent=50,  # 50% through pull
            total_services=2,
            completed_services=0
        )

        # pull_image is 40% of single service, so 50% of 40% is 20%
        # For 2 services, single service is 50% of total
        # So: 50% of 40% of 50% = 10%
        assert progress == 10

    def test_progress_second_service_starting(self):
        """Test progress when second service is starting."""
        progress = self.orchestrator.calculate_progress(
            current_phase='starting',
            phase_percent=50,  # 50% through starting
            total_services=2,
            completed_services=1  # First service done
        )

        # First service complete: 50%
        # Second service starting (20% of service): 50% of 20% of 50% = 5%
        # Total: 55%
        assert progress == 55

    def test_progress_capped_at_100(self):
        """Test that progress never exceeds 100%."""
        progress = self.orchestrator.calculate_progress(
            current_phase='health_check',
            phase_percent=100,
            total_services=1,
            completed_services=1
        )

        assert progress <= 100
