"""Authentication and access control tests for JSON REST API (spec 007 US5)."""

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from portal.common import ensure_session
from portal.webapp import build_app
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.persistence.schema import connect, init_db

pytestmark = pytest.mark.unit


def _collect_all_routes(router_or_app, prefix=""):
    routes = []
    for r in getattr(router_or_app, "routes", []):
        if hasattr(r, "original_router"):
            sub_prefix = prefix + (getattr(getattr(r, "include_context", None), "prefix", "") or "")
            routes.extend(_collect_all_routes(r.original_router, sub_prefix))
        elif hasattr(r, "router"):
            sub_prefix = prefix + (getattr(r, "prefix", "") or "")
            routes.extend(_collect_all_routes(r.router, sub_prefix))
        elif isinstance(r, APIRoute):
            routes.append((prefix + r.path, r))
    return routes


def test_every_api_route_requires_the_key(app, client: TestClient):
    all_routes = _collect_all_routes(app)
    api_routes = [(p, r) for p, r in all_routes if p.startswith("/api/v1")]
    assert len(api_routes) > 0, f"No /api/v1 routes collected: {[p for p, _ in all_routes]}"

    # 1. Structural check: assert the /api/v1 router includes the auth dependency
    api_router_included = [
        r for r in app.routes
        if getattr(getattr(r, "include_context", None), "prefix", "") == "/api/v1"
    ]
    assert len(api_router_included) > 0
    inc = api_router_included[0]
    dep_names = [d.dependency.__name__ for d in inc.original_router.dependencies]
    assert "require_api_key" in dep_names

    # 2. Behavioral check: calling every single GET/POST /api/v1 route without key returns 401
    for path, route in api_routes:
        # replace {params} with dummy values for testing
        test_path = path.replace("{cycle_id}", "c1").replace("{portal_id}", "p1")
        if "GET" in route.methods:
            res = client.get(test_path)
            assert res.status_code == 401, f"Route {path} GET allowed unauthenticated request!"
        if "POST" in route.methods:
            res = client.post(test_path, json={})
            assert res.status_code == 401, f"Route {path} POST allowed unauthenticated request!"


def test_auth_rejections_and_no_leak(client: TestClient, tmp_path):
    # 1. Missing header -> 401 unauthorized
    res_no_auth = client.get("/api/v1/cycles")
    assert res_no_auth.status_code == 401
    data_no_auth = res_no_auth.json()
    assert data_no_auth["error"]["code"] == "unauthorized"
    assert "error" in data_no_auth

    # 2. Wrong key -> 401 unauthorized
    res_bad_auth = client.get("/api/v1/cycles", headers={"X-API-Key": "wrong-secret-key"})
    assert res_bad_auth.status_code == 401
    data_bad_auth = res_bad_auth.json()
    assert data_bad_auth["error"]["code"] == "unauthorized"

    # 3. Post with wrong key -> 401 unauthorized without side effect
    post_bad = client.post(
        "/api/v1/cycles",
        json={"cycle_id": "secret-cycle", "name": "Secret"},
        headers={"X-API-Key": "wrong"},
    )
    assert post_bad.status_code == 401

    # 4. Unconfigured API access -> 503 not_configured
    db_file = str(tmp_path / "unconfigured.db")
    init_db(db_file)
    settings_no_key = Settings(api_key="", database_path=db_file)
    unconf_app = build_app(db_file, settings_no_key)
    with TestClient(unconf_app) as unconf_client:
        res_unconf = unconf_client.get("/api/v1/cycles", headers={"X-API-Key": "any-key"})
        assert res_unconf.status_code == 503
        data_unconf = res_unconf.json()
        assert data_unconf["error"]["code"] == "not_configured"


def test_portal_operates_with_api_key_unset(tmp_path):
    db_file = str(tmp_path / "portal_only.db")
    init_db(db_file)
    settings_portal_only = Settings(api_key="", database_path=db_file)
    app = build_app(db_file, settings_portal_only)

    conn = connect(db_file)
    repo = Repository(conn)
    session_id = ensure_session(repo, "portal-test-cycle")
    conn.close()

    with TestClient(app) as client:
        # Landing page
        assert client.get("/").status_code == 200
        # Admin picker
        assert client.get("/admin").status_code == 200
        # Assessor picker
        assert client.get("/assessor").status_code == 200
        # Public knowledge base
        assert client.get("/public").status_code == 200
        # Review app mount with active session
        assert client.get(f"/review/?session={session_id}").status_code == 200


def test_secret_never_logged_or_persisted(db_path):
    # Non-empty secret is masked to '***'
    s_set = Settings(api_key="my-super-secret-token", database_path=db_path)
    d_set = s_set.as_dict()
    assert d_set["api_key"] == "***"
    assert "my-super-secret-token" not in str(d_set)

    # Empty secret remains empty string
    s_empty = Settings(api_key="", database_path=db_path)
    d_empty = s_empty.as_dict()
    assert d_empty["api_key"] == ""
