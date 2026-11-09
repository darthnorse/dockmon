"""
Image Reference Parsing Utilities

A Docker image reference has the form:

    [registry[:port]/]repository[:tag][@digest]

This module extracts the repository (the image *name*) from a reference,
discarding the registry host, tag, and digest. It is used by update-policy
pattern matching so a pattern such as 'nginx' is tested against the image
name only - never against the tag (e.g. the ':nginx' tag on
'ghcr.io/aalmenar/baikal:nginx') or against the registry host (e.g. 'docker'
in 'docker.io/...').

Unlike registry_adapter._parse_image_ref, this runs in the update-check hot
loop and is intentionally total: it never raises, returning "" for input it
cannot parse into a repository name.
"""

import re
from typing import Optional

SHA256_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def is_registry_host(segment: str) -> bool:
    """True if a reference's first path segment is a registry, not a Docker Hub namespace.

    Matches Docker's own parsing, including that an uppercase segment is a registry.
    """
    return "." in segment or ":" in segment or segment == "localhost" or segment.lower() != segment


def has_tag(image_ref: str) -> bool:
    """True if the reference has a tag or digest. A colon before the last slash is a registry port."""
    return image_ref.rfind(":") > image_ref.rfind("/")


def with_implicit_latest(image_ref: str) -> str:
    return image_ref if has_tag(image_ref) else f"{image_ref}:latest"


def extract_image_repository(image_ref: Optional[str]) -> str:
    """Extract the repository (image name) from a full image reference.

    Strips the registry host, tag, and digest. Case is preserved; callers
    fold case themselves.

    Examples:
        nginx:1.25                       -> nginx
        ghcr.io/aalmenar/baikal:nginx    -> aalmenar/baikal
        docker.io/library/postgres:16    -> library/postgres
        myregistry.com:5000/app          -> app
        ghcr.io/org/app@sha256:abc...     -> org/app
        sha256:abc... (bare digest)       -> "" (no name available)
    """
    if not image_ref:
        return ""

    # Drop the digest (everything from '@' onwards).
    ref = image_ref.split("@", 1)[0]

    # A bare digest reference carries no image name.
    if ref.startswith("sha256:"):
        return ""

    # Drop the registry host. The first path segment is a registry only if it
    # looks like a hostname - it contains a '.' or ':' (port) or is 'localhost'.
    # Otherwise it's a Docker Hub namespace and part of the repository.
    if "/" in ref:
        head, rest = ref.split("/", 1)
        if is_registry_host(head):
            ref = rest

    # Drop the tag. The tag separator is a ':' in the final path segment; a ':'
    # before the last '/' belongs to a registry port, not a tag.
    last_slash = ref.rfind("/")
    last_colon = ref.rfind(":")
    if last_colon > last_slash:
        ref = ref[:last_colon]

    return ref
