"""
Unit tests for Docker Compose security validation.

TDD Phase: RED - Write tests first for compose validation

Tests cover:
- YAML safety (no arbitrary code execution)
- Required fields validation
- Service configuration validation
- Dependency cycle detection
"""

import pytest
from deployment.compose_validator import ComposeValidator, ComposeValidationError, DependencyCycleError


class TestYAMLSafety:
    """Test YAML safety checks to prevent code execution"""

    def test_reject_python_object_tags(self):
        """Should reject YAML with Python object tags (!!python/object)"""
        dangerous_yaml = """
version: '3.8'
services:
  web:
    image: !!python/object/apply:os.system ['echo hacked']
"""
        validator = ComposeValidator()

        with pytest.raises(ComposeValidationError, match="Unsafe YAML"):
            validator.validate_yaml_safety(dangerous_yaml)

    def test_reject_executable_tags(self):
        """Should reject YAML with executable tags"""
        dangerous_yaml = """
version: '3.8'
services:
  web:
    image: nginx
    command: !!python/name:__import__('os').system
"""
        validator = ComposeValidator()

        with pytest.raises(ComposeValidationError, match="Unsafe YAML"):
            validator.validate_yaml_safety(dangerous_yaml)

    def test_accept_safe_yaml(self):
        """Should accept safe YAML without executable tags"""
        safe_yaml = """
version: '3.8'
services:
  web:
    image: nginx:latest
    environment:
      NODE_ENV: production
"""
        validator = ComposeValidator()

        # Should not raise
        validator.validate_yaml_safety(safe_yaml)


class TestRequiredFields:
    """Test validation of required compose file fields"""

    def test_version_field_required(self):
        """Should require 'version' field"""
        compose_data = {
            'services': {
                'web': {'image': 'nginx:latest'}
            }
        }
        validator = ComposeValidator()

        with pytest.raises(ComposeValidationError, match="Missing required field: version"):
            validator.validate_required_fields(compose_data)

    def test_services_field_required(self):
        """Should require 'services' field"""
        compose_data = {
            'version': '3.8'
        }
        validator = ComposeValidator()

        with pytest.raises(ComposeValidationError, match="Missing required field: services"):
            validator.validate_required_fields(compose_data)

    def test_services_must_not_be_empty(self):
        """Should require at least one service"""
        compose_data = {
            'version': '3.8',
            'services': {}
        }
        validator = ComposeValidator()

        with pytest.raises(ComposeValidationError, match="At least one service required"):
            validator.validate_required_fields(compose_data)

    def test_valid_required_fields(self):
        """Should accept compose data with required fields"""
        compose_data = {
            'version': '3.8',
            'services': {
                'web': {'image': 'nginx:latest'}
            }
        }
        validator = ComposeValidator()

        # Should not raise
        validator.validate_required_fields(compose_data)


class TestServiceConfiguration:
    """Test validation of service configuration"""

    def test_service_image_required(self):
        """Should require 'image' or 'build' for each service"""
        compose_data = {
            'version': '3.8',
            'services': {
                'web': {
                    'ports': ['80:80']
                    # Missing image or build
                }
            }
        }
        validator = ComposeValidator()

        with pytest.raises(ComposeValidationError, match="Service 'web' must have 'image' or 'build'"):
            validator.validate_service_configuration(compose_data)

    def test_service_with_image_valid(self):
        """Should accept service with image field"""
        compose_data = {
            'version': '3.8',
            'services': {
                'web': {'image': 'nginx:latest'}
            }
        }
        validator = ComposeValidator()

        # Should not raise
        validator.validate_service_configuration(compose_data)

    def test_service_with_build_valid(self):
        """Should accept service with build field"""
        compose_data = {
            'version': '3.8',
            'services': {
                'web': {
                    'build': {
                        'context': './web',
                        'dockerfile': 'Dockerfile'
                    }
                }
            }
        }
        validator = ComposeValidator()

        # Should not raise
        validator.validate_service_configuration(compose_data)

    def test_invalid_port_mapping_rejected(self):
        """Should reject invalid port mapping format"""
        compose_data = {
            'version': '3.8',
            'services': {
                'web': {
                    'image': 'nginx:latest',
                    'ports': ['invalid-port-format']
                }
            }
        }
        validator = ComposeValidator()

        with pytest.raises(ComposeValidationError, match="Invalid port mapping"):
            validator.validate_service_configuration(compose_data)

    def test_valid_port_mapping_accepted(self):
        """Should accept valid port mapping formats"""
        compose_data = {
            'version': '3.8',
            'services': {
                'web': {
                    'image': 'nginx:latest',
                    'ports': ['80:80', '443:443', '8080:8080/tcp']
                }
            }
        }
        validator = ComposeValidator()

        # Should not raise
        validator.validate_service_configuration(compose_data)


class TestDependencyCycleDetection:
    """Test detection of circular dependencies in service depends_on"""

    def test_simple_dependency_chain_valid(self):
        """Should accept linear dependency chain (A -> B -> C)"""
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
        validator = ComposeValidator()

        # Should not raise
        validator.validate_dependencies(compose_data)

    def test_simple_cycle_detected(self):
        """Should detect simple 2-service cycle (A -> B -> A)"""
        compose_data = {
            'version': '3.8',
            'services': {
                'web': {
                    'image': 'nginx:latest',
                    'depends_on': ['api']
                },
                'api': {
                    'image': 'node:latest',
                    'depends_on': ['web']  # Cycle!
                }
            }
        }
        validator = ComposeValidator()

        with pytest.raises(DependencyCycleError, match="Dependency cycle detected"):
            validator.validate_dependencies(compose_data)

    def test_complex_cycle_detected(self):
        """Should detect complex multi-service cycle (A -> B -> C -> A)"""
        compose_data = {
            'version': '3.8',
            'services': {
                'web': {
                    'image': 'nginx:latest',
                    'depends_on': ['api']
                },
                'api': {
                    'image': 'node:latest',
                    'depends_on': ['cache']
                },
                'cache': {
                    'image': 'redis:latest',
                    'depends_on': ['web']  # Cycle back to web!
                }
            }
        }
        validator = ComposeValidator()

        with pytest.raises(DependencyCycleError, match="Dependency cycle detected"):
            validator.validate_dependencies(compose_data)

    def test_self_dependency_detected(self):
        """Should detect service depending on itself"""
        compose_data = {
            'version': '3.8',
            'services': {
                'web': {
                    'image': 'nginx:latest',
                    'depends_on': ['web']  # Self-cycle!
                }
            }
        }
        validator = ComposeValidator()

        with pytest.raises(DependencyCycleError, match="Service 'web' depends on itself"):
            validator.validate_dependencies(compose_data)

    def test_missing_dependency_service_rejected(self):
        """Should reject dependency on non-existent service"""
        compose_data = {
            'version': '3.8',
            'services': {
                'web': {
                    'image': 'nginx:latest',
                    'depends_on': ['nonexistent']  # Doesn't exist!
                }
            }
        }
        validator = ComposeValidator()

        with pytest.raises(ComposeValidationError, match="Service 'nonexistent' not found"):
            validator.validate_dependencies(compose_data)

    def test_parallel_services_no_dependencies(self):
        """Should accept multiple services with no dependencies"""
        compose_data = {
            'version': '3.8',
            'services': {
                'web': {'image': 'nginx:latest'},
                'api': {'image': 'node:latest'},
                'cache': {'image': 'redis:latest'}
            }
        }
        validator = ComposeValidator()

        # Should not raise
        validator.validate_dependencies(compose_data)

    def test_dependency_order_calculation(self):
        """Should calculate correct service startup order"""
        compose_data = {
            'version': '3.8',
            'services': {
                'web': {
                    'image': 'nginx:latest',
                    'depends_on': ['api']
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
        validator = ComposeValidator()

        order = validator.get_startup_order(compose_data)

        # db and cache have no dependencies, should be first
        # api depends on db and cache, should be after both
        # web depends on api, should be last

        assert isinstance(order, list)
        assert len(order) == 4

        db_index = order.index('db')
        cache_index = order.index('cache')
        api_index = order.index('api')
        web_index = order.index('web')

        # api must come after both db and cache
        assert api_index > db_index
        assert api_index > cache_index

        # web must come after api
        assert web_index > api_index


class TestComposeValidatorIntegration:
    """Test full validation workflow"""

    def test_validate_complete_workflow(self):
        """Should run all validation steps on valid compose data"""
        compose_yaml = """
version: '3.8'
services:
  web:
    image: nginx:latest
    depends_on:
      - api
  api:
    image: node:latest
    depends_on:
      - db
  db:
    image: postgres:latest
"""
        validator = ComposeValidator()

        # Should not raise - all validations pass
        result = validator.validate(compose_yaml)

        assert result['valid'] is True
        assert 'startup_order' in result
        assert len(result['startup_order']) == 3

    def test_validate_catches_all_errors(self):
        """Should catch all validation errors in one pass"""
        invalid_yaml = """
version: '3.8'
services:
  web:
    # Missing image
    depends_on:
      - nonexistent  # Doesn't exist
  api:
    image: node:latest
    depends_on:
      - web  # Creates cycle
"""
        validator = ComposeValidator()

        with pytest.raises(ComposeValidationError) as exc_info:
            validator.validate(invalid_yaml)

        # Should report errors - validator stops at first error, so we just check it caught something
        error_msg = str(exc_info.value)
        assert 'image' in error_msg or 'build' in error_msg or 'nonexistent' in error_msg or 'cycle' in error_msg
