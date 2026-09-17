"""
Response filtering utilities for multi-user support (v2.3.0+)

Centralizes role-based data filtering to eliminate duplication and ensure
consistent behavior across API endpoints and WebSocket broadcasts.
"""

import copy
import json
from typing import Any, Callable, Dict, List, Optional, Set, Union

from utils.keys import host_of_composite_key


def filter_container_env(
    containers: List[Any],
    can_view_env: bool
) -> List[Dict]:
    """
    Filter environment variables from container data for unauthorized users.

    Args:
        containers: List of container objects (dict, Pydantic model, or dataclass)
        can_view_env: True if user has containers.view_env capability

    Returns:
        List of container dicts with env filtered if unauthorized
    """
    if can_view_env:
        # Convert to dicts but preserve env
        return [container_to_dict(c) for c in containers]

    # Filter env from each container
    filtered = []
    for c in containers:
        c_dict = container_to_dict(c)
        c_dict.pop('env', None)
        filtered.append(c_dict)
    return filtered


def filter_container_inspect_env(
    inspect_result: Dict,
    can_view_env: bool
) -> Dict:
    """
    Filter environment variables from Docker inspect result.

    Args:
        inspect_result: Docker inspect API response dict
        can_view_env: True if user has containers.view_env capability

    Returns:
        Inspect result with Config.Env filtered if unauthorized
    """
    if can_view_env:
        return inspect_result

    # Deep copy to avoid mutating the original
    result = copy.deepcopy(inspect_result)
    if isinstance(result, dict) and "Config" in result:
        result["Config"]["Env"] = None
    return result


def filter_ws_container_message(
    message: Dict,
    can_view_env: bool
) -> Dict:
    """
    Filter container data in WebSocket messages for unauthorized users.

    Args:
        message: WebSocket message dict with type and data
        can_view_env: True if user has containers.view_env capability

    Returns:
        Message with container env filtered if unauthorized

    Note:
        Uses deep copy to prevent mutation of shared message data
        across multiple WebSocket connections.
    """
    if can_view_env:
        return message

    # Deep copy required because each connection may receive filtered version
    # while admin connections receive the original with env vars
    filtered_message = copy.deepcopy(message)

    if "data" in filtered_message and "containers" in filtered_message["data"]:
        for c_dict in filtered_message["data"]["containers"]:
            if isinstance(c_dict, dict):
                c_dict.pop("env", None)

    return filtered_message


def filter_stack_env_files(
    env_files: Optional[Dict[str, str]],
    can_view_env: bool,
) -> Dict[str, str]:
    """Return the env-file map only if the caller may view env content.

    Without stacks.view_env, returns an empty map (the compose is still served).
    """
    if not env_files or not can_view_env:
        return {}
    return env_files


def container_to_dict(container: Any) -> Dict:
    """
    Convert container object to dictionary, handling various types.

    Supports:
    - dict (returned as-is with copy)
    - Pydantic models (has .dict() method)
    - Dataclasses with to_dict() method
    - Objects with __dict__

    Args:
        container: Container object of various types

    Returns:
        Dictionary representation of the container
    """
    if isinstance(container, dict):
        return container.copy()
    if hasattr(container, 'dict'):
        # Pydantic model
        return container.dict()
    if hasattr(container, 'to_dict'):
        # Custom to_dict method
        return container.to_dict()
    # Fallback to __dict__
    return container.__dict__.copy()


# ---------------------------------------------------------------------------
# Per-message-type host visibility for scoped WebSocket connections.
#
# A rule returns the set of host ids the message concerns (set() = global,
# deliver to everyone), PRUNE (aggregate payload: prune to visible hosts, then
# deliver) or DROP. A required host key that is missing or null yields DROP,
# never set() - fail-closed. A type with no rule is dropped for scoped
# connections; unrestricted connections are never consulted here.
# ---------------------------------------------------------------------------

PRUNE = object()
DROP = object()

HostRule = Callable[[Dict], Union[Set[str], object]]


def _global(message: Dict) -> Set[str]:
    return set()


def _data(key: str) -> HostRule:
    def rule(message: Dict):
        host_id = (message.get("data") or {}).get(key)
        return DROP if host_id is None else {host_id}
    return rule


def _top(message: Dict):
    host_id = message.get("host_id")
    return {host_id} if host_id else DROP


def _data_host_ids(message: Dict):
    host_ids = (message.get("data") or {}).get("host_ids")
    return DROP if host_ids is None else set(host_ids)


# Event categories that carry no host identity by construction (rule, channel and
# user bookkeeping). A host-less event in any other category is hidden from scoped
# users: it may concern a host whose id the emitter failed to record.
GLOBAL_EVENT_CATEGORIES = frozenset({"system", "alert", "notification", "user"})

# A triggered alert always concerns a scope; host-less, it is the system-scope alert
# (evaluation-engine failures) whose text names the hosts it failed on: admin-only.
ADMIN_ONLY_EVENT_TYPES = frozenset({"rule_triggered"})


def event_scope(host_id: Optional[str], container_id: Optional[str], category: Optional[str],
                event_type: Optional[str] = None) -> Optional[Set[str]]:
    """Hosts an event concerns: a set (empty = global), or None when it must stay hidden.
    Mirrors database.event_visibility_predicate; keep the two in step."""
    if host_id:
        return {host_id}
    # Container alert events are logged with host_id=None and a host_id:short_id container_id
    if container_id and ":" in container_id:
        return {host_of_composite_key(container_id)}
    if not container_id and category in GLOBAL_EVENT_CATEGORIES and event_type not in ADMIN_ONLY_EVENT_TYPES:
        return set()
    return None


def event_is_visible(host_id: Optional[str], container_id: Optional[str], category: Optional[str],
                     visible: Optional[Set[str]], event_type: Optional[str] = None) -> bool:
    if visible is None:
        return True
    hosts = event_scope(host_id, container_id, category, event_type)
    return hosts is not None and hosts <= visible


def alert_is_visible(scope_type: Optional[str], scope_id: Optional[str], host_id: Optional[str],
                     visible: Optional[Set[str]]) -> bool:
    """Python twin of database.alert_visibility_predicate; keep the two in step.
    A host is derived from host_id, a host scope_id or the host_id:short_id prefix of
    a container scope_id. No derivable host = hidden; that includes system-scope alerts,
    whose text names the scopes the evaluation engine failed on (admin-only)."""
    if visible is None:
        return True
    candidates = set()
    if host_id:
        candidates.add(host_id)
    if scope_type == "host" and scope_id:
        candidates.add(scope_id)
    if scope_type == "container" and scope_id and ":" in scope_id:
        candidates.add(host_of_composite_key(scope_id))
    return bool(candidates & visible)


def _event(message: Dict):
    event = message.get("event") or {}
    hosts = event_scope(event.get("host_id"), event.get("container_id"), event.get("category"), event.get("event_type"))
    return DROP if hosts is None else hosts


def _migration_choice(message: Dict):
    data = message.get("data") or {}
    hosts = _data("host_id")(message)
    if hosts is DROP:
        return DROP
    candidates = data.get("candidates") or []
    if any(c.get("host_id") is None for c in candidates):
        return DROP
    return hosts | {c["host_id"] for c in candidates}


WS_HOST_VISIBILITY: Dict[str, Union[HostRule, object]] = {
    "containers_update": PRUNE,
    "host_added": _data("host_id"),
    "host_removed": _data("host_id"),
    "host_status_changed": _data("host_id"),
    # Tags move with the host, so after a migration only the new id can be visible
    "host_migrated": _data("new_host_id"),
    "migration_choice_needed": _migration_choice,
    "container_recreated": _data("host_id"),
    "container_update_progress": _data("host_id"),
    "container_update_layer_progress": _data("host_id"),
    "container_update_warning": _data("host_id"),
    "container_update_complete": _data("host_id"),
    "agent_update_progress": _data("host_id"),
    "auto_restart_success": _data("host_id"),
    "auto_restart_failed": _data("host_id"),
    "container_stats": _top,
    "new_event": _event,
    "batch_job_update": _data_host_ids,
    "batch_item_update": _data("host_id"),
    "blackout_status_changed": _global,
    "deployment_created": _top,
    "deployment_progress": _top,
    "deployment_completed": _top,
    "deployment_failed": _top,
    "deployment_rolled_back": _top,
    "deployment_service_progress": _top,
    "deployment_layer_progress": _data("host_id"),
}


def filter_ws_host_visibility(message: Dict, visible: Optional[Set[str]]) -> Dict:
    """Prune a containers_update-shaped payload to the visible hosts.

    Handles the `containers`/`hosts` lists, the `host_metrics`/`host_sparklines`
    dicts keyed by host id and `container_sparklines` keyed by host_id:short_id.
    Returns a new message; the input is shared across connections and never mutated.
    """
    if visible is None:
        return message
    data = message.get("data") or {}
    pruned = dict(data)
    if "containers" in data:
        pruned["containers"] = [c for c in data["containers"] if c.get("host_id") in visible]
    if "hosts" in data:
        pruned["hosts"] = [h for h in data["hosts"] if h.get("id") in visible]
    for key in ("host_metrics", "host_sparklines"):
        if key in data:
            pruned[key] = {hid: v for hid, v in data[key].items() if hid in visible}
    if "container_sparklines" in data:
        pruned["container_sparklines"] = {
            k: v for k, v in data["container_sparklines"].items() if host_of_composite_key(k) in visible
        }
    return {**message, "data": pruned}


def selector_host_ids(host_selector_json: Optional[str], container_selector_json: Optional[str]) -> Set[str]:
    """Explicit host ids an alert rule's selectors name: host_selector include/host_id
    and the host prefix of host_id:container_name entries in container_selector
    include (the shapes alerts/engine.py evaluates). Tag/name/include_all selectors
    name no host. Unparseable JSON names nothing; the selector validator rejects it."""
    ids: Set[str] = set()
    host_selector = _load_selector(host_selector_json)
    ids.update(_include_entries(host_selector))
    if isinstance(host_selector.get("host_id"), str):
        ids.add(host_selector["host_id"])
    container_selector = _load_selector(container_selector_json)
    ids.update(host_of_composite_key(x) for x in _include_entries(container_selector) if ":" in x)
    return ids


def _include_entries(selector: Dict) -> List[str]:
    """`include` entries; validate_selector_field guarantees a list of strings at the
    door, a bare string still counts as naming itself in case a stored rule predates it."""
    include = selector.get("include")
    if isinstance(include, str):
        return [include]
    if isinstance(include, list):
        return [x for x in include if isinstance(x, str)]
    return []


def _load_selector(selector_json: Optional[str]) -> Dict:
    if not selector_json:
        return {}
    try:
        loaded = json.loads(selector_json)
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}
