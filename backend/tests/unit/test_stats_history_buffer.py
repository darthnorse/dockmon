"""Unit tests for the in-memory live stats buffers (stats_history.py).

Covers the live-chart-window feature additions:
- get_sparklines(include_extended=True) carries timestamps + memory bytes for
  the on-demand detail-view fetch.
- The lean default output stays {cpu, mem, net} so the WebSocket broadcast is
  byte-identical (regression guard - the whole reason the 10-min window was
  scoped out of #231).
- The buffer holds far more than the old 50-point cap so a multi-minute live
  window is possible.
"""

from datetime import datetime, timedelta, timezone

from docker_monitor.stats_history import (
    BROADCAST_POINTS,
    ContainerStatsHistoryBuffer,
    StatsHistoryBuffer,
    live_buffer_max_age_seconds,
)


class TestHostBuffer:
    def test_lean_default_shape_unchanged_broadcast_guard(self):
        # REGRESSION GUARD: the broadcast consumes the lean output. Adding the
        # extended mode must NOT change the default shape.
        buf = StatsHistoryBuffer()
        buf.add_stats("h1", cpu=10.0, mem=20.0, net=5.0)
        out = buf.get_sparklines("h1")
        assert set(out.keys()) == {"cpu", "mem", "net"}

    def test_extended_includes_timestamps_and_memory_bytes(self):
        buf = StatsHistoryBuffer()
        buf.add_stats("h1", cpu=10.0, mem=20.0, net=5.0,
                      memory_used_bytes=1000, memory_limit_bytes=8000)
        buf.add_stats("h1", cpu=12.0, mem=22.0, net=6.0,
                      memory_used_bytes=1100, memory_limit_bytes=8000)
        out = buf.get_sparklines("h1", include_extended=True)
        assert set(out.keys()) == {
            "timestamps", "cpu", "mem", "net",
            "memory_used_bytes", "memory_limit_bytes",
        }
        assert len(out["timestamps"]) == 2
        assert all(isinstance(t, float) for t in out["timestamps"])
        # Memory bytes are stored raw (absolute snapshots), not EMA-smoothed.
        assert out["memory_used_bytes"] == [1000, 1100]
        assert out["memory_limit_bytes"] == [8000, 8000]

    def test_extended_memory_defaults_to_none(self):
        buf = StatsHistoryBuffer()
        buf.add_stats("h1", cpu=10.0, mem=20.0, net=5.0)
        out = buf.get_sparklines("h1", include_extended=True)
        assert out["memory_used_bytes"] == [None]
        assert out["memory_limit_bytes"] == [None]

    def test_extended_empty_returns_all_keys(self):
        buf = StatsHistoryBuffer()
        out = buf.get_sparklines("missing", include_extended=True)
        assert out == {
            "timestamps": [], "cpu": [], "mem": [], "net": [],
            "memory_used_bytes": [], "memory_limit_bytes": [],
        }

    def test_buffer_holds_more_than_50_points(self):
        # A multi-minute live window at 2s needs hundreds of points; the old
        # 50-point cap is too small.
        buf = StatsHistoryBuffer()
        for i in range(400):
            buf.add_stats("h1", cpu=float(i), mem=1.0, net=1.0)
        out = buf.get_sparklines("h1", num_points=400)
        assert len(out["cpu"]) == 400


class TestContainerBuffer:
    def test_lean_default_shape_unchanged_broadcast_guard(self):
        buf = ContainerStatsHistoryBuffer()
        buf.add_stats("h1:abc123abc123", cpu=10.0, mem=20.0, net=5.0)
        out = buf.get_sparklines("h1:abc123abc123")
        assert set(out.keys()) == {"cpu", "mem", "net"}

    def test_extended_includes_timestamps_and_memory_bytes(self):
        buf = ContainerStatsHistoryBuffer()
        key = "h1:abc123abc123"
        buf.add_stats(key, cpu=10.0, mem=20.0, net=5.0,
                      memory_used_bytes=2000, memory_limit_bytes=16000)
        out = buf.get_sparklines(key, include_extended=True)
        assert set(out.keys()) == {
            "timestamps", "cpu", "mem", "net",
            "memory_used_bytes", "memory_limit_bytes",
        }
        assert out["memory_used_bytes"] == [2000]
        assert out["memory_limit_bytes"] == [16000]

    def test_buffer_holds_more_than_50_points(self):
        buf = ContainerStatsHistoryBuffer()
        key = "h1:abc123abc123"
        for i in range(400):
            buf.add_stats(key, cpu=float(i), mem=1.0, net=1.0)
        out = buf.get_sparklines(key, num_points=400)
        assert len(out["cpu"]) == 400


class TestLiveBufferMaxAge:
    """The per-tick age threshold that makes buffer RAM scale with the setting.

    cleanup_old_data is called each monitoring tick with this value, so each
    entity holds ~the configured live window of points and no more -- which is
    what makes the "higher window = more server RAM" help text truthful.
    """

    def test_returns_window_when_window_exceeds_broadcast_floor(self):
        # 600s window at 2s polling: the broadcast needs only 30*2=60s, so the
        # configured window governs how much is buffered.
        assert live_buffer_max_age_seconds(600, 2) == 600

    def test_broadcast_floor_protects_dashboard_for_small_window(self):
        # A 60s window at 5s polling would buffer only 12 points -> too few for
        # the 30-point broadcast sparkline. The floor (30*5=150s) wins so the
        # dashboard cards are never starved by a tiny live window.
        assert live_buffer_max_age_seconds(60, 5) == BROADCAST_POINTS * 5

    def test_handles_float_polling_interval(self):
        # polling_interval may be fractional; result is an int seconds value.
        result = live_buffer_max_age_seconds(600, 2.5)
        assert result == 600
        assert isinstance(result, int)


class TestCleanupAgeTrim:
    """Reviving cleanup_old_data: age-trim bounds buffer size by the window."""

    def test_host_cleanup_trims_old_points_keeps_recent(self):
        buf = StatsHistoryBuffer()
        for i in range(10):
            buf.add_stats("h1", cpu=float(i), mem=1.0, net=1.0)
        # Age the 5 oldest points well beyond the window.
        stale = datetime.now(timezone.utc) - timedelta(seconds=1000)
        for point in list(buf._history["h1"])[:5]:
            point.timestamp = stale
        buf.cleanup_old_data(max_age_seconds=600)
        assert len(buf._history["h1"]) == 5

    def test_container_cleanup_trims_old_points_keeps_recent(self):
        buf = ContainerStatsHistoryBuffer()
        key = "h1:abc123abc123"
        for i in range(10):
            buf.add_stats(key, cpu=float(i), mem=1.0, net=1.0)
        stale = datetime.now(timezone.utc) - timedelta(seconds=1000)
        for point in list(buf._history[key])[:5]:
            point.timestamp = stale
        buf.cleanup_old_data(max_age_seconds=600)
        assert len(buf._history[key]) == 5

    def test_host_cleanup_drops_fully_stale_entity(self):
        # An entity with no fresh points (offline) ages out completely, freeing
        # its buffer + EMA state -- empty arrays afterward, same as today.
        buf = StatsHistoryBuffer()
        buf.add_stats("gone", cpu=1.0, mem=1.0, net=1.0)
        stale = datetime.now(timezone.utc) - timedelta(seconds=1000)
        for point in buf._history["gone"]:
            point.timestamp = stale
        buf.cleanup_old_data(max_age_seconds=600)
        assert "gone" not in buf._history
        assert buf.get_sparklines("gone") == {"cpu": [], "mem": [], "net": []}
