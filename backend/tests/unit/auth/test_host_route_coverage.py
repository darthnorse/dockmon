"""Every HTTP route with {host_id}/{source_host_id} in its path must carry
require_host_access (or the source variant) AFTER its capability guard.

Runs over app.routes, so it covers main.py and every included router, single-
and multi-line decorators alike. It does not cover WebSocket routes (guarded
in-handler, covered by the WS integration tests) or body/record-addressed
surfaces (each has its own test).
"""

from fastapi.routing import APIRoute

from auth.api_key_auth import require_host_access, require_source_host_access
from main import app

GUARD_FOR_PARAM = {"host_id": require_host_access, "source_host_id": require_source_host_access}
GUARDS = set(GUARD_FOR_PARAM.values())
EXPECTED_HOST_ROUTE_COUNT = 44


def _api_routes(routes):
    # FastAPI 0.14x registers include_router() as an _IncludedRouter entry instead of
    # flattening its routes into app.routes; descend into it (and any mount) so router
    # routes stay covered.
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif getattr(route, "original_router", None) is not None:
            yield from _api_routes(route.original_router.routes)
        elif getattr(route, "routes", None):
            yield from _api_routes(route.routes)


def _host_routes():
    return [r for r in _api_routes(app.routes) if set(GUARD_FOR_PARAM) & set(r.param_convertors)]


def _route_deps(route):
    return [d.dependency for d in route.dependencies]


def test_every_host_path_route_is_guarded():
    """Each host param needs its own guard: the guards are Path()-bound to their param name."""
    missing = [
        f"{sorted(r.methods)} {r.path} (needs {guard.__name__})"
        for r in _host_routes()
        for param, guard in GUARD_FOR_PARAM.items()
        if param in r.param_convertors and guard not in _route_deps(r)
    ]
    assert not missing, "host routes without the matching guard:\n" + "\n".join(missing)


def test_host_guard_runs_after_capability_guard():
    """403 must win over 404: a caller lacking the capability learns nothing about host ids."""
    bad = []
    for route in _host_routes():
        deps = _route_deps(route)
        cap_idx = [i for i, d in enumerate(deps) if getattr(d, "__qualname__", "").startswith("require_capability")]
        host_idx = [i for i, d in enumerate(deps) if d in GUARDS]
        if cap_idx and host_idx and min(host_idx) < max(cap_idx):
            bad.append(route.path)
    assert not bad, bad


def test_every_host_route_has_a_capability_guard():
    unguarded = [r.path for r in _host_routes()
                 if not any(getattr(d, "__qualname__", "").startswith("require_capability") for d in _route_deps(r))]
    assert not unguarded, unguarded


def test_host_route_inventory_is_known():
    """A new host route must be added deliberately: bump the count after wiring both guards."""
    routes = sorted(f"{sorted(r.methods)} {r.path}" for r in _host_routes())
    assert len(routes) == EXPECTED_HOST_ROUTE_COUNT, "\n".join(routes)
