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
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import websocket.connection as connection_module
from realtime import ContainerStats, RealtimeMonitor
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
        "old_host_id": "h1", "old_host_name": "Old", "new_host_id": "h2", "new_host_name": None}}, {"h2"}),
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

    @pytest.mark.parametrize("category", ["system", "alert", "notification", "user"])
    def test_new_event_hostless_admin_categories_are_global(self, category):
        """Rule/channel/user bookkeeping reveals nothing about hidden hosts."""
        payload = {"type": "new_event", "event": {"category": category, "host_id": None, "container_id": None}}
        assert WS_HOST_VISIBILITY["new_event"](payload) == set()

    @pytest.mark.parametrize("category", ["container", "host", "health_check"])
    def test_new_event_hostless_host_categories_are_dropped(self, category):
        payload = {"type": "new_event", "event": {"category": category, "host_id": None, "container_id": None}}
        assert WS_HOST_VISIBILITY["new_event"](payload) is DROP

    def test_new_event_hostless_triggered_alert_is_admin_only(self):
        """A host-less rule_triggered event is a system alert firing: its text names the
        scopes the evaluation engine failed on, so it never reaches scoped users."""
        payload = {"type": "new_event", "event": {"category": "alert", "event_type": "rule_triggered",
                                                  "host_id": None, "container_id": None}}
        assert WS_HOST_VISIBILITY["new_event"](payload) is DROP

    def test_new_event_admin_category_naming_a_container_is_not_global(self):
        payload = {"type": "new_event", "event": {"category": "alert", "host_id": None, "container_id": "aaa111111111"}}
        assert WS_HOST_VISIBILITY["new_event"](payload) is DROP

    def test_new_event_empty_strings_count_as_absent(self):
        composite = {"type": "new_event", "event": {"category": "container", "host_id": "", "container_id": "h7:aaa111111111"}}
        assert WS_HOST_VISIBILITY["new_event"](composite) == {"h7"}
        bookkeeping = {"type": "new_event", "event": {"category": "notification", "event_type": "sent", "host_id": "", "container_id": ""}}
        assert WS_HOST_VISIBILITY["new_event"](bookkeeping) == set()

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
        self.closed = None

    async def accept(self):
        pass

    async def send_text(self, text):
        self.sent.append(json.loads(text))

    async def close(self, code=1000, reason=""):
        self.closed = (code, reason)


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
        with patch.object(connection_module, "get_visible_host_ids_for_user",
                          side_effect=lambda uid: {"h2"} if uid == 1 else None):
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
        with patch.object(connection_module, "get_visible_host_ids_for_user", return_value={"h1"}):
            await manager.refresh_all_visible_hosts()
        assert set(realtime.stats_subscribers) == {"h1:aaa111111111"}

    async def test_disconnect_forgets_visible_set(self):
        ws = FakeWebSocket()
        manager = await _manager_with((ws, 1, ALL_CAPS, {"h1"}))
        await manager.disconnect(ws)
        assert ws not in manager._connection_visible_hosts

    async def test_unknown_socket_sees_nothing_not_everything(self):
        manager = ConnectionManager()
        assert manager.get_visible_hosts(FakeWebSocket()) == set()

    async def test_rule_exception_drops_message_but_keeps_connection(self):
        scoped = FakeWebSocket()
        manager = await _manager_with((scoped, 1, ALL_CAPS, {"h1"}))
        with patch.dict(WS_HOST_VISIBILITY, {"host_added": lambda m: 1 / 0}):
            await manager.broadcast({"type": "host_added", "data": {"host_id": "h1"}})
        assert scoped.sent == []
        assert scoped in manager.active_connections
        assert manager.get_visible_hosts(scoped) == {"h1"}


class TestRealtimeRevocation:
    async def test_revoke_only_hidden_hosts_for_that_socket(self):
        ws1, ws2 = FakeWebSocket(), FakeWebSocket()
        realtime = RealtimeMonitor()
        await realtime.subscribe_to_stats(ws1, "aaa111111111", "h1")
        await realtime.subscribe_to_stats(ws1, "ccc333333333", "h2")
        await realtime.subscribe_to_stats(ws2, "ccc333333333", "h2")
        await realtime.revoke_hidden_subscriptions(ws1, {"h1"})
        assert realtime.stats_subscribers["h1:aaa111111111"] == {ws1}
        assert realtime.stats_subscribers["h2:ccc333333333"] == {ws2}

    async def test_unrestricted_revokes_nothing(self):
        ws = FakeWebSocket()
        realtime = RealtimeMonitor()
        await realtime.subscribe_to_stats(ws, "aaa111111111", "h1")
        await realtime.revoke_hidden_subscriptions(ws, None)
        assert set(realtime.stats_subscribers) == {"h1:aaa111111111"}

    async def test_same_short_id_on_two_hosts_never_shares_a_stream(self):
        """Cloned VMs can carry identical container short ids; a user scoped to h2
        must not be attached to h1's stream (and vice versa)."""
        ws1, ws2 = FakeWebSocket(), FakeWebSocket()
        realtime = RealtimeMonitor()
        await realtime.subscribe_to_stats(ws1, "aaa111111111", "h1")
        await realtime.subscribe_to_stats(ws2, "aaa111111111", "h2")
        assert realtime.stats_subscribers == {"h1:aaa111111111": {ws1}, "h2:aaa111111111": {ws2}}
        await realtime.revoke_hidden_subscriptions(ws2, {"h2"})
        assert realtime.stats_subscribers == {"h1:aaa111111111": {ws1}, "h2:aaa111111111": {ws2}}
        await realtime.unsubscribe_from_stats(ws1, "aaa111111111")
        assert realtime.stats_subscribers == {"h2:aaa111111111": {ws2}}


class TestBroadcastResilience:
    async def test_transform_failure_skips_only_that_connection(self):
        broken, healthy = FakeWebSocket(), FakeWebSocket()
        manager = await _manager_with((broken, 1, ALL_CAPS, None), (healthy, 2, ALL_CAPS, None))

        def explode(message, user_id):
            if user_id == 1:
                raise RuntimeError("cache down")
            return message

        with patch.object(manager, "_filter_container_message", side_effect=explode):
            await manager.broadcast(CONTAINERS_UPDATE, filter_containers=True)
        assert broken.sent == []
        assert healthy.sent == [CONTAINERS_UPDATE]
        assert broken in manager.active_connections


class TestLegacyStatsStream:
    async def test_container_stats_payload_names_its_host(self):
        ws = FakeWebSocket()
        ws.send_text = AsyncMock(side_effect=[None, RuntimeError("closed")])
        realtime = RealtimeMonitor()
        await realtime.subscribe_to_stats(ws, "aaa111111111", "h1")
        client = MagicMock()
        client.containers.get.return_value = MagicMock(status="running")
        stats = ContainerStats("aaa111111111", 1.0, 1.0, 1.0, 1.0, 0, 0, 0, 0, 1, "t")
        with patch.object(realtime, "_calculate_container_stats_async", AsyncMock(return_value=stats)):
            await realtime._monitor_container_stats(client, "aaa111111111", "h1", interval=0)
        first = json.loads(ws.send_text.await_args_list[0].args[0])
        assert first["type"] == "container_stats"
        assert first["host_id"] == "h1"
        assert first["data"]["container_id"] == "aaa111111111"


class TestShellSockets:
    """Interactive shells never receive broadcasts, but a user delete or a scope
    change must be able to close them like any other socket of that user."""

    async def test_user_delete_closes_ws_and_shell_sockets(self):
        ws, shell, other = FakeWebSocket(), FakeWebSocket(), FakeWebSocket()
        manager = await _manager_with((ws, 1, ALL_CAPS, None))
        await manager.register_shell(shell, 1, "h1")
        await manager.register_shell(other, 2, "h1")
        await manager.disconnect_user(1)
        assert ws.closed[0] == 4401 and shell.closed[0] == 4401
        assert other.closed is None
        assert ws not in manager.active_connections
        assert shell not in manager._shell_sockets and other in manager._shell_sockets

    async def test_scope_narrowing_closes_shells_on_hidden_hosts_only(self):
        visible_shell, hidden_shell = FakeWebSocket(), FakeWebSocket()
        manager = ConnectionManager()
        await manager.register_shell(visible_shell, 1, "h1")
        await manager.register_shell(hidden_shell, 1, "h2")
        with patch.object(connection_module, "get_visible_host_ids_for_user", return_value={"h1"}):
            await manager.refresh_visible_hosts_for_user(1)
        assert hidden_shell.closed == (4404, "Not found")
        assert visible_shell.closed is None
        assert hidden_shell not in manager._shell_sockets

    async def test_unrestricted_refresh_leaves_shells_open(self):
        shell = FakeWebSocket()
        manager = ConnectionManager()
        await manager.register_shell(shell, 1, "h2")
        with patch.object(connection_module, "get_visible_host_ids_for_user", return_value=None):
            await manager.refresh_all_visible_hosts()
        assert shell.closed is None

    async def test_losing_shell_capability_closes_the_shell(self):
        shell, keeper = FakeWebSocket(), FakeWebSocket()
        manager = ConnectionManager()
        await manager.register_shell(shell, 1, "h1")
        await manager.register_shell(keeper, 2, "h1")
        caps = {1: set(), 2: {"containers.shell"}}
        with patch.object(connection_module, "get_capabilities_for_user", side_effect=lambda uid: caps[uid]):
            await manager.refresh_all_capabilities()
        assert shell.closed == (4403, "Shell access revoked")
        assert keeper.closed is None
        with patch.object(connection_module, "get_capabilities_for_user", return_value=set()):
            await manager.refresh_capabilities_for_user(2)
        assert keeper.closed == (4403, "Shell access revoked")

    async def test_revocations_bump_the_generation_so_a_registering_shell_rechecks(self):
        manager = ConnectionManager()
        before = manager.visibility_generation
        await manager.disconnect_user(1)
        with patch.object(connection_module, "get_capabilities_for_user", return_value=set()):
            await manager.refresh_capabilities_for_user(1)
            await manager.refresh_all_capabilities()
        assert manager.visibility_generation == before + 3
