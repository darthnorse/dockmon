"""
Central configuration for cascading stats tiers.
All tier intervals are derived from a single points_per_view setting.
"""

VIEWS = [
    {"name": "1h", "seconds": 3600},
    {"name": "8h", "seconds": 28800},
    {"name": "24h", "seconds": 86400},
    {"name": "7d", "seconds": 604800},
    {"name": "30d", "seconds": 2592000},
]

DEFAULT_POINTS_PER_VIEW = 500


def compute_tiers(points_per_view: int, polling_interval: float = 2.0) -> list[dict]:
    """
    Compute tier configurations from points_per_view.

    Each tier's interval = max(view_seconds / points_per_view, polling_interval).
    The max() handles polling being slower than the computed interval.

    Returns list of dicts sorted by interval (finest first):
        [{name, seconds, interval, max_points}, ...]
    """
    tiers = []
    for view in VIEWS:
        computed = view["seconds"] / points_per_view
        effective = max(computed, polling_interval)
        max_points = min(points_per_view, int(view["seconds"] / effective))
        tiers.append({
            "name": view["name"],
            "seconds": view["seconds"],
            "interval": effective,
            "max_points": max_points,
        })
    return tiers
