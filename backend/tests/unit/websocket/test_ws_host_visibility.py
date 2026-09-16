"""Fail-closed per-message-type host visibility on WebSocket broadcasts.

A scoped connection (visible_host_ids is a set) receives a message only when its
type has an explicit rule in WS_HOST_VISIBILITY and every host the message
concerns is visible. Unrestricted connections (None) keep today's code path.

EMITTED_WS_TYPES is the inventory of every `type` a broadcast emitter produces
at the pinned commit (grep of manager.broadcast(/.broadcast({ across backend/,
plus the dynamic deployment status_to_event tables and the image-pull
event_type). A new emitter must be added here AND classified in both maps.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

import websocket.connection as connection_module
from realtime import RealtimeMonitor
from utils.response_filtering import DROP, PRUNE, WS_HOST_VISIBILITY, filter_ws_host_visibility
from websocket.connection import MESSAGE_CAPABILITY_MAP, ConnectionManager

EMITTED_WS_TYPES = {
    # docker_monitor/monitor.py
    "containers_update", "host_status_changed", "auto_restart_success", "auto_restart_failed",
    # main.py
    "host_added", "host_removed", "host_migrated", "blackout_status_changed",
    # agent/websocket_handler.py
    "migration_choice_needed", "agent_update_progress", "container_stats",
    "container_update_progress", "container_update_layer_progress", "container_update_complete",
    # updates/update_executor.py, updates/event_emitter.py
    "container_recreated", "container_update_warning",
    # event_logger.py
    "new_event",
    # batch_manager.py
    "batch_job_update", "batch_item_update",
    # deployment/executor.py, deployment/agent_executor.py, deployment/routes.py (dynamic)
    "deployment_created", "deployment_progress", "deployment_completed",
    "deployment_failed", "deployment_rolled_back", "deployment_service_progress",
    # utils/image_pull_progress.py via deployment/host_connector.py (dynamic event_type)
    "deployment_layer_progress",
}

# One payload literal per type, copied from its emitter, with the host set the rule must return.
FIXTURES = {
    "host_added": ({"type": "host_added", "data": {"host_id": "h1", "host_name": "Dev"}}, {"h1"}),
    "host_removed": ({"type": "host_removed", "data": {"host_id": "h1"}}, {"h1"}),
    "host_status_changed": ({"type": "host_status_changed", "data": {"host_id": "h1", "status": "online"}}, {"h1"}),
    "host_migrated": ({"type": "host_migrated", "data": {
        "old_host_id": "h1", "old_host_name": "Old", "new_host_id": "h2", "new_host_name": None}}, {"h1", "h2"}),
    "migration_choice_needed": ({"type": "migration_choice_needed", "data": {
        "agent_id": "a1", "host_id": "h9", "host_name": "new",
        "candidates": [{"host_id": "h1", "host_name": "A"}, {"host_id": "h2", "host_name": "B"}]}}, {"h9", "h1", "h2"}),
    "container_recreated": ({"type": "container_recreated", "data": {
        "host_id": "h1", "old_composite_key": "h1:aaa", "new_composite_key": "h1:bbb", "container_name": "web"}}, {"h1"}),
    "container_update_progress": ({"type": "container_update_progress", "data": {
        "host_id": "h1", "container_id": "aaa111111111", "stage": "pulling", "progress": 10, "message": "m"}}, {"h1"}),
    "container_update_layer_progress": ({"type": "container_update_layer_progress", "data": {
        "host_id": "h1", "entity_id": "aaa111111111", "overall_progress": 10, "layers": [], "total_layers": 0,
        "remaining_layers": 0, "summary": "", "speed_mbps": 0}}, {"h1"}),
    "container_update_warning": ({"type": "container_update_warning", "data": {
        "host_id": "h1", "container_id": "aaa111111111", "container_name": "web", "failed_dependents": ["x"],
        "warning": "w"}}, {"h1"}),
    "container_update_complete": ({"type": "container_update_complete", "data": {
        "host_id": "h1", "old_container_id": "aaa111111111", "new_container_id": "bbb222222222",
        "container_name": "web"}}, {"h1"}),
    "agent_update_progress": ({"type": "agent_update_progress", "data": {
        "host_id": "h1", "agent_id": "a1", "stage": "downloading", "message": "m", "error": None}}, {"h1"}),
    "auto_restart_success": ({"type": "auto_restart_success", "data": {
        "host_id": "h1", "container_id": "aaa111111111", "container_name": "web", "host": "Dev"}}, {"h1"}),
    "auto_restart_failed": ({"type": "auto_restart_failed", "data": {
        "host_id": "h1", "container_id": "aaa111111111", "container_name": "web", "attempts": 3, "max_retries": 3}}, {"h1"}),
    "container_stats": ({"type": "container_stats", "container_id": "aaa111111111", "host_id": "h1", "stats": {}}, {"h1"}),
    "new_event": ({"type": "new_event", "event": {
        "id": 1, "correlation_id": None, "category": "container", "event_type": "state_change", "severity": "info",
        "host_id": "h1", "host_name": "Dev", "container_id": "aaa111111111", "container_name": "web",
        "title": "t", "message": "m", "old_state": None, "new_state": None, "triggered_by": None, "details": None}}, {"h1"}),
    "batch_job_update": ({"type": "batch_job_update", "data": {
        "job_id": "j1", "status": "running", "message": None, "total_items": 2, "completed_items": 0,
        "success_items": 0, "error_items": 0, "skipped_items": 0, "created_at": None, "started_at": None,
        "completed_at": None, "host_ids": ["h1", "h2"]}}, {"h1", "h2"}),
    "batch_item_update": ({"type": "batch_item_update", "data": {
        "job_id": "j1", "item_id": 7, "host_id": "h1", "status": "running", "message": None}}, {"h1"}),
    "blackout_status_changed": ({"type": "blackout_status_changed", "data": {"is_blackout": True, "window_name": "night"}}, set()),
    "deployment_created": ({"type": "deployment_created", "deployment_id": "h1:abc", "host_id": "h1", "name": "s",
                            "status": "planning", "progress": {"overall_percent": 0, "stage": ""},
                            "created_at": None, "completed_at": None}, {"h1"}),
    "deployment_progress": ({"type": "deployment_progress", "deployment_id": "h1:s:x", "host_id": "h1", "name": "s",
                             "status": "creating", "progress": {"overall_percent": 50, "stage": "m"}}, {"h1"}),
    "deployment_completed": ({"type": "deployment_completed", "deployment_id": "h1:s:x", "host_id": "h1", "name": "s",
                              "status": "running", "progress": {"overall_percent": 100, "stage": "done"}}, {"h1"}),
    "deployment_failed": ({"type": "deployment_failed", "deployment_id": "h1:s:x", "host_id": "h1", "name": "s",
                           "status": "failed", "progress": {"overall_percent": 0, "stage": "m"}, "error": "e"}, {"h1"}),
    "deployment_rolled_back": ({"type": "deployment_rolled_back", "deployment_id": "h1:abc", "host_id": "h1",
                                "name": "s", "status": "rolled_back", "progress": {"overall_percent": 0, "stage": ""},
                                "created_at": None, "completed_at": None}, {"h1"}),
    "deployment_service_progress": ({"type": "deployment_service_progress", "deployment_id": "h1:abc", "host_id": "h1",
                                     "services": [{"name": "web", "status": "running"}]}, {"h1"}),
    "deployment_layer_progress": ({"type": "deployment_layer_progress", "data": {
        "host_id": "h1", "entity_id": "h1:s", "overall_progress": 10, "layers": [], "total_layers": 1,
        "remaining_layers": 1, "summary": "", "speed_mbps": 0.0, "updated": 0}}, {"h1"}),
}

CONTAINERS_UPDATE = {
    "type": "containers_update",
    "data": {
        "timestamp": "2026-09-16T00:00:00Z",
        "containers": [
            {"id": "aaa111111111", "short_id": "aaa111111111", "host_id": "h1", "env": ["SECRET=1"]},
            {"id": "ccc333333333", "short_id": "ccc333333333", "host_id": "h2", "env": ["SECRET=2"]},
        ],
        "hosts": [{"id": "h1", "name": "Dev"}, {"id": "h2", "name": "Test"}],
        "host_metrics": {"h1": {"cpu_percent": 1}, "h2": {"cpu_percent": 2}},
        "host_sparklines": {"h1": {"cpu": [1]}, "h2": {"cpu": [2]}},
        "container_sparklines": {"h1:aaa111111111": {"cpu": [1]}, "h2:ccc333333333": {"cpu": [2]}},
    },
}


class TestRuleMapParity:
    def test_rule_map_covers_exactly_the_emitted_types(self):
        assert set(WS_HOST_VISIBILITY) == EMITTED_WS_TYPES

    def test_capability_map_covers_exactly_the_emitted_types(self):
        assert set(MESSAGE_CAPABILITY_MAP) == EMITTED_WS_TYPES

    def test_every_non_prune_type_has_a_fixture(self):
        assert set(FIXTURES) | {"containers_update"} == EMITTED_WS_TYPES


class TestPerTypeRules:
    @pytest.mark.parametrize("msg_type", sorted(FIXTURES))
    def test_rule_returns_the_hosts_the_message_concerns(self, msg_type):
        payload, expected = FIXTURES[msg_type]
        rule = WS_HOST_VISIBILITY[msg_type]
        assert rule is not PRUNE
        assert rule(payload) == expected

    @pytest.mark.parametrize("msg_type", sorted(t for t, (_, exp) in FIXTURES.items() if exp))
    def test_missing_host_key_drops_never_delivers_as_global(self, msg_type):
        payload, _ = FIXTURES[msg_type]
        stripped = json.loads(json.dumps(payload))
        for container in (stripped, stripped.get("data") or {}, stripped.get("event") or {}):
            for key in ("host_id", "old_host_id", "new_host_id", "host_ids", "container_id", "candidates"):
                container.pop(key, None)
        assert WS_HOST_VISIBILITY[msg_type](stripped) is DROP

    def test_new_event_with_null_host_resolves_from_composite_container_id(self):
        payload = {"type": "new_event", "event": {"category": "container", "host_id": None,
                                                  "container_id": "h7:aaa111111111"}}
        assert WS_HOST_VISIBILITY["new_event"](payload) == {"h7"}

    def test_new_event_system_category_without_host_is_global(self):
        payload = {"type": "new_event", "event": {"category": "system", "host_id": None, "container_id": None}}
        assert WS_HOST_VISIBILITY["new_event"](payload) == set()

    def test_new_event_without_host_or_composite_is_dropped(self):
        payload = {"type": "new_event", "event": {"category": "container", "host_id": None, "container_id": "aaa111111111"}}
        assert WS_HOST_VISIBILITY["new_event"](payload) is DROP

    def test_containers_update_is_pruned(self):
        assert WS_HOST_VISIBILITY["containers_update"] is PRUNE
        pruned = filter_ws_host_visibility(CONTAINERS_UPDATE, {"h1"})
        data = pruned["data"]
        assert [c["host_id"] for c in data["containers"]] == ["h1"]
        assert [h["id"] for h in data["hosts"]] == ["h1"]
        assert set(data["host_metrics"]) == {"h1"}
        assert set(data["host_sparklines"]) == {"h1"}
        assert set(data["container_sparklines"]) == {"h1:aaa111111111"}
        assert data["timestamp"] == "2026-09-16T00:00:00Z"
        assert [c["host_id"] for c in CONTAINERS_UPDATE["data"]["containers"]] == ["h1", "h2"], "input must not be mutated"


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def accept(self):
        pass

    async def send_text(self, text):
        self.sent.append(json.loads(text))


ALL_CAPS = {"containers.view", "hosts.view", "events.view", "batch.view", "stacks.view", "containers.view_env"}


async def _manager_with(*connections):
    manager = ConnectionManager()
    for ws, user_id, caps, visible in connections:
        await manager.connect(ws, user_id=user_id, capabilities=caps, visible_host_ids=visible)
    return manager


class TestBroadcastFailClosed:
    async def test_unmapped_type_dropped_for_scoped_delivered_to_unrestricted(self):
        scoped, admin = FakeWebSocket(), FakeWebSocket()
        manager = await _manager_with((scoped, 1, ALL_CAPS, {"h1"}), (admin, 2, ALL_CAPS, None))
        await manager.broadcast({"type": "brand_new_type", "data": {"host_id": "h1"}})
        assert scoped.sent == []
        assert admin.sent == [{"type": "brand_new_type", "data": {"host_id": "h1"}}]

    async def test_message_for_hidden_host_not_delivered(self):
        scoped = FakeWebSocket()
        manager = await _manager_with((scoped, 1, ALL_CAPS, {"h1"}))
        await manager.broadcast({"type": "host_status_changed", "data": {"host_id": "h2", "status": "online"}})
        await manager.broadcast({"type": "host_status_changed", "data": {"host_id": "h1", "status": "online"}})
        assert [m["data"]["host_id"] for m in scoped.sent] == ["h1"]

    async def test_message_naming_several_hosts_needs_all_visible(self):
        scoped = FakeWebSocket()
        manager = await _manager_with((scoped, 1, ALL_CAPS, {"h1"}))
        await manager.broadcast(FIXTURES["batch_job_update"][0])
        assert scoped.sent == []

    async def test_mapped_type_without_host_key_is_dropped(self):
        scoped, admin = FakeWebSocket(), FakeWebSocket()
        manager = await _manager_with((scoped, 1, ALL_CAPS, {"h1"}), (admin, 2, ALL_CAPS, None))
        await manager.broadcast({"type": "host_added", "data": {"host_name": "no id"}})
        assert scoped.sent == []
        assert len(admin.sent) == 1

    async def test_global_type_reaches_scoped_connections(self):
        scoped = FakeWebSocket()
        manager = await _manager_with((scoped, 1, ALL_CAPS, set()))
        await manager.broadcast(FIXTURES["blackout_status_changed"][0])
        assert len(scoped.sent) == 1

    async def test_capability_gate_still_applies_to_scoped_connections(self):
        scoped = FakeWebSocket()
        manager = await _manager_with((scoped, 1, {"containers.view"}, {"h1"}))
        await manager.broadcast({"type": "host_status_changed", "data": {"host_id": "h1", "status": "online"}})
        assert scoped.sent == []

    async def test_containers_update_pruned_for_scoped(self):
        scoped = FakeWebSocket()
        manager = await _manager_with((scoped, 1, ALL_CAPS, {"h2"}))
        await manager.broadcast(CONTAINERS_UPDATE, filter_containers=True)
        data = scoped.sent[0]["data"]
        assert [c["host_id"] for c in data["containers"]] == ["h2"]
        assert set(data["host_metrics"]) == {"h2"}

    async def test_env_filter_composes_with_host_prune(self):
        scoped = FakeWebSocket()
        manager = await _manager_with((scoped, 1, ALL_CAPS - {"containers.view_env"}, {"h2"}))
        with patch.object(connection_module, "has_capability_for_user", return_value=False):
            await manager.broadcast(CONTAINERS_UPDATE, filter_containers=True)
        containers = scoped.sent[0]["data"]["containers"]
        assert [c["host_id"] for c in containers] == ["h2"]
        assert all("env" not in c for c in containers)

    async def test_unrestricted_payload_is_byte_identical_to_input(self):
        admin = FakeWebSocket()
        manager = await _manager_with((admin, 1, ALL_CAPS, None))
        with patch.object(connection_module, "has_capability_for_user", return_value=True):
            await manager.broadcast(CONTAINERS_UPDATE, filter_containers=True)
        assert admin.sent == [CONTAINERS_UPDATE]


class TestVisibilityRefresh:
    async def test_refresh_recomputes_per_user_and_bumps_generation(self):
        ws_a, ws_b = FakeWebSocket(), FakeWebSocket()
        manager = await _manager_with((ws_a, 1, ALL_CAPS, {"h1"}), (ws_b, 2, ALL_CAPS, None))
        gen = manager.visibility_generation
        with patch.object(connection_module, "get_user_group_ids", side_effect=lambda uid: [uid]), \
             patch.object(connection_module, "get_visible_host_ids_for_groups",
                          side_effect=lambda gids: {"h2"} if gids == [1] else None):
            await manager.refresh_visible_hosts_for_user(1)
        assert manager.visibility_generation == gen + 1
        assert manager.get_visible_hosts(ws_a) == {"h2"}
        assert manager.get_visible_hosts(ws_b) is None

    async def test_refresh_all_revokes_hidden_subscriptions(self):
        ws = FakeWebSocket()
        manager = await _manager_with((ws, 1, ALL_CAPS, {"h1", "h2"}))
        realtime = RealtimeMonitor()
        realtime.connection_manager = manager
        manager.realtime = realtime
        await realtime.subscribe_to_stats(ws, "aaa111111111", "h1")
        await realtime.subscribe_to_stats(ws, "ccc333333333", "h2")
        with patch.object(connection_module, "get_user_group_ids", return_value=[1]), \
             patch.object(connection_module, "get_visible_host_ids_for_groups", return_value={"h1"}):
            await manager.refresh_all_visible_hosts()
        assert set(realtime.stats_subscribers) == {"aaa111111111"}

    async def test_disconnect_forgets_visible_set(self):
        ws = FakeWebSocket()
        manager = await _manager_with((ws, 1, ALL_CAPS, {"h1"}))
        await manager.disconnect(ws)
        assert ws not in manager._connection_visible_hosts


class TestRealtimeRevocation:
    async def test_revoke_only_hidden_hosts_for_that_socket(self):
        ws1, ws2 = FakeWebSocket(), FakeWebSocket()
        realtime = RealtimeMonitor()
        await realtime.subscribe_to_stats(ws1, "aaa111111111", "h1")
        await realtime.subscribe_to_stats(ws1, "ccc333333333", "h2")
        await realtime.subscribe_to_stats(ws2, "ccc333333333", "h2")
        await realtime.revoke_hidden_subscriptions(ws1, {"h1"})
        assert realtime.stats_subscribers["aaa111111111"] == {ws1}
        assert realtime.stats_subscribers["ccc333333333"] == {ws2}

    async def test_unrestricted_revokes_nothing(self):
        ws = FakeWebSocket()
        realtime = RealtimeMonitor()
        await realtime.subscribe_to_stats(ws, "aaa111111111", "h1")
        await realtime.revoke_hidden_subscriptions(ws, None)
        assert set(realtime.stats_subscribers) == {"aaa111111111"}
