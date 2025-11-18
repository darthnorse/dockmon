"""
Simple cache wrapper that works with async functions

"""

import asyncio
import time
from collections import defaultdict
from functools import wraps
from typing import Any, Dict, Tuple, Callable

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

                # Actually compute and store
                result = await func(*args, **kwargs)
                cache[key] = (result, time.time())
                return result

        def invalidate():
            """Clear entire cache."""
            cache.clear()

        def invalidate_key(*args, **kwargs):
            """Clear cache for one specific key."""
            key = (args, tuple(sorted(kwargs.items())))
            cache.pop(key, None)

        wrapper.invalidate = invalidate
        wrapper.invalidate_key = invalidate_key
        return wrapper

    return decorator
