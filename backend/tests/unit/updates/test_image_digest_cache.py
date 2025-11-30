"""
Tests for Image Digest Cache functionality.

Tests the database-backed cache layer that reduces registry API calls
by caching digest lookups by image:tag:platform.

Issue #62: Registry rate limit handling
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from database import DatabaseManager, ImageDigestCache
from updates.update_checker import UpdateChecker, CACHE_TTL_LATEST, CACHE_TTL_PINNED, CACHE_TTL_FLOATING, CACHE_TTL_DEFAULT


@pytest.fixture
def db_manager(db_session):
    """Create a DatabaseManager that uses the test session."""
    db = MagicMock(spec=DatabaseManager)

    # Wire up the session
    db.get_session.return_value.__enter__ = MagicMock(return_value=db_session)
    db.get_session.return_value.__exit__ = MagicMock(return_value=False)

    return db


@pytest.fixture
def real_db_manager(db_engine):
    """Create a real DatabaseManager for integration tests."""
    from sqlalchemy.orm import sessionmaker, scoped_session
    from contextlib import contextmanager
    import logging

    # Create session factory
    SessionLocal = scoped_session(sessionmaker(bind=db_engine))

    class TestDatabaseManager:
        """Minimal DatabaseManager for testing cache methods."""

        def __init__(self):
            self.SessionLocal = SessionLocal

        @contextmanager
        def get_session(self):
            session = self.SessionLocal()
            try:
                yield session
            finally:
                session.close()

        def get_cached_image_digest(self, cache_key):
            """Get cached digest if not expired."""
            from datetime import datetime, timedelta, timezone
            with self.get_session() as session:
                entry = session.query(ImageDigestCache).filter_by(
                    cache_key=cache_key
                ).first()

                if not entry:
                    return None

                # Check if expired
                # Handle both naive and aware datetimes from SQLite
                now = datetime.now(timezone.utc)
                checked_at = entry.checked_at
                if checked_at.tzinfo is None:
                    checked_at = checked_at.replace(tzinfo=timezone.utc)
                expires_at = checked_at + timedelta(seconds=entry.ttl_seconds)

                if now > expires_at:
                    return None

                return {
                    "digest": entry.latest_digest,
                    "manifest_json": entry.manifest_json,
                    "registry_url": entry.registry_url,
                }

        def cache_image_digest(self, cache_key, digest, manifest_json, registry_url, ttl_seconds):
            """Store or update cached digest."""
            from datetime import datetime, timezone
            with self.get_session() as session:
                entry = session.query(ImageDigestCache).filter_by(
                    cache_key=cache_key
                ).first()

                now = datetime.now(timezone.utc)

                if entry:
                    entry.latest_digest = digest
                    entry.manifest_json = manifest_json
                    entry.registry_url = registry_url
                    entry.ttl_seconds = ttl_seconds
                    entry.checked_at = now
                    entry.updated_at = now
                else:
                    entry = ImageDigestCache(
                        cache_key=cache_key,
                        latest_digest=digest,
                        manifest_json=manifest_json,
                        registry_url=registry_url,
                        ttl_seconds=ttl_seconds,
                        checked_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(entry)

                session.commit()

        def invalidate_image_cache(self, image_pattern):
            """Invalidate cache entries matching pattern."""
            with self.get_session() as session:
                entries = session.query(ImageDigestCache).filter(
                    ImageDigestCache.cache_key.like(f"{image_pattern}%")
                ).all()

                count = len(entries)
                for entry in entries:
                    session.delete(entry)

                session.commit()
                return count

        def cleanup_expired_image_cache(self):
            """Remove all expired cache entries."""
            from datetime import datetime, timedelta, timezone
            with self.get_session() as session:
                now = datetime.now(timezone.utc)
                all_entries = session.query(ImageDigestCache).all()
                expired = []

                for entry in all_entries:
                    # Handle both naive and aware datetimes from SQLite
                    checked_at = entry.checked_at
                    if checked_at.tzinfo is None:
                        checked_at = checked_at.replace(tzinfo=timezone.utc)
                    expires_at = checked_at + timedelta(seconds=entry.ttl_seconds)
                    if now > expires_at:
                        expired.append(entry)

                for entry in expired:
                    session.delete(entry)

                session.commit()
                return len(expired)

    return TestDatabaseManager()


class TestImageDigestCacheTTL:
    """Test TTL computation based on tag patterns."""

    def test_latest_tag_gets_short_ttl(self):
        """Tags with :latest should get short TTL (configurable via DOCKMON_CACHE_TTL_LATEST)."""
        db = MagicMock(spec=DatabaseManager)
        checker = UpdateChecker(db)

        ttl = checker._compute_cache_ttl_seconds("nginx:latest")
        assert ttl == CACHE_TTL_LATEST

    def test_pinned_version_gets_long_ttl(self):
        """Pinned versions like 1.25.3 should get long TTL (configurable via DOCKMON_CACHE_TTL_PINNED)."""
        db = MagicMock(spec=DatabaseManager)
        checker = UpdateChecker(db)

        # Standard semver
        assert checker._compute_cache_ttl_seconds("nginx:1.25.3") == CACHE_TTL_PINNED
        # With v prefix
        assert checker._compute_cache_ttl_seconds("app:v2.0.1") == CACHE_TTL_PINNED
        # Four-part version
        assert checker._compute_cache_ttl_seconds("app:1.2.3.4") == CACHE_TTL_PINNED

    def test_floating_minor_gets_medium_ttl(self):
        """Floating minor tags like 1.25 should get medium TTL (configurable via DOCKMON_CACHE_TTL_FLOATING)."""
        db = MagicMock(spec=DatabaseManager)
        checker = UpdateChecker(db)

        # Minor version
        assert checker._compute_cache_ttl_seconds("nginx:1.25") == CACHE_TTL_FLOATING
        # Major version only
        assert checker._compute_cache_ttl_seconds("nginx:1") == CACHE_TTL_FLOATING

    def test_non_semver_tags_get_default_ttl(self):
        """Non-semver tags should get default TTL (configurable via DOCKMON_CACHE_TTL_DEFAULT)."""
        db = MagicMock(spec=DatabaseManager)
        checker = UpdateChecker(db)

        assert checker._compute_cache_ttl_seconds("nginx:alpine") == CACHE_TTL_DEFAULT
        assert checker._compute_cache_ttl_seconds("nginx:stable") == CACHE_TTL_DEFAULT
        assert checker._compute_cache_ttl_seconds("nginx:bullseye") == CACHE_TTL_DEFAULT

    def test_registry_prefix_handled(self):
        """Full image refs with registry should work correctly."""
        db = MagicMock(spec=DatabaseManager)
        checker = UpdateChecker(db)

        # GHCR with latest
        assert checker._compute_cache_ttl_seconds("ghcr.io/org/app:latest") == CACHE_TTL_LATEST
        # Docker Hub with pinned
        assert checker._compute_cache_ttl_seconds("docker.io/library/nginx:1.25.3") == CACHE_TTL_PINNED


class TestImageDigestCacheDatabase:
    """Test database CRUD operations for cache."""

    def test_get_cached_digest_returns_none_when_missing(self, real_db_manager):
        """Cache miss should return None."""
        result = real_db_manager.get_cached_image_digest("nginx:1.25:linux/amd64")
        assert result is None

    def test_get_cached_digest_returns_data_when_valid(self, real_db_manager):
        """Valid cache entry should return digest data."""
        # Insert cache entry directly
        with real_db_manager.get_session() as session:
            cache_entry = ImageDigestCache(
                cache_key="nginx:1.25:linux/amd64",
                latest_digest="sha256:abc123",
                registry_url="https://registry.hub.docker.com",
                manifest_json='{"config": {}}',
                ttl_seconds=6 * 3600,
                checked_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(cache_entry)
            session.commit()

        result = real_db_manager.get_cached_image_digest("nginx:1.25:linux/amd64")
        assert result is not None
        assert result["digest"] == "sha256:abc123"
        assert result["registry_url"] == "https://registry.hub.docker.com"

    def test_get_cached_digest_returns_none_when_expired(self, real_db_manager):
        """Expired cache entry should return None."""
        # Insert expired cache entry (checked 7 hours ago with 6 hour TTL)
        with real_db_manager.get_session() as session:
            cache_entry = ImageDigestCache(
                cache_key="nginx:1.25:linux/amd64",
                latest_digest="sha256:abc123",
                registry_url="https://registry.hub.docker.com",
                manifest_json='{"config": {}}',
                ttl_seconds=6 * 3600,
                checked_at=datetime.now(timezone.utc) - timedelta(hours=7),
                created_at=datetime.now(timezone.utc) - timedelta(hours=7),
                updated_at=datetime.now(timezone.utc) - timedelta(hours=7),
            )
            session.add(cache_entry)
            session.commit()

        result = real_db_manager.get_cached_image_digest("nginx:1.25:linux/amd64")
        assert result is None

    def test_cache_image_digest_creates_new_entry(self, real_db_manager):
        """Caching digest should create new entry."""
        real_db_manager.cache_image_digest(
            cache_key="nginx:1.25:linux/amd64",
            digest="sha256:abc123",
            manifest_json='{"config": {}}',
            registry_url="https://registry.hub.docker.com",
            ttl_seconds=6 * 3600
        )

        # Verify entry exists
        with real_db_manager.get_session() as session:
            entry = session.query(ImageDigestCache).filter_by(
                cache_key="nginx:1.25:linux/amd64"
            ).first()
            assert entry is not None
            assert entry.latest_digest == "sha256:abc123"

    def test_cache_image_digest_updates_existing_entry(self, real_db_manager):
        """Caching digest should update existing entry (upsert)."""
        # Create initial entry
        real_db_manager.cache_image_digest(
            cache_key="nginx:1.25:linux/amd64",
            digest="sha256:old",
            manifest_json='{}',
            registry_url="https://registry.hub.docker.com",
            ttl_seconds=6 * 3600
        )

        # Update with new digest
        real_db_manager.cache_image_digest(
            cache_key="nginx:1.25:linux/amd64",
            digest="sha256:new",
            manifest_json='{"updated": true}',
            registry_url="https://registry.hub.docker.com",
            ttl_seconds=6 * 3600
        )

        # Verify only one entry with new digest
        with real_db_manager.get_session() as session:
            entries = session.query(ImageDigestCache).filter_by(
                cache_key="nginx:1.25:linux/amd64"
            ).all()
            assert len(entries) == 1
            assert entries[0].latest_digest == "sha256:new"

    def test_invalidate_image_cache_deletes_matching_entries(self, real_db_manager):
        """Invalidating cache should delete matching entries."""
        # Create multiple entries
        with real_db_manager.get_session() as session:
            for tag in ["1.25", "1.26", "latest"]:
                cache_entry = ImageDigestCache(
                    cache_key=f"nginx:{tag}:linux/amd64",
                    latest_digest=f"sha256:{tag}",
                    ttl_seconds=6 * 3600,
                    checked_at=datetime.now(timezone.utc),
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(cache_entry)
            session.commit()

        # Invalidate nginx:1.25
        count = real_db_manager.invalidate_image_cache("nginx:1.25")
        assert count == 1

        # Verify only that entry was deleted
        with real_db_manager.get_session() as session:
            remaining = session.query(ImageDigestCache).all()
            assert len(remaining) == 2
            keys = [e.cache_key for e in remaining]
            assert "nginx:1.25:linux/amd64" not in keys

    def test_cleanup_expired_image_cache(self, real_db_manager):
        """Cleanup should remove all expired entries."""
        now = datetime.now(timezone.utc)

        # Create expired and valid entries
        with real_db_manager.get_session() as session:
            # Expired entry (7 hours old with 6 hour TTL)
            expired = ImageDigestCache(
                cache_key="nginx:old:linux/amd64",
                latest_digest="sha256:old",
                ttl_seconds=6 * 3600,
                checked_at=now - timedelta(hours=7),
                created_at=now - timedelta(hours=7),
                updated_at=now - timedelta(hours=7),
            )

            # Valid entry
            valid = ImageDigestCache(
                cache_key="nginx:new:linux/amd64",
                latest_digest="sha256:new",
                ttl_seconds=6 * 3600,
                checked_at=now - timedelta(hours=1),
                created_at=now - timedelta(hours=1),
                updated_at=now - timedelta(hours=1),
            )

            session.add(expired)
            session.add(valid)
            session.commit()

        # Cleanup
        count = real_db_manager.cleanup_expired_image_cache()
        assert count == 1

        # Verify only valid entry remains
        with real_db_manager.get_session() as session:
            remaining = session.query(ImageDigestCache).all()
            assert len(remaining) == 1
            assert remaining[0].cache_key == "nginx:new:linux/amd64"


class TestUpdateCheckerCacheIntegration:
    """Test update checker integration with cache layer."""

    @pytest.mark.asyncio
    async def test_cache_miss_calls_registry(self):
        """When cache misses, registry should be called."""
        db = MagicMock(spec=DatabaseManager)
        db.get_cached_image_digest.return_value = None

        checker = UpdateChecker(db)
        checker.registry = MagicMock()
        checker.registry.resolve_tag = AsyncMock(return_value={
            "digest": "sha256:abc123",
            "manifest": {"config": {}},
            "registry": "https://registry.hub.docker.com",
            "repository": "library/nginx",
            "tag": "1.25",
        })
        checker.registry.compute_floating_tag = MagicMock(return_value="nginx:1.25")

        # Mock other dependencies
        checker.monitor = MagicMock()
        checker._get_container_image_digest = AsyncMock(return_value="sha256:old")
        checker._get_container_image_version = AsyncMock(return_value="1.25.0")

        container = {
            "host_id": "host-123",
            "id": "abc123def456",
            "name": "test-nginx",
            "image": "nginx:1.25",
        }

        result = await checker._check_container_update(container)

        # Verify registry was called
        checker.registry.resolve_tag.assert_called_once()
        # Verify result returned
        assert result is not None
        assert result["latest_digest"] == "sha256:abc123"

    @pytest.mark.asyncio
    async def test_cache_hit_skips_registry(self):
        """When cache hits, registry should NOT be called."""
        db = MagicMock(spec=DatabaseManager)
        db.get_cached_image_digest.return_value = {
            "digest": "sha256:cached123",
            "manifest_json": '{"config": {"config": {"Labels": {}}}}',
            "registry_url": "https://registry.hub.docker.com",
        }

        checker = UpdateChecker(db)
        checker.registry = MagicMock()
        checker.registry.resolve_tag = AsyncMock()
        checker.registry.compute_floating_tag = MagicMock(return_value="nginx:1.25")

        # Mock other dependencies
        checker.monitor = MagicMock()
        checker._get_container_image_digest = AsyncMock(return_value="sha256:old")
        checker._get_container_image_version = AsyncMock(return_value="1.25.0")

        container = {
            "host_id": "host-123",
            "id": "abc123def456",
            "name": "test-nginx",
            "image": "nginx:1.25",
        }

        result = await checker._check_container_update(container)

        # Verify registry was NOT called
        checker.registry.resolve_tag.assert_not_called()
        # Verify cached result used
        assert result is not None
        assert result["latest_digest"] == "sha256:cached123"

    @pytest.mark.asyncio
    async def test_cache_stores_result_on_registry_success(self):
        """After successful registry call, result should be cached."""
        db = MagicMock(spec=DatabaseManager)
        db.get_cached_image_digest.return_value = None

        checker = UpdateChecker(db)
        checker.registry = MagicMock()
        checker.registry.resolve_tag = AsyncMock(return_value={
            "digest": "sha256:abc123",
            "manifest": {"config": {}},
            "registry": "https://registry.hub.docker.com",
            "repository": "library/nginx",
            "tag": "1.25",
        })
        checker.registry.compute_floating_tag = MagicMock(return_value="nginx:1.25")

        # Mock other dependencies
        checker.monitor = MagicMock()
        checker._get_container_image_digest = AsyncMock(return_value="sha256:old")
        checker._get_container_image_version = AsyncMock(return_value="1.25.0")

        container = {
            "host_id": "host-123",
            "id": "abc123def456",
            "name": "test-nginx",
            "image": "nginx:1.25",
        }

        await checker._check_container_update(container)

        # Verify cache was written
        db.cache_image_digest.assert_called_once()
        call_args = db.cache_image_digest.call_args
        assert "nginx:1.25" in call_args[1]["cache_key"] or call_args[0][0]
        assert "sha256:abc123" in str(call_args)

    @pytest.mark.asyncio
    async def test_multiple_containers_same_image_one_request(self):
        """Multiple containers with same image should make only one registry request."""
        db = MagicMock(spec=DatabaseManager)
        # First call: cache miss, subsequent calls: cache hit
        db.get_cached_image_digest.side_effect = [
            None,  # First container - miss
            {"digest": "sha256:abc123", "manifest_json": '{}', "registry_url": "https://reg"},  # Second - hit
            {"digest": "sha256:abc123", "manifest_json": '{}', "registry_url": "https://reg"},  # Third - hit
        ]

        checker = UpdateChecker(db)
        checker.registry = MagicMock()
        checker.registry.resolve_tag = AsyncMock(return_value={
            "digest": "sha256:abc123",
            "manifest": {"config": {}},
            "registry": "https://registry.hub.docker.com",
            "repository": "library/nginx",
            "tag": "1.25",
        })
        checker.registry.compute_floating_tag = MagicMock(return_value="nginx:1.25")

        # Mock other dependencies
        checker.monitor = MagicMock()
        checker._get_container_image_digest = AsyncMock(return_value="sha256:old")
        checker._get_container_image_version = AsyncMock(return_value="1.25.0")

        # Three containers with same image (12-char container IDs as required)
        containers = [
            {"host_id": "host-123", "id": f"abc12345{i:04d}", "name": f"nginx-{i}", "image": "nginx:1.25"}
            for i in range(3)
        ]

        for container in containers:
            await checker._check_container_update(container)

        # Verify registry was called only once
        assert checker.registry.resolve_tag.call_count == 1

    @pytest.mark.asyncio
    async def test_database_error_falls_through_to_registry(self):
        """Database errors should fall through to registry call."""
        db = MagicMock(spec=DatabaseManager)
        db.get_cached_image_digest.side_effect = Exception("Database error")

        checker = UpdateChecker(db)
        checker.registry = MagicMock()
        checker.registry.resolve_tag = AsyncMock(return_value={
            "digest": "sha256:abc123",
            "manifest": {"config": {}},
            "registry": "https://registry.hub.docker.com",
            "repository": "library/nginx",
            "tag": "1.25",
        })
        checker.registry.compute_floating_tag = MagicMock(return_value="nginx:1.25")

        # Mock other dependencies
        checker.monitor = MagicMock()
        checker._get_container_image_digest = AsyncMock(return_value="sha256:old")
        checker._get_container_image_version = AsyncMock(return_value="1.25.0")

        container = {
            "host_id": "host-123",
            "id": "abc123def456",
            "name": "test-nginx",
            "image": "nginx:1.25",
        }

        # Should not raise, should fall through to registry
        result = await checker._check_container_update(container)

        # Verify registry was called despite DB error
        checker.registry.resolve_tag.assert_called_once()
        assert result is not None


class TestCacheInvalidationAfterUpdate:
    """Test that cache is invalidated after successful container update."""

    def test_cache_invalidated_after_successful_update(self):
        """After update completes, old image cache should be invalidated."""
        # This test verifies update_executor.py calls db.invalidate_image_cache()
        # Will be implemented when we modify update_executor.py
        pass  # Placeholder - will implement in GREEN phase
