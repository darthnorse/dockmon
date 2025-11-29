"""
Unit tests for registry credentials utility.

Tests verify:
- Single credential lookup by image name
- All credentials retrieval for compose deployments
- Decryption error handling
- Edge cases (empty, missing)

Following TDD principles: RED -> GREEN -> REFACTOR
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from contextlib import contextmanager


class TestGetRegistryCredentials:
    """Tests for get_registry_credentials function"""

    def test_returns_credentials_for_matching_registry(self, test_db):
        """Should return credentials when registry matches image"""
        from database import RegistryCredential
        from utils.registry_credentials import get_registry_credentials

        # Arrange: Create a registry credential
        cred = RegistryCredential(
            registry_url="ghcr.io",
            username="testuser",
            password_encrypted="encrypted_password"
        )
        test_db.add(cred)
        test_db.commit()

        # Create mock db manager
        mock_db = Mock()
        @contextmanager
        def get_session_cm():
            yield test_db
        mock_db.get_session = get_session_cm

        # Act
        with patch('utils.encryption.decrypt_password', return_value="decrypted_secret"):
            result = get_registry_credentials(mock_db, "ghcr.io/myorg/myapp:latest")

        # Assert
        assert result is not None
        assert result["username"] == "testuser"
        assert result["password"] == "decrypted_secret"

    def test_returns_none_for_no_matching_registry(self, test_db):
        """Should return None when no credentials match"""
        from utils.registry_credentials import get_registry_credentials

        # Create mock db manager (empty database)
        mock_db = Mock()
        @contextmanager
        def get_session_cm():
            yield test_db
        mock_db.get_session = get_session_cm

        # Act
        result = get_registry_credentials(mock_db, "ghcr.io/myorg/myapp:latest")

        # Assert
        assert result is None

    def test_defaults_to_docker_hub_for_simple_image(self, test_db):
        """Should default to docker.io for images without explicit registry"""
        from database import RegistryCredential
        from utils.registry_credentials import get_registry_credentials

        # Arrange: Create docker.io credential
        cred = RegistryCredential(
            registry_url="docker.io",
            username="dockeruser",
            password_encrypted="encrypted_password"
        )
        test_db.add(cred)
        test_db.commit()

        mock_db = Mock()
        @contextmanager
        def get_session_cm():
            yield test_db
        mock_db.get_session = get_session_cm

        # Act
        with patch('utils.encryption.decrypt_password', return_value="docker_secret"):
            result = get_registry_credentials(mock_db, "nginx:latest")

        # Assert
        assert result is not None
        assert result["username"] == "dockeruser"

    def test_handles_decryption_error_gracefully(self, test_db):
        """Should return None if decryption fails"""
        from database import RegistryCredential
        from utils.registry_credentials import get_registry_credentials

        # Arrange
        cred = RegistryCredential(
            registry_url="ghcr.io",
            username="testuser",
            password_encrypted="bad_encrypted_data"
        )
        test_db.add(cred)
        test_db.commit()

        mock_db = Mock()
        @contextmanager
        def get_session_cm():
            yield test_db
        mock_db.get_session = get_session_cm

        # Act
        with patch('utils.encryption.decrypt_password', side_effect=Exception("Decryption failed")):
            result = get_registry_credentials(mock_db, "ghcr.io/myorg/myapp:latest")

        # Assert
        assert result is None


class TestGetAllRegistryCredentials:
    """Tests for get_all_registry_credentials function"""

    def test_returns_all_credentials(self, test_db):
        """Should return all stored credentials"""
        from database import RegistryCredential
        from utils.registry_credentials import get_all_registry_credentials

        # Arrange: Create multiple credentials
        cred1 = RegistryCredential(
            registry_url="ghcr.io",
            username="user1",
            password_encrypted="encrypted1"
        )
        cred2 = RegistryCredential(
            registry_url="docker.io",
            username="user2",
            password_encrypted="encrypted2"
        )
        test_db.add(cred1)
        test_db.add(cred2)
        test_db.commit()

        mock_db = Mock()
        @contextmanager
        def get_session_cm():
            yield test_db
        mock_db.get_session = get_session_cm

        # Act
        with patch('utils.encryption.decrypt_password', side_effect=["secret1", "secret2"]):
            result = get_all_registry_credentials(mock_db)

        # Assert
        assert len(result) == 2
        assert any(c["registry_url"] == "ghcr.io" and c["username"] == "user1" for c in result)
        assert any(c["registry_url"] == "docker.io" and c["username"] == "user2" for c in result)

    def test_returns_empty_list_when_no_credentials(self, test_db):
        """Should return empty list when no credentials exist"""
        from utils.registry_credentials import get_all_registry_credentials

        mock_db = Mock()
        @contextmanager
        def get_session_cm():
            yield test_db
        mock_db.get_session = get_session_cm

        # Act
        result = get_all_registry_credentials(mock_db)

        # Assert
        assert result == []

    def test_skips_credential_with_decryption_error(self, test_db):
        """Should skip credentials that fail decryption but return others"""
        from database import RegistryCredential
        from utils.registry_credentials import get_all_registry_credentials

        # Arrange: Create two credentials, one will fail decryption
        cred1 = RegistryCredential(
            registry_url="ghcr.io",
            username="user1",
            password_encrypted="good_encrypted"
        )
        cred2 = RegistryCredential(
            registry_url="docker.io",
            username="user2",
            password_encrypted="bad_encrypted"
        )
        test_db.add(cred1)
        test_db.add(cred2)
        test_db.commit()

        mock_db = Mock()
        @contextmanager
        def get_session_cm():
            yield test_db
        mock_db.get_session = get_session_cm

        # Act: First call succeeds, second fails
        def mock_decrypt(encrypted):
            if encrypted == "good_encrypted":
                return "secret1"
            raise Exception("Decryption failed")

        with patch('utils.encryption.decrypt_password', side_effect=mock_decrypt):
            result = get_all_registry_credentials(mock_db)

        # Assert: Only the successful one is returned
        assert len(result) == 1
        assert result[0]["registry_url"] == "ghcr.io"
        assert result[0]["password"] == "secret1"

    def test_returns_correct_structure(self, test_db):
        """Should return list of dicts with registry_url, username, password"""
        from database import RegistryCredential
        from utils.registry_credentials import get_all_registry_credentials

        cred = RegistryCredential(
            registry_url="registry.example.com",
            username="admin",
            password_encrypted="encrypted"
        )
        test_db.add(cred)
        test_db.commit()

        mock_db = Mock()
        @contextmanager
        def get_session_cm():
            yield test_db
        mock_db.get_session = get_session_cm

        with patch('utils.encryption.decrypt_password', return_value="admin_secret"):
            result = get_all_registry_credentials(mock_db)

        # Assert structure
        assert len(result) == 1
        cred_dict = result[0]
        assert "registry_url" in cred_dict
        assert "username" in cred_dict
        assert "password" in cred_dict
        assert cred_dict["registry_url"] == "registry.example.com"
        assert cred_dict["username"] == "admin"
        assert cred_dict["password"] == "admin_secret"
