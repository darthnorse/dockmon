"""
Shared image pull progress tracking for DockMon.

Provides detailed layer-by-layer progress tracking with download speeds,
used by both the update system and deployment system.

Usage (Update System):
    tracker = ImagePullProgress(loop, connection_manager)
    await tracker.pull_with_progress(
        client,
        "nginx:latest",
        host_id,
        container_id,
        event_type="container_update_layer_progress"
    )

Usage (Deployment System):
    tracker = ImagePullProgress(loop, connection_manager)
    await tracker.pull_with_progress(
        client,
        "nginx:latest",
        host_id,
        deployment_id,
        event_type="deployment_layer_progress"
    )
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional, Callable
import docker
from docker import APIClient

from utils.async_docker import async_docker_call

logger = logging.getLogger(__name__)


class ImagePullProgress:
    """
    Handles Docker image pulls with detailed layer-by-layer progress tracking.

    Features:
    - Layer status tracking (downloading, extracting, complete, cached)
    - Download speed calculation (MB/s with moving average smoothing)
    - Overall progress calculation (bytes-based)
    - WebSocket event broadcasting
    - Automatic API client cloning for streaming
    - Timeout handling
    - Connection leak prevention
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, connection_manager, progress_callback=None):
        """
        Initialize image pull progress tracker.

        Args:
            loop: Event loop for thread-safe coroutine execution
            connection_manager: ConnectionManager for WebSocket broadcasting
            progress_callback: Optional callback(host_id, entity_id, progress_data) called on each progress update
        """
        self.loop = loop
        self.connection_manager = connection_manager
        self.progress_callback = progress_callback

    async def pull_with_progress(
        self,
        client: docker.DockerClient,
        image: str,
        host_id: str,
        entity_id: str,
        event_type: str = "image_pull_layer_progress",
        timeout: int = 1800
    ):
        """
        Pull Docker image with layer-by-layer progress tracking.

        Uses Docker's low-level API to stream pull status and broadcast
        real-time progress to WebSocket clients. Handles cached layers,
        download speed calculation, and throttled broadcasting.

        CRITICAL: Wrapped in async_docker_call to prevent event loop blocking.

        Args:
            client: High-level Docker client (for base URL and TLS config)
            image: Image name with tag (e.g., "nginx:latest")
            host_id: Full UUID of the Docker host
            entity_id: Container ID (12 chars) or Deployment ID (composite key)
            event_type: WebSocket event type (e.g., "container_update_layer_progress")
            timeout: Maximum seconds for the entire pull operation

        Raises:
            TimeoutError: If pull exceeds timeout
            docker.errors.ImageNotFound: If image doesn't exist
            Exception: For other Docker API errors
        """
        # Wrap the entire streaming operation in async_docker_call
        # to prevent blocking the event loop (DockMon standard)
        await async_docker_call(
            self._stream_pull_progress,
            client,
            image,
            host_id,
            entity_id,
            event_type,
            timeout
        )

    def _stream_pull_progress(
        self,
        client: docker.DockerClient,
        image: str,
        host_id: str,
        entity_id: str,
        event_type: str,
        timeout: int
    ):
        """
        Synchronous method that streams Docker pull progress.

        Called via async_docker_call to run in thread pool.
        This is the proper pattern per CLAUDE.md standards.
        """
        # Use the low-level API client from the high-level client
        # client.api is already an APIClient instance with correct settings
        api_client = client.api

        # Layer tracking state
        layer_status = {}  # {layer_id: {"status": str, "current": int, "total": int}}

        # Progress tracking state
        last_broadcast = 0
        last_percent = 0
        last_total_bytes = 0
        last_speed_check = time.time()
        current_speed_mbps = 0.0
        speed_samples = []  # For moving average smoothing (prevents jittery display)
        total_bytes = 0  # Initialize to prevent NameError if stream has zero iterations

        start_time = time.time()

        try:
            # Stream pull with decode (returns generator of dicts)
            stream = api_client.pull(image, stream=True, decode=True)

            for line in stream:
                # Check timeout
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    raise TimeoutError(f"Image pull exceeded {timeout} seconds")

                layer_id = line.get('id')
                status = line.get('status', '')
                progress_detail = line.get('progressDetail', {})

                # Skip non-layer messages (e.g., "Pulling from library/nginx")
                if not layer_id:
                    continue

                # Log all layer status events at INFO level for extraction visibility debugging
                logger.info(f"Layer {layer_id[:12]}: {status}")

                # Handle cached layers (critical for correct progress calculation)
                if status in ['Already exists', 'Pull complete']:
                    # For cached layers, mark as complete with no download
                    existing = layer_status.get(layer_id, {})
                    total = existing.get('total', 0)

                    layer_status[layer_id] = {
                        'status': status,
                        'current': total,  # Fully "downloaded" (from cache)
                        'total': total,
                    }
                    continue

                # Update layer tracking for active downloads/extractions
                current = progress_detail.get('current', 0)
                total = progress_detail.get('total', 0)

                # Preserve total if not provided in this update
                if total == 0 and layer_id in layer_status:
                    total = layer_status[layer_id].get('total', 0)

                layer_status[layer_id] = {
                    'status': status,
                    'current': current,
                    'total': total,
                }

                # Calculate overall progress (bytes-based when available)
                total_bytes = sum(l['total'] for l in layer_status.values() if l['total'] > 0)
                downloaded_bytes = sum(l['current'] for l in layer_status.values())

                if total_bytes > 0:
                    overall_percent = int((downloaded_bytes / total_bytes) * 100)
                else:
                    # Fallback: estimate based on layer completion count
                    completed = sum(1 for l in layer_status.values() if 'complete' in l['status'].lower() or l['status'] == 'Already exists')
                    overall_percent = int((completed / max(len(layer_status), 1)) * 100)

                # Calculate download speed (MB/s) with moving average smoothing
                now = time.time()
                time_delta = now - last_speed_check

                if time_delta >= 1.0:  # Update speed every second
                    bytes_delta = downloaded_bytes - last_total_bytes
                    if bytes_delta > 0:
                        # Calculate raw speed
                        raw_speed = (bytes_delta / time_delta) / (1024 * 1024)

                        # Apply 3-sample moving average to smooth jitter on variable networks
                        speed_samples.append(raw_speed)
                        if len(speed_samples) > 3:
                            speed_samples.pop(0)

                        # Use smoothed average for display
                        current_speed_mbps = sum(speed_samples) / len(speed_samples)

                    last_total_bytes = downloaded_bytes
                    last_speed_check = now

                # Throttle broadcasts (every 500ms OR 5% change OR completion events)
                should_broadcast = (
                    now - last_broadcast >= 0.5 or  # 500ms elapsed
                    abs(overall_percent - last_percent) >= 5 or  # 5% change
                    'complete' in status.lower() or  # Always broadcast completions
                    status == 'Already exists'  # Broadcast cache hits
                )

                if should_broadcast:
                    # Run broadcast in event loop (thread-safe)
                    asyncio.run_coroutine_threadsafe(
                        self._broadcast_layer_progress(
                            host_id,
                            entity_id,
                            event_type,
                            layer_status,
                            overall_percent,
                            current_speed_mbps
                        ),
                        self.loop
                    ).result()

                    last_broadcast = now
                    last_percent = overall_percent

            # Final broadcast at 100%
            asyncio.run_coroutine_threadsafe(
                self._broadcast_layer_progress(
                    host_id,
                    entity_id,
                    event_type,
                    layer_status,
                    100,
                    current_speed_mbps
                ),
                self.loop
            ).result()

            # CRITICAL: Verify image exists after pull completes
            # Stream ending doesn't guarantee image is committed to Docker's image store
            # This prevents race conditions where containers fail with "image not found"
            # Use retry with exponential backoff to handle commit delays
            max_retries = 5
            retry_delay = 0.5  # Start with 500ms

            for attempt in range(max_retries):
                try:
                    client.images.get(image)
                    logger.info(f"Successfully pulled {image} with {len(layer_status)} layers ({total_bytes / (1024 * 1024):.1f} MB)")
                    break  # Image verified, exit retry loop
                except docker.errors.ImageNotFound:
                    if attempt < max_retries - 1:
                        # Not the last attempt, retry after delay
                        logger.warning(f"Image {image} not yet available in Docker image store (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff: 0.5s, 1s, 2s, 4s
                    else:
                        # Last attempt failed, raise error
                        logger.error(f"Image pull stream completed but image {image} not found in Docker image store after {max_retries} retries (race condition)")
                        raise RuntimeError(f"Image {image} pull appeared successful but image not available after {max_retries} verification attempts")

        except TimeoutError:
            logger.error(f"Image pull timed out after {timeout}s for {image}")
            raise
        except Exception as e:
            logger.error(f"Error streaming image pull for {image}: {e}", exc_info=True)
            raise

    async def _broadcast_layer_progress(
        self,
        host_id: str,
        entity_id: str,
        event_type: str,
        layer_status: Dict[str, Dict],
        overall_percent: int,
        speed_mbps: float = 0.0
    ):
        """
        Broadcast detailed layer progress to WebSocket clients.

        Args:
            host_id: Docker host UUID
            entity_id: Container ID or Deployment ID
            event_type: WebSocket event type
            layer_status: Dictionary of layer statuses
            overall_percent: Overall progress percentage (0-100)
            speed_mbps: Current download speed in MB/s
        """
        try:
            if not self.connection_manager:
                return

            # Calculate summary statistics
            total_layers = len(layer_status)
            downloading = sum(1 for l in layer_status.values() if l['status'] == 'Downloading')
            extracting = sum(1 for l in layer_status.values() if l['status'] == 'Extracting')
            complete = sum(1 for l in layer_status.values() if 'complete' in l['status'].lower())
            cached = sum(1 for l in layer_status.values() if l['status'] == 'Already exists')

            # Build summary message with download speed
            if total_layers == 0:
                # Edge case: image with no layers (manifest-only or unusual image)
                summary = "Pull complete (manifest only)"
            elif downloading > 0:
                speed_text = f" @ {speed_mbps:.1f} MB/s" if speed_mbps > 0 else ""
                summary = f"Downloading {downloading} of {total_layers} layers ({overall_percent}%){speed_text}"
            elif extracting > 0:
                summary = f"Extracting {extracting} of {total_layers} layers ({overall_percent}%)"
            elif complete == total_layers:
                cache_text = f" ({cached} cached)" if cached > 0 else ""
                summary = f"Pull complete ({total_layers} layers{cache_text})"
            else:
                summary = f"Pulling image ({overall_percent}%)"

            # Prepare layer data for frontend (convert to list, sorted by status)
            layers = []
            for layer_id, data in layer_status.items():
                percent = 0
                if data['total'] > 0:
                    percent = int((data['current'] / data['total']) * 100)

                layers.append({
                    'id': layer_id,
                    'status': data['status'],
                    'current': data['current'],
                    'total': data['total'],
                    'percent': percent
                })

            # Sort: downloading first, then extracting, then verifying, then complete
            # This keeps active layers at the top for better UX
            status_priority = {
                'Downloading': 1,
                'Extracting': 2,
                'Verifying Checksum': 3,
                'Download complete': 4,
                'Already exists': 5,
                'Pull complete': 6,
                'Pulling fs layer': 0
            }
            layers.sort(key=lambda l: status_priority.get(l['status'], 99))

            # Trim large layer lists for network efficiency
            # UI only displays top 15, so sending all 50+ layers is wasteful
            # Send top 20 active layers + count for remaining
            total_layer_count = len(layers)
            remaining_layers = 0
            if len(layers) > 20:
                layers_to_broadcast = layers[:20]
                remaining_layers = len(layers) - 20
            else:
                layers_to_broadcast = layers

            # Prepare progress data
            progress_data = {
                "overall_progress": overall_percent,
                "layers": layers_to_broadcast,  # Trimmed to top 20 for network efficiency
                "total_layers": total_layer_count,
                "remaining_layers": remaining_layers,
                "summary": summary,
                "speed_mbps": speed_mbps,
                "updated": time.time()
            }

            # Broadcast layer progress event
            await self.connection_manager.broadcast({
                "type": event_type,
                "data": {
                    "host_id": host_id,
                    "entity_id": entity_id,
                    **progress_data
                }
            })

            # Call optional progress callback (e.g., for _active_pulls tracking in UpdateExecutor)
            if self.progress_callback:
                self.progress_callback(host_id, entity_id, progress_data)

        except Exception as e:
            logger.error(f"Error broadcasting layer progress: {e}", exc_info=True)

