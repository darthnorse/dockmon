"""Stack env-file API: the env_files map on create/update/response, plus the DELETE /{name}/env-files/{filename} route (#205)."""
import pytest
from unittest.mock import AsyncMock

from deployment.stack_routes import StackCreate, StackUpdate, StackResponse


def test_models_accept_env_files_map():
    c = StackCreate(name="myapp", compose_yaml="services: {}\n",
                    env_files={".env": "A=1", ".db.env": "P=2"})
    assert c.env_files == {".env": "A=1", ".db.env": "P=2"}

    u = StackUpdate(compose_yaml="services: {}\n", env_files={".env": "A=1"})
    assert u.env_files == {".env": "A=1"}

    r = StackResponse(name="myapp", compose_yaml="services: {}\n",
                      env_files={".env": "A=1"})
    assert r.env_files == {".env": "A=1"}


def test_env_files_defaults_to_empty_map():
    c = StackCreate(name="myapp", compose_yaml="services: {}\n")
    assert c.env_files == {}

    u = StackUpdate(compose_yaml="services: {}\n")
    assert u.env_files == {}

    r = StackResponse(name="myapp", compose_yaml="services: {}\n")
    assert r.env_files == {}


# ==================== DELETE /{name}/env-files/{filename} route tests ====================

@pytest.fixture
def authed_client(client, monkeypatch):
    """TestClient with auth + stacks.edit capability granted."""
    import main
    from auth.api_key_auth import get_current_user_or_api_key

    async def _mock_user():
        return {"username": "test_user", "user_id": 1, "auth_type": "session"}

    main.app.dependency_overrides[get_current_user_or_api_key] = _mock_user
    monkeypatch.setattr("auth.api_key_auth.check_auth_capability", lambda user, cap: True)
    return client


@pytest.fixture
def unauthorized_client(client, monkeypatch):
    """TestClient authenticated but WITHOUT the stacks.edit capability (403)."""
    import main
    from auth.api_key_auth import get_current_user_or_api_key

    async def _mock_user():
        return {"username": "test_user", "user_id": 1, "auth_type": "session"}

    main.app.dependency_overrides[get_current_user_or_api_key] = _mock_user
    monkeypatch.setattr("auth.api_key_auth.check_auth_capability", lambda user, cap: False)
    return client


@pytest.mark.integration
class TestDeleteStackEnvFileRoute:
    def test_authorized_delete_file_removed(self, authed_client, monkeypatch):
        """Authorized request, file exists and is deleted → 200 {"deleted": true}."""
        from deployment import stack_storage
        monkeypatch.setattr(stack_storage, "stack_exists", AsyncMock(return_value=True))
        monkeypatch.setattr(stack_storage, "delete_env_file", AsyncMock(return_value=True))

        response = authed_client.delete("/api/stacks/myapp/env-files/.db.env")

        assert response.status_code == 200
        assert response.json() == {"deleted": True}

    def test_delete_missing_file_returns_false(self, authed_client, monkeypatch):
        """File does not exist on disk → 200 {"deleted": false} (idempotent)."""
        from deployment import stack_storage
        monkeypatch.setattr(stack_storage, "stack_exists", AsyncMock(return_value=True))
        monkeypatch.setattr(stack_storage, "delete_env_file", AsyncMock(return_value=False))

        response = authed_client.delete("/api/stacks/myapp/env-files/.env")

        assert response.status_code == 200
        assert response.json() == {"deleted": False}

    def test_unsafe_filename_returns_400(self, authed_client, monkeypatch):
        """delete_env_file raises ValueError for unsafe filename → 400.

        The storage layer validates filenames (e.g. rejects names with backslashes,
        null bytes, or whitespace). We mock the ValueError so the test exercises the
        route's 400 mapping without depending on a specific invalid character that
        must also survive URL routing.
        """
        from deployment import stack_storage
        monkeypatch.setattr(stack_storage, "stack_exists", AsyncMock(return_value=True))
        monkeypatch.setattr(
            stack_storage,
            "delete_env_file",
            AsyncMock(side_effect=ValueError("Unsafe env filename")),
        )

        # Use a routable filename; the mock unconditionally raises ValueError to
        # simulate what the real storage layer does for any unsafe name.
        response = authed_client.delete("/api/stacks/myapp/env-files/.env")

        assert response.status_code == 400

    def test_missing_stack_returns_404(self, authed_client, monkeypatch):
        """Stack directory does not exist → 404; delete_env_file must NOT be called."""
        from deployment import stack_storage
        monkeypatch.setattr(stack_storage, "stack_exists", AsyncMock(return_value=False))
        mock_delete = AsyncMock(return_value=True)
        monkeypatch.setattr(stack_storage, "delete_env_file", mock_delete)

        response = authed_client.delete("/api/stacks/no-such-stack/env-files/.env")

        assert response.status_code == 404
        mock_delete.assert_not_called()

    def test_without_stacks_edit_returns_403(self, unauthorized_client, monkeypatch):
        """Capability check fails → 403 before any storage call is made."""
        from deployment import stack_storage
        mock_exists = AsyncMock(return_value=True)
        mock_delete = AsyncMock(return_value=True)
        monkeypatch.setattr(stack_storage, "stack_exists", mock_exists)
        monkeypatch.setattr(stack_storage, "delete_env_file", mock_delete)

        response = unauthorized_client.delete("/api/stacks/myapp/env-files/.env")

        assert response.status_code == 403
