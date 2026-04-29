"""
Simple cache wrapper that works with async functions

"""

import asyncio
import time
from collections import defaultdict
from functools import wraps
from typing import Any, Dict, Tuple

CACHE_REGISTRY = {}

def async_ttl_cache(ttl_seconds: float = 60.0):
    """
    Cache results of an async function for ttl_seconds.
    Adds:
      - func.invalidate()         -> clear all cache
      - func.invalidate_key(...)  -> clear specific key
    """
    def decorator(func):
        cache: Dict[Any, Tuple[Any, float]] = {}
        locks: Dict[Any, asyncio.Lock] = defaultdict(asyncio.Lock)
        # Bumped on every invalidate(). Sweeps capture the value at start
        # and refuse to write their result back if it changed mid-flight —
        # otherwise an in-flight sweep that began before invalidate would
        # repopulate the cache with stale data right after we cleared it.
        generation = [0]

        def make_key(args, kwargs):
            # Simple, deterministic key; adjust if you have unhashable args
            return (args, tuple(sorted(kwargs.items())))

        @wraps(func)
        async def wrapper(*args, **kwargs):
            key = make_key(args, kwargs)
            now = time.time()

            entry = cache.get(key)
            if entry is not None:
                result, ts = entry
                if now - ts < ttl_seconds:
                    return result

            # compute and cache
            lock = locks[key]
            async with lock:
                now = time.time()
                entry = cache.get(key)
                if entry is not None:
                    result, ts = entry
                    if now - ts < ttl_seconds:
                        return result

                sweep_gen = generation[0]
                result = await func(*args, **kwargs)
                if sweep_gen == generation[0]:
                    cache[key] = (result, time.time())
                return result

        def invalidate():
            """Clear entire cache and reject any in-flight sweep's result."""
            generation[0] += 1
            cache.clear()

        def invalidate_key(*args, **kwargs):
            """Clear cache for one specific key."""
            generation[0] += 1
            key = (args, tuple(sorted(kwargs.items())))
            cache.pop(key, None)

        wrapper.invalidate = invalidate
        wrapper.invalidate_key = invalidate_key

        CACHE_REGISTRY[func.__name__] = wrapper
        return wrapper

    return decorator
