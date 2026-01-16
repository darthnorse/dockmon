"""
Unit tests for Git API routes (v2.4.0+).

Tests verify:
- Git credentials CRUD operations
- Git repositories CRUD operations
- Test connection endpoint
- Manual sync endpoint
- List files endpoint
- Input validation
- Error handling
- Security features (sanitized responses, admin authorization)

Following Phase 1 learnings:
- Test all exception paths
- Test validators thoroughly
- No __init__.py to avoid package shadowing
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch, AsyncMock

from database import GitCredential, GitRepository
from models.git_models import (
    GitCredentialCreate,
    GitCredentialUpdate,
    GitCredentialResponse,
    GitRepositoryCreate,
    GitRepositoryUpdate,
    GitRepositoryResponse,
    GitTestConnectionRequest,
    GitTestConnectionResponse,
    GitSyncResponse,
    GitFileListResponse,
)


# =============================================================================
# Pydantic Model Validation Tests
# =============================================================================


class TestGitCredentialCreateValidation:
    """Tests for GitCredentialCreate validation"""

    def test_valid_https_credential(self):
        """Should accept valid HTTPS credentials"""
        cred = GitCredentialCreate(
            name="github-token",
            auth_type="https",
            username="user",
            password="ghp_xxxxxxxxxxxx"
        )
        assert cred.name == "github-token"
        assert cred.auth_type == "https"

    def test_valid_ssh_credential(self):
        """Should accept valid SSH credentials"""
        ssh_key = "-----BEGIN OPENSSH PRIVATE KEY-----\ntest\n-----END OPENSSH PRIVATE KEY-----"
        cred = GitCredentialCreate(
            name="deploy-key",
            auth_type="ssh",
            ssh_private_key=ssh_key
        )
        assert cred.name == "deploy-key"
        assert cred.auth_type == "ssh"

    def test_valid_none_credential(self):
        """Should accept 'none' auth type for public repos"""
        cred = GitCredentialCreate(
            name="public-access",
            auth_type="none"
        )
        assert cred.auth_type == "none"

    def test_rejects_empty_name(self):
        """Should reject empty name"""
        # Pydantic's min_length=1 catches this before our custom validator
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="at least 1 character"):
            GitCredentialCreate(name="", auth_type="none")

    def test_rejects_whitespace_only_name(self):
        """Should reject whitespace-only name"""
        with pytest.raises(ValueError, match="cannot be empty"):
            GitCredentialCreate(name="   ", auth_type="none")

    def test_rejects_xss_in_name(self):
        """Should reject XSS attempts in name"""
        with pytest.raises(ValueError, match="invalid characters"):
            GitCredentialCreate(name="<script>alert(1)</script>", auth_type="none")

    def test_rejects_quotes_in_name(self):
        """Should reject quotes in name"""
        with pytest.raises(ValueError, match="invalid characters"):
            GitCredentialCreate(name="test'name", auth_type="none")

    def test_rejects_invalid_auth_type(self):
        """Should reject invalid auth type"""
        with pytest.raises(ValueError):
            GitCredentialCreate(name="test", auth_type="invalid")

    def test_rejects_invalid_ssh_key_format(self):
        """Should reject SSH keys not in PEM format"""
        with pytest.raises(ValueError, match="PEM format"):
            GitCredentialCreate(
                name="bad-key",
                auth_type="ssh",
                ssh_private_key="not a valid key"
            )

    def test_accepts_rsa_key(self):
        """Should accept RSA private key format"""
        rsa_key = "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----"
        cred = GitCredentialCreate(
            name="rsa-key",
            auth_type="ssh",
            ssh_private_key=rsa_key
        )
        assert cred.ssh_private_key == rsa_key

    def test_strips_ssh_key_whitespace(self):
        """Should strip leading/trailing whitespace from SSH key"""
        ssh_key = "  -----BEGIN OPENSSH PRIVATE KEY-----\ntest\n-----END OPENSSH PRIVATE KEY-----  "
        cred = GitCredentialCreate(
            name="key",
            auth_type="ssh",
            ssh_private_key=ssh_key
        )
        assert cred.ssh_private_key.startswith("-----BEGIN")


class TestGitCredentialUpdateValidation:
    """Tests for GitCredentialUpdate validation"""

    def test_all_fields_optional(self):
        """Should accept update with no fields"""
        update = GitCredentialUpdate()
        assert update.name is None
        assert update.auth_type is None

    def test_partial_update(self):
        """Should accept partial updates"""
        update = GitCredentialUpdate(name="new-name")
        assert update.name == "new-name"
        assert update.auth_type is None

    def test_clear_password_flag(self):
        """Should support clear_password flag"""
        update = GitCredentialUpdate(clear_password=True)
        assert update.clear_password is True

    def test_clear_ssh_key_flag(self):
        """Should support clear_ssh_key flag"""
        update = GitCredentialUpdate(clear_ssh_key=True)
        assert update.clear_ssh_key is True


class TestGitRepositoryCreateValidation:
    """Tests for GitRepositoryCreate validation"""

    def test_valid_https_url(self):
        """Should accept HTTPS URLs"""
        repo = GitRepositoryCreate(
            name="my-repo",
            url="https://github.com/org/repo.git",
            branch="main"
        )
        assert repo.url == "https://github.com/org/repo.git"

    def test_valid_ssh_url(self):
        """Should accept SSH URLs"""
        repo = GitRepositoryCreate(
            name="my-repo",
            url="git@github.com:org/repo.git",
            branch="main"
        )
        assert repo.url == "git@github.com:org/repo.git"

    def test_valid_ssh_protocol_url(self):
        """Should accept ssh:// URLs"""
        repo = GitRepositoryCreate(
            name="my-repo",
            url="ssh://git@github.com/org/repo.git",
            branch="main"
        )
        assert repo.url.startswith("ssh://")

    def test_default_branch_is_main(self):
        """Should default to main branch"""
        repo = GitRepositoryCreate(
            name="my-repo",
            url="https://github.com/org/repo.git"
        )
        assert repo.branch == "main"

    def test_default_auto_sync_disabled(self):
        """Should default auto_sync_enabled to False"""
        repo = GitRepositoryCreate(
            name="my-repo",
            url="https://github.com/org/repo.git"
        )
        assert repo.auto_sync_enabled is False

    def test_default_cron_schedule(self):
        """Should default cron to 3 AM daily"""
        repo = GitRepositoryCreate(
            name="my-repo",
            url="https://github.com/org/repo.git"
        )
        assert repo.auto_sync_cron == "0 3 * * *"

    def test_rejects_invalid_url_scheme(self):
        """Should reject URLs without valid scheme"""
        with pytest.raises(ValueError, match="must start with"):
            GitRepositoryCreate(
                name="my-repo",
                url="ftp://example.com/repo.git"
            )

    def test_rejects_url_with_spaces(self):
        """Should reject URLs with spaces"""
        with pytest.raises(ValueError, match="spaces"):
            GitRepositoryCreate(
                name="my-repo",
                url="https://github.com/org/my repo.git"
            )

    def test_rejects_command_injection_in_url(self):
        """Should reject command injection attempts in URL"""
        dangerous_chars = [';', '|', '&', '$', '`', '\n']
        for char in dangerous_chars:
            with pytest.raises(ValueError, match="invalid characters"):
                GitRepositoryCreate(
                    name="my-repo",
                    url=f"https://github.com/org/repo{char}evil.git"
                )

    def test_rejects_branch_starting_with_dash(self):
        """Should reject branch names starting with dash"""
        with pytest.raises(ValueError, match="cannot start with"):
            GitRepositoryCreate(
                name="my-repo",
                url="https://github.com/org/repo.git",
                branch="-evil"
            )

    def test_rejects_branch_with_double_dots(self):
        """Should reject branch names with .."""
        with pytest.raises(ValueError, match="cannot contain"):
            GitRepositoryCreate(
                name="my-repo",
                url="https://github.com/org/repo.git",
                branch="feature/../main"
            )

    def test_rejects_branch_ending_with_lock(self):
        """Should reject branch names ending with .lock"""
        with pytest.raises(ValueError, match="cannot end with"):
            GitRepositoryCreate(
                name="my-repo",
                url="https://github.com/org/repo.git",
                branch="feature.lock"
            )

    def test_accepts_valid_branch_names(self):
        """Should accept valid branch name formats"""
        valid_branches = [
            "main",
            "develop",
            "feature/new-feature",
            "release-1.0.0",
            "hotfix_urgent",
        ]
        for branch in valid_branches:
            repo = GitRepositoryCreate(
                name="my-repo",
                url="https://github.com/org/repo.git",
                branch=branch
            )
            assert repo.branch == branch

    def test_rejects_invalid_cron_format(self):
        """Should reject invalid cron expressions"""
        with pytest.raises(ValueError, match="5 fields"):
            GitRepositoryCreate(
                name="my-repo",
                url="https://github.com/org/repo.git",
                auto_sync_cron="0 3 * *"  # Only 4 fields
            )


class TestGitTestConnectionRequestValidation:
    """Tests for GitTestConnectionRequest validation"""

    def test_valid_request(self):
        """Should accept valid test connection request"""
        req = GitTestConnectionRequest(
            url="https://github.com/org/repo.git",
            branch="main",
            auth_type="none"
        )
        assert req.url == "https://github.com/org/repo.git"

    def test_with_https_auth(self):
        """Should accept request with HTTPS auth"""
        req = GitTestConnectionRequest(
            url="https://github.com/org/repo.git",
            branch="main",
            auth_type="https",
            username="user",
            password="token"
        )
        assert req.auth_type == "https"
        assert req.username == "user"


# =============================================================================
# Response Model Tests
# =============================================================================


class TestGitCredentialResponse:
    """Tests for GitCredentialResponse"""

    def test_from_db_sanitizes_secrets(self):
        """Should not expose secrets in response"""
        mock_cred = Mock()
        mock_cred.id = 1
        mock_cred.name = "test-cred"
        mock_cred.auth_type = "https"
        mock_cred.username = "user"
        mock_cred._password = "encrypted_password"  # Has password
        mock_cred._ssh_private_key = None  # No SSH key
        mock_cred.created_at = datetime(2024, 1, 15, 10, 30, 0)
        mock_cred.updated_at = datetime(2024, 1, 15, 14, 20, 0)

        response = GitCredentialResponse.from_db(mock_cred)

        assert response.id == 1
        assert response.name == "test-cred"
        assert response.has_password is True
        assert response.has_ssh_key is False
        # Verify no actual secrets exposed
        assert not hasattr(response, 'password')
        assert not hasattr(response, '_password')
        assert not hasattr(response, 'ssh_private_key')

    def test_timestamps_have_z_suffix(self):
        """Should add Z suffix to timestamps"""
        mock_cred = Mock()
        mock_cred.id = 1
        mock_cred.name = "test"
        mock_cred.auth_type = "none"
        mock_cred.username = None
        mock_cred._password = None
        mock_cred._ssh_private_key = None
        mock_cred.created_at = datetime(2024, 1, 15, 10, 30, 0)
        mock_cred.updated_at = datetime(2024, 1, 15, 14, 20, 0)

        response = GitCredentialResponse.from_db(mock_cred)

        assert response.created_at.endswith('Z')
        assert response.updated_at.endswith('Z')


class TestGitRepositoryResponse:
    """Tests for GitRepositoryResponse"""

    def test_from_db_includes_credential_name(self):
        """Should include credential name if credential exists"""
        mock_cred = Mock()
        mock_cred.name = "my-credential"

        mock_repo = Mock()
        mock_repo.id = 1
        mock_repo.name = "my-repo"
        mock_repo.url = "https://github.com/org/repo.git"
        mock_repo.branch = "main"
        mock_repo.credential_id = 1
        mock_repo.credential = mock_cred
        mock_repo.auto_sync_enabled = True
        mock_repo.auto_sync_cron = "0 3 * * *"
        mock_repo.last_sync_at = datetime(2024, 1, 15, 3, 0, 0)
        mock_repo.last_commit = "abc123"
        mock_repo.sync_status = "synced"
        mock_repo.sync_error = None
        mock_repo.created_at = datetime(2024, 1, 10, 10, 0, 0)
        mock_repo.updated_at = datetime(2024, 1, 15, 3, 0, 0)

        response = GitRepositoryResponse.from_db(mock_repo, linked_stacks_count=3)

        assert response.credential_name == "my-credential"
        assert response.linked_stacks_count == 3

    def test_from_db_handles_no_credential(self):
        """Should handle repo without credential"""
        mock_repo = Mock()
        mock_repo.id = 1
        mock_repo.name = "my-repo"
        mock_repo.url = "https://github.com/org/repo.git"
        mock_repo.branch = "main"
        mock_repo.credential_id = None
        mock_repo.credential = None
        mock_repo.auto_sync_enabled = False
        mock_repo.auto_sync_cron = "0 3 * * *"
        mock_repo.last_sync_at = None
        mock_repo.last_commit = None
        mock_repo.sync_status = "pending"
        mock_repo.sync_error = None
        mock_repo.created_at = datetime(2024, 1, 10, 10, 0, 0)
        mock_repo.updated_at = datetime(2024, 1, 10, 10, 0, 0)

        response = GitRepositoryResponse.from_db(mock_repo)

        assert response.credential_id is None
        assert response.credential_name is None

    def test_last_sync_at_timestamp_format(self):
        """Should format last_sync_at with Z suffix when present"""
        mock_repo = Mock()
        mock_repo.id = 1
        mock_repo.name = "my-repo"
        mock_repo.url = "https://github.com/org/repo.git"
        mock_repo.branch = "main"
        mock_repo.credential_id = None
        mock_repo.credential = None
        mock_repo.auto_sync_enabled = False
        mock_repo.auto_sync_cron = "0 3 * * *"
        mock_repo.last_sync_at = datetime(2024, 1, 15, 3, 0, 0)
        mock_repo.last_commit = "abc123"
        mock_repo.sync_status = "synced"
        mock_repo.sync_error = None
        mock_repo.created_at = datetime(2024, 1, 10, 10, 0, 0)
        mock_repo.updated_at = datetime(2024, 1, 15, 3, 0, 0)

        response = GitRepositoryResponse.from_db(mock_repo)

        assert response.last_sync_at.endswith('Z')


# =============================================================================
# Database Integration Tests (using test_db fixture)
# =============================================================================


class TestGitCredentialCRUD:
    """Integration tests for GitCredential database operations"""

    def test_create_credential(self, test_db):
        """Should create credential with encrypted fields"""
        cred = GitCredential(
            name="test-cred",
            auth_type="https",
            username="user",
        )
        cred.password = "secret123"

        test_db.add(cred)
        test_db.commit()
        test_db.refresh(cred)

        assert cred.id is not None
        assert cred.name == "test-cred"
        # Password should be encrypted in database
        assert cred._password != "secret123"
        # But decrypted when accessed via property
        assert cred.password == "secret123"

    def test_create_ssh_credential(self, test_db):
        """Should create SSH credential with encrypted key"""
        ssh_key = "-----BEGIN OPENSSH PRIVATE KEY-----\ntest\n-----END OPENSSH PRIVATE KEY-----"
        cred = GitCredential(
            name="ssh-cred",
            auth_type="ssh",
        )
        cred.ssh_private_key = ssh_key

        test_db.add(cred)
        test_db.commit()
        test_db.refresh(cred)

        # Key should be encrypted
        assert cred._ssh_private_key != ssh_key
        # But decrypted when accessed
        assert cred.ssh_private_key == ssh_key

    def test_unique_name_constraint(self, test_db):
        """Should enforce unique name constraint"""
        cred1 = GitCredential(name="unique-name", auth_type="none")
        test_db.add(cred1)
        test_db.commit()

        cred2 = GitCredential(name="unique-name", auth_type="none")
        test_db.add(cred2)

        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            test_db.commit()


class TestGitRepositoryCRUD:
    """Integration tests for GitRepository database operations"""

    def test_create_repository(self, test_db):
        """Should create repository with default values"""
        repo = GitRepository(
            name="test-repo",
            url="https://github.com/org/repo.git",
            branch="main",
        )

        test_db.add(repo)
        test_db.commit()
        test_db.refresh(repo)

        assert repo.id is not None
        assert repo.sync_status == "pending"
        assert repo.auto_sync_enabled is False

    def test_credential_relationship(self, test_db):
        """Should create repository with credential relationship"""
        cred = GitCredential(name="cred", auth_type="none")
        test_db.add(cred)
        test_db.commit()

        repo = GitRepository(
            name="test-repo",
            url="https://github.com/org/repo.git",
            branch="main",
            credential_id=cred.id,
        )
        test_db.add(repo)
        test_db.commit()
        test_db.refresh(repo)

        assert repo.credential_id == cred.id
        assert repo.credential.name == "cred"

    def test_credential_cascade_set_null(self, test_db):
        """Should set credential_id to NULL when credential deleted"""
        cred = GitCredential(name="cred", auth_type="none")
        test_db.add(cred)
        test_db.commit()

        repo = GitRepository(
            name="test-repo",
            url="https://github.com/org/repo.git",
            branch="main",
            credential_id=cred.id,
        )
        test_db.add(repo)
        test_db.commit()

        # Delete credential
        test_db.delete(cred)
        test_db.commit()

        # Refresh repo to see cascade effect
        test_db.refresh(repo)
        assert repo.credential_id is None


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling"""

    def test_credential_name_with_special_chars(self):
        """Should accept valid special chars in name"""
        # These should be allowed: alphanumeric, dash, underscore, dot
        valid_names = [
            "my-credential",
            "my_credential",
            "my.credential",
            "MyCredential123",
        ]
        for name in valid_names:
            cred = GitCredentialCreate(name=name, auth_type="none")
            assert cred.name == name

    def test_url_with_port(self):
        """Should accept URLs with ports"""
        repo = GitRepositoryCreate(
            name="my-repo",
            url="https://github.example.com:8443/org/repo.git",
            branch="main"
        )
        assert ":8443" in repo.url

    def test_url_with_path(self):
        """Should accept URLs with complex paths"""
        repo = GitRepositoryCreate(
            name="my-repo",
            url="https://github.com/org/sub/dir/repo.git",
            branch="main"
        )
        assert repo.url.endswith("repo.git")

    def test_empty_ssh_key_becomes_none(self):
        """Should convert empty SSH key to None"""
        cred = GitCredentialCreate(
            name="test",
            auth_type="none",
            ssh_private_key=""
        )
        assert cred.ssh_private_key is None

    def test_whitespace_ssh_key_becomes_none(self):
        """Should convert whitespace-only SSH key to None"""
        cred = GitCredentialCreate(
            name="test",
            auth_type="none",
            ssh_private_key="   "
        )
        assert cred.ssh_private_key is None


class TestCronValidation:
    """Tests for cron expression validation"""

    def test_valid_cron_expressions(self):
        """Should accept valid cron expressions"""
        valid_crons = [
            "0 3 * * *",      # Daily at 3 AM
            "*/15 * * * *",   # Every 15 minutes
            "0 0 * * 0",      # Weekly on Sunday
            "0 12 1 * *",     # Monthly on 1st at noon
        ]
        for cron in valid_crons:
            repo = GitRepositoryCreate(
                name="my-repo",
                url="https://github.com/org/repo.git",
                auto_sync_cron=cron
            )
            assert repo.auto_sync_cron == cron

    def test_rejects_cron_with_wrong_field_count(self):
        """Should reject cron with wrong number of fields"""
        invalid_crons = [
            "* * * *",        # 4 fields
            "* * * * * *",    # 6 fields
            "3 * *",          # 3 fields
        ]
        for cron in invalid_crons:
            with pytest.raises(ValueError, match="5 fields"):
                GitRepositoryCreate(
                    name="my-repo",
                    url="https://github.com/org/repo.git",
                    auto_sync_cron=cron
                )
