"""
Unit tests for locally-built image detection in the update checker.

A manual update check on a locally-built container used to return a bare None,
which the API surfaced as a misleading "registry authentication / network"
error. A locally-built image has no RepoDigests (Docker only populates those on
pull/push) and cannot be resolved in any registry, so there is genuinely nothing
to check. The checker must distinguish this from a real auth/network failure
(where the image HAS RepoDigests but the registry query for the latest tag
fails) so the API can show an accurate, non-error message.

Following TDD: RED -> GREEN -> REFACTOR.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from database import DatabaseManager
from updates.update_checker import UpdateChecker


def _make_checker():
    """UpdateChecker with all registry/db/docker boundaries mocked."""
    checker = UpdateChecker(db=MagicMock(spec=DatabaseManager), monitor=MagicMock())
    checker.registry = MagicMock()
    checker.registry.compute_floating_tag = MagicMock(side_effect=lambda image, mode: image)
    checker.registry.resolve_tag = AsyncMock(return_value=None)
    checker._get_tracking_mode = MagicMock(return_value="exact")
    checker._get_registry_credentials = MagicMock(return_value=None)
    checker._get_container_image_version = AsyncMock(return_value=None)
    return checker


class TestLocalImageDetection:
    """_check_container_update must flag locally-built images distinctly."""

    @pytest.mark.asyncio
    async def test_returns_local_image_marker_when_no_repo_digests_and_unresolvable(self):
        """No RepoDigests + tag not resolvable in any registry => locally built."""
        checker = _make_checker()
        # No local digest available (image was never pulled/pushed)...
        checker._get_container_image_digest = AsyncMock(return_value=None)
        # ...and the Issue #143 registry fallback also can't resolve it.
        checker.registry.resolve_tag = AsyncMock(return_value=None)

        container = {
            "host_id": "host-123",
            "id": "abc123def456",
            "name": "my-local-app",
            "image": "my-local-app:latest",
            # No "repo_digests" key - the defining trait of a locally-built image
        }

        result = await checker._check_container_update(container, bypass_cache=True)

        assert result is not None, "Locally-built image must not collapse to None"
        assert result.get("status") == "local_image"
        assert result.get("current_image") == "my-local-app:latest"

    @pytest.mark.asyncio
    async def test_auth_failure_returns_none_not_local_marker(self):
        """Image HAS RepoDigests but the latest-tag query fails => generic failure, not local."""
        checker = _make_checker()
        # Current digest is known (image was pulled), so this is a registry image.
        checker._get_container_image_digest = AsyncMock(return_value="sha256:current")
        # Floating-tag resolution fails (e.g. 401 auth) -> registry returns None.
        checker.registry.resolve_tag = AsyncMock(return_value=None)

        container = {
            "host_id": "host-123",
            "id": "abc123def456",
            "name": "private-app",
            "image": "ghcr.io/org/private-app:latest",
            "repo_digests": ["ghcr.io/org/private-app@sha256:current"],
        }

        result = await checker._check_container_update(container, bypass_cache=True)

        assert result is None, "Auth/network failure must stay generic (None), not local_image"

    @pytest.mark.asyncio
    async def test_digest_reference_failure_returns_none_not_local_marker(self):
        """Pinned image@sha256 with no usable digest must not be mislabeled as locally built."""
        checker = _make_checker()
        checker._get_container_image_digest = AsyncMock(return_value=None)

        container = {
            "host_id": "host-123",
            "id": "abc123def456",
            "name": "pinned-app",
            "image": "ghcr.io/org/pinned-app@sha256:deadbeef",
            # No repo_digests, but it's a digest reference - not "locally built"
        }

        result = await checker._check_container_update(container, bypass_cache=True)

        assert result is None, "Digest-pinned failure must stay generic (None), not local_image"
        # The registry fallback must not run for a digest reference.
        checker.registry.resolve_tag.assert_not_called()


class TestCheckSingleContainerPassThrough:
    """check_single_container must surface the local marker without persisting anything."""

    @pytest.mark.asyncio
    async def test_local_marker_passed_through_without_storing(self):
        """A local_image result is returned as-is and never written to the database."""
        checker = _make_checker()
        marker = {"status": "local_image", "current_image": "my-local-app:latest"}

        container = {
            "host_id": "host-123",
            "id": "abc123def456",
            "name": "my-local-app",
            "image": "my-local-app:latest",
        }
        checker._get_container_async = AsyncMock(return_value=container)
        checker._check_container_update = AsyncMock(return_value=marker)
        checker._store_update_info = MagicMock()
        checker._store_local_image_info = MagicMock()
        checker._get_previous_digest = MagicMock(return_value=None)
        checker._create_update_event = AsyncMock()

        result = await checker.check_single_container("host-123", "abc123def456", bypass_cache=True)

        assert result == marker
        # The normal update store + event must be skipped...
        checker._store_update_info.assert_not_called()
        checker._create_update_event.assert_not_called()
        # ...but the lightweight local-image marker is persisted.
        checker._store_local_image_info.assert_called_once()


class TestLocalImagePersistence:
    """A local-image check must persist a row so the UI reflects it after refresh."""

    HOST_ID = "7be442c9-24bc-4047-b33a-41bbf51ea2f9"

    def _seed_host(self, db):
        from database import DockerHostDB
        with db.get_session() as s:
            s.add(DockerHostDB(
                id=self.HOST_ID, name="h",
                url="unix:///var/run/docker.sock", is_active=True,
            ))
            s.commit()

    @pytest.mark.asyncio
    async def test_check_single_container_persists_local_image_row(self, db):
        """check_single_container stamps a ContainerUpdate row for a local image."""
        from database import ContainerUpdate
        self._seed_host(db)

        checker = UpdateChecker(db=db, monitor=MagicMock())
        container = {
            "host_id": self.HOST_ID,
            "id": "abc123def456",
            "name": "local-app",
            "image": "local-app:latest",
        }
        checker._get_container_async = AsyncMock(return_value=container)
        checker._check_container_update = AsyncMock(
            return_value={"status": "local_image", "current_image": "local-app:latest"}
        )

        result = await checker.check_single_container(self.HOST_ID, "abc123def456", bypass_cache=True)

        assert result.get("status") == "local_image"
        composite = f"{self.HOST_ID}:abc123def456"
        with db.get_session() as s:
            rec = s.query(ContainerUpdate).filter_by(container_id=composite).first()
            assert rec is not None, "local-image check must persist a row"
            assert rec.check_status == "local_image"
            assert rec.update_available is False
            assert rec.last_checked_at is not None, "Last checked must be stamped"
            assert rec.current_image == "local-app:latest"

    def test_store_update_info_clears_check_status(self, db):
        """A subsequent normal check clears a stale local_image flag."""
        from database import ContainerUpdate
        self._seed_host(db)
        composite = f"{self.HOST_ID}:abc123def456"
        with db.get_session() as s:
            s.add(ContainerUpdate(
                container_id=composite, host_id=self.HOST_ID,
                current_image="local-app:latest", current_digest="",
                update_available=False, check_status="local_image",
                floating_tag_mode="exact",
            ))
            s.commit()

        checker = UpdateChecker(db=db, monitor=MagicMock())
        container = {"host_id": self.HOST_ID, "id": "abc123def456", "name": "local-app", "image": "local-app:latest"}
        update_info = {
            "current_image": "local-app:latest",
            "current_digest": "sha256:now-resolvable",
            "latest_image": "local-app:latest",
            "latest_digest": "sha256:now-resolvable",
            "update_available": False,
            "registry_url": "docker.io",
            "platform": "linux/amd64",
            "floating_tag_mode": "exact",
            "current_version": None,
            "latest_version": None,
            "changelog_url": None,
            "changelog_source": None,
            "changelog_checked_at": None,
        }

        checker._store_update_info(container, update_info)

        with db.get_session() as s:
            rec = s.query(ContainerUpdate).filter_by(container_id=composite).first()
            assert rec.check_status is None, "normal store must clear the local_image flag"

    def test_store_local_image_info_clears_stale_registry_fields(self, db):
        """A tracked container that becomes local must shed its stale update target."""
        from database import ContainerUpdate
        self._seed_host(db)
        composite = f"{self.HOST_ID}:abc123def456"
        # Pre-existing row from when the image WAS registry-resolvable, with a
        # pending update (the exact state that would otherwise show a phantom update).
        with db.get_session() as s:
            s.add(ContainerUpdate(
                container_id=composite, host_id=self.HOST_ID,
                current_image="myapp:latest", current_digest="sha256:old",
                latest_image="myapp:latest", latest_digest="sha256:new",
                latest_version="2.0.0", update_available=True,
                floating_tag_mode="exact",
            ))
            s.commit()

        checker = UpdateChecker(db=db, monitor=MagicMock())
        container = {"host_id": self.HOST_ID, "id": "abc123def456", "name": "myapp", "image": "myapp:latest"}
        checker._store_local_image_info(container)

        with db.get_session() as s:
            rec = s.query(ContainerUpdate).filter_by(container_id=composite).first()
            assert rec.check_status == "local_image"
            assert rec.update_available is False, "phantom update must be cleared"
            assert rec.latest_image is None
            assert rec.latest_digest is None
            assert rec.latest_version is None

    @pytest.mark.asyncio
    async def test_periodic_check_marks_local_and_clears_phantom_update(self, db):
        """The nightly sweep persists the local marker and clears a stale pending update."""
        from database import ContainerUpdate
        self._seed_host(db)
        composite = f"{self.HOST_ID}:abc123def456"
        # Tracked row with a pending update; the image then becomes locally-built.
        with db.get_session() as s:
            s.add(ContainerUpdate(
                container_id=composite, host_id=self.HOST_ID,
                current_image="myapp:latest", current_digest="sha256:old",
                latest_image="myapp:latest", latest_digest="sha256:new",
                update_available=True, floating_tag_mode="exact",
            ))
            s.commit()

        checker = UpdateChecker(db=db, monitor=MagicMock())
        container = {
            "host_id": self.HOST_ID, "id": "abc123def456",
            "name": "myapp", "image": "myapp:latest", "labels": {},
        }
        checker._get_all_containers = AsyncMock(return_value=[container])
        checker._check_container_update = AsyncMock(
            return_value={"status": "local_image", "current_image": "myapp:latest"}
        )

        stats = await checker.check_all_containers()

        with db.get_session() as s:
            rec = s.query(ContainerUpdate).filter_by(container_id=composite).first()
            assert rec.check_status == "local_image"
            assert rec.update_available is False, "nightly sweep must clear the phantom update"
            assert rec.latest_image is None
        assert stats["checked"] >= 1
