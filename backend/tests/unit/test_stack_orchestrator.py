"""
Unit tests for Docker Compose stack orchestration.

TDD Phase: RED - Write tests first for stack orchestration

Tests cover:
- Service creation in correct dependency order
- Network creation before services
- Volume creation before services
- Progress tracking across multiple services
- Partial failure rollback (some services created, then failure)
- Stack-level operations (stop_all, start_all, remove_all)
"""

import pytest
from deployment.stack_orchestrator import StackOrchestrator, StackOrchestrationError


class TestStackServiceOrdering:
    """Test that services are created in correct dependency order"""

    def test_services_without_dependencies_parallel(self):
        """Should identify services that can be created in parallel"""
        compose_data = {
            'version': '3.8',
            'services': {
                'web': {'image': 'nginx:latest'},
                'cache': {'image': 'redis:latest'},
                'db': {'image': 'postgres:latest'}
            }
        }

        orchestrator = StackOrchestrator()
        groups = orchestrator.get_service_groups(compose_data)

        # All services can start in parallel (no dependencies)
        assert len(groups) == 1
        assert set(groups[0]) == {'web', 'cache', 'db'}

    def test_linear_dependency_chain(self):
        """Should create groups for linear chain (db -> api -> web)"""
        compose_data = {
            'version': '3.8',
            'services': {
                'web': {
                    'image': 'nginx:latest',
                    'depends_on': ['api']
                },
                'api': {
                    'image': 'node:latest',
                    'depends_on': ['db']
                },
                'db': {
                    'image': 'postgres:latest'
                }
            }
        }

        orchestrator = StackOrchestrator()
        groups = orchestrator.get_service_groups(compose_data)

        # Should create 3 groups (sequential)
        assert len(groups) == 3
        assert groups[0] == ['db']  # First (no deps)
        assert groups[1] == ['api']  # Second (depends on db)
        assert groups[2] == ['web']  # Third (depends on api)

    def test_diamond_dependency(self):
        """Should handle diamond dependency (web+api both depend on db+cache)"""
        compose_data = {
            'version': '3.8',
            'services': {
                'web': {
                    'image': 'nginx:latest',
                    'depends_on': ['db', 'cache']
                },
                'api': {
                    'image': 'node:latest',
                    'depends_on': ['db', 'cache']
                },
                'db': {
                    'image': 'postgres:latest'
                },
                'cache': {
                    'image': 'redis:latest'
                }
            }
        }

        orchestrator = StackOrchestrator()
        groups = orchestrator.get_service_groups(compose_data)

        # Should create 2 groups
        assert len(groups) == 2
        assert set(groups[0]) == {'db', 'cache'}  # First (no deps)
        assert set(groups[1]) == {'web', 'api'}   # Second (both depend on first group)


class TestNetworkCreation:
    """Test network creation before services"""

    def test_create_networks_before_services(self):
        """Should create all networks before any services"""
        compose_data = {
            'version': '3.8',
            'services': {
                'web': {
                    'image': 'nginx:latest',
                    'networks': ['frontend']
                }
            },
            'networks': {
                'frontend': {'driver': 'bridge'},
                'backend': {'driver': 'bridge'}
            }
        }

        orchestrator = StackOrchestrator()
        operations = orchestrator.plan_deployment(compose_data)

        # First operations should be network creation
        assert operations[0]['type'] == 'create_network'
        assert operations[1]['type'] == 'create_network'
        # Service creation comes after
        assert operations[2]['type'] == 'create_service'

    def test_skip_external_networks(self):
        """Should not create networks marked as external"""
        compose_data = {
            'version': '3.8',
            'services': {
                'web': {
                    'image': 'nginx:latest',
                    'networks': ['frontend']
                }
            },
            'networks': {
                'frontend': {'external': True}
            }
        }

        orchestrator = StackOrchestrator()
        operations = orchestrator.plan_deployment(compose_data)

        # Should NOT include create_network operation
        network_ops = [op for op in operations if op['type'] == 'create_network']
        assert len(network_ops) == 0


class TestVolumeCreation:
    """Test volume creation before services"""

    def test_create_volumes_before_services(self):
        """Should create all named volumes before services"""
        compose_data = {
            'version': '3.8',
            'services': {
                'db': {
                    'image': 'postgres:latest',
                    'volumes': ['db_data:/var/lib/postgresql/data']
                }
            },
            'volumes': {
                'db_data': {'driver': 'local'}
            }
        }

        orchestrator = StackOrchestrator()
        operations = orchestrator.plan_deployment(compose_data)

        # First operation should be volume creation
        assert operations[0]['type'] == 'create_volume'
        assert operations[0]['name'] == 'db_data'

    def test_skip_bind_mounts(self):
        """Should not create volumes for bind mounts (absolute paths)"""
        compose_data = {
            'version': '3.8',
            'services': {
                'web': {
                    'image': 'nginx:latest',
                    'volumes': ['/host/path:/container/path']
                }
            }
        }

        orchestrator = StackOrchestrator()
        operations = orchestrator.plan_deployment(compose_data)

        # Should NOT include create_volume operation
        volume_ops = [op for op in operations if op['type'] == 'create_volume']
        assert len(volume_ops) == 0


class TestProgressTracking:
    """Test progress tracking across multiple services"""

    def test_progress_calculation_single_service(self):
        """Should calculate progress correctly for single service"""
        orchestrator = StackOrchestrator()

        # Phases: pull_image (40%), creating (20%), starting (20%), health_check (20%)
        progress = orchestrator.calculate_progress(
            current_phase='pull_image',
            phase_percent=50,
            total_services=1,
            completed_services=0
        )

        # pull_image is 40% of total, 50% done = 20% overall
        assert progress == 20

    def test_progress_calculation_multi_service(self):
        """Should calculate progress across multiple services"""
        orchestrator = StackOrchestrator()

        # 3 services, currently on service 2, creating container (50% through)
        progress = orchestrator.calculate_progress(
            current_phase='creating',
            phase_percent=50,
            total_services=3,
            completed_services=1  # 1 service fully complete
        )

        # Service 1: 100% (33.3%)
        # Service 2: creating is 20% of single service, 50% done = 10% of single service = 3.3% overall
        # Total: 33.3 + 3.3 = ~36%
        assert 35 <= progress <= 38


class TestPartialFailureRollback:
    """Test rollback when some services created but then failure occurs"""

    def test_rollback_removes_created_services(self):
        """Should remove all created services on failure"""
        orchestrator = StackOrchestrator()

        # Simulate: db created successfully, api created, web failed
        created_services = ['db', 'api']

        rollback_ops = orchestrator.plan_rollback(created_services)

        # Should remove in reverse order
        assert len(rollback_ops) == 2
        assert rollback_ops[0]['type'] == 'remove_service'
        assert rollback_ops[0]['name'] == 'api'  # Remove api first
        assert rollback_ops[1]['type'] == 'remove_service'
        assert rollback_ops[1]['name'] == 'db'   # Then db

    def test_rollback_removes_created_networks(self):
        """Should remove created networks on rollback"""
        orchestrator = StackOrchestrator()

        created_networks = ['frontend', 'backend']
        created_services = ['web']

        rollback_ops = orchestrator.plan_rollback(
            created_services,
            created_networks=created_networks
        )

        # Should remove services first, then networks
        service_ops = [op for op in rollback_ops if op['type'] == 'remove_service']
        network_ops = [op for op in rollback_ops if op['type'] == 'remove_network']

        assert len(service_ops) == 1
        assert len(network_ops) == 2

    def test_rollback_preserves_external_networks(self):
        """Should NOT remove external networks on rollback"""
        orchestrator = StackOrchestrator()

        created_networks = []  # External networks not in created list

        rollback_ops = orchestrator.plan_rollback(
            created_services=['web'],
            created_networks=created_networks,
            external_networks=['external_net']
        )

        # Should NOT remove external networks
        network_ops = [op for op in rollback_ops if op['type'] == 'remove_network']
        assert len(network_ops) == 0


class TestStackOperations:
    """Test stack-level operations (stop_all, start_all, remove_all)"""

    def test_stop_all_services(self):
        """Should stop all services in reverse dependency order"""
        compose_data = {
            'version': '3.8',
            'services': {
                'web': {
                    'image': 'nginx:latest',
                    'depends_on': ['api']
                },
                'api': {
                    'image': 'node:latest',
                    'depends_on': ['db']
                },
                'db': {
                    'image': 'postgres:latest'
                }
            }
        }

        orchestrator = StackOrchestrator()
        stop_order = orchestrator.get_stop_order(compose_data)

        # Should stop in REVERSE dependency order (web -> api -> db)
        assert stop_order == ['web', 'api', 'db']

    def test_start_all_services(self):
        """Should start all services in dependency order"""
        compose_data = {
            'version': '3.8',
            'services': {
                'web': {
                    'image': 'nginx:latest',
                    'depends_on': ['api']
                },
                'api': {
                    'image': 'node:latest',
                    'depends_on': ['db']
                },
                'db': {
                    'image': 'postgres:latest'
                }
            }
        }

        orchestrator = StackOrchestrator()
        start_order = orchestrator.get_start_order(compose_data)

        # Should start in dependency order (db -> api -> web)
        assert start_order == ['db', 'api', 'web']

    def test_remove_all_services_and_resources(self):
        """Should remove all services, networks, and volumes"""
        compose_data = {
            'version': '3.8',
            'services': {
                'web': {'image': 'nginx:latest'}
            },
            'networks': {
                'frontend': {'driver': 'bridge'}
            },
            'volumes': {
                'data': {'driver': 'local'}
            }
        }

        orchestrator = StackOrchestrator()
        remove_ops = orchestrator.plan_stack_removal(compose_data)

        # Should remove in order: services, networks, volumes
        assert remove_ops[0]['type'] == 'remove_service'
        assert remove_ops[1]['type'] == 'remove_network'
        assert remove_ops[2]['type'] == 'remove_volume'


class TestServiceConfigMapping:
    """Test mapping compose service config to Docker container config"""

    def test_map_basic_service_config(self):
        """Should map basic service configuration"""
        service_config = {
            'image': 'nginx:latest',
            'ports': ['80:80'],
            'environment': {
                'NODE_ENV': 'production'
            }
        }

        orchestrator = StackOrchestrator()
        docker_config = orchestrator.map_service_to_container_config(
            'web',
            service_config
        )

        assert docker_config['image'] == 'nginx:latest'
        assert docker_config['ports'] == {'80/tcp': 80}
        assert docker_config['environment']['NODE_ENV'] == 'production'

    def test_map_service_with_build(self):
        """Should handle services with build context"""
        service_config = {
            'build': {
                'context': './web',
                'dockerfile': 'Dockerfile'
            },
            'ports': ['80:80']
        }

        orchestrator = StackOrchestrator()

        # Should raise error - build not supported in v2.1
        with pytest.raises(StackOrchestrationError, match="not supported"):
            orchestrator.map_service_to_container_config('web', service_config)

    def test_map_service_with_networks(self):
        """Should map service networks to Docker format"""
        service_config = {
            'image': 'nginx:latest',
            'networks': ['frontend', 'backend']
        }

        orchestrator = StackOrchestrator()
        docker_config = orchestrator.map_service_to_container_config(
            'web',
            service_config
        )

        # Should include networks in Docker format
        assert 'networking_config' in docker_config
        assert 'frontend' in docker_config['networking_config']['EndpointsConfig']
        assert 'backend' in docker_config['networking_config']['EndpointsConfig']


class TestStackMetadata:
    """Test stack metadata tracking"""

    def test_create_deployment_metadata_for_each_service(self):
        """Should create deployment_metadata for each service"""
        orchestrator = StackOrchestrator()

        services = ['web', 'api', 'db']
        container_ids = {
            'web': 'abc123456789',
            'api': 'def456789012',
            'db': 'ghi789012345'
        }

        metadata_list = orchestrator.create_stack_metadata(
            deployment_id='host123:stack456',
            host_id='host123',
            services=services,
            container_ids=container_ids
        )

        assert len(metadata_list) == 3

        # Each should have service_name populated
        web_meta = next(m for m in metadata_list if m['service_name'] == 'web')
        assert web_meta['container_id'] == 'host123:abc123456789'
        assert web_meta['deployment_id'] == 'host123:stack456'
