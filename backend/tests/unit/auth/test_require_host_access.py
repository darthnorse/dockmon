"""require_host_access: 404 (never 403) for hosts outside the caller's tag scope.

Listed AFTER require_capability in dependencies=[...] so a caller lacking the
capability gets 403 for every host, hidden or not - the status code must not
reveal whether a host id exists.
"""

import logging

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import auth.api_key_auth as api_key_auth
from auth.api_key_auth import (
    get_current_user_or_api_key,
    require_capability,
    require_host_access,
    require_source_host_access,
)

SESSION_USER = {"auth_type": "session", "user_id": 7, "username": "alice"}
API_KEY_USER = {"auth_type": "api_key", "api_key_id": 3, "api_key_name": "ci", "group_id": 9}


def _app(current_user: dict) -> TestClient:
    app = FastAPI()

    @app.get("/hosts/{host_id}", dependencies=[Depends(require_host_access)])
    async def host_route(host_id: str):
        return {"host_id": host_id}

    @app.get("/migrate/{agent_id}/from/{source_host_id}", dependencies=[Depends(require_source_host_access)])
    async def source_route(agent_id: str, source_host_id: str):
        return {"source_host_id": source_host_id}

    @app.post("/deploy/{id}", dependencies=[Depends(require_host_access)])
    async def miswired_route(id: str):
        return {"id": id}

    @app.get(
        "/guarded/{host_id}",
        dependencies=[Depends(require_capability("hosts.view")), Depends(require_host_access)],
    )
    async def guarded_route(host_id: str):
        return {"host_id": host_id}

    app.dependency_overrides[get_current_user_or_api_key] = lambda: current_user
    return TestClient(app)


@pytest.fixture
def resolver(monkeypatch):
    calls = []

    def set_visible(value):
        def fake(current_user):
            calls.append(current_user)
            return value
        monkeypatch.setattr(api_key_auth, "get_visible_host_ids_for_auth", fake)
        return calls

    return set_visible


class TestRequireHostAccess:
    def test_unrestricted_caller_passes(self, resolver):
        resolver(None)
        assert _app(SESSION_USER).get("/hosts/h1").status_code == 200

    def test_scoped_caller_with_match_passes(self, resolver):
        resolver({"h1", "h2"})
        assert _app(SESSION_USER).get("/hosts/h1").status_code == 200

    def test_scoped_caller_without_match_gets_404(self, resolver):
        resolver({"h2"})
        response = _app(SESSION_USER).get("/hosts/h1")
        assert response.status_code == 404
        assert response.json() == {"detail": "Host not found"}

    def test_orphan_caller_gets_404(self, resolver):
        resolver(set())
        assert _app(SESSION_USER).get("/hosts/h1").status_code == 404

    def test_api_key_dict_is_passed_through_unchanged(self, resolver):
        calls = resolver({"h1"})
        assert _app(API_KEY_USER).get("/hosts/h1").status_code == 200
        assert calls == [API_KEY_USER]

    def test_source_host_variant_reads_source_host_id(self, resolver):
        resolver({"src-visible"})
        client = _app(SESSION_USER)
        assert client.get("/migrate/agent-1/from/src-visible").status_code == 200
        assert client.get("/migrate/agent-1/from/src-hidden").status_code == 404


class TestGuardOrder:
    def test_missing_capability_yields_403_even_for_hidden_host(self, resolver, monkeypatch):
        resolver(set())
        monkeypatch.setattr(api_key_auth, "check_auth_capability", lambda user, cap: False)
        assert _app(SESSION_USER).get("/guarded/hidden").status_code == 403

    def test_capability_holder_gets_404_for_hidden_host(self, resolver, monkeypatch):
        resolver(set())
        monkeypatch.setattr(api_key_auth, "check_auth_capability", lambda user, cap: True)
        assert _app(SESSION_USER).get("/guarded/hidden").status_code == 404


class TestFailClosedBinding:
    def test_route_without_host_id_path_param_rejects_query_value(self, resolver):
        """A guard on a mis-wired route must not read ?host_id= from the query string,
        or a scoped caller could name any visible host to act on a hidden one."""
        resolver({"visible"})
        client = _app(SESSION_USER)
        assert client.post("/deploy/hidden").status_code == 422
        assert client.post("/deploy/hidden?host_id=visible").status_code == 422

    def test_correctly_wired_route_ignores_query_override(self, resolver):
        resolver({"visible"})
        assert _app(SESSION_USER).get("/hosts/hidden?host_id=visible").status_code == 404


class TestDenialLog:
    def test_host_id_cannot_forge_a_log_line(self, resolver, caplog):
        resolver(set())
        with caplog.at_level(logging.INFO, logger="auth.api_key_auth"):
            assert _app(SESSION_USER).get("/hosts/x%0AINFO%20forged%20line").status_code == 404
        messages = [r.getMessage() for r in caplog.records if "denied host scope" in r.getMessage()]
        assert len(messages) == 1
        assert "\n" not in messages[0]
        assert "'x\\nINFO forged line'" in messages[0]


def test_hidden_host_message_matches_unknown_host_message():
    """A scoped caller must not be able to tell 'exists but hidden' from 'does not exist'."""
    import re
    from pathlib import Path
    main_src = Path(__file__).resolve().parents[3].joinpath("main.py").read_text()
    unknown_messages = set(re.findall(r'status_code=404, detail="(Host not found)"', main_src))
    assert unknown_messages == {"Host not found"}
    from auth import api_key_auth
    assert 'detail="Host not found"' in Path(api_key_auth.__file__).read_text()
    assert 'detail="Not found"' not in Path(api_key_auth.__file__).read_text()
