#!/usr/bin/env python3
"""
DockMon Tag-Based Host Visibility E2E Test

Exercises tag-scoped host visibility against a running instance. Creates two
tenant groups scoped to one tag each, tags two existing hosts, and verifies:

1. HTTP lists (hosts, containers, dashboard, events) only show visible hosts
2. Host-addressed routes answer 404 (never 403) for a hidden host
3. A group scoped to a tag no host carries sees nothing; an admin sees everything
4. Open WebSockets are pruned per connection, and start/stop delivering a
   host live when its tags or the user's membership change - no reconnect

Everything it creates is prefixed "scopetest" and removed on exit, including
the temporary host tags. The instance needs at least two hosts.

Usage:
    python scripts/test_host_scope.py --url https://localhost:8001 --insecure \
        (--api-key <admin key> | --username admin --password <password>) \
        [--host-a <name>] [--host-b <name>]
"""

import argparse
import asyncio
import json
import ssl
import sys
import time

import httpx
import websockets

TEST_PASSWORD = "ScopeTest123!"
PREFIX = "scopetest"
TAG_A, TAG_B, TAG_NONE = f"{PREFIX}-a", f"{PREFIX}-b", f"{PREFIX}-none"
GROUP_A, GROUP_B, GROUP_NONE = f"{PREFIX}-tenant-a", f"{PREFIX}-tenant-b", f"{PREFIX}-empty-scope"
USER_A, USER_B, USER_NONE = f"{PREFIX}_a", f"{PREFIX}_b", f"{PREFIX}_empty"
TENANT_CAPS = ["hosts.view", "containers.view", "containers.logs", "containers.operate", "events.view", "alerts.view"]
REQUEST_PACE = 0.5  # stays under the default 120/min limiter with its 20-request burst

GREEN, RED, YELLOW, BOLD, RESET = "\033[92m", "\033[91m", "\033[93m", "\033[1m", "\033[0m"


class HostScopeTester:
    def __init__(self, base_url: str, admin_user: str | None, admin_pass: str | None, api_key: str | None,
                 verify_ssl: bool, host_a: str | None, host_b: str | None):
        self.base_url = base_url.rstrip("/")
        self.ws_base = self.base_url.replace("https://", "wss://").replace("http://", "ws://")
        self.admin_user, self.admin_pass, self.api_key, self.verify_ssl = admin_user, admin_pass, api_key, verify_ssl
        self.want_host_a, self.want_host_b = host_a, host_b

        self.admin: httpx.Client | None = None
        self.clients: dict[str, httpx.Client] = {}
        self.host_a: dict = {}
        self.host_b: dict = {}
        self.group_ids: dict[str, int] = {}
        self.user_ids: dict[str, int] = {}
        self.tagged: list[tuple[str, str]] = []  # (host_id, tag) to remove on cleanup
        self._last_request = 0.0

        self.passed, self.failed = 0, 0
        self.failures: list[str] = []

    # ----- HTTP -----

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, verify=self.verify_ssl, timeout=30.0)

    def _request(self, client: httpx.Client, method: str, path: str, **kw) -> httpx.Response:
        wait = REQUEST_PACE - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        for attempt in range(3):
            resp = client.request(method, path, **kw)
            self._last_request = time.monotonic()
            if resp.status_code != 429:
                return resp
            time.sleep(5 * (attempt + 1))
        return resp

    def _admin(self, method: str, path: str, **kw) -> httpx.Response:
        assert self.admin is not None
        return self._request(self.admin, method, path, **kw)

    def _login(self, username: str, password: str) -> httpx.Client | None:
        client = self._client()
        resp = self._request(client, "POST", "/api/v2/auth/login", json={"username": username, "password": password})
        if resp.status_code != 200:
            client.close()
            return None
        return client

    @staticmethod
    def _items(resp: httpx.Response, key: str) -> list:
        if resp.status_code != 200:
            return []
        data = resp.json()
        items = data.get(key, data) if isinstance(data, dict) else data
        return items if isinstance(items, list) else []

    # ----- assertions -----

    def check(self, name: str, condition: bool, detail: str = ""):
        if condition:
            self.passed += 1
            print(f"  {GREEN}PASS{RESET} {name}")
        else:
            self.failed += 1
            self.failures.append(f"{name} {detail}".strip())
            print(f"  {RED}FAIL{RESET} {name}  {detail}")

    # ----- setup -----

    def setup(self) -> bool:
        print(f"\n{BOLD}=== DockMon Host Scope E2E Test ==={RESET}\nTarget: {self.base_url}\n")

        print("[SETUP] Admin auth...", end=" ", flush=True)
        if self.api_key:
            self.admin = self._client()
            self.admin.headers["Authorization"] = f"Bearer {self.api_key}"
            if self._admin("GET", "/api/v2/groups").status_code != 200:
                print(f"{RED}API key rejected or lacks groups.manage{RESET}")
                return False
        else:
            self.admin = self._login(self.admin_user, self.admin_pass)
            if not self.admin:
                print(f"{RED}could not log in{RESET}")
                return False
        print("ok")

        print("[SETUP] Picking hosts...", end=" ", flush=True)
        hosts = self._items(self._admin("GET", "/api/hosts"), "hosts")
        by_name = {h["name"]: h for h in hosts}
        if self.want_host_a and self.want_host_a not in by_name:
            print(f"{RED}no host named {self.want_host_a!r}{RESET}")
            return False
        if self.want_host_b and self.want_host_b not in by_name:
            print(f"{RED}no host named {self.want_host_b!r}{RESET}")
            return False
        if len(hosts) < 2:
            print(f"{RED}needs two hosts, instance has {len(hosts)}{RESET}")
            return False
        self.host_a = by_name[self.want_host_a] if self.want_host_a else hosts[0]
        remaining = [h for h in hosts if h["id"] != self.host_a["id"]]
        self.host_b = by_name[self.want_host_b] if self.want_host_b else remaining[0]
        if self.host_b["id"] == self.host_a["id"]:
            print(f"{RED}--host-a and --host-b must differ{RESET}")
            return False
        print(f"A={self.host_a['name']}  B={self.host_b['name']}")

        print("[SETUP] Tagging hosts...", end=" ", flush=True)
        if not (self._tag_host(self.host_a["id"], TAG_A) and self._tag_host(self.host_b["id"], TAG_B)
                and self._tag_host(self.host_b["id"], TAG_NONE)):
            return False
        print("ok")

        print("[SETUP] Groups, scopes, users...", end=" ", flush=True)
        host_tags = {t["name"]: t["id"] for t in self._items(self._admin("GET", "/api/v2/groups/host-tags"), "tags")}
        for group, tag in ((GROUP_A, TAG_A), (GROUP_B, TAG_B), (GROUP_NONE, TAG_NONE)):
            gid = self._create_group(group)
            if gid is None:
                return False
            self.group_ids[group] = gid
            self._admin("PUT", f"/api/v2/groups/{gid}/permissions",
                        json={"permissions": [{"capability": c, "allowed": True} for c in TENANT_CAPS]})
            if tag not in host_tags:
                print(f"{RED}tag {tag} missing from /api/v2/groups/host-tags{RESET}")
                return False
            resp = self._admin("PUT", f"/api/v2/groups/{gid}/tag-scopes", json={"tag_ids": [host_tags[tag]]})
            if resp.status_code != 200:
                print(f"{RED}tag-scopes PUT -> {resp.status_code}: {resp.text[:200]}{RESET}")
                return False
        for user, group in ((USER_A, GROUP_A), (USER_B, GROUP_B), (USER_NONE, GROUP_NONE)):
            uid = self._create_user(user, [self.group_ids[group]])
            if uid is None:
                return False
            self.user_ids[user] = uid
        # The scope tag only had to exist to be selectable; with no host carrying it the group sees nothing
        if not self._untag_host(self.host_b["id"], TAG_NONE):
            print(f"{RED}could not untag {TAG_NONE}{RESET}")
            return False
        self.tagged.remove((self.host_b["id"], TAG_NONE))
        print("ok")

        print("[SETUP] Tenant logins...", end=" ", flush=True)
        for user in (USER_A, USER_B, USER_NONE):
            client = self._login(user, TEST_PASSWORD)
            if not client:
                print(f"{RED}could not log in as {user}{RESET}")
                return False
            self.clients[user] = client
        print("ok\n")
        return True

    def _tag_host(self, host_id: str, tag: str) -> bool:
        resp = self._admin("PATCH", f"/api/hosts/{host_id}/tags", json={"tags_to_add": [tag]})
        if resp.status_code != 200:
            print(f"{RED}tag PATCH -> {resp.status_code}: {resp.text[:200]}{RESET}")
            return False
        self.tagged.append((host_id, tag))
        return True

    def _untag_host(self, host_id: str, tag: str) -> bool:
        resp = self._admin("PATCH", f"/api/hosts/{host_id}/tags", json={"tags_to_remove": [tag]})
        return resp.status_code == 200

    def _create_group(self, name: str) -> int | None:
        resp = self._admin("POST", "/api/v2/groups", json={"name": name, "description": "host scope e2e"})
        if resp.status_code in (200, 201):
            return resp.json().get("id")
        if resp.status_code in (400, 409):
            for g in self._items(self._admin("GET", "/api/v2/groups"), "groups"):
                if g.get("name") == name:
                    return g["id"]
        print(f"{RED}group {name} -> {resp.status_code}: {resp.text[:200]}{RESET}")
        return None

    def _create_user(self, username: str, group_ids: list[int]) -> int | None:
        resp = self._admin("POST", "/api/v2/users", json={
            "username": username, "password": TEST_PASSWORD, "group_ids": group_ids, "must_change_password": False,
        })
        if resp.status_code in (200, 201):
            return resp.json().get("id")
        if resp.status_code in (400, 409):
            for u in self._items(self._admin("GET", "/api/v2/users"), "users"):
                if u.get("username") == username:
                    self._admin("POST", f"/api/v2/users/{u['id']}/reset-password", json={"new_password": TEST_PASSWORD})
                    self._admin("PUT", f"/api/v2/users/{u['id']}", json={"group_ids": group_ids})
                    return u["id"]
        print(f"{RED}user {username} -> {resp.status_code}: {resp.text[:200]}{RESET}")
        return None

    # ----- HTTP checks -----

    def run_http_checks(self):
        a_id, b_id = self.host_a["id"], self.host_b["id"]
        both = {a_id, b_id}
        principals = {
            "admin": (self.admin, both),
            "tenant-a": (self.clients[USER_A], {a_id}),
            "tenant-b": (self.clients[USER_B], {b_id}),
            "empty-scope": (self.clients[USER_NONE], set()),
        }

        print(f"{BOLD}[HTTP] List surfaces{RESET}")
        for who, (client, visible) in principals.items():
            hidden = both - visible
            hosts = {h["id"] for h in self._items(self._request(client, "GET", "/api/hosts"), "hosts")}
            self.check(f"{who}: /api/hosts shows visible, hides hidden",
                       visible <= hosts and not (hidden & hosts), f"got {sorted(hosts & both)}")
            containers = self._items(self._request(client, "GET", "/api/containers"), "containers")
            leaked = {c["host_id"] for c in containers} & hidden
            self.check(f"{who}: /api/containers has no hidden host", not leaked, f"leaked {sorted(leaked)}")
            dash_groups = self._request(client, "GET", "/api/dashboard/hosts").json().get("groups", {})
            dash = {h["id"] for group in dash_groups.values() for h in group}
            self.check(f"{who}: /api/dashboard/hosts has no hidden host", not (dash & hidden), f"leaked {sorted(dash & hidden)}")
            events = self._items(self._request(client, "GET", "/api/events", params={"limit": 100}), "events")
            leaked = {e.get("host_id") for e in events} & hidden
            self.check(f"{who}: /api/events has no hidden host", not leaked, f"leaked {sorted(leaked)}")

        print(f"\n{BOLD}[HTTP] Host-addressed routes{RESET}")
        a_containers = [c for c in self._items(self._admin("GET", "/api/containers"), "containers") if c.get("host_id") == a_id]
        if not a_containers:
            self.check("host A has at least one container to address", False)
            return
        cid = (a_containers[0].get("id") or a_containers[0].get("short_id"))[:12]
        routes = [
            ("GET", f"/api/hosts/{a_id}/metrics"),
            ("GET", f"/api/hosts/{a_id}/images"),
            ("GET", f"/api/hosts/{a_id}/containers/{cid}/inspect"),
            ("GET", f"/api/hosts/{a_id}/containers/{cid}/logs?tail=1"),
            ("POST", f"/api/hosts/{a_id}/containers/{cid}/restart"),
        ]
        for method, path in routes:
            expect_ok = method == "GET"  # the restart is only sent to hidden-host principals
            for who in ("tenant-b", "empty-scope"):
                code = self._request(principals[who][0], method, path).status_code
                self.check(f"{who}: {method} {self._short(path)} -> 404 (never 403)", code == 404, f"got {code}")
            if expect_ok:
                code = self._request(principals["tenant-a"][0], method, path).status_code
                self.check(f"tenant-a: {method} {self._short(path)} -> 200", code == 200, f"got {code}")

    def _short(self, path: str) -> str:
        for h in (self.host_a, self.host_b):
            if h:
                path = path.replace(h["id"], f"<{h['name']}>")
        return path

    # ----- WebSocket checks -----

    def run_ws_checks(self):
        print(f"\n{BOLD}[WS] Per-connection visibility and live refresh{RESET}")
        asyncio.run(self._ws_checks())

    def _ws_headers(self, client: httpx.Client) -> dict:
        return {"Cookie": f"session_id={client.cookies.get('session_id')}"}

    def _ssl(self):
        if not self.base_url.startswith("https"):
            return None
        ctx = ssl.create_default_context()
        if not self.verify_ssl:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    async def _hosts_seen(self, ws, seconds: float) -> set[str]:
        """Union of host ids in initial_state/containers_update payloads received within the window."""
        seen: set[str] = set()
        deadline = time.monotonic() + seconds
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            msg = json.loads(raw)
            if msg.get("type") in ("initial_state", "containers_update"):
                data = msg.get("data") or {}
                seen |= {h["id"] for h in data.get("hosts", [])}
                seen |= {c["host_id"] for c in data.get("containers", []) if c.get("host_id")}
        return seen

    async def _ws_checks(self):
        a_id, b_id = self.host_a["id"], self.host_b["id"]
        window = 12.0  # comfortably more than one polling_interval broadcast
        connect = lambda user: websockets.connect(f"{self.ws_base}/ws", additional_headers=self._ws_headers(self.clients[user]),
                                                  ssl=self._ssl(), max_size=None)

        async with connect(USER_A) as ws_a, connect(USER_B) as ws_b, connect(USER_NONE) as ws_none:
            seen_a, seen_b, seen_none = await asyncio.gather(
                self._hosts_seen(ws_a, window), self._hosts_seen(ws_b, window), self._hosts_seen(ws_none, window))
            self.check("tenant-a socket sees host A", a_id in seen_a)
            self.check("tenant-a socket never sees host B", b_id not in seen_a)
            self.check("tenant-b socket sees host B", b_id in seen_b)
            self.check("tenant-b socket never sees host A", a_id not in seen_b)
            self.check("empty-scope socket sees no hosts", not seen_none, f"saw {sorted(seen_none)}")

            # Re-tag host A into tenant B's scope: the open socket must start receiving it
            self.check("admin adds tag B to host A", self._tag_host(a_id, TAG_B))
            seen_b = await self._hosts_seen(ws_b, window)
            self.check("tenant-b socket receives host A after re-tag (no reconnect)", a_id in seen_b)

            self.check("admin removes tag B from host A", self._untag_host(a_id, TAG_B))
            self.tagged.remove((a_id, TAG_B))
            await self._hosts_seen(ws_b, 3.0)  # drain updates already in flight
            seen_b = await self._hosts_seen(ws_b, window)
            self.check("tenant-b socket stops receiving host A after untag", a_id not in seen_b)

            # Membership change: adding the empty-scope user to tenant A refreshes their socket
            resp = self._admin("POST", f"/api/v2/groups/{self.group_ids[GROUP_A]}/members",
                               json={"user_id": self.user_ids[USER_NONE]})
            self.check("admin adds empty-scope user to tenant A", resp.status_code == 200, f"got {resp.status_code}")
            seen_none = await self._hosts_seen(ws_none, window)
            self.check("empty-scope socket receives host A after joining tenant A", a_id in seen_none)
            self.check("empty-scope socket still never sees host B", b_id not in seen_none)

    # ----- teardown -----

    def cleanup(self):
        print(f"\n{BOLD}[CLEANUP]{RESET}")
        if not self.admin:
            return
        for host_id, tag in list(self.tagged):
            print(f"  untag {tag} from {self._short(host_id)}: {'ok' if self._untag_host(host_id, tag) else 'FAILED'}")
        for user, uid in self.user_ids.items():
            resp = self._admin("DELETE", f"/api/v2/users/{uid}")
            print(f"  delete user {user}: {'ok' if resp.status_code == 200 else resp.status_code}")
        for group, gid in self.group_ids.items():
            resp = self._admin("DELETE", f"/api/v2/groups/{gid}")
            print(f"  delete group {group}: {'ok' if resp.status_code == 200 else resp.status_code}")
        for client in list(self.clients.values()) + [self.admin]:
            client.close()

    def summary(self) -> int:
        print(f"\n{BOLD}=== Results: {self.passed} passed, {self.failed} failed ==={RESET}")
        for f in self.failures:
            print(f"  {RED}-{RESET} {f}")
        return 1 if self.failed else 0


def main():
    parser = argparse.ArgumentParser(description="DockMon tag-based host visibility E2E test")
    parser.add_argument("--url", required=True)
    parser.add_argument("--username", "-u")
    parser.add_argument("--password", "-p")
    parser.add_argument("--api-key", help="admin API key (groups/users/hosts/tags manage) instead of a login")
    parser.add_argument("--insecure", action="store_true", help="skip TLS verification")
    parser.add_argument("--host-a", help="host name to scope to tenant A (default: first host)")
    parser.add_argument("--host-b", help="host name to scope to tenant B (default: second host)")
    args = parser.parse_args()
    if not args.api_key and not (args.username and args.password):
        parser.error("give --api-key, or --username and --password")

    tester = HostScopeTester(args.url, args.username, args.password, args.api_key, not args.insecure, args.host_a, args.host_b)
    try:
        if not tester.setup():
            return 2
        tester.run_http_checks()
        tester.run_ws_checks()
    finally:
        tester.cleanup()
    return tester.summary()


if __name__ == "__main__":
    sys.exit(main())
