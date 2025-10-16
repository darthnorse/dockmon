"""
Registry Adapter for Docker Image Update Detection

Resolves Docker image tags to digests by querying registry APIs.
Supports Docker Hub, GHCR, and other OCI-compliant registries.

Inspired by dockpeek's registry interaction patterns, but implemented
independently for DockMon's multi-host architecture.
"""

import aiohttp
import asyncio
import base64
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class RegistryCache:
    """Simple in-memory cache with TTL for registry responses"""

    def __init__(self, ttl_seconds: int = 120):
        self._cache: Dict[str, Tuple[any, datetime]] = {}
        self._ttl = timedelta(seconds=ttl_seconds)

    def get(self, key: str) -> Optional[any]:
        """Get cached value if not expired"""
        if key in self._cache:
            value, timestamp = self._cache[key]
            if datetime.now() - timestamp < self._ttl:
                return value
            else:
                del self._cache[key]
        return None

    def set(self, key: str, value: any):
        """Set cache value with current timestamp"""
        self._cache[key] = (value, datetime.now())

    def clear(self):
        """Clear all cached values"""
        self._cache.clear()


class RegistryAdapter:
    """
    Adapter for querying Docker registries to resolve image tags to digests.

    Supports:
    - Docker Hub (docker.io)
    - GitHub Container Registry (ghcr.io)
    - Google Container Registry (gcr.io)
    - AWS ECR (*.ecr.*.amazonaws.com)
    - Private OCI-compliant registries
    """

    def __init__(self, cache_ttl: int = 120):
        self.cache = RegistryCache(cache_ttl)
        self._auth_cache: Dict[str, Dict] = {}  # Cache auth tokens per registry

    async def resolve_tag(
        self,
        image_ref: str,
        platform: str = "linux/amd64",
        auth: Optional[Dict] = None
    ) -> Optional[Dict]:
        """
        Resolve an image tag to its digest.

        Args:
            image_ref: Full image reference (e.g., "nginx:1.25", "ghcr.io/org/app:latest")
            platform: Target platform (default: linux/amd64)
            auth: Optional authentication dict with keys: username, password

        Returns:
            Dict with keys:
                - digest: sha256 digest (e.g., "sha256:abc123...")
                - manifest: Full manifest dict
                - registry: Registry URL
                - repository: Repository name
                - tag: Tag name
            Or None if resolution fails
        """
        # Check cache first
        cache_key = f"{image_ref}:{platform}"
        cached = self.cache.get(cache_key)
        if cached:
            logger.debug(f"Cache hit for {image_ref}")
            return cached

        try:
            # Parse image reference
            registry, repository, tag = self._parse_image_ref(image_ref)

            # Get auth token if needed
            token = await self._get_auth_token(registry, repository, auth)

            # Fetch manifest
            manifest_url = self._get_manifest_url(registry, repository, tag)
            digest, manifest = await self._fetch_manifest(
                manifest_url, token, platform
            )

            if digest and manifest:
                result = {
                    "digest": digest,
                    "manifest": manifest,
                    "registry": registry,
                    "repository": repository,
                    "tag": tag,
                }
                self.cache.set(cache_key, result)
                logger.info(f"Resolved {image_ref} → {digest[:16]}...")
                return result

        except Exception as e:
            logger.error(f"Failed to resolve {image_ref}: {e}")

        return None

    def _parse_image_ref(self, image_ref: str) -> Tuple[str, str, str]:
        """
        Parse image reference into registry, repository, and tag.

        Examples:
            nginx:1.25 → (docker.io, library/nginx, 1.25)
            ghcr.io/user/app:v1.0 → (ghcr.io, user/app, v1.0)
            myregistry.com:5000/app → (myregistry.com:5000, app, latest)
        """
        # Default values
        registry = "docker.io"
        tag = "latest"

        # Split image reference
        if "@sha256:" in image_ref:
            # Already a digest reference
            raise ValueError(f"Image ref is already a digest: {image_ref}")

        # Check for explicit registry
        if "/" in image_ref:
            parts = image_ref.split("/", 1)
            # If first part has dot or colon, it's likely a registry
            if "." in parts[0] or ":" in parts[0]:
                registry = parts[0]
                image_ref = parts[1]

        # Split repository and tag
        if ":" in image_ref:
            repository, tag = image_ref.rsplit(":", 1)
        else:
            repository = image_ref

        # Docker Hub uses "library/" prefix for official images
        if registry == "docker.io" and "/" not in repository:
            repository = f"library/{repository}"

        return registry, repository, tag

    def _get_manifest_url(self, registry: str, repository: str, tag: str) -> str:
        """
        Construct manifest URL for the registry.

        Uses Registry v2 API format.
        """
        # Ensure registry has protocol
        if not registry.startswith("http"):
            # Use HTTPS for all registries
            registry = f"https://{registry}"

        # Docker Hub uses different API endpoint
        if "docker.io" in registry:
            registry = "https://registry.hub.docker.com"

        return f"{registry}/v2/{repository}/manifests/{tag}"

    async def _get_auth_token(
        self,
        registry: str,
        repository: str,
        auth: Optional[Dict] = None
    ) -> Optional[str]:
        """
        Get authentication token for registry.

        Implements Docker Registry v2 token authentication flow.
        """
        # Check cache first
        cache_key = f"{registry}:{repository}"
        if cache_key in self._auth_cache:
            cached_token = self._auth_cache[cache_key]
            # Check if token is still valid (expires_at field)
            if cached_token.get("expires_at"):
                if datetime.now() < cached_token["expires_at"]:
                    return cached_token["token"]
                else:
                    # Token expired - delete it to prevent memory leak
                    del self._auth_cache[cache_key]

        # For Docker Hub, get token from auth service
        if "docker.io" in registry or "registry.hub.docker.com" in registry:
            return await self._get_dockerhub_token(repository, auth)

        # For GHCR (GitHub Container Registry), get token from GitHub
        if "ghcr.io" in registry:
            return await self._get_ghcr_token(repository, auth)

        # For LSCR (LinuxServer.io Container Registry), get token
        if "lscr.io" in registry:
            return await self._get_lscr_token(repository, auth)

        # For Quay.io (Red Hat Quay), get token
        if "quay.io" in registry:
            return await self._get_quay_token(repository, auth)

        # For other registries, basic auth might be enough
        if auth:
            credentials = f"{auth['username']}:{auth['password']}"
            encoded = base64.b64encode(credentials.encode()).decode()
            return f"Basic {encoded}"

        # No auth needed for public registries
        return None

    async def _get_dockerhub_token(
        self,
        repository: str,
        auth: Optional[Dict] = None
    ) -> Optional[str]:
        """
        Get Bearer token from Docker Hub auth service.

        Docker Hub requires a bearer token from auth.docker.io before
        accessing the registry API.
        """
        auth_url = (
            f"https://auth.docker.io/token"
            f"?service=registry.docker.io"
            f"&scope=repository:{repository}:pull"
        )

        headers = {}
        if auth:
            credentials = f"{auth['username']}:{auth['password']}"
            encoded = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(auth_url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        token = data.get("token")
                        if token:
                            # Cache token (Docker Hub tokens expire in 5 minutes)
                            cache_key = f"docker.io:{repository}"
                            self._auth_cache[cache_key] = {
                                "token": f"Bearer {token}",
                                "expires_at": datetime.now() + timedelta(minutes=4)
                            }
                            return f"Bearer {token}"
        except Exception as e:
            logger.warning(f"Failed to get Docker Hub token: {e}")

        return None

    async def _get_ghcr_token(
        self,
        repository: str,
        auth: Optional[Dict] = None
    ) -> Optional[str]:
        """
        Get Bearer token from GitHub Container Registry.

        GHCR uses GitHub's token service for authentication.
        Public images can be accessed anonymously, but still need a token.
        """
        # GHCR uses ghcr.io as the service name
        auth_url = (
            f"https://ghcr.io/token"
            f"?scope=repository:{repository}:pull"
        )

        headers = {}
        if auth:
            credentials = f"{auth['username']}:{auth['password']}"
            encoded = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(auth_url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        token = data.get("token")
                        if token:
                            # Cache token (GHCR tokens expire in 5 minutes)
                            cache_key = f"ghcr.io:{repository}"
                            self._auth_cache[cache_key] = {
                                "token": f"Bearer {token}",
                                "expires_at": datetime.now() + timedelta(minutes=4)
                            }
                            logger.debug(f"Got GHCR token for {repository}")
                            return f"Bearer {token}"
                        else:
                            logger.warning(f"GHCR token response missing token field: {data}")
                    else:
                        response_text = await response.text()
                        logger.warning(f"GHCR token request returned {response.status}: {response_text}")
        except Exception as e:
            logger.warning(f"Failed to get GHCR token: {e}")

        return None

    async def _get_lscr_token(
        self,
        repository: str,
        auth: Optional[Dict] = None
    ) -> Optional[str]:
        """
        Get Bearer token from LinuxServer.io Container Registry (lscr.io).

        LSCR is similar to GHCR - public images can be accessed anonymously with a token.
        """
        # LSCR uses lscr.io as the service name
        auth_url = (
            f"https://lscr.io/token"
            f"?scope=repository:{repository}:pull"
        )

        headers = {}
        if auth:
            credentials = f"{auth['username']}:{auth['password']}"
            encoded = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(auth_url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        token = data.get("token")
                        if token:
                            # Cache token (LSCR tokens expire in 5 minutes)
                            cache_key = f"lscr.io:{repository}"
                            self._auth_cache[cache_key] = {
                                "token": f"Bearer {token}",
                                "expires_at": datetime.now() + timedelta(minutes=4)
                            }
                            logger.debug(f"Got LSCR token for {repository}")
                            return f"Bearer {token}"
                        else:
                            logger.warning(f"LSCR token response missing token field: {data}")
                    else:
                        response_text = await response.text()
                        logger.warning(f"LSCR token request returned {response.status}: {response_text}")
        except Exception as e:
            logger.warning(f"Failed to get LSCR token: {e}")

        return None

    async def _get_quay_token(
        self,
        repository: str,
        auth: Optional[Dict] = None
    ) -> Optional[str]:
        """
        Get Bearer token from Quay.io (Red Hat Quay Container Registry).

        Quay uses a standard Docker v2 token authentication flow.
        """
        # Quay uses quay.io as the service name
        auth_url = (
            f"https://quay.io/v2/auth"
            f"?service=quay.io"
            f"&scope=repository:{repository}:pull"
        )

        headers = {}
        if auth:
            credentials = f"{auth['username']}:{auth['password']}"
            encoded = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(auth_url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        token = data.get("token")
                        if token:
                            # Cache token (Quay tokens expire in 5 minutes)
                            cache_key = f"quay.io:{repository}"
                            self._auth_cache[cache_key] = {
                                "token": f"Bearer {token}",
                                "expires_at": datetime.now() + timedelta(minutes=4)
                            }
                            logger.debug(f"Got Quay token for {repository}")
                            return f"Bearer {token}"
                        else:
                            logger.warning(f"Quay token response missing token field: {data}")
                    else:
                        response_text = await response.text()
                        logger.warning(f"Quay token request returned {response.status}: {response_text}")
        except Exception as e:
            logger.warning(f"Failed to get Quay token: {e}")

        return None

    async def _fetch_manifest(
        self,
        manifest_url: str,
        token: Optional[str],
        platform: str
    ) -> Tuple[Optional[str], Optional[Dict]]:
        """
        Fetch image manifest from registry.

        Returns tuple of (digest, manifest_dict).
        """
        headers = {
            "Accept": (
                "application/vnd.docker.distribution.manifest.v2+json,"
                "application/vnd.docker.distribution.manifest.list.v2+json,"
                "application/vnd.oci.image.manifest.v1+json,"
                "application/vnd.oci.image.index.v1+json"
            )
        }

        if token:
            headers["Authorization"] = token

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(manifest_url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        # Get digest from Docker-Content-Digest header
                        digest = response.headers.get("Docker-Content-Digest")

                        # Get manifest body
                        manifest = await response.json()

                        logger.debug(f"Fetched manifest for {manifest_url}: mediaType={manifest.get('mediaType')}, digest={digest}")

                        # Handle manifest lists (multi-platform images)
                        if manifest.get("mediaType") in [
                            "application/vnd.docker.distribution.manifest.list.v2+json",
                            "application/vnd.oci.image.index.v1+json"
                        ]:
                            # Find platform-specific manifest
                            logger.debug(f"Manifest is a list, resolving platform-specific manifest for {platform}")
                            digest = await self._resolve_platform_manifest(
                                manifest, platform, manifest_url, token
                            )
                            logger.debug(f"Resolved platform-specific digest: {digest}")

                        return digest, manifest

                    elif response.status == 401:
                        logger.error(f"Authentication failed for {manifest_url}")
                    elif response.status == 404:
                        logger.error(f"Image not found: {manifest_url}")
                    elif response.status == 429:
                        logger.warning(f"Rate limited by registry: {manifest_url}")
                    else:
                        logger.error(f"Registry returned {response.status} for {manifest_url}")

        except asyncio.TimeoutError:
            logger.error(f"Timeout fetching manifest: {manifest_url}")
        except Exception as e:
            logger.error(f"Error fetching manifest: {e}")

        return None, None

    async def _resolve_platform_manifest(
        self,
        manifest_list: Dict,
        platform: str,
        base_url: str,
        token: Optional[str]
    ) -> Optional[str]:
        """
        Resolve platform-specific digest from manifest list.

        Multi-platform images have a manifest list that points to
        platform-specific manifests. We need to fetch the correct one
        to get the actual platform-specific digest (not the digest from the list).
        """
        # Parse platform (e.g., "linux/amd64" → os=linux, arch=amd64)
        os_name, arch = platform.split("/") if "/" in platform else ("linux", platform)

        # Find matching manifest
        platform_manifest_digest = None
        for manifest in manifest_list.get("manifests", []):
            manifest_platform = manifest.get("platform", {})
            if (manifest_platform.get("os") == os_name and
                manifest_platform.get("architecture") == arch):
                platform_manifest_digest = manifest.get("digest")
                break

        if not platform_manifest_digest:
            logger.warning(f"No manifest found for platform {platform}")
            return None

        # Now fetch the actual platform-specific manifest to get its digest
        # The digest from the manifest list is the sha256 of the manifest itself,
        # but we need to fetch it to get the Docker-Content-Digest header
        # which is what Docker uses
        logger.debug(f"Fetching platform-specific manifest: {platform_manifest_digest}")

        # Replace the tag in the URL with the digest
        manifest_url = base_url.rsplit("/", 1)[0] + "/" + platform_manifest_digest

        headers = {
            "Accept": (
                "application/vnd.docker.distribution.manifest.v2+json,"
                "application/vnd.oci.image.manifest.v1+json"
            )
        }

        if token:
            headers["Authorization"] = token

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(manifest_url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        # The digest in the Docker-Content-Digest header is what we want
                        digest = response.headers.get("Docker-Content-Digest")
                        if digest:
                            logger.debug(f"Got platform-specific manifest digest: {digest}")
                            return digest
                        else:
                            # Fallback to the digest from the manifest list
                            logger.warning(f"No Docker-Content-Digest header, using manifest list digest")
                            return platform_manifest_digest
                    else:
                        logger.error(f"Failed to fetch platform manifest: {response.status}")
                        return platform_manifest_digest
        except Exception as e:
            logger.error(f"Error fetching platform manifest: {e}")
            return platform_manifest_digest

    def compute_floating_tag(self, image_tag: str, mode: str) -> str:
        """
        Compute the floating tag based on tracking mode.

        Args:
            image_tag: Original tag (e.g., "nginx:1.25.3")
            mode: Tracking mode (exact|minor|major|latest)

        Returns:
            Computed tag to track

        Examples:
            ("nginx:1.25.3", "exact") → "nginx:1.25.3"
            ("nginx:1.25.3", "minor") → "nginx:1.25"
            ("nginx:1.25.3", "major") → "nginx:1"
            ("nginx:1.25.3", "latest") → "nginx:latest"
        """
        if mode == "exact":
            return image_tag

        # Split image and tag
        if ":" in image_tag:
            image, tag = image_tag.rsplit(":", 1)
        else:
            image, tag = image_tag, "latest"

        if mode == "latest":
            return f"{image}:latest"

        # Parse semantic version
        # Match patterns like: 1.25.3, 1.25.3-alpine, 1.25, v1.25.3
        version_match = re.match(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(.*)$", tag)
        if not version_match:
            # Not a version tag, return as-is
            return image_tag

        major, minor, patch, suffix = version_match.groups()

        if mode == "major":
            # Track major version only
            return f"{image}:{major}{suffix or ''}"
        elif mode == "minor":
            # Track major.minor
            if minor:
                return f"{image}:{major}.{minor}{suffix or ''}"
            else:
                # Already major-only tag
                return f"{image}:{major}{suffix or ''}"

        return image_tag


# Global singleton instance
_registry_adapter = None


def get_registry_adapter() -> RegistryAdapter:
    """Get or create global RegistryAdapter instance"""
    global _registry_adapter
    if _registry_adapter is None:
        _registry_adapter = RegistryAdapter(cache_ttl=120)
    return _registry_adapter
