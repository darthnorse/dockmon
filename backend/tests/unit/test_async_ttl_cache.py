"""
Unit tests for the async_ttl_cache wrapper.

Focus: the generation counter that prevents an in-flight sweep from
writing a stale result back to the cache after invalidate() ran.
"""

import asyncio
import pytest

from utils.cache import async_ttl_cache


@pytest.mark.asyncio
async def test_caches_result_within_ttl():
    calls = {"n": 0}

    @async_ttl_cache(ttl_seconds=10.0)
    async def fetch(host_id: str) -> str:
        calls["n"] += 1
        return f"v{calls['n']}"

    assert await fetch("h") == "v1"
    assert await fetch("h") == "v1"
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_invalidate_forces_recompute():
    calls = {"n": 0}

    @async_ttl_cache(ttl_seconds=10.0)
    async def fetch(host_id: str) -> str:
        calls["n"] += 1
        return f"v{calls['n']}"

    assert await fetch("h") == "v1"
    fetch.invalidate()
    assert await fetch("h") == "v2"


@pytest.mark.asyncio
async def test_invalidate_during_inflight_sweep_rejects_stale_write():
    """
    An invalidate that fires while a sweep is awaiting must not be
    overwritten when the sweep finally returns: the post-invalidate
    state is the source of truth, and a stale repopulation would
    silently undo the invalidate for up to ttl_seconds.
    """
    started = asyncio.Event()
    proceed = asyncio.Event()
    calls = {"n": 0}

    @async_ttl_cache(ttl_seconds=10.0)
    async def fetch(host_id: str) -> str:
        calls["n"] += 1
        my_result = f"v{calls['n']}"
        started.set()
        await proceed.wait()
        return my_result

    # Start the first sweep. It will park inside the function until
    # `proceed` is set.
    sweep1 = asyncio.create_task(fetch("h"))
    await started.wait()

    # While sweep1 is parked, another caller invalidates the cache.
    fetch.invalidate()

    # Let sweep1 finish. Its result must NOT be written to the cache.
    proceed.set()
    assert await sweep1 == "v1"

    # Reset for sweep2 — but the cache shouldn't have v1 in it, so this
    # is a fresh compute.
    started.clear()
    proceed.set()  # already set, allow next call to proceed immediately
    result = await fetch("h")
    assert result == "v2"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_no_invalidate_during_sweep_caches_normally():
    """Without an intervening invalidate, the sweep's result IS cached."""
    calls = {"n": 0}

    @async_ttl_cache(ttl_seconds=10.0)
    async def fetch(host_id: str) -> str:
        calls["n"] += 1
        return f"v{calls['n']}"

    await fetch("h")
    await fetch("h")
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_invalidate_key_also_bumps_generation():
    """Per-key invalidation must reject stale repopulation too."""
    started = asyncio.Event()
    proceed = asyncio.Event()
    calls = {"n": 0}

    @async_ttl_cache(ttl_seconds=10.0)
    async def fetch(host_id: str) -> str:
        calls["n"] += 1
        my_result = f"v{calls['n']}"
        started.set()
        await proceed.wait()
        return my_result

    sweep1 = asyncio.create_task(fetch("h"))
    await started.wait()

    fetch.invalidate_key("h")

    proceed.set()
    await sweep1

    started.clear()
    proceed.set()
    assert await fetch("h") == "v2"
    assert calls["n"] == 2
