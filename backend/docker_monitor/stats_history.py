"""
Stats History Buffer for Sparkline Data
Phase 4c

Maintains a circular buffer of recent stats for each host to generate sparklines.
Implements EMA smoothing (α = 0.3) as specified in dockmon_metrics_collection.md
"""

import logging
from collections import deque
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# EMA smoothing factor (α = 0.3) as per specs
EMA_ALPHA = 0.3

from stats_config import DEFAULT_POINTS_PER_VIEW


@dataclass
class HostStatsPoint:
    """Single stats data point for a host"""
    timestamp: datetime
    cpu_percent: float
    mem_percent: float
    net_bytes_per_sec: float


@dataclass
class ContainerStatsPoint:
    """Single stats data point for a container"""
    timestamp: datetime
    cpu_percent: float
    mem_percent: float
    net_bytes_per_sec: float


class StatsHistoryBuffer:
    """
    Manages historical stats data for sparkline generation

    Features:
    - Circular buffer sized by points_per_view setting
    - EMA smoothing (α = 0.3)
    - Per-host tracking
    - Agent-fed host tracking (to distinguish systemd vs containerized agents)
    """

    def __init__(self, max_points: int = DEFAULT_POINTS_PER_VIEW):
        self._max_points = max_points
        # host_id -> deque of HostStatsPoint
        self._history: Dict[str, deque] = {}

        # Last raw values for EMA calculation
        self._last_raw: Dict[str, HostStatsPoint] = {}

        # Hosts actively receiving stats from agent (systemd mode)
        # host_id -> last update timestamp
        self._agent_fed_hosts: Dict[str, datetime] = {}

    def add_stats(self, host_id: str, cpu: float, mem: float, net: float):
        """
        Add a new stats point with EMA smoothing

        Args:
            host_id: Host identifier
            cpu: CPU usage percentage
            mem: Memory usage percentage
            net: Network bytes per second
        """
        # Initialize history buffer if needed
        if host_id not in self._history:
            self._history[host_id] = deque(maxlen=self._max_points)
            logger.debug(f"Initialized stats history buffer for host {host_id[:8]}")

        # Apply EMA smoothing if we have previous raw data
        if host_id in self._last_raw:
            prev = self._last_raw[host_id]

            # EMA formula: new_value = α * current + (1 - α) * previous
            smoothed_cpu = EMA_ALPHA * cpu + (1 - EMA_ALPHA) * prev.cpu_percent
            smoothed_mem = EMA_ALPHA * mem + (1 - EMA_ALPHA) * prev.mem_percent
            smoothed_net = EMA_ALPHA * net + (1 - EMA_ALPHA) * prev.net_bytes_per_sec
        else:
            # First data point - no smoothing needed
            smoothed_cpu = cpu
            smoothed_mem = mem
            smoothed_net = net

        # Store raw value for next EMA calculation
        self._last_raw[host_id] = HostStatsPoint(
            timestamp=datetime.now(timezone.utc),
            cpu_percent=cpu,
            mem_percent=mem,
            net_bytes_per_sec=net
        )

        # Add smoothed point to history
        point = HostStatsPoint(
            timestamp=datetime.now(timezone.utc),
            cpu_percent=smoothed_cpu,
            mem_percent=smoothed_mem,
            net_bytes_per_sec=smoothed_net
        )

        self._history[host_id].append(point)

    def get_sparklines(self, host_id: str, num_points: int = 0) -> Dict[str, List[float]]:
        """
        Get sparkline data for a host

        Args:
            host_id: Host identifier
            num_points: Number of data points to return (0 = all available)

        Returns:
            Dict with 'cpu', 'mem', 'net' arrays
        """
        if host_id not in self._history or len(self._history[host_id]) == 0:
            return {"cpu": [], "mem": [], "net": [], "timestamps": []}

        history = list(self._history[host_id])
        points = history[-num_points:] if num_points > 0 else history

        return {
            "cpu": [p.cpu_percent for p in points],
            "mem": [p.mem_percent for p in points],
            "net": [p.net_bytes_per_sec for p in points],
            "timestamps": [int(p.timestamp.timestamp()) for p in points],
        }

    def cleanup_old_data(self, max_age_seconds: int = 300):
        """
        Remove old stats history (older than max_age_seconds)
        Called periodically to prevent memory leaks

        Args:
            max_age_seconds: Max age in seconds (default 5 minutes)
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)

        for host_id in list(self._history.keys()):
            history = self._history[host_id]

            # Remove old points
            while history and history[0].timestamp < cutoff_time:
                history.popleft()

            # If history is empty, remove the host entry
            if not history:
                del self._history[host_id]
                if host_id in self._last_raw:
                    del self._last_raw[host_id]
                logger.debug(f"Cleaned up empty history for host {host_id[:8]}")

    def remove_host(self, host_id: str):
        """Remove all history for a host (when host is deleted)"""
        if host_id in self._history:
            del self._history[host_id]
        if host_id in self._last_raw:
            del self._last_raw[host_id]
        logger.debug(f"Removed stats history for host {host_id[:8]}")

    def get_stats_summary(self) -> dict:
        """Get summary of current stats buffer state (for debugging)"""
        return {
            "tracked_hosts": len(self._history),
            "total_points": sum(len(h) for h in self._history.values()),
            "hosts": {
                host_id[:8]: len(history)
                for host_id, history in self._history.items()
            }
        }

    def mark_agent_fed(self, host_id: str):
        """
        Mark that this host is receiving stats directly from an agent (systemd mode).
        Called from _handle_system_stats when agent sends host stats.
        """
        self._agent_fed_hosts[host_id] = datetime.now(timezone.utc)

    def is_agent_fed(self, host_id: str, max_age_seconds: int = 10) -> bool:
        """
        Check if this host is actively receiving stats from an agent.

        Args:
            host_id: Host identifier
            max_age_seconds: Max age of last agent update to consider "active"

        Returns:
            True if agent has sent stats within max_age_seconds
        """
        if host_id not in self._agent_fed_hosts:
            return False

        last_update = self._agent_fed_hosts[host_id]
        age = (datetime.now(timezone.utc) - last_update).total_seconds()
        return age < max_age_seconds


class ContainerStatsHistoryBuffer:
    """
    Manages historical stats data for container sparkline generation

    Features:
    - Circular buffer sized by points_per_view setting
    - EMA smoothing (α = 0.3)
    - Per-container tracking using composite key (host_id:container_id)
    """

    def __init__(self, max_points: int = DEFAULT_POINTS_PER_VIEW):
        self._max_points = max_points
        # composite_key (host_id:container_id) -> deque of ContainerStatsPoint
        self._history: Dict[str, deque] = {}

        # Last raw values for EMA calculation
        self._last_raw: Dict[str, ContainerStatsPoint] = {}

    def add_stats(self, container_key: str, cpu: float, mem: float, net: float):
        """
        Add a new stats point with EMA smoothing

        Args:
            container_key: Container identifier (composite key: host_id:container_id)
            cpu: CPU usage percentage
            mem: Memory usage percentage
            net: Network bytes per second
        """
        # Initialize history buffer if needed
        if container_key not in self._history:
            self._history[container_key] = deque(maxlen=self._max_points)
            logger.debug(f"Initialized stats history buffer for container {container_key[:16]}")

        # Apply EMA smoothing if we have previous raw data
        if container_key in self._last_raw:
            prev = self._last_raw[container_key]

            # EMA formula: new_value = α * current + (1 - α) * previous
            smoothed_cpu = EMA_ALPHA * cpu + (1 - EMA_ALPHA) * prev.cpu_percent
            smoothed_mem = EMA_ALPHA * mem + (1 - EMA_ALPHA) * prev.mem_percent
            smoothed_net = EMA_ALPHA * net + (1 - EMA_ALPHA) * prev.net_bytes_per_sec
        else:
            # First data point - no smoothing needed
            smoothed_cpu = cpu
            smoothed_mem = mem
            smoothed_net = net

        # Store raw value for next EMA calculation
        self._last_raw[container_key] = ContainerStatsPoint(
            timestamp=datetime.now(timezone.utc),
            cpu_percent=cpu,
            mem_percent=mem,
            net_bytes_per_sec=net
        )

        # Add smoothed point to history
        point = ContainerStatsPoint(
            timestamp=datetime.now(timezone.utc),
            cpu_percent=smoothed_cpu,
            mem_percent=smoothed_mem,
            net_bytes_per_sec=smoothed_net
        )

        self._history[container_key].append(point)

    def get_sparklines(self, container_key: str, num_points: int = 0) -> Dict[str, List[float]]:
        """
        Get sparkline data for a container

        Args:
            container_key: Container identifier (composite key: host_id:container_id)
            num_points: Number of data points to return (0 = all available)

        Returns:
            Dict with 'cpu', 'mem', 'net' arrays
        """
        if container_key not in self._history or len(self._history[container_key]) == 0:
            return {"cpu": [], "mem": [], "net": [], "timestamps": []}

        history = list(self._history[container_key])
        points = history[-num_points:] if num_points > 0 else history

        return {
            "cpu": [p.cpu_percent for p in points],
            "mem": [p.mem_percent for p in points],
            "net": [p.net_bytes_per_sec for p in points],
            "timestamps": [int(p.timestamp.timestamp()) for p in points],
        }

    def cleanup_old_data(self, max_age_seconds: int = 300):
        """
        Remove old stats history (older than max_age_seconds)
        Called periodically to prevent memory leaks

        Args:
            max_age_seconds: Max age in seconds (default 5 minutes)
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)

        for container_key in list(self._history.keys()):
            history = self._history[container_key]

            # Remove old points
            while history and history[0].timestamp < cutoff_time:
                history.popleft()

            # If history is empty, remove the container entry
            if not history:
                del self._history[container_key]
                if container_key in self._last_raw:
                    del self._last_raw[container_key]
                logger.debug(f"Cleaned up empty history for container {container_key[:16]}")

    def remove_container(self, container_key: str):
        """Remove all history for a container (when container is deleted)"""
        if container_key in self._history:
            del self._history[container_key]
        if container_key in self._last_raw:
            del self._last_raw[container_key]
        logger.debug(f"Removed stats history for container {container_key[:16]}")

    def get_stats_summary(self) -> dict:
        """Get summary of current stats buffer state (for debugging)"""
        return {
            "tracked_containers": len(self._history),
            "total_points": sum(len(h) for h in self._history.values()),
            "containers": {
                container_key[:16]: len(history)
                for container_key, history in self._history.items()
            }
        }
