"""
Simple cache wrapper that works with async functions

"""

import time
from functools import wraps

def async_ttl_cache(ttl_seconds: float = 60.0):
    global cache
    """
    Cache results of an async function for ttl_seconds.
    Adds:
      - func.invalidate()         -> clear all cache
      - func.invalidate_key(...)  -> clear specific key
    """
    def decorator(func):
        cache = {}  # key -> (result, timestamp)

        @wraps(func)
        async def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.time()

            if key in cache:
                result, ts = cache[key]
                if now - ts < ttl_seconds:
                    return result  # still fresh

            # compute and cache
            result = await func(*args, **kwargs)
            cache[key] = (result, now)
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

