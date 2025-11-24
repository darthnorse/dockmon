"""
Unit tests for validation logic.

Tests both update validation and deployment validation:
- Update validator: Priority-based validation (labels, database, patterns)
- Deployment validator: Field validation (types, formats, constraints)
"""

import pytest
from unittest.mock import MagicMock
from updates.container_validator import (
    ContainerValidator as UpdateValidator,
    ValidationResult,
    ValidationResponse
)
from deployment.container_validator import (
    ContainerValidator as DeploymentValidator,
    ContainerValidationError
)
from database import UpdatePolicy, ContainerUpdate


# ============================================================================
# UPDATE VALIDATION TESTS
# ============================================================================

class TestUpdateValidatorSelfProtection:
    """Test DockMon self-update protection (Priority 0)"""

    def test_blocks_dockmon_container(self, mock_db_session):
        """Should block updates for container named 'dockmon'"""
        validator = UpdateValidator(mock_db_session)

        result = validator.validate_update(
            host_id="host-123",
            container_id="abc123def456",
            container_name="dockmon",
            image_name="dockmon:latest",
            labels={}
        )

        assert result.result == ValidationResult.BLOCK
        assert "cannot update itself" in result.reason.lower()
        assert result.matched_pattern is None

    def test_blocks_dockmon_variants(self, mock_db_session):
        """Should block updates for dockmon-* containers (dev, prod, backup)"""
        validator = UpdateValidator(mock_db_session)

        test_names = ["dockmon-dev", "dockmon-prod", "dockmon-backup-1", "dockmon-staging"]

        for name in test_names:
            result = validator.validate_update(
                host_id="host-123",
                container_id="abc123def456",
                container_name=name,
                image_name="dockmon:latest",
                labels={}
            )

            assert result.result == ValidationResult.BLOCK, f"Failed to block {name}"
            assert "cannot update itself" in result.reason.lower()

    def test_allows_non_dockmon_containers(self, mock_db_session):
        """Should allow updates for containers not named dockmon*"""
        validator = UpdateValidator(mock_db_session)

        result = validator.validate_update(
            host_id="host-123",
            container_id="abc123def456",
            container_name="mydockmonapp",  # Contains 'dockmon' but doesn't start with it
            image_name="nginx:latest",
            labels={}
        )

        # Should fall through to default ALLOW (no patterns, no labels, no DB policy)
        assert result.result == ValidationResult.ALLOW


class TestUpdateValidatorDockerLabels:
    """Test Docker label validation (Priority 1)"""

    def test_label_allow(self, mock_db_session):
        """Docker label 'allow' should take precedence"""
        validator = UpdateValidator(mock_db_session)

        result = validator.validate_update(
            host_id="host-123",
            container_id="abc123def456",
            container_name="nginx",
            image_name="nginx:latest",
            labels={"com.dockmon.update.policy": "allow"}
        )

        assert result.result == ValidationResult.ALLOW
        assert "docker label" in result.reason.lower()

    def test_label_warn(self, mock_db_session):
        """Docker label 'warn' should take precedence"""
        validator = UpdateValidator(mock_db_session)

        result = validator.validate_update(
            host_id="host-123",
            container_id="abc123def456",
            container_name="postgres",
            image_name="postgres:14",
            labels={"com.dockmon.update.policy": "warn"}
        )

        assert result.result == ValidationResult.WARN
        assert "docker label" in result.reason.lower()

    def test_label_block(self, mock_db_session):
        """Docker label 'block' should take precedence"""
        validator = UpdateValidator(mock_db_session)

        result = validator.validate_update(
            host_id="host-123",
            container_id="abc123def456",
            container_name="critical-db",
            image_name="postgres:14",
            labels={"com.dockmon.update.policy": "block"}
        )

        assert result.result == ValidationResult.BLOCK
        assert "docker label" in result.reason.lower()

    def test_label_case_insensitive(self, mock_db_session):
        """Docker label values should be case-insensitive"""
        validator = UpdateValidator(mock_db_session)

        test_cases = ["ALLOW", "Allow", "AlLoW", "WARN", "Warn", "BLOCK", "Block"]

        for label_value in test_cases:
            result = validator.validate_update(
                host_id="host-123",
                container_id="abc123def456",
                container_name="nginx",
                image_name="nginx:latest",
                labels={"com.dockmon.update.policy": label_value}
            )

            expected_result = ValidationResult(label_value.lower())
            assert result.result == expected_result


class TestUpdateValidatorDatabasePolicy:
    """Test per-container database policy (Priority 2)"""

    def test_database_policy_allow(self, mock_db_session):
        """Database policy 'allow' should be used when no label present"""
        validator = UpdateValidator(mock_db_session)

        # Mock database query
        mock_update_record = MagicMock(spec=ContainerUpdate)
        mock_update_record.update_policy = "allow"
        mock_db_session.query.return_value.filter_by.return_value.first.return_value = mock_update_record

        result = validator.validate_update(
            host_id="host-123",
            container_id="abc123def456",
            container_name="nginx",
            image_name="nginx:latest",
            labels={}  # No Docker label
        )

        assert result.result == ValidationResult.ALLOW
        assert "per-container" in result.reason.lower()

    def test_database_policy_warn(self, mock_db_session):
        """Database policy 'warn' should be used"""
        validator = UpdateValidator(mock_db_session)

        mock_update_record = MagicMock(spec=ContainerUpdate)
        mock_update_record.update_policy = "warn"
        mock_db_session.query.return_value.filter_by.return_value.first.return_value = mock_update_record

        result = validator.validate_update(
            host_id="host-123",
            container_id="abc123def456",
            container_name="nginx",
            image_name="nginx:latest",
            labels={}
        )

        assert result.result == ValidationResult.WARN
        assert "per-container" in result.reason.lower()

    def test_database_policy_block(self, mock_db_session):
        """Database policy 'block' should be used"""
        validator = UpdateValidator(mock_db_session)

        mock_update_record = MagicMock(spec=ContainerUpdate)
        mock_update_record.update_policy = "block"
        mock_db_session.query.return_value.filter_by.return_value.first.return_value = mock_update_record

        result = validator.validate_update(
            host_id="host-123",
            container_id="abc123def456",
            container_name="critical-app",
            image_name="myapp:latest",
            labels={}
        )

        assert result.result == ValidationResult.BLOCK
        assert "per-container" in result.reason.lower()

    def test_database_policy_null_skips_to_next_priority(self, mock_db_session):
        """If database policy is null, should check global patterns"""
        validator = UpdateValidator(mock_db_session)

        # Mock update record with null policy
        mock_update_record = MagicMock(spec=ContainerUpdate)
        mock_update_record.update_policy = None
        mock_db_session.query.return_value.filter_by.return_value.first.return_value = mock_update_record

        result = validator.validate_update(
            host_id="host-123",
            container_id="abc123def456",
            container_name="nginx",
            image_name="nginx:latest",
            labels={}
        )

        # Should fall through to default ALLOW (no patterns)
        assert result.result == ValidationResult.ALLOW


class TestUpdateValidatorPatternMatching:
    """Test global pattern matching (Priority 3)"""

    def test_pattern_matches_container_name(self, mock_db_session):
        """Pattern should match container name"""
        validator = UpdateValidator(mock_db_session)

        # Mock enabled pattern
        mock_pattern = MagicMock(spec=UpdatePolicy)
        mock_pattern.pattern = "postgres"
        mock_pattern.category = "database"
        mock_pattern.enabled = True

        mock_db_session.query.return_value.filter_by.return_value.first.return_value = None  # No per-container
        mock_db_session.query.return_value.filter_by.return_value.all.return_value = [mock_pattern]

        result = validator.validate_update(
            host_id="host-123",
            container_id="abc123def456",
            container_name="my-postgres-db",
            image_name="postgres:14",
            labels={}
        )

        assert result.result == ValidationResult.WARN
        assert result.matched_pattern == "postgres"
        assert "database" in result.reason.lower()

    def test_pattern_matches_image_name(self, mock_db_session):
        """Pattern should match image name"""
        validator = UpdateValidator(mock_db_session)

        # Mock enabled pattern
        mock_pattern = MagicMock(spec=UpdatePolicy)
        mock_pattern.pattern = "traefik"
        mock_pattern.category = "proxy"
        mock_pattern.enabled = True

        mock_db_session.query.return_value.filter_by.return_value.first.return_value = None
        mock_db_session.query.return_value.filter_by.return_value.all.return_value = [mock_pattern]

        result = validator.validate_update(
            host_id="host-123",
            container_id="abc123def456",
            container_name="my-reverse-proxy",
            image_name="traefik:latest",
            labels={}
        )

        assert result.result == ValidationResult.WARN
        assert result.matched_pattern == "traefik"

    def test_pattern_case_insensitive(self, mock_db_session):
        """Pattern matching should be case-insensitive"""
        validator = UpdateValidator(mock_db_session)

        mock_pattern = MagicMock(spec=UpdatePolicy)
        mock_pattern.pattern = "nginx"
        mock_pattern.category = "webserver"
        mock_pattern.enabled = True

        mock_db_session.query.return_value.filter_by.return_value.first.return_value = None
        mock_db_session.query.return_value.filter_by.return_value.all.return_value = [mock_pattern]

        result = validator.validate_update(
            host_id="host-123",
            container_id="abc123def456",
            container_name="NGINX-Production",
            image_name="NGINX:LATEST",
            labels={}
        )

        assert result.result == ValidationResult.WARN
        assert result.matched_pattern == "nginx"


class TestUpdateValidatorDefaultBehavior:
    """Test default behavior (Priority 4)"""

    def test_default_allow(self, mock_db_session):
        """Should default to ALLOW when no restrictions found"""
        validator = UpdateValidator(mock_db_session)

        # Mock empty database queries
        mock_db_session.query.return_value.filter_by.return_value.first.return_value = None  # No per-container
        mock_db_session.query.return_value.filter_by.return_value.all.return_value = []  # No patterns

        result = validator.validate_update(
            host_id="host-123",
            container_id="abc123def456",
            container_name="simple-app",
            image_name="myapp:latest",
            labels={}
        )

        assert result.result == ValidationResult.ALLOW
        assert "no restrictions" in result.reason.lower()
        assert result.matched_pattern is None


# ============================================================================
# DEPLOYMENT VALIDATION TESTS
# ============================================================================

class TestDeploymentValidatorRequiredFields:
    """Test required field validation"""

    def test_missing_image_field_raises_error(self):
        """Should raise error when 'image' field is missing"""
        validator = DeploymentValidator()

        definition = {
            "name": "test-container",
            "environment": {"KEY": "value"}
        }

        with pytest.raises(ContainerValidationError, match="Missing required field: 'image'"):
            validator.validate_definition(definition)

    def test_empty_image_raises_error(self):
        """Should raise error when 'image' is empty string"""
        validator = DeploymentValidator()

        definition = {
            "image": "   ",  # Whitespace only
            "name": "test-container"
        }

        with pytest.raises(ContainerValidationError, match="must be a non-empty string"):
            validator.validate_definition(definition)

    def test_valid_minimal_definition(self):
        """Should accept definition with only required fields"""
        validator = DeploymentValidator()

        definition = {
            "image": "nginx:latest"
        }

        # Should not raise
        validator.validate_definition(definition)


class TestDeploymentValidatorFieldTypes:
    """Test field type validation"""

    def test_string_fields_must_be_strings(self):
        """String fields must be strings, not other types"""
        validator = DeploymentValidator()

        # Test 'name' field with wrong type
        definition = {
            "image": "nginx:latest",
            "name": 123  # Should be string
        }

        with pytest.raises(ContainerValidationError, match="Field 'name' must be a string"):
            validator.validate_definition(definition)

    def test_boolean_fields_must_be_booleans(self):
        """Boolean fields must be booleans, not strings"""
        validator = DeploymentValidator()

        definition = {
            "image": "nginx:latest",
            "privileged": "true"  # Should be boolean
        }

        with pytest.raises(ContainerValidationError, match="Field 'privileged' must be a boolean"):
            validator.validate_definition(definition)

    def test_dict_fields_must_be_dicts(self):
        """Dictionary fields must be dicts with string keys/values"""
        validator = DeploymentValidator()

        definition = {
            "image": "nginx:latest",
            "environment": ["KEY=value"]  # Should be dict
        }

        with pytest.raises(ContainerValidationError, match="Field 'environment' must be a dict"):
            validator.validate_definition(definition)

    def test_dict_fields_must_have_string_values(self):
        """Dict fields must have string keys and values"""
        validator = DeploymentValidator()

        definition = {
            "image": "nginx:latest",
            "environment": {"PORT": 8080}  # Value should be string
        }

        with pytest.raises(ContainerValidationError, match="all values must be strings"):
            validator.validate_definition(definition)

    def test_list_fields_must_be_lists(self):
        """List fields must be lists"""
        validator = DeploymentValidator()

        definition = {
            "image": "nginx:latest",
            "ports": "80:80"  # Should be list
        }

        with pytest.raises(ContainerValidationError, match="Field 'ports' must be a list"):
            validator.validate_definition(definition)


class TestDeploymentValidatorPorts:
    """Test port validation"""

    def test_valid_port_formats(self):
        """Should accept valid port formats"""
        validator = DeploymentValidator()

        valid_ports = [
            ["80"],  # Container port only
            ["8080:80"],  # Host:container
            ["127.0.0.1:8080:80"]  # IP:host:container
        ]

        for ports in valid_ports:
            definition = {
                "image": "nginx:latest",
                "ports": ports
            }
            validator.validate_definition(definition)

    def test_invalid_port_range(self):
        """Should reject ports outside valid range (1-65535)"""
        validator = DeploymentValidator()

        definition = {
            "image": "nginx:latest",
            "ports": ["99999:80"]  # Port too high
        }

        with pytest.raises(ContainerValidationError, match="ports must be 1-65535"):
            validator.validate_definition(definition)

    def test_non_numeric_ports(self):
        """Should reject non-numeric port values"""
        validator = DeploymentValidator()

        definition = {
            "image": "nginx:latest",
            "ports": ["abc:80"]
        }

        with pytest.raises(ContainerValidationError, match="ports must be numbers"):
            validator.validate_definition(definition)


class TestDeploymentValidatorVolumes:
    """Test volume validation"""

    def test_valid_volume_formats(self):
        """Should accept valid volume formats"""
        validator = DeploymentValidator()

        valid_volumes = [
            ["/host/path:/container/path"],  # Read-write (default)
            ["/host/path:/container/path:ro"],  # Read-only
            ["/host/path:/container/path:rw"]  # Read-write (explicit)
        ]

        for volumes in valid_volumes:
            definition = {
                "image": "nginx:latest",
                "volumes": volumes
            }
            validator.validate_definition(definition)

    def test_invalid_volume_format(self):
        """Should reject volumes without proper format"""
        validator = DeploymentValidator()

        definition = {
            "image": "nginx:latest",
            "volumes": ["/single/path"]  # Missing destination
        }

        with pytest.raises(ContainerValidationError, match="expected 'source:dest'"):
            validator.validate_definition(definition)

    def test_invalid_volume_mode(self):
        """Should reject invalid volume modes"""
        validator = DeploymentValidator()

        definition = {
            "image": "nginx:latest",
            "volumes": ["/host:/container:invalid"]  # Invalid mode
        }

        with pytest.raises(ContainerValidationError, match="must be 'ro' or 'rw'"):
            validator.validate_definition(definition)


class TestDeploymentValidatorRestartPolicy:
    """Test restart policy validation"""

    def test_valid_restart_policies(self):
        """Should accept valid restart policies"""
        validator = DeploymentValidator()

        valid_policies = ["no", "always", "unless-stopped", "on-failure"]

        for policy in valid_policies:
            definition = {
                "image": "nginx:latest",
                "restart_policy": policy
            }
            validator.validate_definition(definition)

    def test_invalid_restart_policy(self):
        """Should reject invalid restart policies"""
        validator = DeploymentValidator()

        definition = {
            "image": "nginx:latest",
            "restart_policy": "sometimes"  # Invalid
        }

        with pytest.raises(ContainerValidationError, match="Invalid restart policy"):
            validator.validate_definition(definition)


class TestDeploymentValidatorResourceLimits:
    """Test CPU and memory limit validation"""

    def test_valid_cpu_limits(self):
        """Should accept valid CPU limit values"""
        validator = DeploymentValidator()

        valid_cpu_values = ["0.5", "1.0", "2", "4.5"]

        for cpu in valid_cpu_values:
            definition = {
                "image": "nginx:latest",
                "cpu_limit": cpu
            }
            validator.validate_definition(definition)

    def test_negative_cpu_limit(self):
        """Should reject negative CPU limits"""
        validator = DeploymentValidator()

        definition = {
            "image": "nginx:latest",
            "cpu_limit": "-1"
        }

        with pytest.raises(ContainerValidationError, match="CPU limit must be positive"):
            validator.validate_definition(definition)

    def test_excessive_cpu_limit(self):
        """Should warn about excessively high CPU limits"""
        validator = DeploymentValidator()

        definition = {
            "image": "nginx:latest",
            "cpu_limit": "100"  # 100 CPUs seems excessive
        }

        with pytest.raises(ContainerValidationError, match="seems too high"):
            validator.validate_definition(definition)

    def test_valid_memory_formats(self):
        """Should accept valid memory format strings"""
        validator = DeploymentValidator()

        valid_memory_values = ["512m", "1g", "2048m", "1024", "1.5g"]

        for mem in valid_memory_values:
            definition = {
                "image": "nginx:latest",
                "mem_limit": mem
            }
            validator.validate_definition(definition)

    def test_memory_limit_as_bytes(self):
        """Should accept memory limit as integer bytes"""
        validator = DeploymentValidator()

        definition = {
            "image": "nginx:latest",
            "mem_limit": 536870912  # 512MB in bytes
        }

        validator.validate_definition(definition)

    def test_negative_memory_limit(self):
        """Should reject negative memory limits"""
        validator = DeploymentValidator()

        definition = {
            "image": "nginx:latest",
            "mem_limit": -1024
        }

        with pytest.raises(ContainerValidationError, match="Memory limit must be positive"):
            validator.validate_definition(definition)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_db_session():
    """Mock SQLAlchemy database session"""
    session = MagicMock()

    # Default: return None for queries (no records found)
    session.query.return_value.filter_by.return_value.first.return_value = None
    session.query.return_value.filter_by.return_value.all.return_value = []

    return session
