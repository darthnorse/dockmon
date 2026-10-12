"""Outbound HTTP clients honor HTTP(S)_PROXY / NO_PROXY, except loopback-only clients."""

import ast
import asyncio
import json
from pathlib import Path

import pytest

from stats_client import StatsServiceClient
from updates.dockmon_update_checker import DockMonUpdateChecker

BACKEND = Path(__file__).resolve().parents[2]

# aiohttp sessions that must never use a proxy: their target is loopback inside the container.
DIRECT_ONLY = {"stats_client.py"}

PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
              "http_proxy", "https_proxy", "no_proxy", "all_proxy")


def _client_session_calls():
    for path in sorted(BACKEND.rglob("*.py")):
        rel = path.relative_to(BACKEND)
        if rel.parts[0] in ("tests", "venv") or "site-packages" in rel.parts:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "ClientSession"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "aiohttp"):
                yield rel, node


def test_every_aiohttp_session_sets_trust_env_explicitly():
    missing = [f"{rel}:{node.lineno}" for rel, node in _client_session_calls()
               if not any(kw.arg == "trust_env" for kw in node.keywords)]
    assert missing == [], f"aiohttp.ClientSession without explicit trust_env: {missing}"


def test_only_loopback_clients_disable_trust_env():
    calls = list(_client_session_calls())
    assert calls, "AST scan found no aiohttp.ClientSession calls"
    for rel, node in calls:
        kw = next((k for k in node.keywords if k.arg == "trust_env"), None)
        if kw is None:
            continue
        assert isinstance(kw.value, ast.Constant), f"{rel}:{node.lineno} trust_env must be a literal"
        expected = str(rel) not in DIRECT_ONLY
        assert kw.value.value is expected, (
            f"{rel}:{node.lineno} trust_env={kw.value.value}, expected {expected}"
        )


@pytest.fixture
def clean_proxy_env(monkeypatch):
    for var in PROXY_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


@pytest.fixture
async def recording_proxy():
    """Plain-HTTP forward proxy stub: records request lines, answers like the GitHub API."""
    seen = []

    async def handle(reader, writer):
        request_line = (await reader.readline()).decode().strip()
        seen.append(request_line)
        while (await reader.readline()) not in (b"\r\n", b"\n", b""):
            pass
        body = json.dumps({"tag_name": "v9.9.9", "html_url": "http://github.test/r"}).encode()
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                     b"Content-Length: " + str(len(body)).encode() +
                     b"\r\nConnection: close\r\n\r\n" + body)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}", seen
    server.close()
    await server.wait_closed()


@pytest.fixture
def checker(monkeypatch):
    c = DockMonUpdateChecker(db_manager=None)
    monkeypatch.setattr(c, "GITHUB_LATEST_URL", "http://github.invalid/repos/x/releases/latest")
    monkeypatch.setattr(c, "REQUEST_TIMEOUT", 3)
    return c


async def test_update_check_goes_through_proxy(clean_proxy_env, recording_proxy, checker):
    proxy_url, seen = recording_proxy
    clean_proxy_env.setenv("HTTP_PROXY", proxy_url)

    version, _ = await checker._fetch_latest_release()

    assert version == "9.9.9"
    assert seen == ["GET http://github.invalid/repos/x/releases/latest HTTP/1.1"]


async def test_update_check_respects_no_proxy(clean_proxy_env, recording_proxy, checker):
    proxy_url, seen = recording_proxy
    clean_proxy_env.setenv("HTTP_PROXY", proxy_url)
    clean_proxy_env.setenv("NO_PROXY", "github.invalid")

    version, _ = await checker._fetch_latest_release()

    assert version is None
    assert seen == []


async def test_stats_service_session_never_uses_proxy(clean_proxy_env, monkeypatch):
    clean_proxy_env.setenv("HTTP_PROXY", "http://192.0.2.1:3128")
    client = StatsServiceClient()

    async def fake_token():
        return "t"

    monkeypatch.setattr(client, "_load_token", fake_token)
    session = await client._get_session()
    try:
        assert session.trust_env is False
    finally:
        await session.close()
