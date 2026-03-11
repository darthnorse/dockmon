#!/usr/bin/env python3
"""
DockMon Capability Matrix E2E Test

Tests every protected endpoint against the group-based capability authorization
system on the feature/multi-user-support branch. Creates test users with specific
permissions and verifies that:

1. A user with ZERO permissions gets 403 on every protected endpoint
2. A user with the CORRECT capability gets non-403 (auth gate passes)

Usage:
    python scripts/test_capabilities.py \
        --url https://localhost:8001 \
        --username admin \
        --password <password> \
        --insecure
"""

import argparse
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass

import httpx

TEST_CONTAINER_NAME = "captest-nginx"
TEST_PASSWORD = "TestPass123!"

# ---------------------------------------------------------------------------
# ANSI colors
# ---------------------------------------------------------------------------
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"


def ok(msg: str = "") -> str:
    return f"{GREEN}OK{RESET} {msg}"


def fail(msg: str = "") -> str:
    return f"{RED}FAILED{RESET} {msg}"


# ---------------------------------------------------------------------------
# Endpoint definition
# ---------------------------------------------------------------------------
@dataclass
class Endpoint:
    method: str
    path: str
    capability: str
    body: dict | None = None
    skip: bool = False
    skip_reason: str = ""


# ---------------------------------------------------------------------------
# Endpoint matrix - every protected endpoint from the feature branch
# ---------------------------------------------------------------------------
def build_endpoint_matrix(host_id: str, container_id: str) -> list[Endpoint]:
    """Build the full endpoint matrix with path parameters substituted."""

    # Placeholder IDs for entities that won't exist - we just need non-403
    fake_id = "999999"
    fake_uuid = "00000000-0000-0000-0000-000000000000"
    fake_container = "aabbccddeeff"

    endpoints = [
        # ---- hosts.view ----
        Endpoint("GET", "/api/hosts", "hosts.view"),
        Endpoint("GET", f"/api/hosts/{host_id}/metrics", "hosts.view"),
        Endpoint("GET", "/api/dashboard/hosts", "hosts.view"),

        # ---- hosts.manage ----
        Endpoint("POST", "/api/hosts", "hosts.manage",
                 body={"name": "_test_cap_host", "hostname": "127.0.0.1", "connection_type": "local"}),
        Endpoint("POST", "/api/hosts/test-connection", "hosts.manage",
                 body={"hostname": "127.0.0.1", "connection_type": "local"}),
        Endpoint("PUT", f"/api/hosts/{fake_uuid}", "hosts.manage",
                 body={"name": "x", "hostname": "127.0.0.1"}),
        Endpoint("DELETE", f"/api/hosts/{fake_uuid}", "hosts.manage",
                 skip=True, skip_reason="Would delete a real host"),

        # ---- containers.view ----
        Endpoint("GET", "/api/containers", "containers.view"),
        Endpoint("GET", f"/api/hosts/{host_id}/containers/{container_id}/inspect", "containers.view"),
        Endpoint("GET", f"/api/hosts/{host_id}/containers/{container_id}/update-status", "containers.view"),
        Endpoint("GET", "/api/updates/image-cache", "containers.view"),
        Endpoint("GET", "/api/updates/summary", "containers.view"),
        Endpoint("GET", "/api/auto-update-configs", "containers.view"),
        Endpoint("GET", "/api/deployment-metadata", "containers.view"),
        Endpoint("GET", f"/api/hosts/{host_id}/images", "containers.view"),
        Endpoint("GET", f"/api/hosts/{host_id}/networks", "containers.view"),
        Endpoint("GET", f"/api/hosts/{host_id}/volumes", "containers.view"),
        Endpoint("GET", "/api/dashboard/summary", "containers.view"),

        # ---- containers.operate ----
        Endpoint("POST", f"/api/hosts/{host_id}/containers/{container_id}/restart", "containers.operate"),
        Endpoint("POST", f"/api/hosts/{host_id}/containers/{container_id}/stop", "containers.operate"),
        Endpoint("POST", f"/api/hosts/{host_id}/containers/{container_id}/start", "containers.operate"),
        Endpoint("POST", f"/api/hosts/{host_id}/containers/{container_id}/kill", "containers.operate"),
        Endpoint("POST", f"/api/hosts/{host_id}/containers/{container_id}/rename", "containers.operate",
                 body={"name": f"{TEST_CONTAINER_NAME}-renamed"}),
        Endpoint("DELETE", f"/api/hosts/{host_id}/containers/{fake_container}", "containers.operate"),
        Endpoint("POST", f"/api/hosts/{host_id}/containers/{container_id}/auto-restart", "containers.operate",
                 body={"enabled": False}),
        Endpoint("POST", f"/api/hosts/{host_id}/containers/{container_id}/desired-state", "containers.operate",
                 body={"desired_state": "running"}),
        Endpoint("POST", f"/api/hosts/{host_id}/images/prune", "containers.operate"),
        Endpoint("DELETE", f"/api/hosts/{host_id}/networks/{fake_id}", "containers.operate"),
        Endpoint("POST", f"/api/hosts/{host_id}/networks/prune", "containers.operate"),
        Endpoint("DELETE", f"/api/hosts/{host_id}/volumes/fake_vol", "containers.operate"),
        Endpoint("POST", f"/api/hosts/{host_id}/volumes/prune", "containers.operate"),
        Endpoint("POST", "/api/images/prune", "containers.operate"),

        # ---- containers.logs ----
        Endpoint("GET", f"/api/hosts/{host_id}/containers/{container_id}/logs", "containers.logs"),

        # ---- containers.update ----
        Endpoint("DELETE", f"/api/updates/image-cache/fake:latest", "containers.update"),
        Endpoint("POST", f"/api/hosts/{host_id}/containers/{container_id}/check-update", "containers.update"),
        Endpoint("POST", f"/api/hosts/{host_id}/containers/{container_id}/execute-update", "containers.update"),
        Endpoint("PUT", f"/api/hosts/{host_id}/containers/{container_id}/auto-update-config", "containers.update",
                 body={"auto_update": False}),
        Endpoint("POST", "/api/updates/check-all", "containers.update"),

        # ---- tags.view ----
        Endpoint("GET", "/api/tags/suggest", "tags.view"),
        Endpoint("GET", "/api/hosts/tags/suggest", "tags.view"),

        # ---- tags.manage ----
        Endpoint("PATCH", f"/api/hosts/{host_id}/containers/{container_id}/tags", "tags.manage",
                 body={"tags": []}),
        Endpoint("PATCH", f"/api/hosts/{host_id}/tags", "tags.manage",
                 body={"tags": []}),

        # ---- stacks.view ----
        Endpoint("GET", "/api/stacks", "stacks.view"),
        Endpoint("GET", "/api/stacks/_test_nonexistent", "stacks.view"),
        Endpoint("GET", "/api/deployments", "stacks.view"),
        Endpoint("GET", "/api/deployments/known-stacks", "stacks.view"),
        Endpoint("GET", "/api/deployments/running-projects", "stacks.view"),
        Endpoint("GET", f"/api/deployments/{fake_id}", "stacks.view"),
        Endpoint("GET", f"/api/deployments/{fake_id}/compose-preview", "stacks.view"),
        Endpoint("POST", f"/api/deployments/scan-compose-dirs/{host_id}", "stacks.view"),

        # ---- stacks.edit ----
        Endpoint("POST", "/api/stacks", "stacks.edit",
                 body={"name": "_test_cap_stack", "content": "version: '3'\nservices:\n  test:\n    image: alpine"}),
        Endpoint("PUT", "/api/stacks/_test_cap_stack", "stacks.edit",
                 body={"content": "version: '3'\nservices:\n  test:\n    image: alpine"}),
        Endpoint("PUT", "/api/stacks/_test_cap_stack/rename", "stacks.edit",
                 body={"name": "_test_cap_stack_renamed"}),
        Endpoint("POST", "/api/stacks/_test_nonexistent/copy", "stacks.edit",
                 body={"name": "_test_cap_stack_copy"}),
        Endpoint("DELETE", "/api/stacks/_test_cap_stack", "stacks.edit"),
        Endpoint("POST", "/api/deployments/generate-from-containers", "stacks.edit",
                 body={"host_id": host_id, "container_ids": [container_id]}),

        # ---- stacks.deploy ----
        Endpoint("POST", "/api/deployments/deploy", "stacks.deploy",
                 body={"host_id": host_id, "compose_content": "version: '3'", "project_name": "_test_cap"}),
        Endpoint("POST", "/api/deployments", "stacks.deploy",
                 body={"host_id": host_id, "name": "_test_cap_deploy",
                       "compose_content": "version: '3'\nservices:\n  test:\n    image: alpine"}),
        Endpoint("POST", f"/api/deployments/{fake_id}/execute", "stacks.deploy"),
        Endpoint("PUT", f"/api/deployments/{fake_id}", "stacks.deploy",
                 body={"compose_content": "version: '3'"}),
        Endpoint("DELETE", f"/api/deployments/{fake_id}", "stacks.deploy"),
        Endpoint("POST", "/api/deployments/import", "stacks.deploy",
                 body={"host_id": host_id, "project_name": "_test_cap_import",
                       "compose_content": "version: '3'\nservices:\n  test:\n    image: alpine"}),

        # ---- stacks.view_env ----
        Endpoint("POST", f"/api/deployments/read-compose-file/{host_id}", "stacks.view_env",
                 body={"path": "/tmp/nonexistent.yml"}),

        # ---- healthchecks.view ----
        Endpoint("GET", f"/api/containers/{host_id}/{container_id}/http-health-check", "healthchecks.view"),
        Endpoint("GET", "/api/health-check-configs", "healthchecks.view"),

        # ---- healthchecks.manage ----
        Endpoint("PUT", f"/api/containers/{host_id}/{container_id}/http-health-check", "healthchecks.manage",
                 body={"url": "http://localhost", "interval_seconds": 60}),
        Endpoint("DELETE", f"/api/containers/{host_id}/{fake_container}/http-health-check", "healthchecks.manage"),

        # ---- healthchecks.test ----
        Endpoint("POST", f"/api/containers/{host_id}/{container_id}/http-health-check/test", "healthchecks.test"),

        # ---- alerts.view ----
        Endpoint("GET", "/api/alerts/rules", "alerts.view"),
        Endpoint("GET", "/api/blackout/status", "alerts.view"),
        Endpoint("GET", "/api/alerts/", "alerts.view"),
        Endpoint("GET", f"/api/alerts/{fake_id}", "alerts.view"),
        Endpoint("GET", f"/api/alerts/{fake_id}/annotations", "alerts.view"),
        Endpoint("GET", "/api/alerts/stats/", "alerts.view"),

        # ---- alerts.manage ----
        Endpoint("POST", "/api/alerts/rules", "alerts.manage",
                 body={"name": "_test_cap_rule", "type": "container_down", "severity": "warning",
                       "conditions": {}, "notification_channel_ids": []}),
        Endpoint("PUT", f"/api/alerts/rules/{fake_id}", "alerts.manage",
                 body={"name": "_test_cap_rule", "type": "container_down", "severity": "warning",
                       "conditions": {}, "notification_channel_ids": []}),
        Endpoint("DELETE", f"/api/alerts/rules/{fake_id}", "alerts.manage"),
        Endpoint("PATCH", f"/api/alerts/rules/{fake_id}/toggle", "alerts.manage"),
        Endpoint("POST", f"/api/alerts/{fake_id}/resolve", "alerts.manage"),
        Endpoint("POST", f"/api/alerts/{fake_id}/snooze", "alerts.manage",
                 body={"duration_minutes": 60}),
        Endpoint("POST", f"/api/alerts/{fake_id}/unsnooze", "alerts.manage"),
        Endpoint("POST", f"/api/alerts/{fake_id}/annotations", "alerts.manage",
                 body={"text": "test"}),

        # ---- notifications.view ----
        Endpoint("GET", "/api/notifications/channels", "notifications.view"),
        Endpoint("GET", "/api/notifications/template-variables", "notifications.view"),
        Endpoint("GET", f"/api/notifications/channels/{fake_id}/dependent-alerts", "notifications.view"),

        # ---- notifications.manage ----
        Endpoint("POST", "/api/notifications/channels", "notifications.manage",
                 body={"name": "_test_cap_channel", "type": "webhook",
                       "config": {"url": "http://localhost/hook"}}),
        Endpoint("PUT", f"/api/notifications/channels/{fake_id}", "notifications.manage",
                 body={"name": "_test_cap_channel", "type": "webhook",
                       "config": {"url": "http://localhost/hook"}}),
        Endpoint("DELETE", f"/api/notifications/channels/{fake_id}", "notifications.manage"),
        Endpoint("POST", f"/api/notifications/channels/{fake_id}/test", "notifications.manage"),

        # ---- events.view ----
        Endpoint("GET", "/api/events", "events.view"),
        Endpoint("GET", f"/api/events/{fake_id}", "events.view"),
        Endpoint("GET", f"/api/events/correlation/{fake_uuid}", "events.view"),
        Endpoint("GET", "/api/events/statistics", "events.view"),
        Endpoint("GET", f"/api/hosts/{host_id}/events/container/{container_id}", "events.view"),
        Endpoint("GET", f"/api/events/host/{host_id}", "events.view"),

        # ---- policies.view ----
        Endpoint("GET", "/api/update-policies", "policies.view"),

        # ---- policies.manage ----
        Endpoint("PUT", "/api/update-policies/semver/toggle", "policies.manage",
                 body={"enabled": True}),
        Endpoint("POST", "/api/update-policies/custom", "policies.manage",
                 body={"name": "_test_cap_policy", "pattern": "test:*", "action": "update"}),
        Endpoint("PUT", f"/api/update-policies/{fake_id}/action", "policies.manage",
                 body={"action": "update"}),
        Endpoint("DELETE", f"/api/update-policies/custom/{fake_id}", "policies.manage"),
        Endpoint("PUT", f"/api/hosts/{host_id}/containers/{container_id}/update-policy", "policies.manage",
                 body={"policy": "default"}),

        # ---- batch.create ----
        Endpoint("POST", "/api/batch", "batch.create",
                 body={"action": "restart", "containers": [
                     {"host_id": host_id, "container_id": fake_container}]}),
        Endpoint("POST", "/api/batch/validate-update", "batch.create",
                 body={"containers": [
                     {"host_id": host_id, "container_id": fake_container}]}),

        # ---- batch.view ----
        Endpoint("GET", f"/api/batch/{fake_uuid}", "batch.view"),

        # ---- settings.manage ----
        Endpoint("GET", "/api/rate-limit/stats", "settings.manage"),
        Endpoint("POST", "/api/settings", "settings.manage",
                 body={}),
        Endpoint("PUT", "/api/settings", "settings.manage",
                 body={}),
        Endpoint("DELETE", "/api/events/cleanup", "settings.manage"),
        Endpoint("GET", "/api/v2/audit-log/retention", "settings.manage"),
        Endpoint("PUT", "/api/v2/audit-log/retention", "settings.manage",
                 body={"retention_days": 90}),
        Endpoint("POST", "/api/v2/audit-log/cleanup", "settings.manage"),

        # ---- audit.view ----
        Endpoint("GET", "/api/security/audit", "audit.view"),
        Endpoint("GET", "/api/v2/audit-log", "audit.view"),
        Endpoint("GET", "/api/v2/audit-log/actions", "audit.view"),
        Endpoint("GET", "/api/v2/audit-log/entity-types", "audit.view"),
        Endpoint("GET", "/api/v2/audit-log/users", "audit.view"),
        Endpoint("GET", "/api/v2/audit-log/stats", "audit.view"),
        Endpoint("GET", "/api/v2/audit-log/export", "audit.view"),

        # ---- registry.view ----
        Endpoint("GET", "/api/registry-credentials", "registry.view"),

        # ---- registry.manage ----
        Endpoint("POST", "/api/registry-credentials", "registry.manage",
                 body={"name": "_test_cap_reg", "url": "https://registry.example.com",
                       "username": "test", "password": "test"}),
        Endpoint("PUT", f"/api/registry-credentials/{fake_id}", "registry.manage",
                 body={"name": "_test_cap_reg", "url": "https://registry.example.com",
                       "username": "test", "password": "test"}),
        Endpoint("DELETE", f"/api/registry-credentials/{fake_id}", "registry.manage"),

        # ---- agents.view ----
        Endpoint("GET", "/api/agent/list", "agents.view"),
        Endpoint("GET", f"/api/agent/{fake_uuid}/status", "agents.view"),

        # ---- agents.manage ----
        Endpoint("POST", "/api/agent/generate-token", "agents.manage"),
        Endpoint("POST", f"/api/hosts/{host_id}/agent/update", "agents.manage"),
        Endpoint("POST", f"/api/agent/{fake_uuid}/migrate-from/{fake_uuid}", "agents.manage"),

        # ---- groups.manage ----
        Endpoint("GET", "/api/v2/groups", "groups.manage"),
        Endpoint("POST", "/api/v2/groups", "groups.manage",
                 body={"name": "_test_cap_group_endpoint", "description": "test"}),
        Endpoint("GET", f"/api/v2/groups/{fake_id}", "groups.manage"),
        Endpoint("PUT", f"/api/v2/groups/{fake_id}", "groups.manage",
                 body={"name": "_test_cap_group_upd"}),
        Endpoint("DELETE", f"/api/v2/groups/{fake_id}", "groups.manage"),
        Endpoint("POST", f"/api/v2/groups/{fake_id}/members", "groups.manage",
                 body={"user_id": 999}),
        Endpoint("DELETE", f"/api/v2/groups/{fake_id}/members/999", "groups.manage"),
        Endpoint("GET", f"/api/v2/groups/{fake_id}/members", "groups.manage"),
        Endpoint("GET", "/api/v2/groups/permissions/all", "groups.manage"),
        Endpoint("GET", f"/api/v2/groups/{fake_id}/permissions", "groups.manage"),
        Endpoint("PUT", f"/api/v2/groups/{fake_id}/permissions", "groups.manage",
                 body={"permissions": []}),
        Endpoint("POST", f"/api/v2/groups/{fake_id}/permissions/copy-from/{fake_id}", "groups.manage"),

        # ---- users.manage ----
        Endpoint("GET", "/api/v2/users", "users.manage"),
        Endpoint("POST", "/api/v2/users", "users.manage",
                 body={"username": "testcap_user_ep", "password": TEST_PASSWORD,
                       "group_ids": [999999]}),
        Endpoint("GET", f"/api/v2/users/{fake_id}", "users.manage"),
        Endpoint("PUT", f"/api/v2/users/{fake_id}", "users.manage",
                 body={"display_name": "test"}),
        Endpoint("DELETE", f"/api/v2/users/{fake_id}", "users.manage"),
        Endpoint("POST", f"/api/v2/users/{fake_id}/reset-password", "users.manage",
                 body={}),

        # ---- oidc.manage ----
        Endpoint("GET", "/api/v2/oidc/config", "oidc.manage"),
        Endpoint("PUT", "/api/v2/oidc/config", "oidc.manage",
                 body={"enabled": False}),
        Endpoint("POST", "/api/v2/oidc/discover", "oidc.manage",
                 body={"issuer_url": "https://example.com"}),
        Endpoint("GET", "/api/v2/oidc/group-mappings", "oidc.manage"),
        Endpoint("POST", "/api/v2/oidc/group-mappings", "oidc.manage",
                 body={"oidc_claim_value": "_test_cap", "group_id": 1}),
        Endpoint("PUT", f"/api/v2/oidc/group-mappings/{fake_id}", "oidc.manage",
                 body={"oidc_claim_value": "_test_cap", "group_id": 1}),
        Endpoint("DELETE", f"/api/v2/oidc/group-mappings/{fake_id}", "oidc.manage"),

        # ---- apikeys.manage_other ----
        Endpoint("POST", "/api/v2/api-keys/", "apikeys.manage_other",
                 body={"name": "_test_cap_key", "group_id": 1}),
        Endpoint("GET", "/api/v2/api-keys/", "apikeys.manage_other"),
        Endpoint("PATCH", f"/api/v2/api-keys/{fake_id}", "apikeys.manage_other",
                 body={"name": "_test_cap_key_upd"}),
        Endpoint("DELETE", f"/api/v2/api-keys/{fake_id}", "apikeys.manage_other"),
    ]

    return endpoints


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------
class CapabilityTester:
    def __init__(self, base_url: str, admin_user: str, admin_pass: str,
                 verify_ssl: bool = True, filter_capability: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.admin_user = admin_user
        self.admin_pass = admin_pass
        self.verify_ssl = verify_ssl
        self.filter_capability = filter_capability

        # Track created resources for cleanup
        self.created_group_ids: list[int] = []
        self.created_user_ids: list[int] = []
        self.user_group_map: dict[int, int] = {}  # user_id -> group_id
        self.host_id: str = ""
        self.container_id: str = ""
        self.test_container_created = False
        self._cleaned_up = False

        # Session cache: capability -> httpx.Client with session cookie
        # Keys that map to None indicate a cached login failure
        self._sessions: dict[str, httpx.Client | None] = {}

        # Admin session
        self.admin_client: httpx.Client | None = None

        # Results
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.failures: list[str] = []

    # ----- HTTP helpers -----

    def _make_client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            verify=self.verify_ssl,
            timeout=30.0,
            follow_redirects=True,
        )

    def _login(self, client: httpx.Client, username: str, password: str) -> bool:
        """Login and store session cookie in client."""
        resp = client.post("/api/v2/auth/login", json={
            "username": username,
            "password": password,
        })
        return resp.status_code == 200

    def _admin_request(self, method: str, path: str, **kwargs) -> httpx.Response:
        assert self.admin_client is not None
        return self.admin_client.request(method, path, **kwargs)

    def _extract_list(self, resp: httpx.Response, key: str) -> list:
        """Extract a list from an API response, handling both {key: [...]} and [...] formats."""
        if resp.status_code != 200:
            return []
        data = resp.json()
        items = data.get(key, data) if isinstance(data, dict) else data
        return items if isinstance(items, list) else []

    def _get_session(self, capability: str | None) -> httpx.Client | None:
        """Get or create a logged-in session for a capability's test user.

        Returns None if login failed (cached to avoid repeated attempts).
        """
        key = capability or "__noperms__"
        if key in self._sessions:
            return self._sessions[key]

        client = self._make_client()
        username = "testcap_noperms" if capability is None else f"testcap_{capability.replace('.', '_')}"

        if not self._login(client, username, TEST_PASSWORD):
            print(f"  {RED}ERROR{RESET} Could not login as {username}")
            client.close()
            self._sessions[key] = None  # Cache failure
            return None

        self._sessions[key] = client
        return client

    def _safe_request(self, client: httpx.Client, method: str, path: str,
                      **kwargs) -> int:
        """Make an HTTP request, returning the status code or -1 on timeout."""
        try:
            return client.request(method, path, **kwargs).status_code
        except httpx.TimeoutException:
            return -1

    # ----- Setup -----

    def setup(self) -> bool:
        """Create admin session, test container, groups, users."""
        print(f"\n{BOLD}=== DockMon Capability Matrix Test ==={RESET}")
        print(f"Target: {self.base_url}\n")

        # 1. Admin login
        print("[SETUP] Admin login...", end=" ", flush=True)
        self.admin_client = self._make_client()
        if not self._login(self.admin_client, self.admin_user, self.admin_pass):
            print(fail("- Could not login as admin"))
            return False
        print(ok())

        # 2. Discover host_id (localhost)
        print("[SETUP] Discovering localhost host_id...", end=" ", flush=True)
        hosts = self._extract_list(self._admin_request("GET", "/api/hosts"), "hosts")
        if not hosts:
            print(fail("- No hosts found"))
            return False
        self.host_id = hosts[0]["id"]
        print(ok(f"host_id={self.host_id}"))

        # 3. Create a dedicated test container via Docker CLI
        print("[SETUP] Creating test container...", end=" ", flush=True)
        if not self._create_test_container():
            return False

        # 4. Wait for DockMon to discover the test container
        print("[SETUP] Waiting for container discovery...", end=" ", flush=True)
        if not self._wait_for_test_container():
            return False

        # 5. Collect unique capabilities from the endpoint matrix
        endpoints = build_endpoint_matrix(self.host_id, self.container_id)
        capabilities = sorted(set(ep.capability for ep in endpoints))
        print(f"\n[SETUP] {len(capabilities)} unique capabilities across {len(endpoints)} endpoints")

        # 6. Create test groups
        print("[SETUP] Creating test groups...", end=" ", flush=True)
        no_perms_group_id = self._create_group("_test_no_perms")
        if no_perms_group_id is None:
            print(fail())
            return False

        cap_group_ids: dict[str, int] = {}
        for cap in capabilities:
            group_name = f"_test_cap_{cap.replace('.', '_')}"
            gid = self._create_group(group_name)
            if gid is None:
                print(f"\n  {fail(f'creating group for {cap}')}")
                return False
            cap_group_ids[cap] = gid

            # Set capability on this group
            self._admin_request("PUT", f"/api/v2/groups/{gid}/permissions", json={
                "permissions": [{"capability": cap, "allowed": True}]
            })

        print(ok(f"{len(cap_group_ids) + 1} groups"))

        # 7. Create test users
        print("[SETUP] Creating test users...", end=" ", flush=True)

        # No-perms user
        uid = self._create_user("testcap_noperms", no_perms_group_id)
        if uid is None:
            print(fail("creating no-perms user"))
            return False

        # Per-capability users
        for cap, gid in cap_group_ids.items():
            username = f"testcap_{cap.replace('.', '_')}"
            uid = self._create_user(username, gid)
            if uid is None:
                print(f"\n  {fail(f'creating user for {cap}')}")
                return False

        print(ok(f"{len(cap_group_ids) + 1} users"))
        return True

    def _create_test_container(self) -> bool:
        """Create a dedicated nginx container for destructive tests."""
        subprocess.run(
            ["docker", "rm", "-f", TEST_CONTAINER_NAME],
            capture_output=True,
        )
        result = subprocess.run(
            ["docker", "run", "-d", "--name", TEST_CONTAINER_NAME, "nginx:alpine"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(fail(f"- docker run failed: {result.stderr.strip()}"))
            return False
        self.test_container_created = True
        print(ok(TEST_CONTAINER_NAME))
        return True

    def _wait_for_test_container(self, timeout: int = 30) -> bool:
        """Poll the DockMon API until the test container appears."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            containers = self._extract_list(
                self._admin_request("GET", "/api/containers"), "containers")
            for c in containers:
                name = c.get("name", "").lstrip("/")
                if name == "dockmon":
                    continue
                if name == TEST_CONTAINER_NAME:
                    cid = c.get("id", c.get("short_id", ""))
                    if cid:
                        self.container_id = cid[:12]
                        print(ok(f"container_id={self.container_id}"))
                        return True
            time.sleep(2)
        print(fail(f"- Test container not discovered within {timeout}s"))
        return False

    def _remove_test_container(self):
        """Remove the test container via Docker CLI."""
        if not self.test_container_created:
            return
        for name in [TEST_CONTAINER_NAME, f"{TEST_CONTAINER_NAME}-renamed"]:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)

    def _create_group(self, name: str) -> int | None:
        resp = self._admin_request("POST", "/api/v2/groups", json={
            "name": name,
            "description": f"Test group: {name}",
        })
        if resp.status_code in (200, 201):
            data = resp.json()
            gid = data.get("id") or data.get("group", {}).get("id")
            if gid:
                self.created_group_ids.append(gid)
                return gid
        if resp.status_code in (400, 409):
            return self._find_resource("GET", "/api/v2/groups", "groups",
                                       "name", name, self.created_group_ids)
        print(f"\n  {fail(f': {name} -> {resp.status_code}: {resp.text[:200]}')}")
        return None

    def _create_user(self, username: str, group_id: int) -> int | None:
        body = {
            "username": username,
            "password": TEST_PASSWORD,
            "group_ids": [group_id],
            "must_change_password": False,
        }
        resp = self._admin_request("POST", "/api/v2/users", json=body)
        if resp.status_code in (200, 201):
            data = resp.json()
            uid = data.get("id") or data.get("user", {}).get("id")
            if uid:
                self.created_user_ids.append(uid)
                self.user_group_map[uid] = group_id
                return uid
        if resp.status_code in (400, 409):
            # User exists from a previous run - reset password and ensure correct group.
            existing_id = self._find_resource("GET", "/api/v2/users",
                                              "users", "username", username, [])
            if existing_id:
                self._admin_request("POST", f"/api/v2/users/{existing_id}/reset-password",
                                    json={"new_password": TEST_PASSWORD})
                # Ensure user is in the correct group (add target first, then remove others)
                self._admin_request("POST", f"/api/v2/groups/{group_id}/members",
                                    json={"user_id": existing_id})
                # Remove from any other groups (leftover from previous cleanup)
                user_resp = self._admin_request("GET", f"/api/v2/users/{existing_id}")
                user_groups = user_resp.json().get("groups", []) if user_resp.status_code == 200 else []
                for g in user_groups:
                    if g.get("id") != group_id:
                        self._admin_request("DELETE",
                                            f"/api/v2/groups/{g['id']}/members/{existing_id}")
                self.created_user_ids.append(existing_id)
                self.user_group_map[existing_id] = group_id
                return existing_id
        print(f"\n  {fail(f': {username} -> {resp.status_code}: {resp.text[:200]}')}")
        return None

    def _find_resource(self, method: str, path: str, list_key: str,
                       match_field: str, match_value: str,
                       tracking_list: list[int]) -> int | None:
        """Find an existing resource by field value and track its ID."""
        items = self._extract_list(self._admin_request(method, path), list_key)
        for item in items:
            if item.get(match_field) == match_value:
                rid = item["id"]
                if rid not in tracking_list:
                    tracking_list.append(rid)
                return rid
        return None

    # ----- Test execution -----

    def run_tests(self):
        """Run all endpoint tests."""
        endpoints = build_endpoint_matrix(self.host_id, self.container_id)
        if self.filter_capability:
            endpoints = [ep for ep in endpoints if ep.capability == self.filter_capability]

        # Group endpoints by capability for display
        by_cap: dict[str, list[Endpoint]] = {}
        for ep in endpoints:
            by_cap.setdefault(ep.capability, []).append(ep)

        print(f"\n{BOLD}=== Running Tests ==={RESET}\n")

        for cap in sorted(by_cap.keys()):
            eps = by_cap[cap]
            active_count = sum(1 for e in eps if not e.skip)
            print(f"{BOLD}--- {cap} ({active_count} endpoints) ---{RESET}")

            for ep in eps:
                if ep.skip:
                    self.skipped += 1
                    path_short = self._shorten_path(ep.path)
                    print(f"  {YELLOW}SKIP{RESET}  {ep.method:6s} {path_short}  ({ep.skip_reason})")
                    continue
                self._test_endpoint(ep)

            print()

    def _test_endpoint(self, ep: Endpoint):
        """Test a single endpoint: deny with no perms, allow with correct cap."""
        path_short = self._shorten_path(ep.path)
        kwargs: dict = {}
        if ep.body is not None:
            kwargs["json"] = ep.body

        # Deny test: no-perms user should get 403
        deny_client = self._get_session(None)
        if deny_client is None:
            self.failed += 1
            print(f"  {RED}FAIL{RESET}  {ep.method:6s} {path_short:55s} deny=LOGIN_FAILED")
            self.failures.append(f"{ep.method} {ep.path} [{ep.capability}]: no-perms login failed")
            return

        deny_code = self._safe_request(deny_client, ep.method, ep.path, **kwargs)

        # Allow test: user with matching capability should get non-403
        allow_client = self._get_session(ep.capability)
        if allow_client is None:
            self.failed += 1
            print(f"  {RED}FAIL{RESET}  {ep.method:6s} {path_short:55s} deny={deny_code} allow=LOGIN_FAILED")
            self.failures.append(f"{ep.method} {ep.path} [{ep.capability}]: cap user login failed")
            return

        allow_code = self._safe_request(allow_client, ep.method, ep.path, **kwargs)

        deny_ok = deny_code == 403
        allow_ok = allow_code not in (403, -1)

        if deny_ok and allow_ok:
            self.passed += 1
            print(f"  {GREEN}PASS{RESET}  {ep.method:6s} {path_short:55s} deny={deny_code} allow={allow_code}")
        else:
            self.failed += 1
            parts = []
            if deny_code == -1:
                parts.append("deny=TIMEOUT")
            elif not deny_ok:
                parts.append(f"deny={deny_code} EXPECTED 403!")
            if allow_code == -1:
                parts.append("allow=TIMEOUT")
            elif not allow_ok:
                parts.append(f"allow={allow_code} EXPECTED non-403!")
            detail = "  ".join(parts)
            print(f"  {RED}FAIL{RESET}  {ep.method:6s} {path_short:55s} {detail}")
            self.failures.append(f"{ep.method} {ep.path} [{ep.capability}]: {detail}")

    def _shorten_path(self, path: str) -> str:
        """Shorten path for display, replacing UUIDs and long IDs."""
        path = re.sub(
            r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
            '{id}', path)
        path = re.sub(r'/([0-9a-f]{12})(?=/|$)', r'/{cid}', path)
        return path

    # ----- Results -----

    def print_results(self):
        total = self.passed + self.failed + self.skipped
        print(f"\n{BOLD}=== RESULTS ==={RESET}")
        print(f"  {GREEN}Passed{RESET}:  {self.passed}")
        print(f"  {RED}Failed{RESET}:  {self.failed}")
        print(f"  {YELLOW}Skipped{RESET}: {self.skipped}")
        print(f"  Total:   {total}")

        if self.failures:
            print(f"\n{BOLD}{RED}Failures:{RESET}")
            for failure in self.failures:
                print(f"  - {failure}")

    # ----- Cleanup -----

    def cleanup(self):
        """Delete all test users, groups, container. Always runs (but only once)."""
        if self._cleaned_up:
            return
        self._cleaned_up = True

        print(f"\n[CLEANUP] Removing test data...")

        # Remove test container first (Docker CLI, no server dependency)
        self._remove_test_container()
        time.sleep(2)  # Let server process container removal event

        # Close test session clients
        for client in self._sessions.values():
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
        self._sessions.clear()

        # Re-login with a fresh admin session for cleanup
        if self.admin_client is not None:
            try:
                self.admin_client.close()
            except Exception:
                pass

        self.admin_client = self._make_client()
        if not self._login(self.admin_client, self.admin_user, self.admin_pass):
            print(f"[CLEANUP] {RED}Could not re-login as admin, skipping API cleanup{RESET}")
            return

        # Step 1: Move test users to a system group so they have 2 groups,
        # then remove from test group (API requires users to always have >= 1 group)
        if self.user_group_map:
            # Find a system group to temporarily hold users
            system_group_id = self._find_system_group_id()
            if system_group_id:
                print(f"[CLEANUP] Reassigning {len(self.user_group_map)} test users...", end=" ", flush=True)
                reassigned = 0
                for uid, gid in self.user_group_map.items():
                    try:
                        # Add to system group (gives user 2 groups)
                        self._admin_request("POST", f"/api/v2/groups/{system_group_id}/members",
                                            json={"user_id": uid})
                        # Remove from test group (now safe — still in system group)
                        resp = self._admin_request("DELETE", f"/api/v2/groups/{gid}/members/{uid}")
                        if resp.status_code in (200, 204, 404):
                            reassigned += 1
                    except (httpx.ConnectError, httpx.TimeoutException):
                        pass
                print(ok(f"{reassigned} reassigned"))
                time.sleep(0.5)

        # Step 2: Delete test groups (now safe — no test users in them)
        if self.created_group_ids:
            print(f"[CLEANUP] Deleting {len(self.created_group_ids)} test groups...", end=" ", flush=True)
            deleted = self._bulk_delete("/api/v2/groups", self.created_group_ids)
            print(ok(f"{deleted} deleted"))
            time.sleep(0.5)

        # Step 3: Delete test users
        if self.created_user_ids:
            print(f"[CLEANUP] Deleting {len(self.created_user_ids)} test users...", end=" ", flush=True)
            deleted = self._bulk_delete("/api/v2/users", self.created_user_ids)
            print(ok(f"{deleted} deleted"))
            time.sleep(0.5)

        # Step 4: Clean up side-effect resources created by allow tests
        self._cleanup_by_prefix("/api/v2/api-keys/", "keys", "name", "_test_cap")
        self._cleanup_by_prefix("/api/hosts", "hosts", "name", "_test_cap")
        self._cleanup_by_prefix("/api/stacks", "stacks", "name", "_test_cap")
        self._cleanup_by_prefix("/api/deployments", "deployments", "name", "_test_cap")
        self._cleanup_by_prefix("/api/registry-credentials", "credentials", "name", "_test_cap")
        self._cleanup_by_prefix("/api/alerts/rules", "rules", "name", "_test_cap")
        self._cleanup_by_prefix("/api/notifications/channels", "channels", "name", "_test_cap")
        self._cleanup_by_prefix("/api/update-policies", "policies", "name", "_test_cap",
                                delete_base="/api/update-policies/custom")
        self._cleanup_by_prefix("/api/v2/oidc/group-mappings", "mappings",
                                "oidc_claim_value", "_test_cap")
        self._cleanup_by_prefix("/api/v2/users", "users", "username", "testcap_user_ep")
        self._cleanup_by_prefix("/api/v2/groups", "groups", "name", "_test_cap_group_endpoint")

        try:
            self.admin_client.close()
        except Exception:
            pass

        print("[CLEANUP] Done.")

    def _bulk_delete(self, base_path: str, ids: list[int]) -> int:
        """Delete resources by ID, tolerating individual failures."""
        deleted = 0
        for rid in ids:
            try:
                resp = self._admin_request("DELETE", f"{base_path}/{rid}")
                if resp.status_code in (200, 204, 404):
                    deleted += 1
            except (httpx.ConnectError, httpx.TimeoutException):
                pass
        return deleted

    def _find_system_group_id(self) -> int | None:
        """Find a system group (e.g. Read Only) to temporarily hold users during cleanup."""
        try:
            groups = self._extract_list(
                self._admin_request("GET", "/api/v2/groups"), "groups")
            for g in groups:
                if g.get("is_system") and g.get("name") == "Read Only":
                    return g["id"]
            # Fallback: any system group
            for g in groups:
                if g.get("is_system"):
                    return g["id"]
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        return None

    def _cleanup_by_prefix(self, list_endpoint: str, list_key: str,
                           name_field: str, prefix: str,
                           delete_base: str | None = None):
        """Generic cleanup: list resources, delete those matching a name prefix."""
        try:
            resp = self._admin_request("GET", list_endpoint)
            items = self._extract_list(resp, list_key)
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            print(f"  [CLEANUP] Could not list {list_endpoint}: {e}")
            return
        delete_path = delete_base or list_endpoint
        for item in items:
            if not item.get(name_field, "").startswith(prefix):
                continue
            try:
                if list_endpoint == "/api/stacks":
                    self._admin_request("DELETE", f"{delete_path}/{item['name']}")
                else:
                    item_id = item.get("id") or item.get("name", "")
                    self._admin_request("DELETE", f"{delete_path}/{item_id}")
            except (httpx.ConnectError, httpx.TimeoutException):
                pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="DockMon Capability Matrix E2E Test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/test_capabilities.py --url https://localhost:8001 --username admin --password secret --insecure
  python scripts/test_capabilities.py --url http://localhost:8000 -u admin -p secret
        """,
    )
    parser.add_argument("--url", "-U", required=True, help="DockMon base URL")
    parser.add_argument("--username", "-u", default="admin", help="Admin username (default: admin)")
    parser.add_argument("--password", "-p", required=True, help="Admin password")
    parser.add_argument("--insecure", "-k", action="store_true", help="Disable SSL verification")
    parser.add_argument("--capability", "-c", help="Test only this capability (e.g. 'hosts.view')")
    args = parser.parse_args()

    tester = CapabilityTester(
        base_url=args.url,
        admin_user=args.username,
        admin_pass=args.password,
        verify_ssl=not args.insecure,
        filter_capability=args.capability,
    )

    # Signal handlers for cleanup on interrupt
    signal.signal(signal.SIGINT, lambda *_: (tester.cleanup(), sys.exit(130)))
    signal.signal(signal.SIGTERM, lambda *_: (tester.cleanup(), sys.exit(143)))

    try:
        if not tester.setup():
            print(f"\n{RED}Setup failed. Aborting.{RESET}")
            sys.exit(1)

        tester.run_tests()
        tester.print_results()
    finally:
        tester.cleanup()

    sys.exit(1 if tester.failed > 0 else 0)


if __name__ == "__main__":
    main()
