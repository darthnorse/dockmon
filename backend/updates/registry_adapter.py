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
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class RegistryCache:
    """Simple in-memory cache with TTL for registry responses"""

    MAX_CACHE_SIZE = 1000  # Prevent unbounded growth

    def __init__(self, ttl_seconds: int = 120):
        self._cache: Dict[str, Tuple[any, datetime]] = {}
        self._ttl = timedelta(seconds=ttl_seconds)

    def get(self, key: str) -> Optional[any]:
        """Get cached value if not expired"""
        if key in self._cache:
            value, timestamp = self._cache[key]
            if datetime.now(timezone.utc) - timestamp < self._ttl:
                return value
            else:
                del self._cache[key]
        return None

    def set(self, key: str, value: any):
        """Set cache value with current timestamp"""
        # Cleanup before adding if approaching limit
        if len(self._cache) >= self.MAX_CACHE_SIZE:
            self._cleanup_expired()

            # If still over limit after TTL cleanup, remove oldest entries (LRU)
            if len(self._cache) >= self.MAX_CACHE_SIZE:
                sorted_entries = sorted(self._cache.items(), key=lambda x: x[1][1])
                keys_to_remove = [k for k, _ in sorted_entries[:self.MAX_CACHE_SIZE // 10]]  # Remove oldest 10%
                for k in keys_to_remove:
                    del self._cache[k]
                logger.warning(f"Registry cache exceeded limit, removed {len(keys_to_remove)} oldest entries")

        self._cache[key] = (value, datetime.now(timezone.utc))

    def _cleanup_expired(self):
        """Remove all expired entries"""
        now = datetime.now(timezone.utc)
        keys_to_remove = [
            key for key, (_, timestamp) in self._cache.items()
            if now - timestamp >= self._ttl
        ]
        for key in keys_to_remove:
            del self._cache[key]
        if keys_to_remove:
            logger.debug(f"Cleaned up {len(keys_to_remove)} expired cache entries")

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

    MAX_AUTH_CACHE_SIZE = 500  # Prevent unbounded growth of auth tokens

    def __init__(self, cache_ttl: int = 120):
        self.cache = RegistryCache(cache_ttl)
        self._auth_cache: Dict[str, Dict] = {}  # Cache auth tokens per registry

    def _cleanup_auth_cache(self):
        """Clean up expired auth tokens and enforce size limit"""
        now = datetime.now(timezone.utc)

        # Remove expired tokens
        keys_to_remove = [
            key for key, value in self._auth_cache.items()
            if value.get("expires_at") and value["expires_at"] < now
        ]
        for key in keys_to_remove:
            del self._auth_cache[key]

        # If still over limit, remove oldest entries
        if len(self._auth_cache) >= self.MAX_AUTH_CACHE_SIZE:
            sorted_entries = sorted(
                self._auth_cache.items(),
                key=lambda x: x[1].get("expires_at", datetime.min.replace(tzinfo=timezone.utc))
            )
            keys_to_remove = [k for k, _ in sorted_entries[:self.MAX_AUTH_CACHE_SIZE // 10]]
            for k in keys_to_remove:
                del self._auth_cache[k]
            logger.warning(f"Auth cache exceeded limit, removed {len(keys_to_remove)} oldest entries")

    def _encode_basic_auth(self, auth: Dict) -> str:
        """
        Encode username:password as Basic authentication header.

        Args:
            auth: Dict with keys 'username' and 'password'

        Returns:
            Basic auth header string (e.g., "Basic dXNlcjpwYXNz")
        """
        credentials = f"{auth['username']}:{auth['password']}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"

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
                # Fetch config blob to get Labels (for OCI version extraction)
                config_data = await self._fetch_config_blob(
                    registry, repository, manifest, token, platform
                )

                result = {
                    "digest": digest,
                    "manifest": {
                        **manifest,
                        "config": config_data if config_data else manifest.get("config", {})
                    },
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

    def _normalize_registry_url(self, registry: str) -> str:
        """
        Normalize registry URL to full HTTPS URL.

        Args:
            registry: Registry name (e.g., "docker.io", "ghcr.io")

        Returns:
            Normalized HTTPS URL (e.g., "https://registry.hub.docker.com")
        """
        if not registry.startswith("http"):
            registry = f"https://{registry}"

        # Docker Hub uses special endpoint
        if "docker.io" in registry:
            registry = "https://registry.hub.docker.com"

        return registry

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
        # Normalize registry URL
        registry = self._normalize_registry_url(registry)
        return f"{registry}/v2/{repository}/manifests/{tag}"

    def _parse_www_authenticate(self, header: str) -> Optional[Dict[str, str]]:
        """
        Parse WWW-Authenticate header to extract auth parameters.

        The header format follows RFC 7235 (HTTP Authentication) and is typically:
        Bearer realm="https://auth.example.com/token",service="registry.example.com",scope="repository:repo/name:pull"

        Args:
            header: WWW-Authenticate header value

        Returns:
            Dict with keys: realm, service, scope
            Or None if parsing fails

        Example:
            Input: 'Bearer realm="https://ghcr.io/token",service="ghcr.io",scope="repository:user/app:pull"'
            Output: {
                "realm": "https://ghcr.io/token",
                "service": "ghcr.io",
                "scope": "repository:user/app:pull"
            }
        """
        if not header:
            return None

        try:
            # Extract the auth scheme (should be "Bearer")
            if not header.startswith("Bearer "):
                logger.warning(f"Unexpected WWW-Authenticate scheme: {header[:20]}")
                return None

            # Remove "Bearer " prefix
            params_str = header[7:]  # len("Bearer ") = 7

            # Parse key="value" pairs using regex
            # Pattern matches: key="value" or key=value
            param_pattern = r'(\w+)="([^"]+)"'
            matches = re.findall(param_pattern, params_str)

            if not matches:
                logger.warning(f"No parameters found in WWW-Authenticate header")
                return None

            # Convert to dict
            params = {key: value for key, value in matches}

            # Validate required fields
            if "realm" not in params:
                logger.warning(f"WWW-Authenticate missing 'realm' parameter")
                return None

            logger.debug(f"Parsed WWW-Authenticate: realm={params.get('realm')}, service={params.get('service')}, scope={params.get('scope', 'none')}")
            return params

        except Exception as e:
            logger.error(f"Error parsing WWW-Authenticate header: {e}")
            return None

    async def _discover_auth_endpoint(
        self,
        registry: str,
        repository: str
    ) -> Optional[Dict[str, str]]:
        """
        Discover authentication endpoint by attempting manifest fetch.

        Following the Docker Registry V2 specification:
        1. Send HEAD request to manifest endpoint without auth
        2. If 401, parse WWW-Authenticate header to discover auth endpoint
        3. Return parsed auth parameters (realm, service, scope)

        This is the standards-compliant way to discover auth requirements
        for any OCI-compliant registry.

        Args:
            registry: Registry URL (e.g., "ghcr.io", "lscr.io")
            repository: Repository name (e.g., "linuxserver/sabnzbd")

        Returns:
            Dict with keys: realm, service, scope
            Or None if discovery fails or no auth required

        Example:
            _discover_auth_endpoint("lscr.io", "linuxserver/sabnzbd")
            → {
                "realm": "https://ghcr.io/token",
                "service": "ghcr.io",
                "scope": "repository:linuxserver/sabnzbd:pull"
              }
        """
        try:
            # Construct manifest URL for discovery (use 'latest' tag)
            manifest_url = self._get_manifest_url(registry, repository, "latest")

            # Send HEAD request (lighter than GET, we only need headers)
            async with aiohttp.ClientSession() as session:
                async with session.head(
                    manifest_url,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 401:
                        # Registry requires auth - parse WWW-Authenticate header
                        www_auth = response.headers.get("WWW-Authenticate")
                        if www_auth:
                            params = self._parse_www_authenticate(www_auth)
                            if params:
                                logger.debug(f"Discovered auth endpoint for {registry}: {params.get('realm')}")
                                return params
                            else:
                                logger.warning(f"Failed to parse WWW-Authenticate for {registry}")
                        else:
                            logger.warning(f"Registry {registry} returned 401 but no WWW-Authenticate header")
                    elif response.status == 200:
                        # No auth required - public registry
                        logger.debug(f"Registry {registry} allows anonymous access")
                        return None
                    else:
                        # Unexpected status - log and return None
                        logger.warning(f"Unexpected status {response.status} during auth discovery for {registry}")

        except asyncio.TimeoutError:
            logger.warning(f"Timeout during auth discovery for {registry}")
        except Exception as e:
            logger.warning(f"Error discovering auth endpoint for {registry}: {e}")

        return None

    async def _fetch_token_from_endpoint(
        self,
        realm: str,
        service: Optional[str],
        scope: Optional[str],
        auth: Optional[Dict] = None,
        cache_key: Optional[str] = None
    ) -> Optional[str]:
        """
        Fetch Bearer token from discovered auth endpoint.

        This is a generic token fetcher that works with any OCI-compliant
        registry token endpoint. Follows the pattern discovered via
        WWW-Authenticate header parsing.

        Args:
            realm: Token endpoint URL (e.g., "https://ghcr.io/token")
            service: Service name (e.g., "ghcr.io")
            scope: Access scope (e.g., "repository:user/app:pull")
            auth: Optional credentials dict with username/password
            cache_key: Optional cache key for token caching

        Returns:
            Bearer token string (e.g., "Bearer abc123...")
            Or None if fetch fails

        Example:
            _fetch_token_from_endpoint(
                realm="https://ghcr.io/token",
                service="ghcr.io",
                scope="repository:linuxserver/sabnzbd:pull"
            )
            → "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
        """
        try:
            # Build query parameters
            params = {}
            if service:
                params["service"] = service
            if scope:
                params["scope"] = scope

            # Build headers
            headers = {}
            if auth:
                headers["Authorization"] = self._encode_basic_auth(auth)

            # Fetch token
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    realm,
                    params=params,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        token = data.get("token")
                        if token:
                            bearer_token = f"Bearer {token}"

                            # Cache token if cache_key provided
                            if cache_key:
                                self._auth_cache[cache_key] = {
                                    "token": bearer_token,
                                    "expires_at": datetime.now(timezone.utc) + timedelta(minutes=4)
                                }

                            logger.debug(f"Successfully obtained token from {realm}")
                            return bearer_token
                        else:
                            logger.error(f"Token endpoint {realm} returned 200 but no token in response")
                    else:
                        response_text = await response.text()
                        logger.error(f"Token request to {realm} failed with status {response.status}: {response_text[:200]}")

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching token from {realm}")
        except Exception as e:
            logger.warning(f"Error fetching token from {realm}: {e}")

        return None

    async def _get_auth_token(
        self,
        registry: str,
        repository: str,
        auth: Optional[Dict] = None
    ) -> Optional[str]:
        """
        Get authentication token for registry.

        Implements proper OCI/Docker Registry v2 authentication flow:
        1. Check cache for existing valid token
        2. Attempt dynamic discovery via WWW-Authenticate header (standards-compliant)
        3. Fallback to hardcoded methods for known non-standard registries (Docker Hub)
        4. Try basic auth if credentials provided
        5. Return None (anonymous access)

        This approach works with any OCI-compliant registry automatically,
        while maintaining compatibility with registries that don't fully
        follow the specification.

        Args:
            registry: Registry URL (e.g., "ghcr.io", "lscr.io", "docker.io")
            repository: Repository name (e.g., "linuxserver/sabnzbd")
            auth: Optional credentials dict with username/password

        Returns:
            Bearer token string or None
        """
        # Periodic cleanup to prevent unbounded growth
        if len(self._auth_cache) >= self.MAX_AUTH_CACHE_SIZE * 0.8:  # 80% threshold
            self._cleanup_auth_cache()

        # Step 1: Check cache for existing valid token
        cache_key = f"{registry}:{repository}"
        if cache_key in self._auth_cache:
            cached_token = self._auth_cache[cache_key]
            # Check if token is still valid (expires_at field)
            if cached_token.get("expires_at"):
                if datetime.now(timezone.utc) < cached_token["expires_at"]:
                    logger.debug(f"Using cached token for {registry}:{repository}")
                    return cached_token["token"]
                else:
                    # Token expired - delete it to prevent memory leak
                    del self._auth_cache[cache_key]
                    logger.debug(f"Cached token expired for {registry}:{repository}")

        # Step 2: Attempt dynamic discovery (standards-compliant, works with any OCI registry)
        logger.debug(f"Attempting dynamic auth discovery for {registry}")
        auth_params = await self._discover_auth_endpoint(registry, repository)

        if auth_params:
            # Extract discovered parameters
            realm = auth_params.get("realm")
            service = auth_params.get("service")
            scope = auth_params.get("scope")

            if realm:
                logger.info(f"Discovered auth endpoint for {registry}: {realm}")
                token = await self._fetch_token_from_endpoint(
                    realm=realm,
                    service=service,
                    scope=scope,
                    auth=auth,
                    cache_key=cache_key
                )
                if token:
                    return token
                else:
                    logger.warning(f"Failed to fetch token from discovered endpoint: {realm}")
            else:
                logger.warning(f"Auth parameters discovered but missing realm for {registry}")

        # Step 3: Fallback to hardcoded methods for known non-standard registries
        # Docker Hub doesn't properly implement WWW-Authenticate discovery
        if "docker.io" in registry or "registry.hub.docker.com" in registry:
            logger.debug(f"Using Docker Hub fallback for {registry}")
            return await self._get_dockerhub_token(repository, auth)

        # GHCR fallback (should work with discovery, but keep as safety net)
        if "ghcr.io" in registry:
            logger.debug(f"Using GHCR fallback for {registry}")
            return await self._get_ghcr_token(repository, auth)

        # Step 4: Try basic auth if credentials provided
        if auth:
            logger.debug(f"Attempting basic auth for {registry}")
            return self._encode_basic_auth(auth)

        # Step 5: No auth needed (public registry with anonymous access)
        logger.debug(f"No authentication required for {registry}")
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
            headers["Authorization"] = self._encode_basic_auth(auth)

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
                                "expires_at": datetime.now(timezone.utc) + timedelta(minutes=4)
                            }
                            logger.debug(f"Successfully obtained Docker Hub token for '{repository}'")
                            return f"Bearer {token}"
                        else:
                            logger.error(f"Docker Hub returned 200 but no token in response for '{repository}'")
                    else:
                        response_text = await response.text()
                        logger.error(f"Docker Hub token request failed with status {response.status} for '{repository}': {response_text[:200]}")
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
            headers["Authorization"] = self._encode_basic_auth(auth)

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
                                "expires_at": datetime.now(timezone.utc) + timedelta(minutes=4)
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
                            # Keep the index digest (manifest list digest) for comparison
                            # This matches Docker CLI behavior and what docker inspect shows in RepoDigests
                            # Docker uses the index digest as the canonical identifier for multi-platform images
                            logger.debug(f"Manifest list detected for {platform}, using index digest: {digest}")

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

    async def _fetch_config_blob(
        self,
        registry: str,
        repository: str,
        manifest: Dict,
        token: Optional[str],
        platform: str = "linux/amd64"
    ) -> Optional[Dict]:
        """
        Fetch image config blob to extract Labels (for OCI version detection).

        Returns the config dict with Labels, or None if fetch fails.
        """
        # Get config digest from manifest
        config_descriptor = manifest.get("config", {})
        config_digest = config_descriptor.get("digest")

        if not config_digest:
            # Check if this is a manifest list (multi-platform image)
            manifest_type = manifest.get("mediaType", "unknown")
            if manifest_type in ["application/vnd.docker.distribution.manifest.list.v2+json",
                                  "application/vnd.oci.image.index.v1+json"]:
                logger.info(f"Manifest list detected for {repository}, fetching platform-specific manifest for {platform}")
                # Need to fetch platform-specific manifest
                return await self._fetch_config_from_manifest_list(
                    registry, repository, manifest, token, platform
                )
            else:
                logger.info(f"No config digest in manifest for {repository} (type: {manifest_type})")
            return None

        # Normalize registry URL
        normalized_registry = self._normalize_registry_url(registry)

        # Build blob URL
        blob_url = f"{normalized_registry}/v2/{repository}/blobs/{config_digest}"

        headers = {}
        if token:
            headers["Authorization"] = token

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(blob_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        # Config blobs are served as application/octet-stream, but contain JSON
                        # Use content_type=None to bypass aiohttp's content-type validation
                        config = await response.json(content_type=None)
                        logger.info(f"Fetched config blob for {repository}")
                        return config
                    else:
                        logger.warning(f"Failed to fetch config blob: {response.status}")
                        return None

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching config blob for {repository}")
            return None
        except Exception as e:
            logger.warning(f"Error fetching config blob: {e}")
            return None

    async def _fetch_config_from_manifest_list(
        self,
        registry: str,
        repository: str,
        manifest_list: Dict,
        token: Optional[str],
        platform: str
    ) -> Optional[Dict]:
        """
        Fetch config blob from a manifest list by first getting the platform-specific manifest.

        Manifest lists (multi-platform images) don't have config descriptors at the top level.
        We need to find the platform-specific manifest and fetch its config blob.
        """
        # Parse platform (e.g., "linux/amd64" → os=linux, arch=amd64)
        os_name, arch = platform.split("/") if "/" in platform else ("linux", platform)

        # Find matching platform manifest descriptor
        platform_manifest_descriptor = None
        for manifest_desc in manifest_list.get("manifests", []):
            manifest_platform = manifest_desc.get("platform", {})
            if (manifest_platform.get("os") == os_name and
                manifest_platform.get("architecture") == arch):
                platform_manifest_descriptor = manifest_desc
                break

        if not platform_manifest_descriptor:
            logger.warning(f"No manifest found for platform {platform} in {repository}")
            return None

        platform_digest = platform_manifest_descriptor.get("digest")
        if not platform_digest:
            logger.warning(f"Platform manifest descriptor missing digest for {repository}")
            return None

        logger.info(f"Found platform-specific manifest for {repository}: {platform_digest[:16]}...")

        # Normalize registry URL
        normalized_registry = self._normalize_registry_url(registry)

        # Fetch the platform-specific manifest
        manifest_url = f"{normalized_registry}/v2/{repository}/manifests/{platform_digest}"
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
                async with session.get(manifest_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        platform_manifest = await response.json()
                        logger.info(f"Fetched platform-specific manifest for {repository}")

                        # Now get the config blob from this manifest
                        config_descriptor = platform_manifest.get("config", {})
                        config_digest = config_descriptor.get("digest")

                        if not config_digest:
                            logger.warning(f"Platform-specific manifest has no config digest for {repository}")
                            return None

                        # Fetch the config blob
                        blob_url = f"{normalized_registry}/v2/{repository}/blobs/{config_digest}"
                        blob_headers = {}
                        if token:
                            blob_headers["Authorization"] = token

                        async with session.get(blob_url, headers=blob_headers, timeout=aiohttp.ClientTimeout(total=10)) as blob_response:
                            if blob_response.status == 200:
                                config = await blob_response.json(content_type=None)
                                logger.info(f"Fetched config blob from platform-specific manifest for {repository}")
                                return config
                            else:
                                logger.warning(f"Failed to fetch config blob: {blob_response.status}")
                                return None
                    else:
                        logger.warning(f"Failed to fetch platform-specific manifest: {response.status}")
                        return None

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching platform-specific config for {repository}")
            return None
        except Exception as e:
            logger.warning(f"Error fetching platform-specific config: {e}")
            return None

    async def _resolve_platform_manifest(
        self,
        manifest_list: Dict,
        platform: str,
        base_url: str,
        token: Optional[str]
    ) -> Optional[str]:
        """
        Resolve platform-specific manifest digest from manifest list.

        NOTE: This method is currently NOT used for update detection.
        Docker CLI uses the manifest list (index) digest as the canonical identifier,
        not the platform-specific manifest digest. This method is preserved for
        potential future use cases like layer-level inspection or detailed platform
        manifest analysis.

        Multi-platform images have a manifest list that points to platform-specific
        manifests. This method fetches the platform-specific manifest and returns
        its digest (different from the index digest).

        For update detection, use the index digest from the manifest list instead
        to match Docker CLI behavior and docker inspect RepoDigests.
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

        Tracking modes aligned with Semantic Versioning (MAJOR.MINOR.PATCH):
        - exact: Use exact tag from image (no floating)
        - patch: Track patch updates only (X.Y.*) - bug fixes only
        - minor: Track minor+patch updates (X.*.*) - new features, no breaking changes
        - latest: Always track :latest tag

        Args:
            image_tag: Original tag (e.g., "nginx:1.25.3")
            mode: Tracking mode (exact|patch|minor|latest)

        Returns:
            Computed tag to track

        Examples:
            ("nginx:1.25.3", "exact") → "nginx:1.25.3"
            ("nginx:1.25.3", "patch") → "nginx:1.25"
            ("nginx:1.25.3", "minor") → "nginx:1"
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

        major, minor_ver, patch_ver, suffix = version_match.groups()

        if mode == "minor":
            # Track minor+patch updates within major version (X.*)
            # nginx:1.25.3 → nginx:1 (gets 1.26, 1.99, NOT 2.0)
            return f"{image}:{major}{suffix or ''}"
        elif mode == "patch":
            # Track patch updates only within minor version (X.Y.*)
            # nginx:1.25.3 → nginx:1.25 (gets 1.25.4, NOT 1.26)
            if minor_ver:
                return f"{image}:{major}.{minor_ver}{suffix or ''}"
            else:
                # Already major-only tag, fallback to minor mode
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
