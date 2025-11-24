"""
Unit tests for Docker duration parser.

Tests the conversion of Docker Compose time strings to nanoseconds.
"""

import pytest
from utils.duration_parser import parse_docker_duration


class TestBasicDurations:
    """Test basic single-unit durations"""

    def test_parse_seconds(self):
        """Test seconds parsing"""
        assert parse_docker_duration("30s") == 30_000_000_000

    def test_parse_minutes(self):
        """Test minutes parsing"""
        assert parse_docker_duration("5m") == 300_000_000_000

    def test_parse_hours(self):
        """Test hours parsing"""
        assert parse_docker_duration("2h") == 7_200_000_000_000

    def test_parse_milliseconds(self):
        """Test milliseconds parsing"""
        assert parse_docker_duration("500ms") == 500_000_000

    def test_parse_microseconds(self):
        """Test microseconds parsing"""
        assert parse_docker_duration("1000us") == 1_000_000

    def test_parse_nanoseconds(self):
        """Test nanoseconds parsing"""
        assert parse_docker_duration("1000000ns") == 1_000_000


class TestCompoundDurations:
    """Test compound durations with multiple units"""

    def test_parse_minutes_and_seconds(self):
        """Test 1m30s format"""
        assert parse_docker_duration("1m30s") == 90_000_000_000

    def test_parse_hours_and_minutes(self):
        """Test 1h30m format"""
        assert parse_docker_duration("1h30m") == 5_400_000_000_000

    def test_parse_hours_minutes_seconds(self):
        """Test 1h30m45s format"""
        assert parse_docker_duration("1h30m45s") == 5_445_000_000_000

    def test_parse_complex_compound(self):
        """Test multiple units in any order"""
        assert parse_docker_duration("2h15m30s") == 8_130_000_000_000


class TestDecimalValues:
    """Test decimal/float duration values"""

    def test_parse_decimal_seconds(self):
        """Test 1.5s format"""
        assert parse_docker_duration("1.5s") == 1_500_000_000

    def test_parse_decimal_minutes(self):
        """Test 2.5m format"""
        assert parse_docker_duration("2.5m") == 150_000_000_000

    def test_parse_fractional_milliseconds(self):
        """Test 100.5ms format"""
        assert parse_docker_duration("100.5ms") == 100_500_000


class TestEdgeCases:
    """Test edge cases and special values"""

    def test_parse_none_returns_zero(self):
        """Test None input returns 0"""
        assert parse_docker_duration(None) == 0

    def test_parse_empty_string_returns_zero(self):
        """Test empty string returns 0"""
        assert parse_docker_duration("") == 0

    def test_parse_whitespace_returns_zero(self):
        """Test whitespace-only string returns 0"""
        assert parse_docker_duration("   ") == 0

    def test_parse_zero_seconds(self):
        """Test 0s returns 0"""
        assert parse_docker_duration("0s") == 0

    def test_parse_integer_passthrough(self):
        """Test integer (already nanoseconds) passes through"""
        assert parse_docker_duration(30_000_000_000) == 30_000_000_000

    def test_parse_zero_integer_passthrough(self):
        """Test 0 integer passes through"""
        assert parse_docker_duration(0) == 0


class TestInvalidFormats:
    """Test error handling for invalid duration formats"""

    def test_parse_no_unit_raises_error(self):
        """Test number without unit raises ValueError"""
        with pytest.raises(ValueError, match="Invalid duration format"):
            parse_docker_duration("30")

    def test_parse_invalid_unit_raises_error(self):
        """Test invalid unit raises ValueError"""
        with pytest.raises(ValueError, match="Invalid duration format"):
            parse_docker_duration("30x")

    def test_parse_text_only_raises_error(self):
        """Test text without number raises ValueError"""
        with pytest.raises(ValueError, match="Invalid duration format"):
            parse_docker_duration("seconds")


class TestRealWorldExamples:
    """Test real-world Docker Compose healthcheck values"""

    def test_typical_healthcheck_interval(self):
        """Test typical 30s interval"""
        assert parse_docker_duration("30s") == 30_000_000_000

    def test_typical_healthcheck_timeout(self):
        """Test typical 10s timeout"""
        assert parse_docker_duration("10s") == 10_000_000_000

    def test_typical_start_period(self):
        """Test typical 40s start period"""
        assert parse_docker_duration("40s") == 40_000_000_000

    def test_fast_healthcheck(self):
        """Test fast healthcheck (5s interval)"""
        assert parse_docker_duration("5s") == 5_000_000_000

    def test_slow_healthcheck(self):
        """Test slow healthcheck (5m interval)"""
        assert parse_docker_duration("5m") == 300_000_000_000

    def test_very_long_start_period(self):
        """Test long start period for slow-starting apps (2m)"""
        assert parse_docker_duration("2m") == 120_000_000_000
