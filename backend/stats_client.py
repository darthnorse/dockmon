"""
Client for communicating with the Go stats service
"""
import aiohttp
import asyncio
import logging
import os
from typing import Dict, Optional

logger = logging.getLogger(__name__)

STATS_SERVICE_URL = "http://localhost:8081"
TOKEN_FILE_PATH = "/tmp/stats-service-token"


class StatsServiceClient:
    """Client for the Go stats service"""

    def __init__(self, base_url: str = STATS_SERVICE_URL):
        self.base_url = base_url
        self.session: Optional[aiohttp.ClientSession] = None
        self.token: Optional[str] = None

    async def _load_token(self) -> str:
        """Load auth token from file (with retry for startup race condition)"""
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
        """Get or create aiohttp session with auth header"""
        if self.session is None or self.session.closed:
            token = await self._load_token()
            timeout = aiohttp.ClientTimeout(total=5)
            headers = {"Authorization": f"Bearer {token}"}
            self.session = aiohttp.ClientSession(timeout=timeout, headers=headers)
        return self.session

    async def close(self):
        """Close the HTTP session"""
        if self.session and not self.session.closed:
            await self.session.close()

    async def health_check(self) -> bool:
        """Check if stats service is healthy"""
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/health") as resp:
                return resp.status == 200
        except Exception as e:
            logger.warning(f"Stats service health check failed: {e}")
            return False

    async def add_docker_host(self, host_id: str, host_address: str) -> bool:
        """Register a Docker host with the stats service"""
        try:
            session = await self._get_session()
            async with session.post(
                f"{self.base_url}/api/hosts/add",
                json={"host_id": host_id, "host_address": host_address}
            ) as resp:
                if resp.status == 200:
                    logger.info(f"Registered host {host_id} with stats service")
                    return True
                else:
                    logger.error(f"Failed to register host {host_id}: {resp.status}")
                    return False
        except Exception as e:
            logger.error(f"Error registering host {host_id} with stats service: {e}")
            return False

    async def start_container_stream(self, container_id: str, container_name: str, host_id: str) -> bool:
        """Start stats streaming for a container"""
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
                if resp.status == 200:
                    logger.debug(f"Started stats stream for container {container_id[:12]}")
                    return True
                else:
                    logger.warning(f"Failed to start stream for {container_id[:12]}: {resp.status}")
                    return False
        except Exception as e:
            logger.warning(f"Error starting stream for {container_id[:12]}: {e}")
            return False

    async def stop_container_stream(self, container_id: str) -> bool:
        """Stop stats streaming for a container"""
        try:
            session = await self._get_session()
            async with session.post(
                f"{self.base_url}/api/streams/stop",
                json={"container_id": container_id}
            ) as resp:
                if resp.status == 200:
                    logger.debug(f"Stopped stats stream for container {container_id[:12]}")
                    return True
                else:
                    logger.warning(f"Failed to stop stream for {container_id[:12]}: {resp.status}")
                    return False
        except Exception as e:
            logger.warning(f"Error stopping stream for {container_id[:12]}: {e}")
            return False

    async def get_host_stats(self) -> Dict[str, Dict]:
        """
        Get aggregated stats for all hosts
        Returns: {host_id: {cpu_percent, memory_percent, ...}}
        """
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/api/stats/hosts") as resp:
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

    async def get_container_stats(self) -> Dict[str, Dict]:
        """
        Get stats for all containers (for debugging)
        Returns: {container_id: {cpu_percent, memory_percent, ...}}
        """
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/api/stats/containers") as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    logger.error(f"Failed to get container stats: {resp.status}")
                    return {}
        except Exception as e:
            logger.error(f"Error getting container stats from stats service: {e}")
            return {}


# Global instance
_stats_client = None

def get_stats_client() -> StatsServiceClient:
    """Get the global stats client instance"""
    global _stats_client
    if _stats_client is None:
        _stats_client = StatsServiceClient()
    return _stats_client
