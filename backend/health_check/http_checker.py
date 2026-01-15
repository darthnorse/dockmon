"""
HTTP/HTTPS health check service for containers

Responsibilities:
- Background polling of configured HTTP endpoints
- Health state management with debouncing
- Event emission on state changes
- Auto-restart integration
"""

import asyncio
import time
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Set
import httpx

from database import ContainerHttpHealthCheck
from event_bus import Event, EventType, get_event_bus
from utils.keys import make_composite_key

logger = logging.getLogger(__name__)


class HttpHealthChecker:
    """Background service for HTTP/HTTPS health checks"""

    def __init__(self, monitor, db):
        self.monitor = monitor
        self.db = db
        self.running = False
        self.check_tasks: Dict[str, asyncio.Task] = {}

        # Track auto-restart attempts to detect restart loops (10-minute window safety net)
        # Format: {container_id: [(timestamp1, timestamp2, ...), ...]}
        self.restart_history: Dict[str, list] = {}

        # Track restart attempts per unhealthy episode (v2.0.2+)
        # Format: {container_id: attempt_count}
        self.restart_episode_attempts: Dict[str, int] = {}

        # Track last restart timestamp per container (v2.0.2+)
        # Format: {container_id: timestamp}
        self.last_restart_time: Dict[str, float] = {}

        # Cache container info to avoid O(n) lookups on every state change
        # Format: {composite_container_id: container_object}
        self._container_cache: Dict[str, any] = {}
        self._cache_last_refresh = 0.0

        # NOTE: We DON'T create a shared client because verify_ssl is per-check
        # and httpx requires verify to be set at client creation time, not per-request
        # Instead, we create a client per-check in _perform_check()
        logger.info("HttpHealthChecker initialized")

    async def start(self):
        """Start the health check service"""
        logger.info("Starting HTTP health check service")
        self.running = True

        # Main loop: reload configs every 10 seconds for near-instant config changes
        while self.running:
            try:
                await self._reload_and_schedule_checks()
                await asyncio.sleep(10)
            except Exception as e:
                logger.error(f"Error in health check main loop: {e}", exc_info=True)
                await asyncio.sleep(10)

    async def stop(self):
        """Stop the health check service"""
        logger.info("Stopping HTTP health check service")
        self.running = False

        # Cancel all running check tasks and await them to ensure clean shutdown
        for container_id, task in list(self.check_tasks.items()):
            logger.debug(f"Cancelling health check task for {container_id}")
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.debug(f"Health check task for {container_id} cancelled successfully")
            except Exception as e:
                logger.warning(f"Exception during task cancellation for {container_id}: {e}")

        # No shared client to close (clients are created per-check)
        logger.info("HTTP health checker stopped and cleaned up")

    async def _reload_and_schedule_checks(self):
        """Reload enabled backend-based health checks and schedule check tasks"""
        enabled_check_ids: Set[str] = set()

        with self.db.get_session() as session:
            # Only get backend-based checks (v2.2.0+)
            # Agent-based checks are handled by the agent
            enabled_checks = session.query(ContainerHttpHealthCheck).filter(
                ContainerHttpHealthCheck.enabled == True,
                ContainerHttpHealthCheck.check_from == 'backend'
            ).all()

            enabled_check_ids = {check.container_id for check in enabled_checks}

        # Track which checks are currently active
        current_check_ids = set(self.check_tasks.keys())

        # Cancel checks that are no longer enabled
        for container_id in current_check_ids - enabled_check_ids:
            logger.info(f"Cancelling health check for {container_id}")
            task = self.check_tasks.get(container_id)
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.warning(f"Exception while cancelling task for {container_id}: {e}")
                # Use pop() instead of del for safe removal (task may have already removed itself)
                self.check_tasks.pop(container_id, None)

            # Clean up all restart tracking for this container to prevent memory leaks
            self.restart_history.pop(container_id, None)
            self.restart_episode_attempts.pop(container_id, None)  # v2.0.2+
            self.last_restart_time.pop(container_id, None)  # v2.0.2+

        # Start new checks
        for container_id in enabled_check_ids - current_check_ids:
            logger.info(f"Starting health check for {container_id}")
            task = asyncio.create_task(self._check_loop(container_id))
            self.check_tasks[container_id] = task

    async def _check_loop(self, container_id: str):
        """Periodic health check loop for a specific container"""
        try:
            while self.running:
                try:
                    # Get current config (may have changed)
                    config_data = None
                    with self.db.get_session() as session:
                        config = session.query(ContainerHttpHealthCheck).filter_by(
                            container_id=container_id
                        ).first()

                        if not config or not config.enabled:
                            logger.info(f"Health check disabled for {container_id}, stopping loop")
                            break

                        # Extract data we need
                        config_data = {
                            'container_id': config.container_id,
                            'host_id': config.host_id,
                            'url': config.url,
                            'method': config.method,
                            'expected_status_codes': config.expected_status_codes,
                            'timeout_seconds': config.timeout_seconds,
                            'check_interval_seconds': config.check_interval_seconds,
                            'follow_redirects': config.follow_redirects,
                            'verify_ssl': config.verify_ssl,
                            'headers_json': config.headers_json,
                            'auth_config_json': config.auth_config_json,
                            'auto_restart_on_failure': config.auto_restart_on_failure,
                            'failure_threshold': config.failure_threshold,
                            'success_threshold': getattr(config, 'success_threshold', 1),  # Default to 1 for backwards compatibility
                            'max_restart_attempts': getattr(config, 'max_restart_attempts', 3),  # v2.0.2+ (default for backwards compatibility)
                            'restart_retry_delay_seconds': getattr(config, 'restart_retry_delay_seconds', 120),  # v2.0.2+ (default for backwards compatibility)
                            'current_status': config.current_status,
                        }

                    # Perform health check
                    await self._perform_check(config_data)

                    # Check if we should retry restart even without state change (v2.0.2+)
                    # This allows multiple restart attempts for truly broken services
                    if config_data['current_status'] == 'unhealthy' and config_data['auto_restart_on_failure']:
                        await self._trigger_auto_restart(
                            config_data['host_id'],
                            container_id,
                            config_data
                        )

                    # Wait for next check interval
                    await asyncio.sleep(config_data['check_interval_seconds'])

                except asyncio.CancelledError:
                    logger.info(f"Health check cancelled for {container_id}")
                    break
                except Exception as e:
                    logger.error(f"Error in check loop for {container_id}: {e}", exc_info=True)
                    await asyncio.sleep(60)  # Back off on errors

        finally:
            # Safely remove task from dict (pop never raises KeyError)
            self.check_tasks.pop(container_id, None)

    async def _perform_check(self, config: dict):
        """Perform a single HTTP health check"""
        container_id = config['container_id']
        start_time = time.time()

        # Create a dedicated client for this check with proper SSL settings
        # verify_ssl must be set at client level, not per-request
        # Connection pooling is disabled since each check creates its own client
        client_kwargs = {
            'timeout': httpx.Timeout(config['timeout_seconds']),
            'follow_redirects': config['follow_redirects'],
            'limits': httpx.Limits(max_connections=1, max_keepalive_connections=0)
        }

        # Only set verify for HTTPS URLs (SSL verification not applicable to HTTP)
        if config['url'].startswith('https://'):
            client_kwargs['verify'] = config['verify_ssl']

        async with httpx.AsyncClient(**client_kwargs) as client:
            try:
                # Parse expected status codes (cached in config dict to avoid re-parsing)
                if '_parsed_status_codes' not in config:
                    config['_parsed_status_codes'] = self._parse_status_codes(config['expected_status_codes'])
                expected_codes = config['_parsed_status_codes']

                # Build request options
                request_kwargs = {
                    'method': config['method'],
                    'url': config['url'],
                }

                # Add custom headers
                if config['headers_json']:
                    try:
                        headers = json.loads(config['headers_json'])
                        # Validate that headers is a dict with string keys and values
                        if not isinstance(headers, dict):
                            logger.warning(f"Invalid headers_json for {container_id}: must be an object, got {type(headers).__name__}")
                        else:
                            # Convert all values to strings for httpx compatibility
                            str_headers = {}
                            for key, value in headers.items():
                                if not isinstance(key, str):
                                    logger.warning(f"Invalid header key in headers_json for {container_id}: {key} is not a string")
                                    continue
                                str_headers[key] = str(value) if value is not None else ''
                            request_kwargs['headers'] = str_headers
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid headers_json for {container_id}: not valid JSON")

                # Add auth
                if config['auth_config_json']:
                    try:
                        auth_config = json.loads(config['auth_config_json'])
                        # Validate that auth_config is a dict
                        if not isinstance(auth_config, dict):
                            logger.warning(f"Invalid auth_config_json for {container_id}: must be an object, got {type(auth_config).__name__}")
                        elif auth_config.get('type') == 'basic':
                            username = auth_config.get('username')
                            password = auth_config.get('password')
                            if username is not None and password is not None:
                                request_kwargs['auth'] = (str(username), str(password))
                            else:
                                logger.warning(f"Invalid basic auth config for {container_id}: missing username or password")
                        elif auth_config.get('type') == 'bearer':
                            token = auth_config.get('token')
                            if token is not None:
                                if 'headers' not in request_kwargs:
                                    request_kwargs['headers'] = {}
                                request_kwargs['headers']['Authorization'] = f"Bearer {str(token)}"
                            else:
                                logger.warning(f"Invalid bearer auth config for {container_id}: missing token")
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid auth_config_json for {container_id}: not valid JSON")

                # Make request using the dedicated client
                response = await client.request(**request_kwargs)

                # Calculate response time
                response_time_ms = int((time.time() - start_time) * 1000)

                # Check status code
                is_healthy = response.status_code in expected_codes

                # Update state
                await self._update_check_state(
                    config,
                    is_healthy=is_healthy,
                    response_time_ms=response_time_ms,
                    error_message=None if is_healthy else f"Status {response.status_code}"
                )

            except (httpx.TimeoutException, httpx.ConnectError, Exception) as e:
                response_time_ms = int((time.time() - start_time) * 1000)

                # Generate appropriate error message based on exception type
                if isinstance(e, httpx.TimeoutException):
                    error_message = f"Timeout after {config['timeout_seconds']}s"
                elif isinstance(e, httpx.ConnectError):
                    error_message = f"Connection failed: {str(e)[:100]}"
                else:
                    error_message = f"Error: {str(e)[:100]}"

                await self._update_check_state(
                    config,
                    is_healthy=False,
                    response_time_ms=response_time_ms,
                    error_message=error_message
                )

    async def _update_check_state(
        self,
        config: dict,
        is_healthy: bool,
        response_time_ms: int,
        error_message: Optional[str]
    ):
        """Update health check state in database and emit events on state changes"""
        now = datetime.now(timezone.utc)
        container_id = config['container_id']
        old_status = config['current_status']

        # Update state in database
        with self.db.get_session() as session:
            check = session.query(ContainerHttpHealthCheck).filter_by(
                container_id=container_id
            ).first()

            if not check:
                return

            # Update counters
            if is_healthy:
                check.consecutive_successes += 1
                check.consecutive_failures = 0
                check.last_success_at = now
            else:
                check.consecutive_failures += 1
                check.consecutive_successes = 0
                check.last_failure_at = now
                check.last_error_message = error_message

            # Update metadata
            check.last_checked_at = now
            check.last_response_time_ms = response_time_ms

            # Determine new status (with debouncing on both failure and success)
            success_threshold = getattr(check, 'success_threshold', 1)
            if is_healthy and check.consecutive_successes >= success_threshold:
                new_status = 'healthy'
            elif not is_healthy and check.consecutive_failures >= check.failure_threshold:
                new_status = 'unhealthy'
            else:
                new_status = old_status  # Keep current status during debounce period

            check.current_status = new_status
            check.updated_at = now
            session.commit()

            # Log state change (INFO) or routine check (DEBUG)
            if old_status != new_status:
                logger.info(
                    f"Health check status changed for {container_id}: "
                    f"{old_status} → {new_status} "
                    f"(consecutive_failures={check.consecutive_failures})"
                )
            else:
                # Routine check with no state change - log at DEBUG level
                logger.debug(
                    f"Health check for {container_id}: {new_status} "
                    f"(response_time={response_time_ms}ms)"
                )

            # Store config data for event emission (outside session)
            # WARNING: Only access column attributes here, NOT relationships!
            # Accessing lazy-loaded relationships would trigger queries after session closes.
            event_data = {
                'host_id': check.host_id,
                'container_id': container_id,
                'old_status': old_status,
                'new_status': new_status,
                'error_message': error_message,
                'auto_restart_on_failure': check.auto_restart_on_failure,
                'max_restart_attempts': check.max_restart_attempts,  # v2.0.2+
                'restart_retry_delay_seconds': check.restart_retry_delay_seconds,  # v2.0.2+
                'health_check_url': check.url,
                'consecutive_failures': check.consecutive_failures,
                'failure_threshold': check.failure_threshold,
                'response_time_ms': check.last_response_time_ms,
            }

        # Session is now closed - safe for async operations
        if old_status != new_status:
            # Reset episode attempts when service recovers (v2.0.2+)
            if new_status == 'healthy':
                self._reset_episode_attempts(container_id)

            # Emit event on state change
            await self._emit_health_change_event(event_data)

            # Auto-restart on failure
            if new_status == 'unhealthy' and event_data['auto_restart_on_failure']:
                await self._trigger_auto_restart(event_data['host_id'], container_id, event_data)

    async def _emit_health_change_event(self, event_data: dict):
        """Emit CONTAINER_HEALTH_CHANGED event"""
        try:
            # Get container info from cache (refresh every 30 seconds)
            container = await self._get_container_cached(event_data['container_id'])

            if not container:
                logger.warning(f"Container {event_data['container_id']} not found, cannot emit health event")
                return

            # Emit event via event bus
            # container is now a dict with minimal data, not a full Container object
            event_bus = get_event_bus(self.monitor)
            await event_bus.emit(Event(
                event_type=EventType.CONTAINER_HEALTH_CHANGED,
                scope_type='container',
                scope_id=make_composite_key(event_data['host_id'], container['short_id']),
                scope_name=container['name'],
                host_id=event_data['host_id'],
                host_name=container['host_name'],
                data={
                    'old_state': event_data['old_status'],
                    'new_state': event_data['new_status'],
                    'health_check_type': 'http',
                    'error_message': event_data['error_message'],
                    'health_check_url': event_data['health_check_url'],
                    'consecutive_failures': event_data['consecutive_failures'],
                    'failure_threshold': event_data['failure_threshold'],
                    'response_time_ms': event_data['response_time_ms'],
                }
            ))

            logger.info(f"Emitted CONTAINER_HEALTH_CHANGED event for {container['name']}")

        except Exception as e:
            logger.error(f"Failed to emit health change event: {e}", exc_info=True)

    async def _get_container_cached(self, container_id: str):
        """Get container info with caching to avoid O(n) lookups

        Stores minimal data (id, name, host_name) instead of full Container objects
        to avoid holding references to Docker clients or other resources.
        """
        now = time.time()

        # Refresh cache every 30 seconds
        if now - self._cache_last_refresh > 30:
            self._container_cache.clear()
            containers = await self.monitor.get_containers()
            for c in containers:
                composite_id = f"{c.host_id}:{c.short_id}"
                # Store only minimal data to avoid memory leaks from full objects
                self._container_cache[composite_id] = {
                    'short_id': c.short_id,
                    'name': c.name,
                    'host_name': c.host_name,
                    'host_id': c.host_id,
                }
            self._cache_last_refresh = now
            logger.debug(f"Container cache refreshed: {len(self._container_cache)} containers")

        return self._container_cache.get(container_id)

    async def _trigger_auto_restart(self, host_id: str, container_id: str, event_data: dict):
        """
        Trigger automatic container restart on health failure (v2.0.2+ with retry logic)

        Args:
            host_id: Docker host ID
            container_id: Composite container ID (host_id:short_id)
            event_data: Health check event data including retry configuration
        """
        try:
            # Extract configuration from event_data
            max_attempts = event_data.get('max_restart_attempts', 3)
            retry_delay = event_data.get('restart_retry_delay_seconds', 120)

            # Extract short container ID from composite key
            if ':' not in container_id:
                logger.error(f"Invalid container_id format (missing colon): {container_id}")
                return

            _, short_id = container_id.split(':', 1)

            # Check 10-minute sliding window (safety net - prevents restart storms)
            now = time.time()
            if container_id not in self.restart_history:
                self.restart_history[container_id] = []

            # Clean old history (older than 10 minutes)
            self.restart_history[container_id] = [
                ts for ts in self.restart_history[container_id]
                if now - ts < 600
            ]

            # Check if we're in a restart loop (10-minute window safety limit)
            # Limit is 12 to allow max_attempts=10 to work with short retry delays
            if len(self.restart_history[container_id]) >= 12:
                logger.error(
                    f"Restart loop detected for {container_id}: "
                    f"{len(self.restart_history[container_id])} restarts in last 10 minutes. "
                    f"Skipping auto-restart (safety limit)."
                )
                return

            # Check episode-specific attempts (v2.0.2+)
            episode_attempts = self.restart_episode_attempts.get(container_id, 0)

            if episode_attempts >= max_attempts:
                logger.warning(
                    f"Max restart attempts ({max_attempts}) exhausted for {container_id}. "
                    f"Will retry when service recovers and fails again."
                )
                return

            # Check delay since last restart (skip first attempt - restart immediately)
            if episode_attempts > 0:
                last_restart = self.last_restart_time.get(container_id, 0)
                time_since_last = now - last_restart

                if time_since_last < retry_delay:
                    # Too soon, delay not elapsed yet
                    logger.debug(
                        f"Restart attempt {episode_attempts + 1} for {container_id} "
                        f"delayed: {int(retry_delay - time_since_last)}s remaining"
                    )
                    return

            # Perform restart
            logger.info(
                f"Auto-restarting unhealthy container {container_id} "
                f"(episode attempt {episode_attempts + 1}/{max_attempts}, "
                f"10min window: {len(self.restart_history[container_id]) + 1}/12)"
            )

            # Record this restart attempt
            self.restart_episode_attempts[container_id] = episode_attempts + 1
            self.last_restart_time[container_id] = now
            self.restart_history[container_id].append(now)

            # Restart the container (async operation - already runs Docker calls in thread pool)
            await self.monitor.restart_container(host_id, short_id)

        except Exception as e:
            logger.error(f"Failed to auto-restart container {container_id}: {e}", exc_info=True)

    def _reset_episode_attempts(self, container_id: str):
        """
        Reset restart attempt counter when service recovers (v2.0.2+)

        Called when health check status transitions from unhealthy → healthy.
        This allows a fresh set of restart attempts for the next unhealthy episode.
        """
        if container_id in self.restart_episode_attempts:
            logger.info(
                f"Resetting restart episode counter for {container_id} "
                f"(service recovered after {self.restart_episode_attempts[container_id]} attempts)"
            )
            del self.restart_episode_attempts[container_id]
            self.last_restart_time.pop(container_id, None)

    def _parse_status_codes(self, status_codes_str: str) -> set:
        """Parse expected status codes string into set of integers

        Examples:
            "200" → {200}
            "200,201,204" → {200, 201, 204}
            "200-299" → {200, 201, ..., 299}
            "200-299,301" → {200, 201, ..., 299, 301}
        """
        codes = set()

        for part in status_codes_str.split(','):
            part = part.strip()

            if '-' in part:
                # Range
                try:
                    start, end = part.split('-', 1)
                    start_code = int(start.strip())
                    end_code = int(end.strip())
                    codes.update(range(start_code, end_code + 1))
                except ValueError:
                    logger.warning(f"Invalid status code range: {part}")
            else:
                # Single code
                try:
                    codes.add(int(part))
                except ValueError:
                    logger.warning(f"Invalid status code: {part}")

        return codes if codes else {200}  # Default to 200 if parsing fails
