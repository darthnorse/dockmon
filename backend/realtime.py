"""
Real-time monitoring and WebSocket management for DockMon
Provides live container updates and stats streaming
Note: Docker event monitoring is now handled by the Go service
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Set, Optional, Any
from dataclasses import dataclass, asdict
import docker
from docker.models.containers import Container as DockerContainer

logger = logging.getLogger(__name__)

# Custom JSON encoder for datetime objects
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat() + 'Z'
        return super().default(obj)

@dataclass
class ContainerStats:
    """Real-time container statistics (used for WebSocket stats streaming)"""
    container_id: str
    cpu_percent: float
    memory_mb: float
    memory_percent: float
    memory_limit_mb: float
    network_rx_mb: float
    network_tx_mb: float
    block_read_mb: float
    block_write_mb: float
    pids: int
    timestamp: str

class RealtimeMonitor:
    """Manages real-time container monitoring and events"""

    def __init__(self):
        self.stats_subscribers: Dict[str, Set[Any]] = {}  # container_id -> set of websockets
        self.event_subscribers: Set[Any] = set()  # websockets listening to all events
        self.monitoring_tasks: Dict[str, asyncio.Task] = {}

    async def subscribe_to_stats(self, websocket: Any, container_id: str):
        """Subscribe a websocket to container stats"""
        if container_id not in self.stats_subscribers:
            self.stats_subscribers[container_id] = set()

        self.stats_subscribers[container_id].add(websocket)
        logger.info(f"WebSocket subscribed to stats for container {container_id}")

    async def unsubscribe_from_stats(self, websocket: Any, container_id: str):
        """Unsubscribe a websocket from container stats"""
        if container_id in self.stats_subscribers:
            self.stats_subscribers[container_id].discard(websocket)
            if not self.stats_subscribers[container_id]:
                del self.stats_subscribers[container_id]
                # Stop monitoring if no subscribers
                if container_id in self.monitoring_tasks:
                    self.monitoring_tasks[container_id].cancel()
                    del self.monitoring_tasks[container_id]

    async def subscribe_to_events(self, websocket: Any):
        """Subscribe a websocket to all Docker events"""
        self.event_subscribers.add(websocket)
        logger.info("WebSocket subscribed to Docker events")

    async def unsubscribe_from_events(self, websocket: Any):
        """Unsubscribe a websocket from Docker events"""
        self.event_subscribers.discard(websocket)

    async def start_container_stats_stream(self, client: docker.DockerClient,
                                          container_id: str, interval: int = 2):
        """Start streaming stats for a specific container"""
        if container_id in self.monitoring_tasks:
            return  # Already monitoring

        task = asyncio.create_task(
            self._monitor_container_stats(client, container_id, interval)
        )
        self.monitoring_tasks[container_id] = task

    async def _monitor_container_stats(self, client: docker.DockerClient,
                                      container_id: str, interval: int):
        """Monitor and broadcast container stats"""
        logger.info(f"Starting stats monitoring for container {container_id}")

        while container_id in self.stats_subscribers and self.stats_subscribers[container_id]:
            try:
                container = client.containers.get(container_id)

                if container.status != 'running':
                    await asyncio.sleep(interval)
                    continue

                stats = self._calculate_container_stats(container)

                # Broadcast to all subscribers
                dead_sockets = []
                for websocket in self.stats_subscribers.get(container_id, []):
                    try:
                        await websocket.send_text(json.dumps({
                            "type": "container_stats",
                            "data": asdict(stats)
                        }, cls=DateTimeEncoder))
                    except Exception as e:
                        logger.error(f"Error sending stats to websocket: {e}")
                        dead_sockets.append(websocket)

                # Clean up dead sockets
                for ws in dead_sockets:
                    await self.unsubscribe_from_stats(ws, container_id)

            except docker.errors.NotFound:
                logger.warning(f"Container {container_id} not found")
                break
            except Exception as e:
                logger.error(f"Error monitoring container {container_id}: {e}")

            await asyncio.sleep(interval)

        logger.info(f"Stopped stats monitoring for container {container_id}")

    def _calculate_container_stats(self, container: DockerContainer) -> ContainerStats:
        """Calculate container statistics from Docker stats API"""
        try:
            stats = container.stats(stream=False)

            # CPU calculation
            cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - \
                       stats["precpu_stats"]["cpu_usage"]["total_usage"]
            system_cpu_delta = stats["cpu_stats"]["system_cpu_usage"] - \
                              stats["precpu_stats"]["system_cpu_usage"]
            number_cpus = len(stats["cpu_stats"]["cpu_usage"].get("percpu_usage", [1]))

            cpu_percent = 0.0
            if system_cpu_delta > 0.0 and cpu_delta > 0.0:
                cpu_percent = (cpu_delta / system_cpu_delta) * number_cpus * 100.0

            # Memory calculation
            mem_stats = stats.get("memory_stats", {})
            mem_usage = mem_stats.get("usage", 0)
            mem_limit = mem_stats.get("limit", 1)
            mem_percent = (mem_usage / mem_limit) * 100 if mem_limit > 0 else 0

            # Network I/O
            networks = stats.get("networks", {})
            net_rx = sum(net.get("rx_bytes", 0) for net in networks.values())
            net_tx = sum(net.get("tx_bytes", 0) for net in networks.values())

            # Block I/O
            blkio = stats.get("blkio_stats", {})
            io_read = 0
            io_write = 0

            if "io_service_bytes_recursive" in blkio:
                for item in blkio["io_service_bytes_recursive"]:
                    if item["op"] == "Read":
                        io_read += item["value"]
                    elif item["op"] == "Write":
                        io_write += item["value"]

            # Process count
            pids = stats.get("pids_stats", {}).get("current", 0)

            return ContainerStats(
                container_id=container.id[:12],
                cpu_percent=round(cpu_percent, 2),
                memory_mb=round(mem_usage / (1024 * 1024), 2),
                memory_percent=round(mem_percent, 2),
                memory_limit_mb=round(mem_limit / (1024 * 1024), 2),
                network_rx_mb=round(net_rx / (1024 * 1024), 2),
                network_tx_mb=round(net_tx / (1024 * 1024), 2),
                block_read_mb=round(io_read / (1024 * 1024), 2),
                block_write_mb=round(io_write / (1024 * 1024), 2),
                pids=pids,
                timestamp=datetime.now(timezone.utc).isoformat()
            )
        except Exception as e:
            logger.error(f"Error calculating stats: {e}")
            return ContainerStats(
                container_id=container.id[:12],
                cpu_percent=0,
                memory_mb=0,
                memory_percent=0,
                memory_limit_mb=0,
                network_rx_mb=0,
                network_tx_mb=0,
                block_read_mb=0,
                block_write_mb=0,
                pids=0,
                timestamp=datetime.now(timezone.utc).isoformat()
            )

    def stop_all_monitoring(self):
        """Stop all monitoring tasks"""
        logger.info("Stopping all monitoring tasks")

        # Cancel stats monitoring
        for task in self.monitoring_tasks.values():
            task.cancel()
        self.monitoring_tasks.clear()