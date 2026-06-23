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

from docker_monitor.stats_history import (
    StatsHistoryBuffer,
    ContainerStatsHistoryBuffer,
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
