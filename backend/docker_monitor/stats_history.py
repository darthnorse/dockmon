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
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# EMA smoothing factor (α = 0.3) as per specs
EMA_ALPHA = 0.3

# Keep 90 seconds of history at 2-second intervals = 45 data points
# But we'll store 50 to be safe
MAX_HISTORY_POINTS = 50


@dataclass
class HostStatsPoint:
    """Single stats data point for a host"""
    timestamp: datetime
    cpu_percent: float
    mem_percent: float
    net_bytes_per_sec: float


class StatsHistoryBuffer:
    """
    Manages historical stats data for sparkline generation

    Features:
    - Circular buffer (max 50 points = ~90s at 2s interval)
    - EMA smoothing (α = 0.3)
    - Per-host tracking
    """

    def __init__(self):
        # host_id -> deque of HostStatsPoint
        self._history: Dict[str, deque] = {}

        # Last raw values for EMA calculation
        self._last_raw: Dict[str, HostStatsPoint] = {}

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
            self._history[host_id] = deque(maxlen=MAX_HISTORY_POINTS)
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
            timestamp=datetime.now(),
            cpu_percent=cpu,
            mem_percent=mem,
            net_bytes_per_sec=net
        )

        # Add smoothed point to history
        point = HostStatsPoint(
            timestamp=datetime.now(),
            cpu_percent=smoothed_cpu,
            mem_percent=smoothed_mem,
            net_bytes_per_sec=smoothed_net
        )

        self._history[host_id].append(point)

    def get_sparklines(self, host_id: str, num_points: int = 30) -> Dict[str, List[float]]:
        """
        Get sparkline data for a host

        Args:
            host_id: Host identifier
            num_points: Number of data points to return (default 30 for UI)

        Returns:
            Dict with 'cpu', 'mem', 'net' arrays
        """
        if host_id not in self._history or len(self._history[host_id]) == 0:
            # No history yet - return empty arrays
            return {
                "cpu": [],
                "mem": [],
                "net": []
            }

        history = list(self._history[host_id])

        # If we have fewer points than requested, return what we have
        if len(history) <= num_points:
            return {
                "cpu": [p.cpu_percent for p in history],
                "mem": [p.mem_percent for p in history],
                "net": [p.net_bytes_per_sec for p in history]
            }

        # Sample evenly from history to get requested number of points
        # This ensures sparklines look smooth even with varying history lengths
        step = len(history) / num_points
        indices = [int(i * step) for i in range(num_points)]

        return {
            "cpu": [history[i].cpu_percent for i in indices],
            "mem": [history[i].mem_percent for i in indices],
            "net": [history[i].net_bytes_per_sec for i in indices]
        }

    def cleanup_old_data(self, max_age_seconds: int = 300):
        """
        Remove old stats history (older than max_age_seconds)
        Called periodically to prevent memory leaks

        Args:
            max_age_seconds: Max age in seconds (default 5 minutes)
        """
        cutoff_time = datetime.now() - timedelta(seconds=max_age_seconds)

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
