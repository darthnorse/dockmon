"""Characterization of the adapter's tag arithmetic and image-ref parsing."""

import pytest

from updates.registry_adapter import RegistryAdapter

DIGEST_REF = "app@sha256:" + "a" * 64


@pytest.mark.parametrize("image,exact,patch,minor,latest", [
    ("nginx:1.25.3", "nginx:1.25.3", "nginx:1.25", "nginx:1", "nginx:latest"),
    ("nginx:1.25.3-alpine", "nginx:1.25.3-alpine", "nginx:1.25-alpine", "nginx:1-alpine", "nginx:latest"),
    ("nginx:1.25", "nginx:1.25", "nginx:1.25", "nginx:1", "nginx:latest"),
    ("nginx:stable", "nginx:stable", "nginx:stable", "nginx:stable", "nginx:latest"),
    ("nginx", "nginx:latest", "nginx:latest", "nginx:latest", "nginx:latest"),
    ("registry:5000/app:1.2.3", "registry:5000/app:1.2.3", "registry:5000/app:1.2", "registry:5000/app:1",
     "registry:5000/app:latest"),
    ("registry:5000/app", "registry:5000/app:latest", "registry:5000/app:latest", "registry:5000/app:latest",
     "registry:5000/app:latest"),
    ("localhost:5000/org/app", "localhost:5000/org/app:latest", "localhost:5000/org/app:latest",
     "localhost:5000/org/app:latest", "localhost:5000/org/app:latest"),
])
def test_floating_tag_table(image, exact, patch, minor, latest):
    adapter = RegistryAdapter()
    computed = [adapter.compute_floating_tag(image, mode) for mode in ("exact", "patch", "minor", "latest")]
    assert computed == [exact, patch, minor, latest]


# The rows below pin defects rather than intent: the v prefix is dropped and a digest is read as a tag.
@pytest.mark.parametrize("image,mode,expected", [
    ("nginx:v1.25.3", "exact", "nginx:v1.25.3"),
    ("nginx:v1.25.3", "patch", "nginx:1.25"),
    ("nginx:v1.25.3", "minor", "nginx:1"),
    (DIGEST_REF, "exact", DIGEST_REF),
    (DIGEST_REF, "patch", DIGEST_REF),
    (DIGEST_REF, "latest", "app@sha256:latest"),
])
def test_floating_tag_mishandled_refs_known_gap(image, mode, expected):
    assert RegistryAdapter().compute_floating_tag(image, mode) == expected


@pytest.mark.parametrize("image,expected", [
    ("nginx:1.25", ("docker.io", "library/nginx", "1.25")),
    ("nginx", ("docker.io", "library/nginx", "latest")),
    ("ghcr.io/user/app:v1.0", ("ghcr.io", "user/app", "v1.0")),
    ("myregistry.com:5000/app", ("myregistry.com:5000", "app", "latest")),
    ("registry:5000/app:1.2", ("registry:5000", "app", "1.2")),
    ("user/app:tag", ("docker.io", "user/app", "tag")),
    ("localhost/app", ("localhost", "app", "latest")),
    ("index.docker.io/nginx:1", ("index.docker.io", "library/nginx", "1")),
    ("DOCKER.IO/nginx:1", ("DOCKER.IO", "library/nginx", "1")),
    ("docker.io:443/nginx:1", ("docker.io:443", "library/nginx", "1")),
])
def test_parse_image_ref(image, expected):
    assert RegistryAdapter()._parse_image_ref(image) == expected


@pytest.mark.parametrize("image", [DIGEST_REF, "sha256:" + "a" * 64])
def test_parse_image_ref_rejects_digests(image):
    with pytest.raises(ValueError):
        RegistryAdapter()._parse_image_ref(image)
