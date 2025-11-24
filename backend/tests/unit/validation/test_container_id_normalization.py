"""
Unit tests for container ID normalization and composite key management.

Tests verify:
- normalize_container_id() - Defensive normalization (accepts 12 or 64 char)
- make_composite_key() - Strict validation (requires 12 char)
- parse_composite_key() - Parsing and validation

These tests protect against the recurring bug pattern where container ID format
mismatches cause database orphaning, API 500 errors, and frontend crashes.

Related Issues:
- Container ID format standardization (v2.0+)
- Defense-in-depth normalization pattern (v2.2.0+)
"""

import pytest
from utils.container_id import normalize_container_id
from utils.keys import make_composite_key, parse_composite_key


class TestNormalizeContainerId:
    """Test defensive container ID normalization"""

    def test_normalize_short_id_unchanged(self):
        """
        12-char short ID should pass through unchanged.

        Scenario:
        - Frontend sends short ID (from /containers endpoint)
        - Should return same ID
        """
        short_id = "abc123def456"

        result = normalize_container_id(short_id)

        assert result == "abc123def456"
        assert len(result) == 12

    def test_normalize_long_id_truncated(self):
        """
        64-char full ID should be truncated to 12 chars.

        Scenario:
        - Frontend sends full ID (from WebSocket or Docker inspect)
        - Should truncate to first 12 chars
        """
        full_id = "abc123def456" + "0" * 52  # 64 chars total

        result = normalize_container_id(full_id)

        assert result == "abc123def456"
        assert len(result) == 12

    def test_normalize_real_docker_id(self):
        """
        Real Docker container ID should truncate correctly.

        Uses actual Docker ID format from production.
        """
        docker_id = "67c5d214133846c397f4d9947f28cb513377db1fcc74633efd0d13793c45d4f2"

        result = normalize_container_id(docker_id)

        assert result == "67c5d2141338"
        assert len(result) == 12

    def test_normalize_preserves_hexadecimal_chars(self):
        """
        Should preserve all hexadecimal characters correctly.

        Docker IDs use hex characters (0-9, a-f).
        """
        test_id = "abcdef012345"

        result = normalize_container_id(test_id)

        assert result == "abcdef012345"

    def test_normalize_empty_string(self):
        """
        Empty string should return empty string (not error).

        Defensive: Let calling code handle validation.
        """
        result = normalize_container_id("")

        assert result == ""

    def test_normalize_very_short_id(self):
        """
        ID shorter than 12 chars should return as-is.

        Defensive: Don't pad or error, just truncate.
        """
        short_id = "abc123"  # 6 chars

        result = normalize_container_id(short_id)

        assert result == "abc123"
        assert len(result) == 6

    def test_normalize_exactly_12_chars(self):
        """
        Boundary test: Exactly 12 chars should pass through.
        """
        id_12 = "0" * 12

        result = normalize_container_id(id_12)

        assert result == id_12
        assert len(result) == 12

    def test_normalize_idempotent(self):
        """
        Normalizing twice should give same result (idempotent).

        Critical for defensive programming.
        """
        docker_id = "abc123def456789012345678901234567890123456789012345678901234"

        result1 = normalize_container_id(docker_id)
        result2 = normalize_container_id(result1)

        assert result1 == result2
        assert result1 == "abc123def456"


class TestMakeCompositeKey:
    """Test composite key creation with strict validation"""

    def test_make_composite_key_success(self):
        """
        Valid host_id + container_id should create proper composite key.

        Format: {host_id}:{container_id}
        """
        host_id = "7be442c9-24bc-4047-b33a-41bbf51ea2f9"
        container_id = "67c5d2141338"

        result = make_composite_key(host_id, container_id)

        assert result == "7be442c9-24bc-4047-b33a-41bbf51ea2f9:67c5d2141338"
        assert ":" in result

    def test_make_composite_key_format_separator(self):
        """
        Composite key should use colon separator.
        """
        host_id = "test-host"
        container_id = "abc123def456"

        result = make_composite_key(host_id, container_id)

        assert result == "test-host:abc123def456"
        parts = result.split(":")
        assert len(parts) == 2
        assert parts[0] == "test-host"
        assert parts[1] == "abc123def456"

    def test_make_composite_key_empty_host_id_raises(self):
        """
        Empty host_id should raise ValueError.

        Strict validation prevents invalid keys.
        """
        with pytest.raises(ValueError, match="host_id cannot be empty"):
            make_composite_key("", "abc123def456")

    def test_make_composite_key_empty_container_id_raises(self):
        """
        Empty container_id should raise ValueError.
        """
        with pytest.raises(ValueError, match="container_id cannot be empty"):
            make_composite_key("test-host", "")

    def test_make_composite_key_long_container_id_raises(self):
        """
        Container ID longer than 12 chars should raise ValueError.

        CRITICAL: Prevents 64-char IDs from polluting database.
        This is strict validation - caller must normalize first.
        """
        host_id = "test-host"
        long_id = "abc123def456" + "0" * 52  # 64 chars

        with pytest.raises(ValueError, match="container_id must be 12 characters"):
            make_composite_key(host_id, long_id)

    def test_make_composite_key_short_container_id_raises(self):
        """
        Container ID shorter than 12 chars should raise ValueError.
        """
        host_id = "test-host"
        short_id = "abc123"  # 6 chars

        with pytest.raises(ValueError, match="container_id must be 12 characters"):
            make_composite_key(host_id, short_id)

    def test_make_composite_key_exactly_12_chars_success(self):
        """
        Boundary test: Exactly 12 chars should succeed.
        """
        host_id = "test-host"
        container_id = "0" * 12

        result = make_composite_key(host_id, container_id)

        assert result == "test-host:000000000000"

    def test_make_composite_key_with_uuid_host(self):
        """
        Full UUID host_id should work correctly.

        Real-world scenario: Production hosts use UUIDs.
        """
        host_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        container_id = "abc123def456"

        result = make_composite_key(host_id, container_id)

        assert result == "a1b2c3d4-e5f6-7890-abcd-ef1234567890:abc123def456"


class TestParseCompositeKey:
    """Test composite key parsing and validation"""

    def test_parse_composite_key_success(self):
        """
        Valid composite key should parse into (host_id, container_id).
        """
        composite_key = "test-host:abc123def456"

        host_id, container_id = parse_composite_key(composite_key)

        assert host_id == "test-host"
        assert container_id == "abc123def456"

    def test_parse_composite_key_with_uuid(self):
        """
        Composite key with UUID host should parse correctly.
        """
        composite_key = "7be442c9-24bc-4047-b33a-41bbf51ea2f9:67c5d2141338"

        host_id, container_id = parse_composite_key(composite_key)

        assert host_id == "7be442c9-24bc-4047-b33a-41bbf51ea2f9"
        assert container_id == "67c5d2141338"

    def test_parse_composite_key_empty_raises(self):
        """
        Empty composite key should raise ValueError.
        """
        with pytest.raises(ValueError, match="composite_key cannot be empty"):
            parse_composite_key("")

    def test_parse_composite_key_no_separator_raises(self):
        """
        Composite key without colon separator should raise ValueError.
        """
        with pytest.raises(ValueError, match="Invalid composite key format"):
            parse_composite_key("test-host-abc123def456")

    def test_parse_composite_key_empty_host_raises(self):
        """
        Composite key with empty host part should raise ValueError.

        Example: ":abc123def456"
        """
        with pytest.raises(ValueError, match="host_id part is empty"):
            parse_composite_key(":abc123def456")

    def test_parse_composite_key_empty_container_raises(self):
        """
        Composite key with empty container part should raise ValueError.

        Example: "test-host:"
        """
        with pytest.raises(ValueError, match="container_id part is empty"):
            parse_composite_key("test-host:")

    def test_parse_composite_key_wrong_container_length_raises(self):
        """
        Container ID not exactly 12 chars should raise ValueError.

        Prevents corrupted keys from propagating.
        """
        # Too long
        with pytest.raises(ValueError, match="container_id must be 12 characters"):
            parse_composite_key("test-host:abc123def4567890")

        # Too short
        with pytest.raises(ValueError, match="container_id must be 12 characters"):
            parse_composite_key("test-host:abc123")

    def test_parse_composite_key_multiple_colons(self):
        """
        Composite key with multiple colons should raise ValueError.

        Since we split on first colon, "a:b:c:abc123" becomes:
        - host_id = "a"
        - container_id = "b:c:abc123" (16 chars, invalid!)

        This is expected behavior - composite keys should not have
        extra colons.
        """
        # Multiple colons create invalid container_id part
        composite_key = "a:b:c:abc123def456"

        # Should raise because "b:c:abc123def456" is not 12 chars
        with pytest.raises(ValueError, match="container_id must be 12 characters"):
            parse_composite_key(composite_key)

    def test_parse_composite_key_round_trip(self):
        """
        make_composite_key() → parse_composite_key() should be invertible.

        Critical: Ensures data integrity in database operations.
        """
        original_host = "test-host-uuid"
        original_container = "abc123def456"

        # Create composite key
        composite_key = make_composite_key(original_host, original_container)

        # Parse it back
        parsed_host, parsed_container = parse_composite_key(composite_key)

        # Should match original
        assert parsed_host == original_host
        assert parsed_container == original_container


class TestIntegrationScenarios:
    """Test real-world integration scenarios"""

    def test_frontend_to_backend_defensive_pattern(self):
        """
        Test the defensive pattern: normalize before make_composite_key.

        Real-world flow:
        1. Frontend sends 64-char ID (from WebSocket)
        2. Backend normalizes at endpoint boundary
        3. Backend creates composite key for database
        """
        # Frontend sends full ID
        frontend_id = "67c5d214133846c397f4d9947f28cb513377db1fcc74633efd0d13793c45d4f2"
        host_id = "test-host"

        # Backend normalizes defensively
        normalized_id = normalize_container_id(frontend_id)

        # Create composite key with normalized ID
        composite_key = make_composite_key(host_id, normalized_id)

        # Should succeed
        assert composite_key == "test-host:67c5d2141338"

    def test_database_consistency_scenario(self):
        """
        Test scenario where database stores composite keys.

        Flow:
        1. Store composite key in database
        2. Retrieve composite key from database
        3. Parse to get host_id and container_id
        4. Use for Docker operations
        """
        # Store in database
        host_id = "7be442c9-24bc-4047-b33a-41bbf51ea2f9"
        container_id = "abc123def456"
        stored_key = make_composite_key(host_id, container_id)

        # Later: Retrieve from database and parse
        retrieved_host, retrieved_container = parse_composite_key(stored_key)

        # Should match original values
        assert retrieved_host == host_id
        assert retrieved_container == container_id

    def test_multi_host_collision_prevention(self):
        """
        Test that composite keys prevent container ID collisions across hosts.

        Scenario:
        - VM cloned → same container IDs on different hosts
        - Composite keys keep them separate
        """
        container_id = "abc123def456"

        # Same container ID on two different hosts
        host1_key = make_composite_key("host-1", container_id)
        host2_key = make_composite_key("host-2", container_id)

        # Keys should be different
        assert host1_key != host2_key
        assert host1_key == "host-1:abc123def456"
        assert host2_key == "host-2:abc123def456"

    def test_normalize_then_validate_pattern(self):
        """
        Test the recommended pattern: normalize → validate → use.

        This pattern is used at API endpoint boundaries.
        """
        # Input could be 12 or 64 chars
        user_input = "abc123def456789012345678901234567890123456789012345678901234"

        # Step 1: Normalize (defensive)
        normalized = normalize_container_id(user_input)
        assert len(normalized) == 12

        # Step 2: Validate (strict) - via make_composite_key
        composite_key = make_composite_key("test-host", normalized)

        # Step 3: Use
        assert composite_key == "test-host:abc123def456"
