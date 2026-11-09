"""Boundary doubles for driving the real UpdateChecker in characterization tests."""

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from docker.errors import ImageNotFound

from database import ContainerUpdate
from updates.registry_adapter import RegistryAdapter
from updates.update_checker import UpdateChecker

HOST_ID = "7be442c9-24bc-4047-b33a-41bbf51ea2f9"
CONTAINER_ID = "abc123def456"
VERSION_LABEL = "org.opencontainers.image.version"
DOCKER_LIST = "application/vnd.docker.distribution.manifest.list.v2+json"
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
DOCKER_MANIFEST = "application/vnd.docker.distribution.manifest.v2+json"
CHANGELOG_URL = "https://example.com/changelog"
CHANGELOG_CHECKED_AT = datetime(2026, 1, 2, tzinfo=timezone.utc)


def digest(char: str) -> str:
    return "sha256:" + char * 64


CURRENT = digest("a")
LATEST = digest("b")
AMD64_CHILD = digest("c")
ARM64_CHILD = digest("d")
LATEST_CONFIG = digest("e")
STALE_IMAGE_ID = digest("f")
LOCAL_IMAGE_ID = digest("1")


def index_manifest(amd64=AMD64_CHILD, arm64=ARM64_CHILD, media_type=DOCKER_LIST):
    """Index whose non-matching descriptors come before the amd64 one, as registries publish them."""
    manifests = [
        {"digest": arm64, "platform": {"os": "linux", "architecture": "arm64"}},
        {"digest": digest("9"), "platform": {"os": "unknown", "architecture": "unknown"}},
    ]
    if amd64:
        manifests.append({"digest": amd64, "platform": {"os": "linux", "architecture": "amd64"}})
    return {"schemaVersion": 2, "mediaType": media_type, "manifests": manifests}


def registry_result(result_digest, labels=None, manifest=None, config_digest=None, registry="docker.io"):
    """config_digest is ignored by production today; image-ID comparison will read it."""
    body = dict(manifest or {"schemaVersion": 2, "mediaType": DOCKER_MANIFEST})
    body["config"] = {"config": {"Labels": labels or {}}}
    if config_digest:
        body["config_digest"] = config_digest
    return {"digest": result_digest, "manifest": body, "registry": registry}


class FakeRegistry:
    """Routes resolve_tag by image ref; compute_floating_tag is the real one.

    Unrouted refs are recorded rather than raised because production swallows
    exceptions on the fallback path.
    """

    def __init__(self, routes):
        self._routes = routes
        self.compute_floating_tag = RegistryAdapter().compute_floating_tag
        self.calls = []
        self.unexpected = []

    async def resolve_tag(self, image_ref, **kwargs):
        self.calls.append((image_ref, kwargs))
        if image_ref not in self._routes:
            self.unexpected.append(image_ref)
            return None
        route = self._routes[image_ref]
        if isinstance(route, Exception):
            raise route
        return route

    def refs(self):
        return [ref for ref, _ in self.calls]


class _Query:
    def __init__(self, record):
        self._record = record

    def filter_by(self, **_):
        return self

    def first(self):
        return self._record


class _Session:
    def __init__(self, record):
        self._record = record

    def query(self, model):
        assert model is ContainerUpdate, f"unrouted query for {model}"
        return _Query(self._record)


class FakeDb:
    def __init__(self, record=None, cached=None):
        self._record = record
        self.get_cached_image_digest = MagicMock(return_value=cached)
        self.cache_image_digest = MagicMock()

    @contextmanager
    def get_session(self):
        yield _Session(self._record)


def evidence(image_id, ref="app:latest", platform="linux/amd64"):
    return json.dumps({"image_id": image_id, "platform": platform, "ref": ref}, sort_keys=True)


def update_record(mode="exact", verified_image=None):
    return SimpleNamespace(
        floating_tag_mode=mode,
        verified_image=verified_image,
        changelog_url=None,
        changelog_source=None,
        changelog_checked_at=None,
    )


class FakeImage:
    def __init__(self, image_id, repo_digests, labels, image_os, architecture, variant):
        self.id = image_id
        self.attrs = {
            "RepoDigests": repo_digests,
            "Config": {"Labels": labels},
            "Os": image_os,
            "Architecture": architecture,
        }
        if variant:
            self.attrs["Variant"] = variant


class _Images:
    def __init__(self, images):
        self._images = images
        self.requested = []

    def get(self, image_hash):
        self.requested.append(image_hash)
        if image_hash not in self._images:
            raise ImageNotFound(f"No such image: {image_hash}")
        return self._images[image_hash]


class FakeContainer:
    def __init__(self, client, attrs):
        self._client = client
        self.attrs = attrs

    @property
    def image(self):
        image_id = self.attrs.get("ImageID", self.attrs["Image"])
        return self._client.images.get(image_id.split(":")[1])


class _Containers:
    def __init__(self, container):
        self._container = container
        self.requested = []

    def get(self, container_id):
        self.requested.append(container_id)
        return self._container


class FakeClient:
    def __init__(self, image_id=LOCAL_IMAGE_ID, repo_digests=(), image_labels=None, image_missing=False,
                 image_os="linux", architecture="amd64", variant=None):
        images = {}
        if not image_missing:
            images[image_id.split(":")[1]] = FakeImage(
                image_id, list(repo_digests), image_labels or {}, image_os, architecture, variant
            )
        self.images = _Images(images)
        self.containers = _Containers(FakeContainer(self, {"Image": image_id}))


def make_monitor(client=None, containers=()):
    return SimpleNamespace(
        clients={HOST_ID: client} if client else {},
        hosts={HOST_ID: SimpleNamespace(name="docker-1")},
        get_containers=AsyncMock(return_value=list(containers)),
    )


def make_checker(routes, client=None, record=None, cached=None):
    checker = UpdateChecker(db=FakeDb(record=record, cached=cached), monitor=make_monitor(client))
    checker.registry = FakeRegistry(routes)
    return checker


def container_dict(image="app:stable", **overrides):
    container = {"host_id": HOST_ID, "id": CONTAINER_ID, "name": "app", "image": image, "labels": {}}
    container.update(overrides)
    return container


def monitored_container(container):
    """What monitor.get_containers() yields: id fields, and a .dict() that omits the excluded image_id."""
    return SimpleNamespace(
        host_id=container["host_id"],
        id=container["id"],
        short_id=container["id"][:12],
        image_id=container.get("image_id"),
        dict=lambda: {key: value for key, value in container.items() if key != "image_id"},
    )
