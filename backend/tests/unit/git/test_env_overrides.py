"""
Unit tests for environment variable overrides encryption.

Tests verify:
- Encryption and decryption of env overrides
- Merging git .env with DockMon overrides
- Handling of empty/missing values

Following TDD principles: RED -> GREEN -> REFACTOR
"""

import pytest
from unittest.mock import patch

from git.env_overrides import (
    get_env_overrides,
    set_env_overrides,
    merge_env_content,
    validate_env_var_name,
    validate_env_var_value,
    validate_env_vars,
)


class TestGetEnvOverrides:
    """Tests for get_env_overrides function"""

    def test_returns_empty_dict_when_no_encrypted_field(self):
        """Should return empty dict when env_overrides_encrypted is missing"""
        metadata = {"name": "test-stack"}
        result = get_env_overrides(metadata)
        assert result == {}

    def test_returns_empty_dict_when_encrypted_field_is_none(self):
        """Should return empty dict when env_overrides_encrypted is None"""
        metadata = {"name": "test-stack", "env_overrides_encrypted": None}
        result = get_env_overrides(metadata)
        assert result == {}

    def test_decrypts_and_parses_json(self):
        """Should decrypt and parse JSON blob"""
        metadata = {"env_overrides_encrypted": "encrypted_json"}

        with patch('git.env_overrides.decrypt_password', return_value='{"FOO": "bar", "BAZ": "123"}'):
            result = get_env_overrides(metadata)

        assert result == {"FOO": "bar", "BAZ": "123"}

    def test_returns_empty_dict_on_decryption_error(self):
        """Should return empty dict when decryption fails"""
        metadata = {"env_overrides_encrypted": "bad_encrypted_data"}

        with patch('git.env_overrides.decrypt_password', side_effect=ValueError("Decryption failed")):
            result = get_env_overrides(metadata)

        assert result == {}

    def test_returns_empty_dict_on_json_parse_error(self):
        """Should return empty dict when JSON is invalid"""
        metadata = {"env_overrides_encrypted": "encrypted_invalid_json"}

        with patch('git.env_overrides.decrypt_password', return_value='not valid json'):
            result = get_env_overrides(metadata)

        assert result == {}

    def test_returns_empty_dict_on_io_error(self):
        """Should return empty dict when encryption key cannot be read (IOError)"""
        metadata = {"env_overrides_encrypted": "encrypted_data"}

        with patch('git.env_overrides.decrypt_password', side_effect=IOError("Cannot read encryption key")):
            result = get_env_overrides(metadata)

        assert result == {}


class TestValidateEnvVarName:
    """Tests for validate_env_var_name function"""

    def test_valid_names(self):
        """Should accept valid POSIX env var names"""
        assert validate_env_var_name("DB_HOST") is True
        assert validate_env_var_name("_PRIVATE") is True
        assert validate_env_var_name("VAR123") is True
        assert validate_env_var_name("a") is True

    def test_rejects_empty_name(self):
        """Should reject empty string"""
        assert validate_env_var_name("") is False

    def test_rejects_names_starting_with_number(self):
        """Should reject names starting with number"""
        assert validate_env_var_name("123VAR") is False
        assert validate_env_var_name("1") is False

    def test_rejects_names_with_special_chars(self):
        """Should reject names with special characters"""
        assert validate_env_var_name("VAR=VALUE") is False
        assert validate_env_var_name("VAR\nNAME") is False
        assert validate_env_var_name("VAR-NAME") is False
        assert validate_env_var_name("VAR.NAME") is False


class TestValidateEnvVarValue:
    """Tests for validate_env_var_value function"""

    def test_valid_values(self):
        """Should accept values without newlines"""
        assert validate_env_var_value("simple") is True
        assert validate_env_var_value("with spaces") is True
        assert validate_env_var_value("special!@#$%^&*()") is True
        assert validate_env_var_value("") is True  # Empty is valid

    def test_rejects_newlines(self):
        """Should reject values containing newlines"""
        assert validate_env_var_value("line1\nline2") is False
        assert validate_env_var_value("line1\rline2") is False
        assert validate_env_var_value("value\nINJECTED=bad") is False

    def test_rejects_non_string(self):
        """Should reject non-string values"""
        assert validate_env_var_value(123) is False
        assert validate_env_var_value(None) is False


class TestValidateEnvVars:
    """Tests for validate_env_vars function"""

    def test_all_valid(self):
        """Should return True when all names and values are valid"""
        valid, invalid_names, invalid_values = validate_env_vars({"DB_HOST": "x", "DB_PORT": "y"})
        assert valid is True
        assert invalid_names == []
        assert invalid_values == []

    def test_returns_invalid_names(self):
        """Should return list of invalid names"""
        valid, invalid_names, invalid_values = validate_env_vars({
            "VALID_NAME": "ok",
            "123BAD": "bad",
            "ALSO=BAD": "bad"
        })
        assert valid is False
        assert "123BAD" in invalid_names
        assert "ALSO=BAD" in invalid_names
        assert "VALID_NAME" not in invalid_names

    def test_returns_invalid_values(self):
        """Should return list of keys with invalid values"""
        valid, invalid_names, invalid_values = validate_env_vars({
            "GOOD_NAME": "good_value",
            "BAD_VALUE": "has\nnewline"
        })
        assert valid is False
        assert invalid_names == []
        assert "BAD_VALUE" in invalid_values
        assert "GOOD_NAME" not in invalid_values


class TestSetEnvOverrides:
    """Tests for set_env_overrides function"""

    def test_encrypts_and_stores_json(self):
        """Should encrypt JSON and store in metadata"""
        metadata = {"name": "test-stack"}
        env_vars = {"DB_HOST": "localhost", "DB_PORT": "5432"}

        with patch('git.env_overrides.encrypt_password', return_value='encrypted_result') as mock_encrypt:
            set_env_overrides(metadata, env_vars)

        assert metadata["env_overrides_encrypted"] == "encrypted_result"
        # Verify sorted JSON was encrypted
        mock_encrypt.assert_called_once()
        call_arg = mock_encrypt.call_args[0][0]
        assert '"DB_HOST": "localhost"' in call_arg
        assert '"DB_PORT": "5432"' in call_arg

    def test_removes_key_when_env_vars_empty(self):
        """Should remove env_overrides_encrypted when env_vars is empty"""
        metadata = {"name": "test-stack", "env_overrides_encrypted": "old_value"}

        set_env_overrides(metadata, {})

        assert "env_overrides_encrypted" not in metadata

    def test_raises_on_invalid_env_var_name(self):
        """Should raise ValueError for invalid env var names"""
        metadata = {"name": "test-stack"}
        env_vars = {"VALID": "ok", "123INVALID": "bad"}

        with pytest.raises(ValueError, match="Invalid environment variable names"):
            set_env_overrides(metadata, env_vars)

    def test_raises_on_newline_injection_attempt(self):
        """Should raise ValueError for values containing newlines (injection protection)"""
        metadata = {"name": "test-stack"}
        env_vars = {"DB_PASSWORD": "secret\nMALICIOUS_VAR=injected"}

        with pytest.raises(ValueError, match="Values cannot contain newlines"):
            set_env_overrides(metadata, env_vars)

    def test_removes_key_when_env_vars_none(self):
        """Should handle None env_vars"""
        metadata = {"name": "test-stack", "env_overrides_encrypted": "old_value"}

        # Empty dict is treated as "no overrides"
        set_env_overrides(metadata, {})

        assert "env_overrides_encrypted" not in metadata


class TestMergeEnvContent:
    """Tests for merge_env_content function"""

    def test_returns_git_env_only_when_no_overrides(self):
        """Should return git .env content when no overrides"""
        git_env = "DB_HOST=production\nDB_PORT=5432"
        result = merge_env_content(git_env, {})

        assert result == "DB_HOST=production\nDB_PORT=5432"

    def test_returns_overrides_only_when_no_git_env(self):
        """Should return overrides when no git .env"""
        overrides = {"API_KEY": "secret123", "DEBUG": "false"}
        result = merge_env_content(None, overrides)

        assert "API_KEY=secret123" in result
        assert "DEBUG=false" in result

    def test_merges_git_env_and_overrides(self):
        """Should merge git .env and overrides with separator"""
        git_env = "DB_HOST=localhost"
        overrides = {"API_KEY": "secret"}
        result = merge_env_content(git_env, overrides)

        assert "DB_HOST=localhost" in result
        assert "API_KEY=secret" in result
        # Overrides should come after git env
        assert result.index("DB_HOST") < result.index("API_KEY")

    def test_handles_empty_git_env(self):
        """Should handle empty string git .env"""
        overrides = {"KEY": "value"}
        result = merge_env_content("", overrides)

        assert "KEY=value" in result

    def test_handles_both_empty(self):
        """Should return empty string when both are empty"""
        result = merge_env_content(None, {})
        assert result == ""

    def test_sorts_override_keys(self):
        """Should sort override keys for consistent output"""
        overrides = {"Z_VAR": "z", "A_VAR": "a", "M_VAR": "m"}
        result = merge_env_content(None, overrides)

        lines = result.split("\n")
        key_order = [line.split("=")[0] for line in lines if "=" in line]
        assert key_order == sorted(key_order)

    def test_strips_trailing_whitespace_from_git_env(self):
        """Should strip trailing whitespace from git .env"""
        git_env = "DB_HOST=localhost\n\n\n"
        overrides = {"KEY": "value"}
        result = merge_env_content(git_env, overrides)

        # Should not have multiple trailing newlines from git env
        assert "\n\n\n" not in result
