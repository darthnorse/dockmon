"""
Client for communicating with the Go stats service
"""
import aiohttp
import asyncio
import logging
import os
from typing import Dict, Optional, Callable
import json

logger = logging.getLogger(__name__)

STATS_SERVICE_URL = "http://localhost:8081"
TOKEN_FILE_PATH = "/app/data/stats-service-token"


class StatsServiceClient:
    """Client for the Go stats service"""

    def __init__(self, base_url: str = STATS_SERVICE_URL):
        self.base_url = base_url
        self.session: Optional[aiohttp.ClientSession] = None
        self.token: Optional[str] = None
        self.ws_connection: Optional[aiohttp.ClientWebSocketResponse] = None
        self.ws_task: Optional[asyncio.Task] = None
        self.event_callback: Optional[Callable] = None
        self._token_lock = asyncio.Lock()
        self._session_lock = asyncio.Lock()  # Prevent concurrent session creation

    async def _load_token(self) -> str:
        """Load auth token from file (with retry for startup race condition)"""
        # Fast path: check without lock first (double-check locking pattern)
        if self.token:
            return self.token

        async with self._token_lock:
            # Check again after acquiring lock (another thread may have loaded it)
            if self.token:
                return self.token

            # Retry logic: Wait up to 5 seconds for token file to appear
            for attempt in range(10):
                try:
                    if os.path.exists(TOKEN_FILE_PATH):
                        with open(TOKEN_FILE_PATH, 'r') as f:
                            self.token = f.read().strip()
                            logger.info("Loaded stats service auth token")
                            return self.token
                except Exception as e:
                    logger.warning(f"Failed to read token file (attempt {attempt + 1}): {e}")

                await asyncio.sleep(0.5)

            raise RuntimeError(f"Failed to load stats service token from {TOKEN_FILE_PATH}")

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session with auth header (thread-safe)"""
        # Fast path: check without lock
        if self.session is not None and not self.session.closed:
            return self.session

        # Slow path: create session with lock
        async with self._session_lock:
            # Double-check after acquiring lock
            if self.session is not None and not self.session.closed:
                return self.session

            token = await self._load_token()
            timeout = aiohttp.ClientTimeout(total=5)
            headers = {"Authorization": f"Bearer {token}"}
            self.session = aiohttp.ClientSession(timeout=timeout, headers=headers)
            return self.session

    async def close(self):
        """Close the HTTP session and WebSocket connection"""
        # Close WebSocket
        if self.ws_task:
            self.ws_task.cancel()
            try:
                await self.ws_task
            except asyncio.CancelledError:
                pass

        if self.ws_connection and not self.ws_connection.closed:
            await self.ws_connection.close()

        # Close HTTP session
        if self.session and not self.session.closed:
            await self.session.close()

    async def _invalidate_auth(self):
        """Invalidate cached token and session (called when token expires)"""
        async with self._token_lock:
            self.token = None

        async with self._session_lock:
            if self.session and not self.session.closed:
                await self.session.close()
            self.session = None

    async def health_check(self) -> bool:
        """Check if stats service is healthy"""
        for attempt in range(2):
            try:
                session = await self._get_session()
                async with session.get(f"{self.base_url}/health") as resp:
                    if resp.status == 401 and attempt == 0:
                        logger.warning("Stats service returned 401, refreshing token...")
                        await self._invalidate_auth()
                        continue
                    return resp.status == 200
            except Exception as e:
                logger.warning(f"Stats service health check failed: {e}")
                return False
        return False

    async def add_docker_host(self, host_id: str, host_address: str, tls_ca: str = None, tls_cert: str = None, tls_key: str = None) -> bool:
        """Register a Docker host with the stats service"""
        for attempt in range(2):
            try:
                session = await self._get_session()
                payload = {"host_id": host_id, "host_address": host_address}

                # Add TLS certificates if provided
                if tls_ca and tls_cert and tls_key:
                    payload["tls_ca_cert"] = tls_ca
                    payload["tls_cert"] = tls_cert
                    payload["tls_key"] = tls_key

                async with session.post(
                    f"{self.base_url}/api/hosts/add",
                    json=payload
                ) as resp:
                    if resp.status == 401 and attempt == 0:
                        logger.warning("Stats service returned 401, refreshing token...")
                        await self._invalidate_auth()
                        continue
                    if resp.status == 200:
                        logger.info(f"Registered host {host_id} with stats service")
                        return True
                    else:
                        logger.error(f"Failed to register host {host_id}: {resp.status}")
                        return False
            except Exception as e:
                logger.error(f"Error registering host {host_id} with stats service: {e}")
                return False
        return False

    async def remove_docker_host(self, host_id: str) -> bool:
        """Remove a Docker host from the stats service"""
        for attempt in range(2):
            try:
                session = await self._get_session()
                async with session.post(
                    f"{self.base_url}/api/hosts/remove",
                    json={"host_id": host_id}
                ) as resp:
                    if resp.status == 401 and attempt == 0:
                        logger.warning("Stats service returned 401, refreshing token...")
                        await self._invalidate_auth()
                        continue
                    if resp.status == 200:
                        logger.info(f"Removed host {host_id[:8]} from stats service")
                        return True
                    else:
                        logger.warning(f"Failed to remove host {host_id[:8]} from stats service: {resp.status}")
                        return False
            except asyncio.TimeoutError:
                # Timeout during host removal is expected - Go service closes connections immediately
                logger.debug(f"Timeout removing host {host_id[:8]} from stats service (expected during cleanup)")
                return False
            except Exception as e:
                logger.warning(f"Error removing host {host_id[:8]} from stats service: {e}")
                return False
        return False

    async def start_container_stream(self, container_id: str, container_name: str, host_id: str) -> bool:
        """Start stats streaming for a container"""
        for attempt in range(2):
            try:
                session = await self._get_session()
                async with session.post(
                    f"{self.base_url}/api/streams/start",
                    json={
                        "container_id": container_id,
                        "container_name": container_name,
                        "host_id": host_id
                    }
                ) as resp:
                    if resp.status == 401 and attempt == 0:
                        logger.warning("Stats service returned 401, refreshing token...")
                        await self._invalidate_auth()
                        continue
                    if resp.status == 200:
                        logger.debug(f"Started stats stream for container {container_id[:12]}")
                        return True
                    else:
                        error_text = await resp.text()
                        logger.warning(f"Failed to start stream for {container_id[:12]}: HTTP {resp.status} - {error_text}")
                        return False
            except asyncio.TimeoutError:
                # Timeout errors are expected during host cleanup - log at debug level
                logger.debug(f"Timeout starting stream for {container_id[:12]} (expected during host cleanup)")
                return False
            except Exception as e:
                logger.warning(f"Error starting stream for {container_id[:12]}: {type(e).__name__}: {str(e)}", exc_info=True)
                return False
        return False

    async def stop_container_stream(self, container_id: str, host_id: str) -> bool:
        """Stop stats streaming for a container"""
        for attempt in range(2):
            try:
                session = await self._get_session()
                async with session.post(
                    f"{self.base_url}/api/streams/stop",
                    json={"container_id": container_id, "host_id": host_id}
                ) as resp:
                    if resp.status == 401 and attempt == 0:
                        logger.warning("Stats service returned 401, refreshing token...")
                        await self._invalidate_auth()
                        continue
                    if resp.status == 200:
                        logger.debug(f"Stopped stats stream for container {container_id[:12]}")
                        return True
                    else:
                        logger.warning(f"Failed to stop stream for {container_id[:12]}: {resp.status}")
                        return False
            except asyncio.TimeoutError:
                # Timeout errors are expected when bulk stopping streams - log at debug level
                logger.debug(f"Timeout stopping stream for {container_id[:12]} (expected during bulk stop)")
                return False
            except Exception as e:
                logger.warning(f"Error stopping stream for {container_id[:12]}: {e}")
                return False
        return False

    async def get_host_stats(self) -> Dict[str, Dict]:
        """
        Get aggregated stats for all hosts
        Returns: {host_id: {cpu_percent, memory_percent, ...}}
        """
        for attempt in range(2):
            try:
                session = await self._get_session()
                async with session.get(f"{self.base_url}/api/stats/hosts") as resp:
                    if resp.status == 401 and attempt == 0:
                        logger.warning("Stats service returned 401, refreshing token...")
                        await self._invalidate_auth()
                        continue
                    if resp.status == 200:
                        stats = await resp.json()
                        logger.debug(f"Received stats for {len(stats)} hosts from stats service")
                        return stats
                    else:
                        logger.error(f"Failed to get host stats: {resp.status}")
                        return {}
            except Exception as e:
                logger.error(f"Error getting host stats from stats service: {e}")
                return {}
        return {}

    async def get_container_stats(self) -> Dict[str, Dict]:
        """
        Get stats for all containers (for debugging)
        Returns: {container_id: {cpu_percent, memory_percent, ...}}
        """
        for attempt in range(2):
            try:
                session = await self._get_session()
                async with session.get(f"{self.base_url}/api/stats/containers") as resp:
                    if resp.status == 401 and attempt == 0:
                        logger.warning("Stats service returned 401, refreshing token...")
                        await self._invalidate_auth()
                        continue
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        logger.error(f"Failed to get container stats: {resp.status}")
                        return {}
            except Exception as e:
                logger.error(f"Error getting container stats from stats service: {e}")
                return {}
        return {}

    # Event service methods

    async def add_event_host(self, host_id: str, host_address: str, tls_ca: str = None, tls_cert: str = None, tls_key: str = None) -> bool:
        """Register a Docker host with the event monitoring service"""
        for attempt in range(2):
            try:
                session = await self._get_session()
                payload = {"host_id": host_id, "host_address": host_address}

                # Add TLS certificates if provided
                if tls_ca and tls_cert and tls_key:
                    payload["tls_ca_cert"] = tls_ca
                    payload["tls_cert"] = tls_cert
                    payload["tls_key"] = tls_key

                async with session.post(
                    f"{self.base_url}/api/events/hosts/add",
                    json=payload
                ) as resp:
                    if resp.status == 401 and attempt == 0:
                        logger.warning("Stats service returned 401, refreshing token...")
                        await self._invalidate_auth()
                        continue
                    if resp.status == 200:
                        logger.info(f"Registered host {host_id[:8]} with event service")
                        return True
                    else:
                        logger.error(f"Failed to register host {host_id[:8]} with event service: {resp.status}")
                        return False
            except Exception as e:
                logger.error(f"Error registering host {host_id[:8]} with event service: {e}")
                return False
        return False

    async def remove_event_host(self, host_id: str) -> bool:
        """Remove a Docker host from event monitoring"""
        for attempt in range(2):
            try:
                session = await self._get_session()
                async with session.post(
                    f"{self.base_url}/api/events/hosts/remove",
                    json={"host_id": host_id}
                ) as resp:
                    if resp.status == 401 and attempt == 0:
                        logger.warning("Stats service returned 401, refreshing token...")
                        await self._invalidate_auth()
                        continue
                    if resp.status == 200:
                        logger.info(f"Removed host {host_id[:8]} from event service")
                        return True
                    else:
                        logger.warning(f"Failed to remove host {host_id[:8]} from event service: {resp.status}")
                        return False
            except Exception as e:
                logger.warning(f"Error removing host {host_id[:8]} from event service: {e}")
                return False
        return False

    async def get_recent_events(self, host_id: Optional[str] = None) -> list:
        """Get recent cached events"""
        for attempt in range(2):
            try:
                session = await self._get_session()
                url = f"{self.base_url}/api/events/recent"
                if host_id:
                    url += f"?host_id={host_id}"

                async with session.get(url) as resp:
                    if resp.status == 401 and attempt == 0:
                        logger.warning("Stats service returned 401, refreshing token...")
                        await self._invalidate_auth()
                        continue
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        logger.error(f"Failed to get recent events: {resp.status}")
                        return []
            except Exception as e:
                logger.error(f"Error getting recent events: {e}")
                return []
        return []

    async def connect_event_stream(self, event_callback: Callable):
        """
        Connect to the WebSocket event stream

        Args:
            event_callback: Async function to call with each event
        """
        self.event_callback = event_callback

        # Start WebSocket connection in background
        self.ws_task = asyncio.create_task(self._event_stream_loop())
        logger.info("Started event stream WebSocket connection task")

    async def _event_stream_loop(self):
        """Background task that maintains WebSocket connection and processes events"""
        backoff = 1
        max_backoff = 30

        while True:
            try:
                # Load token
                token = await self._load_token()

                # Connect to WebSocket with token in URL
                ws_url = f"{self.base_url.replace('http', 'ws')}/ws/events?token={token}"

                session = await self._get_session()
                async with session.ws_connect(ws_url) as ws:
                    self.ws_connection = ws
                    logger.info("Connected to event stream WebSocket")
                    backoff = 1  # Reset backoff on successful connection

                    # Process messages
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                event = json.loads(msg.data)
                                if self.event_callback:
                                    await self.event_callback(event)
                            except json.JSONDecodeError as e:
                                logger.error(f"Failed to decode event JSON: {e}")
                            except Exception as e:
                                logger.error(f"Error processing event: {e}")

                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logger.error(f"WebSocket error: {ws.exception()}")
                            break

                        elif msg.type == aiohttp.WSMsgType.CLOSED:
                            logger.warning("WebSocket connection closed by server")
                            break

                    self.ws_connection = None

            except asyncio.CancelledError:
                logger.info("Event stream WebSocket task cancelled")
                break

            except aiohttp.ClientResponseError as e:
                # Handle 401 specifically - invalidate cached token and retry immediately
                if e.status == 401:
                    logger.warning("WebSocket received 401, invalidating cached token and retrying immediately")
                    await self._invalidate_auth()
                    backoff = 1  # Reset backoff for immediate retry with fresh token
                else:
                    logger.error(f"Event stream WebSocket HTTP error {e.status}: {e}, reconnecting in {backoff}s")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, max_backoff)

            except Exception as e:
                logger.error(f"Event stream WebSocket error: {e}, reconnecting in {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)


# Global instance
_stats_client = None

def get_stats_client() -> StatsServiceClient:
    """Get the global stats client instance"""
    global _stats_client
    if _stats_client is None:
        _stats_client = StatsServiceClient()
    return _stats_client
