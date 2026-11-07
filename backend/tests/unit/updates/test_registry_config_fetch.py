"""Characterization of RegistryAdapter.resolve_tag's manifest and config-blob flow over fake HTTP."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit

import aiohttp
import pytest

from checker_fakes import DOCKER_LIST, DOCKER_MANIFEST, OCI_INDEX, VERSION_LABEL, digest
from updates.registry_adapter import RegistryAdapter

BASE = "https://registry.example.com/v2/org/app"
IMAGE = "registry.example.com/org/app:latest"
OCTET_STREAM = "application/octet-stream"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"

TAG_DIGEST = digest("a")
AMD64 = digest("b")
ARM64 = digest("c")
ATTESTATION = digest("d")
CONFIG = digest("e")
LABELS = {VERSION_LABEL: "1.2.3"}
CONFIG_BLOB = {"config": {"Labels": LABELS}}
DESCRIPTOR = {"mediaType": "application/vnd.docker.container.image.v1+json", "digest": CONFIG}


class FakeResponse:
    """Mimics aiohttp: json() refuses an octet-stream body unless content_type=None."""

    def __init__(self, status=200, body=None, headers=None, content_type="application/json"):
        self.status = status
        self.headers = headers or {}
        self._body = body
        self._content_type = content_type

    async def json(self, content_type="application/json"):
        if content_type is not None and self._content_type == OCTET_STREAM:
            raise aiohttp.ContentTypeError(MagicMock(), (), message="unexpected mimetype")
        return self._body

    async def text(self):
        return str(self._body)


class _RequestContext:
    def __init__(self, outcome):
        self._outcome = outcome

    async def __aenter__(self):
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome

    async def __aexit__(self, *exc_info):
        return False


class FakeHttp:
    """One router and call log shared by every ClientSession the adapter opens."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []
        self.unexpected = []

    def session(self, **_):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    def _request(self, method, url, headers):
        self.requests.append(SimpleNamespace(method=method, url=url, headers=headers or {}))
        if (method, url) not in self.routes:
            self.unexpected.append((method, url))
            return _RequestContext(FakeResponse(status=404))
        return _RequestContext(self.routes[(method, url)])

    def head(self, url, headers=None, **_):
        return self._request("HEAD", url, headers)

    def get(self, url, headers=None, **_):
        return self._request("GET", url, headers)

    def urls(self, method="GET"):
        return [request.url for request in self.requests if request.method == method]

    def get_request(self, url):
        return next(r for r in self.requests if r.method == "GET" and r.url == url)


@pytest.fixture
def http():
    fake = FakeHttp({("HEAD", f"{BASE}/manifests/latest"): FakeResponse()})
    with patch("updates.registry_adapter.aiohttp.ClientSession", fake.session):
        yield fake
    assert fake.unexpected == []


def single_manifest_routes():
    manifest = {"schemaVersion": 2, "mediaType": DOCKER_MANIFEST, "config": DESCRIPTOR}
    return {
        ("GET", f"{BASE}/manifests/latest"): FakeResponse(body=manifest, headers={"Docker-Content-Digest": TAG_DIGEST}),
        ("GET", f"{BASE}/blobs/{CONFIG}"): FakeResponse(body=CONFIG_BLOB, content_type=OCTET_STREAM),
    }


def index_routes(media_type, child_media_type, descriptors=None):
    if descriptors is None:
        descriptors = [
            {"digest": ARM64, "platform": {"os": "linux", "architecture": "arm64"}},
            {"digest": ATTESTATION, "platform": {"os": "unknown", "architecture": "unknown"}},
            {"digest": AMD64, "platform": {"os": "linux", "architecture": "amd64"}},
        ]
    index = {"schemaVersion": 2, "mediaType": media_type, "manifests": descriptors}
    child = {"schemaVersion": 2, "mediaType": child_media_type, "config": DESCRIPTOR}
    return {
        ("GET", f"{BASE}/manifests/latest"): FakeResponse(body=index, headers={"Docker-Content-Digest": TAG_DIGEST}),
        ("GET", f"{BASE}/manifests/{AMD64}"): FakeResponse(body=child),
        ("GET", f"{BASE}/blobs/{CONFIG}"): FakeResponse(body=CONFIG_BLOB, content_type=OCTET_STREAM),
    }


async def test_single_manifest_octet_stream_config_blob_yields_labels(http):
    http.routes.update(single_manifest_routes())

    result = await RegistryAdapter().resolve_tag(IMAGE)

    assert result["digest"] == TAG_DIGEST
    assert result["manifest"]["config"] == CONFIG_BLOB
    assert result["registry"] == "registry.example.com"


@pytest.mark.parametrize("media_type,child_media_type", [
    (DOCKER_LIST, DOCKER_MANIFEST),
    (OCI_INDEX, OCI_MANIFEST),
])
async def test_index_traverses_to_platform_manifest_and_blob(http, media_type, child_media_type):
    http.routes.update(index_routes(media_type, child_media_type))

    result = await RegistryAdapter().resolve_tag(IMAGE)

    assert http.urls() == [f"{BASE}/manifests/latest", f"{BASE}/manifests/{AMD64}", f"{BASE}/blobs/{CONFIG}"]
    assert result["digest"] == TAG_DIGEST
    assert result["manifest"]["config"] == CONFIG_BLOB
    assert result["manifest"]["mediaType"] == media_type


async def test_platform_absent_from_index_keeps_digest_with_empty_config(http):
    arm_only = [{"digest": ARM64, "platform": {"os": "linux", "architecture": "arm64"}}]
    routes = index_routes(DOCKER_LIST, DOCKER_MANIFEST, descriptors=arm_only)
    http.routes[("GET", f"{BASE}/manifests/latest")] = routes[("GET", f"{BASE}/manifests/latest")]

    result = await RegistryAdapter().resolve_tag(IMAGE)

    assert result["digest"] == TAG_DIGEST
    assert result["manifest"]["config"] == {}


@pytest.mark.parametrize("blob_outcome", [
    FakeResponse(status=404),
    asyncio.TimeoutError(),
    RuntimeError("connection reset"),
], ids=["404", "timeout", "exception"])
async def test_single_manifest_blob_failure_keeps_raw_descriptor(http, blob_outcome):
    http.routes.update(single_manifest_routes())
    http.routes[("GET", f"{BASE}/blobs/{CONFIG}")] = blob_outcome

    result = await RegistryAdapter().resolve_tag(IMAGE)

    assert result["digest"] == TAG_DIGEST
    assert result["manifest"]["config"] == DESCRIPTOR


async def test_bearer_token_from_discovery_reaches_manifest_and_blob(http):
    http.routes.update(single_manifest_routes())
    http.routes[("HEAD", f"{BASE}/manifests/latest")] = FakeResponse(
        status=401,
        headers={"WWW-Authenticate": (
            'Bearer realm="https://auth.example.com/token",'
            'service="registry.example.com",scope="repository:org/app:pull"'
        )},
    )
    http.routes[("GET", "https://auth.example.com/token")] = FakeResponse(body={"token": "abc"})

    await RegistryAdapter().resolve_tag(IMAGE)

    assert http.get_request(f"{BASE}/manifests/latest").headers["Authorization"] == "Bearer abc"
    assert http.get_request(f"{BASE}/blobs/{CONFIG}").headers["Authorization"] == "Bearer abc"


async def test_adapter_cache_is_keyed_by_ref_and_platform(http):
    http.routes.update(single_manifest_routes())
    adapter = RegistryAdapter()

    first = await adapter.resolve_tag(IMAGE)
    requests_after_first = len(http.requests)
    second = await adapter.resolve_tag(IMAGE)

    assert second == first
    assert len(http.requests) == requests_after_first

    await adapter.resolve_tag(IMAGE, platform="linux/arm64")

    assert len(http.requests) > requests_after_first


CREDENTIALS = {"username": "robot", "password": "secret"}
HUB_MANIFEST_HOST = "registry.hub.docker.com"


class AnyHostHttp(FakeHttp):
    """A registry that answers on any host and never challenges, so token fallbacks run."""

    def __init__(self):
        super().__init__({})

    def _request(self, method, url, headers):
        self.requests.append(SimpleNamespace(method=method, url=url, headers=headers or {}))
        if method == "HEAD":
            return _RequestContext(FakeResponse())
        if "/token" in url:
            return _RequestContext(FakeResponse(body={"token": "abc"}))
        if "/blobs/" in url:
            return _RequestContext(FakeResponse(body=CONFIG_BLOB, content_type=OCTET_STREAM))
        manifest = {"schemaVersion": 2, "mediaType": DOCKER_MANIFEST, "config": DESCRIPTOR}
        return _RequestContext(FakeResponse(body=manifest, headers={"Docker-Content-Digest": TAG_DIGEST}))

    def hosts_sent_credentials(self):
        return {urlsplit(r.url).netloc for r in self.requests if r.headers.get("Authorization")}

    def manifest_hosts(self):
        return {urlsplit(r.url).netloc for r in self.requests if r.method == "GET" and "/manifests/" in r.url}


async def resolve_with_credentials(image, mode):
    adapter = RegistryAdapter()
    fake = AnyHostHttp()
    with patch("updates.registry_adapter.aiohttp.ClientSession", fake.session):
        result = await adapter.resolve_tag(adapter.compute_floating_tag(image, mode), auth=CREDENTIALS)
    assert result is not None
    return fake


@pytest.mark.parametrize("image", [
    "docker.io/library/nginx:1",
    "index.docker.io/library/nginx:1",
    "registry-1.docker.io/library/nginx:1",
    "registry.docker.io/library/nginx:1",
    "registry.hub.docker.com/library/nginx:1",
    "DOCKER.IO/library/nginx:1",
    "docker.io:443/library/nginx:1",
    "nginx:1",
])
async def test_docker_hub_credentials_go_only_to_docker_hub(image):
    fake = await resolve_with_credentials(image, "exact")

    assert fake.hosts_sent_credentials() == {"auth.docker.io", HUB_MANIFEST_HOST}
    assert fake.manifest_hosts() == {HUB_MANIFEST_HOST}


async def test_ghcr_credentials_go_only_to_ghcr():
    fake = await resolve_with_credentials("ghcr.io/org/app:1", "exact")

    assert fake.hosts_sent_credentials() == {"ghcr.io"}
    assert fake.manifest_hosts() == {"ghcr.io"}


@pytest.mark.parametrize("image,mode,host", [
    ("notdocker.io/org/app:1", "exact", "notdocker.io"),
    ("registry.docker.io.corp.example/org/app:1", "exact", "registry.docker.io.corp.example"),
    ("registry.hub.docker.com.corp.example/org/app:1", "exact", "registry.hub.docker.com.corp.example"),
    ("myghcr.io/org/app:1", "exact", "myghcr.io"),
    ("ghcr.io.corp.example/org/app:1", "exact", "ghcr.io.corp.example"),
    ("registry.example.com:5000/org/app:1", "exact", "registry.example.com:5000"),
    ("docker.io:5000/org/app:1", "exact", "docker.io:5000"),
    ("registry:5000/app", "latest", "registry:5000"),
])
async def test_credentials_stay_on_any_other_registry(image, mode, host):
    fake = await resolve_with_credentials(image, mode)

    assert fake.hosts_sent_credentials() == {host}
    assert fake.manifest_hosts() == {host}


@pytest.mark.parametrize("registry", ["docker.io", "https://docker.io", "http://docker.io/", "DOCKER.IO:443"])
def test_docker_hub_url_normalization_accepts_scheme_case_and_default_port(registry):
    assert RegistryAdapter()._normalize_registry_url(registry) == f"https://{HUB_MANIFEST_HOST}"


async def test_credentials_still_reach_a_token_service_on_another_https_host(http):
    http.routes.update(single_manifest_routes())
    http.routes[("HEAD", f"{BASE}/manifests/latest")] = FakeResponse(
        status=401,
        headers={"WWW-Authenticate": (
            'Bearer realm="https://auth.example.com/token",'
            'service="registry.example.com",scope="repository:org/app:pull"'
        )},
    )
    http.routes[("GET", "https://auth.example.com/token")] = FakeResponse(body={"token": "abc"})

    await RegistryAdapter().resolve_tag(IMAGE, auth=CREDENTIALS)

    assert http.get_request("https://auth.example.com/token").headers["Authorization"].startswith("Basic ")
    assert http.get_request(f"{BASE}/manifests/latest").headers["Authorization"] == "Bearer abc"
