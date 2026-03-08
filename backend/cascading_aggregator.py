"""
Cascading Round Robin Database aggregator for container statistics.
Replaces the fixed-interval StatsCollector with time-window based cascading.

Data flows: raw ingest -> tier_1h -> tier_8h -> tier_24h -> tier_7d -> tier_30d
Finest tier uses MAX (preserve spikes), coarsest uses AVG (smooth noise),
intermediate tiers blend progressively between the two.
"""

import logging
import math
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func

from database import DatabaseManager, ContainerStatsHistory
from stats_config import compute_tiers, DEFAULT_POINTS_PER_VIEW

logger = logging.getLogger(__name__)


class CascadingAggregator:
    def __init__(self, db: DatabaseManager, points_per_view: int = DEFAULT_POINTS_PER_VIEW,
                 polling_interval: float = 2.0):
        self.db = db
        self.points_per_view = points_per_view
        self.polling_interval = polling_interval
        self.tiers = compute_tiers(points_per_view, polling_interval)
        # (container_id, tier_name) -> {"window_start": datetime, "pending": [dict]}
        self._state: dict[tuple[str, str], dict] = {}
        self._recover_state()

    def _recover_state(self):
        """Initialize window_start per container/tier from last DB timestamps."""
        try:
            with self.db.get_session() as session:
                for tier in self.tiers:
                    rows = session.query(
                        ContainerStatsHistory.container_id,
                        func.max(ContainerStatsHistory.timestamp),
                    ).filter(
                        ContainerStatsHistory.resolution == tier["name"],
                    ).group_by(
                        ContainerStatsHistory.container_id,
                    ).all()

                    for container_id, last_ts in rows:
                        if last_ts:
                            ts = last_ts if last_ts.tzinfo else last_ts.replace(tzinfo=timezone.utc)
                            self._state[(container_id, tier["name"])] = {
                                "window_start": ts,
                                "pending": [],
                            }

            total = len(self._state)
            if total:
                logger.info(f"Recovered RRD state for {total} container/tier pairs")
        except Exception as e:
            logger.error(f"Failed to recover RRD state: {e}", exc_info=True)

    def reconfigure(self, points_per_view: int, polling_interval: float):
        """Re-compute tiers after a settings change."""
        self.points_per_view = points_per_view
        self.polling_interval = polling_interval
        self.tiers = compute_tiers(points_per_view, polling_interval)
        logger.info(f"RRD reconfigured: points_per_view={points_per_view}, "
                     f"polling={polling_interval}s, tiers={len(self.tiers)}")

    def ingest(self, container_id: str, host_id: str, timestamp: datetime,
               cpu: Optional[float], mem_usage: Optional[int],
               mem_limit: Optional[int], net_rx: Optional[float]):
        """Feed a raw data point into the cascade."""
        value = {"cpu": cpu, "mem_usage": mem_usage, "mem_limit": mem_limit, "net_rx": net_rx}
        self._feed_tier(0, container_id, host_id, timestamp, value)

    @staticmethod
    def _quantize_ts(timestamp: datetime, interval: float) -> datetime:
        """Round timestamp down to the nearest tier-interval bucket."""
        epoch = timestamp.replace(tzinfo=timezone.utc).timestamp()
        quantized = math.floor(epoch / interval) * interval
        return datetime.fromtimestamp(quantized, tz=timezone.utc)

    def _feed_tier(self, tier_idx: int, container_id: str, host_id: str,
                   timestamp: datetime, value: dict):
        if tier_idx >= len(self.tiers):
            return

        tier = self.tiers[tier_idx]
        key = (container_id, tier["name"])

        if key not in self._state:
            self._state[key] = {"window_start": timestamp, "pending": []}

        state = self._state[key]
        state["pending"].append(value)

        elapsed = (timestamp - state["window_start"]).total_seconds()
        if elapsed >= tier["interval"]:
            alpha = max(0.0, 0.75 - tier_idx * 0.25)
            agg = self._aggregate_blend(state["pending"], alpha)
            bucket_ts = self._quantize_ts(timestamp, tier["interval"])
            self._write_point(tier["name"], container_id, host_id, bucket_ts, agg)

            self._feed_tier(tier_idx + 1, container_id, host_id, bucket_ts, agg)

            state["pending"] = []
            state["window_start"] = timestamp

    @staticmethod
    def _aggregate_blend(values: list[dict], alpha: float) -> dict:
        """Blend MAX and AVG: alpha=1.0 → pure MAX, alpha=0.0 → pure AVG."""
        if not values:
            return {"cpu": None, "mem_usage": None, "mem_limit": None, "net_rx": None}

        def blended(key):
            nums = [v[key] for v in values if v.get(key) is not None]
            if not nums:
                return None
            return alpha * max(nums) + (1 - alpha) * (sum(nums) / len(nums))

        return {
            "cpu": blended("cpu"),
            "mem_usage": blended("mem_usage"),
            "mem_limit": values[-1].get("mem_limit"),
            "net_rx": blended("net_rx"),
        }

    def _write_point(self, tier_name: str, container_id: str, host_id: str,
                     timestamp: datetime, agg: dict):
        try:
            with self.db.get_session() as session:
                session.add(ContainerStatsHistory(
                    container_id=container_id,
                    host_id=host_id,
                    timestamp=timestamp,
                    cpu_percent=agg["cpu"],
                    memory_usage=agg["mem_usage"],
                    memory_limit=agg["mem_limit"],
                    network_rx_bytes=agg["net_rx"],
                    resolution=tier_name,
                ))
                session.commit()
        except Exception as e:
            logger.error(f"Failed to write RRD point ({tier_name}/{container_id[:16]}): {e}")

    def enforce_ring_buffers(self):
        """Delete excess rows per container/tier. Call periodically (e.g. daily)."""
        total_deleted = 0
        try:
            with self.db.get_session() as session:
                for tier in self.tiers:
                    subq = session.query(
                        ContainerStatsHistory.container_id,
                        func.count().label("cnt"),
                    ).filter(
                        ContainerStatsHistory.resolution == tier["name"],
                    ).group_by(
                        ContainerStatsHistory.container_id,
                    ).having(func.count() > tier["max_points"]).subquery()

                    containers_over = session.query(subq.c.container_id, subq.c.cnt).all()

                    for cid, cnt in containers_over:
                        excess = cnt - tier["max_points"]
                        oldest_ids = session.query(ContainerStatsHistory.id).filter(
                            ContainerStatsHistory.container_id == cid,
                            ContainerStatsHistory.resolution == tier["name"],
                        ).order_by(
                            ContainerStatsHistory.timestamp,
                        ).limit(excess).all()

                        if oldest_ids:
                            ids = [r[0] for r in oldest_ids]
                            session.query(ContainerStatsHistory).filter(
                                ContainerStatsHistory.id.in_(ids),
                            ).delete(synchronize_session=False)
                            total_deleted += len(ids)

                session.commit()
        except Exception as e:
            logger.error(f"Ring buffer enforcement failed: {e}", exc_info=True)

        if total_deleted:
            logger.info(f"Ring buffer cleanup: deleted {total_deleted} excess rows")
        return total_deleted

    def remove_container(self, container_id: str):
        """Clean up in-memory state when a container is removed."""
        keys_to_remove = [k for k in self._state if k[0] == container_id]
        for k in keys_to_remove:
            del self._state[k]
