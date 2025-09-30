"""
Real-time monitoring and WebSocket management for DockMon
Provides live container updates, stats streaming, and Docker event monitoring
"""

import asyncio
import json
import logging
import threading
from datetime import datetime
from typing import Dict, List, Set, Optional, Any
from dataclasses import dataclass, asdict
import docker
from docker.models.containers import Container as DockerContainer

logger = logging.getLogger(__name__)

# Custom JSON encoder for datetime objects
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

@dataclass
class ContainerStats:
    """Real-time container statistics"""
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

@dataclass
class DockerEvent:
    """Docker system event"""
    action: str  # start, stop, die, kill, pause, unpause, restart, create, destroy
    container_id: str
    container_name: str
    image: str
    host_id: str
    timestamp: str
    attributes: dict

class RealtimeMonitor:
    """Manages real-time container monitoring and events"""

    def __init__(self):
        self.stats_subscribers: Dict[str, Set[Any]] = {}  # container_id -> set of websockets
        self.event_subscribers: Set[Any] = set()  # websockets listening to all events
        self.monitoring_tasks: Dict[str, asyncio.Task] = {}
        self.event_tasks: Dict[str, asyncio.Task] = {}
        self.notification_service = None  # Will be set after initialization to avoid circular imports
        self.event_queues: Dict[str, asyncio.Queue] = {}  # Event queues for each host
        self.event_threads: Dict[str, threading.Thread] = {}  # Event threads for each host
        self.event_thread_stop: Dict[str, threading.Event] = {}  # Stop signals for threads

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
                timestamp=datetime.now().isoformat()
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
                timestamp=datetime.now().isoformat()
            )

    def start_event_monitor(self, client: docker.DockerClient, host_id: str):
        """Start monitoring Docker events for a host"""

        # Always stop any existing monitor first to prevent duplicates
        if host_id in self.event_tasks:
            existing_task = self.event_tasks[host_id]
            existing_task.cancel()
            del self.event_tasks[host_id]

        if host_id in self.event_threads:
            # Signal thread to stop (it will check if host_id is in event_tasks)
            pass

        # Create event queue for this host
        self.event_queues[host_id] = asyncio.Queue()

        # Create stop event for this thread
        self.event_thread_stop[host_id] = threading.Event()

        # Start dedicated thread for event stream
        # Pass the current event loop to the thread (if it exists)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No event loop running yet (during startup) - use get_event_loop()
            loop = asyncio.get_event_loop()

        thread = threading.Thread(
            target=self._event_stream_thread,
            args=(client, host_id, loop),
            daemon=True
        )
        thread.start()
        self.event_threads[host_id] = thread

        # Start async task to process events from queue (only if loop is running)
        try:
            # Check if there's a running event loop
            asyncio.get_running_loop()
            # If we get here, there's a running loop, so create the task
            task = asyncio.create_task(self._process_docker_events(host_id))
            self.event_tasks[host_id] = task
        except RuntimeError:
            # No running event loop yet - task will be started when loop starts
            logger.debug(f"Event processing task for host {host_id} will start when event loop starts")

    def stop_event_monitoring(self, host_id: str):
        """Stop event monitoring for a specific host"""
        # Signal thread to stop
        if host_id in self.event_thread_stop:
            self.event_thread_stop[host_id].set()
            del self.event_thread_stop[host_id]

        if host_id in self.event_tasks:
            task = self.event_tasks[host_id]
            task.cancel()
            del self.event_tasks[host_id]
        if host_id in self.event_queues:
            del self.event_queues[host_id]
        if host_id in self.event_threads:
            del self.event_threads[host_id]

    def _event_stream_thread(self, client: docker.DockerClient, host_id: str, loop):
        """Dedicated thread to read Docker events and put them in a queue"""
        logger.info(f"Event stream thread started for host {host_id}")

        try:
            events = client.events(decode=True, filters={"type": "container"})

            for event in events:
                # Check if we should stop using the threading.Event
                stop_event = self.event_thread_stop.get(host_id)
                if stop_event and stop_event.is_set():
                    logger.info(f"Event stream thread for host {host_id} stopping (stop signal received)")
                    break

                # Put event in queue (thread-safe, fire-and-forget)
                try:
                    queue = self.event_queues.get(host_id)
                    if queue:
                        # Use run_coroutine_threadsafe without waiting for completion
                        asyncio.run_coroutine_threadsafe(
                            queue.put(event),
                            loop
                        )
                except Exception as e:
                    logger.error(f"Error scheduling event for queue for host {host_id}: {e}")

        except Exception as e:
            logger.error(f"Error in event stream thread for host {host_id}: {e}")
        finally:
            logger.info(f"Event stream thread stopped for host {host_id}")

    async def _process_docker_events(self, host_id: str):
        """Process Docker events from the queue"""
        logger.info(f"Starting Docker event processing for host {host_id}")

        try:
            queue = self.event_queues[host_id]

            while host_id in self.event_tasks:
                try:
                    # Wait for event with timeout
                    event = await asyncio.wait_for(queue.get(), timeout=5.0)

                    # Parse event
                    docker_event = DockerEvent(
                        action=event.get("Action", ""),
                        container_id=event.get("id", "")[:12],
                        container_name=event.get("Actor", {}).get("Attributes", {}).get("name", ""),
                        image=event.get("Actor", {}).get("Attributes", {}).get("image", ""),
                        host_id=host_id,
                        timestamp=datetime.fromtimestamp(event.get("time", 0)).isoformat(),
                        attributes=event.get("Actor", {}).get("Attributes", {})
                    )

                    # Filter out noisy health check events
                    # Check if this is a health check by looking at the original event
                    event_str = str(event)
                    if docker_event.action.startswith('exec_') and 'healthcheck' in event_str:
                        # Skip health check events - they're too noisy
                        continue

                    # Process event for alerts if notification service is available
                    if self.notification_service and docker_event.action in [
                        'die', 'oom', 'kill', 'health_status', 'restart'
                    ]:
                        # Get exit code for die events
                        exit_code = None
                        if docker_event.action == 'die':
                            exit_code_str = docker_event.attributes.get('exitCode', '0')
                            try:
                                exit_code = int(exit_code_str)
                            except (ValueError, TypeError):
                                exit_code = None

                        # Create alert event
                        from notifications import DockerEventAlert
                        alert_event = DockerEventAlert(
                            container_id=docker_event.container_id,
                            container_name=docker_event.container_name,
                            host_id=docker_event.host_id,
                            event_type=docker_event.action,
                            timestamp=datetime.now(),
                            attributes=docker_event.attributes,
                            exit_code=exit_code
                        )

                        # Process in background to not block event monitoring
                        asyncio.create_task(self.notification_service.process_docker_event(alert_event))

                    # Broadcast to all subscribers
                    dead_sockets = []
                    for websocket in self.event_subscribers:
                        try:
                            await websocket.send_text(json.dumps({
                                "type": "docker_event",
                                "data": asdict(docker_event)
                            }, cls=DateTimeEncoder))
                        except Exception as e:
                            logger.error(f"Error sending event to websocket: {e}")
                            dead_sockets.append(websocket)

                    # Clean up dead sockets
                    for ws in dead_sockets:
                        await self.unsubscribe_from_events(ws)

                except asyncio.TimeoutError:
                    # Timeout is normal - just continue the loop
                    continue
                except Exception as e:
                    logger.error(f"Error in event monitoring loop: {e}")
                    await asyncio.sleep(1)  # Brief pause before retrying

                # Small delay to prevent overwhelming
                await asyncio.sleep(0.1)

        except Exception as e:
            logger.error(f"Error monitoring Docker events: {e}")
        finally:
            logger.info(f"Stopped Docker event monitoring for host {host_id}")
            if host_id in self.event_tasks:
                del self.event_tasks[host_id]

    async def broadcast_container_update(self, containers: List[Any], hosts: List[Any]):
        """Broadcast container updates to all subscribers"""
        message = {
            "type": "containers_update",
            "data": {
                "containers": containers,
                "hosts": hosts,
                "timestamp": datetime.now().isoformat()
            }
        }

        dead_sockets = []
        for websocket in self.event_subscribers:
            try:
                await websocket.send_text(json.dumps(message, cls=DateTimeEncoder))
            except Exception as e:
                logger.error(f"Error broadcasting update: {e}")
                dead_sockets.append(websocket)

        for ws in dead_sockets:
            await self.unsubscribe_from_events(ws)

    def stop_all_monitoring(self):
        """Stop all monitoring tasks"""
        logger.info("Stopping all monitoring tasks")

        # Cancel stats monitoring
        for task in self.monitoring_tasks.values():
            task.cancel()
        self.monitoring_tasks.clear()

        # Cancel event monitoring
        for task in self.event_tasks.values():
            task.cancel()
        self.event_tasks.clear()

class LiveUpdateManager:
    """Manages live updates with throttling and batching"""

    def __init__(self, batch_interval: float = 0.5):
        self.pending_updates: Dict[str, Any] = {}
        self.batch_interval = batch_interval
        self.batch_task: Optional[asyncio.Task] = None
        self.subscribers: Set[Any] = set()

    async def add_update(self, update_type: str, data: Any):
        """Add an update to the pending batch"""
        key = f"{update_type}:{data.get('container_id', 'global')}"
        self.pending_updates[key] = {
            "type": update_type,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }

        # Start batch task if not running
        if not self.batch_task or self.batch_task.done():
            self.batch_task = asyncio.create_task(self._process_batch())

    async def _process_batch(self):
        """Process and send batched updates"""
        await asyncio.sleep(self.batch_interval)

        if not self.pending_updates:
            return

        # Send all pending updates
        updates = list(self.pending_updates.values())
        self.pending_updates.clear()

        message = {
            "type": "batch_update",
            "updates": updates,
            "timestamp": datetime.now().isoformat()
        }

        dead_sockets = []
        for websocket in self.subscribers:
            try:
                await websocket.send_text(json.dumps(message, cls=DateTimeEncoder))
            except Exception as e:
                logger.error(f"Error sending batch update: {e}")
                dead_sockets.append(websocket)

        # Clean up dead sockets
        for ws in dead_sockets:
            self.subscribers.discard(ws)