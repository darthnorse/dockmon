"""
Registry failures must be classified transient vs definitive.

A transient failure (429 rate-limit, 5xx, timeout, network) is retryable and must
NOT be confused with a definitive answer (the registry responded 401/403/404). The
update checker uses this distinction so a transient Docker Hub blip on a bare-name
image isn't misread as "built locally" (which would clobber a real pending update).
"""
import asyncio
import pytest
from unittest.mock import patch, AsyncMock

from updates.registry_adapter import RegistryAdapter, TransientRegistryError


class _CM:
    """Minimal async context manager yielding a fixed value."""
    def __init__(self, value):
        self._v = value

    async def __aenter__(self):
        return self._v

    async def __aexit__(self, *a):
        return False


class _FakeResp:
    def __init__(self, status):
        self.status = status
        self.headers = {}

    async def json(self):
        return {}

    async def text(self):
        return ""


class _FakeSession:
    def __init__(self, resp):
        self._resp = resp

    def get(self, *a, **k):
        return _CM(self._resp)


def _patch_session(resp):
    return patch("aiohttp.ClientSession", return_value=_CM(_FakeSession(resp)))


URL = "https://registry.example.com/v2/library/x/manifests/latest"


class TestFetchManifestFailureClass:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [429, 500, 502, 503])
    async def test_transient_statuses_raise(self, status):
        adapter = RegistryAdapter()
        with _patch_session(_FakeResp(status)):
            with pytest.raises(TransientRegistryError):
                await adapter._fetch_manifest(URL, None, "linux/amd64")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [401, 403, 404])
    async def test_definitive_statuses_return_none(self, status):
        adapter = RegistryAdapter()
        with _patch_session(_FakeResp(status)):
            digest, manifest = await adapter._fetch_manifest(URL, None, "linux/amd64")
        assert digest is None and manifest is None

    @pytest.mark.asyncio
    async def test_timeout_raises_transient(self):
        adapter = RegistryAdapter()

        class _BoomSession:
            def get(self, *a, **k):
                raise asyncio.TimeoutError()

        with patch("aiohttp.ClientSession", return_value=_CM(_BoomSession())):
            with pytest.raises(TransientRegistryError):
                await adapter._fetch_manifest(URL, None, "linux/amd64")


class TestResolveTagPropagatesTransient:
    @pytest.mark.asyncio
    async def test_resolve_tag_reraises_transient(self):
        """resolve_tag must NOT swallow a transient failure into None."""
        adapter = RegistryAdapter()
        adapter._get_auth_token = AsyncMock(return_value=None)
        adapter._fetch_manifest = AsyncMock(side_effect=TransientRegistryError("rate limited"))

        with pytest.raises(TransientRegistryError):
            await adapter.resolve_tag("nginx:latest")

    @pytest.mark.asyncio
    async def test_resolve_tag_returns_none_on_definitive(self):
        """A definitive failure (_fetch_manifest returns None) stays None, not an exception."""
        adapter = RegistryAdapter()
        adapter._get_auth_token = AsyncMock(return_value=None)
        adapter._fetch_manifest = AsyncMock(return_value=(None, None))

        result = await adapter.resolve_tag("nginx:latest")
        assert result is None
